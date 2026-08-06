# SPDX-License-Identifier: AGPL-3.0-only

"""The critic: deterministic verification of proposed deal-review work.

Playbook's reward engine can score an episode only because it holds the answer key —
the rubric, the hidden facts, and the counterparty script. A real client has none of
those. The critic is the deployable half of the same idea: it re-runs the *verifiable*
gates using nothing but materials a lawyer's client actually has, so proposed work
product can be checked before it leaves the building.

Firewall
--------

The critic never opens ``rubric.yaml``, ``hidden_facts.yaml``, or ``counterparty.yaml``,
and never constructs :class:`~playbook_legal.env.PlaybookEnv` — building the environment
loads the rubric. It reads the matter's documents, the public fields of ``matter.yaml``,
and an optional user-supplied authority file. Delete the three answer-key files from a
matter directory and the critic reports exactly the same thing.

Filenames are compared the way a filesystem compares them, and no YAML file can be read
as a document, so neither ``RUBRIC.YAML`` nor a renamed copy gets in.

What it checks
--------------

- **Quotation verification.** Every quoted passage must appear verbatim in the cited
  section, under the reward engine's normalization (see :mod:`playbook_legal.text`).
- **Citation resolution.** Every cited provision must exist in the supplied documents,
  and a quotation with no citation resolves to nothing — which the engine also treats
  as a critical failure.
- **Prohibited concessions.** Proposed redline, markup, and settlement language is
  scanned against the client's stated limits using the engine's matching semantics:
  case-insensitive substring on whitespace-normalized text.
- **Evidence hygiene.** Unquoted issues, quotations below the engine's length floor,
  empty rationales, and summaries below a length floor.

What it deliberately does not do
--------------------------------

The critic makes no quality judgment and spots no issues. It verifies; it does not
lawyer. A submission that comes back clean may still be poor legal work — the critic
reports only what it can prove from the record in front of it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from .loaders import parse_sections
from .models import ActionType
from .rewards import MINIMUM_QUOTE_CHARACTERS
from .text import normalize_text

ANSWER_KEY_FILENAMES = frozenset({"rubric.yaml", "hidden_facts.yaml", "counterparty.yaml"})
AUTHORITY_SCHEMA_VERSION = "playbook.authority.v1"
REPORT_SCHEMA_VERSION = "playbook.critic-report.v1"
DEFAULT_MINIMUM_SUMMARY_CHARACTERS = 80

#: Every action type the environment defines. A submission whose lines name none of
#: them is not a trajectory, and saying so beats reviewing nothing and reporting clean.
KNOWN_ACTION_TYPES: frozenset[str] = frozenset(action.value for action in ActionType)
#: Top-level keys of a structured review. Same reasoning: an unrecognized shape is an
#: error, not an empty review.
REVIEW_KEYS: tuple[str, ...] = ("issues", "redlines", "markups", "settlements", "summary")

_SUBMIT_ACTIONS = frozenset({"submit_issue", "propose_redline"})
_ISSUE_ACTIONS = frozenset({"submit_issue", "revise_issue"})
_REDLINE_ACTIONS = frozenset({"propose_redline", "revise_redline"})
_CONCESSION_KINDS = frozenset({"redline", "markup", "settlement"})
_ACCEPTANCE_NOTE = (
    "the counterparty's language was accepted but is not in this submission; the critic "
    "will not read counterparty.yaml, so supply the closing text as a settlement to have "
    "it verified"
)


class CriticError(RuntimeError):
    """A record, submission, or authority file the critic cannot process."""


class AnswerKeyError(CriticError):
    """Raised when the critic is pointed at benchmark answer-key material."""


class Verdict(StrEnum):
    """Per-item outcomes. Everything but ``VERIFIED`` names a specific failure."""

    VERIFIED = "verified"
    FABRICATED_QUOTE = "FABRICATED_QUOTE"
    UNRESOLVED_CITATION = "UNRESOLVED_CITATION"
    PROHIBITED_CONCESSION = "PROHIBITED_CONCESSION"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


#: Verdicts that fail the run. ``MISSING_EVIDENCE`` is advisory: it reports work the
#: critic could not verify, not work it proved wrong.
CRITICAL_VERDICTS: frozenset[Verdict] = frozenset(
    {Verdict.FABRICATED_QUOTE, Verdict.UNRESOLVED_CITATION, Verdict.PROHIBITED_CONCESSION}
)

_VERDICT_PRECEDENCE: tuple[Verdict, ...] = (
    Verdict.FABRICATED_QUOTE,
    Verdict.PROHIBITED_CONCESSION,
    Verdict.UNRESOLVED_CITATION,
    Verdict.MISSING_EVIDENCE,
    Verdict.VERIFIED,
)


# ----------------------------------------------------------------------- file access


def canonical_filename(name: str) -> str:
    """Fold a filename the way the filesystem folds it before opening.

    Comparing raw basenames is not enough: Windows opens ``RUBRIC.YAML``,
    ``rubric.yaml.``, ``rubric.yaml   `` and ``rubric.yaml:$DATA`` as the same file, so
    a case-sensitive equality test is a firewall with a door in it.
    """
    return name.split(":", maxsplit=1)[0].strip().rstrip(". ").casefold()


def guard_path(path: str | Path) -> Path:
    """Return ``path`` unless it names benchmark answer-key material.

    Every read the critic performs goes through this gate, so a manifest entry, an
    ``--authority`` argument, or a submission path pointing at the answer key fails
    loudly instead of quietly contaminating the verification.
    """
    file_path = Path(path)
    if canonical_filename(file_path.name) in ANSWER_KEY_FILENAMES:
        raise AnswerKeyError(
            f"refusing to open answer-key material: {file_path.name}. The critic verifies "
            "work from client materials only."
        )
    return file_path


def _read_text(path: str | Path) -> str:
    """Read a client file. ``utf-8-sig`` because client material comes from Windows.

    A byte-order mark is invisible in an editor and ruinous here: it hides the first
    ``## `` heading from the section parser, so every citation into that document stops
    resolving, and it makes the first line of a JSONL submission unparseable. Files
    without a BOM decode identically either way.
    """
    file_path = guard_path(path)
    try:
        return file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CriticError(
            f"cannot read {file_path}: it is not UTF-8 text ({exc.reason} at byte {exc.start}). "
            "Re-save the file as UTF-8."
        ) from exc
    except OSError as exc:
        raise CriticError(f"cannot read {file_path}: {exc}") from exc


def _read_document(path: str | Path) -> str:
    """Read one document of the record. Documents are text; answer keys are YAML.

    Renaming ``rubric.yaml`` defeats a filename check, so the record refuses YAML as
    evidence outright. Nothing the critic verifies against can be a serialized answer key.
    """
    file_path = Path(path)
    if file_path.suffix.casefold() in {".yaml", ".yml"}:
        raise AnswerKeyError(
            f"refusing to read {file_path.name} as a document: documents are text, and every "
            "benchmark answer key is YAML. Point the manifest at the paper itself."
        )
    return _read_text(file_path)


def _read_yaml(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    try:
        data = yaml.safe_load(_read_text(file_path))
    except yaml.YAMLError as exc:
        raise CriticError(f"cannot parse {file_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CriticError(f"expected a YAML mapping in {file_path}")
    return data


# --------------------------------------------------------------------- client record


@dataclass(frozen=True)
class ClientRecord:
    """The documents the critic is allowed to see, addressed the way the engine cites."""

    root: Path
    matter_id: str
    title: str
    documents: dict[str, dict[str, Any]]

    @classmethod
    def from_directory(cls, directory: str | Path) -> ClientRecord:
        """Load a matter directory or a bare directory of documents.

        When ``matter.yaml`` is present its document manifest and public identifiers are
        used — and nothing else from it. Otherwise every ``*.md`` file in ``documents/``,
        or in the directory itself, becomes a document whose id is the file stem.
        """
        root = Path(directory)
        if not root.is_dir():
            raise CriticError(f"not a directory: {root}")

        matter_path = root / "matter.yaml"
        matter_id = title = root.name
        entries: list[tuple[str, Path, str]] = []
        if matter_path.is_file():
            matter = _read_yaml(matter_path)
            matter_id = str(matter.get("matter_id", root.name))
            title = str(matter.get("title", matter_id))
            for entry in matter.get("documents", []) or []:
                if not isinstance(entry, dict):
                    raise CriticError(f"malformed document manifest entry in {matter_path}")
                document_id = str(entry.get("id", "")).strip()
                relative = str(entry.get("path", "")).strip()
                if not document_id or not relative:
                    raise CriticError(f"document manifest entry needs id and path in {matter_path}")
                entries.append((document_id, root / relative, str(entry.get("title", document_id))))
        if not entries:
            source = root / "documents" if (root / "documents").is_dir() else root
            entries = [(path.stem, path, path.stem) for path in sorted(source.glob("*.md"))]
        if not entries:
            raise CriticError(f"no documents found under {root}")

        documents: dict[str, dict[str, Any]] = {}
        for document_id, path, document_title in entries:
            if document_id in documents:
                raise CriticError(f"duplicate document id: {document_id}")
            documents[document_id] = {
                "id": document_id,
                "title": document_title,
                "path": str(path),
                "sections": parse_sections(_read_document(path)),
            }
        return cls(root=root, matter_id=matter_id, title=title, documents=documents)

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(self.documents)

    def resolve(self, citation: str) -> str | None:
        """Return the cited section's text, mirroring the engine's citation grammar."""
        if "§" not in str(citation):
            return None
        document_id, section = [part.strip() for part in str(citation).split("§", maxsplit=1)]
        document = self.documents.get(document_id)
        if document and section in document["sections"]:
            return document["sections"][section]
        return None

    def citation_problem(self, citation: str) -> str:
        """Explain, in one clause, why a citation does not resolve."""
        text = str(citation).strip()
        if not text:
            return "no provision was cited"
        if "§" not in text:
            return f"'{text}' is not in '<document_id> §<section>' form"
        document_id, section = [part.strip() for part in text.split("§", maxsplit=1)]
        if document_id not in self.documents:
            known = ", ".join(self.document_ids)
            return f"no document '{document_id}' in the record (documents: {known})"
        return f"document '{document_id}' has no section '{section}'"

    def locate(self, normalized_quote: str) -> str | None:
        """Return the first citation whose section contains an already-normalized quote.

        Numbered sections are searched in preference to the whole-document ``full``
        pseudo-section, so the answer is a pin cite. A document with no ``##`` headings
        has nothing *but* ``full``, though — a client's own deal folder often does — and
        for those the whole document is the only citable unit there is.
        """
        for document_id, document in self.documents.items():
            sections: dict[str, str] = document["sections"]
            pinnable = [key for key in sections if key != "full"] or list(sections)
            for section in pinnable:
                if normalized_quote in normalize_text(sections[section]):
                    return f"{document_id} §{section}"
        return None


# ------------------------------------------------------------------------- authority


@dataclass(frozen=True)
class AuthorityRule:
    """One stated limit, expressed as literal patterns rather than a legal standard."""

    rule_id: str
    description: str
    patterns: tuple[str, ...]
    applies_to: tuple[str, ...] = ()

    def applies(self, citations: Sequence[str]) -> bool:
        """Whether this rule is in scope for work targeting ``citations``.

        A rule without ``applies_to`` is scanned everywhere. A scoped rule is scanned
        against work targeting one of its provisions — and against uncited work, which
        cannot be scoped out.
        """
        if not self.applies_to or not citations:
            return True
        targets = {normalize_text(item) for item in self.applies_to}
        return any(normalize_text(item) in targets for item in citations)

    def hits(self, normalized_text: str) -> tuple[str, ...]:
        """Patterns matching ``normalized_text`` under the engine's substring semantics."""
        return tuple(item for item in self.patterns if normalize_text(item) in normalized_text)


