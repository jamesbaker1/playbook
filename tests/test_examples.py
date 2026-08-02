"""Every shipped matter must carry a validated good trajectory and scored bad ones.

- ``examples/<matter_id>/good.jsonl`` must complete without critical failure and
  score at least 0.7 normalized.
- ``examples/<matter_id>/bad_*.jsonl`` must score below the good trajectory, and
  files named ``bad_critical_*`` or flagged patterns must trip a critical failure
  where the filename says so.
"""

import pytest
from conftest import EXAMPLES, MATTERS, replay

from playbook_legal.lint import discover_matter_dirs

MATTER_DIRS = discover_matter_dirs(MATTERS)


@pytest.mark.parametrize("matter_dir", MATTER_DIRS, ids=lambda p: p.name)
def test_every_matter_has_good_example(matter_dir) -> None:
    assert (EXAMPLES / matter_dir.name / "good.jsonl").exists(), (
        f"matter {matter_dir.name} must ship examples/{matter_dir.name}/good.jsonl"
    )


@pytest.mark.parametrize("matter_dir", MATTER_DIRS, ids=lambda p: p.name)
def test_good_trajectory_scores_strongly(matter_dir) -> None:
    result = replay(matter_dir, EXAMPLES / matter_dir.name / "good.jsonl")
    assert result["terminated"] is True
    assert result["critical_failure"] is False
    assert result["normalized_score"] >= 0.7


@pytest.mark.parametrize("matter_dir", MATTER_DIRS, ids=lambda p: p.name)
def test_bad_trajectories_score_below_good(matter_dir) -> None:
    example_dir = EXAMPLES / matter_dir.name
    bad_files = sorted(example_dir.glob("bad_*.jsonl"))
    if not bad_files:
        pytest.skip("no bad trajectories for this matter")
    good = replay(matter_dir, example_dir / "good.jsonl")
    for bad_file in bad_files:
        bad = replay(matter_dir, bad_file)
        assert bad["normalized_score"] < good["normalized_score"], bad_file.name
        if bad_file.name.startswith("bad_critical_") or "fabricated" in bad_file.name:
            assert bad["critical_failure"] is True, bad_file.name
