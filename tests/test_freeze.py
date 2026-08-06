"""Tests for reviewed, content-addressed dataset freezing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from conftest import EXAMPLES, MATTERS

from playbook_legal import PlaybookEnv
from playbook_legal.dataset import write_dataset
from playbook_legal.demo import scripted_actions
from playbook_legal.freeze import freeze_dataset, verify_frozen_release


def _trace(tmp_path: Path, *, critical: bool = False) -> Path:
    env = PlaybookEnv.from_directory(MATTERS / "ai_saas_001")
    env.reset(seed=7)
    actions = scripted_actions()
    if critical:
        actions = [
            json.loads(line)
            for line in (EXAMPLES / "ai_saas_001" / "bad_fabricated_quote.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
    for action in actions:
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    path = env.save_trace(tmp_path / "trace.json")
    return path


def _build(tmp_path: Path, *, split: str = "train", critical: bool = False) -> Path:
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "families": {
                    "saas_customer": {"split": split, "matters": ["ai_saas_001"]}
                },
            }
        ),
        encoding="utf-8",
    )
    build = tmp_path / "build"
    write_dataset(
        [_trace(tmp_path, critical=critical)],
        registry,
        build,
        allow_held_out=split == "held-out",
        reviewer="reviewer-1",
        review_status="approved",
        matters_root=MATTERS,
    )
    return build


def _card(tmp_path: Path, build: Path, **changes) -> Path:
    manifest_hash = hashlib.sha256((build / "manifest.json").read_bytes()).hexdigest()
    payload = {
        "schema_version": "playbook.freeze.v1",
        "release_id": "playbook-sft-2026-08-001",
        "intended_use": "positive_sft",
        "dataset_manifest_sha256": manifest_hash,
        "inclusion_criteria": ["Replay-verified and approved complete trajectories."],
        "exclusion_criteria": ["Protocol failures and critical failures."],
        "known_limitations": ["Synthetic technology-agreement matters only."],
        "review": {
            "status": "approved",
            "reviewed_episodes": 1,
            "reviewers": [
                {"id": "reviewer-1", "qualification": "Transactional technology lawyer"}
            ],
        },
        "approval": {"approved_by": "release-owner", "approved_on": "2026-08-04"},
    }
    payload.update(changes)
    path = tmp_path / "data-card.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_freeze_is_reproducible_and_independently_verifiable(tmp_path: Path) -> None:
    build = _build(tmp_path)
    card = _card(tmp_path, build)
    first = freeze_dataset(build, card, tmp_path / "frozen-one")
    second = freeze_dataset(build, card, tmp_path / "frozen-two")
    assert first == second
    verified = verify_frozen_release(tmp_path / "frozen-one")
    assert verified["valid"] is True
    assert verified["release_id"] == "playbook-sft-2026-08-001"


def test_freeze_requires_complete_qualified_review_coverage(tmp_path: Path) -> None:
    build = _build(tmp_path)
    card = _card(
        tmp_path,
        build,
        review={
            "status": "approved",
            "reviewed_episodes": 2,
            "reviewers": [{"id": "reviewer-1", "qualification": "Technology lawyer"}],
        },
    )
    with pytest.raises(ValueError, match="every episode"):
        freeze_dataset(build, card, tmp_path / "frozen")


def test_positive_sft_freeze_rejects_critical_failures(tmp_path: Path) -> None:
    build = _build(tmp_path, critical=True)
    with pytest.raises(ValueError, match="critical-failure episodes"):
        freeze_dataset(build, _card(tmp_path, build), tmp_path / "frozen")


def test_positive_sft_freeze_rejects_held_out_data(tmp_path: Path) -> None:
    build = _build(tmp_path, split="held-out")
    with pytest.raises(ValueError, match="held-out data"):
        freeze_dataset(build, _card(tmp_path, build), tmp_path / "frozen")


def test_frozen_release_verifier_detects_tampering(tmp_path: Path) -> None:
    build = _build(tmp_path)
    release = tmp_path / "frozen"
    freeze_dataset(build, _card(tmp_path, build), release)
    view = release / "dataset" / "state_action.jsonl"
    view.write_bytes(view.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="tree hash mismatch"):
        verify_frozen_release(release)


def test_freeze_refuses_to_overwrite_release(tmp_path: Path) -> None:
    build = _build(tmp_path)
    card = _card(tmp_path, build)
    release = tmp_path / "frozen"
    freeze_dataset(build, card, release)
    with pytest.raises(FileExistsError):
        freeze_dataset(build, card, release)