@dataclass(frozen=True)
class Authority:
    """A client's negotiating authority, as the client itself could state it."""

    source: str
    non_negotiables: tuple[AuthorityRule, ...] = ()
    approved_fallbacks: tuple[AuthorityRule, ...] = ()


def _load_rules(raw: Any, pattern_key: str, path: Path) -> tuple[AuthorityRule, ...]:
    rules: list[AuthorityRule] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            raise CriticError(f"{path}: every authority rule must be a mapping")
        rule_id = str(entry.get("id", "")).strip()
        if not rule_id:
            raise CriticError(f"{path}: every authority rule needs an id")
        patterns = [str(item) for item in entry.get(pattern_key, []) or []]
        if not patterns or any(not normalize_text(item) for item in patterns):
            raise CriticError(f"{path}: rule '{rule_id}' needs non-empty {pattern_key}")
        rules.append(
            AuthorityRule(
                rule_id=rule_id,
                description=str(entry.get("description", "")).strip(),
                patterns=tuple(patterns),
                applies_to=tuple(str(item).strip() for item in entry.get("applies_to", []) or []),
            )
        )
    identifiers = [rule.rule_id for rule in rules]
    if len(set(identifiers)) != len(identifiers):
        raise CriticError(f"{path}: duplicate authority rule id")
    return tuple(rules)


