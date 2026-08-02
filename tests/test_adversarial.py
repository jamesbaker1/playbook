"""Adversarial guarantees: no leakage, no reward gaming, deterministic replay."""

import json

from conftest import EXAMPLES, MATTERS, replay

from playbook_legal import PlaybookEnv
from playbook_legal.demo import scripted_actions

MATTER = MATTERS / "ai_saas_001"

# Distinctive strings from hidden facts the demo never asks about, and rubric
# internals that must never surface in any observation.
HIDDEN_STRINGS = [
    "considers any use of its data or outputs for generalized model training",
    "Procurement can calendar renewal dates",
]
RUBRIC_INTERNAL_STRINGS = [
    "critical_failure_patterns",
    "law prohibits all model training",
    "redline_concepts",
    "required_concepts",
    "quote_points",
]


def run_demo_env() -> PlaybookEnv:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=7)
    for action in scripted_actions():
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    return env


def test_full_episode_never_leaks_hidden_state() -> None:
    """Hidden facts must not leak anywhere; rubric internals must not reach the
    agent-visible observation (scoring detail is allowed in harness-side info)."""
    env = run_demo_env()
    observations = json.dumps([event.observation for event in env.trace], ensure_ascii=False)
    everything = json.dumps(
        [{"observation": event.observation, "info": event.info} for event in env.trace],
        ensure_ascii=False,
    )
    for needle in HIDDEN_STRINGS:
        assert needle not in everything, f"leaked hidden fact: {needle}"
    for needle in RUBRIC_INTERNAL_STRINGS:
        assert needle not in observations, f"leaked rubric internal: {needle}"


def test_scripted_demo_completes_with_strong_score() -> None:
    env = run_demo_env()
    result = env.episode_result()
    assert result["terminated"] is True
    assert result["critical_failure"] is False
    assert result["normalized_score"] >= 0.9


def test_same_seed_and_actions_are_deterministic() -> None:
    payloads = []
    for _ in range(2):
        env = run_demo_env()
        payloads.append(
            json.dumps(
                {
                    "events": [
                        {
                            "step": event.step,
                            "action": event.action,
                            "observation": event.observation,
                            "reward": event.reward,
                        }
                        for event in env.trace
                    ],
                    "result": env.episode_result(),
                },
                sort_keys=True,
            )
        )
    assert payloads[0] == payloads[1]


def test_keyword_stuffing_scores_far_below_good_trajectory() -> None:
    good = replay(MATTER, EXAMPLES / "ai_saas_001" / "good.jsonl")
    stuffed = replay(MATTER, EXAMPLES / "ai_saas_001" / "bad_keyword_stuffing.jsonl")
    assert stuffed["normalized_score"] <= 0.1
    assert good["normalized_score"] - stuffed["normalized_score"] >= 0.6


def test_fabricated_quote_trajectory_is_capped() -> None:
    result = replay(MATTER, EXAMPLES / "ai_saas_001" / "bad_fabricated_quote.jsonl")
    assert result["critical_failure"] is True
    assert result["normalized_score"] <= 0.25


def test_reversed_allocation_redline_is_critical() -> None:
    result = replay(MATTER, EXAMPLES / "ai_saas_001" / "bad_critical_redline.jsonl")
    assert result["critical_failure"] is True
    assert result["normalized_score"] <= 0.25
