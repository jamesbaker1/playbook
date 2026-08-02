"""Render a Playbook JSON trace as a self-contained HTML audit report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    rows = []
    for event in trace["events"]:
        action = html.escape(json.dumps(event["action"], indent=2, ensure_ascii=False))
        last_result = html.escape(
            json.dumps(event["observation"].get("last_result", {}), indent=2, ensure_ascii=False)
        )
        rows.append(
            f"""
            <section>
              <h2>Step {event['step']}: {html.escape(event['action'].get('type', 'unknown'))}</h2>
              <p><strong>Reward:</strong> {event['reward']:.3f}</p>
              <details open><summary>Action</summary><pre>{action}</pre></details>
              <details><summary>Environment response</summary><pre>{last_result}</pre></details>
            </section>
            """
        )
    result = trace["result"]
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Playbook Trace — {html.escape(trace['matter'])}</title>
<style>
body {{ max-width: 980px; margin: 40px auto; padding: 0 20px; font-family: system-ui, sans-serif; line-height: 1.5; }}
header, section {{ border: 1px solid #ddd; border-radius: 12px; padding: 20px; margin-bottom: 18px; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f6f6f6; padding: 14px; border-radius: 8px; }}
.score {{ font-size: 2rem; font-weight: 700; }}
small {{ color: #555; }}
</style>
</head>
<body>
<header>
<h1>Playbook episode trace</h1>
<p><strong>Matter:</strong> {html.escape(trace['matter'])}</p>
<p class="score">Score: {result['normalized_score']:.3f}</p>
<p>Raw score: {result['raw_score']} / {result['max_score']} · Critical failure: {result['critical_failure']}</p>
<small>This report displays the complete action trace for audit and training-data review.</small>
</header>
{''.join(rows)}
</body>
</html>"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
