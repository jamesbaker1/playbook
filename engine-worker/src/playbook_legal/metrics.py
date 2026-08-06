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
    tail = (1 - confidence_level) / 2
    lower_index = max(0, int(tail * samples))
    upper_index = min(samples - 1, int((1 - tail) * samples) - 1)
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
