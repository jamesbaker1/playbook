"""Episode-level metrics implementing the SPEC evaluation protocol."""

from __future__ import annotations

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
    over_escalations = sum(
        1
        for event in breakdown.get("reward_events", [])
        if event.get("type") == "off_rubric_escalation"
    )
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
        "steps",
    ]
    aggregate: dict[str, Any] = {"episodes": len(rows)}
    for key in numeric_keys:
        aggregate[key] = round(sum(float(row.get(key, 0.0)) for row in rows) / len(rows), 4)
    aggregate["critical_failure_free_rate"] = round(
        sum(1 for row in rows if not row.get("critical_failure")) / len(rows), 4
    )
    aggregate["completion_rate"] = round(
        sum(1 for row in rows if row.get("terminated")) / len(rows), 4
    )
    return aggregate
