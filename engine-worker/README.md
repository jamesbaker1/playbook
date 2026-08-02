# Playbook engine Worker

This package runs the canonical Python `PlaybookEnv` behind a stateless Cloudflare Worker API.
The browser sends the complete action history on each step; the Worker reconstructs and replays
the episode, so no database or session state is required.

## Prepare and run

From the repository root:

```powershell
python engine-worker/vendor.py
cd engine-worker
uv sync
uv run pywrangler dev
```

`vendor.py` copies the canonical package and matter directories into tracked deployment folders.
Run it whenever engine code or matters change and commit the resulting bundle. Deploy with
`uv run pywrangler deploy` only after tests and an authenticated staging check pass.

Run `python engine-worker/vendor.py --check` to fail if either tracked deployment copy is
missing, stale, or contains extra files. CI performs this parity check without regenerating the
bundle, so a stale commit fails rather than being silently repaired.

Configure `ALLOWED_ORIGIN` in `wrangler.toml` for the GitHub Pages origin. Production secrets or
environment-specific values should be configured in Cloudflare rather than committed.

## API

- `GET /api/health`
- `GET /api/matters`
- `POST /api/start` with `{ "matter_id": "ai_saas_001", "seed": 0 }`
- `POST /api/step` with `{ "matter_id": "ai_saas_001", "seed": 0, "actions": [...] }`

Nonterminal responses deliberately omit rewards and rubric details, preventing the public gym from
becoming a live scoring oracle. Terminal responses include the complete canonical trace and episode
result, including criterion-level audit detail, for useful feedback and explicitly consented
contribution. This is intentional only because the public synthetic matters are the assumed-
contaminated development split: web-gym scores are practice feedback, not benchmark results. Public
Workers must contain synthetic development matters only; sealed evaluation matters and reportable
benchmark runs belong in a separate private deployment that does not expose terminal traces.
