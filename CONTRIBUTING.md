# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

CI runs `ruff check src tests training`, `pytest`, and `playbook-lint --all
matters` on Python 3.11 and 3.12. All three must pass.

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

## License

Apache-2.0. By contributing you agree your contribution is licensed under the
project license.
