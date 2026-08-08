"""Rollout-pilot tooling: prompt scaffold, resumable generation, per-teacher scoring."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

from conftest import EXAMPLES, MATTERS, ROOT, replay
from test_baseline import FakeClient, load_good_actions, tool_call_message

from playbook_legal import PlaybookEnv

sys.path.insert(0, str(ROOT / "training"))

import generate_rollouts
import score_pilot

SCAFFOLD = ROOT / "training" / "scaffold_prompt.txt"
MATTER_ID = "ai_saas_001"
OTHER_MATTER_ID = "saas_renewal_003"


class ExplodingClient:
    """Any completion request is a re-paid episode, so it fails the test loudly."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kwargs):
        raise AssertionError("a checkpointed episode must never be re-run")


def matters_root(tmp_path: Path) -> Path:
    root = tmp_path / "matters"
    root.mkdir()
    for name in (MATTER_ID, OTHER_MATTER_ID):
        shutil.copytree(MATTERS / name, root / name)
    return root


def run_generate(monkeypatch, client, argv: list[str]) -> None:
    monkeypatch.setattr(generate_rollouts, "build_client", lambda *_a, **_k: client)
    monkeypatch.setattr(sys, "argv", ["generate_rollouts", *argv])
    generate_rollouts.main()


def scripted_client() -> FakeClient:
    return FakeClient([tool_call_message(action) for action in load_good_actions()])


def family_package(tmp_path: Path, matter_id: str = MATTER_ID) -> Path:
    """Lay out one family package the way the pilot variant builds do."""
    root = tmp_path / "families"
    family = root / "ai-saas"
    shutil.copytree(MATTERS / matter_id, family / "matters" / matter_id)
    shutil.copytree(EXAMPLES / matter_id, family / "examples" / matter_id)
    (family / "manifest.json").write_text(
        json.dumps({"family_id": "ai_saas", "split": "train"}), encoding="utf-8"
    )
    return root


def synthesize_trace(out_dir: Path, actions_path: Path, *, rollout: int = 0) -> Path:
    """Write a candidate trace by replaying an action file — no model, no network."""
    env = PlaybookEnv.from_directory(MATTERS / MATTER_ID)
    env.reset(seed=rollout)
    for line in actions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, _, terminated, truncated, _ = env.step(json.loads(line))
        if terminated or truncated:
            break
    return env.save_trace(out_dir / f"{MATTER_ID}_r{rollout}.json")


# --------------------------------------------------------------------------- prompt


def test_scaffold_prompt_is_loadable_and_preserves_the_protocol_contract() -> None:
    text = SCAFFOLD.read_text(encoding="utf-8")
    assert text.strip()
    for clause in (
        "EXACTLY ONE tool call per turn",
        "protocol",
        "operative provision",
        "verbatim",
        "submit_final",
    ):
        assert clause in text, f"scaffold dropped the baseline contract clause: {clause}"


# ------------------------------------------------------------------------ generation


def test_variant_filter_restricts_the_sweep(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "rollouts"
    run_generate(
        monkeypatch,
        scripted_client(),
        [
            "--matters",
            str(matters_root(tmp_path)),
            "--out",
            str(out),
            "--model",
            "fake",
            "--rollouts-per-matter",
            "1",
            "--variant",
            MATTER_ID,
        ],
    )
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert [entry["matter_id"] for entry in index] == [MATTER_ID]
    assert not list(out.glob(f"{OTHER_MATTER_ID}*"))


def test_unknown_variant_is_rejected_before_any_billing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(generate_rollouts, "build_client", lambda *_a, **_k: ExplodingClient())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_rollouts",
            "--matters",
            str(matters_root(tmp_path)),
            "--out",
            str(tmp_path / "rollouts"),
            "--variant",
            "no_such_variant",
        ],
    )
    try:
        generate_rollouts.main()
    except SystemExit as exit_error:
        assert "no_such_variant" in str(exit_error)
    else:  # pragma: no cover - the sweep must not proceed
        raise AssertionError("an unknown variant must abort the sweep")


def test_system_prompt_file_reaches_every_request(tmp_path: Path, monkeypatch) -> None:
    client = scripted_client()
    run_generate(
        monkeypatch,
        client,
        [
            "--matters",
            str(matters_root(tmp_path)),
            "--out",
            str(tmp_path / "rollouts"),
            "--model",
            "fake",
            "--rollouts-per-matter",
            "1",
            "--variant",
            MATTER_ID,
            "--system-prompt-file",
            str(SCAFFOLD),
            "--max-tokens",
            "4096",
        ],
    )
    scaffold = SCAFFOLD.read_text(encoding="utf-8")
    assert {request["messages"][0]["content"] for request in client.requests} == {scaffold}
    assert {request["max_tokens"] for request in client.requests} == {4096}


