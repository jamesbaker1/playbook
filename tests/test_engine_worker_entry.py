"""Cloudflare entry-point tests with the runtime-only modules mocked."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "engine-worker" / "src" / "entry.py"


class FakeHeaders:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    @classmethod
    def new(cls):
        return cls()

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


class FakeResponse:
    def __init__(self, body, *, status: int, headers: FakeHeaders) -> None:
        self.body = body
        self.status = status
        self.headers = headers


class FakeWorkerEntrypoint:
    env: SimpleNamespace


class FakeRequest:
    def __init__(
        self,
        method: str,
        url: str = "https://worker.example/api/health",
        *,
        origin: str = "https://playbook.example",
        body: str = "",
        content_length: str | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self._body = body
        self.headers = {"Origin": origin}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    async def text(self) -> str:
        return self._body


@pytest.fixture()
def entry_module(monkeypatch):
    js_module = ModuleType("js")
    js_module.Headers = FakeHeaders
    workers_module = ModuleType("workers")
    workers_module.Response = FakeResponse
    workers_module.WorkerEntrypoint = FakeWorkerEntrypoint
    core_module = ModuleType("core")
    core_module.DEFAULT_MAX_ACTIONS = 50
    core_module.DEFAULT_MAX_REQUEST_BYTES = 1024
    core_module.handle_api = lambda method, path, body, **limits: (
        200,
        {"method": method, "path": path, "body": body.decode(), "limits": limits},
    )
    monkeypatch.setitem(sys.modules, "js", js_module)
    monkeypatch.setitem(sys.modules, "workers", workers_module)
    monkeypatch.setitem(sys.modules, "core", core_module)

    spec = importlib.util.spec_from_file_location("engine_worker_entry_test", ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker(module, **env):
    instance = module.Default()
    instance.env = SimpleNamespace(ALLOWED_ORIGIN="https://playbook.example", **env)
    return instance


def test_fetch_delegates_to_core_and_sets_cors(entry_module) -> None:
    response = asyncio.run(
        worker(entry_module).fetch(
            FakeRequest("POST", "https://worker.example/api/step?ignored=yes", body='{"ok": true}')
        )
    )

    assert response.status == 200
    assert response.headers.values["Access-Control-Allow-Origin"] == "https://playbook.example"
    assert response.headers.values["Cache-Control"] == "no-store"
    payload = json.loads(response.body)
    assert payload["method"] == "POST"
    assert payload["path"] == "/api/step"
    assert payload["body"] == '{"ok": true}'
    assert payload["limits"] == {"max_actions": 50, "max_request_bytes": 1024}


def test_fetch_rejects_forbidden_origin_before_dispatch(entry_module) -> None:
    response = asyncio.run(
        worker(entry_module).fetch(FakeRequest("GET", origin="https://attacker.example"))
    )

    assert response.status == 403
    assert json.loads(response.body)["error"]["code"] == "origin_forbidden"
    assert "Access-Control-Allow-Origin" not in response.headers.values


@pytest.mark.parametrize("origin", ["http://localhost:8000", "http://127.0.0.1:8000"])
def test_fetch_accepts_local_static_server_origins(entry_module, origin: str) -> None:
    response = asyncio.run(worker(entry_module).fetch(FakeRequest("GET", origin=origin)))
    preflight = asyncio.run(worker(entry_module).fetch(FakeRequest("OPTIONS", origin=origin)))

    assert response.status == 200
    assert response.headers.values["Access-Control-Allow-Origin"] == origin
    assert preflight.status == 204
    assert preflight.headers.values["Access-Control-Allow-Origin"] == origin


def test_options_and_request_size_limits(entry_module) -> None:
    options = asyncio.run(worker(entry_module).fetch(FakeRequest("OPTIONS")))
    oversized = asyncio.run(
        worker(entry_module, MAX_REQUEST_BYTES="10").fetch(
            FakeRequest("POST", content_length="11")
        )
    )

    assert options.status == 204
    assert options.body is None
    assert oversized.status == 413
    assert json.loads(oversized.body)["error"]["code"] == "request_too_large"


def test_fetch_hides_runtime_exceptions(entry_module, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("secret engine detail")

    monkeypatch.setattr(entry_module, "handle_api", fail)
    response = asyncio.run(worker(entry_module).fetch(FakeRequest("GET")))

    assert response.status == 500
    assert "secret engine detail" not in response.body
    assert json.loads(response.body)["error"]["code"] == "internal_error"