def load_authority(path: str | Path) -> Authority:
    """Load a ``playbook.authority.v1`` file — the client's limits, written as patterns."""
    file_path = Path(path)
    data = _read_yaml(file_path)
    version = str(data.get("schema_version", ""))
    if version != AUTHORITY_SCHEMA_VERSION:
        raise CriticError(
            f"authority schema_version must be {AUTHORITY_SCHEMA_VERSION!r}, got {version!r}"
        )
    non_negotiables = _load_rules(data.get("non_negotiables"), "prohibited_patterns", file_path)
    fallbacks = _load_rules(data.get("approved_fallbacks"), "permitted_patterns", file_path)
    if not non_negotiables and not fallbacks:
        raise CriticError(f"{file_path}: declares neither non_negotiables nor approved_fallbacks")
    return Authority(
        source=str(data.get("source") or file_path.name),
        non_negotiables=non_negotiables,
        approved_fallbacks=fallbacks,
    )


# ------------------------------------------------------------------------ submission


@dataclass(frozen=True)
class ReviewItem:
    """One reviewable unit of proposed work, in the critic's own vocabulary."""

    kind: str
    ref: str
    source: str
    citations: tuple[str, ...] = ()
    quotes: tuple[tuple[str, str], ...] = ()
    proposed_text: str = ""
    rationale: str = ""
    requires_quote: bool = False
    requires_rationale: bool = False
    unreviewable: str = ""


@dataclass(frozen=True)
class Submission:
    """Proposed work product, normalized away from its wire format."""

    path: Path
    format: str
    items: tuple[ReviewItem, ...]


