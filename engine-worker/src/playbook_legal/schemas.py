# SPDX-License-Identifier: AGPL-3.0-only

"""Action schemas for the Playbook environment.

The environment's native protocol is a structured action dictionary. This module
publishes the same contract in two forms:

- ``action_schemas()``: minimal JSON Schemas embedded in every observation, so the
  contract is fully observable to any agent playing the environment; and
- ``tool_definitions()``: OpenAI-compatible ``tools`` entries, so chat models with
  function calling can play the environment natively via the baseline runner.
"""

from __future__ import annotations

from typing import Any

_ACTIONS: dict[str, dict[str, Any]] = {
    "read_document": {
        "description": (
            "Read a document from the matter file, either in full or one numbered section."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "Document id from the index."},
                "section": {
                    "type": "string",
                    "description": "Optional section number such as '4.2'. Omit for full text.",
                },
            },
            "required": ["document_id"],
        },
    },
    "search_matter": {
        "description": "Case-insensitive substring search across every document section.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search phrase, three or more characters."}
            },
            "required": ["query"],
        },
    },
    "ask_client": {
        "description": (
            "Ask the client one natural-language factual question. Every question consumes "
            "budget, so ask only questions that could change the negotiating position."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question, in plain language."}
            },
            "required": ["question"],
        },
    },
    "escalate": {
        "description": (
            "Escalate one point to the supervising lawyer or the client's decision maker. "
            "Every escalation consumes budget, so escalate only departures from a "
            "non-negotiable position or requests that exceed your authority."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Short label for the point escalated."},
                "reason": {
                    "type": "string",
                    "description": "Why this exceeds your authority or departs from the playbook.",
                },
            },
            "required": ["topic", "reason"],
        },
    },
    "submit_issue": {
        "description": (
            "Submit one material issue. Cite the single operative provision the issue targets "
            "as the FIRST citation, in the form '<document_id> §<section>'. Optional quotes "
            "must reproduce cited section text verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "Your own short label for this issue; reuse it in propose_redline.",
                },
                "title": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Provision citations such as 'msa §4.2'. Operative provision first.",
                },
                "analysis": {"type": "string"},
                "recommendation": {"type": "string"},
                "quotes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "citation": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["citation", "text"],
                    },
                    "description": (
                        "Optional verbatim quotations supporting the issue. Text must appear "
                        "verbatim in the cited section; paraphrase belongs in analysis."
                    ),
                },
            },
            "required": ["issue_id", "title", "severity", "citations", "analysis", "recommendation"],
        },
    },
    "propose_redline": {
        "description": (
            "Propose replacement language for one section. Target the operative provision of "
            "the issue; link it to your submitted issue by reusing your issue_id label."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Label of your submitted issue."},
                "document_id": {"type": "string"},
                "section": {"type": "string"},
                "replacement_text": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["issue_id", "document_id", "section", "replacement_text", "rationale"],
        },
    },
    "send_markup": {
        "description": (
            "Send proposed language for one section to the counterparty and receive their "
            "response. The counterparty answers deterministically: they accept, counter with "
            "their own language, or refuse. Each markup consumes a negotiation round."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Label of your submitted issue."},
                "document_id": {"type": "string"},
                "section": {"type": "string"},
                "proposed_text": {
                    "type": "string",
                    "description": "The language you are sending across the table.",
                },
            },
            "required": ["issue_id", "document_id", "section", "proposed_text"],
        },
    },
    "accept_counterparty": {
        "description": (
            "Accept the counterparty's outstanding counter-proposal for one issue and close "
            "the point on their language. Accepting language you should not accept is scored."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "Your label for the issue whose counter you are accepting.",
                }
            },
            "required": ["issue_id"],
        },
    },
    "submit_final": {
        "description": (
            "Submit the final summary for the supervising lawyer and end the episode. Submit "
            "only after all issues and redlines are in."
        ),
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
}

PROTOCOL: dict[str, str] = {
    "citation_format": "Cite provisions as '<document_id> §<section>', for example 'msa §4.2'.",
    "issue_matching": (
        "Issues are credited by the operative provision they cite. List the single provision "
        "your issue targets as the FIRST citation."
    ),
    "quotes": (
        "Optional 'quotes' entries must reproduce cited section text verbatim. A quotation "
        "that does not appear in the cited section is a critical failure."
    ),
    "questions": (
        "ask_client takes a natural-language question. Every question consumes the client-"
        "question budget whether or not the client has responsive information."
    ),
    "labels": (
        "issue_id is your own label. Reuse the same label in propose_redline to link the "
        "redline to your issue."
    ),
    "escalation": (
        "Escalations are budgeted. Escalate departures from non-negotiable positions and "
        "requests beyond your authority. Both failing to escalate and over-escalating are "
        "scored."
    ),
    "negotiation": (
        "send_markup is answered deterministically by the counterparty: they accept, counter, "
        "or refuse. Accepting counterparty language you should not accept is scored. Closing "
        "every issue is not required — standing firm on a non-negotiable position and flagging "
        "it in your final summary is correct."
    ),
}


def action_schemas() -> dict[str, dict[str, Any]]:
    """Return the action contract keyed by action name."""
    return {name: dict(spec) for name, spec in _ACTIONS.items()}


def tool_definitions(actions: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return the action contract as OpenAI-compatible tool definitions.

    ``actions`` restricts the contract to a subset — the environment filters out the
    negotiation actions on matters without a counterparty, and the baseline runner
    offers only what that matter actually supports.
    """
    specs = _ACTIONS if actions is None else actions
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for name, spec in specs.items()
    ]
