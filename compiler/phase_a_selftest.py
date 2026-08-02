# SPDX-License-Identifier: AGPL-3.0-only

"""Publishable Phase A compiler self-test over a synthetic known-answer matter.

This module is deliberately not the production implementation of ``pipeline.py``.
It supplies narrow, deterministic adapters for the zero-firm-data experiment in
``docs/matter-compiler.md``: fabricate an evidence trail from a public matter, mine
that trail back into candidates, compare them with the known rubric, emit the
already-synthetic package, lint it, and replay its reference trajectory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

from playbook_legal import PlaybookEnv
from playbook_legal.lint import lint_matter

from .redline_miner import extract_edits, merge_substitutions

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
_EVIDENCE_RE = re.compile(
    r"Issue (?P<id>[a-z0-9_]+) \| anchor (?P<anchor>[^|]+) \| severity "
    r"(?P<severity>low|medium|high) \| concepts (?P<concepts>.+)$"
)


@dataclass(frozen=True)
class RecoveredIssue:
    issue_id: str
    anchor: str
    severity: str
    required_concepts: tuple[str, ...]
    redline_concepts: tuple[str, ...]
    evidence_ids: tuple[str, ...]


def generate_evidence_bundle(source_matter: Path, bundle_dir: Path) -> Path:
    """Create fabricated tracked-change chains and correspondence from a public matter."""
    rubric = _yaml(source_matter / "rubric.yaml")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, object]] = []
    messages: list[dict[str, str]] = []
    for index, issue in enumerate(rubric["issues"], start=1):
        issue_id = str(issue["id"])
        anchor = str(issue["anchor"])
        redline = tuple(str(value) for value in issue.get("redline_concepts", []))
        inserted = "; ".join(redline or issue["required_concepts"])
        original = f"{anchor} Provider's original position remains unchanged."
        revised = bundle_dir / f"{issue_id}_v2_tracked.docx"
        base = bundle_dir / f"{issue_id}_v1.docx"
        _write_docx(base, anchor, original)
        _write_docx(revised, anchor, original, inserted=inserted, revision_id=index)
        for version, path in ((1, base), (2, revised)):
            artifacts.append(
                {
                    "artifact_id": f"{issue_id}-v{version}",
                    "kind": "docx",
                    "logical_document": issue_id,
                    "version": version,
                    "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        concepts = "; ".join(str(value) for value in issue["required_concepts"])
        messages.append(
            {
                "id": f"mail-{issue_id}",
                "from": "review.partner@synthetic.example",
                "to": "associate@synthetic.example",
                "subject": f"Review point {index}",
                "body": (
                    f"Issue {issue_id} | anchor {anchor} | severity {issue['severity']} | "
                    f"concepts {concepts}"
                ),
            }
        )
    (bundle_dir / "correspondence.json").write_text(
        json.dumps(messages, indent=2), encoding="utf-8"
    )
    manifest = {
        "source_matter": source_matter.name,
        "synthetic": True,
        "artifacts": artifacts,
        "correspondence": "correspondence.json",
    }
    manifest_path = bundle_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return manifest_path


def recover_bundle(manifest_path: Path) -> list[RecoveredIssue]:
    """Run the scoped Stage 2--5 adapters over only the generated bundle format."""
    root = manifest_path.parent
    manifest = _yaml(manifest_path)
    grouped: dict[str, list[dict]] = {}
    for artifact in manifest["artifacts"]:
        path = root / artifact["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError(f"intake hash mismatch: {path.name}")
        grouped.setdefault(str(artifact["logical_document"]), []).append(artifact)
    # Stage 2: explicit synthetic DMS version numbers are authoritative.
    chains = {key: sorted(value, key=lambda item: int(item["version"])) for key, value in grouped.items()}

    # Stage 3: mine actual OOXML revisions rather than reading expected values.
    redlines: dict[str, tuple[str, ...]] = {}
    evidence: dict[str, list[str]] = {}
    for issue_id, chain in chains.items():
        latest = root / chain[-1]["path"]
        edits = merge_substitutions(extract_edits(latest))
        inserted = " ".join(edit.inserted_text for edit in edits if edit.inserted_text)
        redlines[issue_id] = tuple(part.strip() for part in inserted.split(";") if part.strip())
        evidence[issue_id] = [str(item["artifact_id"]) for item in chain]

    # Stage 4: correspondence carries the human judgment that a redline cannot.
    mail_fields: dict[str, dict[str, object]] = {}
    for message in json.loads((root / manifest["correspondence"]).read_text(encoding="utf-8")):
        match = _EVIDENCE_RE.fullmatch(message["body"])
        if not match:
            continue
        fields = match.groupdict()
        issue_id = fields["id"]
        mail_fields[issue_id] = {
            "anchor": fields["anchor"].strip(),
            "severity": fields["severity"],
            "required_concepts": tuple(
                part.strip() for part in fields["concepts"].split(";") if part.strip()
            ),
        }
        evidence.setdefault(issue_id, []).append(message["id"])

    # Stage 5: deterministic proposal for this labelled synthetic format.
    return [
        RecoveredIssue(
            issue_id=issue_id,
            anchor=str(fields["anchor"]),
            severity=str(fields["severity"]),
            required_concepts=tuple(fields["required_concepts"]),
            redline_concepts=redlines.get(issue_id, ()),
            evidence_ids=tuple(evidence.get(issue_id, ())),
        )
        for issue_id, fields in sorted(mail_fields.items())
    ]


def score_recovery(recovered: list[RecoveredIssue], rubric: dict) -> dict[str, object]:
    """Compare mined proposals with the hand-authored known answer."""
    expected = {str(item["id"]): item for item in rubric["issues"]}
    found = {item.issue_id: item for item in recovered}
    issue_hits = set(expected) & set(found)
    severity_hits = sum(found[key].severity == expected[key]["severity"] for key in issue_hits)
    required_expected = sum(len(item.get("required_concepts", [])) for item in expected.values())
    redline_expected = sum(len(item.get("redline_concepts", [])) for item in expected.values())
    required_hits = sum(
        len(set(found[key].required_concepts) & set(expected[key].get("required_concepts", [])))
        for key in issue_hits
    )
    redline_hits = sum(
        len(set(found[key].redline_concepts) & set(expected[key].get("redline_concepts", [])))
        for key in issue_hits
    )
    return {
        "issues": {"recovered": len(issue_hits), "expected": len(expected)},
        "severities": {"matched": severity_hits, "expected": len(expected)},
        "required_concepts": {"matched": required_hits, "expected": required_expected},
        "redline_concepts": {"matched": redline_hits, "expected": redline_expected},
        "concepts": {
            "matched": required_hits + redline_hits,
            "expected": required_expected + redline_expected,
        },
    }


def emit_synthetic_matter(source_matter: Path, out_dir: Path) -> Path:
    """Stage 6--7 adapter: identity-resynthesize and emit an already-fabricated matter."""
    matter = _yaml(source_matter / "matter.yaml")
    if matter.get("provenance", {}).get("synthetic") is not True:
        raise ValueError("Phase A identity adapter accepts synthetic source matters only")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(source_matter, out_dir)
    return out_dir


def validate_synthetic_package(matter_dir: Path, actions_path: Path) -> dict[str, object]:
    """Stage 8: real linter plus real environment replay."""
    report = lint_matter(matter_dir)
    if not report.ok:
        raise ValueError("lint failed: " + "; ".join(report.errors))
    env = PlaybookEnv.from_directory(matter_dir)
    env.reset(seed=0)
    for line in actions_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            env.step(json.loads(line))
    result = env.episode_result()
    return {
        "lint_errors": len(report.errors),
        "normalized_score": result["normalized_score"],
        "critical_failure": result["critical_failure"],
    }


def run_selftest(repo_root: Path, work_dir: Path) -> dict[str, object]:
    source = repo_root / "matters" / "ai_saas_001"
    manifest = generate_evidence_bundle(source, work_dir / "evidence")
    recovered = recover_bundle(manifest)
    recovery = score_recovery(recovered, _yaml(source / "rubric.yaml"))
    emitted = emit_synthetic_matter(source, work_dir / "emitted" / "ai_saas_001")
    validation = validate_synthetic_package(
        emitted, repo_root / "examples" / "ai_saas_001" / "good.jsonl"
    )
    return {
        "matter_id": "ai_saas_001",
        "stages_exercised": list(range(2, 9)),
        "recovery": recovery,
        "validation": validation,
        "recovered_issues": [asdict(item) for item in recovered],
    }


def _write_docx(
    path: Path, anchor: str, original: str, *, inserted: str = "", revision_id: int = 1
) -> None:
    document = [
        f'<w:p><w:r><w:t>{escape(anchor)}</w:t></w:r></w:p>',
        f'<w:p><w:r><w:t>{escape(original)}</w:t></w:r>',
    ]
    if inserted:
        document.append(
            f'<w:ins w:id="{revision_id}" w:author="Synthetic Partner" '
            'w:date="2026-01-15T12:00:00Z"><w:r><w:t xml:space="preserve">'
            f" {escape(inserted)}</w:t></w:r></w:ins>"
        )
    document.append("</w:p>")
    xml = f'<w:document xmlns:w="{W}"><w:body>{"".join(document)}</w:body></w:document>'
    rels = (
        f'<Relationships xmlns="{RELS}"><Relationship Id="rId1" '
        f'Type="{OFFICE_DOC}" Target="word/document.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", xml)


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the compiler Phase A known-answer test")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_selftest(args.repo_root.resolve(), args.work_dir.resolve())
    print(json.dumps(result, indent=2) if args.json else yaml.safe_dump(result, sort_keys=False))


if __name__ == "__main__":
    main()
