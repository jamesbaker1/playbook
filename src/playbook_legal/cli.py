from __future__ import annotations

import argparse
import json
from pathlib import Path

from .env import PlaybookEnv


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a Playbook action JSONL file.")
    parser.add_argument("matter", type=Path, help="Path to a matter directory")
    parser.add_argument("actions", type=Path, help="JSONL file containing one action per line")
    parser.add_argument("--trace", type=Path, default=Path("artifacts/replay_trace.json"))
    args = parser.parse_args()

    env = PlaybookEnv.from_directory(args.matter)
    env.reset(seed=0)
    for line_number, line in enumerate(args.actions.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        action = json.loads(line)
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    path = env.save_trace(args.trace)
    print(json.dumps(env.episode_result(), indent=2))
    print(f"Trace: {path}")


if __name__ == "__main__":
    main()
