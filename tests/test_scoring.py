"""Tests for the v0.2 content-based scoring contract."""

from conftest import MATTERS

from playbook_legal import PlaybookEnv

MATTER = MATTERS / "ai_saas_001"


def make_env() -> PlaybookEnv:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=1)
    env.step({"type": "read_document", "document_id": "msa", "section": "4.2"})
    return env


ISSUE = {
    "type": "submit_issue",
    "issue_id": "my-own-label",
    "title": "Provider training right exceeds playbook",
    "severity": "high",
    "citations": ["msa §4.2", "playbook §3"],
    "analysis": (
        "Customer Data and Outputs may be used to train generalized models; the playbook "
        "permits only aggregated analytics."
    ),
    "recommendation": "Prohibit training on Customer Data and Outputs.",
}


def test_issue_credited_by_anchor_not_id() -> None:
    env = make_env()
    _, reward, *_ = env.step(dict(ISSUE))
    assert reward > 1.0
    assert env.episode_result()["breakdown"]["matched_issues"] == ["data_training"]


def test_issue_without_anchor_citation_is_unsupported() -> None:
    env = make_env()
    action = dict(ISSUE, citations=["playbook §3"])
    _, reward, *_ = env.step(action)
    assert reward < 0
    assert env.episode_result()["breakdown"]["matched_issues"] == []
    assert env.episode_result()["breakdown"]["unsupported_issues"] == ["my-own-label"]


def test_duplicate_rubric_issue_detected_across_labels() -> None:
    env = make_env()
    env.step(dict(ISSUE))
    _, reward, *_ = env.step(dict(ISSUE, issue_id="different-label"))
    assert reward == -0.2


def test_severity_mismatch_loses_severity_points() -> None:
    env = make_env()
    _, right, *_ = env.step(dict(ISSUE))
    env.reset(seed=1)
    env.step({"type": "read_document", "document_id": "msa", "section": "4.2"})
    _, wrong, *_ = env.step(dict(ISSUE, severity="low"))
    assert right - wrong == 0.25


def test_verified_quote_earns_points() -> None:
    env = make_env()
    action = dict(
        ISSUE,
        quotes=[
            {
                "citation": "msa §4.2",
                "text": "Acme may retain information used for these purposes after expiration",
            }
        ],
    )
    _, reward, *_ = env.step(action)
    env2 = make_env()
    _, base_reward, *_ = env2.step(dict(ISSUE))
    assert reward - base_reward == 0.25
    assert not env.episode_result()["critical_failure"]


def test_fabricated_quote_is_critical_failure() -> None:
    env = make_env()
    action = dict(
        ISSUE,
        quotes=[{"citation": "msa §4.2", "text": "Acme shall never train on any data whatsoever."}],
    )
    env.step(action)
    result = env.episode_result()
    assert result["critical_failure"] is True
    assert result["breakdown"]["fabricated_quotes"]
    assert result["normalized_score"] <= 0.25


def test_short_quote_is_unverified_and_penalized_without_fabrication() -> None:
    env = make_env()
    action = dict(ISSUE, quotes=[{"citation": "msa §4.2", "text": "Acme"}])
    _, reward, *_ = env.step(action)
    baseline = make_env()
    _, baseline_reward, *_ = baseline.step(dict(ISSUE))
    assert reward == baseline_reward - 0.25
    assert env.episode_result()["critical_failure"] is False


def test_issue_anchor_must_be_read_before_credit() -> None:
    env = PlaybookEnv.from_directory(MATTER)
    env.reset(seed=1)
    _, reward, *_ = env.step(dict(ISSUE))
    result = env.episode_result()
    assert reward == -0.5
    assert result["breakdown"]["matched_issues"] == []
    assert result["breakdown"]["reward_events"][-1]["type"] == "unread_anchor_issue"


def test_redline_links_by_label() -> None:
    env = make_env()
    env.step(dict(ISSUE))
    _, reward, *_ = env.step(
        {
            "type": "propose_redline",
            "issue_id": "my-own-label",
            "document_id": "msa",
            "section": "4.2",
            "replacement_text": (
                "Provider may use aggregated and de-identified analytics but shall not use "
                "Customer Data or Outputs to train any model."
            ),
            "rationale": "Playbook position.",
        }
    )
    assert reward == 1.0
    assert env.episode_result()["breakdown"]["matched_redlines"] == ["data_training"]


def test_redline_matches_by_anchor_without_prior_issue() -> None:
    env = make_env()
    _, reward, *_ = env.step(
        {
            "type": "propose_redline",
            "issue_id": "standalone",
            "document_id": "msa",
            "section": "4.2",
            "replacement_text": "Provider shall not use Customer Data or Outputs to train models.",
            "rationale": "Playbook position.",
        }
    )
    assert reward > 0


def test_redline_on_unscored_section_is_unsupported() -> None:
    env = make_env()
    _, reward, *_ = env.step(
        {
            "type": "propose_redline",
            "issue_id": "nowhere",
            "document_id": "msa",
            "section": "1.1",
            "replacement_text": "Acme will provide the service with reasonable care.",
            "rationale": "Stylistic.",
        }
    )
    assert reward == -0.5


def test_final_missing_required_issues_penalized() -> None:
    env = make_env()
    _, reward, *_ = env.step({"type": "submit_final", "summary": "x" * 200})
    assert reward == 0.75 - 4 * 0.25


def test_max_score_is_derived_from_rubric() -> None:
    env = make_env()
    assert env.reward_engine.max_score == 16.0