def _as_list(value: Any) -> list[Any]:
    """Treat a scalar where a list belongs as a one-element list.

    ``{"citations": "msa §4.2"}`` is a plausible mistake, and ``list()`` on a string
    would shred it into characters and report one unresolved citation per letter.
    """
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _citations(payload: dict[str, Any]) -> tuple[str, ...]:
    raw = _as_list(payload.get("citations"))
    if not raw and payload.get("citation"):
        raw = [payload["citation"]]
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _target_citation(payload: dict[str, Any]) -> str:
    citation = str(payload.get("citation", "")).strip()
    if citation:
        return citation
    document_id = str(payload.get("document_id", "")).strip()
    section = str(payload.get("section", "")).strip()
    return f"{document_id} §{section}" if document_id and section else ""


def _quotes(payload: dict[str, Any], default_citation: str = "") -> tuple[tuple[str, str], ...]:
    raw = _as_list(payload.get("quotes"))
    if not raw and payload.get("quote"):
        raw = [payload["quote"]]
    quotes: list[tuple[str, str]] = []
    for entry in raw:
        if isinstance(entry, dict):
            citation = str(entry.get("citation", "") or default_citation).strip()
            quotes.append((citation, str(entry.get("text", ""))))
        else:
            quotes.append((default_citation, str(entry)))
    # An empty quotation is kept, not dropped: the engine penalizes it as unverifiable
    # and the critic reports it the same way, below the length floor.
    return tuple(quotes)


def _issue_item(
    payload: dict[str, Any], source: str, *, pair_quotes: bool, default_ref: str = ""
) -> ReviewItem:
    citations = _citations(payload)
    default_citation = citations[0] if (pair_quotes and citations) else ""
    rationale = " ".join(
        str(payload.get(key, "")).strip()
        for key in ("rationale", "analysis", "recommendation")
        if str(payload.get(key, "")).strip()
    )
    label = payload.get("issue_id") or payload.get("id") or payload.get("title")
    ref = str(label or default_ref or source)
    return ReviewItem(
        kind="issue",
        ref=ref,
        source=source,
        citations=citations,
        quotes=_quotes(payload, default_citation),
        rationale=rationale,
        requires_quote=True,
        requires_rationale=True,
    )


def _drafting_item(payload: dict[str, Any], source: str, kind: str) -> ReviewItem:
    citation = _target_citation(payload)
    text = next(
        (
            str(payload[key])
            for key in ("replacement_text", "proposed_text", "closing_text", "text")
            if str(payload.get(key, "")).strip()
        ),
        "",
    )
    label = payload.get("issue_id") or payload.get("issue") or payload.get("id")
    ref = str(label or citation or source)
    return ReviewItem(
        kind=kind,
        ref=ref,
        source=source,
        citations=(citation,) if citation else (),
        proposed_text=text,
        rationale=str(payload.get("rationale", "")),
        requires_rationale=kind == "redline",
    )


def _summary_item(text: str, source: str) -> ReviewItem:
    return ReviewItem(kind="summary", ref="final summary", source=source, rationale=str(text))


def _items_from_actions(actions: Sequence[tuple[int, dict[str, Any]]]) -> list[ReviewItem]:
    """Turn a trajectory into reviewable items, keeping only the latest revision.

    ``revise_issue`` and ``revise_redline`` are additive in a canonical trace but
    substitutive for review, exactly as the environment treats them for scoring: the
    latest version occupies the position of the version it replaces.

    Only the ``revise_*`` actions do that. A second ``submit_issue`` under a label that
    was already used is a *new* submission the environment scores separately, so it gets
    its own item — collapsing the two would let a fabricated quotation be laundered by
    re-submitting the same label with a clean quotation afterwards.
    """
    items: list[ReviewItem] = []
    slots: dict[tuple[str, ...], int] = {}

    def place(key: tuple[str, ...], item: ReviewItem, *, replaces: bool) -> None:
        if replaces and key in slots:
            items[slots[key]] = item
            return
        # The environment revises the earliest submission carrying the label, so the
        # first occupant of a key stays the revision target.
        slots.setdefault(key, len(items))
        items.append(item)

    for number, action in actions:
        action_type = str(action.get("type", "")).strip()
        source = f"line {number}: {action_type or 'unknown'}"
        revises = action_type not in _SUBMIT_ACTIONS
        if action_type in _ISSUE_ACTIONS:
            item = _issue_item(action, source, pair_quotes=False)
            place(("issue", item.ref), item, replaces=revises)
        elif action_type in _REDLINE_ACTIONS:
            item = _drafting_item(action, source, "redline")
            place(("redline", item.ref, *item.citations), item, replaces=revises)
        elif action_type == "send_markup":
            place(("markup", str(number)), _drafting_item(action, source, "markup"), replaces=False)
        elif action_type == "accept_counterparty":
            label = str(action.get("issue_id") or f"acceptance {number}")
            place(
                ("acceptance", str(number)),
                ReviewItem(
                    kind="acceptance", ref=label, source=source, unreviewable=_ACCEPTANCE_NOTE
                ),
                replaces=False,
            )
        elif action_type == "submit_final":
            place(("summary",), _summary_item(action.get("summary", ""), source), replaces=True)
    return items


