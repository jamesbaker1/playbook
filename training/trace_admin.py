# SPDX-License-Identifier: AGPL-3.0-only

"""Safely inspect, verify, and export records from the trace Worker.

The default operation is read-only: records are fetched into memory, replayed,
and summarized. Raw records are only persisted with ``--raw-dir`` and verified
training data is only written with ``--out``.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from human_data import export_verified, verify_record

USER_AGENT = "playbook-trace-admin/0.1"


class TraceServiceError(RuntimeError):
    """A safe, credential-free description of a trace service failure."""


JsonGetter = Callable[[str, str], Any]


def normalize_endpoint(value: str) -> str:
    endpoint = value.strip().rstrip("/")
    endpoint = endpoint.removesuffix("/api/traces")
    if not endpoint.startswith(("https://", "http://")):
        raise ValueError("endpoint must be an http(s) URL")
    return endpoint


def get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise TraceServiceError("authentication failed (check READ_TOKEN)") from None
        raise TraceServiceError(f"trace service returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TraceServiceError(f"trace service is unavailable ({type(exc).__name__})") from None


@dataclass(frozen=True)
class RemoteRecords:
    records: list[dict[str, Any]]
    keys: list[str]
    pages: int


def fetch_remote(
    endpoint: str,
    token: str,
    *,
    limit: int | None = None,
    getter: JsonGetter = get_json,
) -> RemoteRecords:
    """Authenticate, paginate listings, and fetch at most ``limit`` records."""
    endpoint = normalize_endpoint(endpoint)
    keys: list[str] = []
    cursor: str | None = None
    pages = 0
    while limit is None or len(keys) < limit:
        query = "" if cursor is None else "?" + urllib.parse.urlencode({"cursor": cursor})
        listing = getter(f"{endpoint}/api/traces{query}", token)
        pages += 1
        if not isinstance(listing, dict) or not isinstance(listing.get("keys"), list):
            raise TraceServiceError("trace service returned a malformed listing")
        remaining = None if limit is None else limit - len(keys)
        listed = listing["keys"] if remaining is None else listing["keys"][:remaining]
        if not all(isinstance(key, str) for key in listed):
            raise TraceServiceError("trace service returned malformed keys")
        keys.extend(listed)
        cursor = listing.get("cursor")
        if not cursor:
            break
        if not isinstance(cursor, str):
            raise TraceServiceError("trace service returned a malformed cursor")

    records: list[dict[str, Any]] = []
    for key in keys:
        encoded = urllib.parse.quote(key, safe="")
        record = getter(f"{endpoint}/api/traces/{encoded}", token)
        if not isinstance(record, dict):
            raise TraceServiceError("trace service returned a malformed record")
        records.append(record)
    return RemoteRecords(records=records, keys=keys, pages=pages)


@dataclass(frozen=True)
class AuditReport:
    total: int
    accepted: int
    rejected: int
    rejection_reasons: dict[str, int]


def audit_records(records: list[dict[str, Any]], matters_root: Path) -> AuditReport:
    reasons: Counter[str] = Counter()
    accepted = 0
    for record in records:
        ok, reason, _ = verify_record(record, matters_root)
        if ok:
            accepted += 1
        else:
            reasons[reason] += 1
    return AuditReport(
        total=len(records),
        accepted=accepted,
        rejected=len(records) - accepted,
        rejection_reasons=dict(sorted(reasons.items())),
    )


def cache_records(remote: RemoteRecords, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for key, record in zip(remote.keys, remote.records, strict=True):
        name = urllib.parse.quote(key, safe="") + ".json"
        (destination / name).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Trace Worker base URL")
    parser.add_argument("--matters", type=Path, default=Path("matters"))
    parser.add_argument("--limit", type=int, help="Inspect at most this many records")
    parser.add_argument("--raw-dir", type=Path, help="Opt in to caching untrusted raw records")
    parser.add_argument("--out", type=Path, help="Opt in to writing verified training JSONL")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    token = os.environ.get("PLAYBOOK_TRACES_TOKEN", "")
    if not token:
        raise SystemExit("PLAYBOOK_TRACES_TOKEN is required")
    try:
        remote = fetch_remote(args.endpoint, token, limit=args.limit)
    except (TraceServiceError, ValueError) as exc:
        raise SystemExit(f"health check failed: {exc}") from None

    report = audit_records(remote.records, args.matters)
    if args.raw_dir:
        cache_records(remote, args.raw_dir)
    if args.out:
        export_verified(remote.records, args.matters, args.out)

    payload = {
        "health": "ok",
        "authenticated": True,
        "pages": remote.pages,
        "records": report.total,
        "accepted": report.accepted,
        "rejected": report.rejected,
        "rejection_reasons": report.rejection_reasons,
        "raw_cached": bool(args.raw_dir),
        "export_written": bool(args.out),
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("trace service: healthy and authenticated")
        print(f"records: {report.total}; accepted: {report.accepted}; rejected: {report.rejected}")
        for reason, count in report.rejection_reasons.items():
            print(f"  {count} rejected: {reason}")
        print(
            "dry run: no files written"
            if not (args.raw_dir or args.out)
            else "requested files written"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
