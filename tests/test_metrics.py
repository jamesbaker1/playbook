"""Tests for aggregate and family-aware evaluation metrics."""

import pytest

from playbook_legal.metrics import cluster_bootstrap_interval


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
