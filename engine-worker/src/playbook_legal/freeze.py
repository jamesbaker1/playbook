# SPDX-License-Identifier: AGPL-3.0-only

"""Freeze a reviewed Playbook dataset build into a content-addressed release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .dataset import verify_dataset
from .preferences import SCHEMA_VERSION as PREFERENCE_SCHEMA_VERSION
from .preferences import verify_decision_pairs

SCHEMA_VERSION = "playbook.freeze.v1"
_HELD_OUT_SPLITS = {"held-out", "evaluation", "eval", "test"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tree_files(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, str]]:
    excluded = exclude or set()
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path.read_bytes())}
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.relative_to(root).as_posix() not in excluded
    ]


def _tree_hash(files: list[dict[str, str]]) -> str:
    return _sha256(_canonical(files).encode("utf-8"))


def _load_card(path: Path) -> dict[str, Any]:
    card = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if card.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path}: expected schema_version {SCHEMA_VERSION}")
    if not isinstance(card.get("release_id"), str) or not card["release_id"].strip():
        raise ValueError(f"{path}: release_id is required")
    if card.get("intended_use") not in {"positive_sft", "preference", "evaluation"}:
        raise ValueError(f"{path}: unsupported intended_use")
    for field in ("inclusion_criteria", "exclusion_criteria", "known_limitations"):
        if not isinstance(card.get(field), list) or not card[field]:
            raise ValueError(f"{path}: {field} must be a non-empty list")
    review = card.get("review", {})
    if review.get("status") != "approved":
        raise ValueError(f"{path}: review status must be approved")
    reviewers = review.get("reviewers")
    if not isinstance(reviewers, list) or not reviewers:
        raise ValueError(f"{path}: at least one reviewer is required")
    for reviewer in reviewers:
        if not isinstance(reviewer, dict) or not reviewer.get("id") or not reviewer.get(
            "qualification"
        ):
            raise ValueError(f"{path}: every reviewer needs id and qualification")
    coverage_field = "reviewed_pairs" if card["intended_use"] == "preference" else "reviewed_episodes"
    if not isinstance(review.get(coverage_field), int) or review[coverage_field] < 1:
        raise ValueError(f"{path}: {coverage_field} must be positive")
    approval = card.get("approval", {})
    if not approval.get("approved_by") or not approval.get("approved_on"):
        raise ValueError(f"{path}: approval requires approved_by and approved_on")
    expected = card.get("dataset_manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"{path}: dataset_manifest_sha256 must be SHA-256")
    return card


def _validate_freeze(build_dir: Path, card: dict[str, Any]) -> dict[str, Any]:
    manifest_path = build_dir / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    if _sha256(manifest_bytes) != card["dataset_manifest_sha256"]:
        raise ValueError("data card does not match the dataset manifest hash")
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") == PREFERENCE_SCHEMA_VERSION:
        if card["intended_use"] != "preference":
            raise ValueError("decision-pair builds require intended_use: preference")
        verification = verify_decision_pairs(build_dir)
        expected_records = manifest.get("output", {}).get("pairs")
        coverage_field = "reviewed_pairs"
        qualified = {str(item["id"]) for item in card["review"]["reviewers"]}
        if not set(verification["reviewers"]) <= qualified:
            raise ValueError("preference reviewer is absent from the qualified reviewer list")
        if card["review"][coverage_field] != expected_records:
            raise ValueError("review coverage does not account for every pair")
        contaminated = set(manifest.get("statistics", {}).get("splits", {})) & _HELD_OUT_SPLITS
        if contaminated:
            raise ValueError("preference release contains held-out data")
        return verification
    verification = verify_dataset(build_dir)
    statistics = manifest.get("statistics", {})
    if card["review"]["reviewed_episodes"] != statistics.get("episodes"):
        raise ValueError("review coverage does not account for every episode")
    provenance = manifest.get("provenance", {})
    if provenance.get("review_status") not in {"reviewed", "approved"}:
        raise ValueError("dataset records are not marked reviewed")
    reviewer_ids = {str(item["id"]) for item in card["review"]["reviewers"]}
    if str(provenance.get("reviewer")) not in reviewer_ids:
        raise ValueError("dataset reviewer is absent from the qualified reviewer list")

    if card["intended_use"] == "positive_sft":
        if provenance.get("trace_verification") != "replay_verified":
            raise ValueError("positive SFT release is not replay verified")
        contaminated = set(statistics.get("splits", {})) & _HELD_OUT_SPLITS
        if contaminated:
            raise ValueError("positive SFT release contains held-out data")
        if int(statistics.get("critical_failure_episodes", 0)):
            raise ValueError("positive SFT release contains critical-failure episodes")
    return verification


def freeze_dataset(build_dir: Path, card_path: Path, output_dir: Path) -> dict[str, Any]:
    """Validate and atomically copy a build and data card into a frozen release."""
    card = _load_card(card_path)
    verification = _validate_freeze(build_dir, card)
    if output_dir.exists():
        raise FileExistsError(f"frozen release already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        shutil.copytree(build_dir, temporary / "dataset")
        card_bytes = card_path.read_bytes()
        (temporary / "data_card.yaml").write_bytes(card_bytes)
        files = _tree_files(temporary)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "release_id": card["release_id"],
            "intended_use": card["intended_use"],
            "dataset_manifest_sha256": card["dataset_manifest_sha256"],
            "data_card_sha256": _sha256(card_bytes),
            "files": files,
            "tree_sha256": _tree_hash(files),
            "verification": verification,
        }
        (temporary / "freeze_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_frozen_release(release_dir: Path) -> dict[str, Any]:
    manifest = json.loads((release_dir / "freeze_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported freeze manifest schema")
    files = _tree_files(release_dir, exclude={"freeze_manifest.json"})
    if files != manifest.get("files") or _tree_hash(files) != manifest.get("tree_sha256"):
        raise ValueError("frozen release tree hash mismatch")
    card_path = release_dir / "data_card.yaml"
    if _sha256(card_path.read_bytes()) != manifest.get("data_card_sha256"):
        raise ValueError("frozen data card hash mismatch")
    card = _load_card(card_path)
    verification = _validate_freeze(release_dir / "dataset", card)
    return {
        "valid": True,
        "release_id": manifest["release_id"],
        "tree_sha256": manifest["tree_sha256"],
        "dataset": verification,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("data_card", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze_dataset(args.build, args.data_card, args.out), indent=2, sort_keys=True))


def verify_main() -> None:
    parser = argparse.ArgumentParser(description="Verify a frozen Playbook dataset release.")
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_frozen_release(args.release), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
