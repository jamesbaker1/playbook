# SPDX-License-Identifier: AGPL-3.0-only

"""Build and validate the Harvey LAB -> Playbook interactive adaptation batch.

The generated descriptors point to, but do not redistribute, LAB's Office documents.
Run against an official checkout pinned to the commit in ``manifest.json``.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def load_manifest() -> dict:
    return json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))


def source_task(repo: Path, commit: str, task_id: str) -> dict:
    raw = git(repo, "show", f"{commit}:tasks/{task_id}/task.json")
    return json.loads(raw)


def source_documents(repo: Path, commit: str, task_id: str) -> list[str]:
    prefix = f"tasks/{task_id}/documents/"
    paths = git(repo, "ls-tree", "-r", "--name-only", commit, prefix).splitlines()
    return [path.removeprefix(prefix) for path in paths if path]


def build(repo: Path, output: Path) -> tuple[list[dict], list[dict]]:
    manifest = load_manifest()
    commit = manifest["source"]["commit"]
    actual = git(repo, "rev-parse", "HEAD")
    if actual != commit:
        raise SystemExit(f"Harvey checkout is {actual}; expected pinned commit {commit}")

    descriptors = []
    mappings = []
    adaptations = []
    for workflow in manifest["workflows"]:
        for scenario in manifest["scenarios"]:
            adaptations.append(
                {
                    **scenario,
                    "lab_task_id": (
                        "contracts/commercial-vendor-customer/"
                        f"master-services-agreement-{workflow}/scenario-{scenario['scenario']}"
                    ),
                    "counterparty_profile": f"{workflow}-scenario-{scenario['scenario']}",
                    "counterparty_script": {
                        "mode": "deterministic_position_ladder",
                        "source": f"matters/{scenario['playbook_matter']}/hidden_facts.yaml",
                        "behavior": manifest["workflow_overlays"][workflow],
                    },
                    "adaptation_note": (
                        f"Preserves the LAB {workflow} source bundle while withholding the mapped "
                        "Playbook facts and revealing counterparty movement only through actions."
                    ),
                }
            )
    for item in adaptations:
        task_id = item["lab_task_id"]
        task = source_task(repo, commit, task_id)
        documents = source_documents(repo, commit, task_id)
        if not documents or not task.get("criteria"):
            raise SystemExit(f"{task_id}: source documents or rubric criteria are missing")
        matter = ROOT / "matters" / item["playbook_matter"]
        required = [matter / "matter.yaml", matter / "hidden_facts.yaml", matter / "rubric.yaml"]
        if any(not path.is_file() for path in required):
            raise SystemExit(f"{task_id}: invalid Playbook matter {matter.name}")

        descriptor = {
            "descriptor_version": 1,
            "lab": {
                "repository": manifest["source"]["repository"],
                "commit": commit,
                "task_id": task_id,
                "title": task["title"],
                "documents": documents,
                "criterion_count": len(task["criteria"]),
                "observable_bundle": "tasks/<task-id>/documents plus agent instructions",
                "held_out_from_agent": "inline rubric criteria during the run",
            },
            "playbook": {
                "matter_id": item["playbook_matter"],
                "matter_path": f"matters/{item['playbook_matter']}",
                "document_policy": "Use the LAB source documents and playbook at the pinned path; do not substitute public facts for hidden state.",
                "hidden_facts": f"matters/{item['playbook_matter']}/hidden_facts.yaml",
                "question_budget": item["question_budget"],
                "counterparty_profile": item["counterparty_profile"],
                "counterparty_script": item["counterparty_script"],
                "adaptation_note": item["adaptation_note"],
            },
        }
        descriptors.append(descriptor)
        mappings.append(
            {
                "lab_task_id": task_id,
                "playbook_matter": item["playbook_matter"],
                "workflow": task_id.split("/master-services-agreement-", 1)[1].rsplit("/", 1)[0],
                "source_documents": len(documents),
                "source_criteria": len(task["criteria"]),
                "question_budget": item["question_budget"],
            }
        )

    if len(descriptors) != manifest["expected_task_count"]:
        raise SystemExit("adaptation count does not match expected_task_count")
    output.mkdir(parents=True, exist_ok=True)
    (output / "descriptors.json").write_text(
        json.dumps(descriptors, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "mapping.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mappings[0]))
        writer.writeheader()
        writer.writerows(mappings)
    return descriptors, mappings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harvey-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "generated")
    args = parser.parse_args()
    descriptors, mappings = build(args.harvey_repo.resolve(), args.output.resolve())
    print(
        f"Validated {len(descriptors)} adaptations: "
        f"{sum(row['source_documents'] for row in mappings)} source documents, "
        f"{sum(row['source_criteria'] for row in mappings)} source criteria."
    )


if __name__ == "__main__":
    main()
