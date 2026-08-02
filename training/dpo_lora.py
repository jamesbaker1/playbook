"""LoRA DPO training on chosen/rejected pairs built by ``build_pairs.py``.

Heavy imports live inside ``train`` so importing this module never requires torch.
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def train(
    pairs: Path,
    output_dir: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    beta: float = 0.1,
    epochs: float = 1.0,
    learning_rate: float = 5e-6,
    lora_r: int = 16,
    lora_alpha: int = 32,
) -> None:
    from datasets import load_dataset
    from peft import LoraConfig
    from trl import DPOConfig, DPOTrainer

    dataset = load_dataset("json", data_files=str(pairs), split="train")
    dataset = dataset.select_columns(["prompt", "chosen", "rejected"])
    print(f"Training on {len(dataset)} preference pairs from {pairs}")

    trainer = DPOTrainer(
        model=model_name,
        train_dataset=dataset,
        peft_config=LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=0.05,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
        args=DPOConfig(
            output_dir=str(output_dir),
            beta=beta,
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
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
    parser.add_argument("pairs", type=Path, help="JSONL from build_pairs.py")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=5e-6)
    args = parser.parse_args()
    train(
        args.pairs,
        args.output_dir,
        model_name=args.model,
        beta=args.beta,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
    )


if __name__ == "__main__":
    main()
