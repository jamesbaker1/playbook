"""Runtime-independent request handling for the Playbook engine Worker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playbook_legal import __version__
from playbook_legal.env import PlaybookEnv
from playbook_legal.loaders import load_yaml

ENGINE_VERSION = __version__
DEFAULT_MATTERS_ROOT = Path(__file__).parent / "matters"
DEFAULT_MAX_ACTIONS = 50
DEFAULT_MAX_REQUEST_BYTES = 256 * 1024


class ApiError(ValueError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def list_matters(matters_root: Path) -> list[dict[str, Any]]:
    rows = []
    for matter_yaml in sorted(matters_root.glob("*/matter.yaml")):
        matter = load_yaml(matter_yaml)
        rows.append(
            {
                "id": matter["matter_id"],
                "title": matter["title"],
                "practice_area": matter.get("practice_area", ""),
                "role": matter.get("role", ""),
            }
        )
    return rows


def handle_api(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    matters_root: Path = DEFAULT_MATTERS_ROOT,
    max_actions: int = DEFAULT_MAX_ACTIONS,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
) -> tuple[int, dict[str, Any]]:
    """Handle an API request without depending on the Cloudflare runtime."""
    try:
        if len(body) > max_request_bytes:
            raise ApiError(413, "request_too_large", "Request body is too large.")
        if method == "GET" and path == "/api/health":
            return 200, {"ok": True, "engine_version": ENGINE_VERSION}
        if method == "GET" and path == "/api/matters":
            return 200, {
                "matters": list_matters(matters_root),
                "engine_version": ENGINE_VERSION,
            }
        if method == "POST" and path in {"/api/start", "/api/step"}:
            payload = _parse_payload(body)
            matter_id = _matter_id(payload)
            seed = _seed(payload)
            actions = _actions(payload, max_actions=max_actions)
            if path == "/api/start" and actions:
                raise ApiError(400, "invalid_actions", "Start does not accept prior actions.")
            return 200, _replay(matters_root, matter_id, seed, actions)
        raise ApiError(404, "not_found", "API endpoint not found.")
    except ApiError as exc:
        return exc.status, {
            "error": {"code": exc.code, "message": exc.message},
            "engine_version": ENGINE_VERSION,
        }


def _parse_payload(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "invalid_json", "Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_json", "Request body must be a JSON object.")
    return payload


def _matter_id(payload: dict[str, Any]) -> str:
    value = payload.get("matter_id")
    if not isinstance(value, str) or not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
        raise ApiError(400, "invalid_matter_id", "matter_id is invalid.")
    return value


def _seed(payload: dict[str, Any]) -> int:
    value = payload.get("seed", 0)
    if isinstance(value, bool) or not isinstance(value, int) or not -(2**31) <= value < 2**31:
        raise ApiError(400, "invalid_seed", "seed must be a 32-bit integer.")
    return value


def _actions(payload: dict[str, Any], *, max_actions: int) -> list[dict[str, Any]]:
    value = payload.get("actions", [])
    if not isinstance(value, list) or any(not isinstance(action, dict) for action in value):
        raise ApiError(400, "invalid_actions", "actions must be an array of objects.")
    if len(value) > max_actions:
        raise ApiError(400, "too_many_actions", f"At most {max_actions} actions are allowed.")
    return value


def _replay(
    matters_root: Path, matter_id: str, seed: int, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    matter_dir = matters_root / matter_id
    if not matter_dir.is_dir() or not (matter_dir / "matter.yaml").is_file():
        raise ApiError(404, "matter_not_found", "Matter not found.")
    env = PlaybookEnv.from_directory(matter_dir)
    observation, _ = env.reset(seed=seed)
    reward = 0.0
    terminated = truncated = False
    for index, action in enumerate(actions):
        if terminated or truncated:
            raise ApiError(
                409,
                "episode_complete",
                f"Action {index + 1} occurs after the episode completed.",
            )
        observation, reward, terminated, truncated, _ = env.step(action)
    response: dict[str, Any] = {
        "observation": observation,
        # Withhold incremental score during play. Live rewards turn the public gym
        # into a rubric oracle and produce reward-probing rather than natural traces.
        "reward": reward if terminated or truncated else None,
        "terminated": terminated,
        "truncated": truncated,
        "result": env.episode_result() if terminated or truncated else None,
        "engine_version": ENGINE_VERSION,
    }
    if terminated or truncated:
        response["trace"] = {
            "matter": matter_id,
            "seed": seed,
            "engine_version": ENGINE_VERSION,
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
            "result": env.episode_result(),
        }
    return response
