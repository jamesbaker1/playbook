"""Smoke-test the web-gym site build.

Kept deliberately architecture-agnostic: the web delivery layer is evolving
(engine-in-browser vs. worker-served), so this only asserts that the build script
runs and produces the core static assets it declares. Episode/scoring correctness
is covered by the environment and driver-independent test suites.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import ROOT


def test_site_build_produces_declared_assets(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    subprocess.run(
        [sys.executable, str(ROOT / "web" / "build_site.py"), str(out)],
        check=True,
        capture_output=True,
    )
    for name in ("index.html", "style.css", "app.js", "contribute.js", ".nojekyll"):
        assert (out / name).exists(), f"missing built asset: {name}"

    # Hidden facts, rubrics, and Python runtime code belong only in the engine Worker.
    forbidden = ["manifest.json", "driver.py", "pkg", "matters"]
    for name in forbidden:
        assert not (out / name).exists(), f"private engine asset leaked into site: {name}"
    index = (out / "index.html").read_text(encoding="utf-8").lower()
    app = (out / "app.js").read_text(encoding="utf-8").lower()
    assert "pyodide" not in index
    assert "loadpyodide" not in app
    assert "hidden_facts" not in app
