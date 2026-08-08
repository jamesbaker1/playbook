# SPDX-License-Identifier: AGPL-3.0-only

"""Generate scored rollouts from an OpenAI-compatible model for SFT/DPO data.

Runs the baseline agent N times per matter (varying seed/temperature), saves every
trace, and writes an index of scores. Downstream: keep high-scoring critical-free
trajectories for SFT (``export_dataset.py`` step) and build chosen/rejected pairs
(``build_pairs.py``). API-only — no local GPU or torch required.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playbook_legal.baseline import build_client, run_episode
from playbook_legal.env import PlaybookEnv
from playbook_legal.export import convert
from playbook_legal.lint import discover_matter_dirs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/rollouts"))
    parser.add_argument("--model", default=os.environ.get("PLAYBOOK_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PLAYBOOK_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
    )
    parser.add_argument("--rollouts-per-matter", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--system-prompt-file",
        type=Path,
        help="UTF-8 file whose text replaces the baseline system prompt for every episode",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Per-completion output cap; metered gateways pre-authorize the model's "
        "full output window per request when unset",
    )
    parser.add_argument(
        "--variant",
        action="append",
        dest="variants",
        metavar="MATTER_ID",
        help="Restrict the sweep to this matter directory name; repeatable",
    )
    args = parser.parse_args()

    system_prompt = (
        args.system_prompt_file.read_text(encoding="utf-8")
        if args.system_prompt_file is not None
        else None
    )
    matter_dirs = discover_matter_dirs(args.matters)
    if args.variants:
        wanted = set(args.variants)
        matter_dirs = [matter_dir for matter_dir in matter_dirs if matter_dir.name in wanted]
        missing = sorted(wanted - {matter_dir.name for matter_dir in matter_dirs})
        if missing:
            raise SystemExit(f"No matter under {args.matters} named: {', '.join(missing)}")
    if not matter_dirs:
        raise SystemExit(f"No matters found under {args.matters}")

    client = build_client(args.base_url, os.environ.get("OPENAI_API_KEY"))
    args.out.mkdir(parents=True, exist_ok=True)
    index = []
    for matter_dir in matter_dirs:
        for rollout in range(args.rollouts_per_matter):
            stem = f"{matter_dir.name}_r{rollout}"
            trace_path = args.out / f"{stem}.json"
            record_path = args.out / f"{stem}.result.json"
            # Live runs bill per episode whether or not the sweep finishes, so each
            # episode is checkpointed beside its trace the moment it completes and an
            # interrupted sweep reuses that record instead of repaying for the call.
            if trace_path.exists() and record_path.exists():
                index.append(json.loads(record_path.read_text(encoding="utf-8")))
                print(f"{matter_dir.name} r{rollout}: resumed from {record_path.name}")
                continue
            env = PlaybookEnv.from_directory(matter_dir)
            result = run_episode(
                env,
                client,
                model=args.model,
                seed=rollout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                system_prompt=system_prompt,
            )
            env.save_trace(trace_path)
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            record = convert(trace, agent=f"model:{args.model}")
            (args.out / f"{stem}.chat.json").write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8"
            )
            entry = {
                "matter_id": matter_dir.name,
                "rollout": rollout,
                "trace": trace_path.name,
                "normalized_score": result["normalized_score"],
                "critical_failure": result["critical_failure"],
                "protocol_failures": result.get("protocol_failures", 0),
            }
            record_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
            index.append(entry)
            print(
                f"{matter_dir.name} r{rollout}: score={result['normalized_score']:.3f} "
                f"critical={result['critical_failure']}"
            )
    (args.out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Wrote {len(index)} rollouts to {args.out}")


if __name__ == "__main__":
    main()