def _require_mapping(entry: Any, where: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise CriticError(f"{where} must be a JSON object")
    return entry


def _unrecognized(path: Path, saw: str) -> CriticError:
    """The submission parsed, but nothing in it is reviewable. Say so; never pass it."""
    return CriticError(
        f"{path}: nothing reviewable found — {saw}. A structured review JSON needs at least "
        f"one of: {', '.join(REVIEW_KEYS)}. An actions submission needs one JSON action per "
        f"line with a 'type' from: {', '.join(sorted(KNOWN_ACTION_TYPES))}."
    )


def _items_from_review(payload: dict[str, Any], path: Path) -> list[ReviewItem]:
    if not any(key in payload for key in REVIEW_KEYS):
        keys = ", ".join(sorted(str(key) for key in payload)[:8]) or "(none)"
        raise _unrecognized(path, f"top-level keys were {keys}")
    items: list[ReviewItem] = []
    for index, entry in enumerate(payload.get("issues") or [], 1):
        where = f"issues[{index}]"
        items.append(
            _issue_item(
                _require_mapping(entry, where),
                where,
                pair_quotes=True,
                default_ref=f"issue {index}",
            )
        )
    drafting = (("redlines", "redline"), ("markups", "markup"), ("settlements", "settlement"))
    for key, kind in drafting:
        for index, entry in enumerate(payload.get(key) or [], 1):
            where = f"{key}[{index}]"
            items.append(_drafting_item(_require_mapping(entry, where), where, kind))
    if "summary" in payload:
        items.append(_summary_item(payload.get("summary") or "", "summary"))
    return items


def _read_jsonl(text: str, path: Path) -> list[tuple[int, dict[str, Any]]]:
    actions: list[tuple[int, dict[str, Any]]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            action = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CriticError(f"{path} line {number} is not valid JSON: {exc}") from exc
        if not isinstance(action, dict):
            raise CriticError(f"{path} line {number} is not a JSON object")
        actions.append((number, action))
    if not actions:
        raise CriticError(f"{path} contains no actions")
    return actions


def _require_known_actions(actions: Sequence[tuple[int, dict[str, Any]]], path: Path) -> None:
    """Refuse a trajectory whose lines name no action the environment defines."""
    if not actions:
        raise CriticError(f"{path} contains no actions")
    seen = {str(action.get("type", "")).strip() for _, action in actions}
    if seen & KNOWN_ACTION_TYPES:
        return
    named = ", ".join(sorted(item for item in seen if item)) or "(no 'type' field)"
    raise _unrecognized(path, f"action types were {named}")


def load_submission(path: str | Path) -> Submission:
    """Load proposed work, auto-detecting an actions JSONL or a structured review JSON.

    A whole-file JSON object without a ``type`` key is a structured review; anything
    else is read as trajectory actions, one JSON object per line. Either way, a
    submission that never states a final summary still gets a summary item, so the
    omission is reported rather than silently passing.
    """
    file_path = Path(path)
    text = _read_text(file_path)
    if not text.strip():
        raise CriticError(f"{file_path} is empty")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict) and "type" not in payload:
        items, submission_format = _items_from_review(payload, file_path), "review"
    else:
        if isinstance(payload, dict):
            numbered = [(1, payload)]
        elif isinstance(payload, list):
            numbered = [
                (index, _require_mapping(entry, f"{file_path} entry {index}"))
                for index, entry in enumerate(payload, 1)
            ]
        else:
            numbered = _read_jsonl(text, file_path)
        _require_known_actions(numbered, file_path)
        items, submission_format = _items_from_actions(numbered), "actions"

    if not any(item.kind == "summary" for item in items):
        items.append(_summary_item("", "(absent)"))
    return Submission(path=file_path, format=submission_format, items=tuple(items))


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Finding:
    """One thing the critic can say about one item, with the evidence for saying it."""

    verdict: Verdict
    kind: str
    ref: str
    source: str
    message: str
    citation: str = ""
    quote: str = ""
    authority_id: str = ""
    pattern: str = ""

    @property
    def critical(self) -> bool:
        return self.verdict in CRITICAL_VERDICTS

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "verdict": self.verdict.value,
            "critical": self.critical,
            "item_kind": self.kind,
            "item": self.ref,
            "source": self.source,
            "message": self.message,
        }
        for key in ("citation", "quote", "authority_id", "pattern"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class CriticReport:
    """The verification result: every item, every finding, and whether the run passes."""

    matter_id: str
    record_root: str
    submission: str
    submission_format: str
    authority_source: str
    documents: tuple[str, ...]
    items: tuple[dict[str, Any], ...]
    findings: tuple[Finding, ...]
    verified_quotes: int
    minimum_summary_characters: int

    @property
    def critical_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.critical)

    @property
    def passed(self) -> bool:
        """True when no critical category fired. Advisory findings do not fail a run."""
        return not self.critical_findings

    def verdicts(self) -> set[Verdict]:
        return {finding.verdict for finding in self.findings}

    def counts(self) -> dict[str, int]:
        counts = {verdict.value: 0 for verdict in _VERDICT_PRECEDENCE}
        for finding in self.findings:
            counts[finding.verdict.value] += 1
        counts[Verdict.VERIFIED.value] = sum(
            1 for item in self.items if item["verdict"] == Verdict.VERIFIED.value
        )
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "matter_id": self.matter_id,
            "record_root": self.record_root,
            "submission": self.submission,
            "submission_format": self.submission_format,
            "authority_source": self.authority_source,
            "documents": list(self.documents),
            "minimum_summary_characters": self.minimum_summary_characters,
            "passed": self.passed,
            "verified_quotes": self.verified_quotes,
            "counts": self.counts(),
            "items": [dict(item) for item in self.items],
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_markdown(self) -> str:
        counts = self.counts()
        critical = len(self.critical_findings)
        headline = (
            f"**{critical} critical finding{'s' if critical != 1 else ''} — this work product "
            "does not verify.**"
            if critical
            else "**No critical findings — everything the critic can check, checks out.**"
        )
        lines = [
            f"# Critic report — {self.matter_id}",
            "",
            headline,
            "",
            f"- Submission: `{self.submission}` ({self.submission_format} format)",
            f"- Documents: {', '.join(f'`{name}`' for name in self.documents)}",
            f"- Authority file: {self.authority_source or 'none supplied'}",
            f"- Verified quotations: {self.verified_quotes}",
            "",
            "| Category | Count |",
            "| --- | --- |",
        ]
        lines.extend(f"| {name} | {count} |" for name, count in counts.items())
        lines.extend(["", "## Items", ""])
        for item in self.items:
            lines.append(f"### {item['kind']} `{item['ref']}` — {item['verdict']}")
            lines.append(f"_{item['source']}_")
            for finding in item["findings"]:
                detail = finding["message"]
                if finding.get("citation"):
                    detail = f"({finding['citation']}) {detail}"
                if finding.get("pattern"):
                    detail = f"{detail} — matched pattern `{finding['pattern']}`"
                lines.append(f"- **{finding['verdict']}**: {detail}")
                if finding.get("quote"):
                    lines.append(f"  > {finding['quote']}")
            for allowed in item["within_authority"]:
                lines.append(
                    f"- within stated authority: `{allowed['id']}` "
                    f"(matched `{allowed['pattern']}`)"
                )
            if not item["findings"] and not item["within_authority"]:
                lines.append("- nothing to report")
            lines.append("")
        scope = (
            "The critic verifies; it does not lawyer. It reads the matter's documents, the "
            "public fields of `matter.yaml`, and the supplied authority file — never a rubric, "
            "hidden facts, or a counterparty script. A clean report is not an opinion that the "
            "work is good."
        )
        lines.extend(["---", "", scope])
        return "\n".join(lines)


