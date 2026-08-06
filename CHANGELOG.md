# Changelog

## v0.4.0 — 2026-08-06

The first release with measured model baselines and a scaled variant catalog.

### Benchmark and evaluation

- First measured open-weight model baselines on the 12 public matters:
  Qwen2.5-7B/14B (36 episodes each) and 32B (12 episodes) via native tool
  calling against vLLM served on Modal (`training/modal_vllm.py`), with the
  deterministic reference-replay ceiling (0.985) for comparison. Headline:
  best pooled score 0.165; no model asks useful client questions; the
  critical-failure rate rises with scale (0.056 → 0.139 → 0.250). Scorecards
  in `results/v0.4.0/`; narrative report in `docs/baseline-report.md`;
  comparison builder in `scripts/build_comparison.py`.
- `playbook-bench` gained `--family-registry` for family labels, split
  enforcement, and clustered uncertainty in scorecards; traces now record
  their seed.

### Rollout-yield pilot (Workstream 4 validation)

- Ran the smallest end-to-end test of the teacher-rollout pipeline: 8 candidate
  trajectories from Qwen2.5-32B on 4 newly authored variants → mechanical
  filters (completion, critical-failure, bit-exact replay verification) →
  state-action dataset build → `playbook-dataset-check` valid. Cost: ~$0.31.
- Finding: mechanical filters pass 75% of candidates, but 0 of 8 clear a 0.5
  score bar (teacher scores 0.00–0.19 vs references at 0.97–1.00) — and score
  normalization clamps negative raw rewards to zero, so a preregistered
  minimum-score filter is now required in the plan. The reward-gaming gate
  correctly caught both fabricated-quotation episodes. Summary in
  `results/v0.4.0/rollout-pilot.json`; conclusion folded into
  `docs/playbook-1-plan.md` Workstream 4.

### Synthetic matter families

- Variant family catalog expanded from 5 families / 14 variants to
  **12 families / 42 variants** — every public base matter now backs a
  replay-verified training family. All 42 variants pass lint and reference
  replay at ≥ 0.9 with no critical failures; 29 adversarial gate trajectories
  fire as declared; catalog builds are byte-deterministic.
- Coverage now spans all eight variation dimensions, including
  authority/fallback and counterparty behavior.

### Playbook-1 experiment contract

- Preregistered a CI-based decision rule for the primary comparison
  (one-sided 95% cluster-bootstrap interval must exclude zero) plus a
  temptation-density requirement for sealed evaluation families.
- Added secondary reporting: state-action SFT vs. unmodified base, and
  per-condition protocol-failure rates (guards against a degraded control).
- Plan now states explicitly: sealed evaluation families cannot derive from
  the public dev matters; reviewer hours are a budgeted, named resource;
  a teacher rollout-yield pilot precedes family authoring at scale.

### Dataset and training infrastructure

- Versioned dataset builder with final-answer, trajectory-chat, and
  state-action views; prompt/outcome separation enforced and tested.
- Contamination-safe matter-family registry with family-level split
  enforcement.
- Reviewed, content-addressed dataset freeze gates (`playbook-dataset-freeze`).
- Same-state decision-preference pair builder for decision-level DPO.
- Frozen experiment contract validator (`playbook-experiment-check`).

### Web workspace

- Corrected the matter count shown in the workspace header (12, not 10).
