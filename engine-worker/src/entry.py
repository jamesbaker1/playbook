# SPDX-License-Identifier: AGPL-3.0-only

"""Cloudflare Python Worker entry point."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from core import DEFAULT_MAX_ACTIONS, DEFAULT_MAX_REQUEST_BYTES, handle_api
from js import Headers
from workers import Response, WorkerEntrypoint

LOCAL_DEVELOPMENT_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        origin = request.headers.get("Origin") or ""
        allowed_origin = str(getattr(self.env, "ALLOWED_ORIGIN", ""))
        origin_allowed = origin == allowed_origin or origin in LOCAL_DEVELOPMENT_ORIGINS
        headers = _headers(origin, origin_allowed)
        if request.method == "OPTIONS":
            if not origin_allowed:
                return _json_response(403, {"error": {"code": "origin_forbidden", "message": "Origin is not allowed."}}, headers)
            return Response(None, status=204, headers=headers)
        if origin and not origin_allowed:
            return _json_response(403, {"error": {"code": "origin_forbidden", "message": "Origin is not allowed."}}, headers)
        try:
            max_bytes = int(getattr(self.env, "MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES))
            max_actions = int(getattr(self.env, "MAX_ACTIONS", DEFAULT_MAX_ACTIONS))
            content_length = request.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                return _json_response(413, {"error": {"code": "request_too_large", "message": "Request body is too large."}}, headers)
            body = (await request.text()).encode("utf-8") if request.method == "POST" else b""
            status, payload = handle_api(
                request.method,
                urlsplit(request.url).path,
                body,
                max_actions=max_actions,
                max_request_bytes=max_bytes,
            )
            return _json_response(status, payload, headers)
        except Exception:  # noqa: BLE001 -- never expose runtime or engine details to callers
            return _json_response(500, {"error": {"code": "internal_error", "message": "The scoring service could not process the request."}}, headers)


def _headers(origin: str, origin_allowed: bool):
    headers = Headers.new()
    headers.set("Content-Type", "application/json; charset=utf-8")
    headers.set("Cache-Control", "no-store")
    headers.set("Vary", "Origin")
    if origin and origin_allowed:
        headers.set("Access-Control-Allow-Origin", origin)
        headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        headers.set("Access-Control-Allow-Headers", "Content-Type")
        headers.set("Access-Control-Max-Age", "86400")
    return headers


def _json_response(status: int, payload: dict, headers):
    return Response(json.dumps(payload, ensure_ascii=False), status=status, headers=headers)
