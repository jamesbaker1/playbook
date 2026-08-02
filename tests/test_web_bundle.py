"""Smoke-test the web-gym bundle: build the site, then drive the bundled engine
through a full episode exactly as the browser's Pyodide runtime would."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

from conftest import EXAMPLES, ROOT


def test_bundle_builds_and_plays_an_episode(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "dist"
    subprocess.run(
        [sys.executable, str(ROOT / "web" / "build_site.py"), str(out)],
        check=True,
        capture_output=True,
    )

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for path in manifest["files"]:
        assert (out / path).exists(), f"manifest lists missing file: {path}"
    assert "pkg/playbook_legal/env.py" in manifest["files"]
    assert any(p.startswith("matters/ai_saas_001/") for p in manifest["files"])

    # Import the bundled driver against the bundled package, like the browser does.
    monkeypatch.setenv("PLAYBOOK_WEB_MATTERS", str(out / "matters"))
    monkeypatch.syspath_prepend(str(out / "pkg"))
    monkeypatch.syspath_prepend(str(out))
    for name in [m for m in list(sys.modules) if m.startswith("playbook_legal") or m == "driver"]:
        del sys.modules[name]
    driver = importlib.import_module("driver")

    matters = json.loads(driver.list_matters())
    assert len(matters) >= 8

    json.loads(driver.start("ai_saas_001", 7))
    good = (EXAMPLES / "ai_saas_001" / "good.jsonl").read_text(encoding="utf-8").splitlines()
    response: dict = {}
    for line in good:
        if line.strip():
            response = json.loads(driver.step(line))
    assert response["terminated"] is True
    assert response["result"]["normalized_score"] >= 0.9

    trace = json.loads(driver.trace())
    assert trace["matter"] == "ai_saas_001"
    assert len(trace["events"]) == len([line for line in good if line.strip()])

    # Restore the real package for later tests.
    for name in [m for m in list(sys.modules) if m.startswith("playbook_legal") or m == "driver"]:
        del sys.modules[name]
