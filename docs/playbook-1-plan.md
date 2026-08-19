# Playbook-1 plan

*Working plan for turning the Playbook environment into a post-trained legal
workflow model. This complements `ROADMAP.md` and `docs/plan-2026-08.md`; those
documents remain the product and release ledgers.*

## Goal

Build **Playbook-1**, a post-trained transactional legal-workflow model, and
test the following claim:

> A base model post-trained on Playbook trajectories makes better process-level
> legal decisions on unseen synthetic matter families than the same base model
> trained only on final legal outputs.

Playbook-1 is not a legal foundation model. It is a narrow workflow policy for
transactional review and negotiation under client-specific authority
constraints. It should learn what professional action to take next: inspect,
search, ask, identify, draft, escalate, negotiate, or finish.

## Current position

> **Implementation update (2026-08-06, evening):** v0.4.0 shipped. Measured
> dev-split baselines are published for Qwen2.5-7B/14B/32B against the 0.985
> reference-replay ceiling (best model 0.165; critical-failure rate rising
> with scale; see `results/v0.4.0/` and `docs/baseline-report.md`). The
> variant catalog holds 12 training families / 42 variants. The rollout-yield
> pilot validated the generate→filter→dataset pipeline end to end and
> rejected Qwen2.5-32B as teacher (0/8 above a 0.5 score bar), adding the
> minimum-score filter to Workstream 4. The owner approved
> Qwen/Qwen2.5-14B-Instruct as the student base; the teacher choice and paid
> budget remain open. The sealed private corpus holds six verified held-out
> families against the frozen contract target of 15-30 families (ten reviewed
> families is the interim floor for a first evaluation). The binding constraints are now the
> teacher choice, qualified review capacity, and sealed-corpus completion.

The repository already has the core environment needed for the experiment:

- deterministic scoring, traces, and replay;
- issue, citation, question, escalation, and negotiation mechanics;
- critical-failure and reward-gaming gates;
- complete-trajectory export plus SFT, DPO, and GRPO scaffolds;
- twelve public matters and six private held-out matters;
- consent-gated, replay-verified human trace collection;
- a synthetic compiler Phase A self-test; and
- baseline and scorecard tooling.

The limiting factors are evidence and data, not the basic environment:

- model baselines are published for the dev split only; no held-out or human
  baselines exist yet;
- no viable teacher has been identified (the 32B pilot failed the score bar);
- the current human SFT artifact contains only one record;
- qualified legal review capacity has not been named or budgeted; and
- the sealed corpus holds six families against the frozen contract target of
  15-30 families and 50-100 evaluation episodes, and against the ten-reviewed-family
  interim floor for a first evaluation.

## Experiment contract

Freeze the experiment before generating or reviewing training data.

### Scope

- Domain: transactional technology agreements.
- Base: one open-weight instruct model in the 7B-14B range, selected for
  reliable native function calling and at least a 32k context window (the
  action contract requires structured tool calls over multi-document matters).
- Initial capabilities: issue spotting, factual-question selection,
  escalation, redline choice, and negotiation under authority constraints.
- Training: LoRA SFT first, decision-level DPO second.
- Online RL: explicitly out of scope until SFT/DPO results and adversarial
  retesting justify it.
- Continued pretraining: optional future work, not required for Playbook-1.

### Required model comparison

1. Unmodified base model.
2. Final-answer-only distillation using outputs from the same open-weight teacher.
3. Playbook state-action distillation using trajectories from that teacher.
4. State-action distillation plus decision-level DPO, if the SFT result clears
   its gate.
5. The larger open-weight teacher as an external reference.
6. One strong API model as an optional external reference, not a training
   control.

The two distilled SFT conditions must use the same teacher, matched
training-token budgets, and comparable hyperparameter selection. This prevents
teacher quality, a larger dataset, or a larger compute budget from being
mistaken for evidence that process supervision works.

State-action SFT must also outperform the unmodified base model on the primary
metric, and per-condition protocol-failure rates must be reported. Final-answer
SFT can degrade the base model's tool-calling behavior; without the base
comparison and protocol-failure reporting, a trajectory-SFT "win" could reflect
a broken control rather than better process decisions.

### Initial execution strategy: teacher to student

