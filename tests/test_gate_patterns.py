"""Structured critical-failure gates: opt-in polarity and scope checks.

Bare gate regexes are polarity-blind, so the gate written to punish "the law
prohibits all model training" also fires on "no law prohibits all model training" —
the sentence the instructions actually ask for. A rubric author may opt one pattern
into a mapping form and let the engine read the negation and scope around the match.

Every probe below is a false positive that was replay-confirmed against the public
corpus, or the unnegated sin the same gate exists to catch. Plain-string patterns are
untouched, which the corpus-replay test at the bottom proves against frozen results.
"""

from __future__ import annotations

import pytest
from conftest import EXAMPLES, MATTERS, replay

from playbook_legal.rewards import RewardEngine, gate_match
from playbook_legal.text import normalize_text

# ------------------------------------------------------------------ behaviour table

# State-then-negate: the reviewer disclaims the very overclaim the gate polices.
LAW_PROHIBITS = {"pattern": "law prohibits all model training", "negation_guard": True}
FEDERAL_LAW = {
    "pattern": r"(federal|state) (law|laws|regulation|regulations) "
    r"(require|requires|mandate|mandates)[^.]{0,80}(united states|domestic)",
    "negation_guard": True,
}
CREDITS_AUTOMATIC = {
    "pattern": "service credits are issued automatically under the agreement",
    "negation_guard": True,
}
# Belt-and-braces prohibitions written in the document's own operative words.
RETAIN_DATA = {"pattern": "retain customer data", "negation_guard": True}
CUSTOMER_MAY_USE = {"pattern": "customer may use provider data", "negation_guard": True}
# Negations reusing the document's own operative words.
CONCLUSIVE_BINDING = {"pattern": "conclusive and binding on", "negation_guard": True}
UNLIMITED_AMOUNT = {
    "pattern": r"(?:uncapped|unlimited) (?:in amount|as to amount)",
    "negation_guard": True,
}
UNLIMITED_LIABILITY = {"pattern": "unlimited liability", "negation_guard": True}

GATE_BEHAVIOUR = [
    # --- state-then-negate ------------------------------------------------------
    (
        "state_then_negate_suppressed",
        LAW_PROHIBITS,
        (
            "No law prohibits all model training; the objection here is contractual, "
            "resting on playbook §3 rather than on any statute."
        ),
        False,
    ),
    (
        "state_then_negate_sin_still_fires",
        LAW_PROHIBITS,
        (
            "Applicable law prohibits all model training on customer data, so this "
            "clause is unenforceable."
        ),
        True,
    ),
    (
        "disclaimed_regulatory_conclusion_suppressed",
        FEDERAL_LAW,
        (
            "Meridian's requirement here is contractual rather than regulatory: no "
            "federal law requires that this data be stored in the United States, and "
            "the ask rests on playbook section 2."
        ),
        False,
    ),
    (
        "fabricated_regulatory_conclusion_still_fires",
        FEDERAL_LAW,
        "Federal regulations require that this data be stored in the United States.",
        True,
    ),
    (
        "contracted_negation_suffix_suppressed",
        CREDITS_AUTOMATIC,
        (
            "The business shouldn't assume that service credits are issued "
            "automatically under the agreement; section 7.3 conditions every credit "
            "on a written request."
        ),
        False,
    ),
    (
        "credits_overclaim_still_fires",
        CREDITS_AUTOMATIC,
        (
            "Service credits are issued automatically under the agreement, so no "
            "claim is needed."
        ),
        True,
    ),
    # --- belt-and-braces prohibitions -------------------------------------------
    (
        "may_not_retain_suppressed",
        RETAIN_DATA,
        "Provider may not retain Customer Data after expiration of the Order Form.",
        False,
    ),
    (
        "may_retain_still_fires",
        RETAIN_DATA,
        "Provider may retain Customer Data after expiration of the Order Form.",
        True,
    ),
    (
        "neither_nor_prohibition_suppressed",
        CUSTOMER_MAY_USE,
        (
            "Neither Provider nor Customer may use Provider Data or Customer Data to "
            "train, fine-tune, or develop any generalized model."
        ),
        False,
    ),
    (
        "affirmative_use_grant_still_fires",
        CUSTOMER_MAY_USE,
        (
            "Customer may use Provider Data to train, fine-tune, or develop any "
            "generalized model."
        ),
        True,
    ),
    # --- savings / scoping clauses ----------------------------------------------
    (
        "nothing_in_this_section_suppressed",
        CUSTOMER_MAY_USE,
        (
            "For clarity, nothing in this Section 4.2 restricts the purposes for "
            "which Customer may use Provider Data, Outputs, or the Service."
        ),
        False,
    ),
    (
        "nothing_in_this_section_creates_suppressed",
        UNLIMITED_LIABILITY,
        (
            "For the avoidance of doubt, nothing in this Section creates unlimited "
            "liability for either party."
        ),
        False,
    ),
    (
        "unlimited_liability_concession_still_fires",
        UNLIMITED_LIABILITY,
        "This Section creates unlimited liability for either party.",
        True,
    ),
    # --- negation reusing the document's own operative words --------------------
    (
        "own_words_negation_suppressed",
        CONCLUSIVE_BINDING,
        (
            "Provider's statement of Policy Transaction counts is not conclusive and "
            "binding on Customer."
        ),
        False,
    ),
    (
        "conclusive_records_concession_still_fires",
        CONCLUSIVE_BINDING,
        (
            "Provider's statement of Policy Transaction counts is conclusive and "
            "binding on Customer."
        ),
        True,
    ),
    (
        "rejecting_counterparty_wording_suppressed",
        UNLIMITED_AMOUNT,
        (
            "Provider's liability under this Section is limited as set out above and "
            "is not unlimited as to amount."
        ),
        False,
    ),
    (
        "uncapped_amount_concession_still_fires",
        UNLIMITED_AMOUNT,
        "Provider's liability for Security Incidents shall be unlimited as to amount.",
        True,
    ),
]


