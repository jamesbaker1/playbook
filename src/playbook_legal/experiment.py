# SPDX-License-Identifier: AGPL-3.0-only

"""Validate the frozen Playbook-1 experiment contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_METRICS = {
    "critical_failure_rate",
    "citation_validity",
    "fabricated_quote_count",
    "completion_rate",
    "required_issue_recall",
    "unsupported_issue_count",
    "question_recall",
    "escalation_recall",
    "over_escalation_count",
    "settled_issue_ratio",
    "trap_counter_acceptance_count",
    "normalized_score",
}
REQUIRED_CONDITIONS = {
    "base",
    "final_answer_sft",
    "state_action_sft",
    "state_action_sft_dpo",
    "external_reference",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_experiment_contract(path: Path) -> dict[str, Any]:
    """Load and validate the preregistered experiment design."""
    contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _require(contract.get("schema_version") == "playbook.experiment.v1", "bad schema_version")
    _require(contract.get("status") == "frozen", "experiment status must be frozen")

    primary = contract.get("primary_metric", {})
    _require(primary.get("name") == "critical_failure_rate", "primary metric must be critical_failure_rate")
    _require(primary.get("direction") == "minimize", "critical_failure_rate must be minimized")
    _require(primary.get("unit") == "episode", "primary metric unit must be episode")

    uncertainty = contract.get("uncertainty", {})
    _require(
        uncertainty.get("resampling_unit") == "matter_family",
        "uncertainty must resample matter families",
    )
    _require(
        uncertainty.get("method") in {"cluster_bootstrap", "family_level_randomization"},
        "unsupported family-level uncertainty method",
    )

    conditions = contract.get("conditions", [])
    condition_ids = {item.get("id") for item in conditions if isinstance(item, dict)}
    _require(condition_ids == REQUIRED_CONDITIONS, "conditions do not match required comparison")
    treatment = next(item for item in conditions if item["id"] == "state_action_sft")
    control = next(item for item in conditions if item["id"] == "final_answer_sft")
    _require(
        treatment.get("token_budget_group") == control.get("token_budget_group") != "",
        "SFT conditions must share a non-empty token_budget_group",
    )
    _require(
        treatment.get("base_model_group") == control.get("base_model_group") != "",
        "SFT conditions must share a non-empty base_model_group",
    )
    _require(
        treatment.get("teacher_model_group") == control.get("teacher_model_group") != "",
        "distillation conditions must share a non-empty teacher_model_group",
    )
    teacher = next(item for item in conditions if item["id"] == "external_reference")
    _require(
        teacher.get("model_group") == treatment.get("teacher_model_group"),
        "external teacher reference must match the distillation teacher_model_group",
    )

    gates = contract.get("release_gates", [])
    _require(bool(gates), "at least one release gate is required")
    for gate in gates:
        metric = gate.get("metric")
        _require(metric in SUPPORTED_METRICS, f"unsupported release-gate metric: {metric!r}")
        _require(gate.get("direction") in {"minimize", "maximize"}, f"bad direction for {metric}")

    execution = contract.get("execution", {})
    if execution.get("model_selection_status") != "approved":
        _require(execution.get("base_model") is None, "unapproved base model must remain null")
        _require(execution.get("teacher_model") is None, "unapproved teacher model must remain null")
    if execution.get("budget_status") != "approved":
        _require(execution.get("paid_budget_usd") is None, "unapproved paid budget must remain null")
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path, nargs="?", default=Path("docs/playbook-1-experiment.yaml"))
    args = parser.parse_args()
    contract = load_experiment_contract(args.contract)
    print(json.dumps({"valid": True, "schema_version": contract["schema_version"]}))


if __name__ == "__main__":
    main()
