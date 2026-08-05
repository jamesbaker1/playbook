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

- no measured model or human baselines have been published;
- the current human SFT artifact contains only one record;
- current SFT consumes complete trajectories rather than an explicit
  state-action dataset;
- current DPO compares whole episodes rather than competing actions from the
  same state;
- there is no final-answer-only SFT control; and
- six held-out matters do not support the intended 50-100 episode evaluation
  without additional sealed matter families or variants.

## Experiment contract

Freeze the experiment before generating or reviewing training data.

### Scope

- Domain: transactional technology agreements.
- Base: one open-weight instruct model in the 7B-14B range.
- Initial capabilities: issue spotting, factual-question selection,
  escalation, redline choice, and negotiation under authority constraints.
- Training: LoRA SFT first, decision-level DPO second.
- Online RL: explicitly out of scope until SFT/DPO results and adversarial
  retesting justify it.
- Continued pretraining: optional future work, not required for Playbook-1.

### Required model comparison

1. Unmodified base model.
2. Final-answer-only SFT using the same base model.
3. Playbook trajectory/state-action SFT using the same base model.
4. Trajectory SFT plus DPO, if the SFT result clears its gate.
5. One strong API model as an external reference, not a training control.

The two SFT conditions must use matched training-token budgets and comparable
hyperparameter selection. This prevents a larger dataset or compute budget from
being mistaken for evidence that process supervision works.

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
- at least 10 sealed evaluation families yielding 50-100 evaluation episodes.

Family-level separation is mandatory. Variants of one latent template must not
be divided between training and evaluation.

### Acceptance

- Every variant passes matter lint and reference replay.
- Required adversarial trajectories trip the intended gates.
- Clean and restraint cases are represented.
- The sealed registry exposes identifiers and hashes, not hidden evaluation
  contents, to the training pipeline.

## Workstream 3: baselines

Before fine-tuning, run the selected base model on public development matters
and sealed evaluation families. Run one strong API model under the same action
contract as an external reference.

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

## Workstream 4: rollout generation and legal review

Generate several candidate trajectories per training variant. Automatically
reject protocol failures, incomplete episodes, non-reproducible traces, and
critical failures from positive SFT data. Do not simply select the highest
scoring path: sample across matter families, decisions, score bands, and failure
types for qualified legal review.

Training sources, in priority order:

1. expert-authored and reviewed reference trajectories;
2. model trajectories corrected or approved by lawyers; and
3. qualified, consented, replay-verified human gym traces.

The reviewer should correct material actions and record why alternatives are
inferior. This produces both better demonstrations and decision-level
preference data.

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

1. final-answer-only LoRA SFT;
2. trajectory/state-action LoRA SFT;
3. blind evaluation of both against the unchanged base;
4. one small, preregistered hyperparameter adjustment if necessary; and
5. a final frozen comparison.

Keep the base model, train/evaluation families, training-token budget, and
evaluation settings constant. Save adapters, configurations, logs, checkpoints,
dataset hashes, and environment versions.

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
  -> base-model baselines
  -> reviewed and frozen training corpus
  -> final-answer SFT
  -> trajectory/state-action SFT
  -> blind controlled comparison
  -> decision-level DPO
  -> release
```

## Immediate next package

The first implementation package should require no paid API or GPU work:

1. finalize this experiment contract, including the primary metric;
2. add the state-action and final-answer dataset views;
3. add a contamination-safe matter-family registry;
4. test prompt/outcome separation and family-level split enforcement; and
5. write the reproducible dataset manifest format.

Once that package is green, choose the base model and approve the baseline and
rollout budget before incurring external cost.
