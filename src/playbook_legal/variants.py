# SPDX-License-Identifier: AGPL-3.0-only

"""Materialize deterministic, validated synthetic matter-family variants."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .dataset import load_family_registry
from .env import PlaybookEnv
from .lint import lint_matter

SCHEMA_VERSION = "playbook.variants.v1"
CATALOG_SCHEMA_VERSION = "playbook.variant_catalog.v1"
GENERATOR_VERSION = "1"
_BUDGETS = {
    "maximum_steps",
    "maximum_client_questions",
    "maximum_escalations",
    "maximum_negotiation_rounds",
}
_MEANINGFUL_TRANSFORMS = {
    "set_budget",
    "set_hidden_answer",
    "set_public_fact",
    "set_role",
    "reorder_documents",
    "set_issue_state",
    "set_authority_bundle",
}
_AUTHORITY_RUBRIC_FIELDS = {
    "non_negotiable",
    "settlement_concepts",
    "settlement_critical_failure_patterns",
    "required_concepts",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    text = yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(text, encoding="utf-8", newline="\n")


def _tree_files(root: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rows.append({"path": path.relative_to(root).as_posix(), "sha256": _sha256(path.read_bytes())})
    return rows


def _tree_hash(files: list[dict[str, str]]) -> str:
    return _sha256(_canonical(files).encode("utf-8"))


def _load_spec(path: Path) -> dict[str, Any]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path}: expected schema_version {SCHEMA_VERSION}")
    if spec.get("generator_version") != GENERATOR_VERSION:
        raise ValueError(f"{path}: expected generator_version {GENERATOR_VERSION}")
    if not isinstance(spec.get("family_id"), str) or not spec["family_id"]:
        raise ValueError(f"{path}: family_id is required")
    if not isinstance(spec.get("split"), str) or not spec["split"]:
        raise ValueError(f"{path}: split is required")
    if not isinstance(spec.get("base_matter_id"), str) or not spec["base_matter_id"]:
        raise ValueError(f"{path}: base_matter_id is required")
    variants = spec.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError(f"{path}: variants must be a non-empty list")
    ids = [item.get("variant_id") for item in variants if isinstance(item, dict)]
    if len(ids) != len(variants) or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError(f"{path}: every variant needs a variant_id")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate variant_id")
    return spec


def _replace_section(matter_dir: Path, matter: dict[str, Any], change: dict[str, Any]) -> None:
    document_id = str(change.get("document_id", ""))
    section = str(change.get("section", ""))
    content = change.get("content")
    manifest = {str(item.get("id")): item for item in matter.get("documents", [])}
    if document_id not in manifest or not section or not isinstance(content, str):
        raise ValueError("compliant_section requires a known document_id, section, and content")
    path = matter_dir / str(manifest[document_id]["path"])
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(?ms)^(##[ \t]+{re.escape(section)}(?:[ \t]+[^\r\n]*)?\r?\n).*?(?=^##[ \t]+|\Z)"
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"section {document_id} {section} did not resolve exactly once")
    body = content.strip() + "\n\n"
    updated = text[: matches[0].start()] + matches[0].group(1) + "\n" + body + text[matches[0].end() :]
    path.write_text(updated.rstrip() + "\n", encoding="utf-8", newline="\n")


def _apply_transforms(
    matter_dir: Path,
    matter: dict[str, Any],
    hidden: dict[str, Any],
    rubric: dict[str, Any],
    counterparty: dict[str, Any],
    transforms: list[dict[str, Any]],
) -> list[str]:
    touched: set[tuple[str, ...]] = set()
    dimensions: set[str] = set()
    documents = matter.get("documents", [])
    document_ids = [str(item.get("id")) for item in documents]

    for transform in transforms:
        if not isinstance(transform, dict):
            raise TypeError("each transform must be a mapping")
        kind = transform.get("type")
        if kind not in _MEANINGFUL_TRANSFORMS:
            raise ValueError(f"unsupported transform type: {kind!r}")
        if kind == "set_budget":
            name = str(transform.get("name", ""))
            value = transform.get("value")
            if name not in _BUDGETS or not isinstance(value, int) or value < 1:
                raise ValueError(f"invalid budget transform: {name!r}={value!r}")
            target = ("matter", "constraints", name)
            matter.setdefault("constraints", {})[name] = value
            dimensions.add("budgets")
        elif kind == "set_hidden_answer":
            question_id = str(transform.get("question_id", ""))
            answers = hidden.get("client_answers", {})
            if question_id not in answers or not isinstance(transform.get("value"), str):
                raise ValueError(f"unknown or invalid hidden answer: {question_id!r}")
            target = ("hidden_facts", "client_answers", question_id)
            answers[question_id] = transform["value"]
            dimensions.add("hidden_facts")
        elif kind == "set_public_fact":
            key = str(transform.get("key", ""))
            if not key or "value" not in transform:
                raise ValueError("set_public_fact requires key and value")
            target = ("matter", "public_facts", key)
            matter.setdefault("public_facts", {})[key] = transform["value"]
            dimensions.add("leverage_and_facts")
        elif kind == "set_role":
            value = transform.get("value")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("set_role requires a non-empty value")
            target = ("matter", "role")
            matter["role"] = value
            dimensions.add("role")
        elif kind == "reorder_documents":
            order = transform.get("document_ids")
            if not isinstance(order, list) or len(order) != len(document_ids):
                raise ValueError("reorder_documents must list every document exactly once")
            if {str(item) for item in order} != set(document_ids) or len(set(order)) != len(order):
                raise ValueError("reorder_documents contains missing or duplicate ids")
            target = ("matter", "documents")
            by_id = {str(item["id"]): item for item in documents}
            matter["documents"] = [by_id[str(item)] for item in order]
            dimensions.add("document_order")
        elif kind == "set_issue_state":
            issue_id = str(transform.get("issue_id", ""))
            if transform.get("state") != "absent":
                raise ValueError("set_issue_state currently supports only state: absent")
            issues = rubric.get("issues", [])
            matches = [issue for issue in issues if str(issue.get("id")) == issue_id]
            if len(matches) != 1:
                raise ValueError(f"issue {issue_id!r} did not resolve exactly once")
            section_change = transform.get("compliant_section")
            if not isinstance(section_change, dict):
                raise ValueError("absent issue requires a compliant_section")
            target = ("rubric", "issues", issue_id)
            _replace_section(matter_dir, matter, section_change)
            rubric["issues"] = [issue for issue in issues if str(issue.get("id")) != issue_id]
            final = rubric.setdefault("final_submission", {})
            final["required_issue_ids"] = [
                item for item in final.get("required_issue_ids", []) if str(item) != issue_id
            ]
            positions = counterparty.get("positions", {}) or {}
            positions.pop(issue_id, None)
            if "positions" in counterparty:
                counterparty["positions"] = positions
            dimensions.add("clean_vs_issue_bearing")
        else:
            issue_id = str(transform.get("issue_id", ""))
            issues = [issue for issue in rubric.get("issues", []) if str(issue.get("id")) == issue_id]
            if len(issues) != 1:
                raise ValueError(f"authority issue {issue_id!r} did not resolve exactly once")
            fields = transform.get("rubric_fields")
            if not isinstance(fields, dict) or not fields or not set(fields) <= _AUTHORITY_RUBRIC_FIELDS:
                raise ValueError("authority bundle has unsupported or missing rubric_fields")
            playbook_section = transform.get("playbook_section")
            if not isinstance(playbook_section, dict):
                raise ValueError("authority bundle requires playbook_section")
            escalation_id = str(transform.get("remove_escalation_id", ""))
            escalations = rubric.get("escalations", [])
            escalation_matches = [
                item for item in escalations if str(item.get("id")) == escalation_id
            ]
            if len(escalation_matches) != 1:
                raise ValueError(f"escalation {escalation_id!r} did not resolve exactly once")
            answer = transform.get("hidden_answer")
            question_id = str(answer.get("question_id", "")) if isinstance(answer, dict) else ""
            answers = hidden.get("client_answers", {})
            if question_id not in answers or not isinstance(answer.get("value"), str):
                raise ValueError("authority bundle requires a valid hidden client answer")
            position = transform.get("counterparty_position")
            if not isinstance(position, dict):
                raise ValueError("authority bundle requires a counterparty_position")
            target = ("authority", issue_id)
            _replace_section(matter_dir, matter, playbook_section)
            issues[0].update(fields)
            rubric["escalations"] = [
                item for item in escalations if str(item.get("id")) != escalation_id
            ]
            hidden.get("escalation_answers", {}).pop(escalation_id, None)
            answers[question_id] = answer["value"]
            counterparty.setdefault("positions", {})[issue_id] = position
            dimensions.add("authority_and_fallback")
            dimensions.add("counterparty_behavior")
        if target in touched:
            raise ValueError(f"multiple transforms target {'/'.join(target)}")
        touched.add(target)
    if not dimensions:
        raise ValueError("variant has no legally meaningful transforms")
    return sorted(dimensions)


def _replay(matter_dir: Path, actions_path: Path, seed: int) -> dict[str, Any]:
    env = PlaybookEnv.from_directory(matter_dir)
    env.reset(seed=seed)
    for line in actions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, _, terminated, truncated, _ = env.step(json.loads(line))
        if terminated or truncated:
            break
    return env.episode_result()


def _materialize_one(
    variant: dict[str, Any],
    *,
    spec: dict[str, Any],
    matters_root: Path,
    examples_root: Path,
    staging: Path,
) -> dict[str, Any]:
    base_id = spec["base_matter_id"]
    variant_id = variant["variant_id"]
    source_matter = matters_root / base_id
    source_examples = examples_root / base_id
    matter_out = staging / "matters" / variant_id
    example_out = staging / "examples" / variant_id
    if not source_matter.is_dir() or not (source_examples / "good.jsonl").is_file():
        raise ValueError(f"base package or reference trajectory is missing for {base_id!r}")
    shutil.copytree(source_matter, matter_out)
    example_out.mkdir(parents=True)
    reference_source = source_examples / "good.jsonl"
    if variant.get("reference_actions"):
        candidate = Path(str(variant["reference_actions"]))
        reference_source = candidate if candidate.is_absolute() else Path(spec["_spec_dir"]) / candidate
    if not reference_source.is_file():
        raise ValueError(f"reference trajectory does not exist: {reference_source}")
    shutil.copy2(reference_source, example_out / "good.jsonl")
    if variant.get("reference_edits"):
        actions = [
            json.loads(line)
            for line in (example_out / "good.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        edits = variant["reference_edits"]
        if edits.get("drop_action_types"):
            dropped = {str(item) for item in edits["drop_action_types"]}
            actions = [action for action in actions if str(action.get("type")) not in dropped]
        inserts = edits.get("insert_after", [])
        for insertion in inserts:
            match = insertion.get("match", {})
            indexes = [
                index
                for index, action in enumerate(actions)
                if all(action.get(key) == value for key, value in match.items())
            ]
            if len(indexes) != 1 or not isinstance(insertion.get("action"), dict):
                raise ValueError("reference insertion target must resolve exactly once")
            actions.insert(indexes[0] + 1, insertion["action"])
        if "final_summary" in edits:
            finals = [action for action in actions if action.get("type") == "submit_final"]
            if len(finals) != 1 or not isinstance(edits["final_summary"], str):
                raise ValueError("reference final_summary requires exactly one submit_final")
            finals[0]["summary"] = edits["final_summary"]
        (example_out / "good.jsonl").write_text(
            "".join(_canonical(action) + "\n" for action in actions),
            encoding="utf-8",
            newline="\n",
        )

    matter_path = matter_out / "matter.yaml"
    hidden_path = matter_out / "hidden_facts.yaml"
    matter = yaml.safe_load(matter_path.read_text(encoding="utf-8"))
    hidden = yaml.safe_load(hidden_path.read_text(encoding="utf-8"))
    rubric_path = matter_out / "rubric.yaml"
    counterparty_path = matter_out / "counterparty.yaml"
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    counterparty = (
        yaml.safe_load(counterparty_path.read_text(encoding="utf-8"))
        if counterparty_path.exists()
        else {}
    )
    dimensions = _apply_transforms(
        matter_out, matter, hidden, rubric, counterparty, variant.get("transforms", [])
    )
    matter["matter_id"] = variant_id
    matter["title"] = str(variant.get("title") or matter["title"])
    provenance = matter.setdefault("provenance", {})
    provenance["variant_family_id"] = spec["family_id"]
    provenance["base_matter_id"] = base_id
    provenance["generator_version"] = GENERATOR_VERSION
    _write_yaml(matter_path, matter)
    _write_yaml(hidden_path, hidden)
    _write_yaml(rubric_path, rubric)
    if counterparty_path.exists() or counterparty:
        _write_yaml(counterparty_path, counterparty)

    lint = lint_matter(matter_out)
    if not lint.ok:
        raise ValueError(f"{variant_id}: lint failed: {'; '.join(lint.errors)}")
    if "seed" in variant:
        raise ValueError("use replay_seed; generation is authored and has no random seed")
    seed = int(variant.get("replay_seed", 0))
    result = _replay(matter_out, example_out / "good.jsonl", seed)
    minimum_score = float(spec.get("minimum_reference_score", 0.7))
    if (
        not result["terminated"]
        or result["truncated"]
        or result["critical_failure"]
        or float(result["normalized_score"]) < minimum_score
    ):
        raise ValueError(f"{variant_id}: reference replay failed validation: {result}")
    adversarial_results = []
    for index, adversarial in enumerate(variant.get("adversarial_trajectories", [])):
        source = Path(str(adversarial.get("path", "")))
        source = source if source.is_absolute() else Path(spec["_spec_dir"]) / source
        if not source.is_file():
            raise ValueError(f"{variant_id}: adversarial trajectory does not exist: {source}")
        destination = example_out / f"adversarial_{index + 1}.jsonl"
        shutil.copy2(source, destination)
        bad_result = _replay(matter_out, destination, seed)
        expected_event = adversarial.get("expected_event_type")
        event_types = {
            str(event.get("type"))
            for event in bad_result.get("breakdown", {}).get("reward_events", [])
        }
        if expected_event and expected_event not in event_types:
            raise ValueError(f"{variant_id}: adversarial gate {expected_event!r} did not fire")
        if "critical_failure" in adversarial and bool(bad_result["critical_failure"]) != bool(
            adversarial["critical_failure"]
        ):
            raise ValueError(f"{variant_id}: adversarial critical-failure expectation missed")
        if "maximum_score" in adversarial and float(bad_result["normalized_score"]) > float(
            adversarial["maximum_score"]
        ):
            raise ValueError(f"{variant_id}: adversarial score exceeded maximum")
        adversarial_results.append(
            {
                "path": destination.name,
                "expected_event_type": expected_event,
                "critical_failure": bad_result["critical_failure"],
                "score": bad_result["normalized_score"],
            }
        )
    files = [
        {"path": f"matters/{variant_id}/{item['path']}", "sha256": item["sha256"]}
        for item in _tree_files(matter_out)
    ] + [
        {"path": f"examples/{variant_id}/{item['path']}", "sha256": item["sha256"]}
        for item in _tree_files(example_out)
    ]
    return {
        "variant_id": variant_id,
        "replay_seed": seed,
        "dimensions": dimensions,
        "content_hash": _tree_hash(files),
        "files": files,
        "validation": {
            "lint_errors": 0,
            "reference_score": result["normalized_score"],
            "terminated": result["terminated"],
            "truncated": result["truncated"],
            "critical_failure": result["critical_failure"],
            "adversarial": adversarial_results,
        },
    }


def generate_family(
    spec_path: Path, matters_root: Path, examples_root: Path, output_root: Path
) -> dict[str, Any]:
    """Generate a complete family atomically; refuse to overwrite an existing output."""
    spec = _load_spec(spec_path)
    spec["_spec_dir"] = spec_path.parent.resolve().as_posix()
    if output_root.exists():
        raise FileExistsError(f"output already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        base_files = [
            {"path": f"matters/{spec['base_matter_id']}/{item['path']}", "sha256": item["sha256"]}
            for item in _tree_files(matters_root / spec["base_matter_id"])
        ]
        base_reference = examples_root / spec["base_matter_id"] / "good.jsonl"
        base_files.append(
            {
                "path": f"examples/{spec['base_matter_id']}/good.jsonl",
                "sha256": _sha256(base_reference.read_bytes()),
            }
        )
        template_sha256 = _tree_hash(base_files)
        variants = [
            _materialize_one(
                variant,
                spec=spec,
                matters_root=matters_root,
                examples_root=examples_root,
                staging=temporary,
            )
            for variant in sorted(spec["variants"], key=lambda item: item["variant_id"])
        ]
        required_dimensions = spec.get("required_dimensions", [])
        if not isinstance(required_dimensions, list) or any(
            not isinstance(item, str) or not item for item in required_dimensions
        ):
            raise ValueError("required_dimensions must be a list of names")
        covered_dimensions = sorted(
            {dimension for variant in variants for dimension in variant["dimensions"]}
        )
        missing_dimensions = sorted(set(required_dimensions) - set(covered_dimensions))
        if missing_dimensions:
            raise ValueError(
                "family does not cover required semantic dimensions: "
                + ", ".join(missing_dimensions)
            )
        split = spec["split"]
        if split in {"held-out", "evaluation", "eval", "test"}:
            registry_family = {
                "split": split,
                "template_sha256": template_sha256,
                "sealed_matter_hashes": {
                    item["variant_id"]: item["content_hash"] for item in variants
                },
            }
        else:
            registry_family = {
                "split": split,
                "template_sha256": template_sha256,
                "matters": [item["variant_id"] for item in variants],
            }
        output_files = sorted(
            (file for variant in variants for file in variant["files"]),
            key=lambda item: item["path"],
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "family_id": spec["family_id"],
            "split": split,
            "base_matter_id": spec["base_matter_id"],
            "base_files": base_files,
            "template_sha256": template_sha256,
            "spec_sha256": _sha256(spec_path.read_bytes()),
            "output_tree_sha256": _tree_hash(output_files),
            "dimension_coverage": {
                "required": sorted(required_dimensions),
                "covered": covered_dimensions,
            },
            "variants": variants,
            "registry_fragment": {
                "version": 1,
                "families": {spec["family_id"]: registry_family},
            },
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, output_root)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def build_catalog(
    catalog_path: Path,
    matters_root: Path,
    examples_root: Path,
    output_root: Path,
    *,
    require_targets: bool = False,
) -> dict[str, Any]:
    """Atomically generate every family in a catalog and merge its safe registry."""
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    if catalog.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise ValueError(f"{catalog_path}: expected schema_version {CATALOG_SCHEMA_VERSION}")
    if catalog.get("generator_version") != GENERATOR_VERSION:
        raise ValueError(f"{catalog_path}: expected generator_version {GENERATOR_VERSION}")
    entries = catalog.get("families")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{catalog_path}: families must be a non-empty list")
    targets = catalog.get("targets", {})
    target_fields = {"training_families", "training_variants", "evaluation_families"}
    if not isinstance(targets, dict) or set(targets) != target_fields:
        raise ValueError(f"{catalog_path}: targets must contain exactly {sorted(target_fields)}")
    for field in target_fields:
        if not isinstance(targets.get(field), int) or targets[field] < 0:
            raise ValueError(f"{catalog_path}: target {field} must be a nonnegative integer")
    if output_root.exists():
        raise FileExistsError(f"catalog output already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        family_manifests: list[dict[str, Any]] = []
        merged_families: dict[str, Any] = {}
        if any(not isinstance(entry, dict) or not isinstance(entry.get("spec"), str) for entry in entries):
            raise TypeError("every catalog family requires a spec path")
        for entry in sorted(entries, key=lambda item: item["spec"]):
            candidate = Path(entry["spec"])
            spec_path = candidate if candidate.is_absolute() else catalog_path.parent / candidate
            spec = _load_spec(spec_path)
            family_id = spec["family_id"]
            if family_id in merged_families:
                raise ValueError(f"duplicate catalog family_id: {family_id}")
            family_output = temporary / "families" / family_id
            manifest = generate_family(spec_path, matters_root, examples_root, family_output)
            family_manifests.append(
                {
                    "family_id": family_id,
                    "split": manifest["split"],
                    "variants": len(manifest["variants"]),
                    "template_sha256": manifest["template_sha256"],
                    "manifest_sha256": _sha256(
                        (family_output / "manifest.json").read_bytes()
                    ),
                    "dimensions": manifest["dimension_coverage"]["covered"],
                }
            )
            merged_families.update(manifest["registry_fragment"]["families"])

        registry = {"version": 1, "families": merged_families}
        registry_path = temporary / "family_registry.yaml"
        _write_yaml(registry_path, registry)
        load_family_registry(registry_path)
        training = [item for item in family_manifests if item["split"] == "train"]
        evaluation = [
            item
            for item in family_manifests
            if item["split"] in {"held-out", "evaluation", "eval", "test"}
        ]
        actual = {
            "training_families": len(training),
            "training_variants": sum(item["variants"] for item in training),
            "evaluation_families": len(evaluation),
        }
        target_status = {
            field: {"target": targets[field], "actual": actual[field], "met": actual[field] >= targets[field]}
            for field in targets
        }
        ready = all(item["met"] for item in target_status.values())
        if require_targets and not ready:
            missing = ", ".join(field for field, item in target_status.items() if not item["met"])
            raise ValueError(f"catalog does not meet required targets: {missing}")
        files = _tree_files(temporary)
        manifest = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "catalog_sha256": _sha256(catalog_path.read_bytes()),
            "families": family_manifests,
            "targets": target_status,
            "ready": ready,
            "files": files,
            "tree_sha256": _tree_hash(files),
        }
        (temporary / "catalog_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, output_root)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--examples", type=Path, default=Path("examples"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate_family(args.spec, args.matters, args.examples, args.out)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def catalog_main() -> None:
    parser = argparse.ArgumentParser(description="Build a Playbook synthetic-family catalog.")
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--examples", type=Path, default=Path("examples"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--require-targets", action="store_true")
    args = parser.parse_args()
    manifest = build_catalog(
        args.catalog,
        args.matters,
        args.examples,
        args.out,
        require_targets=args.require_targets,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
