# SPDX-License-Identifier: AGPL-3.0-only

"""Pool the post-revision baseline scorecards into a cross-model comparison table.

A one-off sibling of ``scripts/build_comparison.py``: that script is registered for
the v0.4.0 release entries (its scorecard root is ``artifacts/scorecards`` and its model list is fixed, and it
expects the two frontier rows), so pointing it at the re-measured campaign would
either rewrite a published table or silently drop rows. This reuses its ``pool``
helper and column set verbatim so the emitted table is format-identical, and reads
``results/postrevision-2026-08/`` instead.

    python scripts/build_comparison_postrevision.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_comparison import COLUMNS, pool

from playbook_legal.metrics import cluster_bootstrap_interval

SCORECARDS = ROOT / "results" / "postrevision-2026-08"

MODELS = [
    ("Qwen2.5-32B-Instruct", "qwen2_5-32b-seed", [0]),
    ("Qwen2.5-14B-Instruct", "qwen2_5-14b-seed", [0, 1, 2]),
    ("Qwen2.5-7B-Instruct", "qwen2_5-7b-seed", [0, 1, 2]),
]

NOTE = (
    "Pooled means over all episodes per model; 32B pools a single seed. "
    "Critical-failure CI is a 95% cluster bootstrap resampled by matter family. "
    "Measured on the post-revision instrument; not comparable to results/v0.4.0."
)


def protocol_failures(rows: list[dict]) -> int:
    return sum(int(row.get("protocol_failures", 0)) for row in rows)


def main() -> None:
    entries = []

    reference = json.loads((SCORECARDS / "reference-replay.json").read_text(encoding="utf-8"))
    entries.append(
        {
            "label": "Expert reference (replay)",
            "seeds": [0],
            **pool(reference["episodes"]),
            "protocol_failures": protocol_failures(reference["episodes"]),
            "critical_failure_ci95": None,
        }
    )

    for label, prefix, seeds in MODELS:
        rows: list[dict] = []
        for seed in seeds:
            path = SCORECARDS / f"{prefix}{seed}.json"
            if not path.exists():
                print(f"MISSING {path} - skipping {label}")
                rows = []
                break
            rows.extend(json.loads(path.read_text(encoding="utf-8"))["episodes"])
        if not rows:
            continue
        ci = cluster_bootstrap_interval(rows, "critical_failure_rate")
        entries.append(
            {
                "label": label,
                "seeds": seeds,
                **pool(rows),
                "protocol_failures": protocol_failures(rows),
                "critical_failure_ci95": [ci["lower"], ci["upper"]] if ci else None,
            }
        )

    payload = {
        "split": "dev",
        "matters": 12,
        "instrument": "post-revision (structured critical-failure guards)",
        "note": NOTE,
        "models": entries,
    }
    (SCORECARDS / "comparison.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Playbook baseline comparison - 12 public matters (dev split), post-revision instrument",
        "",
        "| Model | Episodes | "
        + " | ".join(label for _, label in COLUMNS)
        + " | Critical 95% CI |",
        "|" + " --- |" * (len(COLUMNS) + 3),
    ]
    for entry in entries:
        ci = entry["critical_failure_ci95"]
        ci_text = f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "-"
        cells = " | ".join(
            f"{entry[key]:.3f}" if isinstance(entry[key], float) else str(entry[key])
            for key, _ in COLUMNS
        )
        lines.append(f"| {entry['label']} | {entry['episodes']} | {cells} | {ci_text} |")
    lines += [
        "",
        NOTE,
        "",
        "Protocol failures (turns that returned no usable tool call, pooled per row): "
        + ", ".join(f"{entry['label']} {entry['protocol_failures']}" for entry in entries)
        + ".",
        "",
    ]
    (SCORECARDS / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
