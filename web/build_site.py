"""Assemble the static web-gym site into an output directory.

Bundles the web assets, the actual playbook_legal package source, and every public
matter, plus a manifest the browser uses to mount them into the Pyodide filesystem.

    python web/build_site.py dist
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"

ASSETS = ["index.html", "style.css", "app.js", "contribute.js", "driver.py"]


def build(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    for name in ASSETS:
        shutil.copy2(WEB / name, out_dir / name)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    files: list[str] = ["driver.py"]

    pkg_out = out_dir / "pkg" / "playbook_legal"
    pkg_out.mkdir(parents=True)
    for source in sorted((REPO / "src" / "playbook_legal").glob("*.py")):
        shutil.copy2(source, pkg_out / source.name)
        files.append(f"pkg/playbook_legal/{source.name}")

    for matter_dir in sorted((REPO / "matters").iterdir()):
        if not (matter_dir / "matter.yaml").exists():
            continue
        for source in sorted(matter_dir.rglob("*")):
            if source.is_dir():
                continue
            relative = source.relative_to(REPO).as_posix()
            destination = out_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            files.append(relative)

    (out_dir / "manifest.json").write_text(
        json.dumps({"files": files}, indent=2), encoding="utf-8"
    )
    print(f"{out_dir}: {len(files)} files in manifest")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "dist"))
