# Open-weight baseline, re-measured on the post-revision instrument

**Measured 2026-08-19** against the repository at commit **`2649bd9`** — that is,
after the instrument revision that migrated every public-corpus critical-failure
gate onto structured guards (`6d8cc6a` → `0efefdb` → `2a9496e`; see
`docs/instrument-audit-2026-08.md` and the *Instrument revision* entry in
`CHANGELOG.md`).

## Not comparable to `results/v0.4.0/`

Every row in `results/v0.4.0/` was measured under the **pre-revision** gates. The
revision removed instrument error in *both* directions — false positives that
fired on correct, playbook-compliant drafting, and false negatives that let
paraphrases of the gated conduct through — so a critical-failure rate measured
here and one measured there are **two different measurements, not two samples of
one quantity**. Do not diff them, do not put them in one column, and do not
describe a movement between them as a change in model behavior.

The environment, the matters, the runner, the prompt, the seeds, and the serving
path are otherwise unchanged from the v0.4.0 protocol. These are **protocol
replications, not bitwise reproductions**: the language models were sampled
fresh, and vLLM sampling is not deterministic across runs even at a fixed seed.
How much of each critical-rate movement is attributable to the gate revision
therefore differs by row, and a per-episode comparison against the v0.4.0
trajectories decomposes it:

- **Qwen2.5-32B** reproduced the v0.4.0 trajectories bitwise on all 12 episodes,
  so its movement (0.250 → 0.333) is gate-attributable: exactly one episode
  (`saas_renewal_003`) flipped critical under the revised gates on an identical
  trajectory.
- **Qwen2.5-14B** reproduced only 6 of 36 episodes; one flip happened on an
  identical trajectory, five on freshly sampled ones. Its movement
  (0.139 → 0.306) is **confounded** — instrument revision and sampling variance
  cannot be separated at this scale.
- **Qwen2.5-7B** reproduced 15 of 36; two flips on identical trajectories, three
  on resampled ones (two of those flipped critical → clean). Its non-gated
  metrics also drifted more than the other rows (steps 11.0 → 9.6, unsupported
  issues 1.11 → 0.83, citation validity 0.972 → 0.944), which is what fresh
  sampling looks like, not what a gate change looks like.

Read this directory as the current instrument's measurement, not as evidence of
what the revision alone did to any pooled rate.

## What was run

- 12 public matters (`matters/`, dev split), `--runner baseline`, native tool
  calling, temperature 0.2, the baseline system prompt untouched, **no
  `--max-tokens` cap** (matching the v0.4.0 Qwen rows).
- Qwen2.5-7B-Instruct and Qwen2.5-14B-Instruct: seeds 0, 1, 2 (36 episodes each).
- Qwen2.5-32B-Instruct: seed 0 only (12 episodes; indicative).
- Served from self-hosted vLLM 0.25.1 on Modal via `training/modal_vllm.py`
  (7B on A10G, 14B on L40S, 32B on H100), one model live at a time.
- The expert reference replay was re-run into this directory as the
  same-instrument ceiling.

Reproduce one row:

```bash
export OPENAI_API_KEY=<the vLLM shared secret>
python -m playbook_legal.bench --runner baseline \
  --model Qwen/Qwen2.5-7B-Instruct --base-url "$URL/v1" \
  --seeds 0 --split dev \
  --family-registry datasets/matter-families.yaml --save-traces \
  --out results/postrevision-2026-08/qwen2_5-7b-seed0
```

`comparison.md` / `comparison.json` are built by
`scripts/build_comparison_postrevision.py`, a one-off sibling of
`scripts/build_comparison.py` (that script's scorecard root and model list are
fixed to the v0.4.0 entries; it reuses its `pool` helper and column set so the
table format is identical).

## Results

| Model | Episodes | Score | Critical rate | Critical 95% CI | Citation validity | Issue recall | Question recall | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Expert reference (replay) | 12 | 0.985 | 0.000 | — | 1.000 | 0.917 | 0.958 | 22.6 |
| Qwen2.5-32B-Instruct | 12 | 0.076 | 0.333 | [0.083, 0.583] | 1.000 | 0.208 | 0.000 | 8.5 |
| Qwen2.5-14B-Instruct | 36 | 0.142 | 0.306 | [0.111, 0.528] | 1.000 | 0.320 | 0.007 | 8.3 |
| Qwen2.5-7B-Instruct | 36 | 0.034 | 0.083 | [0.000, 0.222] | 0.944 | 0.103 | 0.039 | 9.6 |

Critical-failure CIs are 95% cluster bootstraps resampling the twelve matter
families as intact clusters. They are wide at this scale; the 32B row pools a
single seed.

Protocol failures (model turns that returned no usable tool call, pooled):
7B 3 (all in one `nego_saas_010` episode), 14B 1, 32B 3 (all in one
`msa_provider_004` episode). Two episodes exhausted the retry budget and were
**force-terminated by the harness** with a degenerate final submission, both
scoring 0.000: `qwen2_5-32b-seed0/msa_provider_004` and
`qwen2_5-7b-seed0/nego_saas_010`. The 32B case is one of only twelve episodes in
that row, so its 0.076 mean carries that harness artifact. No sweep was
interrupted or resumed.

## Traces are retained

Every row in every scorecard has a replayable trace under that scorecard's own
`traces/` directory — `qwen2_5-7b-seed0/traces/<matter>-seed0.trace.json` and so
on, 96 traces for the 96 episodes across the eight scorecards. `playbook-bench`
refuses to publish a scorecard claiming trace coverage it does not have, and
coverage (no missing trace, no orphan trace) plus a two-episode round-trip
re-score (extract the trace's actions, replay them through `playbook-eval`,
require an identical `normalized_score`, `critical_failure`, and step count) was
re-checked independently for all eight scorecards after the fact. All passed.

Because `PlaybookEnv.reset` only *records* its seed — the seed reaches the model
sampler, never the environment — scoring is seed-independent and a trace from
any seed re-scores identically under `playbook-eval`'s fixed seed-0 reset.

## Still pending

The two frontier reference rows (Claude Haiku 4.5, GPT-5.6-terra) have **not**
been re-measured on the revised instrument; that is blocked on an OpenRouter
top-up. Until they land, this directory holds open-weight rows only, and the
frontier comparisons in `docs/baseline-report.md` remain pre-revision numbers.
