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

const ALLOWED_ORIGINS = new Set([
  "https://jamesbaker1.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
]);

const MAX_BYTES = 2_000_000;
const CONSENT_VERSION = "2026-08-01";
const BACKGROUNDS = new Set(["lawyer", "legal_professional", "law_student", "other"]);
const MODES = new Set(["learn", "benchmark"]);

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
      if (text.length > MAX_BYTES) return json({ error: "too large" }, 413, headers);
      let payload;
      try {
        payload = JSON.parse(text);
      } catch {
        return json({ error: "invalid json" }, 400, headers);
      }
      const trace = payload && payload.trace;
      const consent = payload && payload.consent;
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
      const key = `trace:${trace.matter}:${Date.now()}:${crypto.randomUUID()}`;
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