def test_completed_episode_is_checkpointed_and_never_re_run(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "rollouts"
    root = matters_root(tmp_path)
    argv = [
        "--matters",
        str(root),
        "--out",
        str(out),
        "--model",
        "fake",
        "--rollouts-per-matter",
        "1",
        "--variant",
        MATTER_ID,
    ]
    run_generate(monkeypatch, scripted_client(), argv)
    sidecar = out / f"{MATTER_ID}_r0.result.json"
    assert sidecar.exists()
    first = json.loads((out / "index.json").read_text(encoding="utf-8"))

    # A resumed sweep reuses the recorded record instead of paying for the episode again.
    run_generate(monkeypatch, ExplodingClient(), argv)
    assert json.loads((out / "index.json").read_text(encoding="utf-8")) == first


# --------------------------------------------------------------------------- scoring


def score(tmp_path: Path, rollouts: Path, families: Path, *, bar: float = 0.5) -> dict:
    out = tmp_path / "summary.json"
    assert (
        score_pilot.main(
            [
                "--rollouts",
                str(rollouts),
                "--families-root",
                str(families),
                "--teacher",
                "vendor/teacher-model",
                "--score-bar",
                str(bar),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return json.loads(out.read_text(encoding="utf-8"))


def test_reference_grade_candidate_clears_every_stage(tmp_path: Path) -> None:
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    synthesize_trace(rollouts, EXAMPLES / MATTER_ID / "good.jsonl")
    summary = score(tmp_path, rollouts, family_package(tmp_path))

    assert summary["teacher"]["model"] == "vendor/teacher-model"
    assert summary["teacher"]["seeds"] == [0]
    assert summary["qualitative_assessment"] == []
    (variant,) = summary["environments"]["variants_used"]
    assert variant["variant"] == MATTER_ID
    assert variant["family_id"] == "ai_saas"
    expected = replay(MATTERS / MATTER_ID, EXAMPLES / MATTER_ID / "good.jsonl")
    assert variant["reference_score"] == expected["normalized_score"]

    (candidate,) = summary["candidates"]
    assert candidate["stage_completed"] is True
    assert candidate["stage_critical_free"] is True
    assert candidate["stage_replay_verified"] is True
    assert candidate["stage_above_score_bar"] is True
    assert candidate["survived"] is True
    assert candidate["reject_reason"] is None
    assert candidate["diagnostics"]["read_every_document"] is True
    assert candidate["diagnostics"]["missing_required_issues_at_final"] == []
    assert summary["rollout_yield"]["yield_above_bar"] == 1.0


def test_score_bar_rejects_a_mechanically_valid_candidate(tmp_path: Path) -> None:
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    synthesize_trace(rollouts, EXAMPLES / MATTER_ID / "good.jsonl")
    summary = score(tmp_path, rollouts, family_package(tmp_path), bar=0.999)

    (candidate,) = summary["candidates"]
    assert candidate["stage_replay_verified"] is True
    assert candidate["stage_above_score_bar"] is False
    assert candidate["mechanically_valid"] is True
    assert candidate["survived"] is False
    assert "below bar" in candidate["reject_reason"]
    assert summary["rollout_yield"]["episode_yield_rate"] == 1.0
    assert summary["rollout_yield"]["yield_above_bar"] == 0.0
    assert summary["rollout_yield"]["survivor_traces"] == []


def test_critical_failure_stops_the_pipeline_before_replay(tmp_path: Path) -> None:
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    synthesize_trace(rollouts, EXAMPLES / MATTER_ID / "bad_fabricated_quote.jsonl")
    summary = score(tmp_path, rollouts, family_package(tmp_path))

    (candidate,) = summary["candidates"]
    assert candidate["stage_completed"] is True
    assert candidate["stage_critical_free"] is False
    assert candidate["stage_replay_verified"] is None
    assert candidate["stage_above_score_bar"] is None
    assert candidate["survived"] is False
    assert candidate["reject_reason"] == "critical failure"
    assert candidate["diagnostics"]["fabricated_quotes"]
    assert summary["rollout_yield"]["survivors"] == 0


def test_sidecars_and_chat_records_are_not_scored_as_candidates(tmp_path: Path) -> None:
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    synthesize_trace(rollouts, EXAMPLES / MATTER_ID / "good.jsonl")
    (rollouts / f"{MATTER_ID}_r0.result.json").write_text("{}", encoding="utf-8")
    (rollouts / f"{MATTER_ID}_r0.chat.json").write_text("{}", encoding="utf-8")
    (rollouts / "index.json").write_text("[]", encoding="utf-8")
    summary = score(tmp_path, rollouts, family_package(tmp_path))
    assert summary["rollout_yield"]["candidates_generated"] == 1
