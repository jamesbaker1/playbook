from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RewardState:
    raw_score: float = 0.0
    critical_failure: bool = False
    asked_questions: set[str] = field(default_factory=set)
    submitted_issues: set[str] = field(default_factory=set)
    submitted_redlines: set[str] = field(default_factory=set)
    invalid_citations: list[str] = field(default_factory=list)
    unsupported_issues: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class RewardEngine:
    def __init__(self, rubric: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        self.rubric = rubric
        self.documents = documents
        self.state = RewardState()
        self.issue_map = {item["id"]: item for item in rubric.get("issues", [])}
        self.question_map = {item["id"]: item for item in rubric.get("questions", [])}
        self.max_score = float(rubric.get("max_score", self._derive_max_score()))

    def reset(self) -> None:
        self.state = RewardState()

    def score_question(self, question_id: str) -> tuple[float, dict[str, Any]]:
        criterion = self.question_map.get(question_id)
        if criterion is None:
            return self._record(-0.25, "unsupported_question", question_id)
        if question_id in self.state.asked_questions:
            return self._record(-0.15, "redundant_question", question_id)
        self.state.asked_questions.add(question_id)
        points = float(criterion.get("points", 0.5))
        return self._record(points, "required_question", question_id)

    def score_issue(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        issue_id = str(action.get("issue_id", ""))
        criterion = self.issue_map.get(issue_id)
        if criterion is None:
            self.state.unsupported_issues.append(issue_id)
            return self._record(-0.5, "unsupported_issue", issue_id)
        if issue_id in self.state.submitted_issues:
            return self._record(-0.2, "duplicate_issue", issue_id)

        self.state.submitted_issues.add(issue_id)
        points = float(criterion.get("base_points", 1.0))
        details: dict[str, Any] = {"criterion": issue_id, "components": {"base": points}}

        expected_severity = criterion.get("severity")
        severity_points = float(criterion.get("severity_points", 0.25))
        if action.get("severity") == expected_severity:
            points += severity_points
            details["components"]["severity"] = severity_points
        else:
            details["components"]["severity"] = 0.0

        valid_citations, invalid_citations = self._validate_citations(action.get("citations", []))
        self.state.invalid_citations.extend(invalid_citations)
        required_citations = set(criterion.get("required_citations", []))
        citation_points = float(criterion.get("citation_points", 0.25))
        if required_citations.issubset(valid_citations):
            points += citation_points
            details["components"]["citations"] = citation_points
        else:
            details["components"]["citations"] = 0.0
            details["missing_citations"] = sorted(required_citations - valid_citations)
        if invalid_citations:
            penalty = 0.75 * len(invalid_citations)
            points -= penalty
            details["components"]["invalid_citation_penalty"] = -penalty

        combined_text = " ".join(
            str(action.get(key, "")) for key in ("title", "analysis", "recommendation")
        ).lower()
        concepts = [str(item).lower() for item in criterion.get("required_concepts", [])]
        matched = [concept for concept in concepts if concept in combined_text]
        concept_points = float(criterion.get("concept_points", 0.5))
        if concepts:
            awarded = concept_points * (len(matched) / len(concepts))
            points += awarded
            details["components"]["concepts"] = awarded
            details["matched_concepts"] = matched
        else:
            details["components"]["concepts"] = 0.0

        critical_patterns = criterion.get("critical_failure_patterns", [])
        for pattern in critical_patterns:
            if re.search(pattern, combined_text, flags=re.IGNORECASE):
                self.state.critical_failure = True
                details["critical_failure_pattern"] = pattern

        return self._record(points, "issue", issue_id, details)

    def score_redline(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        issue_id = str(action.get("issue_id", ""))
        criterion = self.issue_map.get(issue_id)
        if criterion is None:
            return self._record(-0.5, "unsupported_redline", issue_id)
        if issue_id in self.state.submitted_redlines:
            return self._record(-0.2, "duplicate_redline", issue_id)
        self.state.submitted_redlines.add(issue_id)

        redline = str(action.get("replacement_text", "")).lower()
        required = [str(item).lower() for item in criterion.get("redline_concepts", [])]
        redline_points = float(criterion.get("redline_points", 1.0))
        if not required:
            return self._record(0.0, "unscored_redline", issue_id)
        matched = [concept for concept in required if concept in redline]
        points = redline_points * (len(matched) / len(required))
        details = {"criterion": issue_id, "matched_redline_concepts": matched}

        for pattern in criterion.get("redline_critical_failure_patterns", []):
            if re.search(pattern, redline, flags=re.IGNORECASE):
                self.state.critical_failure = True
                details["critical_failure_pattern"] = pattern

        return self._record(points, "redline", issue_id, details)

    def score_final(self, summary: str) -> tuple[float, dict[str, Any]]:
        config = self.rubric.get("final_submission", {})
        points = float(config.get("points", 0.5))
        min_chars = int(config.get("minimum_characters", 80))
        if len(summary.strip()) < min_chars:
            points = 0.0
        required_issue_ids = set(config.get("required_issue_ids", []))
        missing = sorted(required_issue_ids - self.state.submitted_issues)
        if missing:
            points -= float(config.get("missing_required_issue_penalty", 0.25)) * len(missing)
        return self._record(points, "final_submission", "final", {"missing_issues": missing})

    def result(self, *, terminated: bool, truncated: bool, steps: int, matter_id: str) -> dict[str, Any]:
        raw = self.state.raw_score
        normalized = max(0.0, min(1.0, raw / self.max_score if self.max_score else 0.0))
        if self.state.critical_failure:
            cap = float(self.rubric.get("critical_failure_score_cap", 0.25))
            normalized = min(normalized, cap)
        return {
            "matter_id": matter_id,
            "raw_score": round(raw, 4),
            "max_score": self.max_score,
            "normalized_score": round(normalized, 4),
            "critical_failure": self.state.critical_failure,
            "terminated": terminated,
            "truncated": truncated,
            "steps": steps,
            "breakdown": {
                "asked_questions": sorted(self.state.asked_questions),
                "submitted_issues": sorted(self.state.submitted_issues),
                "submitted_redlines": sorted(self.state.submitted_redlines),
                "invalid_citations": self.state.invalid_citations,
                "unsupported_issues": self.state.unsupported_issues,
                "reward_events": self.state.events,
            },
        }

    def _validate_citations(self, citations: list[Any]) -> tuple[set[str], list[str]]:
        valid: set[str] = set()
        invalid: list[str] = []
        for raw in citations:
            citation = str(raw)
            if "§" not in citation:
                invalid.append(citation)
                continue
            document_id, section = [part.strip() for part in citation.split("§", maxsplit=1)]
            document = self.documents.get(document_id)
            if document and section in document["sections"]:
                valid.add(citation)
            else:
                invalid.append(citation)
        return valid, invalid

    def _record(
        self,
        points: float,
        event_type: str,
        criterion: str,
        details: dict[str, Any] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        self.state.raw_score += points
        event = {
            "type": event_type,
            "criterion": criterion,
            "points": round(points, 4),
            **(details or {}),
        }
        self.state.events.append(event)
        return points, event

    def _derive_max_score(self) -> float:
        total = sum(float(q.get("points", 0.5)) for q in self.rubric.get("questions", []))
        for issue in self.rubric.get("issues", []):
            total += float(issue.get("base_points", 1.0))
            total += float(issue.get("severity_points", 0.25))
            total += float(issue.get("citation_points", 0.25))
            total += float(issue.get("concept_points", 0.5))
            total += float(issue.get("redline_points", 1.0))
        total += float(self.rubric.get("final_submission", {}).get("points", 0.5))
        return total
