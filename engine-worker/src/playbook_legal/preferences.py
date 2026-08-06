# SPDX-License-Identifier: AGPL-3.0-only

"""Build reviewed decision-level DPO pairs from competing actions at the same state."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .dataset import load_family_registry
from .export import SYSTEM_PROMPT

SCHEMA_VERSION = "playbook.decision_preferences.v1"
CANDIDATE_SCHEMA_VERSION = "playbook.decision_candidate.v1"
CATEGORIES = {
    "client_question",
    "evidence_grounding",
    "required_escalation",
    "over_escalation",
    "authorized_fallback",
    "trap_counter",
    "restraint",
}
_HELD_OUT_SPLITS = {"held-out", "evaluation", "eval", "test"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_hash(record: dict[str, Any]) -> str:
    return _sha256(
        _canonical({key: value for key, value in record.items() if key != "content_hash"}).encode(
            "utf-8"
        )
    )


def _validate_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise ValueError("candidate has an unsupported schema_version")
    for field in ("pair_id", "candidate_id", "matter_id", "preference_source", "reviewer"):
        if not isinstance(candidate.get(field), str) or not candidate[field]:
            raise ValueError(f"candidate requires {field}")
    if candidate.get("review_status") != "approved":
        raise ValueError("candidate review_status must be approved")
    if candidate.get("category") not in CATEGORIES:
        raise ValueError(f"unsupported preference category: {candidate.get('category')!r}")
    if not isinstance(candidate.get("state"), dict) or not isinstance(candidate.get("action"), dict):
        raise TypeError("candidate state and action must be mappings")
    action_type = candidate["action"].get("type")
    schemas = candidate["state"].get("action_schemas", {})
    if action_type not in schemas:
        raise ValueError(f"candidate action {action_type!r} is unavailable in its state")
    if not isinstance(candidate.get("outcome"), dict):
        raise TypeError("candidate outcome must be a mapping")
    if not isinstance(candidate.get("preference_rank"), int):
        raise TypeError("candidate preference_rank must be an integer")
    reason = candidate.get("structured_reason")
    if not isinstance(reason, dict) or not reason.get("summary") or not reason.get("principle"):
        raise ValueError("candidate structured_reason requires summary and principle")


def build_decision_pairs(
    candidates_path: Path,
    registry_path: Path,
    output_dir: Path,
    *,
    allow_held_out: bool = False,
) -> dict[str, Any]:
    """Build deterministic same-state pairs and a hashed manifest."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty preference release: {output_dir}")
    candidates_bytes = candidates_path.read_bytes()
    candidates = [
        json.loads(line) for line in candidates_bytes.decode("utf-8").splitlines() if line.strip()
    ]
    if not candidates:
        raise ValueError("candidate file is empty")
    registry = load_family_registry(registry_path)
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidate_ids: set[str] = set()
    for candidate in candidates:
        _validate_candidate(candidate)
        if candidate["candidate_id"] in candidate_ids:
            raise ValueError(f"duplicate candidate_id: {candidate['candidate_id']}")
        candidate_ids.add(candidate["candidate_id"])
        matter_id = candidate["matter_id"]
        if matter_id not in registry:
            raise ValueError(f"candidate matter {matter_id!r} is absent from the family registry")
        entry = registry[matter_id]
        if entry["split"] in _HELD_OUT_SPLITS and not allow_held_out:
            raise ValueError(f"refusing held-out preference family {entry['matter_family_id']!r}")
        by_pair[candidate["pair_id"]].append(candidate)

    records: list[dict[str, Any]] = []
    for pair_id, pair in sorted(by_pair.items()):
        if len(pair) != 2:
            raise ValueError(f"pair {pair_id!r} must contain exactly two candidates")
        left, right = pair
        if left["matter_id"] != right["matter_id"]:
            raise ValueError(f"pair {pair_id!r} crosses matters")
        if _canonical(left["state"]) != _canonical(right["state"]):
            raise ValueError(f"pair {pair_id!r} candidates do not share the same state")
        if left["category"] != right["category"]:
            raise ValueError(f"pair {pair_id!r} crosses preference categories")
        if left["preference_source"] != right["preference_source"]:
            raise ValueError(f"pair {pair_id!r} crosses preference sources")
        if left["reviewer"] != right["reviewer"]:
            raise ValueError(f"pair {pair_id!r} crosses reviewers")
        if left["preference_rank"] == right["preference_rank"]:
            raise ValueError(f"pair {pair_id!r} has tied preference ranks")
        chosen, rejected = sorted(pair, key=lambda item: item["preference_rank"], reverse=True)
        entry = registry[chosen["matter_id"]]
        prompt_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _canonical(chosen["state"])},
        ]
        prompt = _canonical(prompt_messages)
        for candidate in pair:
            outcome = _canonical(candidate["outcome"])
            if outcome in prompt:
                raise ValueError(f"pair {pair_id!r} leaks an action outcome into its prompt")
        record = {
            "schema_version": SCHEMA_VERSION,
            "pair_id": pair_id,
            "prompt": prompt,
            "chosen": _canonical(chosen["action"]),
            "rejected": _canonical(rejected["action"]),
            "metadata": {
                "matter_id": chosen["matter_id"],
                **entry,
                "state_sha256": _sha256(_canonical(chosen["state"]).encode("utf-8")),
                "category": chosen["category"],
                "preference_source": chosen["preference_source"],
                "reviewer": chosen["reviewer"],
                "chosen_candidate_id": chosen["candidate_id"],
                "rejected_candidate_id": rejected["candidate_id"],
                "chosen_outcome": chosen["outcome"],
                "rejected_outcome": rejected["outcome"],
                "chosen_reason": chosen["structured_reason"],
                "rejected_reason": rejected["structured_reason"],
            },
        }
        record["content_hash"] = _record_hash(record)
        records.append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    pairs_bytes = "".join(_canonical(record) + "\n" for record in records).encode("utf-8")
    (output_dir / "decision_pairs.jsonl").write_bytes(pairs_bytes)
    registry_bytes = registry_path.read_bytes()
    (output_dir / "family_registry.yaml").write_bytes(registry_bytes)
    category_counts = Counter(record["metadata"]["category"] for record in records)
    family_counts = Counter(record["metadata"]["matter_family_id"] for record in records)
    split_counts = Counter(record["metadata"]["split"] for record in records)
    reviewer_counts = Counter(record["metadata"]["reviewer"] for record in records)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "candidates": {"path": candidates_path.name, "sha256": _sha256(candidates_bytes)},
            "registry": {"path": "family_registry.yaml", "sha256": _sha256(registry_bytes)},
        },
        "output": {
            "path": "decision_pairs.jsonl",
            "pairs": len(records),
            "sha256": _sha256(pairs_bytes),
        },
        "statistics": {
            "categories": dict(sorted(category_counts.items())),
            "families": dict(sorted(family_counts.items())),
            "splits": dict(sorted(split_counts.items())),
            "reviewers": dict(sorted(reviewer_counts.items())),
        },
        "inclusion_policy": {
            "approved_review_required": True,
            "same_state_required": True,
            "distinct_rank_required": True,
            "held_out_denied_by_default": True,
            "allow_held_out": allow_held_out,
            "outcomes_excluded_from_policy_prompt": True,
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def verify_decision_pairs(output_dir: Path) -> dict[str, Any]:
    """Verify pair, registry, record hashes, and the same-state leakage boundary."""
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("preference manifest has an unsupported schema_version")
    registry_descriptor = manifest.get("inputs", {}).get("registry", {})
    registry_path = output_dir / str(registry_descriptor.get("path", ""))
    if not registry_path.is_file() or _sha256(registry_path.read_bytes()) != registry_descriptor.get(
        "sha256"
    ):
        raise ValueError("preference registry snapshot hash mismatch")
    registry = load_family_registry(registry_path)
    output = manifest.get("output", {})
    pairs_path = output_dir / str(output.get("path", ""))
    raw = pairs_path.read_bytes()
    if _sha256(raw) != output.get("sha256"):
        raise ValueError("decision-pair output hash mismatch")
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    if len(records) != output.get("pairs"):
        raise ValueError("decision-pair count mismatch")
    for record in records:
        if record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("decision-pair record has an unsupported schema")
        if record.get("content_hash") != _record_hash(record):
            raise ValueError("decision-pair record content hash mismatch")
        metadata = record.get("metadata", {})
        matter_id = metadata.get("matter_id")
        if matter_id not in registry or any(
            metadata.get(key) != value for key, value in registry[matter_id].items()
        ):
            raise ValueError("decision-pair lineage does not match registry")
        messages = json.loads(record["prompt"])
        if [item.get("role") for item in messages] != ["system", "user"]:
            raise ValueError("decision-pair prompt has an invalid message shape")
        prompt = record["prompt"]
        for field in ("chosen_outcome", "rejected_outcome"):
            if _canonical(metadata[field]) in prompt:
                raise ValueError("decision-pair outcome leaked into policy prompt")
    expected_statistics = {
        "categories": dict(
            sorted(Counter(record["metadata"]["category"] for record in records).items())
        ),
        "families": dict(
            sorted(Counter(record["metadata"]["matter_family_id"] for record in records).items())
        ),
        "splits": dict(
            sorted(Counter(record["metadata"]["split"] for record in records).items())
        ),
        "reviewers": dict(
            sorted(Counter(record["metadata"]["reviewer"] for record in records).items())
        ),
    }
    if manifest.get("statistics") != expected_statistics:
        raise ValueError("decision-pair statistics do not match records")
    return {
        "valid": True,
        "schema_version": SCHEMA_VERSION,
        "pairs": len(records),
        "reviewers": sorted(expected_statistics["reviewers"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-held-out", action="store_true")
    args = parser.parse_args()
    manifest = build_decision_pairs(
        args.candidates,
        args.registry,
        args.out,
        allow_held_out=args.allow_held_out,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


def verify_main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Playbook decision-pair release.")
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_decision_pairs(args.release), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
