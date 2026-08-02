"""Tests for the matter linter."""

from pathlib import Path

import yaml
from conftest import MATTERS

from playbook_legal.lint import CANARY, discover_matter_dirs, lint_matter


def test_shipped_matters_pass_lint() -> None:
    for matter_dir in discover_matter_dirs(MATTERS):
        report = lint_matter(matter_dir)
        assert report.ok, f"{matter_dir}: {report.errors}"


def _write_minimal_matter(root: Path) -> Path:
    matter_dir = root / "test_matter"
    (matter_dir / "documents").mkdir(parents=True)
    (matter_dir / "documents" / "msa.md").write_text(
        "# Agreement\n\n## 1.1 Service\n\nProvider provides the service.\n",
        encoding="utf-8",
    )
    (matter_dir / "matter.yaml").write_text(
        yaml.safe_dump(
            {
                "matter_id": "test_matter",
                "title": "Test",
                "practice_area": "technology_transactions",
                "role": "Customer counsel",
                "assignment": "Review.",
                "constraints": {"maximum_steps": 10, "maximum_client_questions": 2},
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
                        "id": "issue_one",
                        "anchor": "msa §1.1",
                        "severity": "high",
                        "required_citations": ["msa §1.1"],
                        "required_concepts": ["service"],
                    }
                ],
                "final_submission": {"points": 0.5, "required_issue_ids": ["issue_one"]},
            }
        ),
        encoding="utf-8",
    )
    (matter_dir / "hidden_facts.yaml").write_text(
        yaml.safe_dump({"client_answers": {"q_one": "Yes, next month."}}),
        encoding="utf-8",
    )
    return matter_dir


def _mutate_rubric(matter_dir: Path, mutate) -> None:
    rubric_path = matter_dir / "rubric.yaml"
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    mutate(rubric)
    rubric_path.write_text(yaml.safe_dump(rubric), encoding="utf-8")


def test_minimal_matter_passes(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)
    report = lint_matter(matter_dir)
    assert report.ok, report.errors


def test_missing_anchor_fails(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)
    _mutate_rubric(matter_dir, lambda r: r["issues"][0].pop("anchor"))
    report = lint_matter(matter_dir)
    assert any("anchor" in error for error in report.errors)


def test_unresolvable_anchor_fails(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)

    def mutate(rubric):
        rubric["issues"][0]["anchor"] = "msa §9.9"
        rubric["issues"][0]["required_citations"] = ["msa §9.9"]

    _mutate_rubric(matter_dir, mutate)
    report = lint_matter(matter_dir)
    assert any("does not resolve" in error for error in report.errors)


def test_duplicate_anchor_fails(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)

    def mutate(rubric):
        clone = dict(rubric["issues"][0], id="issue_two")
        rubric["issues"].append(clone)

    _mutate_rubric(matter_dir, mutate)
    report = lint_matter(matter_dir)
    assert any("shared by more than one issue" in error for error in report.errors)


def test_question_without_hidden_answer_fails(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)
    (matter_dir / "hidden_facts.yaml").write_text(
        yaml.safe_dump({"client_answers": {}}), encoding="utf-8"
    )
    report = lint_matter(matter_dir)
    assert any("no answer in hidden_facts" in error for error in report.errors)


def test_wrong_canary_fails(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)
    matter_path = matter_dir / "matter.yaml"
    matter = yaml.safe_load(matter_path.read_text(encoding="utf-8"))
    matter["canary"] = "wrong"
    matter_path.write_text(yaml.safe_dump(matter), encoding="utf-8")
    report = lint_matter(matter_dir)
    assert any("canary" in error for error in report.errors)


def test_invalid_regex_fails(tmp_path: Path) -> None:
    matter_dir = _write_minimal_matter(tmp_path)
    _mutate_rubric(
        matter_dir,
        lambda r: r["issues"][0].__setitem__("critical_failure_patterns", ["(unclosed"]),
    )
    report = lint_matter(matter_dir)
    assert any("invalid regex" in error for error in report.errors)
