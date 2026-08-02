# Training

GPU work runs on Modal only after an explicit `modal run`; nothing in this
directory automatically spends compute or requires local PyTorch.

## Human trace export

The production trace API is
`https://playbook-traces.james-baker1628.workers.dev`. Its administrative reads
require the same token stored as the Worker's `READ_TOKEN` secret. Follow
`web/worker/README.md` to synchronize access without exposing the token.

From the repository root, fetch, replay, verify, and export records:

```bash
export PLAYBOOK_TRACES_TOKEN  # load it from a password manager first
python training/human_data.py \
  --endpoint https://playbook-traces.james-baker1628.workers.dev \
  --output artifacts/human_verified.jsonl
```

```powershell
# Set $env:PLAYBOOK_TRACES_TOKEN from a password manager first.
.\.venv\Scripts\python.exe training\human_data.py `
  --endpoint https://playbook-traces.james-baker1628.workers.dev `
  --output artifacts\human_verified.jsonl
```

Raw downloads are cached in `artifacts/human_traces`; the JSONL export and raw
cache are gitignored. To re-run verification without network access:

```bash
python training/human_data.py --skip-fetch --output artifacts/human_verified.jsonl
```

```powershell
.\.venv\Scripts\python.exe training\human_data.py --skip-fetch `
  --output artifacts\human_verified.jsonl
```

The verifier rejects unknown matters, malformed or incomplete action streams,
actions after episode completion, non-reproducing scores, critical-failure
mismatches, and missing/current-consent failures. Accepted episodes use locally
replayed observations rather than browser-provided observation text.

Verification proves integrity, not legal quality. Before any training run:

1. Preserve the raw snapshot, export, command/version metadata, and rejection
   counts so the dataset can be reproduced.
2. Have a qualified reviewer inspect drafting content and material actions,
   sampling across matter, score band, contributor background, and failure type.
3. Remove private, identifying, privileged, or otherwise unsuitable content under
   the applicable data policy; consent alone is not a quality or privacy review.
4. Approve a versioned, immutable training file and record its hash. Never train
   automatically from the live inbox.
5. Establish base-model results on public development and private held-out matters
   before fine-tuning. Keep training and held-out matters structurally disjoint.

## Launch SFT deliberately

Modal setup and GPU training may incur charges. Review the approved JSONL before
uploading it, then run:

```bash
python -m pip install modal
modal setup
modal volume create playbook-artifacts
modal volume put playbook-artifacts artifacts/human_verified.jsonl /data/human_verified.jsonl
modal run training/modal_app.py::sft --data /vol/data/human_verified.jsonl
```

The same commands work in PowerShell (use backticks only if splitting lines). The
default SFT function uses an A10G and writes the adapter to
`/vol/outputs/sft_adapter`. A successful integrity export is not evidence that the
dataset is large, representative, or good enough to improve a model; do not launch
SFT until the review gate and baseline are complete.

## Broader training sequence

1. Baseline: `playbook-bench --runner baseline --model <model>` on public dev and
   private held-out matters.
2. Rollouts: `python training/generate_rollouts.py`, then legally review important
   actions and retain high-scoring, critical-free trajectories for SFT.
3. SFT: `modal run training/modal_app.py::sft`.
4. Preference pairs: `python training/build_pairs.py`; then DPO with
   `modal run training/modal_app.py::dpo`.
5. Run `pytest tests/test_adversarial.py` and add regressions for newly observed
   reward hacking before considering online RL.
6. GRPO: `modal run training/modal_app.py::grpo`; this is heavier and configured
   for an A100.

Report every metric required by SPEC section 10 on private held-out matters, not
only public development matters. Pre-register the metric expected to move before
each experiment.

## Export troubleshooting

- HTTP 401: synchronize `READ_TOKEN` and `PLAYBOOK_TRACES_TOKEN`; do not attempt to
  retrieve the write-only Worker secret.
- A network timeout: retry the export. Existing raw files are cached and skipped,
  and `--skip-fetch` can verify the current snapshot offline.
- Zero exported records: read the printed rejection reasons. It may also mean the
  inbox has no genuine, complete, consented contributions; do not treat zero as a
  training corpus.
- A Python import or matter error: run from the repository root with the project
  virtual environment and confirm the matching matters checkout is present.