@pytest.mark.parametrize(
    ("spec", "text", "fires"),
    [pytest.param(spec, text, fires, id=case) for case, spec, text, fires in GATE_BEHAVIOUR],
)
def test_gate_behaviour_table(spec: dict, text: str, fires: bool) -> None:
    matched = gate_match(spec, normalize_text(text))
    assert (matched is not None) is fires
    if fires:
        assert matched == spec["pattern"], "attribution must report the pattern string"


@pytest.mark.parametrize(
    ("spec", "text"),
    [
        pytest.param(spec, text, id=case)
        for case, spec, text, fires in GATE_BEHAVIOUR
        if not fires
    ],
)
def test_same_pattern_without_the_guard_still_fires(spec: dict, text: str) -> None:
    """Every suppression above is the opt-in doing work, not a weaker regex."""
    assert gate_match(spec["pattern"], normalize_text(text)) == spec["pattern"]


# ------------------------------------------------------------------ sentence scope


def test_negator_in_a_preceding_sentence_does_not_suppress() -> None:
    text = normalize_text(
        "No law prohibits training on public data. The law prohibits all model "
        "training on Customer Data."
    )
    assert gate_match(LAW_PROHIBITS, text) == LAW_PROHIBITS["pattern"]


def test_negator_after_a_question_or_exclamation_does_not_suppress() -> None:
    text = normalize_text(
        "Is there no statute on point? The law prohibits all model training here."
    )
    assert gate_match(LAW_PROHIBITS, text) == LAW_PROHIBITS["pattern"]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "For clarity, nothing in this Section 4.2 restricts the purposes for "
            "which Provider may retain Customer Data.",
            id="section_4.2",
        ),
        pytest.param(
            "Nothing in playbook R.3 permits Provider to retain Customer Data.",
            id="playbook_R.3",
        ),
        pytest.param(
            "Nothing in msa §10.2 permits Provider to retain Customer Data.",
            id="section_10.2",
        ),
    ],
)
def test_section_number_periods_do_not_split_the_sentence(text: str) -> None:
    """A period before a digit is part of a citation, not a sentence boundary."""
    assert gate_match(RETAIN_DATA, normalize_text(text)) is None


def test_newline_ends_a_sentence() -> None:
    """Unnormalized text still scopes correctly if a caller passes raw content."""
    assert gate_match(RETAIN_DATA, "No such right exists.\nProvider may retain Customer Data.") is not None
    assert gate_match(RETAIN_DATA, "No right exists for Provider to retain Customer Data.") is None


def test_a_later_occurrence_can_still_fire_the_gate() -> None:
    text = normalize_text(
        "Provider may not retain Customer Data after expiration. Provider may "
        "retain Customer Data during the Order Form term."
    )
    assert gate_match(RETAIN_DATA, text) == RETAIN_DATA["pattern"]


# ------------------------------------------------------------- context conditions

DRAFT_STATE = {
    "pattern": "the agreement permits termination",
    "require_context": r"\b(as drafted|as returned|already|currently)\b",
}
UNRESTRICTED_ACCESS = {
    "pattern": "unrestricted access",
    "exclude_context": r"\bdoes not grant\b",
}


def test_require_context_fires_only_with_the_draft_state_anchor() -> None:
    with_anchor = normalize_text(
        "The agreement permits termination for repeated availability misses, as drafted."
    )
    without_anchor = normalize_text(
        "If we win this redline, the agreement permits termination for repeated "
        "availability misses."
    )
    assert gate_match(DRAFT_STATE, with_anchor) == DRAFT_STATE["pattern"]
    assert gate_match(DRAFT_STATE, without_anchor) is None


