# SPDX-License-Identifier: AGPL-3.0-only

"""Benchmark harness: score a runner across many matters and emit a scorecard.

Runners:
- ``replay``: replays each matter's reference trajectory (``examples/<id>/good.jsonl``)
  — the deterministic ceiling reference for the scorecard format.
- ``baseline``: runs a live OpenAI-compatible model via :mod:`playbook_legal.baseline`.

Outputs ``<out>.json`` (full per-episode metrics plus aggregate) and ``<out>.md``
(a readable table). With ``--save-traces`` each episode's replayable trace is also
written to ``<out>/traces/<matter>-seed<seed>.trace.json`` so every published row
can be re-scored from the trace instead of being taken on trust.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .dataset import load_family_registry
from .env import PlaybookEnv
from .lint import discover_matter_dirs
from .loaders import load_yaml
from .metrics import aggregate_metrics, cluster_bootstrap_interval, compute_metrics

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


def run_replay(
    matter_dir: Path,
    examples_root: Path,
    seed: int,
    *,
    trace_path: Path | None = None,
) -> dict[str, Any] | None:
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
    if trace_path is not None:
        env.save_trace(trace_path)
    return env.episode_result()


def run_baseline(
    matter_dir: Path,
    seed: int,
    args: argparse.Namespace,
    *,
    trace_path: Path | None = None,
) -> dict[str, Any]:
    from .baseline import build_client, run_episode

    client = build_client(args.base_url, os.environ.get("OPENAI_API_KEY"))
    env = PlaybookEnv.from_directory(matter_dir)
    result = run_episode(
        env,
        client,
        model=args.model,
        seed=seed,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    if trace_path is not None:
        env.save_trace(trace_path)
    return result


def to_markdown(
    rows: list[dict[str, Any]], aggregate: dict[str, Any], title: str, split: str
) -> str:
    def fmt(value: Any) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    header = "| " + " | ".join(label for _, label in _COLUMNS) + " |"
    divider = "|" + "|".join(" --- " for _ in _COLUMNS) + "|"
    lines = [f"# {title}", "", f"Split: `{split}`", "", header, divider]
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
    parser.add_argument(
        "--family-registry",
        type=Path,
        help="Matter-family registry used for family labels and clustered uncertainty",
    )
    parser.add_argument("--runner", choices=["replay", "baseline"], default="replay")
    parser.add_argument(
        "--split",
        choices=["dev", "held-out", "custom"],
        help="Dataset split recorded in the scorecard (default: dev for ./matters, custom otherwise)",
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--model", default=os.environ.get("PLAYBOOK_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PLAYBOOK_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Per-completion output cap; metered gateways pre-authorize the model's "
        "full output window per request when unset",
    )
    parser.add_argument("--out", type=Path, default=Path("artifacts/scorecard"))
    parser.add_argument(
        "--save-traces",
        action="store_true",
        help="Retain each episode's replayable trace under <out>/traces/ so every "
        "published row can be independently re-scored",
    )
    args = parser.parse_args()
    split = args.split or ("dev" if args.matters == Path("matters") else "custom")
    family_registry = load_family_registry(args.family_registry) if args.family_registry else None
    if args.runner == "replay" and len(args.seeds) != 1:
        parser.error(
            "reference replay is deterministic; pass exactly one seed instead of "
            "creating duplicate benchmark rows"
        )

    matter_dirs = discover_matter_dirs(args.matters)
    if not matter_dirs:
        raise SystemExit(f"No matters found under {args.matters}")

    # Live runs bill per episode whether or not results ever reach disk, so every
    # completed episode is checkpointed immediately and an interrupted sweep resumes
    # instead of repaying for finished work.
    partial_path = args.out.with_suffix(".partial.json")
    traces_dir = args.out.with_suffix("") / "traces" if args.save_traces else None
    rows: list[dict[str, Any]] = []
    if partial_path.exists():
        rows = json.loads(partial_path.read_text(encoding="utf-8"))
        print(f"Resuming: {len(rows)} episode(s) restored from {partial_path}")
    completed = {(str(row["matter_id"]), int(row["seed"])) for row in rows}

    skipped: list[str] = []
    for matter_dir in matter_dirs:
        rubric = load_yaml(matter_dir / "rubric.yaml")
        counterparty_path = matter_dir / "counterparty.yaml"
        counterparty = load_yaml(counterparty_path) if counterparty_path.exists() else {}
        for seed in args.seeds:
            trace_path = (
                traces_dir / f"{matter_dir.name}-seed{seed}.trace.json"
                if traces_dir is not None
                else None
            )
            if (matter_dir.name, seed) in completed:
                # A resumed episode is never re-run, so its trace can only exist if the
                # interrupted run also wrote one. Resuming a no-trace checkpoint with
                # --save-traces would publish traces_dir over a directory that cannot
                # cover every row — refuse rather than assert coverage that is absent.
                if trace_path is not None and not trace_path.exists():
                    raise SystemExit(
                        f"--save-traces: episode {matter_dir.name} seed {seed} was restored "
                        f"from the checkpoint {partial_path} but has no trace at {trace_path}. "
                        "Resumed episodes are not re-run, so that trace can never be written. "
                        "Delete the partial checkpoint to re-run those episodes with traces, "
                        "or rerun without --save-traces."
                    )
                continue
            if args.runner == "replay":
                result = run_replay(matter_dir, args.examples, seed, trace_path=trace_path)
                if result is None:
                    skipped.append(matter_dir.name)
                    break
            else:
                result = run_baseline(matter_dir, seed, args, trace_path=trace_path)
            metrics = compute_metrics(result, rubric, counterparty)
            if family_registry is not None:
                matter_id = str(metrics["matter_id"])
                if matter_id not in family_registry:
                    raise SystemExit(f"Matter {matter_id!r} is absent from {args.family_registry}")
                family = family_registry[matter_id]
                if split != "custom" and family["split"] != split:
                    raise SystemExit(
                        f"Matter {matter_id!r} is registered as {family['split']!r}, not {split!r}"
                    )
                metrics["matter_family_id"] = family["matter_family_id"]
            metrics["seed"] = seed
            rows.append(metrics)
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    if traces_dir is not None:
        # traces_dir is a coverage claim: every published row must be re-scorable from
        # a file in it. Verify before emitting the field, never after.
        missing = [
            f"{row['matter_id']} seed {row['seed']}"
            for row in rows
            if not (traces_dir / f"{row['matter_id']}-seed{row['seed']}.trace.json").exists()
        ]
        if missing:
            raise SystemExit(
                f"--save-traces: {len(missing)} scorecard row(s) have no trace under "
                f"{traces_dir}: {', '.join(missing)}. Refusing to publish a scorecard "
                "claiming trace coverage it does not have."
            )

    aggregate = aggregate_metrics(rows)
    uncertainty = (
        cluster_bootstrap_interval(rows, "critical_failure_rate")
        if family_registry is not None
        else None
    )
    label = args.model if args.runner == "baseline" else "reference replay"
    payload = {
        "runner": args.runner,
        "label": label,
        "split": split,
        "episodes": rows,
        "aggregate": aggregate,
        "uncertainty": uncertainty,
        "skipped": skipped,
    }
    if traces_dir is not None:
        payload["traces_dir"] = traces_dir.as_posix()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(
        to_markdown(rows, aggregate, f"Playbook scorecard — {label}", split),
        encoding="utf-8",
    )
    partial_path.unlink(missing_ok=True)
    if skipped:
        print(f"Skipped (no reference trajectory): {', '.join(skipped)}")
    print(json.dumps(aggregate, indent=2))
    print(f"Scorecard: {json_path} and {md_path}")
    if traces_dir is not None:
        print(f"Traces: {traces_dir}")


if __name__ == "__main__":
    main()
