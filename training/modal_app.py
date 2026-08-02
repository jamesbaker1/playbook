# SPDX-License-Identifier: AGPL-3.0-only

"""Modal app wrapping the training scaffolds. NOTHING here runs automatically.

Setup (one time):
    pip install modal && modal setup
    modal volume create playbook-artifacts

Upload data, then launch a job explicitly, e.g.:
    modal volume put playbook-artifacts artifacts/sft_data.jsonl /data/sft_data.jsonl
    modal run training/modal_app.py::sft --data /vol/data/sft_data.jsonl

Every function writes adapters to the shared volume under /vol/outputs/.
GPU sizing: A10G handles 7B-8B LoRA SFT/DPO; GRPO generation is heavier — use A100.
"""

from __future__ import annotations

from pathlib import Path

import modal

app = modal.App("playbook-training")

volume = modal.Volume.from_name("playbook-artifacts", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch>=2.4",
        "transformers>=4.50",
        "datasets>=3",
        "trl>=0.17",
        "peft>=0.14",
        "accelerate>=1.2",
        "PyYAML>=6.0",
    )
    .add_local_dir(str(Path(__file__).resolve().parents[1] / "src"), remote_path="/repo/src")
    .add_local_dir(str(Path(__file__).resolve().parents[1] / "matters"), remote_path="/repo/matters")
    .add_local_dir(str(Path(__file__).resolve().parent), remote_path="/repo/training")
)


def _prepare_path() -> None:
    import sys

    sys.path.insert(0, "/repo/src")
    sys.path.insert(0, "/repo/training")


@app.function(image=image, gpu="A10G", timeout=6 * 60 * 60, volumes={"/vol": volume})
def sft(data: str = "/vol/data/sft_data.jsonl", output: str = "/vol/outputs/sft_adapter") -> None:
    _prepare_path()
    from sft_lora import train

    train(Path(data), Path(output))
    volume.commit()


@app.function(image=image, gpu="A10G", timeout=6 * 60 * 60, volumes={"/vol": volume})
def dpo(pairs: str = "/vol/data/dpo_pairs.jsonl", output: str = "/vol/outputs/dpo_adapter") -> None:
    _prepare_path()
    from dpo_lora import train

    train(Path(pairs), Path(output))
    volume.commit()


@app.function(image=image, gpu="A100", timeout=12 * 60 * 60, volumes={"/vol": volume})
def grpo(matters: str = "/repo/matters", output: str = "/vol/outputs/grpo_adapter") -> None:
    _prepare_path()
    from grpo_env_reward import train

    train(Path(matters), Path(output))
    volume.commit()
