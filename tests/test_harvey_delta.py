import csv
import importlib.util
import json
from pathlib import Path

EXPERIMENT = Path(__file__).parents[1] / "experiments" / "harvey_lab_delta"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_has_24_unique_pinned_adaptations():
    manifest = json.loads((EXPERIMENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["expected_task_count"] == 24
    assert len(manifest["workflows"]) * len(manifest["scenarios"]) == 24
    assert len({row["scenario"] for row in manifest["scenarios"]}) == 6
    assert len(manifest["source"]["commit"]) == 40


def test_paired_report_uses_only_complete_pairs(tmp_path):
    module = load_module("paired_delta", EXPERIMENT / "paired_delta.py")
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "lab_task_id,playbook_matter\ntask/one,matter_one\n", encoding="utf-8"
    )
    lab = tmp_path / "lab.jsonl"
    playbook = tmp_path / "playbook.jsonl"
    lab.write_text('{"model":"m","task_id":"task/one","score":1}\n', encoding="utf-8")
    playbook.write_text(
        '{"model":"m","task_id":"task/one","score":0.25}\n', encoding="utf-8"
    )
    output = tmp_path / "report.md"
    with mapping.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    module.report(rows, lab, playbook, output)
    report = output.read_text(encoding="utf-8")
    assert "-0.7500" in report
    assert "public since May 2026" in report


def test_run_plan_uses_a_unique_trace_for_every_adaptation(tmp_path):
    module = load_module("paired_delta_plan", EXPERIMENT / "paired_delta.py")
    rows = [
        {"lab_task_id": "contracts/msa/review/01", "playbook_matter": "same"},
        {"lab_task_id": "contracts/msa/redline/01", "playbook_matter": "same"},
    ]
    output = tmp_path / "plan.json"
    module.emit_plan(rows, ["m"], output)
    plan = json.loads(output.read_text(encoding="utf-8"))
    commands = {entry["playbook_command"] for entry in plan}
    assert len(commands) == 2
    assert all("adapter.py" in command for command in commands)


def test_adapter_extracts_office_and_email_text():
    module = load_module("harvey_adapter", EXPERIMENT / "adapter.py")
    import io
    import zipfile

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Operative term</w:t></w:r></w:p></w:body></w:document>',
        )
    assert "Operative term" in module.extract_text("agreement.docx", data.getvalue())
    assert "Client fact" in module.extract_text(
        "instruction.eml", b"Content-Type: text/plain; charset=utf-8\n\nClient fact"
    )


def test_adapter_builds_a_runnable_episode_with_lab_documents(monkeypatch, tmp_path):
    module = load_module("harvey_adapter_env", EXPERIMENT / "adapter.py")
    import io
    import zipfile

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>LAB operative term</w:t></w:r></w:p></w:body></w:document>',
        )

    descriptor = {
        "lab": {
            "commit": "a" * 40,
            "task_id": "contracts/example/scenario-01",
            "title": "Example LAB task",
            "documents": ["agreement.docx"],
        },
        "playbook": {
            "matter_path": "matters/ai_saas_001",
            "question_budget": 2,
        },
    }

    def fake_git(repo, *args, binary=False):
        if args[:2] == ("rev-parse", "HEAD"):
            return "a" * 40 + "\n"
        if args[0] == "show" and binary:
            return data.getvalue()
        raise AssertionError(args)

    monkeypatch.setattr(module, "_git", fake_git)
    env = module.build_env(tmp_path, descriptor)
    observation, _ = env.reset(seed=0)
    lab_document = next(row for row in observation["documents"] if row["id"].startswith("lab_"))
    assert lab_document["title"] == "LAB source: agreement.docx"
    next_observation, *_ = env.step(
        {"type": "read_document", "document_id": lab_document["id"]}
    )
    assert "LAB operative term" in next_observation["last_result"]["content"]


def test_execute_plan_runs_both_forms(monkeypatch, tmp_path):
    module = load_module("paired_delta_execute", EXPERIMENT / "paired_delta.py")
    plan = tmp_path / "plan.json"
    plan.write_text('[{"lab_command":"lab","playbook_command":"playbook"}]', encoding="utf-8")
    seen = []

    class Result:
        returncode = 0

    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: seen.append(command) or Result())
    module.execute_plan(plan, approve_provider_spend=True)
    assert seen == ["lab", "playbook"]
