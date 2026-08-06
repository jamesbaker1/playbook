"""Tests for reviewed same-state decision preference pairs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from conftest import MATTERS

from playbook_legal import PlaybookEnv
from playbook_legal.freeze import freeze_dataset, verify_frozen_release
from playbook_legal.preferences import build_decision_pairs, verify_decision_pairs


def _registry(tmp_path: Path, split: str = "train") -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "families": {
                    "ai_saas_questions": {
                        "split": split,
                        "template_sha256": "a" * 64,
                        "matters": ["ai_saas_001"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _candidates(tmp_path: Path, mutate=None) -> Path:
    env = PlaybookEnv.from_directory(MATTERS / "ai_saas_001")
    state, _ = env.reset(seed=9)
    base = {
        "schema_version": "playbook.decision_candidate.v1",
        "pair_id": "question-at-intake-001",
        "matter_id": "ai_saas_001",
        "state": state,
        "preference_source": "qualified_legal_review",
        "category": "client_question",
        "reviewer": "reviewer-1",
        "review_status": "approved",
    }
    rows = [
        {
            **base,
            "candidate_id": "useful-question",
            "action": {
                "type": "ask_client",
                "question": "Will the service process regulated or sensitive personal data?",
            },
            "outcome": {
                "reward": 0.5,
                "result": "Client disclosed health-benefits information.",
            },
            "preference_rank": 2,
            "structured_reason": {
                "summary": "The answer changes privacy and security negotiation priorities.",
                "principle": "Ask only facts that can change the legal position.",
            },
        },
        {
            **base,
            "candidate_id": "unnecessary-question",
            "action": {"type": "ask_client", "question": "What color is the client's logo?"},
            "outcome": {"reward": -0.1, "result": "No relevant client information."},
            "preference_rank": 1,
            "structured_reason": {
                "summary": "The question consumes budget without affecting the review.",
                "principle": "Preserve scarce client-question budget.",
            },
        },
    ]
    if mutate:
        mutate(rows)
    path = tmp_path / "candidates.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_builder_emits_only_competing_actions_from_identical_state(tmp_path: Path) -> None:
    out = tmp_path / "pairs"
    manifest = build_decision_pairs(_candidates(tmp_path), _registry(tmp_path), out)
    assert manifest["output"]["pairs"] == 1
    record = json.loads((out / "decision_pairs.jsonl").read_text(encoding="utf-8"))
    assert json.loads(record["chosen"])["question"].startswith("Will the service")
    assert json.loads(record["rejected"])["question"].startswith("What color")
    prompt = record["prompt"]
    assert "Client disclosed health-benefits information" not in prompt
    assert "No relevant client information" not in prompt
    assert record["metadata"]["matter_family_id"] == "ai_saas_questions"
    assert record["metadata"]["template_sha256"] == "a" * 64
    assert record["metadata"]["chosen_reason"]["principle"]
    assert verify_decision_pairs(out)["pairs"] == 1


def test_builder_is_byte_reproducible(tmp_path: Path) -> None:
    candidates = _candidates(tmp_path)
    registry = _registry(tmp_path)
    first = build_decision_pairs(candidates, registry, tmp_path / "one")
    second = build_decision_pairs(candidates, registry, tmp_path / "two")
    assert first == second
    assert (tmp_path / "one" / "decision_pairs.jsonl").read_bytes() == (
        tmp_path / "two" / "decision_pairs.jsonl"
    ).read_bytes()


def test_builder_rejects_candidates_from_different_states(tmp_path: Path) -> None:
    def change_state(rows: list[dict]) -> None:
        rows[1] = deepcopy(rows[1])
        rows[1]["state"]["budgets"]["steps_remaining"] -= 1

    with pytest.raises(ValueError, match="same state"):
        build_decision_pairs(
            _candidates(tmp_path, change_state), _registry(tmp_path), tmp_path / "out"
        )


def test_builder_rejects_unreviewed_candidate(tmp_path: Path) -> None:
    def unreview(rows: list[dict]) -> None:
        rows[1]["review_status"] = "pending"

    with pytest.raises(ValueError, match="must be approved"):
        build_decision_pairs(
            _candidates(tmp_path, unreview), _registry(tmp_path), tmp_path / "out"
        )


def test_builder_rejects_held_out_family_by_default(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="held-out"):
        build_decision_pairs(
            _candidates(tmp_path), _registry(tmp_path, "held-out"), tmp_path / "out"
        )


def test_builder_rejects_action_unavailable_in_shared_state(tmp_path: Path) -> None:
    def unavailable(rows: list[dict]) -> None:
        rows[1]["action"] = {"type": "accept_counterparty", "issue_id": "x"}

    with pytest.raises(ValueError, match="unavailable"):
        build_decision_pairs(
            _candidates(tmp_path, unavailable), _registry(tmp_path), tmp_path / "out"
        )


def test_preference_release_can_be_frozen_and_verified(tmp_path: Path) -> None:
    build = tmp_path / "pairs"
    build_decision_pairs(_candidates(tmp_path), _registry(tmp_path), build)
    card = {
        "schema_version": "playbook.freeze.v1",
        "release_id": "playbook-preferences-001",
        "intended_use": "preference",
        "dataset_manifest_sha256": hashlib.sha256(
            (build / "manifest.json").read_bytes()
        ).hexdigest(),
        "inclusion_criteria": ["Same-state actions approved by a qualified reviewer."],
        "exclusion_criteria": ["Tied ranks and cross-state comparisons."],
        "known_limitations": ["Synthetic technology-agreement decisions only."],
        "review": {
            "status": "approved",
            "reviewed_pairs": 1,
            "reviewers": [
                {"id": "reviewer-1", "qualification": "Transactional technology lawyer"}
            ],
        },
        "approval": {"approved_by": "release-owner", "approved_on": "2026-08-04"},
    }
    card_path = tmp_path / "preference-card.yaml"
    card_path.write_text(yaml.safe_dump(card, sort_keys=False), encoding="utf-8")
    frozen = tmp_path / "frozen"
    freeze_dataset(build, card_path, frozen)
    assert verify_frozen_release(frozen)["valid"] is True


def test_pair_verifier_detects_tampering(tmp_path: Path) -> None:
    out = tmp_path / "pairs"
    build_decision_pairs(_candidates(tmp_path), _registry(tmp_path), out)
    pairs = out / "decision_pairs.jsonl"
    pairs.write_bytes(pairs.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="output hash mismatch"):
        verify_decision_pairs(out)
