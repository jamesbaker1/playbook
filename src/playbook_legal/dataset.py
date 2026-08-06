# SPDX-License-Identifier: AGPL-3.0-only

"""Build deterministic, contamination-safe Playbook training datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from playbook_legal.env import PlaybookEnv
from playbook_legal.export import SYSTEM_PROMPT, convert
from playbook_legal.loaders import load_documents, load_yaml

SCHEMA_VERSION = "playbook.dataset.v1"
GENERATOR_VERSION = "1"
VIEWS = ("final_answer", "trajectory_chat", "state_action")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _content_hash(record: dict[str, Any]) -> str:
    unhashed = {key: value for key, value in record.items() if key != "content_hash"}
    return _hash_bytes(_canonical(unhashed).encode("utf-8"))


def _tree_hash(root: Path) -> str:
    files = [
        {"path": path.relative_to(root).as_posix(), "sha256": _hash_bytes(path.read_bytes())}
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]
    return _hash_bytes(_canonical(files).encode("utf-8"))


def verify_trace_replay(trace: dict[str, Any], matter_dir: Path) -> dict[str, Any]:
    """Replay a trace and reject any forged observation, reward, event info, or result."""
    if "seed" not in trace or (trace["seed"] is not None and not isinstance(trace["seed"], int)):
        raise ValueError("trace has no valid replay seed")
    env = PlaybookEnv.from_directory(matter_dir)
    initial, _ = env.reset(seed=trace["seed"])
    if initial != trace.get("initial_observation"):
        raise ValueError("trace initial_observation does not match deterministic replay")
    events = trace.get("events", [])
    for index, stored in enumerate(events):
        observation, reward, terminated, truncated, info = env.step(stored["action"])
        actual = {
            "step": index + 1,
            "action": stored["action"],
            "observation": observation,
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
            "info": info,
        }
        if actual != stored:
            raise ValueError(f"trace event {index + 1} does not match deterministic replay")
        if (terminated or truncated) and index != len(events) - 1:
            raise ValueError("trace contains events after episode completion")
    result = env.episode_result()
    if result != trace.get("result"):
        raise ValueError("trace result does not match deterministic replay")
    return {
        "matter_id": trace.get("matter"),
        "seed": trace["seed"],
        "events": len(events),
        "trace_sha256": _hash_bytes(_canonical(trace).encode("utf-8")),
        "matter_package_sha256": _tree_hash(matter_dir),
    }


def load_family_registry(path: Path) -> dict[str, dict[str, str]]:
    """Return matter -> family/split mapping after enforcing family-level separation."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if payload.get("version") != 1 or not isinstance(payload.get("families"), dict):
        raise ValueError(f"{path}: expected version 1 and a families mapping")

    matters: dict[str, dict[str, str]] = {}
    family_splits: dict[str, str] = {}
    template_splits: dict[str, str] = {}
    for family_id, config in sorted(payload["families"].items()):
        if not isinstance(config, dict) or not isinstance(config.get("split"), str):
            raise TypeError(f"{path}: family {family_id!r} has no split")
        split = config["split"]
        previous = family_splits.setdefault(str(family_id), split)
        if previous != split:
            raise ValueError(f"{path}: family {family_id!r} appears in multiple splits")
        template_sha256 = config.get("template_sha256")
        if template_sha256 is not None:
            if not isinstance(template_sha256, str) or re.fullmatch(
                r"[0-9a-f]{64}", template_sha256
            ) is None:
                raise ValueError(f"{path}: family {family_id!r} has an invalid template SHA-256")
            previous_template_split = template_splits.setdefault(template_sha256, split)
            if previous_template_split != split:
                raise ValueError(
                    f"{path}: template {template_sha256} appears in multiple splits "
                    f"({previous_template_split!r} and {split!r})"
                )
        family_matters = config.get("matters")
        sealed_hashes = config.get("sealed_matter_hashes")
        if family_matters is not None and sealed_hashes is not None:
            raise ValueError(f"{path}: family {family_id!r} mixes open and sealed matters")
        if sealed_hashes is not None:
            if split not in {"held-out", "evaluation", "eval", "test"}:
                raise ValueError(f"{path}: sealed family {family_id!r} must be held out")
            if not isinstance(sealed_hashes, dict) or not sealed_hashes:
                raise ValueError(f"{path}: sealed family {family_id!r} has no identifier hashes")
            for matter_id, digest in sealed_hashes.items():
                if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    raise ValueError(f"{path}: sealed matter {matter_id!r} has an invalid SHA-256")
            family_matters = list(sealed_hashes)
        if not isinstance(family_matters, list) or not family_matters:
            raise ValueError(f"{path}: family {family_id!r} has no matters")
        for matter_id in family_matters:
            matter_id = str(matter_id)
            if matter_id in matters:
                raise ValueError(f"{path}: matter {matter_id!r} appears more than once")
            matters[matter_id] = {
                "matter_family_id": str(family_id),
                "split": split,
                **({"template_sha256": template_sha256} if template_sha256 else {}),
            }
    return matters


