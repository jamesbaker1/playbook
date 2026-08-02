"""Gymnasium adapter tests (skipped when gymnasium is not installed)."""

import json

import pytest
from conftest import MATTERS

gymnasium = pytest.importorskip("gymnasium")

from playbook_legal.gym_adapter import PlaybookGymEnv


def test_reset_and_step_round_trip() -> None:
    env = PlaybookGymEnv(MATTERS / "ai_saas_001")
    observation, info = env.reset(seed=3)
    assert info["matter_id"] == "ai_saas_001"
    parsed = json.loads(observation)
    assert "action_schemas" in parsed

    observation, reward, terminated, truncated, _ = env.step(
        json.dumps({"type": "read_document", "document_id": "msa", "section": "4.2"})
    )
    assert reward == 0.0
    assert not terminated and not truncated
    assert "Model Training" in json.loads(observation)["last_result"]["content"]


def test_invalid_action_string_is_penalized_not_fatal() -> None:
    env = PlaybookGymEnv(MATTERS / "ai_saas_001")
    env.reset(seed=3)
    _, reward, terminated, truncated, _ = env.step("this is not json")
    assert reward == -0.5
    assert not terminated and not truncated


def test_terminates_on_final() -> None:
    env = PlaybookGymEnv(MATTERS / "ai_saas_001")
    env.reset(seed=3)
    _, _, terminated, _, _ = env.step(json.dumps({"type": "submit_final", "summary": "x" * 200}))
    assert terminated
    assert env.episode_result()["terminated"] is True
