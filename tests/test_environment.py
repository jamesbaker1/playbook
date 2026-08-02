from pathlib import Path

import pytest

from playbook_legal import PlaybookEnv
from playbook_legal.demo import scripted_actions


ROOT = Path(__file__).resolve().parents[1]
MATTER = ROOT / "matters" / "ai_saas_001"


def test_reset_hides_client_answers() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    observation, info = env.reset(seed=1)
    serialized = str(observation)
    assert "September 15" not in serialized
    assert "employee health-benefits" not in serialized
    assert info["matter_id"] == "ai_saas_001"


def test_ask_client_reveals_only_requested_fact() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=1)
    observation, reward, *_ = env.step(
        {
            "type": "ask_client",
            "question_id": "q_launch_deadline",
            "question": "Is there a fixed deadline?",
        }
    )
    assert reward > 0
    assert "September 15" in observation["last_result"]["answer"]
    assert "employee health-benefits" not in str(observation)


def test_invalid_citation_is_penalized() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=1)
    _, reward, *_ = env.step(
        {
            "type": "submit_issue",
            "issue_id": "data_training",
            "title": "Training right",
            "severity": "high",
            "citations": ["msa §99.9", "playbook §3"],
            "analysis": "Customer Data and Outputs may be used to train models, not aggregated analytics.",
            "recommendation": "Delete it.",
        }
    )
    assert reward < 2.0
    assert "msa §99.9" in env.episode_result()["breakdown"]["invalid_citations"]


def test_scripted_demo_completes_with_strong_score() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=7)
    for action in scripted_actions():
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    result = env.episode_result()
    assert result["terminated"] is True
    assert result["critical_failure"] is False
    assert result["normalized_score"] >= 0.7


def test_cannot_step_after_termination() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=1)
    env.step({"type": "submit_final", "summary": "x" * 200})
    with pytest.raises(RuntimeError):
        env.step({"type": "search_matter", "query": "data"})
