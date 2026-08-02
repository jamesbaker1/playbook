"""Tests for the working halves of the matter compiler.

Two things are asserted end to end: that tracked changes come out of a real OPC
package with correct authorship and nesting, and that a rendered email thread is
addressable by the *same* section parser the environment and linter use.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from playbook_legal.loaders import _parse_sections, load_documents

# `compiler/` sits at the repo root rather than under src/, and pytest only puts
# tests/ on sys.path. Import it explicitly so this file works under `pytest -q`,
# `python -m pytest`, and a direct file path alike, with no import-order games.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

correspondence = importlib.import_module("compiler.correspondence")
redline_miner = importlib.import_module("compiler.redline_miner")
phase_a_selftest = importlib.import_module("compiler.phase_a_selftest")

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"

DOCUMENT_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}">
  <w:body>
    <w:p><w:r><w:t>4.2 Product Improvement and Model Training</w:t></w:r></w:p>
    <w:p>
      <w:r><w:t>Acme may use Customer Data </w:t></w:r>
      <w:del w:id="1" w:author="Dana Whitfield" w:date="2026-03-04T15:04:00Z">
        <w:r><w:delText>to train generalized machine-learning models</w:delText></w:r>
      </w:del>
      <w:ins w:id="2" w:author="Dana Whitfield" w:date="2026-03-04T15:04:12Z">
        <w:r><w:t>solely to provide and support the Service</w:t></w:r>
      </w:ins>
      <w:r><w:t>.</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>10.2 Liability Cap</w:t></w:r></w:p>
    <w:p>
      <w:ins w:id="3" w:author="Priya Raman" w:date="2026-03-05T09:00:00Z">
        <w:r><w:t>Liability for Security Incidents is subject to a supercap of </w:t></w:r>
        <w:del w:id="4" w:author="Dana Whitfield" w:date="2026-03-06T11:30:00Z">
          <w:r><w:delText>three times</w:delText></w:r>
        </w:del>
        <w:r><w:t>two times the general cap.</w:t></w:r>
      </w:ins>
    </w:p>
    <w:p>
      <w:pPr><w:rPr><w:ins w:id="5" w:author="Dana Whitfield" w:date="2026-03-04T15:05:00Z"/>
      </w:rPr></w:pPr>
      <w:r><w:t>The parties agree as follows.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

COMMENTS_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{W}">
  <w:comment w:id="1" w:author="Priya Raman" w:initials="PR" w:date="2026-03-05T09:02:00Z">
    <w:p><w:r><w:t>Playbook requires a 2x supercap. Do not concede this.</w:t></w:r></w:p>
  </w:comment>
</w:comments>
"""

ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS}">
  <Relationship Id="rId1" Type="{OFFICE_DOC}" Target="word/document.xml"/>
</Relationships>
"""

DOCUMENT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS}">
  <Relationship Id="rId10" Type="{COMMENTS_REL}" Target="comments.xml"/>
</Relationships>
"""


