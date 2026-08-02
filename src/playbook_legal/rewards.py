"""Deterministic reward engine for Playbook environments.

v0.2 scoring contract
---------------------

Rubric credit is earned by *content*, never by guessing rubric-internal identifiers:

- Issues are matched to rubric criteria by the operative provision they cite. Each
  rubric issue declares a unique ``anchor`` citation; the first submitted citation
  that is some criterion's anchor decides the match. The agent's ``issue_id`` is
  only a label used to link a later redline to the same issue.
- Client questions are matched by concept phrases appearing in the free-text
  question. Rubric questions declare ``concepts`` (all must appear) and optional
  ``aliases`` (alternative concept lists).
- Quotations are verified verbatim against the cited section. A quotation that
  does not appear in the cited section is a critical failure (fabrication gate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MINIMUM_QUOTE_CHARACTERS = 15


def _normalize(text: str) -> str:
    return " ".join(str(text).lower().split())


@dataclass
class RewardState:
    raw_score: float = 0.0
    critical_failure: bool = False
    asked_questions: set[str] = field(default_factory=set)
    questions_asked_total: int = 0
    matched_issues: set[str] = field(default_factory=set)
    matched_redlines: set[str] = field(default_factory=set)
    issue_labels: dict[str, str] = field(default_factory=dict)
    valid_citation_count: int = 0
    invalid_citations: list[str] = field(default_factory=list)
    unsupported_issues: list[str] = field(default_factory=list)
    fabricated_quotes: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class RewardEngine:
    def __init__(self, rubric: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        self.rubric = rubric
        self.documents = documents
        self.state = RewardState()
        self.issue_map = {item["id"]: item for item in rubric.get("issues", [])}
        self.anchor_map = {
            str(item["anchor"]): item for item in rubric.get("issues", []) if item.get("anchor")
        }
        self.questions = list(rubric.get("questions", []))
        self.max_score = float(rubric.get("max_score", self._derive_max_score()))

    def reset(self) -> None:
        self.state = RewardState()

    # ------------------------------------------------------------------ questions

    def match_question(self, question_text: str) -> dict[str, Any] | None:
        """Match free question text to a rubric question by concept phrases."""
        text = _normalize(question_text)
        for criterion in self.questions:
            variants: list[list[str]] = [criterion.get("concepts", [])]
            variants.extend(criterion.get("aliases", []))
            for variant in variants:
                if variant and all(_normalize(concept) in text for concept in variant):
                    return criterion
        return None

    def score_question(self, question_text: str) -> tuple[float, dict[str, Any], str | None]:
        self.state.questions_asked_total += 1
        criterion = self.match_question(question_text)
        if criterion is None:
            points, event = self._record(-0.1, "off_rubric_question", _normalize(question_text)[:80])
            return points, event, None
        question_id = str(criterion["id"])
        if question_id in self.state.asked_questions:
            points, event = self._record(-0.15, "redundant_question", question_id)
            return points, event, question_id
        self.state.asked_questions.add(question_id)
        points, event = self._record(
            float(criterion.get("points", 0.5)), "required_question", question_id
        )
        return points, event, question_id

    # -------------------------------------------------------------------- issues

    def match_issue(self, citations: list[str]) -> dict[str, Any] | None:
        """Match an issue submission to a rubric criterion by its anchor citation.

        The first citation that is some criterion's anchor decides the match, which
        is why the protocol instructs agents to cite the operative provision first.
        """
        for raw in citations:
            criterion = self.anchor_map.get(str(raw).strip())
            if criterion is not None:
                return criterion
        return None

    def score_issue(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        label = str(action.get("issue_id", ""))
        citations = [str(item) for item in action.get("citations", [])]
        valid_citations, invalid_citations = self._validate_citations(citations)
        self.state.valid_citation_count += len(valid_citations)
        self.state.invalid_citations.extend(invalid_citations)
        invalid_penalty = 0.75 * len(invalid_citations)

        criterion = self.match_issue([c for c in citations if c in valid_citations])
        if criterion is None:
            self.state.unsupported_issues.append(label)
            return self._record(
                -0.5 - invalid_penalty,
                "unsupported_issue",
                label,
                {"reason": "no cited provision matches a scored issue's operative anchor"},
            )

        rubric_id = str(criterion["id"])
        if rubric_id in self.state.matched_issues:
            return self._record(-0.2, "duplicate_issue", rubric_id)
        self.state.matched_issues.add(rubric_id)
        self.state.issue_labels[label] = rubric_id

        points = float(criterion.get("base_points", 1.0))
        details: dict[str, Any] = {"criterion": rubric_id, "components": {"base": points}}

        severity_points = float(criterion.get("severity_points", 0.25))
        if action.get("severity") == criterion.get("severity"):
            points += severity_points
            details["components"]["severity"] = severity_points
        else:
            details["components"]["severity"] = 0.0

        required_citations = set(criterion.get("required_citations", []))
        citation_points = float(criterion.get("citation_points", 0.25))
        if required_citations.issubset(valid_citations):
            points += citation_points
            details["components"]["citations"] = citation_points
        else:
            details["components"]["citations"] = 0.0
            details["missing_citations"] = sorted(required_citations - valid_citations)
        if invalid_citations:
            points -= invalid_penalty
            details["components"]["invalid_citation_penalty"] = -invalid_penalty

        combined_text = _normalize(
            " ".join(str(action.get(key, "")) for key in ("title", "analysis", "recommendation"))
        )
        concepts = [_normalize(item) for item in criterion.get("required_concepts", [])]
        concept_points = float(criterion.get("concept_points", 0.5))
        if concepts:
            matched = [concept for concept in concepts if concept in combined_text]
            awarded = concept_points * (len(matched) / len(concepts))
            points += awarded
            details["components"]["concepts"] = awarded
            details["matched_concepts"] = matched
        else:
            details["components"]["concepts"] = 0.0

        quote_delta, quote_details = self._score_quotes(action.get("quotes", []), criterion)
        points += quote_delta
        details["components"]["quotes"] = quote_delta
        if quote_details:
            details["quotes"] = quote_details

        for pattern in criterion.get("critical_failure_patterns", []):
            if re.search(pattern, combined_text, flags=re.IGNORECASE):
                self.state.critical_failure = True
                details["critical_failure_pattern"] = pattern

        return self._record(points, "issue", rubric_id, details)

    def _score_quotes(
        self, quotes: list[Any], criterion: dict[str, Any]
    ) -> tuple[float, list[dict[str, Any]]]:
        """Verify quotations verbatim against their cited sections.

        A verified quotation earns ``quote_points`` once per issue. A quotation that
        cannot be found in the cited section is fabricated: critical failure plus a
        penalty for each fabrication.
        """
        delta = 0.0
        details: list[dict[str, Any]] = []
        verified = False
        for quote in quotes:
            citation = str(quote.get("citation", "")) if isinstance(quote, dict) else ""
            text = str(quote.get("text", "")) if isinstance(quote, dict) else str(quote)
            normalized = _normalize(text)
            if len(normalized) < MINIMUM_QUOTE_CHARACTERS:
                details.append({"citation": citation, "status": "ignored_too_short"})
                continue
            section_text = self._resolve_citation(citation)
            if section_text is not None and normalized in _normalize(section_text):
                verified = True
                details.append({"citation": citation, "status": "verified"})
            else:
                self.state.critical_failure = True
                self.state.fabricated_quotes.append(citation or normalized[:60])
                delta -= 1.0
                details.append({"citation": citation, "status": "fabricated"})
        if verified:
            delta += float(criterion.get("quote_points", 0.25))
        return delta, details

    # ------------------------------------------------------------------ redlines

    def score_redline(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        label = str(action.get("issue_id", ""))
        target = f"{action.get('document_id')} §{action.get('section')}"
        rubric_id = self.state.issue_labels.get(label)
        if rubric_id is None:
            criterion = self.anchor_map.get(target)
            rubric_id = str(criterion["id"]) if criterion else None
        if rubric_id is None or rubric_id not in self.issue_map:
            return self._record(
                -0.5,
                "unsupported_redline",
                label,
                {"reason": "redline matches no submitted issue label and no operative anchor"},
            )
        criterion = self.issue_map[rubric_id]
        if rubric_id in self.state.matched_redlines:
            return self._record(-0.2, "duplicate_redline", rubric_id)
        self.state.matched_redlines.add(rubric_id)

        redline = _normalize(action.get("replacement_text", ""))
        details: dict[str, Any] = {"criterion": rubric_id}
        for pattern in criterion.get("redline_critical_failure_patterns", []):
            if re.search(pattern, redline, flags=re.IGNORECASE):
                self.state.critical_failure = True
                details["critical_failure_pattern"] = pattern

        required = [_normalize(item) for item in criterion.get("redline_concepts", [])]
        redline_points = float(criterion.get("redline_points", 1.0))
        if not required or redline_points == 0.0:
            return self._record(0.0, "unscored_redline", rubric_id, details)
        matched = [concept for concept in required if concept in redline]
        details["matched_redline_concepts"] = matched
        points = redline_points * (len(matched) / len(required))
        return self._record(points, "redline", rubric_id, details)

    # --------------------------------------------------------------------- final

    def score_final(self, summary: str) -> tuple[float, dict[str, Any]]:
        config = self.rubric.get("final_submission", {})
        points = float(config.get("points", 0.5))
        if len(summary.strip()) < int(config.get("minimum_characters", 80)):
            points = 0.0
        required_issue_ids = set(config.get("required_issue_ids", []))
        missing = sorted(required_issue_ids - self.state.matched_issues)
        if missing:
            points -= float(config.get("missing_required_issue_penalty", 0.25)) * len(missing)
        return self._record(points, "final_submission", "final", {"missing_issues": missing})

    # -------------------------------------------------------------------- result

    def result(
        self, *, terminated: bool, truncated: bool, steps: int, matter_id: str
    ) -> dict[str, Any]:
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
                "questions_asked_total": self.state.questions_asked_total,
                "matched_issues": sorted(self.state.matched_issues),
                "matched_redlines": sorted(self.state.matched_redlines),
                "valid_citation_count": self.state.valid_citation_count,
                "invalid_citations": self.state.invalid_citations,
                "unsupported_issues": self.state.unsupported_issues,
                "fabricated_quotes": self.state.fabricated_quotes,
                "reward_events": self.state.events,
            },
        }

    # ------------------------------------------------------------------- helpers

    def _resolve_citation(self, citation: str) -> str | None:
        if "§" not in citation:
            return None
        document_id, section = [part.strip() for part in citation.split("§", maxsplit=1)]
        document = self.documents.get(document_id)
        if document and section in document["sections"]:
            return document["sections"][section]
        return None

    def _validate_citations(self, citations: list[str]) -> tuple[set[str], list[str]]:
        valid: set[str] = set()
        invalid: list[str] = []
        for citation in citations:
            if self._resolve_citation(citation) is not None:
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
            total += float(issue.get("quote_points", 0.25))
            total += float(issue.get("redline_points", 1.0))
        total += float(self.rubric.get("final_submission", {}).get("points", 0.5))
        return total
