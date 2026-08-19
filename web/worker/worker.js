// SPDX-License-Identifier: AGPL-3.0-only
/* playbook-traces — trace-collection endpoint for the web gym.
 *
 * POST /api/traces        public (CORS-limited): accept one episode trace
 * GET  /api/traces        Bearer READ_TOKEN: list stored keys (paginated)
 * GET  /api/traces/<key>  Bearer READ_TOKEN: fetch one stored record
 *
 * Uploaded scores are advisory only — the training pipeline
 * (training/human_data.py) replays every trace through the real engine and
 * recomputes the score before anything reaches a dataset.
 */

import policy from "../policy.json" with { type: "json" };

const ALLOWED_ORIGINS = new Set([
  "https://jamesbaker1.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
]);

const MAX_REQUEST_BYTES = 6_000_000;
const MAX_CANONICAL_BYTES = 2_000_000;
const MAX_INTERACTION_BYTES = 4_000_000;
const MAX_INTERACTION_EVENTS = 2500;
const CONSENT_VERSION = policy.consent_version;
const BACKGROUNDS = new Set(["lawyer", "legal_professional", "law_student", "other"]);
const MODES = new Set(["learn", "benchmark"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const INTERACTION_TYPE = /^(matter|document|search|selection|issue|redline|communication|counterparty|fact|final|capture|validation|transport)\.[a-z0-9_.-]+$/;

function validInteractionTrace(value, contributionId, matter, appVersion) {
  if (value == null) return true;
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > MAX_INTERACTION_BYTES) {
    return false;
  }
  if (
    typeof value !== "object" || value.schema_version !== "1" ||
    !UUID.test(value.session_id || "") || value.contribution_id !== contributionId ||
    value.matter_id !== matter || value.engine_version !== appVersion ||
    value.consent_version !== CONSENT_VERSION ||
    typeof value.started_at !== "string" ||
    (value.completed_at !== null && typeof value.completed_at !== "string") ||
    !Array.isArray(value.events) || value.events.length > MAX_INTERACTION_EVENTS
  ) return false;
  const ids = new Set();
  return value.events.every((event, index) => {
    if (!event || typeof event !== "object" || !UUID.test(event.event_id || "") ||
        ids.has(event.event_id) || event.sequence !== index + 1 ||
        typeof event.occurred_at !== "string" || !INTERACTION_TYPE.test(event.type || "") ||
        !event.target || typeof event.target !== "object" ||
        !event.data || typeof event.data !== "object" || Array.isArray(event.data) ||
        (event.duration_ms !== null && (!Number.isInteger(event.duration_ms) || event.duration_ms < 0))) {
      return false;
    }
    ids.add(event.event_id);
    return true;
  });
}

function cors(origin) {
  const allowed = ALLOWED_ORIGINS.has(origin) ? origin : "https://jamesbaker1.github.io";
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
  };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function authorized(request, env) {
  const header = request.headers.get("Authorization") || "";
  return env.READ_TOKEN && header === `Bearer ${env.READ_TOKEN}`;
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const headers = cors(origin);
    const url = new URL(request.url);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });

    if (request.method === "POST" && url.pathname === "/api/traces") {
      const text = await request.text();
      if (new TextEncoder().encode(text).byteLength > MAX_REQUEST_BYTES) {
        return json({ error: "too large" }, 413, headers);
      }
      let payload;
      try {
        payload = JSON.parse(text);
      } catch {
        return json({ error: "invalid json" }, 400, headers);
      }
      const trace = payload && payload.trace;
      const consent = payload && payload.consent;
      const contributionId = payload && payload.contribution_id;
      if (
        !trace ||
        typeof trace.matter !== "string" ||
        !/^[a-z0-9_]{1,64}$/.test(trace.matter) ||
        !Array.isArray(trace.events) ||
        trace.events.length === 0 ||
        trace.events.length > 200 ||
        typeof trace.result !== "object"
      ) {
        return json({ error: "not a playbook trace" }, 400, headers);
      }
      if (new TextEncoder().encode(JSON.stringify(trace)).byteLength > MAX_CANONICAL_BYTES) {
        return json({ error: "canonical trace too large" }, 413, headers);
      }
      if (!UUID.test(contributionId || "")) {
        return json({ error: "valid contribution_id is required" }, 400, headers);
      }
      if (
        !consent ||
        consent.version !== CONSENT_VERSION ||
        consent.training_and_evaluation !== true
      ) {
        return json({ error: "explicit current consent is required" }, 400, headers);
      }
      if (typeof payload.app_version !== "string" || !/^[0-9A-Za-z._-]{1,32}$/.test(payload.app_version)) {
        return json({ error: "valid app_version is required" }, 400, headers);
      }
      if (!validInteractionTrace(
        payload.interaction_trace, contributionId, trace.matter, payload.app_version
      )) {
        return json({ error: "invalid interaction trace" }, 400, headers);
      }
      if (payload.app != null && payload.app !== "web-gym") {
        return json({ error: "invalid contribution source" }, 400, headers);
      }
      const background = payload.background == null ? null : String(payload.background);
      if (background !== null && !BACKGROUNDS.has(background)) {
        return json({ error: "invalid professional background" }, 400, headers);
      }
      const mode = payload.mode == null ? null : String(payload.mode);
      if (mode !== null && !MODES.has(mode)) {
        return json({ error: "invalid play mode" }, 400, headers);
      }
      const handle = String(payload.handle || "")
        .replace(/[^\w .-]/g, "")
        .slice(0, 40);
      // Deterministic storage makes concurrent same-ID requests idempotent:
      // they can only overwrite the same record and always return the same key.
      const key = `trace:contribution:${contributionId}`;
      const record = {
        uploaded_at: new Date().toISOString(),
        agent: "human",
        handle: handle || null,
        app: payload.app || "web-gym",
        app_version: payload.app_version,
        mode,
        background,
        consent: {
          version: CONSENT_VERSION,
          training_and_evaluation: true,
          recorded_at: new Date().toISOString(),
        },
        claimed_score: trace.result.normalized_score ?? null,
        trace,
        contribution_id: contributionId,
        interaction_trace: payload.interaction_trace || null,
      };
      await env.TRACES.put(key, JSON.stringify(record));
      return json({ ok: true, key }, 200, headers);
    }

    if (request.method === "GET" && url.pathname === "/api/traces") {
      if (!authorized(request, env)) return json({ error: "unauthorized" }, 401, headers);
      const list = await env.TRACES.list({
        prefix: "trace:",
        cursor: url.searchParams.get("cursor") || undefined,
      });
      return json(
        { keys: list.keys.map((k) => k.name), cursor: list.list_complete ? null : list.cursor },
        200,
        headers
      );
    }

    if (request.method === "GET" && url.pathname.startsWith("/api/traces/")) {
      if (!authorized(request, env)) return json({ error: "unauthorized" }, 401, headers);
      const key = decodeURIComponent(url.pathname.slice("/api/traces/".length));
      const value = await env.TRACES.get(key);
      if (value === null) return json({ error: "not found" }, 404, headers);
      return new Response(value, {
        status: 200,
        headers: { "Content-Type": "application/json", ...headers },
      });
    }

    return json({ error: "not found" }, 404, headers);
  },
};
