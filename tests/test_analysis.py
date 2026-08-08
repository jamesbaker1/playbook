"""Tests for the preregistered Playbook-1 release-gate analysis."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from conftest import ROOT

from playbook_legal.analysis import evaluate_release_gates
from playbook_legal.analysis import main as analysis_main
from playbook_legal.experiment import load_experiment_contract

CONTRACT_PATH = ROOT / "docs" / "playbook-1-experiment.yaml"
FAMILIES = [f"family_{index}" for index in range(10)]
EPISODES_PER_FAMILY = 5
SAMPLES = 200


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return load_experiment_contract(CONTRACT_PATH)


def make_rows(
    *,
    critical_families: Sequence[str] = (),
    citation_validity: float = 1.0,
    fabricated_quotes: float = 0.0,
    incomplete_episodes: int = 0,
    **extra: Any,
) -> list[dict[str, Any]]:
    """Family-clustered episode rows, 10 families x 5 episodes, with exact rates."""
    failing = set(critical_families)
    rows = [
        {
            "matter_id": f"{family_id}_{episode}",
            "matter_family_id": family_id,
            "critical_failure": family_id in failing,
            "terminated": True,
            "citation_validity": citation_validity,
            "fabricated_quote_count": fabricated_quotes,
            **extra,
        }
        for family_id in FAMILIES
        for episode in range(EPISODES_PER_FAMILY)
    ]
    for row in rows[:incomplete_episodes]:
        row["terminated"] = False
    return rows


def winning_conditions(**overrides: Any) -> dict[str, list[dict[str, Any]]]:
    """State-action clearly beats final-answer, and both beat the untrained base."""
    conditions = {
        "base": make_rows(critical_families=FAMILIES[:8]),
        "final_answer_sft": make_rows(critical_families=FAMILIES[:7]),
        "state_action_sft": make_rows(),
    }
    conditions.update(overrides)
    return conditions


def gate_for(verdict: dict[str, Any], metric: str) -> dict[str, Any]:
    return next(gate for gate in verdict["gates"] if gate["metric"] == metric)


def test_large_state_action_effect_clears_every_gate(contract: dict[str, Any]) -> None:
    verdict = evaluate_release_gates(contract, winning_conditions(), samples=SAMPLES)
    primary = gate_for(verdict, "critical_failure_rate")
    assert primary["treatment"] == "state_action_sft"
    assert primary["control"] == "final_answer_sft"
    assert primary["decision_rule"] == "one_sided_cluster_bootstrap_ci_excludes_zero"
    assert primary["difference"] == -0.7
    assert primary["bootstrap"]["upper"] < 0
    assert primary["excludes_zero"] is True
    assert primary["passed"] is True
    assert verdict["all_gates_pass"] is True
    assert [gate["metric"] for gate in verdict["gates"]] == [
        "critical_failure_rate",
        "citation_validity",
        "fabricated_quote_count",
        "completion_rate",
    ]


def test_no_effect_fails_the_primary_gate(contract: dict[str, Any]) -> None:
    conditions = winning_conditions(
        final_answer_sft=make_rows(critical_families=FAMILIES[:3]),
        state_action_sft=make_rows(critical_families=FAMILIES[3:6]),
    )
    verdict = evaluate_release_gates(contract, conditions, samples=SAMPLES)
    primary = gate_for(verdict, "critical_failure_rate")
    assert primary["difference"] == 0.0
    assert primary["excludes_zero"] is False
    assert primary["passed"] is False
    assert verdict["all_gates_pass"] is False
    # The guardrails are untouched by the primary metric and still pass.
    assert gate_for(verdict, "citation_validity")["passed"] is True


def test_evaluation_is_deterministic_for_a_seed(contract: dict[str, Any]) -> None:
    conditions = winning_conditions()
    first = evaluate_release_gates(contract, conditions, samples=SAMPLES, seed=5)
    second = evaluate_release_gates(contract, conditions, samples=SAMPLES, seed=5)
    assert first == second
    assert first["uncertainty"]["seed"] == 5


def test_missing_conditions_are_named(contract: dict[str, Any]) -> None:
    conditions = winning_conditions()
    del conditions["base"]
    with pytest.raises(ValueError, match="no episode rows for condition\\(s\\): base"):
        evaluate_release_gates(contract, conditions, samples=SAMPLES)

    conditions = winning_conditions()
    del conditions["final_answer_sft"]
    with pytest.raises(ValueError, match="final_answer_sft"):
        evaluate_release_gates(contract, conditions, samples=SAMPLES)


def test_undeclared_condition_is_rejected(contract: dict[str, Any]) -> None:
    conditions = winning_conditions(state_action=make_rows())
    with pytest.raises(ValueError, match="not declared in the contract: state_action"):
        evaluate_release_gates(contract, conditions, samples=SAMPLES)


def test_conditions_scored_on_different_families_are_rejected(contract: dict[str, Any]) -> None:
    conditions = winning_conditions()
    for row in conditions["state_action_sft"]:
        row["matter_family_id"] = f"other_{row['matter_family_id']}"
    with pytest.raises(ValueError, match="identical matter families"):
        evaluate_release_gates(contract, conditions, samples=SAMPLES)


@pytest.mark.parametrize(
    ("citation_validity", "expected_regression", "passes"),
    [(1.0, 0.0, True), (0.99, 0.01, True), (0.98, 0.02, False)],
)
def test_citation_validity_allows_exactly_one_point(
    contract: dict[str, Any], citation_validity: float, expected_regression: float, passes: bool
) -> None:
    conditions = winning_conditions(
        state_action_sft=make_rows(citation_validity=citation_validity)
    )
    gate = gate_for(
        evaluate_release_gates(contract, conditions, samples=SAMPLES), "citation_validity"
    )
    assert gate["maximum_regression"] == 0.01
    assert gate["regression"] == expected_regression
    assert gate["passed"] is passes


@pytest.mark.parametrize(
    ("fabricated_quotes", "expected_regression", "passes"),
    [(0.0, 0.0, True), (0.02, 0.02, False)],
)
def test_fabricated_quotes_tolerate_no_regression(
    contract: dict[str, Any], fabricated_quotes: float, expected_regression: float, passes: bool
) -> None:
    conditions = winning_conditions(
        state_action_sft=make_rows(fabricated_quotes=fabricated_quotes)
    )
    gate = gate_for(
        evaluate_release_gates(contract, conditions, samples=SAMPLES), "fabricated_quote_count"
    )
    assert gate["maximum_regression"] == 0
    assert gate["regression"] == expected_regression
    assert gate["passed"] is passes


@pytest.mark.parametrize(
    ("incomplete_episodes", "expected_regression", "passes"),
    [(0, 0.0, True), (1, 0.02, True), (2, 0.04, False)],
)
def test_completion_rate_allows_two_points(
    contract: dict[str, Any], incomplete_episodes: int, expected_regression: float, passes: bool
) -> None:
    conditions = winning_conditions(
        state_action_sft=make_rows(incomplete_episodes=incomplete_episodes)
    )
    gate = gate_for(
        evaluate_release_gates(contract, conditions, samples=SAMPLES), "completion_rate"
    )
    assert gate["maximum_regression"] == 0.02
    assert gate["regression"] == expected_regression
    assert gate["passed"] is passes


def test_secondary_reporting_compares_state_action_with_base(contract: dict[str, Any]) -> None:
    verdict = evaluate_release_gates(contract, winning_conditions(), samples=SAMPLES)
    comparison = next(
        item for item in verdict["secondary_reporting"] if item.get("comparison")
    )
    assert comparison["comparison"] == "state_action_sft_lt_base"
    assert comparison["reporting_only"] is True
    assert comparison["bootstrap"]["estimate"] == -0.8
    assert comparison["excludes_zero"] is True


def test_protocol_failure_rate_is_marked_unavailable_without_the_column(
    contract: dict[str, Any],
) -> None:
    verdict = evaluate_release_gates(contract, winning_conditions(), samples=SAMPLES)
    protocol = next(
        item for item in verdict["secondary_reporting"] if item["metric"] == "protocol_failure_rate"
    )
    assert protocol["available"] is False
    assert protocol["by_condition"]["base"]["available"] is False
    assert "protocol_failures" in protocol["by_condition"]["base"]["reason"]


def test_protocol_failure_rate_is_reported_per_condition_when_present(
    contract: dict[str, Any],
) -> None:
    conditions = winning_conditions(
        base=make_rows(critical_families=FAMILIES[:8], protocol_failures=2),
        final_answer_sft=make_rows(critical_families=FAMILIES[:7], protocol_failures=0),
        state_action_sft=make_rows(protocol_failures=0),
    )
    verdict = evaluate_release_gates(contract, conditions, samples=SAMPLES)
    protocol = next(
        item for item in verdict["secondary_reporting"] if item["metric"] == "protocol_failure_rate"
    )
    assert protocol["available"] is True
    assert protocol["scope"] == "per_condition"
    # An episode counts once however many protocol failures it recorded.
    assert protocol["by_condition"]["base"]["value"] == 1.0
    assert protocol["by_condition"]["state_action_sft"]["value"] == 0.0
    assert protocol["by_condition"]["base"]["episodes"] == len(FAMILIES) * EPISODES_PER_FAMILY


def test_per_family_reporting_covers_every_family(contract: dict[str, Any]) -> None:
    verdict = evaluate_release_gates(contract, winning_conditions(), samples=SAMPLES)
    per_family = verdict["per_family"]
    assert per_family["report_per_family"] is True
    assert per_family["metric"] == "critical_failure_rate"
    assert [entry["matter_family_id"] for entry in per_family["families"]] == sorted(FAMILIES)
    first = per_family["families"][0]
    assert set(first["conditions"]) == {"base", "final_answer_sft", "state_action_sft"}
    assert first["conditions"]["state_action_sft"]["episodes"] == EPISODES_PER_FAMILY
    assert first["difference"] == -1.0  # family_0 fails under the control, never under state-action
    assert per_family["families"][-1]["difference"] == 0.0  # family_9 fails under neither


def test_reported_numbers_never_use_negative_zero(contract: dict[str, Any]) -> None:
    # A condition that ties its control must read as 0.0, not -0.0, in the verdict.
    verdict = evaluate_release_gates(contract, winning_conditions(), samples=SAMPLES)
    assert gate_for(verdict, "citation_validity")["regression"] == 0.0
    assert re.search(r"-0\.0(?![1-9])", json.dumps(verdict)) is None


def test_condition_summary_counts_episodes_and_families(contract: dict[str, Any]) -> None:
    verdict = evaluate_release_gates(contract, winning_conditions(), samples=SAMPLES)
    assert verdict["conditions"]["state_action_sft"] == {
        "episodes": len(FAMILIES) * EPISODES_PER_FAMILY,
        "families": len(FAMILIES),
    }
    assert verdict["contract_status"] == "frozen"
    assert verdict["primary_metric"] == "critical_failure_rate"


def write_scorecard(path: Path, rows: list[dict[str, Any]], *, wrapped: bool) -> Path:
    payload = {"runner": "baseline", "episodes": rows} if wrapped else rows
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def cli_argv(tmp_path: Path, conditions: dict[str, list[dict[str, Any]]], out: Path) -> list[str]:
    argv = ["playbook-analysis", "--contract", str(CONTRACT_PATH)]
    for index, (condition, rows) in enumerate(conditions.items()):
        path = write_scorecard(tmp_path / f"{condition}.json", rows, wrapped=index % 2 == 0)
        argv += ["--condition", f"{condition}={path}"]
    return argv + ["--samples", str(SAMPLES), "--out", str(out)]


def test_cli_writes_a_verdict(tmp_path: Path, monkeypatch, capsys) -> None:
    out = tmp_path / "verdict.json"
    monkeypatch.setattr(sys, "argv", cli_argv(tmp_path, winning_conditions(), out))
    analysis_main()
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["all_gates_pass"] is True
    assert len(verdict["gates"]) == 4
    captured = capsys.readouterr().out
    assert "PASS critical_failure_rate" in captured
    assert "Verdict: all release gates pass" in captured


def test_cli_can_fail_the_build_on_a_missed_gate(tmp_path: Path, monkeypatch, capsys) -> None:
    conditions = winning_conditions(
        final_answer_sft=make_rows(critical_families=FAMILIES[:3]),
        state_action_sft=make_rows(critical_families=FAMILIES[3:6]),
    )
    out = tmp_path / "verdict.json"
    argv = cli_argv(tmp_path, conditions, out) + ["--require-pass"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as excinfo:
        analysis_main()
    assert excinfo.value.code == 1
    assert "FAIL critical_failure_rate" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["all_gates_pass"] is False


def test_cli_rejects_a_missing_condition(tmp_path: Path, monkeypatch) -> None:
    conditions = winning_conditions()
    del conditions["base"]
    monkeypatch.setattr(
        sys, "argv", cli_argv(tmp_path, conditions, tmp_path / "verdict.json")
    )
    with pytest.raises(SystemExit, match="2"):
        analysis_main()


def test_cli_requires_at_least_one_condition(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["playbook-analysis", "--contract", str(CONTRACT_PATH)])
    with pytest.raises(SystemExit, match="2"):
        analysis_main()
