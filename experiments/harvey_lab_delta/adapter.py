"""Load a pinned Harvey LAB task as a runnable interactive Playbook episode."""

from __future__ import annotations

import argparse
import email
import json
import re
import subprocess
import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from playbook_legal.env import PlaybookEnv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", "-C", str(repo), *args], capture_output=True, check=True,
        text=not binary,
    )
    return result.stdout


def _xml_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    paragraphs = []
    for node in root.iter():
        if node.tag.endswith(("}p", "}row")):
            text = " ".join(part.text or "" for part in node.iter() if part.tag.endswith("}t"))
            if text.strip():
                paragraphs.append(text.strip())
    return "\n".join(paragraphs)


def extract_text(name: str, data: bytes) -> str:
    """Extract agent-readable text using only the standard library."""
    suffix = Path(name).suffix.lower()
    if suffix == ".eml":
        message = email.message_from_bytes(data)
        parts = []
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
        return "\n".join(parts)
    if suffix in {".txt", ".md", ".csv"}:
        return data.decode("utf-8", "replace")
    if suffix in {".docx", ".xlsx", ".pptx"}:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = [
                item for item in archive.namelist()
                if (suffix == ".docx" and item == "word/document.xml")
                or (suffix == ".xlsx" and (item.startswith("xl/worksheets/") or item == "xl/sharedStrings.xml"))
                or (suffix == ".pptx" and item.startswith("ppt/slides/slide") and item.endswith(".xml"))
            ]
            return "\n".join(_xml_text(archive.read(item)) for item in sorted(members))
    raise ValueError(f"unsupported LAB document type: {name}")


def _document_id(name: str, used: set[str]) -> str:
    base = "lab_" + re.sub(r"[^a-z0-9]+", "_", Path(name).stem.lower()).strip("_")
    candidate = base
    index = 2
    while candidate in used:
        candidate, index = f"{base}_{index}", index + 1
    used.add(candidate)
    return candidate


def load_descriptor(task_id: str, descriptor_path: Path = HERE / "generated" / "descriptors.json") -> dict:
    rows = json.loads(descriptor_path.read_text(encoding="utf-8"))
    try:
        return next(row for row in rows if row["lab"]["task_id"] == task_id)
    except StopIteration as exc:
        raise ValueError(f"task is not in the adaptation batch: {task_id}") from exc


def build_env(repo: Path, descriptor: dict) -> PlaybookEnv:
    commit = descriptor["lab"]["commit"]
    actual = str(_git(repo, "rev-parse", "HEAD")).strip()
    if actual != commit:
        raise ValueError(f"Harvey checkout is {actual}; expected pinned commit {commit}")

    base = PlaybookEnv.from_directory(ROOT / descriptor["playbook"]["matter_path"])
    matter = deepcopy(base.matter)
    matter["matter_id"] = "harvey_lab__" + descriptor["lab"]["task_id"].replace("/", "__")
    matter["title"] = descriptor["lab"]["title"] + " (interactive adaptation)"
    matter["assignment"] = (
        matter["assignment"] + " The LAB source bundle is included below; hidden client facts "
        "must be obtained through ask_client and counterparty movement through negotiation actions."
    )
    matter.setdefault("constraints", {})["maximum_client_questions"] = descriptor["playbook"]["question_budget"]

    # Keep the mapped synthetic scoring scaffold so anchors remain deterministic, and
    # add every pinned LAB source document as first-class searchable/readable evidence.
    documents = deepcopy(base.documents)
    used = set(documents)
    prefix = f"tasks/{descriptor['lab']['task_id']}/documents/"
    for name in descriptor["lab"]["documents"]:
        raw = _git(repo, "show", f"{commit}:{prefix}{name}", binary=True)
        assert isinstance(raw, bytes)
        text = extract_text(name, raw)
        doc_id = _document_id(name, used)
        documents[doc_id] = {
            "id": doc_id,
            "title": f"LAB source: {name}",
            "path": f"git:{commit}:{prefix}{name}",
            "text": text,
            "sections": {"full": text},
        }

    counterparty = deepcopy(base.counterparty)
    if not counterparty.get("positions"):
        resist = 1 if "subsequent-turn" not in descriptor["lab"]["task_id"] else 2
        counterparty = {
            "positions": {
                issue["id"]: {
                    "accept_concepts": [issue.get("redline_concepts") or issue.get("required_concepts", [])],
                    "resist_rounds": resist,
                    "counter_text": "Counterparty offers its documented fallback and requests a targeted response.",
                }
                for issue in base.rubric.get("issues", []) if issue.get("redline_points", 0) > 0
            }
        }
    return PlaybookEnv(
        matter_dir=base.matter_dir, matter=matter, rubric=deepcopy(base.rubric),
        hidden_facts=deepcopy(base.hidden_facts), documents=documents, counterparty=counterparty,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harvey-repo", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--actions", type=Path, help="JSONL actions to replay; omit for a reset smoke test")
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    env = build_env(args.harvey_repo.resolve(), load_descriptor(args.task))
    observation, _ = env.reset(seed=0)
    if args.actions:
        for line in args.actions.read_text(encoding="utf-8").splitlines():
            if line.strip():
                observation, _, terminated, truncated, _ = env.step(json.loads(line))
                if terminated or truncated:
                    break
    if args.trace:
        env.save_trace(args.trace)
    print(json.dumps({"matter": observation["matter"], "documents": observation["documents"], "result": env.episode_result()}))


if __name__ == "__main__":
    main()
