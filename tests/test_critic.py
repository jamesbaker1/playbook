"""The critic verifies proposed work from client materials only.

Two properties matter most and are tested hardest:

- it reproduces the engine's verifiable gates (fabricated quotations, unresolved
  citations, prohibited concessions) with the engine's own matching semantics; and
- it never touches the benchmark answer key, so it keeps working on a matter
  directory from which ``rubric.yaml``, ``hidden_facts.yaml``, and
  ``counterparty.yaml`` have been deleted.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import EXAMPLES, MATTERS, ROOT, replay

from playbook_legal.critic import (
    ANSWER_KEY_FILENAMES,
    AnswerKeyError,
    ClientRecord,
    CriticError,
    Verdict,
    canonical_filename,
    critique,
    guard_path,
    load_authority,
    load_submission,
    main,
    review,
)
from playbook_legal.rewards import RewardEngine

MATTER = MATTERS / "ai_saas_001"
GOOD = EXAMPLES / "ai_saas_001" / "good.jsonl"
FABRICATED = EXAMPLES / "ai_saas_001" / "bad_fabricated_quote.jsonl"
AUTHORITY = ROOT / "examples" / "authority" / "ai_saas_001.authority.yaml"
KNOWN_BAD = (
    "bad_fabricated_quote.jsonl",
    "bad_critical_redline.jsonl",
    "bad_keyword_stuffing.jsonl",
)
#: A real passage of msa §4.2, used wherever a test needs a quotation that verifies.
REAL_QUOTE = (
    "Acme may use Customer Data, prompts, inputs, Outputs, and usage information to operate, "
    "train, test, improve, and develop Acme's services and generalized machine-learning models."
)


def verdicts(report) -> set[str]:
    return {finding.verdict for finding in report.findings}


def _authority_file(tmp_path: Path, **payload) -> Path:
    document = {"schema_version": "playbook.authority.v1", **payload}
    path = tmp_path / "authority.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    return path


def _review_file(tmp_path: Path, payload: dict, name: str = "review.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ------------------------------------------------------------------ quote verification


def test_reference_trajectory_verifies_and_fabrication_is_caught() -> None:
    good = critique(MATTER, GOOD, authority_path=AUTHORITY)
    assert good.passed is True
    assert good.critical_findings == ()
    assert good.verified_quotes == 3

    bad = critique(MATTER, FABRICATED, authority_path=AUTHORITY)
    assert bad.passed is False
    assert verdicts(bad) == {Verdict.FABRICATED_QUOTE}
    finding = bad.critical_findings[0]
    assert finding.citation == "msa §4.2"
    assert "model-training claims" in finding.quote


def test_fabrication_verdict_agrees_with_the_rubric_scored_engine() -> None:
    """Same trajectory, same call: the engine gates it and the critic flags it."""
    scored = replay(MATTER, FABRICATED)
    assert scored["critical_failure"] is True
    assert scored["breakdown"]["fabricated_quotes"] == ["msa §4.2"]

    report = critique(MATTER, FABRICATED)
    assert [f.citation for f in report.findings if f.verdict == Verdict.FABRICATED_QUOTE] == [
        "msa §4.2"
    ]

    # And the engine scores the reference trajectory clean, exactly as the critic does.
    assert replay(MATTER, GOOD)["critical_failure"] is False
    assert critique(MATTER, GOOD).passed is True


def test_whitespace_and_case_differences_still_verify(tmp_path: Path) -> None:
    payload = {
        "issues": [
            {
                "citation": "msa §10.2",
                "quote": "THIS  cap\n applies to ALL claims,   including confidentiality",
                "rationale": "Reformatted but verbatim.",
            }
        ],
        "summary": "The single fees-paid cap covers confidentiality, data-security, and "
        "indemnification claims and needs a supercap for those exposures.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert report.passed is True
    assert report.verified_quotes == 1


def test_uncited_quotation_that_exists_nowhere_is_fabrication(tmp_path: Path) -> None:
    payload = {
        "issues": [
            {"quote": "Provider warrants the model will never hallucinate.", "rationale": "No."}
        ]
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert Verdict.FABRICATED_QUOTE in verdicts(report)
    assert report.passed is False


def test_reformatting_the_engine_tolerates_does_not_trip_the_gate(tmp_path: Path) -> None:
    """Non-breaking spaces, hard wraps, and case are collapsed by both sides alike."""
    quote = REAL_QUOTE.replace(" ", " ", 3).replace("inputs,", "INPUTS,\r\n\t").upper()
    payload = {
        "issues": [{"citation": "msa §4.2", "quote": quote, "rationale": "Pasted from a brief."}],
        "summary": "The provider's training right is the principal exposure and should be "
        "treated as a condition of signature by the business.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert report.verified_quotes == 1
    assert report.passed is True


def test_near_miss_quotations_still_fail_but_say_why(tmp_path: Path) -> None:
    """Smart quotes and ellipses are fabrications to the engine, so they are here too.

    The verdict is unchanged; only the message earns its keep by naming the cause,
    because "does not appear verbatim" sends a lawyer hunting for a phantom edit.
    """
    curly = REAL_QUOTE.replace("Acme's", "Acme’s")
    elided = "Acme may use Customer Data, prompts, … and generalized machine-learning models."
    payload = {
        "issues": [
            {"citation": "msa §4.2", "quote": curly, "rationale": "Retyped in Word."},
            {"citation": "msa §4.2", "quote": elided, "rationale": "Shortened for the memo."},
        ],
        "summary": "The provider's training right is the principal exposure and should be "
        "treated as a condition of signature by the business.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert verdicts(report) == {Verdict.FABRICATED_QUOTE}
    assert report.passed is False
    messages = [f.message for f in report.findings]
    assert any("only in typography" in message for message in messages)
    assert any("elides text" in message for message in messages)


def test_spliced_and_homoglyph_quotations_are_fabrications(tmp_path: Path) -> None:
    """Two evasions that look verbatim to a human reader."""
    record = ClientRecord.from_directory(MATTER)
    first, second = record.resolve("msa §4.1") or "", record.resolve("msa §4.2") or ""
    spliced = " ".join(first.split()[-8:] + second.split()[1:9])
    payload = {
        "issues": [
            {"citation": "msa §4.2", "quote": spliced, "rationale": "Two provisions, one quote."},
            {
                "citation": "msa §4.2",
                "quote": REAL_QUOTE.replace("Acme", "Аcme", 1),  # Cyrillic А
                "rationale": "Looks identical.",
            },
        ],
        "summary": "The provider's training right is the principal exposure and should be "
        "treated as a condition of signature by the business.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert [f.verdict for f in report.findings if f.quote] == [
        Verdict.FABRICATED_QUOTE,
        Verdict.FABRICATED_QUOTE,
    ]


def test_a_document_without_headings_is_still_citable(tmp_path: Path) -> None:
    """A client's own deal folder has no ``## 4.2`` headings; the whole file is the cite."""
    docs = tmp_path / "client_documents"
    docs.mkdir()
    (docs / "sow.md").write_text(f"Statement of work.\n\n{REAL_QUOTE}\n", encoding="utf-8")
    payload = {"issues": [{"quote": REAL_QUOTE, "rationale": "No pin cite available."}]}
    report = critique(docs, _review_file(tmp_path, payload))
    finding = next(f for f in report.findings if f.verdict == Verdict.UNRESOLVED_CITATION)
    assert "sow §full" in finding.message

    cited = {"issues": [{"citation": "sow §full", "quote": REAL_QUOTE, "rationale": "Cited."}]}
    assert critique(docs, _review_file(tmp_path, cited, name="cited.json")).verified_quotes == 1


