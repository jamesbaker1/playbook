"""Tests for the v0.3 escalation contract.

Escalations are matched by concept, budgeted, answered from hidden guidance, and
settled up at final submission: a required escalation that never happened costs
points, and a ``critical_if_missed`` one that never happened is a critical failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from playbook_legal import PlaybookEnv
from playbook_legal.lint import CANARY, lint_matter
from playbook_legal.metrics import compute_metrics

EXCLUSIVITY_GUIDANCE = "Exclusivity of any length needs CEO sign-off; the CEO has refused twice."
UNCAPPED_GUIDANCE = "The deal desk will accept a supercap at three times fees, never uncapped."


def _write_matter(root: Path, **overrides) -> Path:
    """A minimal matter carrying an escalations block (test_lint's pattern, extended)."""
    matter_dir = root / "escalation_matter"
    (matter_dir / "documents").mkdir(parents=True)
    (matter_dir / "documents" / "msa.md").write_text(
        "# Agreement\n\n## 1.1 Service\n\nProvider provides the service.\n",
        encoding="utf-8",
    )
    constraints = {
        "maximum_steps": 20,
        "maximum_client_questions": 2,
        "maximum_escalations": 2,
    }
    constraints.update(overrides.get("constraints", {}))
    (matter_dir / "matter.yaml").write_text(
        yaml.safe_dump(
            {
                "matter_id": "escalation_matter",
                "title": "Escalation Test",
                "practice_area": "technology_transactions",
                "role": "Customer counsel",
                "assignment": "Review and escalate what exceeds your authority.",
                "constraints": constraints,
                "documents": [{"id": "msa", "title": "MSA", "path": "documents/msa.md"}],
                "provenance": {"synthetic": True},
                "canary": CANARY,
            }
        ),
        encoding="utf-8",
    )
    rubric = {
        "critical_failure_score_cap": 0.25,
        "questions": [{"id": "q_one", "points": 0.5, "concepts": ["deadline"]}],
        "escalations": [
            {
                "id": "esc_exclusivity",
                "points": 0.75,
                "concepts": ["exclusivity"],
                "aliases": [["non-compete"], ["vertical", "restriction"]],
                "required": True,
            },
            {
                "id": "esc_uncapped",
                "points": 0.5,
                "concepts": ["uncapped", "liability"],
                "critical_if_missed": True,
            },
        ],
        "issues": [
            {
                "id": "issue_one",
                "anchor": "msa §1.1",
                "severity": "high",
                "required_citations": ["msa §1.1"],
                "required_concepts": ["service"],
            }
        ],
        "final_submission": {
            "points": 0.5,
            "required_issue_ids": [],
            "missed_escalation_penalty": 0.5,
            "required_concepts": ["exclusivity", "uncapped liability"],
            "concept_points": 0.5,
        },
    }
    rubric.update(overrides.get("rubric", {}))
    (matter_dir / "rubric.yaml").write_text(yaml.safe_dump(rubric), encoding="utf-8")
    hidden = {
        "client_answers": {"q_one": "The business wants to sign next month."},
        "escalation_answers": {
            "esc_exclusivity": EXCLUSIVITY_GUIDANCE,
            "esc_uncapped": UNCAPPED_GUIDANCE,
        },
    }
    hidden.update(overrides.get("hidden_facts", {}))
    (matter_dir / "hidden_facts.yaml").write_text(yaml.safe_dump(hidden), encoding="utf-8")
    return matter_dir


def make_env(tmp_path: Path, **overrides) -> PlaybookEnv:
    env = PlaybookEnv.from_directory(_write_matter(tmp_path, **overrides))
    env.reset(seed=1)
    return env


def escalate(topic: str, reason: str) -> dict:
    return {"type": "escalate", "topic": topic, "reason": reason}


EXCLUSIVITY = escalate(
    "Exclusivity",
    "The customer demands a three-year exclusivity; the playbook makes that a rejection item.",
)
UNCAPPED = escalate(
    "Uncapped liability",
    "They want uncapped liability for data breach, which exceeds my authority.",
)
LONG_SUMMARY = (
    "I reviewed the agreement, opened the material issues, and set out the negotiating "
    "posture for each of them in the order the client should work through them."
)


def test_fixture_matter_passes_lint(tmp_path: Path) -> None:
    report = lint_matter(_write_matter(tmp_path))
    assert report.ok, report.errors


def test_matched_escalation_scores_and_returns_guidance(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step(dict(EXCLUSIVITY))
    assert reward == 0.75
    assert observation["last_result"]["guidance"] == EXCLUSIVITY_GUIDANCE
    assert observation["learned_facts"]["esc_exclusivity"] == EXCLUSIVITY_GUIDANCE
    assert observation["submitted_escalation_topics"] == ["Exclusivity"]
    assert env.episode_result()["breakdown"]["raised_escalations"] == ["esc_exclusivity"]


def test_alias_concepts_match_the_same_escalation(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    _, reward, *_ = env.step(
        escalate("Vertical restriction", "They want a vertical restriction on named competitors.")
    )
    assert reward == 0.75
    assert env.episode_result()["breakdown"]["raised_escalations"] == ["esc_exclusivity"]


def test_redundant_escalation_is_penalized(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(EXCLUSIVITY))
    _, reward, *_ = env.step(
        escalate("Exclusivity again", "Raising the exclusivity demand a second time.")
    )
    assert reward == -0.15
    breakdown = env.episode_result()["breakdown"]
    assert breakdown["raised_escalations"] == ["esc_exclusivity"]
    assert breakdown["escalations_total"] == 2


def test_off_rubric_escalation_is_penalized_and_reveals_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step(
        escalate("Font choice", "The counterparty's paper uses an unattractive typeface.")
    )
    assert reward == -0.25
    assert observation["last_result"]["guidance"].startswith("Noted.")
    assert EXCLUSIVITY_GUIDANCE not in json.dumps(observation)
    assert UNCAPPED_GUIDANCE not in json.dumps(observation)
    breakdown = env.episode_result()["breakdown"]
    assert breakdown["raised_escalations"] == []
    assert breakdown["escalations_total"] == 1
    assert [event["type"] for event in breakdown["reward_events"]] == ["off_rubric_escalation"]


def test_every_escalation_consumes_budget_until_exhausted(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    assert env.max_escalations == 2
    observation, *_ = env.step(dict(EXCLUSIVITY))
    assert observation["budgets"]["escalations_remaining"] == 1
    observation, *_ = env.step(
        escalate("Pricing", "An off-rubric escalation still consumes the budget.")
    )
    assert observation["budgets"]["escalations_remaining"] == 0
    observation, reward, *_ = env.step(dict(UNCAPPED))
    assert reward == -0.5
    assert observation["last_result"]["error"] == "Escalation budget exhausted."


def test_escalation_missing_fields_is_rejected(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step({"type": "escalate", "topic": "Exclusivity"})
    assert reward == -0.25
    assert "reason" in observation["last_result"]["error"]
    assert observation["budgets"]["escalations_remaining"] == 2


def test_unrevealed_escalation_guidance_never_leaks(tmp_path: Path) -> None:
    """Escalating one point reveals that point's guidance and nothing else."""
    env = make_env(tmp_path)
    env.step(dict(UNCAPPED))
    env.step(escalate("Payment terms", "Net 90 is unusual but within my authority."))
    env.step({"type": "submit_final", "summary": LONG_SUMMARY})
    observations = json.dumps([event.observation for event in env.trace], ensure_ascii=False)
    everything = json.dumps(
        [{"observation": event.observation, "info": event.info} for event in env.trace],
        ensure_ascii=False,
    )
    assert UNCAPPED_GUIDANCE in observations
    assert EXCLUSIVITY_GUIDANCE not in everything
    for needle in ("escalation_answers", "critical_if_missed", "missed_escalation_penalty"):
        assert needle not in observations


def test_missed_critical_escalation_is_a_critical_failure(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    _, reward, *_ = env.step({"type": "submit_final", "summary": "x" * 200})
    result = env.episode_result()
    assert result["critical_failure"] is True
    assert result["normalized_score"] <= 0.25
    final_event = result["breakdown"]["reward_events"][-1]
    assert final_event["missed_critical_escalations"] == ["esc_uncapped"]
    assert final_event["missed_escalations"] == ["esc_exclusivity"]
    # 0.5 base less one 0.5 penalty for the missed (non-critical) required escalation.
    assert reward == 0.0


def test_missed_required_escalation_costs_points_without_critical_failure(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(UNCAPPED))
    _, reward, *_ = env.step({"type": "submit_final", "summary": "x" * 200})
    result = env.episode_result()
    assert result["critical_failure"] is False
    assert reward == 0.5 - 0.5
    final_event = result["breakdown"]["reward_events"][-1]
    assert final_event["missed_escalations"] == ["esc_exclusivity"]
    assert final_event["missed_critical_escalations"] == []


def test_final_required_concepts_award_a_fraction(tmp_path: Path) -> None:
    def final_reward(name: str, summary: str) -> float:
        env = make_env(tmp_path / name)
        env.step(dict(EXCLUSIVITY))
        env.step(dict(UNCAPPED))
        _, reward, *_ = env.step({"type": "submit_final", "summary": summary})
        return reward

    neither = final_reward(
        "neither", "The agreement is broadly acceptable and I set out the posture below. " * 2
    )
    half = final_reward(
        "half", "I escalated the exclusivity demand and set out the negotiating posture. " * 2
    )
    both = final_reward(
        "both",
        "I escalated the exclusivity demand and the uncapped liability request to the client. " * 2,
    )
    assert neither == 0.5
    assert half == 0.75
    assert both == 1.0


def test_max_score_includes_escalation_points(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    # 0.5 question + (0.75 + 0.5) escalations + 3.25 issue + 0.5 final + 0.5 final concepts
    assert env.reward_engine.max_score == 6.0


def test_escalation_metrics(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(EXCLUSIVITY))
    env.step(escalate("Typeface", "Purely cosmetic, and outside the rubric."))
    env.step({"type": "submit_final", "summary": LONG_SUMMARY})
    metrics = compute_metrics(env.episode_result(), env.rubric)
    assert metrics["escalation_recall"] == 0.5
    assert metrics["over_escalation_count"] == 1
    assert metrics["settled_issue_ratio"] == 1.0


def test_matter_without_escalations_still_works(tmp_path: Path) -> None:
    env = make_env(tmp_path, rubric={"escalations": []})
    _, reward, *_ = env.step({"type": "submit_final", "summary": LONG_SUMMARY})
    result = env.episode_result()
    assert reward == 0.5
    assert result["critical_failure"] is False
    assert result["breakdown"]["raised_escalations"] == []


def test_lint_rejects_escalation_without_concepts(tmp_path: Path) -> None:
    matter_dir = _write_matter(tmp_path)
    rubric_path = matter_dir / "rubric.yaml"
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    rubric["escalations"][0].pop("concepts")
    rubric_path.write_text(yaml.safe_dump(rubric), encoding="utf-8")
    report = lint_matter(matter_dir)
    assert any("must declare concepts" in error for error in report.errors)


def test_lint_warns_on_unreachable_escalation_answer(tmp_path: Path) -> None:
    matter_dir = _write_matter(tmp_path)
    hidden_path = matter_dir / "hidden_facts.yaml"
    hidden = yaml.safe_load(hidden_path.read_text(encoding="utf-8"))
    hidden["escalation_answers"]["esc_ghost"] = "Nothing points here."
    hidden_path.write_text(yaml.safe_dump(hidden), encoding="utf-8")
    report = lint_matter(matter_dir)
    assert report.ok
    assert any("unreachable" in warning and "esc_ghost" in warning for warning in report.warnings)
