# Changelog

## Unreleased

### Structured critical-failure gates (opt-in)

- Entries in `critical_failure_patterns`, `redline_critical_failure_patterns`, and
  `settlement_critical_failure_patterns` may now be a mapping instead of a plain
  string: `pattern` (required) plus optional `negation_guard`, `require_context`, and
  `exclude_context`. Adversarial probing replay-confirmed 84 false-positive blockers
  across the 12 public matters — bare substring gates firing on the sentence the
  instructions actually ask for ("**no** law prohibits all model training", "**neither**
  Provider **nor** Customer may use Provider Data", "is **not** conclusive and binding
  on", "**nothing** in this Section restricts..."). One engine mechanism a rubric author
  opts into per pattern replaces tempering 136 regexes by hand.
- `negation_guard` drops a match when a negator (`no`, `not`, `never`, `nothing`,
  `none`, `neither`, `nor`, `cannot`, `without`, `n't`) falls between the start of the
  match's sentence and the end of the matched span. Sentences break on `.`/`?`/`!` +
  whitespace or a newline; a period before a digit never breaks one, so `§10.2` and
  `R.3` stay intact. All three sites share one `gate_match` helper, so the semantics
  cannot diverge, and trace attribution still reports the `pattern` string.
- Plain-string patterns are byte-identical to before — proven by replaying the public
  references and `bad_critical_*` trajectories against frozen scores, critical flags,
  and fired-gate attributions. No shipped rubric opts in yet; the mechanism is dormant.
- The linter validates the mapping form per matter: `pattern` present and compilable,
  guard regexes compilable, and **unknown keys rejected** rather than silently ignored.

### The critic (v0) — deterministic verification without an answer key

- New `playbook-critic <matter_or_docs_dir> <submission>` and
  `playbook_legal.critic`: a deterministic verification layer that reviews proposed
  deal-review work using **only** materials a real client would have. It never opens
  `rubric.yaml`, `hidden_facts.yaml`, or `counterparty.yaml`, and never constructs
  `PlaybookEnv` — every read passes through a guard that refuses those filenames, so
  a matter directory with the three answer-key files deleted verifies identically.
  Filenames are folded the way the filesystem folds them (`RUBRIC.YAML`,
  `rubric.yaml.`, and `rubric.yaml:$DATA` all open the same file on Windows), and no
  YAML file can enter the record as a document, so renaming an answer key does not
  smuggle it in as evidence. No LLM calls anywhere.
- Checks: verbatim quotation verification (mirroring the engine's fabricated-quote
  gate exactly), citation resolution, prohibited concessions in redline/markup/
  settlement language, and evidence hygiene. Verdicts are `verified`,
  `FABRICATED_QUOTE`, `UNRESOLVED_CITATION`, `PROHIBITED_CONCESSION`, and the
  advisory `MISSING_EVIDENCE`; any critical verdict exits nonzero. Everything the
  engine treats as a critical failure and the critic can see for itself is critical
  here too — including a quotation that carries no citation at all.
- Accepts both an actions JSONL trajectory and a structured review JSON, and emits a
  `playbook.critic-report.v1` JSON report plus a readable Markdown report. A
  submission in neither shape is refused with an explanation rather than reviewed as
  an empty one.
- New `playbook.authority.v1` schema lets a client state its own limits as literal
  patterns, matched with the engine's semantics (case-insensitive substring on
  whitespace-normalized text, so `30 days` matches inside `130 days`). Worked example
  in `examples/authority/ai_saas_001.authority.yaml`, derived solely from that
  matter's public client playbook.
- `playbook_legal.text.normalize_text` is now the single shared normalization used by
  both the reward engine and the critic; `loaders.parse_sections` is public so the
  critic tokenizes sections identically to the linter. Neither change alters engine
  behavior.
- Documentation: `docs/critic.md`; README CLI table and practice section.

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
