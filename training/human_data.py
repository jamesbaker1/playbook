# SPDX-License-Identifier: AGPL-3.0-only

"""Fetch, verify, and export human-contributed traces from the web gym.

Nothing uploaded from a browser is trusted. For every record this pipeline
replays the claimed action sequence through the real environment and recomputes
the result deterministically; a record is kept only if the replay reproduces the
claimed normalized score and critical-failure status. Exported chat records are
built from the REPLAYED episode (regenerated observations), never from uploaded
observation text, so tampered uploads cannot poison a dataset.

    export PLAYBOOK_TRACES_TOKEN=...   # the worker's READ_TOKEN
    python training/human_data.py --endpoint https://playbook-traces.<acct>.workers.dev
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from playbook_legal import __version__
from playbook_legal.env import PlaybookEnv
from playbook_legal.export import convert

SCORE_TOLERANCE = 1e-6
POLICY_PATH = Path(__file__).resolve().parents[1] / "web" / "policy.json"
CONSENT_VERSION = json.loads(POLICY_PATH.read_text(encoding="utf-8"))["consent_version"]
ALLOWED_BACKGROUNDS = {"lawyer", "legal_professional", "law_student", "other"}
ALLOWED_MODES = {"learn", "benchmark"}
INTERACTION_TYPES = re.compile(
    r"^(matter|document|search|selection|issue|redline|communication|counterparty|fact|final|capture|validation|transport)\.[a-z0-9_.-]+$"
)
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def verify_interaction_trace(record: dict[str, Any]) -> tuple[bool, str]:
    """Validate the optional semantic trace independently from canonical replay."""
    interaction = record.get("interaction_trace")
    if interaction is None:
        return True, "not present"
    if not isinstance(interaction, dict) or interaction.get("schema_version") != "1":
        return False, "invalid interaction trace schema"
    if (
        not UUID.fullmatch(str(record.get("contribution_id", "")))
        or interaction.get("contribution_id") != record.get("contribution_id")
        or interaction.get("matter_id") != (record.get("trace") or {}).get("matter")
        or interaction.get("engine_version") != record.get("app_version")
        or interaction.get("consent_version") != CONSENT_VERSION
        or not UUID.fullmatch(str(interaction.get("session_id", "")))
    ):
        return False, "interaction trace provenance mismatch"
    events = interaction.get("events")
    if not isinstance(events, list) or len(events) > 2500:
        return False, "malformed interaction events"
    ids: set[str] = set()
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            return False, "malformed interaction event order"
        event_id = str(event.get("event_id", ""))
        if not UUID.fullmatch(event_id) or event_id in ids:
            return False, "malformed interaction event id"
        ids.add(event_id)
        if not INTERACTION_TYPES.fullmatch(str(event.get("type", ""))):
            return False, "invalid interaction event type"
    return True, "ok"


def _get(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            # Cloudflare's edge rejects the bare urllib user agent.
            "User-Agent": f"playbook-human-data/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_records(endpoint: str, token: str, raw_dir: Path) -> list[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    cursor: str | None = None
    while True:
        url = f"{endpoint}/api/traces" + (f"?cursor={cursor}" if cursor else "")
        listing = _get(url, token)
        for key in listing["keys"]:
            destination = raw_dir / (key.replace(":", "_") + ".json")
            if not destination.exists():
                record = _get(f"{endpoint}/api/traces/{key}", token)
                destination.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            paths.append(destination)
        cursor = listing.get("cursor")
        if not cursor:
            break
    return paths


def verify_record(
    record: dict[str, Any], matters_root: Path
) -> tuple[bool, str, dict[str, Any] | None]:
    """Replay the record's actions; return (ok, reason, replayed_trace_payload)."""
    consent = record.get("consent") or {}
    if (
        consent.get("version") != CONSENT_VERSION
        or consent.get("training_and_evaluation") is not True
    ):
        return False, "missing or outdated training-and-evaluation consent", None
    app_version = record.get("app_version")
    if not isinstance(app_version, str) or not re.fullmatch(r"[0-9A-Za-z._-]{1,32}", app_version):
        return False, "missing or invalid app version", None
    if record.get("app", "web-gym") != "web-gym":
        return False, "invalid contribution source", None
    interaction_ok, interaction_reason = verify_interaction_trace(record)
    if not interaction_ok:
        return False, interaction_reason, None
    background = record.get("background")
    if background is not None and background not in ALLOWED_BACKGROUNDS:
        return False, "invalid contributor background", None
    mode = record.get("mode")
    if mode is not None and mode not in ALLOWED_MODES:
        return False, "invalid play mode", None

    trace = record.get("trace") or {}
    matter_id = str(trace.get("matter", ""))
    matter_dir = matters_root / matter_id
    if not (matter_dir / "matter.yaml").exists():
        return False, f"unknown matter: {matter_id}", None
    events = trace.get("events") or []
    claimed = trace.get("result") or {}
    if not isinstance(events, list) or not events or len(events) > 200:
        return False, "malformed events", None
    if not isinstance(claimed, dict):
        return False, "malformed claimed result", None

    env = PlaybookEnv.from_directory(matter_dir)
    seed = trace.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**31) <= seed < 2**31:
        return False, "invalid replay seed", None
    initial_observation, _ = env.reset(seed=seed)
    ended_at: int | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            return False, "malformed event", None
        action = event.get("action")
        if not isinstance(action, dict):
            return False, "malformed event", None
        try:
            _, _, terminated, truncated, _ = env.step(action)
        except RuntimeError:
            return False, "actions continue past episode end", None
        if terminated or truncated:
            ended_at = index
            break

    if ended_at is None:
        return False, "incomplete episode", None
    if ended_at != len(events) - 1:
        return False, "actions continue past episode end", None

    replayed = env.episode_result()
    claimed_score = claimed.get("normalized_score")
    if isinstance(claimed_score, bool) or not isinstance(claimed_score, (int, float)):
        return False, "malformed claimed score", None
    if abs(replayed["normalized_score"] - float(claimed_score)) > SCORE_TOLERANCE:
        return False, (
            f"score mismatch: claimed {claimed.get('normalized_score')} "
            f"replayed {replayed['normalized_score']}"
        ), None
    if replayed["critical_failure"] != bool(claimed.get("critical_failure", False)):
        return False, "critical-failure mismatch", None

    payload = {
        "matter": matter_id,
        "seed": seed,
        "initial_observation": initial_observation,
        "events": [
            {
                "step": event.step,
                "action": event.action,
                "observation": event.observation,
                "reward": event.reward,
                "terminated": event.terminated,
                "truncated": event.truncated,
                "info": event.info,
            }
            for event in env.trace
        ],
        "result": replayed,
    }
    return True, "ok", payload


