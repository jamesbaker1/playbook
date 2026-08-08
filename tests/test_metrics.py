"""Tests for aggregate and family-aware evaluation metrics."""

import pytest

from playbook_legal.metrics import cluster_bootstrap_difference, cluster_bootstrap_interval

FAMILIES = [f"family_{index}" for index in range(10)]


def episode_rows(failing_families, *, episodes_per_family=3):
    """Family-clustered rows where whole families do or do not fail."""
    failing = set(failing_families)
    return [
        {
            "matter_family_id": family_id,
            "critical_failure": family_id in failing,
            "citation_validity": 0.5 if family_id in failing else 1.0,
        }
        for family_id in FAMILIES
        for _ in range(episodes_per_family)
    ]


def test_cluster_bootstrap_keeps_family_observations_together() -> None:
    rows = [
        {"matter_family_id": "safe", "critical_failure": False},
        {"matter_family_id": "safe", "critical_failure": False},
        {"matter_family_id": "unsafe", "critical_failure": True},
        {"matter_family_id": "unsafe", "critical_failure": True},
    ]
    result = cluster_bootstrap_interval(rows, "critical_failure_rate", samples=500, seed=4)
    assert result["estimate"] == 0.5
    assert result["lower"] == 0.0
    assert result["upper"] == 1.0
    assert result["families"] == 2


def test_cluster_bootstrap_requires_family_labels() -> None:
    with pytest.raises(ValueError, match="matter_family_id"):
        cluster_bootstrap_interval([{"critical_failure": False}], "critical_failure_rate")


def test_cluster_bootstrap_difference_finds_a_known_large_effect() -> None:
    treatment = episode_rows([])
    control = episode_rows(FAMILIES[:7])
    result = cluster_bootstrap_difference(
        treatment, control, "critical_failure_rate", samples=500, seed=1
    )
    assert result["estimate"] == -0.7
    assert result["lower"] is None  # one-sided: the lower tail runs to -inf
    assert result["upper"] < 0
    assert result["excludes_zero"] is True
    assert result["families"] == len(FAMILIES)


def test_cluster_bootstrap_difference_reports_no_effect_when_there_is_none() -> None:
    # Same family set and same failure rate, but the failures land on different
    # families, so the difference is centred on zero with real resampling spread.
    treatment = episode_rows(FAMILIES[:3])
    control = episode_rows(FAMILIES[3:6])
    result = cluster_bootstrap_difference(
        treatment, control, "critical_failure_rate", samples=500, seed=1
    )
    assert result["estimate"] == 0.0
    assert result["upper"] > 0
    assert result["excludes_zero"] is False


def test_cluster_bootstrap_difference_rejects_mismatched_family_sets() -> None:
    treatment = episode_rows([])
    control = [dict(row, matter_family_id="unseen") for row in episode_rows([])]
    with pytest.raises(ValueError, match="identical matter families"):
        cluster_bootstrap_difference(treatment, control, "critical_failure_rate", samples=50)


def test_cluster_bootstrap_difference_requires_family_labels() -> None:
    rows = episode_rows([])
    stripped = [{"critical_failure": False}]
    with pytest.raises(ValueError, match="matter_family_id"):
        cluster_bootstrap_difference(rows, stripped, "critical_failure_rate", samples=50)


def test_cluster_bootstrap_difference_is_deterministic_for_a_seed() -> None:
    treatment = episode_rows(FAMILIES[:2])
    control = episode_rows(FAMILIES[:6])
    first = cluster_bootstrap_difference(
        treatment, control, "critical_failure_rate", samples=200, seed=7
    )
    second = cluster_bootstrap_difference(
        treatment, control, "critical_failure_rate", samples=200, seed=7
    )
    assert first == second
    assert first["seed"] == 7 and first["samples"] == 200


def test_one_sided_bound_is_tighter_than_the_two_sided_bound() -> None:
    treatment = episode_rows(FAMILIES[:2])
    control = episode_rows(FAMILIES[:6])
    one_sided = cluster_bootstrap_difference(
        treatment, control, "critical_failure_rate", samples=500, seed=3
    )
    two_sided = cluster_bootstrap_difference(
        treatment, control, "critical_failure_rate", samples=500, seed=3, one_sided=False
    )
    assert one_sided["one_sided"] is True and two_sided["one_sided"] is False
    assert one_sided["estimate"] == two_sided["estimate"]
    assert one_sided["upper"] <= two_sided["upper"]
    assert two_sided["lower"] is not None
    assert two_sided["lower"] <= two_sided["upper"]


def test_cluster_bootstrap_difference_handles_continuous_metrics() -> None:
    treatment = episode_rows([])
    control = episode_rows(FAMILIES)
    result = cluster_bootstrap_difference(
        treatment, control, "citation_validity", samples=200, seed=0
    )
    assert result["estimate"] == 0.5
    assert result["excludes_zero"] is False  # the one-sided bound only detects decreases
