"""Benchmark harness: score a runner across many matters and emit a scorecard.

Runners:
- ``replay``: replays each matter's reference trajectory (``examples/<id>/good.jsonl``)
  — the deterministic ceiling reference for the scorecard format.
- ``baseline``: runs a live OpenAI-compatible model via :mod:`playbook_legal.baseline`.

Outputs ``<out>.json`` (full per-episode metrics plus aggregate) and ``<out>.md``
(a readable table).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .env import PlaybookEnv
from .lint import discover_matter_dirs
from .loaders import load_yaml
from .metrics import aggregate_metrics, compute_metrics

_COLUMNS = [
    ("matter_id", "Matter"),
    ("normalized_score", "Score"),
    ("issue_recall", "Issue recall"),
    ("question_recall", "Question recall"),
    ("citation_validity", "Citation validity"),
    ("redline_completion", "Redlines"),
    ("unsupported_issue_count", "Unsupported"),
    ("critical_failure", "Critical"),
    ("steps", "Steps"),
]


def run_replay(matter_dir: Path, examples_root: Path, seed: int) -> dict[str, Any] | None:
    actions_path = examples_root / matter_dir.name / "good.jsonl"
    if not actions_path.exists():
        return None
    env = PlaybookEnv.from_directory(matter_dir)
    env.reset(seed=seed)
    for line in actions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, _, terminated, truncated, _ = env.step(json.loads(line))
        if terminated or truncated:
            break
    return env.episode_result()


def run_baseline(matter_dir: Path, seed: int, args: argparse.Namespace) -> dict[str, Any]:
    from .baseline import build_client, run_episode

    client = build_client(args.base_url, os.environ.get("OPENAI_API_KEY"))
    env = PlaybookEnv.from_directory(matter_dir)
    return run_episode(env, client, model=args.model, seed=seed, temperature=args.temperature)


def to_markdown(rows: list[dict[str, Any]], aggregate: dict[str, Any], title: str) -> str:
    def fmt(value: Any) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    header = "| " + " | ".join(label for _, label in _COLUMNS) + " |"
    divider = "|" + "|".join(" --- " for _ in _COLUMNS) + "|"
    lines = [f"# {title}", "", header, divider]
    for row in rows:
        lines.append("| " + " | ".join(fmt(row.get(key, "")) for key, _ in _COLUMNS) + " |")
    lines += [
        "",
        "## Aggregate",
        "",
        "```json",
        json.dumps(aggregate, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Playbook benchmark scorecard.")
    parser.add_argument("--matters", type=Path, default=Path("matters"), help="Matter root directory")
    parser.add_argument("--examples", type=Path, default=Path("examples"))
    parser.add_argument("--runner", choices=["replay", "baseline"], default="replay")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--model", default=os.environ.get("PLAYBOOK_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PLAYBOOK_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--out", type=Path, default=Path("artifacts/scorecard"))
    args = parser.parse_args()

    matter_dirs = discover_matter_dirs(args.matters)
    if not matter_dirs:
        raise SystemExit(f"No matters found under {args.matters}")

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for matter_dir in matter_dirs:
        rubric = load_yaml(matter_dir / "rubric.yaml")
        counterparty_path = matter_dir / "counterparty.yaml"
        counterparty = load_yaml(counterparty_path) if counterparty_path.exists() else {}
        for seed in args.seeds:
            if args.runner == "replay":
                result = run_replay(matter_dir, args.examples, seed)
                if result is None:
                    skipped.append(matter_dir.name)
                    break
            else:
                result = run_baseline(matter_dir, seed, args)
            metrics = compute_metrics(result, rubric, counterparty)
            metrics["seed"] = seed
            rows.append(metrics)

    aggregate = aggregate_metrics(rows)
    label = args.model if args.runner == "baseline" else "reference replay"
    payload = {
        "runner": args.runner,
        "label": label,
        "episodes": rows,
        "aggregate": aggregate,
        "skipped": skipped,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(rows, aggregate, f"Playbook scorecard — {label}"), encoding="utf-8")
    if skipped:
        print(f"Skipped (no reference trajectory): {', '.join(skipped)}")
    print(json.dumps(aggregate, indent=2))
    print(f"Scorecard: {json_path} and {md_path}")


if __name__ == "__main__":
    main()
