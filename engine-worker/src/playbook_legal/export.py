# SPDX-License-Identifier: AGPL-3.0-only

"""Convert Playbook episode traces into chat-format SFT JSONL records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = (
    "You are a legal agent operating in the Playbook environment. Choose one valid "
    "structured action at a time and ground all conclusions in visible matter content."
)


def convert(trace: dict[str, Any], *, agent: str = "scripted") -> dict[str, Any]:
    """Convert one trace into a chat record. ``agent`` tags the trajectory source

    (e.g. ``scripted``, ``model:<name>``, ``human``) so mixed datasets stay separable.
    """
    events = trace["events"]
    if "initial_observation" not in trace:
        raise ValueError(
            "trace has no initial_observation; regenerate it before export to avoid "
            "training on a post-action observation"
        )
    observation = trace["initial_observation"]

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(observation, ensure_ascii=False)},
    ]
    for event in events:
        action = json.dumps(event["action"], ensure_ascii=False)
        messages.append({"role": "assistant", "content": action})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(event["observation"], ensure_ascii=False),
            }
        )
    return {
        "matter_id": trace["matter"],
        "agent": agent,
        "score": trace["result"]["normalized_score"],
        "critical_failure": trace["result"]["critical_failure"],
        "messages": messages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--agent", default="scripted", help="Trajectory source tag")
    args = parser.parse_args()
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    record = convert(trace, agent=args.agent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
