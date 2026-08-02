"""Tests for the budget-gated baseline sprint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from playbook_legal.baseline_sprint import (
    REQUIRED_METRICS,
    aggregate_scorecards,
    bench_command,
    require_credentials,
    result_markdown,
    validate_models,
)


def test_preflight_rejects_missing_credentials() -> None:
    with pytest.raises(ValueError, match="no baseline requests were started"):
        require_credentials("OWNER_BASELINE_KEY", {})


def test_model_list_must_be_explicit_unique_and_filename_safe() -> None:
    assert validate_models(["provider/model-a", "provider/model-b"]) == [
        "provider/model-a",
        "provider/model-b",
    ]
    with pytest.raises(ValueError, match="non-empty"):
        validate_models([])
    with pytest.raises(ValueError, match="duplicates"):
        validate_models(["model-a", "model-a"])
    with pytest.raises(ValueError, match="collide"):
        validate_models(["org/model", "org:model"])


def test_commands_carry_explicit_model_split_and_output(tmp_path: Path) -> None:
    command = bench_command(
        model="org/model",
        split="held-out",
        matters=tmp_path / "private",
        out=tmp_path / "scorecards" / "held-out",
        seeds=[1, 2],
        temperature=0.1,
    )
    assert command[command.index("--model") + 1] == "org/model"
    assert command[command.index("--split") + 1] == "held-out"
    assert command[command.index("--seeds") + 1 : command.index("--temperature")] == ["1", "2"]


def _scorecard(model: str, split: str, score: float, *, trap: tuple[int, int] = (0, 0)) -> dict:
    aggregate = {metric: 0.5 for metric in REQUIRED_METRICS}
    aggregate.update(
        {
            "episodes": 1,
            "normalized_score": score,
            "critical_failure_free_rate": 1.0,
            "escalation_recall": 0.75,
            "over_escalation_count": 0.25,
            "settled_issue_ratio": 0.8,
        }
    )
    return {
        "runner": "baseline",
        "label": model,
        "split": split,
        "aggregate": aggregate,
        "episodes": [
            {
                "matter_id": "nego_saas_010" if split == "dev" else "held_001",
                "trap_counter_exposure_count": trap[0],
                "trap_counter_acceptance_count": trap[1],
            }
        ],
    }


def test_scorecard_aggregation_validates_metrics_delta_and_trap_note(tmp_path: Path) -> None:
    model = "provider/model-a"
    model_dir = tmp_path / "provider-model-a"
    model_dir.mkdir()
    (model_dir / "dev.json").write_text(
        json.dumps(_scorecard(model, "dev", 0.7, trap=(1, 1))), encoding="utf-8"
    )
    (model_dir / "held-out.json").write_text(
        json.dumps(_scorecard(model, "held-out", 0.6)), encoding="utf-8"
    )

    summary = aggregate_scorecards([model], tmp_path)
    row = summary["models"][0]
    assert row["held_out_minus_dev"] == -0.1
    assert row["nego_saas_010_trap"] == {"episodes": 1, "exposures": 1, "acceptances": 1}
    markdown = result_markdown(summary)
    assert "Held-out − dev" in markdown
    assert "1 trap counter(s) exposed; 1 accepted" in markdown


def test_scorecard_aggregation_rejects_missing_required_metric(tmp_path: Path) -> None:
    model = "model-a"
    model_dir = tmp_path / model
    model_dir.mkdir()
    payload = _scorecard(model, "dev", 0.7)
    del payload["aggregate"]["escalation_recall"]
    (model_dir / "dev.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="escalation_recall"):
        aggregate_scorecards([model], tmp_path)
