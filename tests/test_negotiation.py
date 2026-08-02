"""Tests for the v0.3 deterministic negotiation contract.

The counterparty is a script, not a model: it accepts, counters, or refuses by a
fixed rule. What is scored is the text an issue actually closes on — including
whether the agent accepted counterparty language it should have refused.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from playbook_legal import PlaybookEnv
from playbook_legal.lint import CANARY, lint_matter
from playbook_legal.metrics import compute_metrics

NOTICE_COUNTER = "Provider shall notify Customer within 48 hours of confirming an incident."
NOTICE_COUNTER_MESSAGE = "48 hours is our standard; the security team cannot commit to less."
NOTICE_TRAP = "Provider shall notify Customer within 30 days of confirming an incident."
NOTICE_TRAP_MESSAGE = "Then we will hold at our outside window."
NOTICE_REJECT = "We have nothing further to give on incident notice."
TRAINING_COUNTER = "Provider may use aggregated and de-identified data for service analytics."
TRAINING_COUNTER_MESSAGE = "We can commit to aggregated analytics only."
TRAINING_REJECT = "Our data position is final."
CAP_COUNTER = "Provider's aggregate liability shall not exceed one times the fees paid."
CAP_COUNTER_MESSAGE = "One times fees is what the desk approved."
CAP_REJECT = "One times fees is our final position on the cap."

DOCUMENT = """# Master Services Agreement

## 1.1 Services

Provider will provide the services described in each order form.

## 4.2 Use of Data

Provider may use Customer Data and Outputs to train its models.

## 5.1 Incident Notice

Provider shall notify Customer of a confirmed security incident within a reasonable period.

## 10.2 Limitation of Liability