def build_docx(*, with_comments: bool = True) -> io.BytesIO:
    """Build a minimal but structurally valid .docx in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", DOCUMENT_XML)
        if with_comments:
            archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
            archive.writestr("word/comments.xml", COMMENTS_XML)
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------- redlines


def test_extract_edits_reads_ins_and_del_in_document_order() -> None:
    edits = redline_miner.extract_edits(build_docx())

    assert [edit.kind for edit in edits] == ["deletion", "insertion", "insertion", "deletion"]
    assert [edit.revision_id for edit in edits] == ["1", "2", "3", "4"]
    assert edits[0].deleted_text == "to train generalized machine-learning models"
    assert edits[0].inserted_text == ""
    assert edits[0].author == "Dana Whitfield"
    assert edits[0].date == "2026-03-04T15:04:00Z"
    assert edits[1].inserted_text == "solely to provide and support the Service"


def test_nested_deletion_does_not_leak_into_the_enclosing_insertion() -> None:
    edits = redline_miner.extract_edits(build_docx())
    insertion = edits[2]
    nested_deletion = edits[3]

    assert insertion.author == "Priya Raman"
    assert insertion.inserted_text == (
        "Liability for Security Incidents is subject to a supercap of "
        "two times the general cap."
    )
    assert "three times" not in insertion.inserted_text
    assert nested_deletion.author == "Dana Whitfield"
    assert nested_deletion.deleted_text == "three times"


def test_paragraph_context_is_the_accepted_view_with_a_section_hint() -> None:
    edits = redline_miner.extract_edits(build_docx())

    assert edits[0].paragraph_index == 1
    assert edits[0].section_hint == "4.2"
    assert edits[0].paragraph_context == (
        "Acme may use Customer Data solely to provide and support the Service."
    )
    assert "to train generalized" not in edits[0].paragraph_context
    assert edits[2].section_hint == "10.2"
    assert edits[2].paragraph_index == 3


def test_textless_paragraph_mark_revisions_are_dropped() -> None:
    edits = redline_miner.extract_edits(build_docx())
    assert "5" not in {edit.revision_id for edit in edits}


def test_paragraph_views_expose_both_original_and_accepted_text() -> None:
    original, accepted = redline_miner.paragraph_views(build_docx())[1]

    assert original == "Acme may use Customer Data to train generalized machine-learning models."
    assert accepted == "Acme may use Customer Data solely to provide and support the Service."


def test_merge_substitutions_pairs_a_delete_and_insert_by_one_author() -> None:
    merged = redline_miner.merge_substitutions(redline_miner.extract_edits(build_docx()))

    assert [edit.kind for edit in merged] == ["substitution", "insertion", "deletion"]
    substitution = merged[0]
    assert substitution.deleted_text == "to train generalized machine-learning models"
    assert substitution.inserted_text == "solely to provide and support the Service"
    assert substitution.revision_id == "1+2"


def test_edits_by_author_groups_the_record() -> None:
    grouped = redline_miner.edits_by_author(redline_miner.extract_edits(build_docx()))
    assert set(grouped) == {"Dana Whitfield", "Priya Raman"}
    assert len(grouped["Dana Whitfield"]) == 3


def test_extract_comments_reads_the_comments_part() -> None:
    comments = redline_miner.extract_comments(build_docx())

    assert len(comments) == 1
    assert comments[0].author == "Priya Raman"
    assert comments[0].initials == "PR"
    assert comments[0].text == "Playbook requires a 2x supercap. Do not concede this."


def test_extract_comments_is_empty_when_there_is_no_comments_part() -> None:
    assert redline_miner.extract_comments(build_docx(with_comments=False)) == []


def test_non_docx_input_fails_with_a_useful_message() -> None:
    with pytest.raises(ValueError, match="OPC zip"):
        redline_miner.extract_edits(io.BytesIO(b"\xd0\xcf\x11\xe0legacy .doc"))


# ---------------------------------------------------------------- correspondence


THREAD = [
    {
        "from": "A. Okafor <aokafor@northstar.example>",
        "to": ["D. Whitfield <dwhitfield@firm.example>"],
        "date": "2026-03-02T09:12:00Z",
        "subject": "Acme MSA — training rights",
        "body": "Dana — can the provider train on our data? Procurement needs an answer.",
    },
    {
        "from": "D. Whitfield <dwhitfield@firm.example>",
        "to": "A. Okafor <aokafor@northstar.example>",
        "cc": "P. Raman <praman@firm.example>",
        "date": "2026-03-02T14:40:00Z",
        "subject": "RE: Acme MSA — training rights",
        "label": "Privileged & Confidential",
        "body": (
            "Section 4.2 as drafted lets them train generalized models on Customer Data\n"
            "and Outputs. That is outside the playbook.\n"
            "\n"
            "## 4.2 quoted from their draft\n"
            "Acme may use Customer Data ... to train ... generalized models."
        ),
        "attachments": ["Acme MSA v3 (DW comments).docx"],
    },
    {
        "from": "A. Okafor <aokafor@northstar.example>",
        "to": ["D. Whitfield <dwhitfield@firm.example>"],
        "date": "2026-03-03T08:05:00Z",
        "subject": "RE: Acme MSA — training rights",
        "body": "Training on our data is non-negotiable. Aggregated analytics are fine.",
    },
]


def render_thread_document() -> str:
    return correspondence.messages_to_document(
        THREAD,
        title="Matter Correspondence",
        thread_title="Acme MSA — training rights",
        thread_number=3,
    )


def test_thread_renders_one_section_per_message() -> None:
    sections = _parse_sections(render_thread_document())

    assert {"3.1", "3.2", "3.3"} <= set(sections)
    assert sections["3.1"].startswith("## 3.1 From: A. Okafor")
    assert "**Date:** 2026-03-02T14:40:00Z" in sections["3.2"]
    assert "**Cc:** P. Raman <praman@firm.example>" in sections["3.2"]
    assert "**Handling:** Privileged & Confidential" in sections["3.2"]
    assert "Acme MSA v3 (DW comments).docx" in sections["3.2"]
    assert "non-negotiable" in sections["3.3"]


def test_quoted_markdown_heading_in_a_body_cannot_forge_a_section() -> None:
    sections = _parse_sections(render_thread_document())

    assert "4.2" not in sections
    assert "\\## 4.2 quoted from their draft" in sections["3.2"]


def test_document_loads_through_the_real_loader_and_resolves_citations(tmp_path: Path) -> None:
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    (documents_dir / "emails.md").write_text(render_thread_document(), encoding="utf-8")

    manifest = [{"id": "emails", "title": "Matter Correspondence", "path": "documents/emails.md"}]
    documents = load_documents(tmp_path, manifest)

    sections = documents["emails"]["sections"]
    assert [key for key in sections if key != "full"] == ["3.1", "3.2", "3.3"]
    assert correspondence.citation("emails", 3, 2) == "emails §3.2"
    document_id, section = correspondence.citation("emails", 3, 2).split(" §")
    assert section in documents[document_id]["sections"]
    assert "That is outside the playbook." in sections["3.2"]


def test_multiple_threads_get_distinct_tokens() -> None:
    threads = [
        correspondence.build_thread("Instructions", THREAD[:2]),
        correspondence.build_thread("Counterparty", THREAD[2:]),
    ]
    sections = _parse_sections(correspondence.render_document(threads, title="Correspondence"))

    assert [key for key in sections if key != "full"] == ["1.1", "1.2", "2.1"]


def test_title_and_intro_stay_out_of_the_message_sections() -> None:
    document = correspondence.render_document(
        [correspondence.build_thread("T", THREAD[:1])],
        title="Matter Correspondence",
        intro="## not a section — thread filed from the DMS",
    )
    sections = _parse_sections(document)

    assert [key for key in sections if key != "full"] == ["1.1"]
    assert "# Matter Correspondence" in sections["full"]
    assert "\\## not a section" in sections["full"]


def test_section_token_is_one_based() -> None:
    assert correspondence.section_token(3, 1) == "3.1"
    with pytest.raises(ValueError):
        correspondence.section_token(0, 1)


def test_build_message_normalizes_recipient_shapes() -> None:
    message = correspondence.build_message({"from": "a@x", "to": "b@x; c@x", "body": "hi"})

    assert message.recipients == ("b@x", "c@x")
    assert correspondence.build_message({"body": "x"}).sender == "(unknown sender)"


# ---------------------------------------------------------- Phase A known answer


def test_phase_a_bundle_contains_real_versioned_docx_and_correspondence(tmp_path: Path) -> None:
    source = ROOT / "matters" / "ai_saas_001"
    manifest_path = phase_a_selftest.generate_evidence_bundle(source, tmp_path)
    manifest = phase_a_selftest._yaml(manifest_path)

    assert manifest["synthetic"] is True
    assert len(manifest["artifacts"]) == 10
    assert {item["version"] for item in manifest["artifacts"]} == {1, 2}
    tracked = next(tmp_path.glob("*_v2_tracked.docx"))
    assert redline_miner.extract_edits(tracked)
    messages = json.loads((tmp_path / "correspondence.json").read_text(encoding="utf-8"))
    assert len(messages) == 5


def test_phase_a_recovers_known_answer_and_validates_emitted_package(tmp_path: Path) -> None:
    result = phase_a_selftest.run_selftest(ROOT, tmp_path)

    assert result["stages_exercised"] == [2, 3, 4, 5, 6, 7, 8]
    assert result["recovery"] == {
        "issues": {"recovered": 5, "expected": 5},
        "severities": {"matched": 5, "expected": 5},
        "required_concepts": {"matched": 18, "expected": 18},
        "redline_concepts": {"matched": 11, "expected": 11},
        "concepts": {"matched": 29, "expected": 29},
    }
    assert result["validation"]["lint_errors"] == 0
    assert result["validation"]["normalized_score"] >= 0.7
    assert result["validation"]["critical_failure"] is False
