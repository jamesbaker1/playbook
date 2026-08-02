"""Copy canonical local source and matter packs into the Worker bundle."""

from __future__ import annotations

import shutil
from pathlib import Path

WORKER = Path(__file__).resolve().parent
REPO = WORKER.parent
DESTINATIONS = {
    REPO / "src" / "playbook_legal": WORKER / "src" / "playbook_legal",
    REPO / "matters": WORKER / "src" / "matters",
}

for source, destination in DESTINATIONS.items():
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Vendored {source.relative_to(REPO)} -> {destination.relative_to(REPO)}")
