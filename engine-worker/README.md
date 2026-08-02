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

`vendor.py` copies the canonical package and matter directories into ignored deployment folders.
Run it again whenever engine code or matters change. Deploy with `uv run pywrangler deploy` only after
tests and an authenticated staging check pass.

Configure `ALLOWED_ORIGIN` in `wrangler.toml` for the GitHub Pages origin. Production secrets or
environment-specific values should be configured in Cloudflare rather than committed.

## API

- `GET /api/health`
- `GET /api/matters`
- `POST /api/start` with `{ "matter_id": "ai_saas_001", "seed": 0 }`
- `POST /api/step` with `{ "matter_id": "ai_saas_001", "seed": 0, "actions": [...] }`

Nonterminal responses deliberately omit rewards and rubric details, preventing the public gym from
becoming a scoring oracle. Terminal responses include the complete canonical trace and episode result
for feedback and explicitly consented contribution. Public Workers must contain synthetic practice
matters only; sealed evaluation matters belong in a separate private deployment.
