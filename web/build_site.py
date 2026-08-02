"""Assemble the lightweight web-gym client into an output directory.

The scoring engine and matter internals live in the separate Cloudflare Worker.
The public site contains only static interface assets.

    python web/build_site.py dist
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent

ASSETS = [
    "index.html",
    "style.css",
    "api-base.js",
    "citation.js",
    "score.js",
    "capture.js",
    "draft-store.js",
    "app.js",
    "contribute.js",
    "policy.json",
    "favicon.svg",
    "og-card.png",
]


def build(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    for name in ASSETS:
        shutil.copy2(WEB / name, out_dir / name)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"{out_dir}: {len(ASSETS)} static assets")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "dist"))
