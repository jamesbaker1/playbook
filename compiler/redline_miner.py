"""Tracked-changes extractor for Word (.docx) files — stdlib only.

A ``.docx`` is an OPC package: a zip archive whose main part is normally
``word/document.xml``. Word records redlines *in that XML*, which makes a partner's
markup machine-readable without any diffing heuristics:

``w:ins``
    An insertion. Carries ``w:author``, ``w:date`` (ISO 8601), ``w:id``. Text lives
    in child ``w:r/w:t`` runs.
``w:del``
    A deletion. Same attributes; text lives in ``w:r/w:delText`` runs (Word renames
    the element so the text is not part of the accepted document).
``w:moveFrom`` / ``w:moveTo``
    A move, recorded as a matched deletion/insertion pair.
``w:comment`` (in ``word/comments.xml``)
    Margin comments, anchored in ``document.xml`` by ``w:commentRangeStart`` /
    ``w:commentRangeEnd`` / ``w:commentReference`` sharing a ``w:id``.

Revision elements nest: text inserted by one lawyer and then deleted by another is
``<w:ins><w:del><w:r><w:delText>``. Each revision element is therefore reported
exactly once, with the text that belongs to *it* — a nested deletion never leaks
into the enclosing insertion's ``inserted_text``.

Known limits, stated rather than hidden (see ``docs/matter-compiler.md`` §2.3):

- Clause numbers produced by ``numbering.xml`` (auto-numbered lists) do not appear
  in the paragraph text, so ``section_hint`` will be empty for those documents. It
  is a heuristic anchor, never authority: the emitter renumbers on the way out.
- Revision marks that carry no text (an inserted paragraph mark recorded in
  ``w:pPr/w:rPr/w:ins``) are dropped as non-substantive.
- Formatting-only revisions (``w:rPrChange``, ``w:pPrChange``, ``w:tblPrChange``)
  are not reported; they are almost never the substantive partner edit we want.
- Legacy binary ``.doc`` files are not zips and must be converted first.
- ``w:author`` is only as good as the producing firm: Litera Metadact-style metadata
  cleaning and Word's ``w:removePersonalInformation`` setting both rewrite authors
  to "Author", which silently destroys attribution.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_DOCUMENT_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)

Source = str | Path | IO[bytes]

_INSERTING = {"ins", "moveTo"}
_DELETING = {"del", "moveFrom"}
_REVISION_KINDS = {
    "ins": "insertion",
    "del": "deletion",
    "moveTo": "move_to",
    "moveFrom": "move_from",
}

_SECTION_RE = re.compile(
    r"^(?:section|article|clause)?\s*(\d+(?:\.\d+)*)[.):]?\s+(\S+)", re.IGNORECASE
)


@dataclass(frozen=True)
class RedlineEdit:
    """One tracked change, with enough context to become a candidate rubric issue."""

    author: str
    date: str
    kind: str
    inserted_text: str
    deleted_text: str
    paragraph_index: int
    paragraph_context: str
    section_hint: str
    revision_id: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentComment:
    """One margin comment from ``word/comments.xml``."""

    comment_id: str
    author: str
    initials: str
    date: str
    text: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# --------------------------------------------------------------------------- api


def iter_edits(source: Source) -> Iterator[RedlineEdit]:
    """Yield every substantive tracked change in document order."""
    root = ET.fromstring(_read_part(source, _main_document_name))
    seen: set[int] = set()
    current_section = ""
    paragraphs = [element for element in root.iter() if _local(element.tag) == "p"]
    for index, paragraph in enumerate(paragraphs):
        context = _squeeze(_collect_text(paragraph, accepted=True))
        token = _leading_section_token(context)
        if token:
            current_section = token
        for element in paragraph.iter():
            kind = _REVISION_KINDS.get(_local(element.tag))
            if kind is None or id(element) in seen:
                continue
            seen.add(id(element))
            inserting = _local(element.tag) in _INSERTING
            text = _squeeze(_collect_text(element, accepted=inserting))
            if not text:
                continue  # paragraph-mark and formatting-only revisions
            yield RedlineEdit(
                author=_attr(element, "author") or "(unattributed)",
                date=_attr(element, "date"),
                kind=kind,
                inserted_text=text if inserting else "",
                deleted_text="" if inserting else text,
                paragraph_index=index,
                paragraph_context=context,
                section_hint=current_section,
                revision_id=_attr(element, "id"),
            )


def extract_edits(source: Source) -> list[RedlineEdit]:
    """Return every substantive tracked change in document order."""
    return list(iter_edits(source))


def extract_comments(source: Source) -> list[DocumentComment]:
    """Return margin comments. Empty when the package has no comments part."""
    try:
        payload = _read_part(source, _comments_name)
    except KeyError:
        return []
    root = ET.fromstring(payload)
    comments: list[DocumentComment] = []
    for element in root.iter():
        if _local(element.tag) != "comment":
            continue
        comments.append(
            DocumentComment(
                comment_id=_attr(element, "id"),
                author=_attr(element, "author") or "(unattributed)",
                initials=_attr(element, "initials"),
                date=_attr(element, "date"),
                text=_squeeze(_collect_text(element, accepted=True)),
            )
        )
    return comments


def merge_substitutions(edits: Sequence[RedlineEdit]) -> list[RedlineEdit]:
    """Collapse an adjacent deletion/insertion by the same author into one edit.

    A partner replacing language produces two revision elements; as a candidate
    rubric issue it is a single substitution ("was X, is now Y"), and the pair is
    what Stage 3 turns into an anchor plus ``redline_concepts``.
    """
    merged: list[RedlineEdit] = []
    index = 0
    while index < len(edits):
        current = edits[index]
        following = edits[index + 1] if index + 1 < len(edits) else None
        pair = _substitution_pair(current, following)
        if pair is not None:
            merged.append(pair)
            index += 2
            continue
        merged.append(current)
        index += 1
    return merged


def _substitution_pair(first: RedlineEdit, second: RedlineEdit | None) -> RedlineEdit | None:
    if second is None:
        return None
    if first.author != second.author or first.paragraph_index != second.paragraph_index:
        return None
    kinds = {first.kind, second.kind}
    if kinds != {"insertion", "deletion"}:
        return None
    inserted = first.inserted_text or second.inserted_text
    deleted = first.deleted_text or second.deleted_text
    return RedlineEdit(
        author=first.author,
        date=first.date,
        kind="substitution",
        inserted_text=inserted,
        deleted_text=deleted,
        paragraph_index=first.paragraph_index,
        paragraph_context=first.paragraph_context,
        section_hint=first.section_hint,
        revision_id=f"{first.revision_id}+{second.revision_id}".strip("+"),
    )


def edits_by_author(edits: Sequence[RedlineEdit]) -> dict[str, list[RedlineEdit]]:
    """Group edits by author — the first cut at "whose judgment is this?"."""
    grouped: dict[str, list[RedlineEdit]] = {}
    for edit in edits:
        grouped.setdefault(edit.author, []).append(edit)
    return grouped


# ----------------------------------------------------------------------- package


def _read_part(source: Source, resolver) -> bytes:
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:  # legacy .doc, corrupt export, or a PDF
        raise ValueError(
            "not a .docx (OPC zip) package; convert legacy .doc/.rtf files first"
        ) from exc
    with archive:
        return archive.read(resolver(archive))


def _main_document_name(archive: zipfile.ZipFile) -> str:
    """Resolve the main document part through ``_rels/.rels`` rather than guessing."""
    names = set(archive.namelist())
    if "_rels/.rels" in names:
        for relationship in ET.fromstring(archive.read("_rels/.rels")):
            if _attr(relationship, "Type") != OFFICE_DOCUMENT_REL:
                continue
            target = _attr(relationship, "Target").lstrip("/")
            if target in names:
                return target
    if "word/document.xml" in names:
        return "word/document.xml"
    raise ValueError("no main document part found in package")


def _comments_name(archive: zipfile.ZipFile) -> str:
    names = set(archive.namelist())
    main = _main_document_name(archive)
    folder, _, base = main.rpartition("/")
    rels_name = f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"
    if rels_name in names:
        for relationship in ET.fromstring(archive.read(rels_name)):
            if not _attr(relationship, "Type").endswith("/comments"):
                continue
            target = _attr(relationship, "Target").lstrip("/")
            for candidate in (target, f"{folder}/{target}" if folder else target):
                if candidate in names:
                    return candidate
    fallback = f"{folder}/comments.xml" if folder else "comments.xml"
    if fallback in names:
        return fallback
    raise KeyError("no comments part in package")


# --------------------------------------------------------------------------- xml


def _local(tag: str) -> str:
    """Return an element or attribute name without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _attr(element: ET.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return ""


def _collect_text(node: ET.Element, *, accepted: bool) -> str:
    """Collect text under ``node``.

    ``accepted=True`` renders the "accept all changes" view (insertions in,
    deletions out); ``accepted=False`` renders the "reject all" view.
    """
    parts: list[str] = []
    for child in node:
        tag = _local(child.tag)
        if accepted and tag in _DELETING:
            continue
        if not accepted and tag in _INSERTING:
            continue
        if tag in ("t", "delText"):
            parts.append(child.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
        else:
            parts.append(_collect_text(child, accepted=accepted))
    return "".join(parts)


def paragraph_views(source: Source) -> list[tuple[str, str]]:
    """Return ``(original, accepted)`` text for every paragraph, in document order.

    The pair is the input to a version-to-version diff when a document arrives with
    its changes already accepted and the redline must be recovered by comparison.
    """
    root = ET.fromstring(_read_part(source, _main_document_name))
    return [
        (
            _squeeze(_collect_text(element, accepted=False)),
            _squeeze(_collect_text(element, accepted=True)),
        )
        for element in root.iter()
        if _local(element.tag) == "p"
    ]


def _squeeze(text: str) -> str:
    return " ".join(text.split())


def _leading_section_token(text: str) -> str:
    """Best-effort clause number at the start of a paragraph ("4.2", "10.2")."""
    match = _SECTION_RE.match(text)
    if match is None:
        return ""
    token, following = match.group(1), match.group(2)
    if "." in token:
        return token
    if following[:1].isupper() and len(text) <= 100:
        return token
    return ""


# --------------------------------------------------------------------------- cli


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract tracked changes from a .docx file.")
    parser.add_argument("path", type=Path, help="Path to a .docx file")
    parser.add_argument("--comments", action="store_true", help="Include margin comments")
    parser.add_argument("--merge", action="store_true", help="Collapse delete/insert pairs")
    args = parser.parse_args(argv)

    edits = extract_edits(args.path)
    if args.merge:
        edits = merge_substitutions(edits)
    payload: dict[str, object] = {"edits": [edit.as_dict() for edit in edits]}
    if args.comments:
        payload["comments"] = [comment.as_dict() for comment in extract_comments(args.path)]
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
