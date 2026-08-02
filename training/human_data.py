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
import urllib.request
from pathlib import Path
from typing import Any

from playbook_legal.env import PlaybookEnv
from playbook_legal.export import convert

SCORE_TOLERANCE = 1e-6


def _get(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            # Cloudflare's edge rejects the bare urllib user agent.
            "User-Agent": "playbook-human-data/0.2",
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
    trace = record.get("trace") or {}
    matter_id = str(trace.get("matter", ""))
    matter_dir = matters_root / matter_id
    if not (matter_dir / "matter.yaml").exists():
        return False, f"unknown matter: {matter_id}", None
    events = trace.get("events") or []
    claimed = trace.get("result") or {}

    env = PlaybookEnv.from_directory(matter_dir)
    env.reset(seed=0)
    for event in events:
        action = event.get("action")
        if not isinstance(action, dict):
            return False, "malformed event", None
        try:
            _, _, terminated, truncated, _ = env.step(action)
        except RuntimeError:
            return False, "actions continue past episode end", None
        if terminated or truncated:
            break

    replayed = env.episode_result()
    if abs(replayed["normalized_score"] - float(claimed.get("normalized_score", -1))) > SCORE_TOLERANCE:
        return False, (
            f"score mismatch: claimed {claimed.get('normalized_score')} "
            f"replayed {replayed['normalized_score']}"
        ), None
    if replayed["critical_failure"] != bool(claimed.get("critical_failure", False)):
        return False, "critical-failure mismatch", None

    payload = {
        "matter": matter_id,
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
            tag = "human" + (f":{record['handle']}" if record.get("handle") else "")
            chat = convert(payload, agent=tag)
            handle.write(json.dumps(chat, ensure_ascii=False) + "\n")
            kept += 1
    return kept, rejected, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=False, help="Worker base URL")
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--raw-dir", type=Path, default=Path("artifacts/human_traces"))
    parser.add_argument(
        "--out", "--output", dest="out", type=Path, default=Path("artifacts/human_sft.jsonl")
    )
    parser.add_argument("--skip-fetch", action="store_true", help="Verify/export raw-dir only")
    args = parser.parse_args()

    if not args.skip_fetch:
        token = os.environ.get("PLAYBOOK_TRACES_TOKEN", "")
        if not args.endpoint or not token:
            raise SystemExit("--endpoint and PLAYBOOK_TRACES_TOKEN are required to fetch")
        endpoint = args.endpoint.rstrip("/")
        if endpoint.endswith("/api/traces"):
            endpoint = endpoint[: -len("/api/traces")]
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


if __name__ == "__main__":
    main()