# ---------------------------------------------------------------------------- checks


def _finding(item: ReviewItem, verdict: Verdict, message: str, **extra: str) -> Finding:
    return Finding(
        verdict=verdict,
        kind=item.kind,
        ref=item.ref,
        source=item.source,
        message=message,
        **extra,
    )


def _excerpt(text: str, limit: int = 160) -> str:
    normalized = normalize_text(text)
    return normalized if len(normalized) <= limit else f"{normalized[:limit].rstrip()}..."


#: Characters a word processor substitutes silently. Folding them is for *explaining* a
#: near miss only — never for deciding one. The engine compares literal text, so a
#: quotation retyped with curly quotes is fabricated there and must be fabricated here.
_TYPOGRAPHIC_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "«": '"',
        "»": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
    }
)
_ELLIPSIS_MARKS = ("…", "...", ". . .", "[...]")


def _quote_hint(quote: str, section_text: str) -> str:
    """Name the likely cause of a near miss, without softening the verdict."""
    normalized = normalize_text(quote)
    haystack = normalize_text(section_text)
    if normalized.translate(_TYPOGRAPHIC_FOLD) in haystack.translate(_TYPOGRAPHIC_FOLD):
        return (
            "; it differs from the cited text only in typography (curly quotes, dashes), and "
            "verification is literal — paste the passage straight from the document"
        )
    if any(mark in quote for mark in _ELLIPSIS_MARKS):
        return (
            "; the quotation elides text, and verification is verbatim — quote one contiguous "
            "passage instead"
        )
    return ""


def _check_citations(record: ClientRecord, item: ReviewItem) -> list[Finding]:
    """Every cited provision must exist in the supplied documents."""
    return [
        _finding(
            item,
            Verdict.UNRESOLVED_CITATION,
            f"cited provision does not resolve: {record.citation_problem(citation)}",
            citation=citation,
        )
        for citation in item.citations
        if record.resolve(citation) is None
    ]


