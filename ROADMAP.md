# Roadmap

## Phase 1 — Environment and scoring contract ✅

- [x] v0.1 vertical slice: env, rewards, trace, one matter, tests.
- [x] v0.2 scoring contract: content-based issue/question matching (no rubric-ID
      guessing), verbatim quote verification with a fabrication gate, scoring detail
      removed from agent-visible observations.
- [x] Matter linter with contamination canary; CI (pytest + ruff + matter lint).
- [x] Adversarial tests: hidden-state leakage sweep, determinism, anti-gaming
      (keyword stuffing must lose), fabrication and reversal gates.
- [x] HTML trace report and SFT export as package CLIs.

## Phase 2 — Matter factory and benchmark ✅ (this release)

- [x] 7 additional technology-transactions matters, varied per AUTHORING.md
      (document architecture, role flips, regulatory overlays, factual pivots).
- [x] Public dev split (`matters/`) and private held-out split (separate private
      repository), disjoint by structure and vocabulary.
- [x] Reference + adversarial trajectories per matter, enforced by CI.
- [x] Baseline runner: OpenAI-compatible tool-calling loop (any endpoint via
      base_url), protocol-failure recovery.
- [x] `playbook-bench` scorecard implementing the SPEC §10 evaluation protocol.

## Phase 3 — Trajectories and SFT (scaffolded, not yet run)

- [x] Rollout generation and scoring (`training/generate_rollouts.py`).
- [x] LoRA SFT scaffold (`training/sft_lora.py`, Modal: `modal_app.py::sft`).
- [ ] Run baselines (API + open models) on dev and held-out splits.
- [ ] Legally review high-scoring trajectories; train the first adapter.
- [ ] Evaluate base vs. SFT on the private held-out matters.

## Phase 4 — Preference optimization and online RL (scaffolded, not yet run)

- [x] Chosen/rejected pair builder (`training/build_pairs.py`).
- [x] DPO scaffold (`training/dpo_lora.py`, Modal: `modal_app.py::dpo`).
- [x] GRPO scaffold with environment-owned reward (`training/grpo_env_reward.py`).
- [ ] Adversarial reward re-testing on real rollouts before any online RL.
- [ ] Small GRPO experiment; publish methods, baselines, limitations, and a demo.

## Phase 5 — Humans in the gym (design)

- [ ] Web UI over the environment (it is already a turn-based JSON API): people play
      the same episodes models play, scored by the same rubrics.
- [ ] Human-lawyer baseline numbers for the benchmark.
- [ ] Skill-gated pairwise preference collection on redlines (gold-matter
      calibration, vote weighting) feeding a drafting-quality reward model — crowd
      signal trains a judge; it never becomes raw online reward.
- [ ] LLM judge as implementation #2 of rubric criteria for drafting nuance, with
      calibration against the human adjudication data.

## North star

A matter compiler: turn a real deal's artifact trail (documents, negotiation
history, tracked-changes, outcome) into a matter package inside the data owner's own
walls — the same environment, reward engine, and trace format, pointed at private
corpora that never leave the firm. The open repository stays 100% synthetic.