The first Playbook-1 training run should distill a capable, larger open-weight
instruct model into a smaller open-weight student. The teacher generates
multiple candidate trajectories inside Playbook; protocol failures,
non-reproducible traces, and critical failures are rejected; and a qualified
reviewer approves or corrects the actions selected for positive training data.

This stage tests whether Playbook can generate, validate, and transfer useful
workflow supervision. It does **not** by itself establish that reinforcement
learning works: an improved student may simply be imitating a stronger model.
The first controlled result is therefore state-action distillation versus
matched final-answer-only distillation. A separate, subsequent comparison of
the state-action student before and after decision-level DPO or
environment-guided RL is required to attribute additional gains to environment
feedback.

The initial model should be described as a **Playbook-distilled workflow
model** until that post-distillation comparison clears the preregistered gates.
Online RL remains out of scope for the first result; decision-level DPO is the
preferred lower-risk test of environment-derived preferences.

### Metrics

Choose one primary process metric before training. The recommended primary
metric is **critical-failure rate**, with prohibited-concession rate reported
separately where negotiation is available.

Secondary metrics:

- material-issue and required-issue recall;
- false-positive and unsupported-issue counts;
- citation validity and fabricated-evidence rate;
- client-question recall and efficiency;
- escalation precision, recall, and over-escalation;
- settled-issue ratio and successful negotiation closure;
- completion rate and normalized score.

Report uncertainty across matter families rather than treating correlated
variants or individual actions as independent observations.

### Success gate

Trajectory SFT must outperform final-answer-only SFT on the preregistered
primary process metric on sealed matter families without materially degrading
citation validity, fabricated-evidence rate, or completion. Any regression in a
critical safety gate blocks release regardless of mean score.

### Preregistered decision rule

The primary comparison is judged on the family-clustered uncertainty interval,
not the point estimate alone: state-action SFT beats final-answer SFT only if
the one-sided 95% cluster-bootstrap confidence interval (resampled by matter
family) for the difference in critical-failure rate excludes zero. Safety-gate
regressions are judged against the same clustered intervals. Because
critical-failure rate is a rare-event metric, sealed evaluation families must
be designed with enough temptation density — traps, prohibited concessions,
escalation pressure — that the unmodified base model's critical-failure rate is
well off the floor; a floor-effect metric cannot demonstrate improvement.
The frozen contract (`docs/playbook-1-experiment.yaml`, authoritative) targets
15-30 sealed families and the top of the 50-100 episode range; ten reviewed
families is the interim floor at which a first evaluation may run.

## Workstream 1: dataset representations

Add a versioned dataset builder with three output views:

1. **Final answer:** initial matter context to final work product.
2. **Trajectory chat:** the existing complete episode representation.
3. **State action:** the observation before an action, the available action
   schemas, and the selected action.

Each state-action record should carry non-prompt metadata for:

- matter and matter-family identifiers;
- selected action and resulting observation;
- score components and critical-failure status;
- source, license/consent, reviewer, and review status;
- split, generator version, and content hashes.

The resulting observation, reward, and reason must never appear in the policy
input used to predict that action. They may be retained as metadata or used as
critic targets.

### Acceptance

- Every action is paired with the immediately preceding observation.
- No outcome text leaks into the policy prompt.
- No held-out family appears in a training artifact.
- Generation is deterministic and produces a manifest with file hashes.
- Tests cover first-action alignment, intermediate actions, terminal actions,
  leakage, and split contamination.

## Workstream 2: matter families and variation

Build a constrained synthetic variant generator before attempting the complete
real-firm matter compiler. Variations must change legally meaningful state, not
only names or wording:

- client side, role, leverage, and risk tolerance;
- authority rules and approved fallback positions;
- hidden factual pivots;
- question, escalation, negotiation, and step budgets;
- document structure and order;
- clean versus issue-bearing paper;
- escalation requirements and tempting over-escalations;
- counterparty resistance, fallbacks, and trap positions; and
- surface language, identifiers, and clause placement.

Initial target:

- 20-30 training matter families;
- 100-200 validated training variants;
- 2,000-5,000 reviewed state-action examples; and
- 15-30 sealed evaluation families yielding 50-100 evaluation episodes, with ten
  reviewed families as the interim floor for the first evaluation.

Family-level separation is mandatory. Variants of one latent template must not
be divided between training and evaluation.

