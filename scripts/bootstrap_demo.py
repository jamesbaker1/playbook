# SPDX-License-Identifier: AGPL-3.0-only

"""Run the preregistered release-gate estimator on the only paired rows that exist.

This is a machinery demonstration, not the Playbook-1 experiment. The experiment
compares ``state_action_sft`` against ``final_answer_sft`` on held-out sealed
matter families, and neither condition exists yet. What this script feeds the
estimator instead is two v0.4.0 frontier reference scorecards — GPT-5.6-terra and
Claude Haiku 4.5, single seed each, the same twelve public *dev* matters, scored
under the pre-revision critical-failure instrument whose rates are not comparable
to post-revision ones without a re-run. Read the output as "the gate computes
what the contract says it computes", never as evidence about state-action
distillation.

Every number comes from the repository's own estimator,
``playbook_legal.metrics.cluster_bootstrap_difference``, over rows read by the
same loader the ``playbook-analysis`` console entry point uses. The estimator
does not return its resample distribution, so the distribution is recovered by
recording each ``rng.choices`` draw the estimator makes and replaying those draws
through the metrics module's own family grouping; the replay's order statistics
are then checked against the bounds the estimator published, and the script
raises if the two disagree.

    python scripts/bootstrap_demo.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from playbook_legal import metrics
from playbook_legal.analysis import load_condition_rows
from playbook_legal.metrics import cluster_bootstrap_difference

TREATMENT = ("openai/gpt-5.6-terra (seed 0)", "results/v0.4.0/gpt-5_6-terra-seed0.json")
CONTROL = ("anthropic/claude-haiku-4.5 (seed 0)", "results/v0.4.0/claude-haiku-4_5-seed0.json")
OUT_PATH = "results/bootstrap-demo/2026-08-19-terra-vs-haiku.json"

# The knobs the frozen contract does not freeze, at the values playbook-analysis
# defaults to; the confidence level is the one the contract does freeze.
FAMILY_KEY = "matter_family_id"
SAMPLES = 2000
SEED = 0
CONFIDENCE_LEVEL = 0.95

# metric, one_sided, key in the output payload
RUNS = [
    ("critical_failure_rate", True, "critical_failure_rate__one_sided"),
    ("critical_failure_rate", False, "critical_failure_rate__two_sided"),
    ("normalized_score", False, "normalized_score__two_sided"),
]

CAVEAT = (
    "Machinery demonstration, not the Playbook-1 experiment. Two v0.4.0 frontier "
    "reference scorecards, single seed each, on the twelve public dev matters, "
    "measured under the pre-revision critical-failure instrument. No trained "
    "condition and no held-out sealed family is involved, and pre-revision rates "
    "are not comparable to post-revision ones without a re-run."
)


class _RecordingRandom(random.Random):
    """A ``random.Random`` that keeps every ``choices`` list it hands back."""

    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.draws: list[list[str]] = []

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        selected = super().choices(population, weights, cum_weights=cum_weights, k=k)
        self.draws.append(list(selected))
        return selected


def bootstrap_with_distribution(
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    metric: str,
    *,
    one_sided: bool,
) -> tuple[dict[str, Any], list[float]]:
    """The estimator's result, plus the resample distribution it built internally.

    The distribution is a replay of the draws the estimator made, not a second
    bootstrap: the recorded family lists are regrouped with ``_family_values``,
    the module's own grouping, and the replay is rejected unless its order
    statistics reproduce the bounds the estimator published.
    """
    recorded: list[_RecordingRandom] = []

    def factory(seed_value: int) -> _RecordingRandom:
        rng = _RecordingRandom(seed_value)
        recorded.append(rng)
        return rng

    original = metrics.random.Random
    metrics.random.Random = factory
    try:
        result = cluster_bootstrap_difference(
            rows_a,
            rows_b,
            metric,
            family_key=FAMILY_KEY,
            samples=SAMPLES,
            confidence_level=CONFIDENCE_LEVEL,
            seed=SEED,
            one_sided=one_sided,
        )
    finally:
        metrics.random.Random = original

    families_a = metrics._family_values(rows_a, metric, FAMILY_KEY)
    families_b = metrics._family_values(rows_b, metric, FAMILY_KEY)
    distribution = []
    for selected in recorded[0].draws:
        values_a = [value for family in selected for value in families_a[family]]
        values_b = [value for family in selected for value in families_b[family]]
        distribution.append(sum(values_a) / len(values_a) - sum(values_b) / len(values_b))

    if len(distribution) != SAMPLES:
        raise ValueError(f"{metric}: recorded {len(distribution)} draws, expected {SAMPLES}")
    ordered = sorted(distribution)
    lower_index, upper_index = metrics._tail_indices(
        SAMPLES, CONFIDENCE_LEVEL, one_sided=one_sided
    )
    replayed = (
        None if lower_index is None else metrics._round(ordered[lower_index]),
        metrics._round(ordered[upper_index]),
    )
    if replayed != (result["lower"], result["upper"]):
        raise ValueError(
            f"{metric}: replayed bounds {replayed} do not reproduce the estimator's "
            f"{(result['lower'], result['upper'])}"
        )
    return result, distribution


def interval(result: dict[str, Any]) -> str:
    """The published interval, as the post prints it."""
    if result["lower"] is None:
        return f"(-inf, {result['upper']}]"
    return f"[{result['lower']}, {result['upper']}]"


def main() -> None:
    treatment_label, treatment_file = TREATMENT
    control_label, control_file = CONTROL
    rows_a = load_condition_rows(ROOT / treatment_file)
    rows_b = load_condition_rows(ROOT / control_file)

    families = sorted({str(row[FAMILY_KEY]) for row in rows_a})
    payload: dict[str, Any] = {
        "caveat": CAVEAT,
        "generated_by": "scripts/bootstrap_demo.py",
        "estimator": "playbook_legal.metrics.cluster_bootstrap_difference",
        "split": "dev",
        "instrument": "pre-revision (v0.4.0 critical-failure gates)",
        "treatment": {
            "label": treatment_label,
            "file": treatment_file,
            "episodes": len(rows_a),
        },
        "control": {
            "label": control_label,
            "file": control_file,
            "episodes": len(rows_b),
        },
        "resampling_unit": "matter_family",
        "family_key": FAMILY_KEY,
        "families": families,
        "family_count": len(families),
        "samples": SAMPLES,
        "seed": SEED,
        "confidence_level": CONFIDENCE_LEVEL,
        "runs": {},
    }

    print(f"{CAVEAT}\n")
    print(f"treatment  {treatment_label}  ({len(rows_a)} episodes)")
    print(f"control    {control_label}  ({len(rows_b)} episodes)")
    print(f"{len(families)} matter families, {SAMPLES} resamples, seed {SEED}\n")

    for metric, one_sided, key in RUNS:
        result, distribution = bootstrap_with_distribution(
            rows_a, rows_b, metric, one_sided=one_sided
        )
        payload["runs"][key] = {
            "metric": metric,
            "one_sided": one_sided,
            "estimate": result["estimate"],
            "lower": result["lower"],
            "upper": result["upper"],
            "excludes_zero": result["excludes_zero"],
            "result": result,
            "resample_differences": distribution,
        }
        sided = "one-sided" if one_sided else "two-sided"
        print(
            f"{metric:<22} {sided}  estimate {result['estimate']:<8} "
            f"{interval(result):<20} excludes zero: "
            f"{'yes' if result['excludes_zero'] else 'no'}"
        )

    out = ROOT / OUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_PATH} ({len(RUNS)} runs, {SAMPLES} resamples each)")


if __name__ == "__main__":
    main()
