# Playbook: a benchmark and training environment for multi-step legal work

*Technical report — pre-results draft. No model or human benchmark has been run or
reported here.*

## Abstract

Playbook is a partially observable, deterministic environment for evaluating and
training legal agents on multi-step work. This draft documents the environment and
evaluation protocol; it makes no empirical claim about model or human performance.

## 1. Motivation

Legal AI evaluation is dominated by static, single-turn tasks (classification,
extraction, QA). But legal work is a *process*: gathering facts under budget,
following client instructions, deciding what to escalate, drafting operative
language, and never fabricating authority. Playbook models that process as a
partially observable environment with deterministic, expert-authored scoring —
the design pattern (policy-constrained agents, hidden state, verifiable rewards)
that produced useful agent benchmarks in other domains, instantiated for
technology-transactions practice.

## 2. Environment design

Summarize [architecture](architecture.md) + [environment API](environment.md):
matter packages, nine actions exposed as tool calls (two only when a matter has a
counterparty), budgets, observation
hygiene (no hidden state, no scoring detail agent-side).

## 3. The scoring contract

Summarize [scoring](scoring.md): anchor-based issue matching (no rubric-ID
guessing), concept-matched free-text client questions, verbatim quote
verification as a fabrication gate, critical-failure caps, derived max score.
State the anti-gaming invariants and that they are enforced as CI tests.

## 4. The matter corpus

12 public dev matters + 6 private held-out matters, all synthetic, canary-tagged,
lint-enforced, each shipping a validated reference trajectory (≥ 0.7; the lowest
public reference replay is 0.9375) and
adversarial trajectories that must trip the gates. Table of matters with their
structural variations (exhibit traps, amendment cross-referencing, role flip,
hidden severity pivots, regulatory framing, divergent vocabulary in the held-out
set).

## 5. Baseline results

No model or human baseline results are available. Results should be added only from
saved, reproducible scorecards that identify the `dev` or `held-out` split. Reference
trajectory replays validate authored matters and the scorecard pipeline; they are not
model benchmark results.

The [baseline sprint runbook](baseline-sprint.md) generates a measured, paste-ready table
with the dev-to-held-out delta and the required escalation, over-escalation, settlement,
and `nego_saas_010` trap-counter checks. This section must only be replaced from that
generated artifact; no placeholder or estimated scores belong here.

## 6. Training experiments

No training experiment results are available. A future report must state the rollout
corpus, training method, pre-registered metric, adversarial re-test, and held-out delta.

## 7. Limitations

- Deterministic concept/anchor scoring measures *coverage of the expert answer*,
  not persuasive quality of prose; drafting nuance needs the planned judge layer.
- Twelve public matters principally cover technology transactions, with two synthetic
  M&A matters adding a second practice area; the small corpus cannot establish broad
  performance across either practice area.
- Public matters must be presumed contaminated after publication; the held-out
  set is small.
- Synthetic paper is simplified relative to real negotiated agreements.

## 8. Ethics and provenance

All content synthetic; no confidential materials, employer playbooks, or
privileged work product; canary strings for contamination detection; not legal
advice. Environment outputs are research artifacts, not counsel.

## Appendix

Future result-bearing revisions should include full scorecards, per-matter rubric
summaries, and reproduction commands (`playbook-bench` invocations, split, seeds,
model versions, and dates).
