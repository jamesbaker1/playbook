from __future__ import annotations

import json
from pathlib import Path

import pytest

from playbook_legal import PlaybookEnv

ROOT = Path(__file__).resolve().parents[1]
MATTERS = ROOT / "matters"
EXAMPLES = ROOT / "examples"


def replay(matter_dir: Path, actions_path: Path, *, seed: int = 0) -> dict:
    """Replay a JSONL action file against a matter and return the episode result."""
    env = PlaybookEnv.from_directory(matter_dir)
    env.reset(seed=seed)
    for line in actions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, _, terminated, truncated, _ = env.step(json.loads(line))
        if terminated or truncated:
            break
    return env.episode_result()


@pytest.fixture()
def ai_saas_env() -> PlaybookEnv:
    env = PlaybookEnv.from_directory(MATTERS / "ai_saas_001")
    env.reset(seed=1)
    return env
