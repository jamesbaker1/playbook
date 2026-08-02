# Harvey LAB delta experiment

This experiment maps 24 public Harvey LAB master-services-agreement tasks into
interactive Playbook episode descriptors. It is an adaptation protocol, not a
redistribution of the source Office files and not a claim of measured results.

## Reproducible source audit

The official `harveyai/harvey-labs` repository is pinned at commit
`a30c248c5b70923d3d2a31db25235b619a67e5f2` (MIT). At that commit, repository-tree
inspection finds 1,760 `task.json` files: 498 are under `tasks/contracts`. A LAB
task publicly ships its instructions, source documents, and inline pass/fail rubric
criteria. The harness, document parsers, agent prompt/tools, and LLM-judge prompt are
also public. The repository does **not** ship reference answers, private rubric
criteria, hidden client facts, interactive client/counterparty state, or scored model
runs. During a normal LAB run the criteria are not placed in the agent workspace, but
they remain obtainable from the public repository; they are evaluation-hidden, not a
private test set.

For the selected 24 tasks, the pinned tree contains **240 source documents and 1,338
inline rubric criteria**. Those counts are recomputed by the builder rather than stored
as acceptance inputs.

Build and validate the selected batch against an official checkout:

```powershell
python experiments/harvey_lab_delta/build_batch.py `
  --harvey-repo C:\path\to\harvey-labs
```

The builder refuses a checkout at any other commit, loads every source `task.json`
through Git, verifies that every task has documents and criteria, verifies each mapped
Playbook matter has a rubric and hidden facts, and writes `generated/descriptors.json`
plus the required LAB-task-to-Playbook mapping table. The descriptors preserve each
LAB document name and immutable source location. They add a question budget, mapped
hidden-fact state, and deterministic counterparty behavior. Office documents stay in
the MIT source checkout and should be mounted/read from the pinned paths; conversion
to Markdown would lose redlines, tracked changes, workbook structure, and other
features material to the original tasks.

## Run an interactive adaptation

`adapter.py` materializes a descriptor as a real `PlaybookEnv`. It reads the pinned
LAB Office and email files directly from Git, extracts agent-readable text, mounts
every source document in the episode, applies the mapped question budget and hidden
fact state, and exposes deterministic negotiation actions. A reset-only smoke run is:

```powershell
python experiments/harvey_lab_delta/adapter.py `
  --harvey-repo C:\path\to\harvey-labs `
  --task contracts/commercial-vendor-customer/master-services-agreement-counterparty-paper-review/scenario-01
```

Pass `--actions actions.jsonl --trace trace.json` to replay an action sequence and
save its complete trace. The adapter supports the selected bundles' `.docx`, `.xlsx`,
`.pptx`, `.eml`, and plain-text sources using standard-library extraction. On Windows,
it enables Git long-path handling for the deeply nested LAB paths.

The interactive score is intentionally a mapped Playbook reward scaffold, not a
reimplementation of LAB's LLM judge. The LAB sources are the same, but hidden facts
and counterparty behavior are the experimental treatment. Accordingly, the paired
delta is a composite environment comparison; it must not be described as a
psychometrically matched before/after score.

## Paired runs

After choosing models and explicitly approving provider spend, emit a run plan:

```powershell
python experiments/harvey_lab_delta/paired_delta.py --models MODEL_A MODEL_B `
  --emit-plan artifacts/harvey_lab_delta/run-plan.json
```

Run both commands in each specification with the same exact model version and record
one JSON object per line for each form:

```json
{"model":"exact-provider-model-id","task_id":"contracts/.../scenario-01","score":0.0}
```

For Playbook records, `task_id` is still the mapped LAB task ID (the run plan carries
the Playbook matter separately), and `score` is the final normalized score. For LAB,
use its all-pass task score. Preserve failures as explicit records; do not silently
drop them. Generate the report only when all observed LAB records have pairs:

```powershell
python experiments/harvey_lab_delta/paired_delta.py `
  --lab-results artifacts/harvey_lab_delta/lab.jsonl `
  --playbook-results artifacts/harvey_lab_delta/playbook.jsonl `
  --report artifacts/harvey_lab_delta/report.md
```

The output reports `Playbook - LAB` per model and includes scale and contamination
limitations. A negative delta is consistent with, but alone does not prove, the thesis
that static rubric grading over a fully observable bundle overstates capability in an
interactive partially observable environment.

## Contamination caveat

Harvey LAB has been public since May 2026. Its documents, instructions, and exact
rubrics may be in model pretraining, post-training, retrieval indexes, or manual
benchmark tuning. Accordingly, LAB performance cannot be treated as uncontaminated;
the paired comparison must disclose this date and treat unusually strong LAB scores
as potentially inflated. Playbook's synthetic canaries and hidden/private split reduce
but do not eliminate contamination risk.
