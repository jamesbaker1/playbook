"""Convert a Playbook episode trace into a simple chat-format SFT JSONL record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def convert(trace: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a legal agent operating in the Playbook environment. Choose one valid "
                "structured action at a time and ground all conclusions in visible matter content."
            ),
        }
    ]
    for event in trace["events"]:
        observation = json.dumps(event["observation"], ensure_ascii=False)
        action = json.dumps(event["action"], ensure_ascii=False)
        messages.append({"role": "user", "content": observation})
        messages.append({"role": "assistant", "content": action})
    return {
        "matter_id": trace["matter"],
        "score": trace["result"]["normalized_score"],
        "messages": messages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    record = convert(trace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
