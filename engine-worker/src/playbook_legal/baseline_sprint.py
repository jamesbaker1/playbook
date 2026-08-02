# SPDX-License-Identifier: AGPL-3.0-only

"""Plan, run, and summarize the budget-gated model baseline sprint."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_METRICS = (
    "normalized_score",
    "raw_score",
    "issue_recall",
    "required_issue_recall",
    "unsupported_issue_count",
    "citation_validity",
    "question_recall",
    "questions_asked",
    "escalation_recall",
    "over_escalation_count",
    "redline_completion",
    "settled_issue_ratio",
    "fabricated_quote_count",
    "critical_failure_free_rate",
    "steps",
)


def validate_models(models: list[str]) -> list[str]:
    """Require an explicit, unambiguous model list."""
    cleaned = [model.strip() for model in models]
    if not cleaned or any(not model for model in cleaned):
        raise ValueError("provide at least one non-empty model with --models")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("--models contains duplicates")
    slugs = [model_slug(model) for model in cleaned]
    if len(set(slugs)) != len(slugs):
        raise ValueError("model names collide after filename normalization")
    return cleaned


def model_slug(model: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in model.lower())
    return "-".join(part for part in slug.split("-") if part)


def require_credentials(api_key_env: str, environ: dict[str, str] | None = None) -> None:
    """Fail before a paid request when the named credential is absent."""
    values = os.environ if environ is None else environ
    if not values.get(api_key_env, "").strip():
        raise ValueError(f"{api_key_env} is not set; no baseline requests were started")


def bench_command(
    *, model: str, split: str, matters: Path, out: Path, seeds: list[int], temperature: float
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "playbook_legal.bench",
        "--runner",
        "baseline",
        "--model",
        model,
        "--split",
        split,
        "--matters",
        str(matters),
        "--seeds",
        *[str(seed) for seed in seeds],
        "--temperature",
        str(temperature),
        "--out",
        str(out),
    ]


def load_scorecard(path: Path, *, model: str, split: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("runner") != "baseline" or payload.get("label") != model:
        raise ValueError(f"{path}: expected baseline scorecard for {model!r}")
    if payload.get("split") != split:
        raise ValueError(f"{path}: expected split {split!r}")
    aggregate = payload.get("aggregate", {})
    missing = [metric for metric in REQUIRED_METRICS if metric not in aggregate]
    if missing:
        raise ValueError(f"{path}: missing required metrics: {', '.join(missing)}")
    if not payload.get("episodes"):
        raise ValueError(f"{path}: scorecard contains no episodes")
    return payload


def aggregate_scorecards(
    models: list[str], scorecard_root: Path, *, require_held_out: bool = True
) -> dict[str, Any]:
    """Validate measured scorecards and compute explicit held-out deltas."""
    rows: list[dict[str, Any]] = []
    for model in models:
        slug = model_slug(model)
        dev = load_scorecard(scorecard_root / slug / "dev.json", model=model, split="dev")
        held_path = scorecard_root / slug / "held-out.json"
        if not held_path.exists() and not require_held_out:
            continue
        held = load_scorecard(held_path, model=model, split="held-out")
        dev_score = float(dev["aggregate"]["normalized_score"])
        held_score = float(held["aggregate"]["normalized_score"])
        nego_rows = [
            episode for episode in dev["episodes"] if episode.get("matter_id") == "nego_saas_010"
        ]
        rows.append(
            {
                "model": model,
                "dev": dev["aggregate"],
                "held_out": held["aggregate"],
                "held_out_minus_dev": round(held_score - dev_score, 4),
                "nego_saas_010_trap": {
                    "episodes": len(nego_rows),
                    "exposures": sum(
                        int(row.get("trap_counter_exposure_count", 0)) for row in nego_rows
                    ),
                    "acceptances": sum(
                        int(row.get("trap_counter_acceptance_count", 0)) for row in nego_rows
                    ),
                },
            }
        )
    if not rows:
        raise ValueError("no complete dev/held-out model scorecard pairs found")
    return {"source": "measured playbook-bench scorecards", "models": rows}


def result_markdown(summary: dict[str, Any]) -> str:
    """Produce a paste-ready report fragment containing measured values only."""
    lines = [
        "| Model | Dev score | Held-out score | Held-out − dev | Escalation recall (held-out) | Over-escalations (held-out) | Settled ratio (held-out) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["models"]:
        dev, held = row["dev"], row["held_out"]
        lines.append(
            f"| {row['model']} | {dev['normalized_score']:.4f} | "
            f"{held['normalized_score']:.4f} | {row['held_out_minus_dev']:+.4f} | "
            f"{held['escalation_recall']:.4f} | {held['over_escalation_count']:.4f} | "
            f"{held['settled_issue_ratio']:.4f} |"
        )
    lines += ["", "Trap-counter check (`nego_saas_010`, dev split):"]
    for row in summary["models"]:
        trap = row["nego_saas_010_trap"]
        lines.append(
            f"- `{row['model']}`: {trap['exposures']} trap counter(s) exposed; "
            f"{trap['acceptances']} accepted across {trap['episodes']} episode(s)."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True, help="explicit provider model IDs")
    parser.add_argument("--dev-matters", type=Path, default=Path("matters"))
    parser.add_argument("--held-out-matters", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top", type=int, default=2)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--out", type=Path, default=Path("artifacts/baseline-sprint"))
    parser.add_argument("--execute", action="store_true", help="make model requests")
    args = parser.parse_args()

    try:
        models = validate_models(args.models)
        if args.top < 1:
            raise ValueError("--top must be at least 1")
        if args.execute:
            require_credentials(args.api_key_env)
            if args.held_out_matters is None or not args.held_out_matters.is_dir():
                raise ValueError("--execute requires an existing --held-out-matters directory")
    except ValueError as exc:
        parser.error(str(exc))

    commands = {
        model: bench_command(
            model=model,
            split="dev",
            matters=args.dev_matters,
            out=args.out / model_slug(model) / "dev",
            seeds=args.seeds,
            temperature=args.temperature,
        )
        for model in models
    }
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "models": models,
        "dev_matters": str(args.dev_matters),
        "held_out_matters": str(args.held_out_matters) if args.held_out_matters else None,
        "seeds": args.seeds,
        "temperature": args.temperature,
        "commands": {model: subprocess.list2cmdline(command) for model, command in commands.items()},
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not args.execute:
        print(json.dumps(manifest, indent=2))
        print("Plan only: no credentials checked and no model requests made. Add --execute to run.")
        return

    run_env = dict(os.environ)
    if args.api_key_env != "OPENAI_API_KEY":
        run_env["OPENAI_API_KEY"] = run_env[args.api_key_env]
    for command in commands.values():
        subprocess.run(command, check=True, env=run_env)

    ranked = sorted(
        models,
        key=lambda model: float(
            load_scorecard(
                args.out / model_slug(model) / "dev.json", model=model, split="dev"
            )["aggregate"]["normalized_score"]
        ),
        reverse=True,
    )[: args.top]
    for model in ranked:
        command = bench_command(
            model=model,
            split="held-out",
            matters=args.held_out_matters,
            out=args.out / model_slug(model) / "held-out",
            seeds=args.seeds,
            temperature=args.temperature,
        )
        subprocess.run(command, check=True, env=run_env)

    summary = aggregate_scorecards(ranked, args.out)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (args.out / "report-fragment.md").write_text(result_markdown(summary), encoding="utf-8")
    print(f"Measured summary: {args.out / 'summary.json'}")
    print(f"Paste-ready report fragment: {args.out / 'report-fragment.md'}")


if __name__ == "__main__":
    main()
