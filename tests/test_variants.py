"""Tests for deterministic constrained matter-family variants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from conftest import EXAMPLES, MATTERS, ROOT

from playbook_legal import PlaybookEnv
from playbook_legal.dataset import load_family_registry
from playbook_legal.lint import lint_matter
from playbook_legal.variants import build_catalog, generate_family

SPEC = ROOT / "datasets" / "families" / "ai-saas-pivots.yaml"
AUTHORITY_SPEC = ROOT / "datasets" / "families" / "nego-saas-authority.yaml"
CATALOG = ROOT / "datasets" / "family-catalog.yaml"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _canonical_hash(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_spec(tmp_path: Path, mutate) -> Path:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    mutate(spec)
    path = tmp_path / "family.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def test_family_generation_is_byte_deterministic_and_valid(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = generate_family(SPEC, MATTERS, EXAMPLES, first)
    assert manifest == generate_family(SPEC, MATTERS, EXAMPLES, second)
    assert _files(first) == _files(second)
    emitted = sorted(
        (file for variant in manifest["variants"] for file in variant["files"]),
        key=lambda item: item["path"],
    )
    assert manifest["output_tree_sha256"] == _canonical_hash(emitted)
    assert manifest["template_sha256"] == _canonical_hash(manifest["base_files"])
    assert manifest["dimension_coverage"]["required"] == manifest["dimension_coverage"][
        "covered"
    ]
    for file in emitted:
        assert hashlib.sha256((first / file["path"]).read_bytes()).hexdigest() == file["sha256"]

    assert [item["variant_id"] for item in manifest["variants"]] == [
        "ai_saas_pivot_001",
        "ai_saas_pivot_002",
        "ai_saas_pivot_clean_003",
    ]
    for item in manifest["variants"]:
        assert item["validation"]["reference_score"] >= 0.9
        assert item["validation"]["terminated"] is True
        assert item["validation"]["truncated"] is False
        matter = first / "matters" / item["variant_id"]
        assert lint_matter(matter).ok
    clean = next(item for item in manifest["variants"] if item["variant_id"].endswith("clean_003"))
    assert clean["dimensions"] == ["clean_vs_issue_bearing"]
    assert clean["validation"]["adversarial"][0]["expected_event_type"] == "unsupported_issue"
    assert clean["validation"]["adversarial"][0]["score"] <= 0.5


def test_variants_change_meaningful_state_without_mutating_source(tmp_path: Path) -> None:
    source_before = (MATTERS / "ai_saas_001" / "matter.yaml").read_bytes()
    out = tmp_path / "family"
    generate_family(SPEC, MATTERS, EXAMPLES, out)

    fixed = PlaybookEnv.from_directory(out / "matters" / "ai_saas_pivot_001")
    flexible = PlaybookEnv.from_directory(out / "matters" / "ai_saas_pivot_002")
    fixed_observation, _ = fixed.reset(seed=0)
    flexible_observation, _ = flexible.reset(seed=0)
    assert fixed.max_client_questions == 3
    assert flexible.max_steps == 26
    assert fixed_observation["documents"] != flexible_observation["documents"]
    fixed_answer, *_ = fixed.step(
        {"type": "ask_client", "question": "Is there a fixed launch deadline?"}
    )
    flexible_answer, *_ = flexible.step(
        {"type": "ask_client", "question": "Is there a fixed launch deadline?"}
    )
    assert "limiting leverage" in fixed_answer["last_result"]["answer"]
    assert "meaningful leverage" in flexible_answer["last_result"]["answer"]
    clean_dir = out / "matters" / "ai_saas_pivot_clean_003"
    clean_rubric = yaml.safe_load((clean_dir / "rubric.yaml").read_text(encoding="utf-8"))
    assert clean_rubric["issues"] == []
    assert clean_rubric["final_submission"]["required_issue_ids"] == []
    clean_actions = (out / "examples" / "ai_saas_pivot_clean_003" / "good.jsonl").read_text(
        encoding="utf-8"
    )
    assert "submit_issue" not in clean_actions
    assert "propose_redline" not in clean_actions
    assert (MATTERS / "ai_saas_001" / "matter.yaml").read_bytes() == source_before


def test_generation_rejects_conflicting_semantic_transforms(tmp_path: Path) -> None:
    def duplicate_budget(spec: dict) -> None:
        spec["variants"] = [spec["variants"][0]]
        spec["variants"][0]["transforms"].append(
            {"type": "set_budget", "name": "maximum_client_questions", "value": 2}
        )

    with pytest.raises(ValueError, match="multiple transforms target"):
        generate_family(
            _write_spec(tmp_path, duplicate_budget), MATTERS, EXAMPLES, tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()


def test_reference_must_terminate_above_threshold(tmp_path: Path) -> None:
    def impossible_threshold(spec: dict) -> None:
        spec["variants"] = [spec["variants"][0]]
        spec["minimum_reference_score"] = 1.01

    with pytest.raises(ValueError, match="reference replay failed"):
        generate_family(
            _write_spec(tmp_path, impossible_threshold), MATTERS, EXAMPLES, tmp_path / "out"
        )


def test_family_must_cover_declared_semantic_dimensions(tmp_path: Path) -> None:
    def demand_uncovered_dimension(spec: dict) -> None:
        spec["variants"] = [spec["variants"][0]]
        spec["required_dimensions"] = ["counterparty_behavior"]

    with pytest.raises(ValueError, match="counterparty_behavior"):
        generate_family(
            _write_spec(tmp_path, demand_uncovered_dimension),
            MATTERS,
            EXAMPLES,
            tmp_path / "out",
        )
    assert not (tmp_path / "out").exists()


def test_held_out_generation_emits_only_hashed_registry_entries(tmp_path: Path) -> None:
    def seal(spec: dict) -> None:
        spec["split"] = "held-out"
        spec["variants"] = [spec["variants"][0]]
        spec["required_dimensions"] = [
            "budgets",
            "document_order",
            "hidden_facts",
            "leverage_and_facts",
        ]

    out = tmp_path / "sealed"
    manifest = generate_family(_write_spec(tmp_path, seal), MATTERS, EXAMPLES, out)
    fragment = manifest["registry_fragment"]
    family = fragment["families"]["ai_saas_pivots"]
    assert "matters" not in family
    assert set(family["sealed_matter_hashes"]) == {"ai_saas_pivot_001"}
    assert family["template_sha256"] == manifest["template_sha256"]
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump(fragment), encoding="utf-8")
    assert load_family_registry(registry_path)["ai_saas_pivot_001"]["split"] == "held-out"
    assert "fixed launch" not in json.dumps(fragment).lower()


def test_generator_refuses_to_overwrite_output(tmp_path: Path) -> None:
    out = tmp_path / "family"
    generate_family(SPEC, MATTERS, EXAMPLES, out)
    with pytest.raises(FileExistsError):
        generate_family(SPEC, MATTERS, EXAMPLES, out)


def test_authority_bundle_aligns_fallback_and_adversarial_gates(tmp_path: Path) -> None:
    out = tmp_path / "authority"
    manifest = generate_family(AUTHORITY_SPEC, MATTERS, EXAMPLES, out)
    strict = next(item for item in manifest["variants"] if item["variant_id"].endswith("strict_001"))
    fallback = next(
        item for item in manifest["variants"] if item["variant_id"].endswith("fallback_002")
    )
    assert strict["validation"]["adversarial"][0]["critical_failure"] is True
    assert strict["validation"]["adversarial"][0]["score"] <= 0.25
    assert fallback["dimensions"] == ["authority_and_fallback", "counterparty_behavior"]
    assert fallback["validation"]["reference_score"] >= 0.9
    assert fallback["validation"]["adversarial"][0]["expected_event_type"] == (
        "off_rubric_escalation"
    )

    matter_dir = out / "matters" / "nego_saas_fallback_002"
    rubric = yaml.safe_load((matter_dir / "rubric.yaml").read_text(encoding="utf-8"))
    training = next(issue for issue in rubric["issues"] if issue["id"] == "data_training")
    assert training["non_negotiable"] is False
    assert rubric["escalations"] == []
    hidden = yaml.safe_load((matter_dir / "hidden_facts.yaml").read_text(encoding="utf-8"))
    assert hidden["escalation_answers"] == {}
    actions = (
        out / "examples" / "nego_saas_fallback_002" / "good.jsonl"
    ).read_text(encoding="utf-8")
    assert '"type":"escalate"' not in actions
    assert '"type":"accept_counterparty"' in actions


def test_catalog_build_is_reproducible_and_reports_target_gap(tmp_path: Path) -> None:
    first = tmp_path / "catalog-one"
    second = tmp_path / "catalog-two"
    manifest = build_catalog(CATALOG, MATTERS, EXAMPLES, first)
    assert manifest == build_catalog(CATALOG, MATTERS, EXAMPLES, second)
    assert _files(first) == _files(second)
    assert manifest["ready"] is False
    assert manifest["targets"]["training_families"] == {
        "target": 20,
        "actual": 12,
        "met": False,
    }
    assert manifest["targets"]["training_variants"]["actual"] == 42
    registry = load_family_registry(first / "family_registry.yaml")
    assert len(registry) == 42
    assert {entry["matter_family_id"] for entry in registry.values()} == {
        "ai_saas_pivots",
        "clean_paper_restraint",
        "cloud_operations",
        "embedded_software_license",
        "fintech_vendor_risk",
        "health_data_governance",
        "merger_target_response",
        "ml_development_ip",
        "nego_saas_authority",
        "policy_saas_renewal",
        "private_acquisition_mandate",
        "provider_deal_desk",
    }


def test_catalog_target_gate_fails_atomically(tmp_path: Path) -> None:
    out = tmp_path / "catalog"
    with pytest.raises(ValueError, match="does not meet required targets"):
        build_catalog(CATALOG, MATTERS, EXAMPLES, out, require_targets=True)
    assert not out.exists()