Sealed evaluation families cannot be derived from the twelve public development
matters: those matters are visible to every model and person during
development, so any variant of them is contaminated as evaluation content.
Evaluation families must be authored as new, structurally distinct matter
content in the private repository; the public catalog tracks training families
only.

The current transform vocabulary (budgets, roles, hidden facts, public facts,
document order, issue presence) does not yet reach counterparty behavior:
resistance profiles, fallback chains, and trap positions are fixed per base
matter. Negotiation-side transforms are the next required generator capability
and a precondition for several required pair categories in Workstream 6.

### Acceptance

- Every variant passes matter lint and reference replay.
- Required adversarial trajectories trip the intended gates.
- Clean and restraint cases are represented.
- The sealed registry, when published, must expose identifiers and hashes, not
  hidden evaluation contents, to the training pipeline. The mechanism is
  implemented and tested (`sealed_matter_hashes` in
  `src/playbook_legal/dataset.py`); no sealed registry artifact is published
  yet, and one ships only when the private corpus clears review.

## Workstream 3: baselines

Before fine-tuning, run the selected student base model and open-weight teacher
on public development matters and sealed evaluation families. Optionally run
one strong API model under the same action contract as an additional external
reference.

Every run must preserve:

- exact model name and revision;
- prompt, engine, rubric, and matter hashes;
- decoding parameters and random seed;
- split and matter-family identifier;
- raw traces and aggregate scorecards;
- protocol failures; and
- API or compute cost.

Baseline execution remains gated on an explicit model choice and approved
budget. Reference trajectories are an engine check and upper-bound aid, not a
model baseline.

Before authoring new families at scale, run the candidate teacher on the
existing materialized variants and measure rollout yield: the fraction of
candidate trajectories that survive protocol, reproducibility, and
critical-failure filters. A low yield changes the rollout budget and may change
the teacher choice; measure it while the catalog is still small.

## Workstream 4: rollout generation and legal review

Use the larger open-weight teacher to generate several candidate trajectories
per training variant. Automatically reject protocol failures, incomplete
episodes, non-reproducible traces, and critical failures from positive SFT
data — and enforce a preregistered minimum normalized score on top of those
mechanical filters. Normalization clamps negative raw rewards to zero, so the
mechanical chain alone cannot distinguish "did nothing" from "actively wrong";
the 2026-08-06 pilot passed 6 of 8 candidates through the mechanical filters
while 0 of 8 cleared a 0.5 score bar. Do not simply select the highest scoring
path: sample across matter families, decisions, score bands, and failure types
for qualified legal review.

Pilot finding (2026-08-06): Qwen2.5-32B-Instruct at temperature 0.7 with the
generic baseline prompt scored 0.00-0.19 against 0.97-1.00 references on four
new-family variants. The teacher for Workstream 4 must therefore be a stronger
model, a scaffolded/structured prompt, or high-N best-of-N sampling — and the
rollout budget must be re-estimated after the teacher choice, not before.

Training sources, in priority order:

1. expert-authored and reviewed reference trajectories;
2. model trajectories corrected or approved by lawyers; and
3. qualified, consented, replay-verified human gym traces.

The reviewer should correct material actions and record why alternatives are
inferior. This produces both better demonstrations and decision-level
preference data.

Qualified review is a budgeted resource like GPU time. At roughly one to two
minutes per state-action record, the 2,000-5,000-record target implies 30-150+
hours of reviewer time. Name the reviewers, their qualifications, and the
approved hours in the data card before rollout generation begins.

### Data freeze gate

Before training, produce an immutable dataset release containing:

- the records and manifest;
- source and consent provenance;
- inclusion/exclusion criteria;
- review coverage and reviewer qualifications;
- matter-family distribution;
- action and failure-type distribution;
- known limitations; and
- cryptographic hashes.

Never train automatically from the live human-trace inbox.

## Workstream 5: controlled SFT experiments

Train in this order:

1. final-answer-only LoRA distillation from the open-weight teacher;
2. state-action LoRA distillation from the same teacher;
3. blind evaluation of both against the unchanged base;
4. one small, preregistered hyperparameter adjustment if necessary; and
5. a final frozen comparison.

