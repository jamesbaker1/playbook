"""Tests for versioned, contamination-safe dataset views."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import MATTERS

from playbook_legal import PlaybookEnv
from playbook_legal.dataset import (
    build_records,
    load_family_registry,
    verify_dataset,
    verify_trace_replay,
    write_dataset,
)
from playbook_legal.demo import scripted_actions


def _trace(tmp_path: Path) -> tuple[dict, Path]:
    env = PlaybookEnv.from_directory(MATTERS / "ai_saas_001")
    env.reset(seed=7)
    for action in scripted_actions():
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    path = env.save_trace(tmp_path / "trace.json")
    return json.loads(path.read_text(encoding="utf-8")), path


def _registry(tmp_path: Path, split: str = "train") -> Path:
    path = tmp_path / "families.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "families": {
                    "saas_customer": {"split": split, "matters": ["ai_saas_001"]}
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_state_actions_pair_each_action_with_preceding_observation(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    records = build_records(
        trace, {"matter_family_id": "saas_customer", "split": "train"}
    )["state_action"]

    assert len(records) == len(trace["events"])
    assert json.loads(records[0]["messages"][1]["content"]) == trace["initial_observation"]
    assert json.loads(records[0]["messages"][2]["content"]) == trace["events"][0]["action"]
    assert json.loads(records[1]["messages"][1]["content"]) == trace["events"][0]["observation"]
    assert records[-1]["metadata"]["terminated"] is True


def test_action_outcome_is_metadata_not_policy_input(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    first = build_records(
        trace, {"matter_family_id": "saas_customer", "split": "train"}
    )["state_action"][0]

    outcome = trace["events"][0]["observation"]["last_result"]["content"]
    prompt = first["messages"][1]["content"]
    assert outcome not in prompt
    assert first["metadata"]["resulting_observation"] == trace["events"][0]["observation"]
    assert first["metadata"]["reward"] == trace["events"][0]["reward"]


def test_state_action_metadata_preserves_template_lineage(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    records = build_records(
        trace,
        {
            "matter_family_id": "saas_customer",
            "split": "train",
            "template_sha256": "d" * 64,
        },
    )["state_action"]
    assert {record["metadata"]["template_sha256"] for record in records} == {"d" * 64}


def test_final_answer_contains_only_initial_context_and_final_work_product(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    record = build_records(
        trace, {"matter_family_id": "saas_customer", "split": "train"}
    )["final_answer"][0]

    assert len(record["messages"]) == 3
    assert record["messages"][-1]["content"] == trace["events"][-1]["action"]["summary"]
    assert trace["events"][-1]["observation"]["last_result"]["message"] not in json.dumps(
        record["messages"]
    )


def test_final_answer_control_receives_complete_visible_matter_but_no_hidden_facts(
    tmp_path: Path,
) -> None:
    trace, _ = _trace(tmp_path)
    record = build_records(
        trace,
        {"matter_family_id": "saas_customer", "split": "train"},
        matter_dir=MATTERS / "ai_saas_001",
    )["final_answer"][0]
    context = json.loads(record["messages"][1]["content"])
    msa = next(document for document in context["documents"] if document["id"] == "msa")
    assert "train" in msa["sections"]["4.2"].lower()
    serialized = json.dumps(context)
    hidden = (MATTERS / "ai_saas_001" / "hidden_facts.yaml").read_text(encoding="utf-8")
    assert "September 15" in hidden
    assert "September 15" not in serialized
    assert "Final work product submitted" not in serialized


def test_registry_rejects_matter_in_two_families(tmp_path: Path) -> None:
    path = tmp_path / "families.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "families": {
                    "one": {"split": "train", "matters": ["same"]},
                    "two": {"split": "held-out", "matters": ["same"]},
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="appears more than once"):
        load_family_registry(path)


def test_registry_accepts_only_hashed_identifiers_for_sealed_families(tmp_path: Path) -> None:
    path = tmp_path / "sealed.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "families": {
                    "sealed_saas": {
                        "split": "held-out",
                        "sealed_matter_hashes": {"eval_001": "a" * 64},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert load_family_registry(path)["eval_001"] == {
        "matter_family_id": "sealed_saas",
        "split": "held-out",
    }

    path.write_text(path.read_text(encoding="utf-8").replace("a" * 64, "not-a-hash"), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid SHA-256"):
        load_family_registry(path)


def test_registry_rejects_one_template_lineage_across_splits(tmp_path: Path) -> None:
    path = tmp_path / "contaminated.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "families": {
                    "training_alias": {
                        "split": "train",
                        "template_sha256": "b" * 64,
                        "matters": ["renamed_train_variant"],
                    },
                    "evaluation_alias": {
                        "split": "held-out",
                        "template_sha256": "b" * 64,
                        "sealed_matter_hashes": {"renamed_eval_variant": "c" * 64},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="template.*multiple splits"):
        load_family_registry(path)


def test_builder_rejects_held_out_family_by_default(tmp_path: Path) -> None:
    _, trace_path = _trace(tmp_path)
    with pytest.raises(ValueError, match="refusing to export held-out"):
        write_dataset([trace_path], _registry(tmp_path, "held-out"), tmp_path / "out")


def test_manifest_and_outputs_are_reproducible(tmp_path: Path) -> None:
    _, trace_path = _trace(tmp_path)
    registry = _registry(tmp_path)
    first = write_dataset([trace_path], registry, tmp_path / "one")
    second = write_dataset([trace_path], registry, tmp_path / "two")

    assert first == second
    assert first["statistics"]["episodes"] == 1
    assert first["statistics"]["families"] == {"saas_customer": 1}
    assert first["statistics"]["actions"]["submit_final"] == 1
    assert first["provenance"]["review_status"] == "unreviewed"
    assert first["inclusion_policy"]["outcomes_excluded_from_policy_prompt"] is True
    assert verify_dataset(tmp_path / "one")["valid"] is True
    assert (tmp_path / "one" / "manifest.json").read_bytes() == (
        tmp_path / "two" / "manifest.json"
    ).read_bytes()
    for view in ("final_answer", "trajectory_chat", "state_action"):
        assert first["outputs"][view]["records"] > 0
        assert (tmp_path / "one" / f"{view}.jsonl").read_bytes() == (
            tmp_path / "two" / f"{view}.jsonl"
        ).read_bytes()


def test_builder_refuses_to_overwrite_nonempty_release(tmp_path: Path) -> None:
    _, trace_path = _trace(tmp_path)
    registry = _registry(tmp_path)
    out = tmp_path / "release"
    write_dataset([trace_path], registry, out)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_dataset([trace_path], registry, out)


def test_trace_replay_verification_rejects_forged_outcome(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    trace["events"][0]["reward"] = 999
    with pytest.raises(ValueError, match="event 1"):
        verify_trace_replay(trace, MATTERS / "ai_saas_001")


def test_trace_replay_verification_requires_recorded_seed(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    del trace["seed"]
    with pytest.raises(ValueError, match="replay seed"):
        verify_trace_replay(trace, MATTERS / "ai_saas_001")


def test_dataset_records_replay_verification_evidence(tmp_path: Path) -> None:
    _, trace_path = _trace(tmp_path)
    out = tmp_path / "verified"
    manifest = write_dataset(
        [trace_path], _registry(tmp_path), out, matters_root=MATTERS
    )
    assert manifest["provenance"]["trace_verification"] == "replay_verified"
    assert manifest["replay_verifications"][0]["events"] > 1
    assert len(manifest["replay_verifications"][0]["matter_package_sha256"]) == 64


def test_verifier_detects_tampered_dataset_view(tmp_path: Path) -> None:
    _, trace_path = _trace(tmp_path)
    out = tmp_path / "release"
    write_dataset([trace_path], _registry(tmp_path), out)
    state_actions = out / "state_action.jsonl"
    state_actions.write_bytes(state_actions.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="view hash mismatch"):
        verify_dataset(out)


def test_verifier_detects_tampered_registry_snapshot(tmp_path: Path) -> None:
    _, trace_path = _trace(tmp_path)
    out = tmp_path / "release"
    write_dataset([trace_path], _registry(tmp_path), out)
    registry = out / "family_registry.yaml"
    registry.write_bytes(registry.read_bytes() + b"# changed\n")
    with pytest.raises(ValueError, match="registry snapshot hash mismatch"):
        verify_dataset(out)
