# Baseline sprint runbook

W10 is intentionally budget-gated. Do not run it until the owner supplies both an
approved model list and an API credential. Planning is local and makes no requests:

```powershell
playbook-baseline-sprint --models provider/model-a provider/model-b
```

This writes `artifacts/baseline-sprint/manifest.json`. Review its explicit, split-labeled
`playbook-bench` commands, model IDs, seeds, temperature, and output paths before approving
spend. Model aliases such as "latest" are discouraged: use provider version IDs wherever
the provider offers them.

## Execute the measured sprint

The private repository path is deliberately required for execution. With the owner-approved
key in `OPENAI_API_KEY`:

```powershell
playbook-baseline-sprint `
  --models provider/model-a provider/model-b `
  --held-out-matters C:\path\to\playbook-private\matters `
  --top 2 `
  --execute
```

Use `--api-key-env NAME` if the approved credential is stored under another environment
variable. The runner first executes every named model on the public `dev` split, ranks them
by mean normalized score, and executes only the top `--top` models on `held-out`. Missing
credentials or a missing held-out directory stop the sprint before the first request.

Each model gets separate `dev.json`/`.md` and `held-out.json`/`.md` scorecards. The final
`summary.json` validates the SPEC evaluation fields, including escalation recall,
over-escalation count, and settled-issue ratio, and records `held_out_minus_dev` explicitly.
The sprint also writes `report-fragment.md`, including measured `nego_saas_010` trap-counter
exposure and acceptance counts. A zero-exposure result means the sprint did not test the
trap and must be investigated; it is not evidence that the model resisted it.

## Publish results

Copy the generated table and trap-counter note into the README and `docs/report.md` only
after reviewing the saved scorecards. Keep the model version, date, split, seeds,
temperature, and reproduction command adjacent to the table. Never enter scores by hand,
promote a reference replay as a model baseline, or fill the report from console output.

Human baselines remain a separate external activity. The author and early testers must use
Benchmark mode and submit through the verified, consent-versioned trace pipeline. Publish
only replay-verified human scorecards; do not estimate or synthesize a human baseline.