Provider's aggregate liability shall not exceed the fees paid in the prior twelve months.
"""

POSITIONS = {
    "incident_notice": {
        "resist_rounds": 1,
        "accept_concepts": [["24 hours", "discover"]],
        "counters": [
            {"message": NOTICE_COUNTER_MESSAGE, "text": NOTICE_COUNTER},
            {"message": NOTICE_TRAP_MESSAGE, "text": NOTICE_TRAP},
        ],
        "reject_message": NOTICE_REJECT,
    },
    "data_training": {
        "resist_rounds": 0,
        "accept_concepts": [["shall not use", "train"]],
        "counters": [{"message": TRAINING_COUNTER_MESSAGE, "text": TRAINING_COUNTER}],
        "reject_message": TRAINING_REJECT,
    },
    "liability_cap": {
        "resist_rounds": 0,
        "accept_concepts": [["two times", "supercap"]],
        "counters": [{"message": CAP_COUNTER_MESSAGE, "text": CAP_COUNTER}],
        "reject_message": CAP_REJECT,
    },
}


def _write_matter(root: Path, *, negotiated: bool = True, **overrides) -> Path:
    """A minimal matter with a scripted counterparty (test_lint's pattern, extended)."""
    matter_dir = root / "negotiation_matter"
    (matter_dir / "documents").mkdir(parents=True)
    (matter_dir / "documents" / "msa.md").write_text(DOCUMENT, encoding="utf-8")
    constraints = {
        "maximum_steps": 30,
        "maximum_client_questions": 2,
        "maximum_escalations": 2,
        "maximum_negotiation_rounds": 8,
    }
    constraints.update(overrides.get("constraints", {}))
    (matter_dir / "matter.yaml").write_text(
        yaml.safe_dump(
            {
                "matter_id": "negotiation_matter",
                "title": "Negotiation Test",
                "practice_area": "technology_transactions",
                "role": "Customer counsel",
                "assignment": "Close what you can and hold the non-negotiable positions.",
                "constraints": constraints,
                "documents": [{"id": "msa", "title": "MSA", "path": "documents/msa.md"}],
                "provenance": {"synthetic": True},
                "canary": CANARY,
            }
        ),
        encoding="utf-8",
    )
    (matter_dir / "rubric.yaml").write_text(
        yaml.safe_dump(
            {
                "critical_failure_score_cap": 0.25,
                "questions": [{"id": "q_one", "points": 0.5, "concepts": ["deadline"]}],
                "issues": [
                    {
                        "id": "service_scope",
                        "anchor": "msa §1.1",
                        "severity": "low",
                        "required_citations": ["msa §1.1"],
                        "required_concepts": ["service"],
                    },
                    {
                        "id": "data_training",
                        "anchor": "msa §4.2",
                        "severity": "high",
                        "required_citations": ["msa §4.2"],
                        "required_concepts": ["customer data"],
                        "settlement_points": 1.0,
                        "settlement_concepts": ["aggregated", "de-identified"],
                    },
                    {
                        "id": "incident_notice",
                        "anchor": "msa §5.1",
                        "severity": "high",
                        "required_citations": ["msa §5.1"],
                        "required_concepts": ["notice"],
                        "settlement_points": 1.0,
                        "settlement_concepts": ["24 hours", "discover"],
                        "settlement_critical_failure_patterns": ["30 days"],
                    },
                    {
                        "id": "liability_cap",
                        "anchor": "msa §10.2",
                        "severity": "high",
                        "required_citations": ["msa §10.2"],
                        "required_concepts": ["cap"],
                        "settlement_points": 1.0,
                        "settlement_concepts": ["two times", "supercap"],
                        "non_negotiable": True,
                    },
                ],
                "final_submission": {"points": 0.5, "required_issue_ids": []},
            }
        ),
        encoding="utf-8",
    )
    (matter_dir / "hidden_facts.yaml").write_text(
        yaml.safe_dump({"client_answers": {"q_one": "They want to sign next month."}}),
        encoding="utf-8",
    )
    if negotiated:
        positions = overrides.get("positions", POSITIONS)
        (matter_dir / "counterparty.yaml").write_text(
            yaml.safe_dump({"positions": positions}), encoding="utf-8"
        )
    return matter_dir


def make_env(tmp_path: Path, **overrides) -> PlaybookEnv:
    env = PlaybookEnv.from_directory(_write_matter(tmp_path, **overrides))
    env.reset(seed=1)
    return env


def issue(label: str, section: str, title: str) -> dict:
    return {
        "type": "submit_issue",
        "issue_id": label,
        "title": title,
        "severity": "high",
        "citations": [f"msa §{section}"],
        "analysis": f"The provision at msa section {section} departs from the playbook position.",
        "recommendation": "Replace it with the playbook language.",
    }


def markup(label: str, section: str, text: str, *, document_id: str = "msa") -> dict:
    return {
        "type": "send_markup",
        "issue_id": label,
        "document_id": document_id,
        "section": section,
        "proposed_text": text,
    }


ISSUE_NOTICE = issue("notice", "5.1", "Incident notice window is unbounded")
ISSUE_TRAINING = issue("training", "4.2", "Provider trains on customer data")
ISSUE_CAP = issue("cap", "10.2", "Liability cap is too low")

GOOD_NOTICE = (
    "Provider shall notify Customer without undue delay and in any event within 24 hours "
    "after it discovers a security incident."
)
WEAK_NOTICE = "Provider shall notify Customer promptly after confirming a security incident."
WEAK_TRAINING = "Provider shall never process Customer Data for any purpose whatsoever."
WEAK_CAP = "Provider's aggregate liability shall be two times the fees paid in the prior year."
SUMMARY = (
    "I opened the material issues, negotiated the points the counterparty would move on, and "
    "flagged the positions where we should hold firm rather than concede."
)


def settlement_event(result: dict) -> dict:
    return next(e for e in result["breakdown"]["reward_events"] if e["type"] == "settlement")


def test_fixture_matter_passes_lint(tmp_path: Path) -> None:
    report = lint_matter(_write_matter(tmp_path))
    assert report.ok, report.errors


def test_negotiation_actions_appear_only_when_a_counterparty_exists(tmp_path: Path) -> None:
    quiet = make_env(tmp_path / "quiet", negotiated=False)
    observation = quiet._observation()
    assert quiet.negotiation_enabled is False
    assert "send_markup" not in observation["action_schemas"]
    assert "accept_counterparty" not in observation["action_schemas"]
    assert "negotiation" not in observation["protocol"]
    assert "negotiation" not in observation
    assert "negotiation_rounds_remaining" not in observation["budgets"]

    loud = make_env(tmp_path / "loud")
    observation = loud._observation()
    assert loud.negotiation_enabled is True
    assert "send_markup" in observation["action_schemas"]
    assert "accept_counterparty" in observation["action_schemas"]
    assert "negotiation" in observation["protocol"]
    assert observation["negotiation"] == {}
    assert observation["budgets"]["negotiation_rounds_remaining"] == 8


def test_counterparty_resists_then_accepts(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(ISSUE_NOTICE))

    observation, first, *_ = env.step(markup("notice", "5.1", GOOD_NOTICE))
    assert first == 0.0
    assert observation["last_result"]["response"] == "counter"
    assert observation["last_result"]["message"] == NOTICE_COUNTER_MESSAGE
    assert observation["last_result"]["counter_text"] == NOTICE_COUNTER
    assert observation["negotiation"]["notice"] == {
        "status": "open",
        "rounds_used": 1,
        "last_message": NOTICE_COUNTER_MESSAGE,
        "last_counter_text": NOTICE_COUNTER,
    }

    observation, second, *_ = env.step(markup("notice", "5.1", GOOD_NOTICE))
    assert second == 1.0
    assert observation["last_result"]["response"] == "accepted"
    assert observation["negotiation"]["notice"]["status"] == "closed"
    assert observation["negotiation"]["notice"]["closed_by"] == "ours"

    result = env.episode_result()
    assert result["breakdown"]["settled_issues"] == ["incident_notice"]
    settlement = settlement_event(result)
    assert settlement["closed_by"] == "ours"
    assert settlement["missing_concepts"] == []
    assert result["critical_failure"] is False


def test_markup_resolves_by_anchor_without_a_submitted_issue(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step(markup("standalone", "4.2", WEAK_TRAINING))
    assert reward == 0.0
    assert observation["last_result"]["response"] == "counter"
    assert "standalone" in observation["negotiation"]


def test_accepting_a_compliant_counter_scores_the_settlement(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(ISSUE_TRAINING))
    observation, _, *_ = env.step(markup("training", "4.2", WEAK_TRAINING))
    assert observation["last_result"]["counter_text"] == TRAINING_COUNTER

    observation, reward, *_ = env.step({"type": "accept_counterparty", "issue_id": "training"})
    assert reward == 1.0
    assert observation["negotiation"]["training"]["closed_by"] == "theirs"
    result = env.episode_result()
    assert result["critical_failure"] is False
    settlement = settlement_event(result)
    assert settlement["closed_by"] == "theirs"
    assert sorted(settlement["matched_concepts"]) == ["aggregated", "de-identified"]


def test_accepting_a_trap_counter_is_critical_and_capped(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(ISSUE_NOTICE))
    env.step(markup("notice", "5.1", GOOD_NOTICE))
    observation, _, *_ = env.step(markup("notice", "5.1", WEAK_NOTICE))
    assert observation["last_result"]["counter_text"] == NOTICE_TRAP

    _, reward, *_ = env.step({"type": "accept_counterparty", "issue_id": "notice"})
    env.step({"type": "submit_final", "summary": SUMMARY})
    result = env.episode_result()
    assert reward == 0.0
    assert result["critical_failure"] is True
    assert result["normalized_score"] <= 0.25
    settlement = settlement_event(result)
    assert settlement["critical_failure_pattern"] == "30 days"


def test_conceding_a_non_negotiable_issue_is_critical(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(ISSUE_CAP))
    env.step(markup("cap", "10.2", WEAK_CAP))
    _, reward, *_ = env.step({"type": "accept_counterparty", "issue_id": "cap"})
    result = env.episode_result()
    assert reward == 0.0
    assert result["critical_failure"] is True
    settlement = settlement_event(result)
    assert settlement["non_negotiable_missing"] == ["two times", "supercap"]


def test_rejection_leaves_the_issue_open_and_unscored(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(ISSUE_CAP))
    env.step(markup("cap", "10.2", WEAK_CAP))
    observation, reward, *_ = env.step(markup("cap", "10.2", WEAK_CAP))
    assert reward == 0.0
    assert observation["last_result"]["response"] == "rejected"
    assert observation["last_result"]["message"] == CAP_REJECT
    assert observation["negotiation"]["cap"]["status"] == "open"
    result = env.episode_result()
    assert result["breakdown"]["settled_issues"] == []
    assert [e["type"] for e in result["breakdown"]["reward_events"]][-1] == "counterparty_reject"


def test_negotiation_round_budget_exhaustion(tmp_path: Path) -> None:
    env = make_env(tmp_path, constraints={"maximum_negotiation_rounds": 2})
    assert env.max_negotiation_rounds == 2
    env.step(dict(ISSUE_NOTICE))
    env.step(markup("notice", "5.1", GOOD_NOTICE))
    observation, _, *_ = env.step(markup("notice", "5.1", GOOD_NOTICE))
    assert observation["budgets"]["negotiation_rounds_remaining"] == 0

    observation, reward, *_ = env.step(markup("notice", "5.1", GOOD_NOTICE))
    assert reward == -0.5
    assert observation["last_result"]["error"] == "Negotiation-round budget exhausted."
    observation, reward, *_ = env.step({"type": "accept_counterparty", "issue_id": "notice"})
    assert reward == -0.5


def test_unsupported_markup_is_penalized_and_still_burns_a_round(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step(markup("mystery", "9.9", "Anything at all."))
    assert reward == -0.5
    assert observation["budgets"]["negotiation_rounds_remaining"] == 7
    assert observation["negotiation"] == {}

    observation, reward, *_ = env.step(markup("scope", "1.1", "Provider will use due care."))
    assert reward == -0.5
    assert observation["budgets"]["negotiation_rounds_remaining"] == 6
    events = env.episode_result()["breakdown"]["reward_events"]
    assert [event["type"] for event in events] == ["unsupported_markup", "unsupported_markup"]
    assert "no position" in events[1]["reason"]


def test_missing_markup_fields_costs_no_round(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step(
        {"type": "send_markup", "issue_id": "notice", "document_id": "msa"}
    )
    assert reward == -0.25
    assert observation["last_result"]["missing"] == ["section", "proposed_text"]
    assert observation["budgets"]["negotiation_rounds_remaining"] == 8


def test_markup_on_a_closed_issue_is_a_duplicate_settlement(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.step(dict(ISSUE_NOTICE))
    env.step(markup("notice", "5.1", GOOD_NOTICE))
    env.step(markup("notice", "5.1", GOOD_NOTICE))
    observation, reward, *_ = env.step(markup("notice", "5.1", GOOD_NOTICE))
    assert reward == -0.2
    assert observation["negotiation"]["notice"]["status"] == "closed"
    events = env.episode_result()["breakdown"]["reward_events"]
    assert events[-1]["type"] == "duplicate_settlement"


def test_accept_without_an_outstanding_counter_is_rejected(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    observation, reward, *_ = env.step({"type": "accept_counterparty", "issue_id": "nothing"})
    assert reward == -0.25
    assert "no outstanding" in observation["last_result"]["error"]
    assert observation["budgets"]["negotiation_rounds_remaining"] == 8


def full_episode(tmp_path: Path) -> PlaybookEnv:
    env = make_env(tmp_path)
    for action in (
        {"type": "read_document", "document_id": "msa", "section": "5.1"},
        dict(ISSUE_NOTICE),
        markup("notice", "5.1", GOOD_NOTICE),
        markup("notice", "5.1", GOOD_NOTICE),
        {"type": "submit_final", "summary": SUMMARY},
    ):
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    return env


def test_observations_never_leak_counterparty_configuration(tmp_path: Path) -> None:
    env = full_episode(tmp_path)
    observations = json.dumps([event.observation for event in env.trace], ensure_ascii=False)

    # Delivered counterparty speech is fair game; everything else is hidden state.
    assert NOTICE_COUNTER in observations
    for needle in (
        NOTICE_TRAP,
        NOTICE_TRAP_MESSAGE,
        NOTICE_REJECT,
        TRAINING_COUNTER,
        TRAINING_COUNTER_MESSAGE,
        TRAINING_REJECT,
        CAP_COUNTER,
        CAP_COUNTER_MESSAGE,
        CAP_REJECT,
        "accept_concepts",
        "resist_rounds",
        "reject_message",
        "settlement_points",
        "settlement_concepts",
        "settlement_critical_failure_patterns",
        "non_negotiable",
        "supercap",
    ):
        assert needle not in observations, f"leaked counterparty config: {needle}"


def test_negotiation_episode_is_deterministic(tmp_path: Path) -> None:
    payloads = []
    for index in range(2):
        env = full_episode(tmp_path / f"run{index}")
        payloads.append(
            json.dumps(
                {
                    "events": [
                        {
                            "step": event.step,
                            "action": event.action,
                            "observation": event.observation,
                            "reward": event.reward,
                            "info": event.info,
                        }
                        for event in env.trace
                    ],
                    "result": env.episode_result(),
                },
                sort_keys=True,
            )
        )
    assert payloads[0] == payloads[1]


def test_max_score_includes_settlement_points(tmp_path: Path) -> None:
    negotiated = make_env(tmp_path / "with").reward_engine.max_score
    quiet = make_env(tmp_path / "without", negotiated=False).reward_engine.max_score
    # Three of the four rubric issues carry a counterparty position worth 1.0 each.
    assert negotiated - quiet == 3.0
    assert negotiated == 17.0


def test_settled_issue_ratio_metric(tmp_path: Path) -> None:
    env = full_episode(tmp_path)
    counterparty = env.counterparty
    metrics = compute_metrics(env.episode_result(), env.rubric, counterparty)
    assert metrics["settled_issue_ratio"] == 1 / 3
    assert metrics["escalation_recall"] == 1.0


def test_lint_rejects_a_position_that_is_not_a_rubric_issue(tmp_path: Path) -> None:
    positions = {**POSITIONS, "not_an_issue": POSITIONS["data_training"]}
    matter_dir = _write_matter(tmp_path, positions=positions)
    report = lint_matter(matter_dir)
    assert any("not a rubric issue id" in error for error in report.errors)


def test_lint_requires_accept_concepts_and_reject_message(tmp_path: Path) -> None:
    broken = {"incident_notice": {"counters": [{"message": "no", "text": "no"}]}}
    report = lint_matter(_write_matter(tmp_path, positions=broken))
    assert any("accept_concepts" in error for error in report.errors)
    assert any("reject_message" in error for error in report.errors)


def test_lint_requires_counter_message_and_text(tmp_path: Path) -> None:
    broken = {
        "incident_notice": {
            "accept_concepts": [["24 hours"]],
            "reject_message": NOTICE_REJECT,
            "counters": [{"message": "Only a message."}],
        }
    }
    report = lint_matter(_write_matter(tmp_path, positions=broken))
    assert any("needs text" in error for error in report.errors)


def test_lint_warns_when_a_negotiated_issue_has_no_settlement_points(tmp_path: Path) -> None:
    matter_dir = _write_matter(tmp_path)
    rubric_path = matter_dir / "rubric.yaml"
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    for item in rubric["issues"]:
        if item["id"] == "incident_notice":
            item["settlement_points"] = 0.0
    rubric_path.write_text(yaml.safe_dump(rubric), encoding="utf-8")
    report = lint_matter(matter_dir)
    assert report.ok
    assert any("settlement_points" in warning for warning in report.warnings)
