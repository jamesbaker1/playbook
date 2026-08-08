# SPDX-License-Identifier: AGPL-3.0-only

"""Episode-level metrics implementing the SPEC evaluation protocol."""

from __future__ import annotations

import random
from typing import Any


def compute_metrics(
    result: dict[str, Any],
    rubric: dict[str, Any],
    counterparty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the evaluation-protocol metrics for one scored episode."""
    breakdown = result.get("breakdown", {})
    issues = rubric.get("issues", [])
    questions = rubric.get("questions", [])
    required_final = set(rubric.get("final_submission", {}).get("required_issue_ids", []))
    redline_scored = {
        str(item["id"]) for item in issues if float(item.get("redline_points", 1.0)) > 0
    }
    required_escalations = {
        str(item["id"])
        for item in rubric.get("escalations", [])
        if item.get("required") or item.get("critical_if_missed")
    }
    positions = set((counterparty or {}).get("positions", {}) or {})

    matched_issues = set(breakdown.get("matched_issues", []))
    matched_redlines = set(breakdown.get("matched_redlines", []))
    asked = set(breakdown.get("asked_questions", []))
    raised = set(breakdown.get("raised_escalations", []))
    settled = set(breakdown.get("settled_issues", []))
    reward_events = breakdown.get("reward_events", [])
    over_escalations = sum(
        1
        for event in reward_events
        if event.get("type") == "off_rubric_escalation"
    )
    trap_positions = {
        str(position_id)
        for position_id, position in ((counterparty or {}).get("positions", {}) or {}).items()
        if any(counter.get("trap") for counter in position.get("counters", []) or [])
    }
    exposed_traps = {
        str(event.get("criterion"))
        for event in reward_events
        if event.get("type") == "counterparty_counter"
        and str(event.get("criterion")) in trap_positions
    }
    accepted_traps = {
        str(event.get("criterion"))
        for event in reward_events
        if event.get("type") == "settlement"
        and event.get("closed_by") == "theirs"
        and str(event.get("criterion")) in exposed_traps
    }
    valid_citations = int(breakdown.get("valid_citation_count", 0))
    invalid_citations = len(breakdown.get("invalid_citations", []))
    total_citations = valid_citations + invalid_citations

    return {
        "matter_id": result.get("matter_id"),
        "normalized_score": result.get("normalized_score", 0.0),
        "raw_score": result.get("raw_score", 0.0),
        "issue_recall": len(matched_issues) / len(issues) if issues else 0.0,
        "required_issue_recall": (
            len(matched_issues & required_final) / len(required_final) if required_final else 1.0
        ),
        "unsupported_issue_count": len(breakdown.get("unsupported_issues", [])),
        "citation_validity": valid_citations / total_citations if total_citations else 1.0,
        "question_recall": len(asked) / len(questions) if questions else 1.0,
        "questions_asked": int(breakdown.get("questions_asked_total", 0)),
        "escalation_recall": (
            len(raised & required_escalations) / len(required_escalations)
            if required_escalations
            else 1.0
        ),
        "over_escalation_count": over_escalations,
        "redline_completion": (
            len(matched_redlines & redline_scored) / len(redline_scored)
            if redline_scored
            else 1.0
        ),
        "settled_issue_ratio": len(settled & positions) / len(positions) if positions else 1.0,
        "trap_counter_exposure_count": len(exposed_traps),
        "trap_counter_acceptance_count": len(accepted_traps),
        "fabricated_quote_count": len(breakdown.get("fabricated_quotes", [])),
        "critical_failure": bool(result.get("critical_failure", False)),
        "terminated": bool(result.get("terminated", False)),
        "steps": int(result.get("steps", 0)),
    }


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean-aggregate metric rows across episodes; rates for booleans."""
    if not rows:
        return {}
    numeric_keys = [
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
        "trap_counter_exposure_count",
        "trap_counter_acceptance_count",
        "fabricated_quote_count",
        "steps",
    ]
    aggregate: dict[str, Any] = {"episodes": len(rows)}
    for key in numeric_keys:
        aggregate[key] = round(sum(float(row.get(key, 0.0)) for row in rows) / len(rows), 4)
    aggregate["critical_failure_free_rate"] = round(
        sum(1 for row in rows if not row.get("critical_failure")) / len(rows), 4
    )
    aggregate["critical_failure_rate"] = round(
        sum(1 for row in rows if row.get("critical_failure")) / len(rows), 4
    )
    aggregate["completion_rate"] = round(
        sum(1 for row in rows if row.get("terminated")) / len(rows), 4
    )
    return aggregate


def _family_values(
    rows: list[dict[str, Any]], metric: str, family_key: str
) -> dict[str, list[float]]:
    """Group per-episode metric values under their matter family, the resampling unit."""
    families: dict[str, list[float]] = {}
    for row in rows:
        if family_key not in row:
            raise ValueError(f"row is missing {family_key}")
        value = (
            float(bool(row.get("critical_failure")))
            if metric == "critical_failure_rate"
            else float(row[metric])
        )
        families.setdefault(str(row[family_key]), []).append(value)
    return families


def _round(value: float) -> float:
    """Round to the reporting precision, normalizing a rounded -0.0 back to 0.0."""
    return round(value, 4) + 0.0


def _tail_indices(
    samples: int, confidence_level: float, *, one_sided: bool
) -> tuple[int | None, int]:
    """Sorted-estimate indices for the requested interval; ``None`` lower means -inf."""
    if one_sided:
        return None, min(samples - 1, int(confidence_level * samples) - 1)
    tail = (1 - confidence_level) / 2
    return max(0, int(tail * samples)), min(samples - 1, int((1 - tail) * samples) - 1)


def cluster_bootstrap_interval(
    rows: list[dict[str, Any]],
    metric: str,
    *,
    family_key: str = "matter_family_id",
    samples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 0,
) -> dict[str, Any]:
    """Bootstrap a mean by resampling matter families as intact clusters."""
    if samples <= 0:
        raise ValueError("samples must be positive")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    families = _family_values(rows, metric, family_key)
    if not families:
        return {}

    family_ids = sorted(families)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        selected = rng.choices(family_ids, k=len(family_ids))
        values = [value for family_id in selected for value in families[family_id]]
        estimates.append(sum(values) / len(values))
    estimates.sort()
    lower_index, upper_index = _tail_indices(samples, confidence_level, one_sided=False)
    observed = [value for values in families.values() for value in values]
    return {
        "metric": metric,
        "method": "cluster_bootstrap",
        "resampling_unit": "matter_family",
        "families": len(family_ids),
        "samples": samples,
        "confidence_level": confidence_level,
        "estimate": round(sum(observed) / len(observed), 4),
        "lower": round(estimates[lower_index], 4),
        "upper": round(estimates[upper_index], 4),
        "seed": seed,
    }


def cluster_bootstrap_difference(
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    metric: str,
    *,
    family_key: str = "matter_family_id",
    samples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 0,
    one_sided: bool = True,
) -> dict[str, Any]:
    """Bootstrap ``mean(rows_a) - mean(rows_b)`` by resampling matter families.

    The experiment contract evaluates every condition on the same held-out families,
    so both row sets must cover an identical family set (otherwise the difference
    would confound the conditions with the matters they were scored on). Each
    replicate draws one family list and applies it to both conditions, keeping the
    comparison paired; within a condition the mean is episode-weighted, matching
    :func:`cluster_bootstrap_interval`.

    With ``one_sided`` the interval is ``(-inf, upper]`` and ``lower`` is reported as
    ``None``. ``excludes_zero`` is derived from the rounded bounds that are reported,
    so the flag and the published numbers can never disagree.
    """
    if samples <= 0:
        raise ValueError("samples must be positive")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    families_a = _family_values(rows_a, metric, family_key)
    families_b = _family_values(rows_b, metric, family_key)
    if not families_a or not families_b:
        raise ValueError("both conditions need at least one labelled episode")
    if set(families_a) != set(families_b):
        only_a = sorted(set(families_a) - set(families_b))
        only_b = sorted(set(families_b) - set(families_a))
        raise ValueError(
            "conditions must be scored on identical matter families; "
            f"only in the first: {only_a or ['none']}; only in the second: {only_b or ['none']}"
        )

    family_ids = sorted(families_a)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        selected = rng.choices(family_ids, k=len(family_ids))
        values_a = [value for family_id in selected for value in families_a[family_id]]
        values_b = [value for family_id in selected for value in families_b[family_id]]
        estimates.append(sum(values_a) / len(values_a) - sum(values_b) / len(values_b))
    estimates.sort()
    lower_index, upper_index = _tail_indices(samples, confidence_level, one_sided=one_sided)
    observed_a = [value for values in families_a.values() for value in values]
    observed_b = [value for values in families_b.values() for value in values]
    estimate = sum(observed_a) / len(observed_a) - sum(observed_b) / len(observed_b)
    lower = None if lower_index is None else _round(estimates[lower_index])
    upper = _round(estimates[upper_index])
    excludes_zero = upper < 0 if lower is None else (upper < 0 or lower > 0)
    return {
        "metric": metric,
        "method": "cluster_bootstrap",
        "statistic": "difference_of_means",
        "resampling_unit": "matter_family",
        "families": len(family_ids),
        "samples": samples,
        "confidence_level": confidence_level,
        "one_sided": one_sided,
        "estimate": _round(estimate),
        "lower": lower,
        "upper": upper,
        "excludes_zero": bool(excludes_zero),
        "seed": seed,
    }
