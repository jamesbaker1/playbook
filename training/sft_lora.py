"""LoRA supervised fine-tuning on exported Playbook chat trajectories.

Designed to run on a GPU box or Modal (see ``modal_app.py``); heavy imports live
inside ``train`` so importing this module never requires torch.

Input: JSONL where each line is an export.py chat record
(``{"matter_id", "agent", "score", "critical_failure", "messages": [...]}``).
Rows with critical failures or scores below ``--min-score`` are dropped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def load_records(path: Path, min_score: float) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("critical_failure"):
            continue
        if float(record.get("score", 0.0)) < min_score:
            continue
        records.append({"messages": record["messages"]})
    return records


def train(
    data: Path,
    output_dir: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    min_score: float = 0.6,
    epochs: float = 2.0,
    learning_rate: float = 1e-4,
    lora_r: int = 16,
    lora_alpha: int = 32,
    max_seq_length: int = 8192,
) -> None:
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    records = load_records(data, min_score)
    if not records:
        raise SystemExit(f"No qualifying records in {data}")
    dataset = Dataset.from_list(records)
    print(f"Training on {len(dataset)} trajectories from {data}")

    trainer = SFTTrainer(
        model=model_name,
        train_dataset=dataset,
        peft_config=LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=0.05,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
        args=SFTConfig(
            output_dir=str(output_dir),
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            max_length=max_seq_length,
            logging_steps=5,
            save_strategy="epoch",
            bf16=True,
            report_to="none",
        ),
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    print(f"Adapter saved to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="JSONL of exported chat trajectories")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--min-score", type=float, default=0.6)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--max-seq-length", type=int, default=8192)
    args = parser.parse_args()
    train(
        args.data,
        args.output_dir,
        model_name=args.model,
        min_score=args.min_score,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        max_seq_length=args.max_seq_length,
    )


if __name__ == "__main__":
    main()
