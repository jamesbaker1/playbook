from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from conftest import replay

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("worker_core", ROOT / "engine-worker/src/core.py")
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def request(method: str, path: str, payload=None):
    body = b"" if payload is None else json.dumps(payload).encode()
    return core.handle_api(method, path, body, matters_root=ROOT / "matters")


def test_health_and_matters():
    status, health = request("GET", "/api/health")
    assert status == 200
    assert health["ok"] is True
    assert health["engine_version"]
    status, response = request("GET", "/api/matters")
    assert status == 200
    assert any(row["id"] == "ai_saas_001" for row in response["matters"])


def test_start_and_stateless_step():
    status, started = request("POST", "/api/start", {"matter_id": "ai_saas_001", "seed": 7})
    assert status == 200
    assert started["observation"]["matter"]["matter_id"] == "ai_saas_001"
    status, stepped = request(
        "POST",
        "/api/step",
        {"matter_id": "ai_saas_001", "seed": 7, "actions": [{"type": "read_document", "document_id": "msa"}]},
    )
    assert status == 200
    assert stepped["observation"]["last_result"]["document_id"] == "msa"
    assert stepped["terminated"] is False
    assert stepped["result"] is None
    assert stepped["reward"] is None
    assert "info" not in stepped
    assert "trace" not in stepped


def test_rejects_bad_input_without_leaking_details():
    status, response = request("POST", "/api/step", {"matter_id": "../hidden", "actions": []})
    assert status == 400
    assert response["error"]["code"] == "invalid_matter_id"
    status, response = request("POST", "/api/start", {"matter_id": "missing"})
    assert status == 404
    assert response["error"]["code"] == "matter_not_found"


def test_terminal_response_includes_full_trace():
    action = {"type": "submit_final", "summary": "Review complete."}
    status, response = request(
        "POST", "/api/step", {"matter_id": "ai_saas_001", "seed": 0, "actions": [action]}
    )
    assert status == 200
    assert response["terminated"] is True
    assert response["result"]
    assert response["trace"]["events"][0]["action"] == action
    assert response["trace"]["result"] == response["result"]
    assert response["trace"]["engine_version"] == response["engine_version"]


def test_request_limits_and_episode_boundary():
    status, response = core.handle_api(
        "POST", "/api/step", b"{}" * 20, matters_root=ROOT / "matters", max_request_bytes=4
    )
    assert status == 413
    assert response["error"]["code"] == "request_too_large"

    status, response = request(
        "POST",
        "/api/step",
        {
            "matter_id": "ai_saas_001",
            "actions": [
                {"type": "submit_final", "summary": "Done."},
                {"type": "read_document", "document_id": "msa"},
            ],
        },
    )
    assert status == 409
    assert response["error"]["code"] == "episode_complete"


def test_negotiation_reference_replays_like_browser_and_matches_cli_exactly():
    """The browser resends the complete action list after every user action."""
    matter_id = "nego_saas_010"
    actions_path = ROOT / "examples" / matter_id / "good.jsonl"
    actions = [json.loads(line) for line in actions_path.read_text(encoding="utf-8").splitlines()]

    for end in range(1, len(actions) + 1):
        status, response = request(
            "POST", "/api/step", {"matter_id": matter_id, "seed": 0, "actions": actions[:end]}
        )
        assert status == 200
        assert response["terminated"] is (end == len(actions))

    cli_result = replay(ROOT / "matters" / matter_id, actions_path)
    assert response["result"] == cli_result
    assert {"escalate", "send_markup", "accept_counterparty"} <= {
        action["type"] for action in actions
    }