# ---------------------------------------------------------------- citation resolution


def test_citation_to_a_nonexistent_section_is_unresolved(tmp_path: Path) -> None:
    payload = {
        "issues": [
            {
                "citation": "msa §77.7",
                "quote": "Acme may use Customer Data, prompts, inputs, Outputs",
                "rationale": "Cites a provision that does not exist.",
            }
        ],
        "summary": "One issue was raised against a provision number that is not in the paper, "
        "so the analysis cannot be checked against the record at all.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert Verdict.UNRESOLVED_CITATION in verdicts(report)
    assert Verdict.FABRICATED_QUOTE not in verdicts(report)
    assert report.passed is False
    messages = " ".join(finding.message for finding in report.critical_findings)
    assert "has no section '77.7'" in messages


def test_unknown_document_and_malformed_citation_are_reported_distinctly() -> None:
    record = ClientRecord.from_directory(MATTER)
    assert "no document 'nda'" in record.citation_problem("nda §1.1")
    assert "not in '<document_id> §<section>' form" in record.citation_problem("MSA section 4.2")
    assert record.resolve("msa §4.2") is not None


# ------------------------------------------------------------- prohibited concessions


def test_prohibited_settlement_flags_and_authorized_fallback_does_not(tmp_path: Path) -> None:
    authority = _authority_file(
        tmp_path,
        non_negotiables=[
            {
                "id": "no_generalized_model_training",
                "description": "No training on Customer Data or Outputs.",
                "prohibited_patterns": ["train generalized models"],
            }
        ],
        approved_fallbacks=[
            {
                "id": "aggregated_analytics",
                "description": "Aggregated, de-identified analytics are permitted.",
                "permitted_patterns": ["aggregated and de-identified usage analytics"],
            }
        ],
    )
    conceded = _review_file(
        tmp_path,
        {
            "settlements": [
                {
                    "issue": "training-right",
                    "closing_text": "Provider may train generalized models on Customer Data.",
                }
            ],
            "summary": "The training point closed on the counterparty's language, which is a "
            "departure from the client's stated position and must be escalated.",
        },
        name="conceded.json",
    )
    authorized = _review_file(
        tmp_path,
        {
            "settlements": [
                {
                    "issue": "training-right",
                    "closing_text": "Provider may use aggregated and de-identified usage "
                    "analytics only.",
                }
            ],
            "summary": "The training point closed on the client's approved fallback, so no "
            "escalation is required before signature on this issue.",
        },
        name="authorized.json",
    )

    bad = critique(MATTER, conceded, authority_path=authority)
    assert Verdict.PROHIBITED_CONCESSION in verdicts(bad)
    assert bad.passed is False
    hit = next(f for f in bad.findings if f.verdict == Verdict.PROHIBITED_CONCESSION)
    assert hit.authority_id == "no_generalized_model_training"
    assert hit.pattern == "train generalized models"
    assert hit.ref == "training-right"

    good = critique(MATTER, authorized, authority_path=authority)
    assert Verdict.PROHIBITED_CONCESSION not in verdicts(good)
    assert good.passed is True
    settlement = next(item for item in good.items if item["kind"] == "settlement")
    assert settlement["within_authority"] == [
        {"id": "aggregated_analytics", "pattern": "aggregated and de-identified usage analytics"}
    ]


def test_substring_semantics_match_the_engine_exactly(tmp_path: Path) -> None:
    """'30 days' matches inside '130 days' — for the engine and for the critic alike."""
    closing = "Either party may give notice of nonrenewal at least 130 days before expiry."

    engine = RewardEngine(
        {"issues": [{"id": "renewal", "settlement_concepts": ["30 days"]}]},
        documents={},
    )
    _, event = engine.score_settlement("renewal", closing, "ours")
    assert event["matched_concepts"] == ["30 days"]

    authority = _authority_file(
        tmp_path,
        non_negotiables=[{"id": "renewal_notice", "prohibited_patterns": ["30 days"]}],
    )
    report = critique(
        MATTER,
        _review_file(tmp_path, {"settlements": [{"issue": "renewal", "closing_text": closing}]}),
        authority_path=authority,
    )
    hits = [f for f in report.findings if f.verdict == Verdict.PROHIBITED_CONCESSION]
    assert [f.pattern for f in hits] == ["30 days"]


def test_prohibited_patterns_are_scanned_in_redlines_and_markups(tmp_path: Path) -> None:
    authority = _authority_file(
        tmp_path,
        non_negotiables=[{"id": "incident_notice", "prohibited_patterns": ["72 hours"]}],
    )
    actions = [
        {
            "type": "propose_redline",
            "issue_id": "incident-timing",
            "document_id": "dpa",
            "section": "5.1",
            "replacement_text": "Provider shall notify Customer within 72 hours of discovery.",
            "rationale": "Splits the difference.",
        },
        {
            "type": "send_markup",
            "issue_id": "incident-timing",
            "document_id": "dpa",
            "section": "5.1",
            "proposed_text": "Notice within 72 hours after discovery is acceptable.",
        },
    ]
    path = tmp_path / "actions.jsonl"
    path.write_text("\n".join(json.dumps(action) for action in actions), encoding="utf-8")

    report = critique(MATTER, path, authority_path=authority)
    flagged = {f.kind for f in report.findings if f.verdict == Verdict.PROHIBITED_CONCESSION}
    assert flagged == {"redline", "markup"}


def test_scoped_rules_only_fire_on_the_provisions_they_govern(tmp_path: Path) -> None:
    authority = _authority_file(
        tmp_path,
        non_negotiables=[
            {
                "id": "incident_notice",
                "applies_to": ["dpa §5.1"],
                "prohibited_patterns": ["72 hours"],
            }
        ],
    )
    payload = {
        "redlines": [
            {
                "citation": "msa §12.1",
                "replacement_text": "Either party may terminate on 72 hours notice.",
                "rationale": "Unrelated provision.",
            }
        ]
    }
    report = critique(MATTER, _review_file(tmp_path, payload), authority_path=authority)
    assert Verdict.PROHIBITED_CONCESSION not in verdicts(report)


def test_authority_file_is_validated(tmp_path: Path) -> None:
    bad_version = tmp_path / "bad.yaml"
    bad_version.write_text("schema_version: playbook.authority.v0\n", encoding="utf-8")
    with pytest.raises(CriticError, match="schema_version"):
        load_authority(bad_version)

    with pytest.raises(CriticError, match="non-empty prohibited_patterns"):
        load_authority(
            _authority_file(tmp_path, non_negotiables=[{"id": "x", "prohibited_patterns": ["  "]}])
        )


def test_shipped_authority_file_is_derived_from_the_public_playbook_only() -> None:
    authority = load_authority(AUTHORITY)
    assert "playbook.md" in authority.source
    assert {rule.rule_id for rule in authority.non_negotiables} >= {
        "no_generalized_model_training",
        "incident_notice_24_hours",
    }
    playbook = (MATTER / "documents" / "playbook.md").read_text(encoding="utf-8")
    assert "non-negotiable" in playbook

    # The reference trajectory is authorized work: it must not trip a single pattern.
    report = critique(MATTER, GOOD, authority_path=AUTHORITY)
    assert Verdict.PROHIBITED_CONCESSION not in verdicts(report)


# ------------------------------------------------------------------- evidence hygiene


def test_evidence_hygiene_is_advisory_not_critical(tmp_path: Path) -> None:
    payload = {
        "issues": [{"citation": "msa §4.2", "rationale": ""}],
        "summary": "Too short.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    messages = [f.message for f in report.findings]
    assert verdicts(report) == {Verdict.MISSING_EVIDENCE}
    assert report.passed is True
    assert any("no verbatim quotation" in message for message in messages)
    assert any("no rationale was given" in message for message in messages)
    assert any("below the 80-character floor" in message for message in messages)


def test_an_empty_quotation_is_reported_rather_than_dropped(tmp_path: Path) -> None:
    """The engine penalizes an empty quotation as unverifiable; silence would diverge."""
    payload = {
        "issues": [
            {
                "citation": "msa §4.2",
                "quotes": [{"citation": "msa §4.2", "text": ""}],
                "rationale": "Forgot to paste the language.",
            }
        ],
        "summary": "The provider's training right is the principal exposure and should be "
        "treated as a condition of signature by the business.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    assert verdicts(report) == {Verdict.MISSING_EVIDENCE}
    assert any("15-character floor" in finding.message for finding in report.findings)
    assert report.passed is True


def test_a_submission_without_a_final_summary_still_reports_one() -> None:
    report = critique(MATTER, EXAMPLES / "ai_saas_001" / "bad_critical_redline.jsonl")
    summary = next(item for item in report.items if item["kind"] == "summary")
    assert summary["ref"] == "final summary"


def test_accepted_counterparty_language_is_reported_as_unverifiable(tmp_path: Path) -> None:
    path = tmp_path / "accept.jsonl"
    path.write_text(
        json.dumps({"type": "accept_counterparty", "issue_id": "training-right"}), encoding="utf-8"
    )
    report = critique(MATTER, path)
    acceptance = next(item for item in report.items if item["kind"] == "acceptance")
    assert acceptance["verdict"] == Verdict.MISSING_EVIDENCE.value
    assert "will not read counterparty.yaml" in acceptance["findings"][0]["message"]


# --------------------------------------------------------------- submission handling


def test_both_submission_formats_are_detected(tmp_path: Path) -> None:
    assert load_submission(GOOD).format == "actions"
    assert load_submission(_review_file(tmp_path, {"issues": []})).format == "review"


def test_revisions_replace_rather_than_accumulate(tmp_path: Path) -> None:
    actions = [
        {
            "type": "submit_issue",
            "issue_id": "training",
            "citations": ["msa §4.2"],
            "quotes": [{"citation": "msa §4.2", "text": "Acme guarantees perfect Outputs."}],
            "analysis": "First pass.",
        },
        {
            "type": "revise_issue",
            "issue_id": "training",
            "citations": ["msa §4.2"],
            "quotes": [
                {
                    "citation": "msa §4.2",
                    "text": "Acme may use Customer Data, prompts, inputs, Outputs",
                }
            ],
            "analysis": "Corrected quotation.",
        },
    ]
    path = tmp_path / "revised.jsonl"
    path.write_text("\n".join(json.dumps(action) for action in actions), encoding="utf-8")

    report = critique(MATTER, path)
    issues = [item for item in report.items if item["kind"] == "issue"]
    assert len(issues) == 1
    assert Verdict.FABRICATED_QUOTE not in verdicts(report)


def _issue_action(quote: str, **overrides) -> dict:
    action = {
        "type": "submit_issue",
        "issue_id": "training-right",
        "title": "Provider model-training right exceeds client position",
        "severity": "high",
        "citations": ["msa §4.2"],
        "quotes": [{"citation": "msa §4.2", "text": quote}],
        "analysis": "The provider may train generalized models on Customer Data.",
        "recommendation": "Delete the training right.",
    }
    action.update(overrides)
    return action


def _jsonl(tmp_path: Path, actions: list[dict], name: str = "actions.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(action) for action in actions), encoding="utf-8")
    return path


def test_resubmitting_a_label_does_not_launder_a_fabricated_quotation(tmp_path: Path) -> None:
    """Only ``revise_*`` replaces. A second ``submit_issue`` is a second submission.

    The environment scores both and critically fails on the first one's fabrication, so
    a critic that kept only the last version would clear work the benchmark fails.
    """
    path = _jsonl(
        tmp_path,
        [
            {"type": "read_document", "document_id": "msa", "section": "4.2"},
            _issue_action("Acme guarantees that Outputs will be free of any third-party claims."),
            _issue_action(REAL_QUOTE),
            {"type": "submit_final", "summary": "The training right is the principal issue and "
             "the client should treat it as a condition of signature."},
        ],
    )
    assert replay(MATTER, path)["critical_failure"] is True

    report = critique(MATTER, path)
    issues = [item for item in report.items if item["kind"] == "issue"]
    assert len(issues) == 2, "a re-submitted label is a new submission, not a revision"
    assert report.passed is False
    assert Verdict.FABRICATED_QUOTE in verdicts(report)


def test_an_uncited_quotation_is_critical_because_the_engine_fails_it(tmp_path: Path) -> None:
    """Real text, no pin cite: the engine cannot resolve '' and fails the episode.

    Advisory here would green-light exactly that, so the critic calls it what it is —
    an unresolved citation, critical, and fixable by re-citing.
    """
    path = _jsonl(
        tmp_path,
        [
            {"type": "read_document", "document_id": "msa", "section": "4.2"},
            _issue_action("", quotes=[REAL_QUOTE]),  # bare string: no citation travels with it
            {"type": "submit_final", "summary": "The training right is the principal issue and "
             "the client should treat it as a condition of signature."},
        ],
    )
    assert replay(MATTER, path)["critical_failure"] is True

    report = critique(MATTER, path)
    assert report.passed is False
    finding = next(f for f in report.findings if f.verdict == Verdict.UNRESOLVED_CITATION)
    assert "carries no citation" in finding.message
    assert "msa §4.2" in finding.message, "say where the text actually lives"


def test_two_fabrications_under_one_citation_are_both_reported(tmp_path: Path) -> None:
    payload = {
        "issues": [
            {
                "citation": "msa §4.2",
                "quotes": [
                    "Acme shall indemnify Customer for every conceivable claim on earth.",
                    "Acme warrants that Outputs are always factually correct and safe.",
                ],
                "rationale": "Two invented passages, one citation.",
            }
        ],
        "summary": "The analysis rests on language that is not in the agreement at all, so "
        "none of it can be relied on without a fresh read of the paper.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    fabrications = [f for f in report.findings if f.verdict == Verdict.FABRICATED_QUOTE]
    assert len(fabrications) == 2, "identical messages must not collapse distinct evidence"
    assert len({f.quote for f in fabrications}) == 2


def test_unrecognized_submission_shapes_are_refused_not_silently_passed(tmp_path: Path) -> None:
    """Reviewing nothing and reporting clean is the worst answer available."""
    almost = _review_file(tmp_path, {"issue": [{"quote": "x"}], "final_summary": "y" * 200})
    with pytest.raises(CriticError, match="nothing reviewable found"):
        load_submission(almost)
    with pytest.raises(CriticError, match="issues, redlines, markups, settlements, summary"):
        load_submission(almost)

    typo = _jsonl(tmp_path, [{"type": "submit_issues", "issue_id": "a"}], name="typo.jsonl")
    with pytest.raises(CriticError, match="action types were submit_issues"):
        load_submission(typo)

    # An empty but recognized shape is a legitimate (if useless) review, not an error.
    assert load_submission(_review_file(tmp_path, {"issues": []}, name="empty.json")).format


def test_a_scalar_where_a_list_belongs_is_read_as_one_entry(tmp_path: Path) -> None:
    """``list("msa §4.2")`` would report one unresolved citation per letter."""
    payload = {
        "issues": [
            {"citations": "msa §4.2", "quotes": REAL_QUOTE, "rationale": "Singular by mistake."}
        ],
        "summary": "The provider's training right is the principal exposure and should be "
        "treated as a condition of signature by the business.",
    }
    report = critique(MATTER, _review_file(tmp_path, payload))
    issue = next(item for item in report.items if item["kind"] == "issue")
    assert issue["citations"] == ["msa §4.2"]
    assert report.verified_quotes == 1
    assert report.passed is True


def test_a_byte_order_mark_breaks_neither_documents_nor_submissions(tmp_path: Path) -> None:
    """A BOM is invisible in an editor and fatal here — Windows clients emit them.

    Unhandled, it hides the first ``## `` heading from the section parser (so every
    citation into that document stops resolving) and makes line 1 of a JSONL unparseable.
    """
    docs = tmp_path / "client_documents"
    docs.mkdir()
    (docs / "msa.md").write_text(f"## 4.2 Use of Data\n\n{REAL_QUOTE}\n", encoding="utf-8-sig")
    record = ClientRecord.from_directory(docs)
    assert record.resolve("msa §4.2") is not None

    path = tmp_path / "bom.jsonl"
    path.write_text(json.dumps(_issue_action(REAL_QUOTE)), encoding="utf-8-sig")
    report = review(record, load_submission(path))
    assert report.verified_quotes == 1


def test_documents_that_are_not_utf8_say_what_to_fix(tmp_path: Path) -> None:
    docs = tmp_path / "client_documents"
    docs.mkdir()
    (docs / "msa.md").write_bytes("## 4.2 Use\nCaf\xe9 clause.\n".encode("latin-1"))
    with pytest.raises(CriticError, match="not UTF-8 text"):
        ClientRecord.from_directory(docs)


def test_malformed_submissions_raise_a_readable_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(CriticError, match="line 1 is not valid JSON"):
        load_submission(broken)

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(CriticError, match="is empty"):
        load_submission(empty)


# ---------------------------------------------------------------- answer-key firewall


def test_critic_works_on_a_matter_stripped_of_its_answer_key(tmp_path: Path) -> None:
    stripped = tmp_path / "ai_saas_001"
    shutil.copytree(MATTER, stripped)
    for name in ANSWER_KEY_FILENAMES:
        (stripped / name).unlink(missing_ok=True)
    assert not any((stripped / name).exists() for name in ANSWER_KEY_FILENAMES)

    reference = critique(MATTER, GOOD, authority_path=AUTHORITY)
    stripped_report = critique(stripped, GOOD, authority_path=AUTHORITY)

    assert stripped_report.passed is True
    assert stripped_report.counts() == reference.counts()
    assert [item["verdict"] for item in stripped_report.items] == [
        item["verdict"] for item in reference.items
    ]

    fabricated = critique(stripped, FABRICATED, authority_path=AUTHORITY)
    assert verdicts(fabricated) == {Verdict.FABRICATED_QUOTE}


def test_critic_works_on_a_bare_directory_of_documents(tmp_path: Path) -> None:
    docs = tmp_path / "client_documents"
    shutil.copytree(MATTER / "documents", docs)
    record = ClientRecord.from_directory(docs)
    assert set(record.document_ids) == {"instructions", "playbook", "msa", "dpa"}
    assert critique(docs, GOOD).passed is True


def test_critic_never_opens_the_answer_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with the answer key present, no read of it is ever attempted.

    The failing paths are exercised too, not just the clean one: a fabricated quotation
    sends the critic hunting through every section for the text, and an unresolved
    citation makes it enumerate the record. Neither may reach for the answer key.
    """
    opened: list[str] = []
    real_open = io.open

    def recording_open(file, *args, **kwargs):
        try:
            opened.append(Path(os.fspath(file)).name)
        except TypeError:  # a raw file descriptor, not a path
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    unresolved = _review_file(
        tmp_path,
        {
            "issues": [{"citation": "nda §1.1", "quote": REAL_QUOTE, "rationale": "Wrong paper."}],
            "summary": "s" * 200,
        },
    )
    assert all((MATTER / name).exists() for name in ("rubric.yaml", "hidden_facts.yaml"))
    monkeypatch.setattr(io, "open", recording_open)
    monkeypatch.setattr(builtins, "open", recording_open)
    try:
        report = critique(MATTER, GOOD, authority_path=AUTHORITY)
        assert critique(MATTER, FABRICATED, authority_path=AUTHORITY).passed is False
        assert critique(MATTER, unresolved).passed is False
    finally:
        monkeypatch.undo()

    assert report.passed is True
    assert "matter.yaml" in opened, "the recorder must actually observe the critic's reads"
    assert "msa.md" in opened
    # Fold the recorded names the same way the guard does, so a would-be `RUBRIC.YAML`
    # read cannot slip past the assertion that is supposed to catch it.
    folded = {canonical_filename(name) for name in opened}
    assert not (folded & set(ANSWER_KEY_FILENAMES)), sorted(set(opened))


def test_pointing_the_critic_at_the_answer_key_is_refused() -> None:
    for name in ANSWER_KEY_FILENAMES:
        with pytest.raises(AnswerKeyError, match="answer-key"):
            load_authority(MATTER / name)
    with pytest.raises(AnswerKeyError):
        load_submission(MATTER / "rubric.yaml")


def test_a_manifest_pointing_at_the_answer_key_is_refused(tmp_path: Path) -> None:
    matter = tmp_path / "sneaky"
    shutil.copytree(MATTER, matter)
    manifest = yaml.safe_load((matter / "matter.yaml").read_text(encoding="utf-8"))
    manifest["documents"].append({"id": "leak", "path": "rubric.yaml"})
    (matter / "matter.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(AnswerKeyError):
        ClientRecord.from_directory(matter)


def test_answer_key_names_are_matched_the_way_the_filesystem_matches_them() -> None:
    """A case-sensitive basename test is a firewall with a door in it.

    Windows opens every one of these as ``rubric.yaml``: NTFS folds case, Win32 drops
    trailing dots and spaces, and ``:$DATA`` names the file's default stream.
    """
    for variant in ("RUBRIC.YAML", "Rubric.Yaml", "rubric.yaml.", "rubric.yaml  ", "rubric.yaml:$DATA"):
        with pytest.raises(AnswerKeyError, match="answer-key"):
            guard_path(MATTER / variant)
    for variant in ("HIDDEN_FACTS.yaml", "Counterparty.YAML"):
        with pytest.raises(AnswerKeyError):
            load_authority(MATTER / variant)
    # Nothing else is caught by the fold.
    assert guard_path(MATTER / "matter.yaml").name == "matter.yaml"
    assert guard_path("documents/rubric_notes.md").name == "rubric_notes.md"


def test_a_renamed_answer_key_cannot_enter_the_record_as_a_document(tmp_path: Path) -> None:
    """Filename matching alone loses to ``copy rubric.yaml evidence.yaml``.

    So the record refuses YAML as evidence outright: every answer key is YAML, and a
    document the critic verifies quotations against must be the paper itself.
    """
    matter = tmp_path / "renamed"
    shutil.copytree(MATTER, matter)
    shutil.copy(MATTER / "rubric.yaml", matter / "documents" / "evidence.yaml")
    manifest = yaml.safe_load((matter / "matter.yaml").read_text(encoding="utf-8"))
    manifest["documents"].append({"id": "evidence", "path": "documents/evidence.yaml"})
    (matter / "matter.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    with pytest.raises(AnswerKeyError, match="documents are text"):
        ClientRecord.from_directory(matter)


def test_critic_never_constructs_the_environment() -> None:
    """Building PlaybookEnv loads the rubric, so the critic must never do it."""
    source = (ROOT / "src" / "playbook_legal" / "critic.py").read_text(encoding="utf-8")
    assert "from .env import" not in source
    assert "PlaybookEnv(" not in source
    assert "PlaybookEnv.from_directory" not in source


# ------------------------------------------------------------------------ report + cli


def test_reports_render_in_both_formats_and_name_the_scope() -> None:
    report = critique(MATTER, FABRICATED, authority_path=AUTHORITY)
    markdown = report.to_markdown()
    assert "# Critic report — ai_saas_001" in markdown
    assert "FABRICATED_QUOTE" in markdown
    assert "it does not lawyer" in markdown

    payload = report.to_dict()
    assert payload["schema_version"] == "playbook.critic-report.v1"
    assert payload["passed"] is False
    assert payload["counts"]["FABRICATED_QUOTE"] == 1
    assert json.loads(json.dumps(payload))["matter_id"] == "ai_saas_001"


def test_cli_exit_codes_and_written_reports(tmp_path: Path, capsys) -> None:
    out = tmp_path / "reports" / "critic"
    assert main([str(MATTER), str(GOOD), "--authority", str(AUTHORITY), "--out", str(out)]) == 0
    assert (tmp_path / "reports" / "critic.json").exists()
    assert (tmp_path / "reports" / "critic.md").exists()
    capsys.readouterr()

    assert main([str(MATTER), str(FABRICATED), "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["FABRICATED_QUOTE"] == 1

    assert main([str(MATTER), str(tmp_path / "missing.jsonl")]) == 2
    assert "playbook-critic:" in capsys.readouterr().err


def test_cli_reports_output_failures_instead_of_a_traceback(tmp_path: Path, capsys) -> None:
    existing = tmp_path / "reports"
    existing.mkdir()
    assert main([str(MATTER), str(GOOD), "--out", str(existing)]) == 2
    assert "--out takes a path prefix" in capsys.readouterr().err

    blocker = tmp_path / "blocker.txt"
    blocker.write_text("not a directory", encoding="utf-8")
    assert main([str(MATTER), str(GOOD), "--out", str(blocker / "nested" / "critic")]) == 2
    assert "cannot write the report" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exit_info:
        main([str(MATTER), str(GOOD), "--min-summary-chars", "-1"])
    assert exit_info.value.code == 2
    assert "cannot be negative" in capsys.readouterr().err


def test_every_known_bad_trajectory_earns_a_critical_finding() -> None:
    """The shipped authority file has to actually catch the shipped adversarial traces."""
    for name in KNOWN_BAD:
        report = critique(MATTER, EXAMPLES / "ai_saas_001" / name, authority_path=AUTHORITY)
        assert report.passed is False, name
        assert report.critical_findings, name

    reference = critique(MATTER, GOOD, authority_path=AUTHORITY)
    assert reference.passed is True


def test_summary_floor_is_configurable() -> None:
    record = ClientRecord.from_directory(MATTER)
    submission = load_submission(GOOD)

    default = review(record, submission)
    assert not any("character floor" in finding.message for finding in default.findings)

    strict = review(record, submission, minimum_summary_characters=10_000)
    assert any("10000-character floor" in finding.message for finding in strict.findings)
    assert strict.passed is True  # a thin summary is advisory, never a gate
