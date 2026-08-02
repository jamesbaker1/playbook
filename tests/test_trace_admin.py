from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest
from conftest import MATTERS, ROOT
from test_human_data import build_genuine_record

sys.path.insert(0, str(ROOT / "training"))

from trace_admin import (
    TraceServiceError,
    audit_records,
    cache_records,
    fetch_remote,
    get_json,
    main,
    normalize_endpoint,
)


def test_normalize_endpoint() -> None:
    assert normalize_endpoint("https://example.test/api/traces/") == "https://example.test"
    with pytest.raises(ValueError):
        normalize_endpoint("example.test")


def test_fetch_remote_paginates_encodes_keys_and_honors_limit() -> None:
    calls: list[str] = []

    def getter(url: str, token: str):
        assert token == "secret"
        calls.append(url)
        if url.endswith("/api/traces"):
            return {"keys": ["trace:first"], "cursor": "next cursor"}
        if "cursor=" in url:
            return {"keys": ["trace:second", "trace:ignored"], "cursor": None}
        return {"trace": {}}

    result = fetch_remote("https://example.test", "secret", limit=2, getter=getter)
    assert result.keys == ["trace:first", "trace:second"]
    assert result.pages == 2
    assert "cursor=next+cursor" in calls[1]
    assert calls[2].endswith("trace%3Afirst")
    assert calls[3].endswith("trace%3Asecond")


def test_fetch_remote_rejects_malformed_listing() -> None:
    with pytest.raises(TraceServiceError, match="malformed listing"):
        fetch_remote("https://example.test", "secret", getter=lambda _url, _token: {})


def test_audit_reports_grouped_rejections() -> None:
    good = build_genuine_record()
    bad = build_genuine_record()
    del bad["consent"]
    report = audit_records([good, bad, bad], MATTERS)
    assert (report.total, report.accepted, report.rejected) == (3, 1, 2)
    assert report.rejection_reasons == {"missing or outdated training-and-evaluation consent": 2}


def test_cache_records_is_explicit_and_uses_safe_filename(tmp_path: Path) -> None:
    remote = fetch_remote(
        "https://example.test",
        "secret",
        getter=lambda url, _token: (
            {"keys": ["trace:a/b"], "cursor": None} if url.endswith("/api/traces") else {"value": 1}
        ),
    )
    cache_records(remote, tmp_path)
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].name == "trace%3Aa%2Fb.json"


def test_main_defaults_to_dry_run(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("PLAYBOOK_TRACES_TOKEN", "do-not-print-me")
    monkeypatch.setattr(
        "trace_admin.fetch_remote",
        lambda *_args, **_kwargs: type(
            "Remote", (), {"records": [build_genuine_record()], "keys": ["key"], "pages": 1}
        )(),
    )
    assert main(["--endpoint", "https://example.test", "--matters", str(MATTERS)]) == 0
    output = capsys.readouterr().out
    assert "dry run: no files written" in output
    assert "do-not-print-me" not in output
    assert list(tmp_path.iterdir()) == []


def test_http_auth_error_is_redacted(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.test", 401, "bad", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(TraceServiceError) as caught:
        get_json("https://example.test/api/traces", "super-secret")
    assert "authentication failed" in str(caught.value)
    assert "super-secret" not in str(caught.value)
