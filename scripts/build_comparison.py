# SPDX-License-Identifier: AGPL-3.0-only

"""Pool per-seed baseline scorecards into a cross-model comparison table.

Reads artifacts/scorecards/<slug>-seed<N>.json files plus the reference-replay
scorecard and writes comparison.json and comparison.md alongside them. Pooling
keeps episodes as rows; the critical-failure confidence interval clusters by
matter family so correlated seeds and variants are not treated as independent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playbook_legal.metrics import cluster_bootstrap_interval

SCORECARDS = Path("artifacts/scorecards")

MODELS = [
    ("Claude Opus 5", "claude-opus-5-seed", [0]),
    ("GPT-5.6-sol", "gpt-5_6-sol-seed", [0]),
    ("Qwen2.5-32B-Instruct", "qwen2_5-32b-seed", [0]),
    ("Qwen2.5-14B-Instruct", "qwen2_5-14b-seed", [0, 1, 2]),
    ("Qwen2.5-7B-Instruct", "qwen2_5-7b-seed", [0, 1, 2]),
]

COLUMNS = [
    ("normalized_score", "Score"),
    ("critical_failure_rate", "Critical rate"),
    ("citation_validity", "Citation validity"),
    ("issue_recall", "Issue recall"),
    ("question_recall", "Question recall"),
    ("unsupported_issue_count", "Unsupported/ep"),
    ("steps", "Steps"),
    ("completion_rate", "Completion"),
]


def pool(rows: list[dict]) -> dict:
    n = len(rows)

    def mean(key: str) -> float:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return sum(values) / len(values) if values else float("nan")

    critical = sum(1 for row in rows if row.get("critical_failure"))
    return {
        "episodes": n,
        "normalized_score": round(mean("normalized_score"), 4),
        "critical_failure_rate": round(critical / n, 4),
        "critical_failures": critical,
        "citation_validity": round(mean("citation_validity"), 4),
        "issue_recall": round(mean("issue_recall"), 4),
        "question_recall": round(mean("question_recall"), 4),
        "unsupported_issue_count": round(mean("unsupported_issue_count"), 4),
        "steps": round(mean("steps"), 1),
        "completion_rate": round(
            sum(1 for row in rows if row.get("terminated")) / n, 4
        ),
    }


def main() -> None:
    entries = []

    reference = json.loads((SCORECARDS / "reference-replay.json").read_text(encoding="utf-8"))
    entries.append(
        {
            "label": "Expert reference (replay)",
            "seeds": [0],
            **pool(reference["episodes"]),
            "critical_failure_ci95": None,
        }
    )

    for label, prefix, seeds in MODELS:
        rows: list[dict] = []
        for seed in seeds:
            path = SCORECARDS / f"{prefix}{seed}.json"
            if not path.exists():
                print(f"MISSING {path} — skipping {label}")
                rows = []
                break
            rows.extend(json.loads(path.read_text(encoding="utf-8"))["episodes"])
        if not rows:
            continue
        pooled = pool(rows)
        ci = cluster_bootstrap_interval(rows, "critical_failure_rate")
        entries.append(
            {
                "label": label,
                "seeds": seeds,
                **pooled,
                "critical_failure_ci95": [ci["lower"], ci["upper"]] if ci else None,
            }
        )

    payload = {
        "split": "dev",
        "matters": 12,
        "note": (
            "Pooled means over all episodes per model; 32B pools a single seed. "
            "Critical-failure CI is a 95% cluster bootstrap resampled by matter family."
        ),
        "models": entries,
    }
    (SCORECARDS / "comparison.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Playbook baseline comparison — 12 public matters (dev split)",
        "",
        "| Model | Episodes | "
        + " | ".join(label for _, label in COLUMNS)
        + " | Critical 95% CI |",
        "|" + " --- |" * (len(COLUMNS) + 3),
    ]
    for entry in entries:
        ci = entry["critical_failure_ci95"]
        ci_text = f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "—"
        cells = " | ".join(
            f"{entry[key]:.3f}" if isinstance(entry[key], float) else str(entry[key])
            for key, _ in COLUMNS
        )
        lines.append(f"| {entry['label']} | {entry['episodes']} | {cells} | {ci_text} |")
    lines += [
        "",
        payload["note"],
        "",
    ]
    (SCORECARDS / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
