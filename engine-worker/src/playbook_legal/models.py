# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActionType(StrEnum):
    READ_DOCUMENT = "read_document"
    SEARCH_MATTER = "search_matter"
    ASK_CLIENT = "ask_client"
    ESCALATE = "escalate"
    SUBMIT_ISSUE = "submit_issue"
    REVISE_ISSUE = "revise_issue"
    PROPOSE_REDLINE = "propose_redline"
    REVISE_REDLINE = "revise_redline"
    SEND_MARKUP = "send_markup"
    ACCEPT_COUNTERPARTY = "accept_counterparty"
    SUBMIT_FINAL = "submit_final"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class TraceEvent:
    step: int
    action: dict[str, Any]
    observation: dict[str, Any]
    reward: float
    terminated: bool
    truncated: bool
    info: dict[str, Any]


@dataclass(slots=True)
class EpisodeResult:
    matter_id: str
    raw_score: float
    max_score: float
    normalized_score: float
    critical_failure: bool
    terminated: bool
    truncated: bool
    steps: int
    breakdown: dict[str, Any] = field(default_factory=dict)