def _check_quotes(record: ClientRecord, item: ReviewItem) -> tuple[list[Finding], int]:
    """Verify quotations exactly as the engine's fabrication gate does.

    The engine collapses "the citation does not resolve" into the same fabrication
    gate as "the text is not there". The critic separates them — both are critical,
    but only one of them is fixable by re-citing.

    A quotation with no citation at all is in the first bucket, never in neither: the
    engine cannot resolve an empty citation and fails the episode for it, so calling it
    advisory here would green-light work the benchmark critically fails.
    """
    findings: list[Finding] = []
    verified = 0
    for citation, text in item.quotes:
        normalized = normalize_text(text)
        excerpt = _excerpt(text)
        if len(normalized) < MINIMUM_QUOTE_CHARACTERS:
            findings.append(
                _finding(
                    item,
                    Verdict.MISSING_EVIDENCE,
                    f"quotation is below the {MINIMUM_QUOTE_CHARACTERS}-character floor the "
                    "engine requires before it will verify a quotation",
                    citation=citation,
                    quote=excerpt,
                )
            )
            continue
        if not citation:
            located = record.locate(normalized)
            findings.append(
                _finding(
                    item,
                    Verdict.UNRESOLVED_CITATION if located else Verdict.FABRICATED_QUOTE,
                    f"quotation carries no citation, so nothing verifies it; the text does "
                    f"appear at {located} — cite that provision"
                    if located
                    else "quotation carries no citation and appears in no supplied document",
                    quote=excerpt,
                )
            )
            continue
        section_text = record.resolve(citation)
        if section_text is None:
            findings.append(
                _finding(
                    item,
                    Verdict.UNRESOLVED_CITATION,
                    f"quotation cannot be verified: {record.citation_problem(citation)}",
                    citation=citation,
                    quote=excerpt,
                )
            )
            continue
        if normalized in normalize_text(section_text):
            verified += 1
            continue
        located = record.locate(normalized)
        message = "quotation does not appear verbatim in the cited section"
        if located:
            message += f"; the same text appears at {located} — cite that provision"
        else:
            message += _quote_hint(text, section_text)
        findings.append(
            _finding(item, Verdict.FABRICATED_QUOTE, message, citation=citation, quote=excerpt)
        )
    return findings, verified


def _check_hygiene(item: ReviewItem, minimum_summary_characters: int) -> list[Finding]:
    """Report work whose own evidence is missing, before anything else is claimed."""
    findings: list[Finding] = []
    if item.unreviewable:
        findings.append(_finding(item, Verdict.MISSING_EVIDENCE, item.unreviewable))
    if item.requires_quote and not item.quotes:
        findings.append(
            _finding(
                item,
                Verdict.MISSING_EVIDENCE,
                "no verbatim quotation supports this issue, so none of it can be verified",
            )
        )
    if item.requires_rationale and not item.rationale.strip():
        findings.append(_finding(item, Verdict.MISSING_EVIDENCE, "no rationale was given"))
    if item.kind in _CONCESSION_KINDS and not item.proposed_text.strip():
        findings.append(
            _finding(item, Verdict.MISSING_EVIDENCE, f"{item.kind} states no operative language")
        )
    if item.kind == "summary":
        length = len(item.rationale.strip())
        if length < minimum_summary_characters:
            findings.append(
                _finding(
                    item,
                    Verdict.MISSING_EVIDENCE,
                    f"final summary is {length} characters, below the "
                    f"{minimum_summary_characters}-character floor",
                )
            )
    return findings


def _check_concessions(
    authority: Authority | None, item: ReviewItem
) -> tuple[list[Finding], list[dict[str, str]]]:
    """Scan proposed language for prohibited patterns, using the engine's semantics.

    Matching is case-insensitive substring on whitespace-normalized text — the same
    rule the engine applies to settlement and redline concepts, unanchored and
    unstemmed, so ``30 days`` matches inside ``130 days``. Matching an approved
    fallback is reported as context; it never cancels a prohibited hit.
    """
    if authority is None or item.kind not in _CONCESSION_KINDS or not item.proposed_text.strip():
        return [], []
    normalized = normalize_text(item.proposed_text)
    findings: list[Finding] = []
    for rule in authority.non_negotiables:
        if not rule.applies(item.citations):
            continue
        for pattern in rule.hits(normalized):
            message = f"proposed language concedes '{rule.rule_id}'"
            if rule.description:
                message = f"{message}: {rule.description}"
            findings.append(
                _finding(
                    item,
                    Verdict.PROHIBITED_CONCESSION,
                    message,
                    authority_id=rule.rule_id,
                    pattern=pattern,
                )
            )
    within = [
        {"id": rule.rule_id, "pattern": pattern}
        for rule in authority.approved_fallbacks
        if rule.applies(item.citations)
        for pattern in rule.hits(normalized)
    ]
    return findings, within


def _item_verdict(findings: Sequence[Finding]) -> Verdict:
    """The most serious verdict an item earned, or ``VERIFIED`` when it earned none."""
    verdicts = {finding.verdict for finding in findings}
    for verdict in _VERDICT_PRECEDENCE:
        if verdict in verdicts:
            return verdict
    return Verdict.VERIFIED


