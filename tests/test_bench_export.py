"""Tests for the benchmark scorecard, SFT export, and HTML render utilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import EXAMPLES, MATTERS, ROOT

from playbook_legal import PlaybookEnv
from playbook_legal.bench import main as bench_main
from playbook_legal.demo import scripted_actions
from playbook_legal.export import convert
from playbook_legal.render import render


def make_trace(tmp_path: Path) -> dict:
    env = PlaybookEnv.from_directory(MATTERS / "ai_saas_001")
    env.reset(seed=7)
    for action in scripted_actions():
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    path = env.save_trace(tmp_path / "trace.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_produces_chat_record(tmp_path: Path) -> None:
    trace = make_trace(tmp_path)
    record = convert(trace, agent="scripted")
    assert record["matter_id"] == "ai_saas_001"
    assert record["agent"] == "scripted"
    assert record["score"] >= 0.9
    assert record["messages"][0]["role"] == "system"
    assert record["messages"][1]["role"] == "user"
    assert record["messages"][2]["role"] == "assistant"
    json.loads(record["messages"][2]["content"])  # actions are valid JSON


def test_export_pairs_actions_with_preceding_observations(tmp_path: Path) -> None:
    trace = make_trace(tmp_path)
    record = convert(trace, agent="scripted")

    initial = json.loads(record["messages"][1]["content"])
    first_result = trace["events"][0]["observation"]["last_result"]["content"]
    assert initial["last_result"] == {"message": "Matter opened."}
    assert first_result not in record["messages"][1]["content"]
    assert json.loads(record["messages"][2]["content"]) == trace["events"][0]["action"]
    assert first_result == json.loads(record["messages"][3]["content"])["last_result"]["content"]


def test_export_rejects_legacy_trace_without_initial_observation(tmp_path: Path) -> None:
    trace = make_trace(tmp_path)
    del trace["initial_observation"]
    with pytest.raises(ValueError, match="regenerate"):
        convert(trace, agent="scripted")


def test_render_produces_html(tmp_path: Path) -> None:
    trace = make_trace(tmp_path)
    html_text = render(trace)
    assert "Playbook episode trace" in html_text
    assert "ai_saas_001" in html_text


def test_bench_replay_scorecard(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "scorecard"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "playbook-bench",
            "--matters",
            str(ROOT / "matters"),
            "--examples",
            str(EXAMPLES),
            "--runner",
            "replay",
            "--out",
            str(out),
        ],
    )
    bench_main()
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["split"] == "custom"
    assert payload["aggregate"]["episodes"] >= 1
    assert payload["aggregate"]["critical_failure_free_rate"] == 1.0
    markdown = out.with_suffix(".md").read_text(encoding="utf-8")
    assert markdown.startswith("# Playbook scorecard")
    assert "Split: `custom`" in markdown


def test_bench_records_explicit_split(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "held-out-scorecard"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "playbook-bench",
            "--matters",
            str(ROOT / "matters"),
            "--examples",
            str(EXAMPLES),
            "--runner",
            "replay",
            "--split",
            "held-out",
            "--out",
            str(out),
        ],
    )
    bench_main()
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["split"] == "held-out"
    assert "Split: `held-out`" in out.with_suffix(".md").read_text(encoding="utf-8")


def test_bench_rejects_duplicate_deterministic_replay_seeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "playbook-bench",
            "--matters",
            str(ROOT / "matters"),
            "--runner",
            "replay",
            "--seeds",
            "0",
            "1",
            "--out",
            str(tmp_path / "scorecard"),
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        bench_main()
