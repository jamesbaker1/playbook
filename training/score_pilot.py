# SPDX-License-Identifier: AGPL-3.0-only

"""Score one teacher's rollout pilot and emit the pilot summary.

Reads a rollout directory produced by ``generate_rollouts.py`` (traces, chat records
and per-episode sidecars) plus the variant family packages the episodes were run
against, applies the pilot's rejection-sampling filters in order, and writes a
summary JSON modelled on ``artifacts/rollout-pilot/summary.json``.

Filter stages, in order, each evaluated only when the previous one passed:

1. completed        — the episode terminated and was not truncated
2. critical-free    — no critical-failure gate fired
3. replay-verified  — every recorded action reproduces bit-exactly against the
                      same variant matter package and seed
4. score bar        — normalized_score >= the bar (NEW for this pilot: the
                      mechanical filters alone admit negative-raw-reward
                      trajectories, as the 2026-08-06 Qwen2.5-32B pilot showed)

No network access: replay and reference scoring are local and deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playbook_legal.bench import run_replay
from playbook_legal.dataset import verify_trace_replay
from playbook_legal.lint import discover_matter_dirs

LABEL = (
    "PIPELINE VALIDATION ONLY - NOT TRAINING DATA. No legal review was performed; "
    "no record produced here is approved for training use."
)
PURPOSE = (
    "Two-teacher scaffolded rollout pilot: measure the rollout yield of one API teacher "
    "under the scaffolded workflow prompt against the same variants as the 2026-08-06 "
    "Qwen2.5-32B pilot, with a minimum-score filter on top of the mechanical filters."
)
RUNNER = "playbook_legal.baseline.run_episode, the same code path as the playbook-baseline CLI"
_NON_TRACE_SUFFIXES = (".chat.json", ".result.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_variant_packages(families_root: Path) -> dict[str, dict[str, Any]]:
    """Map variant id -> its matter directory, examples root and family metadata."""
    packages: dict[str, dict[str, Any]] = {}
    for family_dir in sorted(path for path in families_root.iterdir() if path.is_dir()):
        matters_root = family_dir / "matters"
        if not matters_root.is_dir():
            continue
        manifest_path = family_dir / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )
        for matter_dir in discover_matter_dirs(matters_root):
            packages[matter_dir.name] = {
                "family_id": str(manifest.get("family_id", family_dir.name)),
                "family_package": str(family_dir),
                "split": manifest.get("split"),
                "matter_dir": matter_dir,
                "examples_root": family_dir / "examples",
            }
    return packages


def discover_traces(rollouts: Path) -> list[Path]:
    """Candidate trace files, excluding the sidecars and the run index."""
    return sorted(
        path
        for path in rollouts.glob("*.json")
        if path.name != "index.json" and not path.name.endswith(_NON_TRACE_SUFFIXES)
    )


def trace_diagnostics(trace: dict[str, Any]) -> dict[str, Any]:
    """Derive the per-episode diagnostics the pilot summary reports."""
    breakdown = trace["result"].get("breakdown", {})
    finals = [
        event
        for event in breakdown.get("reward_events", [])
        if event.get("type") == "final_submission"
    ]
    actions = [event["action"] for event in trace["events"]]
    read = {
        str(action.get("document_id")) for action in actions if action["type"] == "read_document"
    }
    available = [
        str(document.get("id")) for document in trace["initial_observation"].get("documents", [])
    ]
    return {
        "actions": [action["type"] for action in actions],
        "documents_read": sorted(read),
        "documents_available": available,
        "read_every_document": bool(available) and read.issuperset(available),
        "questions_asked": breakdown.get("questions_asked_total", 0),
        "escalations_raised": breakdown.get("escalations_total", 0),
        "matched_issues": breakdown.get("matched_issues", []),
        "unsupported_issues": breakdown.get("unsupported_issues", []),
        "fabricated_quotes": breakdown.get("fabricated_quotes", []),
        "invalid_citations": breakdown.get("invalid_citations", []),
        "missing_required_issues_at_final": finals[-1].get("missing_issues", []) if finals else [],
    }


def score_candidate(
    trace_path: Path, packages: dict[str, dict[str, Any]], score_bar: float
) -> dict[str, Any]:
    """Apply the four filter stages to one candidate trace."""
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    result = trace["result"]
    variant = str(trace["matter"])
    package = packages.get(variant)

    completed = bool(result["terminated"]) and not bool(result["truncated"])
    critical_free = (not bool(result["critical_failure"])) if completed else None
    replay_verified: bool | None = None
    replay: dict[str, Any] | None = None
    reject_reason: str | None = None

    if not completed:
        reject_reason = "did not complete"
    elif not critical_free:
        reject_reason = "critical failure"
    elif package is None:
        replay_verified = False
        reject_reason = f"no variant package for {variant}"
    else:
        try:
            replay = verify_trace_replay(trace, package["matter_dir"])
            replay_verified = True
        except ValueError as exc:
            replay_verified = False
            reject_reason = f"replay verification failed: {exc}"

    above_bar: bool | None = None
    if replay_verified:
        above_bar = float(result["normalized_score"]) >= score_bar
        if not above_bar:
            reject_reason = f"normalized_score {result['normalized_score']} below bar {score_bar}"

    return {
        "trace": trace_path.name,
        "trace_sha256": _sha256(trace_path),
        "variant": variant,
        "family": package["family_id"] if package else None,
        "seed": trace["seed"],
        "steps": result["steps"],
        "normalized_score": result["normalized_score"],
        "raw_score": result["raw_score"],
        "max_score": result["max_score"],
        "critical_failure": result["critical_failure"],
        "terminated": result["terminated"],
        "truncated": result["truncated"],
        "protocol_failures": result.get("protocol_failures"),
        "stage_completed": completed,
        "stage_critical_free": critical_free,
        "stage_replay_verified": replay_verified,
        "stage_above_score_bar": above_bar,
        "mechanically_valid": bool(replay_verified),
        "survived": bool(above_bar),
        "reject_reason": reject_reason,
        "replay_verification": replay,
        "diagnostics": trace_diagnostics(trace),
    }


def variants_used(
    candidates: list[dict[str, Any]], packages: dict[str, dict[str, Any]], seed: int
) -> list[dict[str, Any]]:
    """Reference scores replayed from each variant package the pilot actually used."""
    rows = []
    for variant in sorted({candidate["variant"] for candidate in candidates}):
        package = packages.get(variant)
        if package is None:
            rows.append({"variant": variant, "reference_score": None, "family_package": None})
            continue
        reference = run_replay(package["matter_dir"], package["examples_root"], seed)
        rows.append(
            {
                "family_id": package["family_id"],
                "family_package": package["family_package"],
                "variant": variant,
                "split": package["split"],
                "reference_score": reference["normalized_score"] if reference else None,
                "reference_replay_seed": seed,
            }
        )
    return rows


def summarize(candidates: list[dict[str, Any]], references: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(candidate["normalized_score"]) for candidate in candidates]
    reference_scores = [
        float(row["reference_score"]) for row in references if row["reference_score"] is not None
    ]
    per_variant: dict[str, dict[str, Any]] = {}
    for row in references:
        variant_scores = [
            float(candidate["normalized_score"])
            for candidate in candidates
            if candidate["variant"] == row["variant"]
        ]
        per_variant[row["variant"]] = {
            "scores": variant_scores,
            "reference_score": row["reference_score"],
        }
    return {
        "teacher_score_range": [min(scores), max(scores)] if scores else None,
        "teacher_mean_normalized_score": round(sum(scores) / len(scores), 4) if scores else None,
        "reference_score_range": (
            [min(reference_scores), max(reference_scores)] if reference_scores else None
        ),
        "per_variant": per_variant,
    }


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    packages = discover_variant_packages(args.families_root)
    trace_paths = discover_traces(args.rollouts)
    if not trace_paths:
        raise SystemExit(f"No candidate traces found under {args.rollouts}")
    candidates = [score_candidate(path, packages, args.score_bar) for path in trace_paths]
    references = variants_used(candidates, packages, args.reference_seed)

    generated = len(candidates)
    mechanically_valid = [candidate for candidate in candidates if candidate["mechanically_valid"]]
    survivors = [candidate for candidate in candidates if candidate["survived"]]
    system_prompt = (
        {
            "path": str(args.system_prompt_file),
            "sha256": _sha256(args.system_prompt_file),
        }
        if args.system_prompt_file is not None
        else None
    )
    return {
        "label": LABEL,
        "purpose": PURPOSE,
        "date_utc": datetime.now(UTC).date().isoformat(),
        "teacher": {
            "model": args.teacher,
            "serving": args.serving,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "seeds": sorted({candidate["seed"] for candidate in candidates}),
            "runner": RUNNER,
            "system_prompt": system_prompt,
        },
        "environments": {
            "source": str(args.families_root),
            "variants_used": references,
        },
        "score_bar": args.score_bar,
        "filters_applied": [
            "stage 1 completed: result.terminated and not result.truncated",
            "stage 2 critical-free: result.critical_failure is False",
            (
                "stage 3 replay-verified: playbook_legal.dataset.verify_trace_replay replays "
                "every recorded action against the same variant matter package and seed; the "
                "initial observation, each step's observation, reward, termination flags and "
                "info, and the final episode result must all reproduce exactly"
            ),
            (
                f"stage 4 score bar: result.normalized_score >= {args.score_bar}; the mechanical "
                "filters alone admit negative-raw-reward trajectories, so a minimum-score filter "
                "is required before any candidate is treated as supervision"
            ),
        ],
        "candidates": candidates,
        "rollout_yield": {
            "candidates_generated": generated,
            "survived_completed": sum(1 for c in candidates if c["stage_completed"]),
            "survived_critical_free": sum(1 for c in candidates if c["stage_critical_free"]),
            "survived_replay_verified": sum(1 for c in candidates if c["stage_replay_verified"]),
            "survived_above_score_bar": sum(1 for c in candidates if c["stage_above_score_bar"]),
            "mechanically_valid": len(mechanically_valid),
            "survivors": len(survivors),
            "episode_yield_rate": round(len(mechanically_valid) / generated, 4),
            "yield_above_bar": round(len(survivors) / generated, 4),
            "survivor_traces": [candidate["trace"] for candidate in survivors],
        },
        "score_summary": summarize(candidates, references),
        "qualitative_assessment": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score one teacher's rollout pilot.")
    parser.add_argument("--rollouts", type=Path, required=True, help="generate_rollouts output dir")
    parser.add_argument(
        "--families-root",
        type=Path,
        required=True,
        help="Root holding <family>/matters/<variant> and <family>/examples/<variant>",
    )
    parser.add_argument("--teacher", required=True, help="Teacher model slug, as sent to the API")
    parser.add_argument("--score-bar", type=float, default=0.5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--serving", default="OpenRouter (OpenAI-compatible API)")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, help="Per-completion cap used for generation")
    parser.add_argument(
        "--system-prompt-file",
        type=Path,
        help="System prompt used for generation; recorded by path and SHA-256",
    )
    parser.add_argument(
        "--reference-seed",
        type=int,
        default=0,
        help="Seed for the reference trajectory replay (the environment is deterministic)",
    )
    args = parser.parse_args(argv)

    summary = build_summary(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    yield_block = summary["rollout_yield"]
    print(
        f"{args.teacher}: {yield_block['survivors']}/{yield_block['candidates_generated']} "
        f"above the {args.score_bar} bar "
        f"({yield_block['mechanically_valid']} mechanically valid)"
    )
    print(f"Summary: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
