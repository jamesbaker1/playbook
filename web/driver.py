"""Pyodide-side driver for the Playbook web gym.

Runs inside the browser's Python runtime. The JS layer talks to these functions
with JSON strings only, so no proxy lifetimes to manage. The environment here is
the same package the trainers and the benchmark use — nothing is reimplemented.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from playbook_legal.env import PlaybookEnv
from playbook_legal.loaders import load_yaml

# Overridable so the bundle can be smoke-tested outside the browser.
MATTERS_ROOT = Path(os.environ.get("PLAYBOOK_WEB_MATTERS", "/site/matters"))

_env: PlaybookEnv | None = None


def list_matters() -> str:
    rows = []
    for matter_yaml in sorted(MATTERS_ROOT.glob("*/matter.yaml")):
        matter = load_yaml(matter_yaml)
        rows.append(
            {
                "id": matter["matter_id"],
                "title": matter["title"],
                "practice_area": matter.get("practice_area", ""),
                "role": matter.get("role", ""),
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def start(matter_id: str, seed: int = 0) -> str:
    global _env
    _env = PlaybookEnv.from_directory(MATTERS_ROOT / matter_id)
    observation, info = _env.reset(seed=int(seed))
    return json.dumps({"observation": observation, "info": info}, ensure_ascii=False)


def step(action_json: str) -> str:
    if _env is None:
        raise RuntimeError("start() first")
    action = json.loads(action_json)
    observation, reward, terminated, truncated, _info = _env.step(action)
    payload = {
        "observation": observation,
        "reward": reward,
        "terminated": terminated,
        "truncated": truncated,
    }
    if terminated or truncated:
        payload["result"] = _env.episode_result()
    return json.dumps(payload, ensure_ascii=False)


def trace() -> str:
    if _env is None:
        raise RuntimeError("start() first")
    return json.dumps(
        {
            "matter": _env.matter["matter_id"],
            "events": [
                {
                    "step": event.step,
                    "action": event.action,
                    "observation": event.observation,
                    "reward": event.reward,
                    "terminated": event.terminated,
                    "truncated": event.truncated,
                    "info": event.info,
                }
                for event in _env.trace
            ],
            "result": _env.episode_result(),
        },
        ensure_ascii=False,
        indent=2,
    )
