# SPDX-License-Identifier: AGPL-3.0-only

"""Create a run plan or calculate paired LAB/Playbook score deltas.

No provider calls are made here. This keeps model runs subject to the project's
explicit budget-approval gate and prevents placeholders being mistaken for results.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def mapping_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def emit_plan(rows: list[dict[str, str]], models: list[str], output: Path, harvey_repo: Path | None = None) -> None:
    plan = []
    for model in models:
        for row in rows:
            run_slug = row["lab_task_id"].replace("/", "__")
            plan.append(
                {
                    "model": model,
                    "lab_task_id": row["lab_task_id"],
                    "playbook_matter": row["playbook_matter"],
                    "lab_command": (
                        "uv run python -m harness.run "
                        f"--model {model} --task {row['lab_task_id']}"
                    ),
                    "playbook_command": (
                        "python experiments/harvey_lab_delta/adapter.py "
                        f"--harvey-repo {harvey_repo or '<HARVEY_REPO>'} --task {row['lab_task_id']} "
                        f"--actions artifacts/harvey_lab_delta/actions/{model}/{run_slug}.jsonl "
                        f"--trace artifacts/harvey_lab_delta/runs/{model}/{run_slug}.json"
                    ),
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(plan)} paired run specifications to {output}")


def execute_plan(path: Path, *, approve_provider_spend: bool) -> None:
    if not approve_provider_spend:
        raise SystemExit("execution requires --approve-provider-spend")
    plan = json.loads(path.read_text(encoding="utf-8"))
    for pair in plan:
        for form in ("lab", "playbook"):
            command = pair[f"{form}_command"]
            result = subprocess.run(command, shell=True, check=False)
            if result.returncode:
                raise SystemExit(f"{form} command failed ({result.returncode}): {command}")


def report(rows: list[dict[str, str]], lab_path: Path, playbook_path: Path, output: Path) -> None:
    lab = {(r["model"], r["task_id"]): float(r["score"]) for r in read_jsonl(lab_path)}
    playbook = {
        (r["model"], r["task_id"]): float(r["score"]) for r in read_jsonl(playbook_path)
    }
    paired: dict[str, list[tuple[float, float]]] = defaultdict(list)
    missing = []
    for row in rows:
        models = {model for model, task in lab if task == row["lab_task_id"]}
        for model in models:
            left = lab.get((model, row["lab_task_id"]))
            right = playbook.get((model, row["lab_task_id"]))
            if left is None or right is None:
                missing.append(f"{model}: {row['lab_task_id']}")
            else:
                paired[model].append((left, right))
    if missing:
        raise SystemExit("Missing paired observations:\n" + "\n".join(missing))
    if not paired:
        raise SystemExit("No paired observations found")

    lines = [
        "# Harvey LAB / Playbook paired delta results",
        "",
        "> Generated only from the supplied run records; no missing values are imputed.",
        "",
        "| Model | Pairs | LAB mean | Playbook mean | Delta (Playbook - LAB) |",
        "|---|---:|---:|---:|---:|",
    ]
    for model, values in sorted(paired.items()):
        lab_mean = statistics.fmean(v[0] for v in values)
        pb_mean = statistics.fmean(v[1] for v in values)
        lines.append(f"| {model} | {len(values)} | {lab_mean:.4f} | {pb_mean:.4f} | {pb_mean-lab_mean:+.4f} |")
    lines += [
        "",
        "## Interpretation guardrails",
        "",
        "LAB uses all-pass rubric scores while Playbook uses normalized environment reward; the delta is descriptive, not a claim that the scales are psychometrically equivalent. LAB has been public since May 2026, so memorization or benchmark-specific tuning can inflate LAB performance. Report model identifiers, dates, prompts, seeds, failures, and every excluded pair.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote measured report to {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=HERE / "generated" / "mapping.csv")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--emit-plan", type=Path)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--approve-provider-spend", action="store_true")
    parser.add_argument("--harvey-repo", type=Path)
    parser.add_argument("--lab-results", type=Path)
    parser.add_argument("--playbook-results", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = mapping_rows(args.mapping)
    if args.emit_plan:
        if not args.models:
            parser.error("--emit-plan requires --models")
        emit_plan(rows, args.models, args.emit_plan, args.harvey_repo)
        return
    if args.execute_plan:
        execute_plan(args.execute_plan, approve_provider_spend=args.approve_provider_spend)
        return
    if not (args.lab_results and args.playbook_results and args.report):
        parser.error("provide --emit-plan, or both result files and --report")
    report(rows, args.lab_results, args.playbook_results, args.report)


if __name__ == "__main__":
    main()