def _dedupe(findings: Sequence[Finding]) -> list[Finding]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[Finding] = []
    for finding in findings:
        # The quote belongs in the key: two different fabrications under one citation
        # share a message, and dropping the second would hide half the evidence.
        key = (
            finding.verdict,
            finding.ref,
            finding.citation,
            finding.message,
            finding.pattern,
            finding.quote,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def review(
    record: ClientRecord,
    submission: Submission,
    authority: Authority | None = None,
    *,
    minimum_summary_characters: int = DEFAULT_MINIMUM_SUMMARY_CHARACTERS,
) -> CriticReport:
    """Verify a submission against the client record and, optionally, stated authority."""
    reviewed: list[dict[str, Any]] = []
    findings: list[Finding] = []
    verified_quotes = 0
    for item in submission.items:
        quote_findings, verified = _check_quotes(record, item)
        verified_quotes += verified
        concessions, within_authority = _check_concessions(authority, item)
        item_findings = _dedupe(
            [
                *_check_citations(record, item),
                *quote_findings,
                *_check_hygiene(item, minimum_summary_characters),
                *concessions,
            ]
        )
        reviewed.append(
            {
                "kind": item.kind,
                "ref": item.ref,
                "source": item.source,
                "verdict": _item_verdict(item_findings).value,
                "citations": list(item.citations),
                "within_authority": within_authority,
                "findings": [finding.to_dict() for finding in item_findings],
            }
        )
        findings.extend(item_findings)
    return CriticReport(
        matter_id=record.matter_id,
        record_root=str(record.root),
        submission=str(submission.path),
        submission_format=submission.format,
        authority_source=authority.source if authority else "",
        documents=record.document_ids,
        items=tuple(reviewed),
        findings=tuple(findings),
        verified_quotes=verified_quotes,
        minimum_summary_characters=minimum_summary_characters,
    )


def critique(
    record_dir: str | Path,
    submission_path: str | Path,
    *,
    authority_path: str | Path | None = None,
    minimum_summary_characters: int = DEFAULT_MINIMUM_SUMMARY_CHARACTERS,
) -> CriticReport:
    """Load a record, a submission, and optional authority, then verify in one call."""
    return review(
        ClientRecord.from_directory(record_dir),
        load_submission(submission_path),
        load_authority(authority_path) if authority_path else None,
        minimum_summary_characters=minimum_summary_characters,
    )


# ------------------------------------------------------------------------------- cli


def _print(text: str) -> None:
    """Print a report without dying on a console that cannot encode '§'."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "") or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def write_report(report: CriticReport, out: str | Path) -> tuple[Path, Path]:
    """Write ``<out>.json`` and ``<out>.md``, returning both paths."""
    stem = Path(out)
    if stem.is_dir():
        raise CriticError(
            f"--out takes a path prefix such as {Path(stem, 'critic')}, not an existing "
            f"directory: {stem}"
        )
    if stem.suffix in {".json", ".md"}:
        stem = stem.with_suffix("")
    if not stem.name:
        raise CriticError("--out needs a file-name prefix, for example reports/critic")
    json_path = stem.with_name(f"{stem.name}.json")
    markdown_path = stem.with_name(f"{stem.name}.md")
    try:
        stem.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(report.to_markdown() + "\n", encoding="utf-8")
    except OSError as exc:
        raise CriticError(f"cannot write the report to {stem.parent}: {exc}") from exc
    return json_path, markdown_path


def _summary_floor(value: str) -> int:
    """``--min-summary-chars`` type: a negative floor silently disables the check."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("a summary floor cannot be negative")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    """Verify proposed deal-review work. Exit 1 on any critical finding, 2 on bad input."""
    parser = argparse.ArgumentParser(
        prog="playbook-critic",
        description=(
            "Deterministically verify proposed deal-review work against the client's own "
            "documents. Never reads rubrics, hidden facts, or counterparty scripts."
        ),
    )
    parser.add_argument("record", type=Path, help="Matter directory or directory of documents")
    parser.add_argument("submission", type=Path, help="Actions JSONL or structured review JSON")
    parser.add_argument("--authority", type=Path, default=None, help="playbook.authority.v1 file")
    parser.add_argument("--out", type=Path, default=None, help="Write <out>.json and <out>.md")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Report format written to stdout (default: markdown)",
    )
    parser.add_argument(
        "--min-summary-chars",
        type=_summary_floor,
        default=DEFAULT_MINIMUM_SUMMARY_CHARACTERS,
        help=f"Summary length floor (default: {DEFAULT_MINIMUM_SUMMARY_CHARACTERS})",
    )
    args = parser.parse_args(argv)

    try:
        report = critique(
            args.record,
            args.submission,
            authority_path=args.authority,
            minimum_summary_characters=args.min_summary_chars,
        )
    except CriticError as exc:
        print(f"playbook-critic: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        _print(json.dumps(report.to_dict(), indent=2))
    else:
        _print(report.to_markdown())
    if args.out is not None:
        try:
            json_path, markdown_path = write_report(report, args.out)
        except CriticError as exc:
            print(f"playbook-critic: {exc}", file=sys.stderr)
            return 2
        _print(f"\nWrote {json_path} and {markdown_path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