def _metadata(
    trace: dict[str, Any],
    registry_entry: dict[str, str],
    *,
    source: str,
    license_or_consent: str,
    reviewer: str | None,
    review_status: str,
) -> dict[str, Any]:
    result = trace["result"]
    return {
        "matter_id": trace["matter"],
        **registry_entry,
        "source": source,
        "license_or_consent": license_or_consent,
        "reviewer": reviewer,
        "review_status": review_status,
        "generator_version": GENERATOR_VERSION,
        "score": result["normalized_score"],
        "score_components": result.get("breakdown", {}),
        "critical_failure": result["critical_failure"],
    }


def build_records(
    trace: dict[str, Any],
    registry_entry: dict[str, str],
    *,
    source: str = "scripted",
    license_or_consent: str = "AGPL-3.0-only",
    reviewer: str | None = None,
    review_status: str = "unreviewed",
    matter_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Create all dataset views for one trace without exposing action outcomes in prompts."""
    if "initial_observation" not in trace:
        raise ValueError("trace has no initial_observation")
    events = trace.get("events", [])
    if not events:
        raise ValueError("trace has no events")
    base_meta = _metadata(
        trace,
        registry_entry,
        source=source,
        license_or_consent=license_or_consent,
        reviewer=reviewer,
        review_status=review_status,
    )

    trajectory = convert(trace, agent=source)
    trajectory_record = {
        "schema_version": SCHEMA_VERSION,
        "view": "trajectory_chat",
        "messages": trajectory["messages"],
        "metadata": base_meta,
    }

    final_events = [event for event in events if event["action"].get("type") == "submit_final"]
    final_records: list[dict[str, Any]] = []
    if final_events:
        summary = final_events[-1]["action"].get("summary", "")
        final_context: dict[str, Any] = {"initial_observation": trace["initial_observation"]}
        if matter_dir is not None:
            matter = load_yaml(matter_dir / "matter.yaml")
            documents = load_documents(matter_dir, matter.get("documents", []))
            final_context["documents"] = [
                {
                    "id": document_id,
                    "title": document["title"],
                    "sections": {
                        section: content
                        for section, content in document["sections"].items()
                        if section != "full"
                    },
                }
                for document_id, document in documents.items()
            ]
        final_records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "view": "final_answer",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _canonical(final_context),
                    },
                    {"role": "assistant", "content": str(summary)},
                ],
                "metadata": base_meta,
            }
        )

    state_records: list[dict[str, Any]] = []
    preceding = trace["initial_observation"]
    for index, event in enumerate(events):
        # Only the observation available before this action enters the policy prompt.
        record = {
            "schema_version": SCHEMA_VERSION,
            "view": "state_action",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _canonical(preceding)},
                {"role": "assistant", "content": _canonical(event["action"])},
            ],
            "metadata": {
                **base_meta,
                "step": index + 1,
                "selected_action": event["action"],
                "resulting_observation": event["observation"],
                "reward": event.get("reward"),
                "reason": event.get("info", {}),
                "terminated": bool(event.get("terminated")),
                "truncated": bool(event.get("truncated")),
            },
        }
        state_records.append(record)
        preceding = event["observation"]

    views = {
        "final_answer": final_records,
        "trajectory_chat": [trajectory_record],
        "state_action": state_records,
    }
    for records in views.values():
        for record in records:
            record["content_hash"] = _content_hash(record)
    return views


def write_dataset(
    traces: Iterable[Path],
    registry_path: Path,
    output_dir: Path,
    *,
    allow_held_out: bool = False,
    source: str = "scripted",
    license_or_consent: str = "AGPL-3.0-only",
    reviewer: str | None = None,
    review_status: str = "unreviewed",
    matters_root: Path | None = None,
) -> dict[str, Any]:
    """Build views and a deterministic manifest. Held-out data is denied by default."""
    registry = load_family_registry(registry_path)
    trace_paths = sorted((Path(path) for path in traces), key=lambda path: path.as_posix())
    names = [path.name for path in trace_paths]
    if len(names) != len(set(names)):
        raise ValueError("trace filenames must be unique for a reproducible manifest")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty dataset release: {output_dir}")
    all_records: dict[str, list[dict[str, Any]]] = {view: [] for view in VIEWS}
    inputs: list[dict[str, str]] = []
    episode_rows: list[dict[str, Any]] = []
    replay_verifications: list[dict[str, Any]] = []
    for path in trace_paths:
        raw = path.read_bytes()
        trace = json.loads(raw)
        matter_id = str(trace.get("matter", ""))
        if matter_id not in registry:
            raise ValueError(f"{path}: matter {matter_id!r} is absent from the family registry")
        if matters_root is not None:
            matter_dir = matters_root / matter_id
            if not matter_dir.is_dir():
                raise ValueError(f"{path}: matter package is missing: {matter_dir}")
            replay_verifications.append(verify_trace_replay(trace, matter_dir))
        entry = registry[matter_id]
        if entry["split"] in {"held-out", "evaluation", "eval", "test"} and not allow_held_out:
            raise ValueError(f"{path}: refusing to export held-out family {entry['matter_family_id']!r}")
        built = build_records(
            trace,
            entry,
            source=source,
            license_or_consent=license_or_consent,
            reviewer=reviewer,
            review_status=review_status,
            matter_dir=(matters_root / matter_id) if matters_root is not None else None,
        )
        for view in VIEWS:
            all_records[view].extend(built[view])
        inputs.append({"path": path.name, "sha256": _hash_bytes(raw)})
        episode_rows.append(
            {
                "matter_id": matter_id,
                **entry,
                "critical_failure": bool(trace["result"]["critical_failure"]),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict[str, Any]] = {}
    for view in VIEWS:
        records = sorted(
            all_records[view],
            key=lambda row: (row["metadata"]["matter_family_id"], row["metadata"]["matter_id"], row["metadata"].get("step", 0)),
        )
        data = "".join(_canonical(record) + "\n" for record in records).encode("utf-8")
        filename = f"{view}.jsonl"
        (output_dir / filename).write_bytes(data)
        outputs[view] = {"path": filename, "records": len(records), "sha256": _hash_bytes(data)}

    registry_bytes = registry_path.read_bytes()
    registry_snapshot = "family_registry.yaml"
    (output_dir / registry_snapshot).write_bytes(registry_bytes)
    action_counts = Counter(
        str(record["metadata"]["selected_action"].get("type", ""))
        for record in all_records["state_action"]
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "registry": {"path": registry_snapshot, "sha256": _hash_bytes(registry_bytes)},
        "inputs": inputs,
        "outputs": outputs,
        "provenance": {
            "source": source,
            "license_or_consent": license_or_consent,
            "reviewer": reviewer,
            "review_status": review_status,
            "trace_verification": (
                "replay_verified" if matters_root is not None else "unverified"
            ),
        },
        "inclusion_policy": {
            "registered_family_required": True,
            "initial_observation_required": True,
            "held_out_denied_by_default": True,
            "allow_held_out": allow_held_out,
            "outcomes_excluded_from_policy_prompt": True,
            "final_answer_context": (
                "complete_visible_matter" if matters_root is not None else "initial_observation_only"
            ),
        },
        "statistics": {
            "episodes": len(episode_rows),
            "critical_failure_episodes": sum(
                1 for row in episode_rows if row["critical_failure"]
            ),
            "families": dict(
                sorted(Counter(row["matter_family_id"] for row in episode_rows).items())
            ),
            "splits": dict(sorted(Counter(row["split"] for row in episode_rows).items())),
            "actions": dict(sorted(action_counts.items())),
            "review_status": {review_status: len(episode_rows)},
        },
        "replay_verifications": replay_verifications,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (output_dir / "manifest.json").write_bytes(manifest_bytes)
    return manifest


def verify_dataset(output_dir: Path) -> dict[str, Any]:
    """Independently verify a built dataset release and its prompt/outcome boundary."""
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("dataset manifest has an unsupported schema_version")
    registry = manifest.get("registry", {})
    registry_path = output_dir / str(registry.get("path", ""))
    if not registry_path.is_file() or _hash_bytes(registry_path.read_bytes()) != registry.get(
        "sha256"
    ):
        raise ValueError("family registry snapshot hash mismatch")
    load_family_registry(registry_path)

    verified_records = 0
    for view in VIEWS:
        descriptor = manifest.get("outputs", {}).get(view, {})
        path = output_dir / str(descriptor.get("path", ""))
        if not path.is_file():
            raise ValueError(f"missing dataset view: {view}")
        raw = path.read_bytes()
        if _hash_bytes(raw) != descriptor.get("sha256"):
            raise ValueError(f"dataset view hash mismatch: {view}")
        records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
        if len(records) != descriptor.get("records"):
            raise ValueError(f"dataset view record-count mismatch: {view}")
        for record in records:
            if record.get("schema_version") != SCHEMA_VERSION or record.get("view") != view:
                raise ValueError(f"invalid record schema or view in {view}")
            if record.get("content_hash") != _content_hash(record):
                raise ValueError(f"record content hash mismatch in {view}")
            if view == "state_action":
                messages = record.get("messages", [])
                if len(messages) != 3 or [item.get("role") for item in messages] != [
                    "system",
                    "user",
                    "assistant",
                ]:
                    raise ValueError("state-action record has an invalid policy message shape")
                outcome = _canonical(record.get("metadata", {}).get("resulting_observation"))
                policy_input = "\n".join(item.get("content", "") for item in messages[:2])
                if outcome in policy_input:
                    raise ValueError("state-action outcome leaked into policy input")
            verified_records += 1
    return {
        "valid": True,
        "schema_version": SCHEMA_VERSION,
        "views": len(VIEWS),
        "records": verified_records,
    }


def verify_main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Playbook dataset release.")
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_dataset(args.release), indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", type=Path, nargs="+")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument("--source", default="scripted")
    parser.add_argument("--license-or-consent", default="AGPL-3.0-only")
    parser.add_argument("--reviewer")
    parser.add_argument("--review-status", default="unreviewed")
    parser.add_argument("--matters", type=Path, help="Replay every trace against this matter root")
    args = parser.parse_args()
    manifest = write_dataset(
        args.traces,
        args.registry,
        args.out,
        allow_held_out=args.allow_held_out,
        source=args.source,
        license_or_consent=args.license_or_consent,
        reviewer=args.reviewer,
        review_status=args.review_status,
        matters_root=args.matters,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
