from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected mapping in {path}")
    return data


def load_documents(matter_dir: Path, manifest: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for entry in manifest:
        document_id = str(entry["id"])
        path = matter_dir / str(entry["path"])
        text = path.read_text(encoding="utf-8")
        documents[document_id] = {
            "id": document_id,
            "title": entry.get("title", document_id),
            "path": str(path),
            "text": text,
            "sections": _parse_sections(text),
        }
    return documents


def _parse_sections(text: str) -> dict[str, str]:
    """Parse Markdown headings like '## 4.2 Use of Data' into section-addressable chunks."""
    lines = text.splitlines()
    sections: dict[str, list[str]] = {}
    current = "full"
    sections[current] = []
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip()
            token = heading.split(maxsplit=1)[0].rstrip(".")
            current = token
            sections.setdefault(current, [])
        sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}
