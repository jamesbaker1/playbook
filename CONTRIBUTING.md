# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

CI runs `ruff check src tests training compiler web`, `python engine-worker/vendor.py
--check`, `pytest`, and `playbook-lint --all matters` on Python 3.11 and 3.12. All
four must pass. `make lint` runs the identical ruff scope plus the same matter lint,
so a clean `make lint` covers CI's lint steps exactly — `web` included; keep it that
way. A second CI job runs the web unit tests on Node 20 with `node --test
tests/api_base.test.js tests/capture.test.js tests/citation_helpers.test.js
tests/draft_store.test.js tests/score_helpers.test.js`.

## Contributing a matter

Matters are the most valuable contribution. Read [AUTHORING.md](AUTHORING.md)
first — it is the contract. In short:

1. Author `matters/<id>/` (matter.yaml, rubric.yaml, hidden_facts.yaml,
   documents/) and `examples/<id>/` (good.jsonl + at least one bad_*.jsonl).
2. `playbook-lint matters/<id>` must pass with zero errors.
3. `playbook-eval matters/<id> examples/<id>/good.jsonl` must score ≥ 0.7
   normalized, terminated, no critical failure.
4. Bad trajectories must score below good; files named `bad_critical_*` or
   containing `fabricated` must trip the critical gate.
5. `pytest` — the parametrized example tests pick up new matters automatically.

Matter content rules (non-negotiable): synthetic only — no confidential client
materials, employer playbooks, privileged work product, or recognizable
reconstructed matters. Include the provenance block and the canary line. Content
must be plausible, simplified U.S. tech-transactions substance; it is not legal
advice and should not read like any identifiable firm's form.

## Contributing code

- Match the existing style: typed, `from __future__ import annotations`,
  ruff line length 100. Comments only for non-obvious constraints.
- Scoring changes need adversarial tests: if you add a reward component, add the
  test that shows how gaming it fails.
- The observation contract is load-bearing: nothing rubric- or hidden-state-
  derived may enter agent-visible observations. `test_adversarial.py` enforces
  this; extend it if you extend observations.
- Determinism is non-negotiable in the environment and reward engine (no clocks,
  no RNG outside the seeded generator).

## Working on the web gym

The site under `web/` is deliberately dependency-light static HTML, CSS, and
JavaScript. The canonical environment runs in `engine-worker/`. Preserve these boundaries:

- Do not duplicate scoring or matter logic in JavaScript. Browser actions must go
  through the versioned Worker API and `PlaybookEnv`.
- Never add Python package source, matters, rubrics, hidden facts, or a Pyodide
  runtime to the Pages build. `tests/test_web_bundle.py` enforces this boundary.
- Preserve drafts when users change tabs or mobile panes. Starting a new matter is
  the point at which forms and local workspace state reset.
- Desktop uses a matter/document/work-product layout. At widths up to 980px, only
  one workspace surface should be exposed at a time through the mobile navigation.
- New controls need keyboard operation, visible focus, plain-language labels, and
  effective touch targets of at least 44 CSS pixels.
- Final submission is irreversible and must continue to use the in-page preflight.
- Keep technical boot output collapsed by default; runtime transparency should not
  displace the task interface.

Build and validate the exact GitHub Pages bundle with:

```bash
python web/build_site.py dist
python -m pytest -q tests/test_web_bundle.py
python -m pytest -q tests/test_engine_worker.py
node --check web/app.js
node --check web/contribute.js
```

Manual browser checks should include 320×568, 390×844, and 768×1024 viewports,
keyboard-only use, switching every mobile pane with partially completed forms, an
invalid issue/redline submission, and final-preflight cancellation.

### Local web gym

Run the static site and engine Worker in separate terminals from the repository root:

```bash
cd web
python -m http.server 8000
```

```bash
cd engine-worker
python vendor.py
npx wrangler dev
```

Then open
`http://localhost:8000/?api=http%3A%2F%2Flocalhost%3A8787`. The static server is
on port 8000 and the local Worker API is on port 8787. The engine's CORS policy
accepts both `http://localhost:8000` and `http://127.0.0.1:8000`; keep the hostname
consistent in the page URL and `api` value when substituting `127.0.0.1`.

The `api` query parameter has precedence over the browser-local setting, which in
turn has precedence over the production endpoint. To use the local Worker without
keeping the query parameter, set the origin-only URL in the browser console:

```js
localStorage.setItem("playbook.api-base.v1", "http://localhost:8787")
```

Remove it with `localStorage.removeItem("playbook.api-base.v1")` to return to the
production Worker. Only an `http` or `https` origin is accepted: credentials,
paths, query strings, and fragments are rejected.

Prepare the Worker bundle with `python engine-worker/vendor.py`. Deploy the Worker
before deploying a frontend that requires a new API contract. Run the direct-engine
parity tests before every Worker deployment; the Pages client and Worker deploy
independently and must report compatible engine versions.

## Human trace contributions

Trace upload is opt-in and implemented separately in `web/contribute.js`. The public
POST endpoint accepts anonymous traces plus an optional handle. Administrative reads
require the Worker's `READ_TOKEN`; never put that secret or `.wrangler/` state in Git.

Download, replay, and export candidate traces with `training/human_data.py`. Uploaded
scores are untrusted: the verifier reconstructs the matter episode, replays every
action, and retains only traces whose score and critical-failure status reproduce.
See [web/worker/README.md](web/worker/README.md) for deployment and secret setup.

## License

AGPL-3.0-only. By contributing you agree your contribution is licensed under the
project license and that the project owner may also offer the contribution as part
of Playbook under separate commercial terms. Do not contribute code you do not have
the authority to license on that basis.
