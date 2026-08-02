from pathlib import Path

import pytest
from conftest import MATTERS

from playbook_legal import PlaybookEnv

MATTER = MATTERS / "ai_saas_001"


def test_reset_hides_client_answers() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    observation, info = env.reset(seed=1)
    serialized = str(observation)
    assert "September 15" not in serialized
    assert "employee health-benefits" not in serialized
    assert info["matter_id"] == "ai_saas_001"


def test_observation_exposes_contract() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    observation, _ = env.reset(seed=1)
    assert "protocol" in observation
    assert set(observation["action_schemas"]) == {
        "read_document",
        "search_matter",
        "ask_client",
        "escalate",
        "submit_issue",
        "revise_issue",
        "propose_redline",
        "revise_redline",
        "submit_final",
    }


def test_full_document_read_marks_every_section_read(ai_saas_env: PlaybookEnv) -> None:
    observation, reward, *_ = ai_saas_env.step(
        {"type": "read_document", "document_id": "msa"}
    )
    assert reward == 0.0
    assert observation["last_result"]["section"] is None
    read = ai_saas_env.reward_engine.state.read_citations
    assert len([citation for citation in read if citation.startswith("msa ")]) == len(
        ai_saas_env.documents["msa"]["sections"]
    )


def test_ask_client_free_text_reveals_only_requested_fact(ai_saas_env: PlaybookEnv) -> None:
    observation, reward, *_ = ai_saas_env.step(
        {"type": "ask_client", "question": "Is there a launch date the business has committed to?"}
    )
    assert reward > 0
    assert "September 15" in observation["last_result"]["answer"]
    assert "employee health-benefits" not in str(observation)


def test_off_rubric_question_consumes_budget(ai_saas_env: PlaybookEnv) -> None:
    before = ai_saas_env._observation()["budgets"]["client_questions_remaining"]
    observation, reward, *_ = ai_saas_env.step(
        {"type": "ask_client", "question": "What is the provider's favorite color?"}
    )
    assert reward < 0
    assert "no responsive information" in observation["last_result"]["answer"]
    assert observation["budgets"]["client_questions_remaining"] == before - 1


def test_question_budget_exhaustion(ai_saas_env: PlaybookEnv) -> None:
    for index in range(ai_saas_env.max_client_questions):
        ai_saas_env.step({"type": "ask_client", "question": f"Unrelated question {index}?"})
    observation, reward, *_ = ai_saas_env.step(
        {"type": "ask_client", "question": "One more question?"}
    )
    assert reward == -0.5
    assert "budget" in observation["last_result"]["error"].lower()


def test_invalid_citation_is_penalized(ai_saas_env: PlaybookEnv) -> None:
    _, reward, *_ = ai_saas_env.step(
        {
            "type": "submit_issue",
            "issue_id": "training",
            "title": "Training right",
            "severity": "high",
            "citations": ["msa §4.2", "msa §99.9"],
            "analysis": "Customer Data and Outputs may be used to train models.",
            "recommendation": "Delete it.",
        }
    )
    assert reward < 2.0
    assert "msa §99.9" in ai_saas_env.episode_result()["breakdown"]["invalid_citations"]


def test_cannot_step_after_termination(ai_saas_env: PlaybookEnv) -> None:
    ai_saas_env.step({"type": "submit_final", "summary": "x" * 200})
    with pytest.raises(RuntimeError):
        ai_saas_env.step({"type": "search_matter", "query": "data"})


def test_unknown_action_penalized(ai_saas_env: PlaybookEnv) -> None:
    observation, reward, terminated, truncated, _ = ai_saas_env.step({"type": "sue_everyone"})
    assert reward == -0.5
    assert not terminated and not truncated
    assert "Unknown action" in observation["last_result"]["error"]


def test_step_budget_truncates() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=1)
    truncated = False
    for _ in range(env.max_steps + 1):
        try:
            _, _, _, truncated, _ = env.step({"type": "search_matter", "query": "data"})
        except RuntimeError:
            break
    assert truncated
    assert env.episode_result()["truncated"] is True


def test_save_trace_writes_file(tmp_path: Path) -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=3)
    destination = env.save_trace(tmp_path / "trace.json")
    assert destination.exists()
