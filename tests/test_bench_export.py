"""Tests for the benchmark scorecard, SFT export, and HTML render utilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import EXAMPLES, MATTERS, ROOT

from playbook_legal import PlaybookEnv
from playbook_legal.bench import main as bench_main
from playbook_legal.cli import main as eval_main
from playbook_legal.dataset import verify_trace_replay
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
    assert payload["aggregate"]["critical_failure_rate"] == 0.0
    markdown = out.with_suffix(".md").read_text(encoding="utf-8")
    assert markdown.startswith("# Playbook scorecard")
    assert "Split: `custom`" in markdown


def test_bench_checkpoints_every_episode_and_resumes(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "scorecard"
    argv = [
        "playbook-bench",
        "--matters",
        str(ROOT / "matters"),
        "--examples",
        str(EXAMPLES),
        "--runner",
        "replay",
        "--out",
        str(out),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    bench_main()
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    # A completed run leaves no partial behind.
    assert not out.with_suffix(".partial.json").exists()

    # Simulate an interrupted sweep: the partial holds every episode already paid
    # for. A resumed run must keep those rows instead of re-running them.
    poisoned = [dict(row, normalized_score=-99.0) for row in payload["episodes"]]
    out2 = tmp_path / "resumed"
    out2.with_suffix(".partial.json").write_text(json.dumps(poisoned), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", argv[:-1] + [str(out2)])
    bench_main()
    resumed = json.loads(out2.with_suffix(".json").read_text(encoding="utf-8"))
    scores = {row["normalized_score"] for row in resumed["episodes"]}
    assert scores == {-99.0}, "resumed run re-executed episodes it should have skipped"
    assert not out2.with_suffix(".partial.json").exists()


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


def test_bench_reports_family_clustered_uncertainty(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "family-scorecard"
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
            "dev",
            "--family-registry",
            str(ROOT / "datasets" / "matter-families.yaml"),
            "--out",
            str(out),
        ],
    )
    bench_main()
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert all("matter_family_id" in row for row in payload["episodes"])
    assert payload["uncertainty"]["metric"] == "critical_failure_rate"
    assert payload["uncertainty"]["resampling_unit"] == "matter_family"


def _bench_argv(out: Path, *extra: str) -> list[str]:
    return [
        "playbook-bench",
        "--matters",
        str(ROOT / "matters"),
        "--examples",
        str(EXAMPLES),
        "--runner",
        "replay",
        "--out",
        str(out),
        *extra,
    ]


def test_bench_retains_no_traces_by_default(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "scorecard"
    monkeypatch.setattr(sys, "argv", _bench_argv(out))
    bench_main()
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert "traces_dir" not in payload
    assert not out.exists(), "no trace directory should appear without --save-traces"


def test_bench_save_traces_round_trips_to_identical_scores(tmp_path: Path, monkeypatch) -> None:
    """A published row must be re-derivable: the retained trace re-scores identically.

    This is the audit property the v0.4.0 rows lack — without a trace, a scorecard
    number can only be taken on trust.
    """
    out = tmp_path / "scorecard"
    monkeypatch.setattr(sys, "argv", _bench_argv(out, "--save-traces", "--seeds", "3"))
    bench_main()
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))

    traces_dir = out / "traces"
    assert payload["traces_dir"] == traces_dir.as_posix()
    assert traces_dir.is_dir()

    scored = {row["matter_id"]: row for row in payload["episodes"]}
    assert scored, "the replay sweep produced no episodes to check"

    checked = 0
    for row in payload["episodes"]:
        matter_id = row["matter_id"]
        trace_path = traces_dir / f"{matter_id}-seed3.trace.json"
        assert trace_path.exists(), f"no retained trace for {matter_id}"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))

        # The file is the canonical trace format the rest of the toolchain consumes.
        assert trace["matter"] == matter_id
        assert trace["seed"] == 3
        assert "initial_observation" in trace
        convert(trace, agent="scripted")
        render(trace)

        # The trace replays deterministically against the shipped matter package.
        verify_trace_replay(trace, ROOT / "matters" / matter_id)

        # playbook-eval re-scores the trace's actions to the identical published row.
        actions_path = tmp_path / f"{matter_id}-actions.jsonl"
        actions_path.write_text(
            "".join(json.dumps(event["action"]) + "\n" for event in trace["events"]),
            encoding="utf-8",
        )
        rescored_path = tmp_path / f"{matter_id}-rescored.json"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "playbook-eval",
                str(ROOT / "matters" / matter_id),
                str(actions_path),
                "--trace",
                str(rescored_path),
            ],
        )
        eval_main()
        rescored = json.loads(rescored_path.read_text(encoding="utf-8"))
        assert rescored["result"]["normalized_score"] == trace["result"]["normalized_score"]
        assert rescored["result"]["normalized_score"] == row["normalized_score"]
        assert rescored["result"] == trace["result"]
        checked += 1

    assert checked == len(scored)


def test_bench_save_traces_refuses_to_resume_a_traceless_checkpoint(
    tmp_path: Path, monkeypatch
) -> None:
    """Interrupt without ``--save-traces``, resume with it: the run must fail loudly.

    Resumed episodes are skipped, so their traces are never written — but
    ``traces_dir`` was emitted unconditionally, publishing a scorecard that claims
    every row is re-scorable from a directory missing most of them.
    """
    first = tmp_path / "scorecard"
    monkeypatch.setattr(sys, "argv", _bench_argv(first))
    bench_main()
    episodes = json.loads(first.with_suffix(".json").read_text(encoding="utf-8"))["episodes"]
    assert episodes, "the replay sweep produced no episodes to checkpoint"

    out = tmp_path / "resumed"
    out.with_suffix(".partial.json").write_text(json.dumps(episodes), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _bench_argv(out, "--save-traces"))
    with pytest.raises(SystemExit) as excinfo:
        bench_main()

    assert excinfo.value.code != 0, "a traceless resume must not exit 0"
    message = str(excinfo.value)
    assert "--save-traces" in message
    assert "has no trace" in message
    assert "Delete the partial checkpoint" in message
    assert "rerun without --save-traces" in message

    # Nothing is published: no scorecard at all, so no traces_dir claim either.
    assert not out.with_suffix(".json").exists(), "no scorecard may be published"
    assert not out.with_suffix(".md").exists()
    assert not (out / "traces").exists()
    assert out.with_suffix(".partial.json").exists(), "the checkpoint must survive for retry"


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