def export_verified(
    records: list[dict[str, Any]], matters_root: Path, out_path: Path
) -> tuple[int, int, list[str]]:
    kept = 0
    rejected = 0
    reasons: list[str] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            ok, reason, payload = verify_record(record, matters_root)
            if not ok:
                rejected += 1
                reasons.append(reason)
                continue
            chat = convert(payload, agent="human")
            chat["provenance"] = {
                "source": "human_contribution",
                "app": record.get("app", "web-gym"),
                "app_version": record["app_version"],
                "mode": record.get("mode"),
                "consent_version": record["consent"]["version"],
                "contributor_background": record.get("background"),
            }
            handle.write(json.dumps(chat, ensure_ascii=False) + "\n")
            kept += 1
    return kept, rejected, reasons


def export_interactions(records: list[dict[str, Any]], out_path: Path) -> tuple[int, int]:
    """Export validated semantic traces separately; never mix them into canonical SFT."""
    kept = rejected = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            ok, _reason = verify_interaction_trace(record)
            interaction = record.get("interaction_trace")
            if not ok:
                rejected += 1
            elif interaction is not None:
                handle.write(json.dumps(interaction, ensure_ascii=False) + "\n")
                kept += 1
    return kept, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=False, help="Worker base URL")
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--raw-dir", type=Path, default=Path("artifacts/human_traces"))
    parser.add_argument(
        "--out", "--output", dest="out", type=Path, default=Path("artifacts/human_sft.jsonl")
    )
    parser.add_argument("--interaction-out", type=Path, help="Write validated semantic traces")
    parser.add_argument("--skip-fetch", action="store_true", help="Verify/export raw-dir only")
    args = parser.parse_args()

    if not args.skip_fetch:
        token = os.environ.get("PLAYBOOK_TRACES_TOKEN", "")
        if not args.endpoint or not token:
            raise SystemExit("--endpoint and PLAYBOOK_TRACES_TOKEN are required to fetch")
        endpoint = args.endpoint.rstrip("/")
        endpoint = endpoint.removesuffix("/api/traces")
        paths = fetch_records(endpoint, token, args.raw_dir)
        print(f"fetched {len(paths)} records into {args.raw_dir}")

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.raw_dir.glob("*.json"))
    ]
    kept, rejected, reasons = export_verified(records, args.matters, args.out)
    print(f"verified and exported {kept}; rejected {rejected}")
    for reason in reasons:
        print(f"  rejected: {reason}")
    print(args.out)
    if args.interaction_out:
        interaction_kept, interaction_rejected = export_interactions(records, args.interaction_out)
        print(f"exported {interaction_kept} interaction traces; rejected {interaction_rejected}")
        print(args.interaction_out)


if __name__ == "__main__":
    main()
