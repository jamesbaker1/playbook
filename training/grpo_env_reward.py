# SPDX-License-Identifier: AGPL-3.0-only

"""GRPO with the environment-owned episode reward.

Prompt-only dataset: each row is the matter's initial observation plus a matter
identifier. A completion is a full action script — one JSON action per line. The
reward function instantiates a FRESH environment per completion, executes the
parsed actions, and returns ``normalized_score`` (with a critical failure the cap
applies automatically, so fabrication is punished by construction).

Run ONLY after the adversarial reward tests pass (`pytest tests/test_adversarial.py`).
Heavy imports live inside ``train`` so importing this module never requires torch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playbook_legal.baseline import SYSTEM_PROMPT
from playbook_legal.env import PlaybookEnv
from playbook_legal.lint import discover_matter_dirs

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def build_prompt_dataset(matters_root: Path) -> list[dict]:
    rows = []
    for matter_dir in discover_matter_dirs(matters_root):
        env = PlaybookEnv.from_directory(matter_dir)
        observation, _ = env.reset(seed=0)
        rows.append(
            {
                "prompt": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(observation, ensure_ascii=False)
                        + "\n\nEmit your COMPLETE action sequence for this matter, one JSON "
                        "action per line, ending with a submit_final action.",
                    },
                ],
                "matter_dir": str(matter_dir),
            }
        )
    return rows


def parse_actions(completion: str) -> list[dict]:
    actions = []
    for line in completion.splitlines():
        line = line.strip().strip("`")
        if not line.startswith("{"):
            continue
        try:
            action = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(action, dict) and "type" in action:
            actions.append(action)
    return actions


def episode_reward(completion: str, matter_dir: str) -> float:
    env = PlaybookEnv.from_directory(matter_dir)
    env.reset(seed=0)
    actions = parse_actions(completion)
    if not actions:
        return 0.0
    for action in actions:
        try:
            _, _, terminated, truncated, _ = env.step(action)
        except RuntimeError:
            break
        if terminated or truncated:
            break
    return float(env.episode_result()["normalized_score"])


def reward_environment_score(completions, matter_dir=None, **kwargs) -> list[float]:
    """TRL GRPO reward hook: one fresh environment per completion."""
    rewards = []
    for completion, directory in zip(completions, matter_dir):
        text = completion if isinstance(completion, str) else completion[-1]["content"]
        rewards.append(episode_reward(text, directory))
    return rewards


def train(
    matters_root: Path,
    output_dir: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    num_generations: int = 8,
    learning_rate: float = 1e-6,
    max_steps: int = 200,
) -> None:
    from datasets import Dataset
    from peft import LoraConfig
    from trl import GRPOConfig, GRPOTrainer

    dataset = Dataset.from_list(build_prompt_dataset(matters_root))
    print(f"GRPO over {len(dataset)} matter prompts")

    trainer = GRPOTrainer(
        model=model_name,
        train_dataset=dataset,
        reward_funcs=reward_environment_score,
        peft_config=LoraConfig(
            r=16,
            lora_alpha=32,
            lora_dropout=0.05,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
        args=GRPOConfig(
            output_dir=str(output_dir),
            num_generations=num_generations,
            learning_rate=learning_rate,
            max_steps=max_steps,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            logging_steps=1,
            bf16=True,
            report_to="none",
        ),
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    print(f"Adapter saved to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/grpo_adapter"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--num-generations", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-6)
    parser.add_argument("--max-steps", type=int, default=200)
    args = parser.parse_args()
    train(
        args.matters,
        args.output_dir,
        model_name=args.model,
        num_generations=args.num_generations,
        learning_rate=args.learning_rate,
        max_steps=args.max_steps,
    )


if __name__ == "__main__":
    main()
