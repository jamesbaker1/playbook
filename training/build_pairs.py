"""Build DPO chosen/rejected pairs from scored rollouts.

Pairs are formed within a matter: the highest-scoring critical-free rollout is
"chosen"; any rollout at least ``--margin`` below it (or with a critical failure)
is "rejected". The prompt is the shared prefix (system + initial observation);
chosen/rejected are the full action transcripts.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def transcript(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages if m["role"] == "assistant")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollouts", type=Path, default=Path("artifacts/rollouts"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/dpo_pairs.jsonl"))
    parser.add_argument("--margin", type=float, default=0.15)
    args = parser.parse_args()

    index = json.loads((args.rollouts / "index.json").read_text(encoding="utf-8"))
    by_matter: dict[str, list[dict]] = defaultdict(list)
    for row in index:
        by_matter[row["matter_id"]].append(row)

    pairs = []
    for matter_id, rows in sorted(by_matter.items()):
        clean = [r for r in rows if not r["critical_failure"]]
        if not clean:
            continue
        best = max(clean, key=lambda r: r["normalized_score"])
        best_chat = json.loads(
            (args.rollouts / f"{matter_id}_r{best['rollout']}.chat.json").read_text(
                encoding="utf-8"
            )
        )
        for row in rows:
            if row is best:
                continue
            worse_enough = (
                best["normalized_score"] - row["normalized_score"] >= args.margin
                or row["critical_failure"]
            )
            if not worse_enough:
                continue
            other_chat = json.loads(
                (args.rollouts / f"{matter_id}_r{row['rollout']}.chat.json").read_text(
                    encoding="utf-8"
                )
            )
            pairs.append(
                {
                    "matter_id": matter_id,
                    "prompt": json.dumps(best_chat["messages"][:2], ensure_ascii=False),
                    "chosen": transcript(best_chat["messages"]),
                    "rejected": transcript(other_chat["messages"]),
                    "chosen_score": best["normalized_score"],
                    "rejected_score": row["normalized_score"],
                    "rejected_critical": row["critical_failure"],
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(f"Wrote {len(pairs)} pairs to {args.out}")


if __name__ == "__main__":
    main()
