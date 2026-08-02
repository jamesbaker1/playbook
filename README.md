# Playbook

**Train legal agents on the work, not just the law.**

[![CI](https://github.com/jamesbaker1/playbook/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesbaker1/playbook/actions/workflows/ci.yml)

Playbook is a gym for legal agents: partially observable, rubric-scored environments
for evaluating and training AI on realistic, multi-step legal work. An agent receives
a matter file, documents, professional instructions, and a client negotiation
playbook. It must inspect the record, ask a limited number of client questions,
identify material issues, propose redlines, and submit a final summary. Every action
is scored by deterministic verifiers against expert-authored rubrics, and every
episode produces a complete audit trace usable as training data.

Existing legal benchmarks test static, single-turn tasks. Playbook tests the
*process* of legal work: fact gathering under budget, playbook compliance, escalation
judgment, citation-grounded analysis, and drafting — the same design pattern that
made policy-constrained agent benchmarks work in other domains.

## The v0.2 scoring contract

Credit is earned by **content**, never by guessing rubric internals:

- **Issues** are credited by the operative provision they cite (each rubric issue has
  a unique *anchor* citation; your first citation decides the match).
- **Client questions** are free text, matched by concepts; every question consumes
  budget whether or not it lands.
- **Quotations** are verified verbatim against the cited section. A fabricated quote
  is a **critical failure** that caps the episode score — polish cannot rescue
  fabrication.
- Scoring detail never appears in agent-visible observations, so the rubric cannot
  be probed mid-episode.
- Given the same matter, seed, and actions, everything is deterministic.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # environment, scoring, adversarial, and example tests
python -m playbook_legal.demo   # scripted episode with full score breakdown
```

## Core API

```python
from playbook_legal import PlaybookEnv

env = PlaybookEnv.from_directory("matters/ai_saas_001")
observation, info = env.reset(seed=7)
observation, reward, terminated, truncated, info = env.step({
    "type": "ask_client",
    "question": "Is there a fixed launch deadline affecting negotiation leverage?",
})
```

`step()` follows the Gymnasium shape. Actions are also exposed as OpenAI-compatible
tool definitions (`playbook_legal.tool_definitions()`), so any chat model with
function calling can play the environment via the baseline runner.

## Command-line tools

| Command | Purpose |
| --- | --- |
| `playbook-demo` | Run the scripted reference episode |
| `playbook-eval <matter> <actions.jsonl>` | Replay an action file and print the score |
| `playbook-lint --all matters` | Validate matter packages (anchors, citations, canary) |
| `playbook-baseline <matter> --model <m>` | Let an OpenAI-compatible model play a matter |
| `playbook-bench --runner replay\|baseline` | Score a runner across all matters → scorecard |
| `playbook-render <trace> <out.html>` | Render a trace as an HTML audit report |
| `playbook-export <trace> <out.jsonl>` | Convert a trace to chat-format SFT data |

## Matters

Public development matters live in `matters/` (all synthetic; each carries a
contamination canary string). Private held-out evaluation matters live in a separate
private repository so published models can be scored on unseen work. Every matter
ships a validated reference trajectory and adversarial bad trajectories in
`examples/<matter_id>/`, enforced by CI.

## Repository map

```text
src/playbook_legal/       Environment, scoring, schemas, linter, baseline, bench
matters/                  Public synthetic matters (dev split)
examples/<matter_id>/     Reference + adversarial trajectories per matter
training/                 Modal-ready SFT / DPO / GRPO scaffolds (never auto-run)
tests/                    Environment, scoring, adversarial, lint, baseline tests
SPEC.md                   Technical specification (v0.2 contract)
AUTHORING.md              How to author and validate a matter
ROADMAP.md                Build plan and status
```

## Design principles

1. **Score actions, not prose similarity.**
2. **Separate hidden state from agent observations.**
3. **Use deterministic verifiers first; add judges only where verifiers cannot reach.**
4. **Treat critical legal failures as gates, not small average penalties.**
5. **Make the reward un-gameable before making it bigger** (anti-gaming tests in CI).
6. **Log every action for auditability and training-data generation.**
7. **Keep public evaluation matters separate from private held-out matters.**
8. **Use only synthetic, licensed, or clearly public source materials.**

All matter content is synthetic and intentionally simplified. It is not legal advice.
