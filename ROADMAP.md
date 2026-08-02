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

## Phase 2 — Matter factory and benchmark ✅

- [x] 7 additional technology-transactions matters, varied per AUTHORING.md
      (document architecture, role flips, regulatory overlays, factual pivots).
- [x] Public dev split (`matters/`) and private held-out split (separate private
      repository), disjoint by structure and vocabulary.
- [x] Reference + adversarial trajectories per matter, enforced by CI.
- [x] Baseline runner: OpenAI-compatible tool-calling loop (any endpoint via
      base_url), protocol-failure recovery.
- [x] `playbook-bench` scorecard implementing the SPEC §10 evaluation protocol.

## Phase 2.5 — Judgment mechanics ✅ (v0.3, this release)

Issue-spotting is the easy half of the job. Phase 2.5 scores the two things a
supervising partner actually watches for: whether you know what is not yours to
decide, and what you give away when someone pushes back.

- [x] **Escalation contract** (SPEC §7): budgeted `escalate(topic, reason)`,
      concept-matched like client questions, answered from hidden supervisor guidance.
      Required escalations are settled up at `submit_final`; `critical_if_missed` is a
      gate. Over-escalation and redundant escalation are penalized.
- [x] **Deterministic negotiation contract** (SPEC §8): `counterparty.yaml` as hidden
      state; `send_markup` / `accept_counterparty` published only where a counterparty
      exists; accept/counter/refuse decided by `accept_concepts` + `resist_rounds`.
      Settlements score the text an issue actually *closes on*; `non_negotiable` and
      `settlement_critical_failure_patterns` are gates.
- [x] New budgets and observation surface: `maximum_escalations` (2),
      `maximum_negotiation_rounds` (8), `escalations_remaining`,
      `submitted_escalation_topics`, the per-label `negotiation` map.
- [x] Metrics extended: escalation recall, over-escalation count, settled-issue ratio.
- [x] `msa_provider_004` retrofitted with the CEO-sign-off escalation its own playbook
      already required.
- [x] Leakage and determinism sweeps extended to escalation guidance and counterparty
      configuration (`tests/test_escalation.py`, `tests/test_negotiation.py`).
- [x] `clean_msa_009` — the trap matter: a compliant renewal where the correct answer
      is "no material issues", graded through `final_submission.required_concepts`.
      Tests false-positive discipline, which no issue-bearing matter can.
- [x] `nego_saas_010` — the negotiation matter: a scripted counterparty with a genuine
      concession, a trap counter, and a client red line the agent must refuse to trade.
- [ ] Baseline numbers for escalation recall and settled-issue quality across models;
      confirm the trap counter is actually trapping.

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

## Phase 5 — Humans in the gym (in progress)

- [x] Static web UI backed by the canonical Cloudflare Python Worker. Rubrics,
      hidden facts, matter files, and scorer code are excluded from the Pages bundle;
      there is no browser-local scoring fallback.
- [x] Learn mode for guided practice and Benchmark mode for sealed attempts, with a
      desktop three-pane workspace and mobile one-pane navigation.
- [x] Opt-in trace contribution: Cloudflare Worker collection endpoint plus a
      replay-verified export pipeline (`training/human_data.py`). Consent is explicit
      and versioned; source, app version, play mode, seed, and optional professional
      background are retained as provenance; handles are excluded from exports.
- [x] Browser parity for escalation and deterministic negotiation, with action-schema
      driven forms, citation and quote preflight, retry/busy states, episode resume,
      persistent learned facts, auditable score diagnosis, and shareable result cards.
- [ ] Run a paid calibration pilot with 5–10 practicing lawyers. Measure completion
      time, rubric/expert agreement, repeat consistency, and cost per reviewed trace.
- [ ] Add blinded expert review: first material error, corrected next action, and
      pairwise preference labels. Keep raw, validated, reviewed, curated, and sealed
      evaluation data as separate tiers.
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
