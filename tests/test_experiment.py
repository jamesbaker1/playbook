"""Tests for the frozen Playbook-1 experiment contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from conftest import ROOT

from playbook_legal.experiment import load_experiment_contract

CONTRACT = ROOT / "docs" / "playbook-1-experiment.yaml"


def _write(tmp_path: Path, contract: dict) -> Path:
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return path


def test_repository_experiment_contract_is_frozen_and_valid() -> None:
    contract = load_experiment_contract(CONTRACT)
    assert contract["primary_metric"]["name"] == "critical_failure_rate"
    assert contract["uncertainty"]["resampling_unit"] == "matter_family"
    assert contract["execution"]["base_model"] is None


def test_contract_requires_matched_sft_token_budgets(tmp_path: Path) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    changed = deepcopy(contract)
    condition = next(item for item in changed["conditions"] if item["id"] == "final_answer_sft")
    condition["token_budget_group"] = "larger_control_budget"
    with pytest.raises(ValueError, match="token_budget_group"):
        load_experiment_contract(_write(tmp_path, changed))


def test_contract_requires_the_same_distillation_teacher(tmp_path: Path) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    changed = deepcopy(contract)
    condition = next(item for item in changed["conditions"] if item["id"] == "final_answer_sft")
    condition["teacher_model_group"] = "different_teacher"
    with pytest.raises(ValueError, match="teacher_model_group"):
        load_experiment_contract(_write(tmp_path, changed))


def test_contract_rejects_episode_level_resampling(tmp_path: Path) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    contract["uncertainty"]["resampling_unit"] = "episode"
    with pytest.raises(ValueError, match="matter families"):
        load_experiment_contract(_write(tmp_path, contract))


def test_pending_execution_cannot_smuggle_in_model_or_budget(tmp_path: Path) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    contract["execution"]["base_model"] = "some/model"
    with pytest.raises(ValueError, match="must remain null"):
        load_experiment_contract(_write(tmp_path, contract))


def test_pending_execution_cannot_select_teacher(tmp_path: Path) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    contract["execution"]["teacher_model"] = "some/teacher"
    with pytest.raises(ValueError, match="teacher model"):
        load_experiment_contract(_write(tmp_path, contract))