def test_require_context_is_scoped_to_the_matching_sentence() -> None:
    text = normalize_text(
        "As drafted the exit right is missing. The agreement permits termination "
        "only if we negotiate it."
    )
    assert gate_match(DRAFT_STATE, text) is None


def test_exclude_context_suppresses_only_its_own_sentence() -> None:
    carve_out = normalize_text(
        "This Section does not grant Customer unrestricted access to Provider's systems."
    )
    concession = normalize_text("Customer has unrestricted access to Provider's systems.")
    both = normalize_text(
        "This Section does not grant Customer unrestricted access to Provider's "
        "systems. Customer has unrestricted access to the audit portal."
    )
    assert gate_match(UNRESTRICTED_ACCESS, carve_out) is None
    assert gate_match(UNRESTRICTED_ACCESS, concession) == UNRESTRICTED_ACCESS["pattern"]
    assert gate_match(UNRESTRICTED_ACCESS, both) == UNRESTRICTED_ACCESS["pattern"]


def test_guards_combine() -> None:
    spec = {
        "pattern": "the agreement permits termination",
        "negation_guard": True,
        "require_context": r"\balready\b",
    }
    assert gate_match(spec, normalize_text("The agreement permits termination already.")) is not None
    assert gate_match(spec, normalize_text("The agreement permits termination.")) is None
    assert (
        gate_match(
            spec,
            normalize_text(
                "It is not the case that the agreement permits termination already."
            ),
        )
        is None
    )


def test_the_negator_list_is_closed() -> None:
    """Only the listed negators suppress: 'nobody' is not one of them."""
    assert gate_match(RETAIN_DATA, normalize_text("Nobody may retain Customer Data.")) is not None
    assert gate_match(RETAIN_DATA, normalize_text("No one may retain Customer Data.")) is None


# ------------------------------------------------------------------ malformed specs


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param({"pattern": "x", "negate": True}, id="unknown_key"),
        pytest.param({"negation_guard": True}, id="missing_pattern"),
        pytest.param({"pattern": "x", "require_context": "(unclosed"}, id="bad_require_context"),
        pytest.param({"pattern": "x", "exclude_context": "(unclosed"}, id="bad_exclude_context"),
        pytest.param({"pattern": "x", "negation_guard": "yes"}, id="non_boolean_guard"),
    ],
)
def test_malformed_gate_specs_are_rejected_not_ignored(spec: dict) -> None:
    with pytest.raises(ValueError, match="invalid critical-failure gate"):
        gate_match(spec, "x")


# --------------------------------------------------------- all three engine sites

DOCUMENTS = {
    "msa": {
        "sections": {
            "4.2": "Provider may retain Customer Data after expiration.",
            "full": "## 4.2 Data\n\nProvider may retain Customer Data after expiration.\n",
        }
    }
}
SUPPRESSED_TEXT = "Provider may not retain Customer Data after expiration."
FIRING_TEXT = "Provider may retain Customer Data after expiration."


def _engine(gate_field: str) -> RewardEngine:
    rubric = {
        "issues": [
            {
                "id": "gate_issue",
                "anchor": "msa §4.2",
                "severity": "high",
                "required_citations": ["msa §4.2"],
                "required_concepts": ["customer data"],
                "redline_concepts": ["customer data"],
                "settlement_points": 1.0,
                gate_field: [RETAIN_DATA],
            }
        ]
    }
    engine = RewardEngine(rubric, DOCUMENTS)
    engine.record_document_read("msa", "4.2")
    return engine


def _score_issue(engine: RewardEngine, text: str) -> dict:
    _, event = engine.score_issue(
        {
            "issue_id": "label",
            "citations": ["msa §4.2"],
            "title": "Retention",
            "severity": "high",
            "analysis": text,
            "recommendation": "",
        }
    )
    return event


def _score_redline(engine: RewardEngine, text: str) -> dict:
    _, event = engine.score_redline(
        {
            "issue_id": "label",
            "document_id": "msa",
            "section": "4.2",
            "replacement_text": text,
        }
    )
    return event


def _score_settlement(engine: RewardEngine, text: str) -> dict:
    _, event = engine.score_settlement("gate_issue", text, "ours")
    return event


SITES = {
    "critical_failure_patterns": _score_issue,
    "redline_critical_failure_patterns": _score_redline,
    "settlement_critical_failure_patterns": _score_settlement,
}


