# Playbook: a benchmark and training environment for multi-step legal work

*Technical report — environment and protocol, with a measured dev-split baseline.
Model baseline results exist; [`docs/baseline-report.md`](baseline-report.md) is
their canonical write-up and this report reproduces only its summary table. No
human baseline has been run.*

## Abstract

Playbook is a partially observable, deterministic environment for evaluating and
training legal agents on multi-step work. This report documents the environment
and evaluation protocol, and summarizes the measured v0.4.0 baseline on the
twelve-matter public development split (§5). Held-out and human baselines have
not been run.

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

12 public dev matters plus a private held-out corpus under construction, all
synthetic, canary-tagged, lint-enforced, each shipping a validated reference
trajectory (≥ 0.7; the lowest public reference replay is 0.9375) and
adversarial trajectories that must trip the gates. Table of matters with their
structural variations (exhibit traps, amendment cross-referencing, role flip,
hidden severity pivots, regulatory framing, divergent vocabulary in the held-out
set).

The held-out corpus is not yet complete. The frozen experiment contract
(`docs/playbook-1-experiment.yaml`) targets 15-30 sealed families yielding
50-100 evaluation episodes, with ten reviewed families as the interim floor for
a first evaluation. As of 2026-08-08 six families are owner-reviewed; five more
are drafted and blocked at adversarial pre-review. Held-out results should not
be reported until at least the interim floor is cleared.

## 5. Baseline results

Measured model baselines exist for the **public development split only**. The
canonical write-up, with per-model discussion and the full caveat list, is
[`docs/baseline-report.md`](baseline-report.md); the table below is copied
unchanged from `results/v0.4.0/comparison.md`. No held-out and no human baseline
results are available.

### Playbook baseline comparison — 12 public matters (dev split)

| Model | Episodes | Score | Critical rate | Citation validity | Issue recall | Question recall | Unsupported/ep | Steps | Completion | Critical 95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Expert reference (replay) | 12 | 0.985 | 0.000 | 1.000 | 0.917 | 0.958 | 0.000 | 22.600 | 1.000 | — |
| Claude Haiku 4.5 | 12 | 0.336 | 0.250 | 0.688 | 0.583 | 0.083 | 1.667 | 15.600 | 1.000 | [0.000, 0.500] |
| GPT-5.6-terra | 12 | 0.474 | 0.000 | 1.000 | 0.583 | 0.056 | 0.000 | 30.200 | 1.000 | [0.000, 0.000] |
| Qwen2.5-32B-Instruct | 12 | 0.076 | 0.250 | 1.000 | 0.208 | 0.000 | 0.917 | 8.500 | 1.000 | [0.000, 0.500] |
| Qwen2.5-14B-Instruct | 36 | 0.165 | 0.139 | 1.000 | 0.312 | 0.000 | 0.417 | 8.200 | 1.000 | [0.000, 0.333] |
| Qwen2.5-7B-Instruct | 36 | 0.031 | 0.056 | 0.972 | 0.106 | 0.021 | 1.111 | 11.000 | 0.972 | [0.000, 0.139] |

Pooled means over all episodes per model; 32B pools a single seed. Critical-failure CI is a 95% cluster bootstrap resampled by matter family.

Two caveats bind every row above:

- **Pre-revision gates.** All rows were measured under the pre-revision
  critical-failure gates. A subsequent adversarial audit found and fixed
  regex false-positive and false-negative surfaces in those gates; it could not
  determine whether any *measured* critical failure was a phrasing artifact,
  only that the instrument could not rule it out. Critical rates measured after
  the revision are not numerically comparable to this table without a re-run.
- **Single seed.** The 32B row and both frontier rows pool a single seed
  (12 episodes each); the 7B and 14B rows pool three seeds (36 episodes). Single-seed
  rows are indicative, not settled.

Reference trajectory replays validate authored matters and the scorecard pipeline;
they are not model benchmark results. Any addition to this section must come from
saved, reproducible scorecards that identify the `dev` or `held-out` split. The
[baseline sprint runbook](baseline-sprint.md) generates a measured, paste-ready table
with the dev-to-held-out delta and the required escalation, over-escalation, settlement,
and `nego_saas_010` trap-counter checks; no placeholder or estimated scores belong here.

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
