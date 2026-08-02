# Playbook

**Train legal agents on the work, not just the law.**

[![CI](https://github.com/jamesbaker1/playbook/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesbaker1/playbook/actions/workflows/ci.yml)

Playbook is a gym for legal agents: partially observable, rubric-scored environments
for evaluating and training AI on realistic, multi-step legal work. An agent receives
a matter file, documents, professional instructions, and a client negotiation
playbook. It must inspect the record, ask a limited number of client questions,
identify material issues, propose redlines, escalate what exceeds its authority,
negotiate against a scripted counterparty where the matter has one, and submit a final
summary. Every action is scored by deterministic verifiers against expert-authored
rubrics, and every episode produces a complete audit trace usable as training data.

Existing legal benchmarks test static, single-turn tasks. Playbook tests the
*process* of legal work: fact gathering under budget, playbook compliance, escalation
judgment, negotiation under a concession playbook, citation-grounded analysis, and
drafting — the same design pattern that made policy-constrained agent benchmarks work
in other domains.

**Play it yourself:** [jamesbaker1.github.io/playbook](https://jamesbaker1.github.io/playbook/)
— the web gym uses the canonical scoring engine through a dedicated Cloudflare
service, under the same budgets and scoring gates the models face. Its action controls
are driven by the engine contract, including escalation and scripted negotiation when
a matter publishes them. The interface uses a
familiar legal-workspace model: matter file on the left, document in the center,
and structured review actions on the right. On mobile, a bottom bar switches among
Matter, Document, Work, Issues, and Activity without losing drafts. See the
[web-gym guide](docs/web-gym.md).

## The v0.3 scoring contract

Credit is earned by **content**, never by guessing rubric internals:

- **Issues** are credited by the operative provision they cite (each rubric issue has
  a unique *anchor* citation; your first citation decides the match).
- **Client questions** are free text, matched by concepts; every question consumes
  budget whether or not it lands.
- **Quotations** are verified verbatim against the cited section. A fabricated quote
  is a **critical failure** that caps the episode score — polish cannot rescue
  fabrication.
- **Escalations** (`escalate`) are free text too, budgeted and concept-matched. A
  matched one returns the supervisor's hidden guidance; over-escalating is penalized,
  and a required escalation that never happened is settled up at final submission.
- **Negotiation** (`send_markup`, `accept_counterparty`) is answered by a
  deterministic scripted counterparty that accepts, counters, or refuses. What is
  scored is the language a point actually *closed on* — conceding a non-negotiable, or
  accepting a plausible-sounding trap counter, trips the critical gate.
- Scoring detail never appears in agent-visible observations, so the rubric cannot
  be probed mid-episode.
- Given the same matter, seed, and actions, everything is deterministic — the
  counterparty included.

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
| `playbook-baseline-sprint --models ...` | Plan or run the budget-gated, split-labeled baseline sprint |
| `playbook-render <trace> <out.html>` | Render a trace as an HTML audit report |
| `playbook-export <trace> <out.jsonl>` | Convert a trace to chat-format SFT data |

## Web gym

The hosted gym is both a demonstration and a human-data interface. Its lightweight
browser client sends the matter ID and action history to a Cloudflare Python Worker,
which reconstructs the episode with the same `playbook_legal` package used by the CLI.
The browser never receives rubrics, hidden facts, or scorer source, and does not
reimplement the reward engine.

Users choose Learn mode for workflow guidance or Benchmark mode for a sealed attempt
without hints or pre-submit warnings. Submitted issues become persistent work-product cards. From each card, a reviewer can
reopen cited evidence or start a linked redline. Before final submission, a preflight
shows sections reviewed, questions used, issues submitted, draft coverage, and remaining
steps. These are workflow warnings, not legal-quality judgments.

An unfinished review is saved on that device after every accepted step as its matter ID,
seed, and action sequence. On return, the browser offers to resume by deterministically
replaying that exact sequence through the scoring service. Finishing, discarding, or
replacing the review clears the saved episode. Learned client and supervisor facts stay
visible beneath the document list; questions and searches open Activity, while submitted
issues and redlines open Review.

Review actions are processed by the scoring service. Completed traces are uploaded to
the separate training-data collector only if the user explicitly chooses
**contribute trace** and records explicit, versioned training consent. The ingestion
pipeline preserves non-identifying provenance, replays every trace, and rejects
records that are incomplete or do not reproduce their claimed result. Optional
handles remain in raw storage and are excluded from training exports. See [Using the web gym](docs/web-gym.md) and
[the Worker deployment notes](web/worker/README.md).

## Matters

Twelve public development matters (all synthetic; each carries a contamination canary
string), varied by document architecture, role, leverage, and hidden-fact pivots:

| Matter | Scenario | What it tests |
| --- | --- | --- |
| `ai_saas_001` | AI SaaS MSA + DPA, customer side | Model-training rights, incident notice, liability supercap |
| `cloud_msa_002` | Enterprise cloud platform | Key terms hidden in a security exhibit; data residency |
| `saas_renewal_003` | Renewal amendment | A buried SLA-credit deletion; cross-document reading |
| `msa_provider_004` | Provider-side markup response | Accept/counter/escalate judgment under a concession playbook |
| `ml_services_005` | Custom ML development | IP allocation, background-technology trap, acceptance gates |
| `health_saas_006` | Wellness-benefits platform | A hidden biometric fact that changes severity calls |
| `fintech_vendor_007` | Regulated fintech vendor | Regulatory framing, exam access, flow-down obligations |
| `source_license_008` | Inbound SDK license | GPLv3/copyleft analysis without the classic overclaim |
| `clean_msa_009` | A compliant renewal — the paper is fine | False-positive discipline: the right answer is "no material issues" |
| `nego_saas_010` | Live negotiation vs. scripted counterparty | Standing firm on non-negotiables, authorized concessions, escalation under pressure |
| `public_merger_target_011` | Public-target merger markup, target side | MAE carveouts, board matching rights, ordinary-course control, fee-tail traps |
| `private_acquisition_buyer_012` | Private-target acquisition, buyer side | Knowledge inquiry plus deductible, cap, and survival allocation |

Private held-out evaluation matters live in a separate private repository so
published models can be scored on unseen work. Every matter ships a validated
reference trajectory and adversarial bad trajectories in `examples/<matter_id>/`,
enforced by CI (reference ≥ 0.7 with no critical failure; fabricated-quote and
reversed-redline trajectories must trip the critical gate).

## Repository map

```text
src/playbook_legal/       Environment, scoring, schemas, linter, baseline, bench
compiler/                 Matter-compilation pipeline and validation tools
matters/                  Public synthetic matters (dev split)
examples/<matter_id>/     Reference + adversarial trajectories per matter
web/                      Lightweight GitHub Pages client for the web gym
engine-worker/            Canonical Python scoring API for Cloudflare Workers
training/                 Modal-ready SFT / DPO / GRPO scaffolds (never auto-run)
tests/                    Environment, scoring, adversarial, lint, baseline tests
docs/                     Architecture, environment API, scoring, evaluation, report
SPEC.md                   Technical specification (v0.3 contract)
AUTHORING.md              How to author and validate a matter
ROADMAP.md                Build plan and status
```

Deeper reading: [web gym](docs/web-gym.md) · [architecture](docs/architecture.md) ·
[environment API](docs/environment.md) · [scoring in depth](docs/scoring.md) ·
[evaluation](docs/evaluation.md) · [contributing](CONTRIBUTING.md)

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

## License

Copyright © 2026 James Baker.

Playbook is open-source software under the
[GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-only`). If you modify
Playbook and make that modified version available to users over a network, the AGPL
generally requires you to offer those users the corresponding source under the same
license.

Organizations that need proprietary integration, private modifications, redistribution
under different terms, warranty terms, or other exceptions may obtain a separate
commercial license. See [Commercial licensing](COMMERCIAL-LICENSING.md) or contact
[jamesbaker2019@gmail.com](mailto:jamesbaker2019@gmail.com).

Versions previously released under Apache-2.0 remain available under the license that
applied to those versions.
