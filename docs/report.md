# Playbook: a benchmark and training environment for multi-step legal work

*Technical report — draft skeleton. Sections marked ▢ await experimental results.*

## Abstract

▢ One paragraph after baselines: the environment, the contract, N models compared,
the headline finding (expected shape: strong issue-spotting, weaker fact-gathering
discipline and fabrication avoidance under pressure), and the held-out result.

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
matter packages, six actions exposed as tool calls, budgets, observation
hygiene (no hidden state, no scoring detail agent-side).

## 3. The scoring contract

Summarize [scoring](scoring.md): anchor-based issue matching (no rubric-ID
guessing), concept-matched free-text client questions, verbatim quote
verification as a fabrication gate, critical-failure caps, derived max score.
State the anti-gaming invariants and that they are enforced as CI tests.

## 4. The matter corpus

8 public dev matters + 2 private held-out matters, all synthetic, canary-tagged,
lint-enforced, each shipping a validated reference trajectory (≥ 0.97) and
adversarial trajectories that must trip the gates. Table of matters with their
structural variations (exhibit traps, amendment cross-referencing, role flip,
hidden severity pivots, regulatory framing, divergent vocabulary in the held-out
set).

## 5. Baseline results

▢ Scorecard table: models × SPEC §10 metrics on the public dev split.
▢ Same table on the private held-out split.
▢ Human baseline: at least one attorney playing under the same budgets.
▢ Failure-mode analysis: where do models lose points — question discipline,
   severity calibration, quote fabrication, protocol failures?

## 6. Training experiments

▢ Rollout generation stats; SFT (LoRA) on filtered high-scoring trajectories;
DPO on within-matter pairs; whether GRPO with the environment-owned reward was
run and what the adversarial re-testing showed. Pre-registered metric and the
held-out delta.

## 7. Limitations

- Deterministic concept/anchor scoring measures *coverage of the expert answer*,
  not persuasive quality of prose; drafting nuance needs the planned judge layer.
- Ten matters cover one practice area (technology transactions), one side of the
  v0.2 contract's assumptions (single-round review, no counterparty simulator).
- Public matters must be presumed contaminated after publication; the held-out
  set is small.
- Synthetic paper is simplified relative to real negotiated agreements.

## 8. Ethics and provenance

All content synthetic; no confidential materials, employer playbooks, or
privileged work product; canary strings for contamination detection; not legal
advice. Environment outputs are research artifacts, not counsel.

## Appendix

▢ Full scorecards, per-matter rubrics summary, reproduction commands
(`playbook-bench` invocations, seeds, model versions, dates).