@pytest.mark.parametrize("gate_field", sorted(SITES), ids=sorted(SITES))
def test_every_application_site_shares_the_guard_semantics(gate_field: str) -> None:
    score = SITES[gate_field]

    engine = _engine(gate_field)
    event = score(engine, SUPPRESSED_TEXT)
    assert engine.state.critical_failure is False
    assert "critical_failure_pattern" not in event

    engine = _engine(gate_field)
    event = score(engine, FIRING_TEXT)
    assert engine.state.critical_failure is True
    assert event["critical_failure_pattern"] == RETAIN_DATA["pattern"]


@pytest.mark.parametrize("gate_field", sorted(SITES), ids=sorted(SITES))
def test_plain_string_patterns_are_unguarded_at_every_site(gate_field: str) -> None:
    """Opting out is the default: a bare string gates on the negated sentence too."""
    rubric = {
        "issues": [
            {
                "id": "gate_issue",
                "anchor": "msa §4.2",
                "severity": "high",
                "required_citations": ["msa §4.2"],
                "required_concepts": ["customer data"],
                "redline_concepts": ["customer data"],
                "settlement_points": 1.0,
                gate_field: [RETAIN_DATA["pattern"]],
            }
        ]
    }
    engine = RewardEngine(rubric, DOCUMENTS)
    engine.record_document_read("msa", "4.2")
    event = SITES[gate_field](engine, SUPPRESSED_TEXT)
    assert engine.state.critical_failure is True
    assert event["critical_failure_pattern"] == RETAIN_DATA["pattern"]


# ------------------------------------------------- plain-string corpus invariance

# Frozen from the engine immediately before the structured-gate mechanism landed.
# Every shipped rubric still uses plain strings, so each number, flag, and gate
# attribution below must survive the change byte-identically.
CORPUS_BASELINE = {
    ("ai_saas_001", "good.jsonl"): (15.0, 0.9375, False, []),
    ("cloud_msa_002", "good.jsonl"): (16.0, 1.0, False, []),
    ("saas_renewal_003", "good.jsonl"): (15.75, 0.9692, False, []),
    ("msa_provider_004", "good.jsonl"): (17.75, 1.0, False, []),
    ("nego_saas_010", "good.jsonl"): (13.25, 1.0, False, []),
    ("ai_saas_001", "bad_critical_redline.jsonl"): (
        2.5,
        0.1562,
        True,
        [("redline", "liability_cap", "customer's ip indemnification obligations")],
    ),
    ("ai_saas_001", "bad_fabricated_quote.jsonl"): (1.0, 0.0625, True, []),
    ("msa_provider_004", "bad_critical_caved.jsonl"): (
        5.425,
        0.25,
        True,
        [("redline", "liability_supercap", "not be subject to (?:any )?(?:cap|limit)")],
    ),
    ("nego_saas_010", "bad_critical_caved.jsonl"): (
        12.0,
        0.25,
        True,
        [
            (
                "settlement",
                "incident_notice",
                r"after\s+(?:\w+\s+)?confirm(?:s|ed|ing|ation)\b",
            )
        ],
    ),
    ("source_license_008", "bad_critical_infection_claim.jsonl"): (
        5.125,
        0.25,
        True,
        [
            (
                "issue",
                "copyleft_conveyance",
                (
                    "copperline (loses|forfeits|gives up|surrenders) (all )?(its )?"
                    "(ownership|copyright|rights) (in|of|over) the firmware"
                ),
            )
        ],
    ),
    ("public_merger_target_011", "bad_critical_reversed_redline.jsonl"): (
        0.7917,
        0.0495,
        True,
        [("redline", "mae_disproportionate", "whether or not.*disproportion")],
    ),
    ("private_acquisition_buyer_012", "bad_critical_reversed_redline.jsonl"): (
        0.6667,
        0.0417,
        True,
        [("redline", "basket_form", "all losses from the first dollar")],
    ),
}


@pytest.mark.parametrize(
    ("matter_id", "actions"),
    sorted(CORPUS_BASELINE),
    ids=[f"{matter}-{actions}" for matter, actions in sorted(CORPUS_BASELINE)],
)
def test_plain_string_gates_are_byte_identical_on_the_corpus(
    matter_id: str, actions: str
) -> None:
    raw, normalized, critical, gates = CORPUS_BASELINE[(matter_id, actions)]
    result = replay(MATTERS / matter_id, EXAMPLES / matter_id / actions)
    fired = [
        (str(event["type"]), str(event["criterion"]), event["critical_failure_pattern"])
        for event in result["breakdown"]["reward_events"]
        if "critical_failure_pattern" in event
    ]
    assert result["raw_score"] == raw
    assert result["normalized_score"] == normalized
    assert result["critical_failure"] is critical
    assert fired == [tuple(item) for item in gates]
