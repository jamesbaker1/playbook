"""Email threads as first-class Playbook documents — stdlib only.

Correspondence is where the *reasoning* of a deal lives: the supervising lawyer's
instructions, the client's answers, the counterparty's refusals. Playbook already
has a document format that can carry it with no runtime change, because
``playbook_legal.loaders._parse_sections`` addresses any ``## <token> <title>``
heading and the reward engine cites sections as ``<document_id> §<token>``.

This module renders a thread so that **one message is one section**::

    ## 3.1 From: D. Whitfield — Re: Acme MSA — data-training right

    **From:** D. Whitfield <dwhitfield@example.com>
    **To:** A. Okafor
    **Date:** 2026-03-04T15:04:00Z
    **Subject:** Re: Acme MSA — data-training right

    Body text.

The token is ``<thread>.<message>``, so a single ``correspondence.md`` can hold
several threads and every message is independently citable (``emails §3.1``) as an
issue's ``required_citations`` entry or a rubric anchor. See
``docs/matter-compiler.md`` §4.

Two invariants matter and are enforced here:

1. **Section tokens are unique** within the document — the linter rejects reuse and
   the reward engine resolves citations by token.
2. **Message bodies cannot forge sections.** A quoted reply containing a Markdown
   heading would otherwise split the document; leading ``#`` runs are escaped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

_HEADING_RE = re.compile(r"^(#{1,6})(\s|$)")

_SENDER_KEYS = ("from", "sender", "from_")
_RECIPIENT_KEYS = ("to", "recipients", "to_recipients")
_CC_KEYS = ("cc", "cc_recipients", "copy")


@dataclass(frozen=True)
class Message:
    """One email. ``label`` carries a handling marker such as 'Privileged'."""

    sender: str
    recipients: tuple[str, ...] = ()
    date: str = ""
    subject: str = ""
    body: str = ""
    cc: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class Thread:
    """An ordered set of messages sharing a subject."""

    title: str
    messages: tuple[Message, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------- construction


def build_message(payload: Mapping[str, Any] | Message) -> Message:
    """Coerce a mapping (Graph, PST, or hand-written) into a :class:`Message`.

    ``from`` is a Python keyword, so mappings are the interchange format; ``to`` and
    ``cc`` accept either a string or a sequence.
    """
    if isinstance(payload, Message):
        return payload
    return Message(
        sender=_first_string(payload, _SENDER_KEYS) or "(unknown sender)",
        recipients=_as_tuple(_first_value(payload, _RECIPIENT_KEYS)),
        date=str(payload.get("date", "")),
        subject=str(payload.get("subject", "")),
        body=str(payload.get("body", "")),
        cc=_as_tuple(_first_value(payload, _CC_KEYS)),
        attachments=_as_tuple(payload.get("attachments")),
        label=str(payload.get("label", "")),
    )


def build_thread(title: str, messages: Iterable[Mapping[str, Any] | Message]) -> Thread:
    return Thread(title=title, messages=tuple(build_message(item) for item in messages))


def section_token(thread_number: int, message_index: int) -> str:
    """Return the citable section token for a message (1-based on both axes)."""
    if thread_number < 1 or message_index < 1:
        raise ValueError("thread_number and message_index are 1-based")
    return f"{thread_number}.{message_index}"


def citation(document_id: str, thread_number: int, message_index: int) -> str:
    """Return a Playbook citation string, e.g. ``emails §3.1``."""
    return f"{document_id} §{section_token(thread_number, message_index)}"


# ----------------------------------------------------------------------- rendering


def render_thread(thread: Thread, *, thread_number: int = 1) -> str:
    """Render one thread as a run of ``## <thread>.<n>`` sections."""
    blocks: list[str] = []
    for offset, message in enumerate(thread.messages, start=1):
        blocks.append(_render_message(message, section_token(thread_number, offset), thread.title))
    return "\n\n".join(blocks)


def render_document(
    threads: Sequence[Thread],
    *,
    title: str,
    intro: str = "",
    first_thread_number: int = 1,
) -> str:
    """Render a whole correspondence document.

    The H1 title and any ``intro`` land in the parser's implicit ``full`` section, so
    every ``##`` heading in the emitted file is a message and nothing else.
    """
    parts: list[str] = [f"# {title}"]
    if intro:
        parts.append(_escape_headings(intro.strip()))
    seen: set[str] = set()
    for offset, thread in enumerate(threads, start=first_thread_number):
        for index in range(1, len(thread.messages) + 1):
            token = section_token(offset, index)
            if token in seen:
                raise ValueError(f"duplicate section token: {token}")
            seen.add(token)
        parts.append(render_thread(thread, thread_number=offset))
    return "\n\n".join(part for part in parts if part) + "\n"


def messages_to_document(
    messages: Iterable[Mapping[str, Any] | Message],
    *,
    title: str,
    thread_title: str = "",
    thread_number: int = 1,
    intro: str = "",
) -> str:
    """Convenience wrapper: one thread in, one Playbook document out."""
    thread = build_thread(thread_title or title, messages)
    return render_document(
        [thread], title=title, intro=intro, first_thread_number=thread_number
    )


def _render_message(message: Message, token: str, thread_title: str) -> str:
    subject = message.subject or thread_title
    heading = f"## {token} From: {_squeeze(message.sender)} — Re: {_squeeze(_clip(subject, 80))}"
    lines = [heading, ""]
    lines.append(f"**From:** {_squeeze(message.sender)}")
    if message.recipients:
        lines.append(f"**To:** {'; '.join(_squeeze(item) for item in message.recipients)}")
    if message.cc:
        lines.append(f"**Cc:** {'; '.join(_squeeze(item) for item in message.cc)}")
    if message.date:
        lines.append(f"**Date:** {_squeeze(message.date)}")
    if subject:
        lines.append(f"**Subject:** {_squeeze(subject)}")
    if message.attachments:
        lines.append(f"**Attachments:** {'; '.join(_squeeze(a) for a in message.attachments)}")
    if message.label:
        lines.append(f"**Handling:** {_squeeze(message.label)}")
    body = _escape_headings(_normalize_body(message.body))
    if body:
        lines.extend(["", body])
    return "\n".join(lines)


# ------------------------------------------------------------------------ helpers


def _normalize_body(body: str) -> str:
    text = str(body).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    collapsed: list[str] = []
    for line in lines:
        if not line and collapsed and not collapsed[-1]:
            continue
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def _escape_headings(text: str) -> str:
    """Neutralize Markdown headings inside prose so they cannot forge a section."""
    return "\n".join(
        "\\" + line if _HEADING_RE.match(line) else line for line in text.split("\n")
    )


def _clip(text: str, limit: int) -> str:
    text = _squeeze(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _squeeze(text: str) -> str:
    return " ".join(str(text).split())


def _first_value(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in payload and payload[key]:
            return payload[key]
    return None


def _first_string(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    value = _first_value(payload, keys)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(";") if part.strip()]
        return tuple(parts)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value),)