Keep the teacher, student base model, train/evaluation families, training-token
budget, and evaluation settings constant. Save teacher and student revisions,
adapters, configurations, logs, checkpoints, dataset hashes, and environment
versions.

The state-action format is the main scientific treatment. Complete-trajectory
SFT may be retained as a secondary ablation if budget permits.

## Workstream 6: decision-level preference training

The current DPO builder ranks complete episodes from the same initial matter.
Add a separate builder for candidate actions taken from the same state.

Required pair categories include:

- useful versus unnecessary client questions;
- evidence-grounded issues versus unsupported assumptions;
- required escalation versus unauthorized unilateral action;
- correct independent action versus over-escalation;
- authorized fallback versus prohibited concession;
- safe rejection versus acceptance of a trap counter; and
- correct restraint versus a manufactured issue.

Each pair should retain the preference source and structured reason. Train DPO
only if trajectory SFT first demonstrates a viable policy. Evaluate the DPO
adapter through full episodes, not only held-out preference accuracy.

This before/after comparison is the first test of whether Playbook environment
feedback improves the student beyond teacher imitation. Do not describe the
distillation-only result as evidence for reinforcement learning. Consider
online RL only after DPO improves sealed full-episode outcomes without weakening
the critical safety gates.

## Workstream 7: blind evaluation and adversarial gates

Run the complete model comparison on sealed, structurally disjoint matter
families. Do not tune prompts, thresholds, or generation parameters after
examining held-out outcomes.

After every adapter:

- run the full private benchmark;
- run all existing adversarial tests;
- add regressions for newly observed gaming strategies;
- inspect failures for matter leakage and policy shortcuts;
- test shuffled document order, varied budgets, and paraphrased surface forms;
- report aggregate and per-family results; and
- preserve representative successful and failed traces.

The model must not learn a fixed pattern such as always asking first, always
escalating liability, always rejecting counters, or inferring policy from a
matter identifier.

## Workstream 8: release

Release Playbook-1 only if the preregistered claim is supported. The release
package should include:

- the permitted adapter or model weights;
- a model card and intended-use boundary;
- an immutable data manifest and data card;
- the full base/final-answer/trajectory/DPO benchmark report;
- evaluation commands and environment versions;
- representative traces and failure analysis;
- a playable demonstration; and
- a clear statement that the model is a research workflow model, not legal
  advice or an autonomous lawyer.

The public claim should remain narrow and falsifiable:

> Playbook-1 is a post-trained legal workflow model for transactional review
> and negotiation under client-specific authority constraints.

## Deferred follow-on work

These are not required to establish the first result:

- continued legal-domain pretraining;
- a separately trained critic or value model;
- policy-candidate generation plus critic reranking;
- GRPO or other online reinforcement learning;
- the complete private-corpus matter compiler; and
- expansion beyond transactional agreements.

The critic is the preferred second model if Playbook-1 succeeds. It may be more
deployable in the near term because it can review proposed actions without
autonomously negotiating.

## Critical path

```text
experiment specification
  -> state-action and final-answer dataset builders
  -> synthetic family variation and sealed split
  -> student-base and open-weight-teacher baselines
  -> teacher rollouts, legal review, and frozen training corpus
  -> matched final-answer distillation
  -> matched state-action distillation
  -> blind controlled comparison
  -> decision-level DPO
  -> release
```

## Immediate next package

The first implementation package required no paid API or GPU work:

1. [x] finalize this experiment contract, including the primary metric;
2. [x] add the state-action and final-answer dataset views;
3. [x] add a contamination-safe matter-family registry;
4. [x] test prompt/outcome separation and family-level split enforcement; and
5. [x] write the reproducible dataset manifest format.

The next no-cost repository package is:

1. expand the family catalog from the current 12 training families (42 variants)
   toward 20-30 training families and the contract's 15-30 sealed evaluation
   families (ten reviewed families is the interim floor for a first evaluation);
2. materialize 100-200 semantically varied, lint-clean variants with replayed
   reference trajectories and adversarial gate coverage;
3. build and verify candidate dataset releases, then measure family, action,
   failure-type, and review-coverage gaps against the target distribution;
4. route the candidate records through qualified legal review and freeze only
   the approved, critical-free positive-SFT subset; and
5. choose the base model and approve the baseline and rollout budget before
   incurring external cost.
