# Four-Week Roadmap

## Week 1 — Environment and first matter

- Freeze the v0.1 schema.
- Complete and test `ai_saas_001`.
- Add a trace viewer or readable HTML report.
- Run scripted good and bad trajectories.
- Write adversarial tests for hidden-state leakage and citation fabrication.

**Exit condition:** another developer can install the repository, run an episode, inspect
its trace, and understand every reward component.

## Week 2 — Matter factory and benchmark

- Author 7–9 additional technology-transactions matters.
- Create public development and private evaluation splits.
- Add matter linting and rubric validation.
- Build API/local-model baseline runners.
- Establish a human adjudication sheet for non-deterministic drafting criteria.

**Exit condition:** at least three models can be compared across ten matters with a stable
scorecard.

## Week 3 — Trajectories and SFT

- Generate multiple candidate trajectories per training matter.
- Review and correct the legally important actions.
- Export chat-format SFT data.
- Fine-tune a 7B–8B instruct model with LoRA.
- Evaluate base versus SFT on private held-out matters.

**Exit condition:** the trained adapter improves at least one pre-registered metric without
increasing critical failures.

## Week 4 — Preference optimization and small online RL

- Rejection-sample high-scoring trajectories.
- Generate chosen/rejected pairs.
- Run a DPO experiment.
- Connect the deterministic episode score to an online RL trainer.
- Run a small GRPO experiment only after adversarial reward testing.
- Publish methods, baseline results, limitations, and a demo.

**Exit condition:** an end-to-end reproducible result showing whether environment-based
post-training improves held-out legal-agent performance.
