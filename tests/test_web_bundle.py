"""Smoke-test the web-gym site build.

Kept deliberately architecture-agnostic: the web delivery layer is evolving
(engine-in-browser vs. worker-served), so this only asserts that the build script
runs and produces the core static assets it declares. Episode/scoring correctness
is covered by the environment and driver-independent test suites.
"""

from __future__ import annotations

import shutil
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
    for name in (
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
        ".nojekyll",
    ):
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
    assert 'property="og:title"' in index
    assert 'property="og:image"' in index
    assert 'name="twitter:card"' in index
    assert 'rel="icon"' in index


def test_step_failures_and_busy_state_are_visible_and_retryable(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    subprocess.run(
        [sys.executable, str(ROOT / "web" / "build_site.py"), str(out)],
        check=True,
        capture_output=True,
    )
    app = (out / "app.js").read_text(encoding="utf-8")
    style = (out / "style.css").read_text(encoding="utf-8")

    assert 'showWorkspace("activity")' in app
    assert 'el("button", "retry-step", "retry this action")' in app
    assert "const requestAction = JSON.parse(JSON.stringify(action));" in app
    assert "await retry(requestAction);" in app
    assert "activeSubmit.disabled = true" in app
    assert 'composer.setAttribute("aria-busy", "true")' in app
    assert '#composer[aria-busy="true"] .tabform.active' in style
    assert 'content: "saving\\2026"' in style
    assert "pointer-events: none" in style

    contribute = (out / "contribute.js").read_text(encoding="utf-8")
    assert ".style." not in contribute
    assert 'createElement("br")' not in contribute
    assert 'app_version: "' not in contribute
    assert 'version: "2026-' not in contribute


def test_citation_preflight_assets_are_wired() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    style = (ROOT / "web" / "style.css").read_text(encoding="utf-8")

    assert "knownCitations.add(citation)" in app
    assert "window.PlaybookCitations.checkQuote" in app
    assert '"submit anyway"' in app
    assert '"copy citation"' in app
    assert 'class="insert-section"' in index
    assert '<script src="citation.js"></script>' in index
    assert '<script src="capture.js"></script>' in index
    assert ".field-error" in style and ".hard-warning" in style


def test_semantic_capture_consent_pause_and_attachment() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to verify semantic capture")
    subprocess.run(
        [node, str(ROOT / "tests" / "capture.test.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_consented_capture_auto_contributes_with_deterministic_idempotency() -> None:
    contribute = (ROOT / "web" / "contribute.js").read_text(encoding="utf-8")
    worker = (ROOT / "web" / "worker" / "worker.js").read_text(encoding="utf-8")

    assert "if (captureStatus?.enabled)" in contribute
    assert "automaticUploads.has(captureStatus.session_id)" in contribute
    automatic = contribute.index("if (captureStatus?.enabled)")
    manual_checkbox = contribute.index('consent.type = "checkbox"')
    assert automatic < manual_checkbox
    assert "PlaybookCapture.attachContribution" in contribute[automatic:manual_checkbox]
    assert "trace:contribution:${contributionId}" in worker
    assert "await env.TRACES.get(idempotencyKey)" not in worker
    assert "await env.TRACES.put(idempotencyKey, key)" not in worker


def test_citation_helpers_match_scorer_preflight_contract() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to verify the web citation helpers")
    subprocess.run(
        [node, str(ROOT / "tests" / "citation_helpers.test.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_api_base_query_storage_and_default_precedence() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to verify API endpoint selection")
    subprocess.run(
        [node, str(ROOT / "tests" / "api_base.test.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_escalation_and_negotiation_ui_follow_observation_contract() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    style = (ROOT / "web" / "style.css").read_text(encoding="utf-8")

    assert "Object.keys(obs.action_schemas || {})" in app
    assert 'button.hidden = !available.has(button.dataset.tab)' in app
    assert 'type: "escalate"' in app
    assert 'type: "send_markup"' in app
    assert 'type: "accept_counterparty"' in app
    assert 'Object.entries(obs?.negotiation || {})' in app
    assert 'data-tab="escalate"' in index and 'data-tab="negotiate"' in index
    assert 'id="pending-counters"' in index
    assert ".supervisor-guidance" in style and ".negotiation-chip.countered" in style

    combined = app + index
    assert "CLI-only" not in combined and "cli-only" not in combined


def test_unfinished_work_resume_and_workflow_destinations_are_wired() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    style = (ROOT / "web" / "style.css").read_text(encoding="utf-8")

    assert 'const RESUME_KEY = "playbook.unfinished-episode.v1"' in app
    assert 'window.addEventListener("beforeunload"' in app
    assert "confirmMatterReplacement(id)" in app
    assert "matter_id: episode.matter_id" in app
    assert "seed: episode.seed" in app
    assert "actions: episode.actions" in app
    assert "for (const action of resume.actions)" in app
    assert "clearSavedEpisode();" in app
    assert 'id="resume-dialog"' in index

    ask = app.index("async function ask")
    search = app.index("async function search")
    issue = app.index("async function submitIssue")
    redline = app.index("async function proposeRedline")
    assert 'showWorkspace("activity")' in app[ask:search]
    assert 'showWorkspace("activity")' in app[search:issue]
    assert 'showWorkspace("review")' in app[issue:redline]
    assert 'showWorkspace("review")' in app[redline:app.index("async function escalate")]
    assert 'id="learned-facts"' in index
    assert "renderLearnedFacts(obs)" in app
    assert ".learned-fact" in style


def test_score_screen_diagnoses_failures_and_builds_share_card() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    style = (ROOT / "web" / "style.css").read_text(encoding="utf-8")

    score_helper = (ROOT / "web" / "score.js").read_text(encoding="utf-8")
    fabricated = score_helper.index('title: "Fabricated quotes"')
    invalid = score_helper.index('title: "Invalid citations"')
    assert fabricated < invalid
    assert 'lead: "These quotations could not be verified as verbatim text:"' in score_helper
    assert 'lead: "Correct these citations:"' in score_helper
    assert "for (const value of values)" in app
    assert 'String(value)' in app

    assert "detail.open = true" in app
    assert 'const thead = el("thead")' in app
    assert '["criterion", "event", "points"]' in app
    assert "window.PlaybookScore.humanizeCriterion" in app
    assert 'breakdown.settled_issues || []' in app
    assert 'breakdown.raised_escalations || []' in app

    assert 'canvas.width = 1200' in app
    assert 'canvas.height = 630' in app
    assert '"download card"' in app
    assert '"copy summary"' in app
    assert 'canvas.toBlob' in app and '"image/png"' in app
    assert 'ctx.fillText("playbook"' in app
    assert "card.matterTitle" in app and "card.mode" in app and "card.band" in app
    assert "card.metrics.forEach" in app and "SITE_URL" in app
    assert ".score-integrity" in style and ".score th" in style

    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to verify the score helpers")
    subprocess.run(
        [node, str(ROOT / "tests" / "score_helpers.test.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_attorney_workspace_uses_full_documents_and_selection_driven_work() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    style = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "web-gym.md").read_text(encoding="utf-8")

    assert 'const action = { type: "read_document", document_id: docId };' in app
    assert "documentCache.has(docId)" in app
    assert "cacheDocumentSections(docId, lr.content)" in app
    assert 'data-selection-action="issue"' in index
    assert 'data-selection-action="redline"' in index
    assert "currentSelection = { documentId: currentDocumentId, section" in app
    assert "buildStatusReport()" in app
    assert 'const DRAFT_KEY_PREFIX = "playbook.workspace-draft.v1."' in app
    assert "window.setTimeout(persistWorkspaceDraft, 500)" in app
    assert "window.PlaybookDraftStore.create" in app
    assert "await draftStore.set" in app and "await draftStore.get" in app
    assert "window.PlaybookCapture.create" in app
    assert "window.PlaybookCapture.mountControls" in app
    assert "capture_session_id: window.playbookCaptureSession" in app
    assert "await beginCapture(id, resume?.capture_session_id || null)" in app
    for event_type in (
        "document.opened", "search.submitted", "selection.created",
        "communication.sent", "counterparty.markup_sent",
        "final.submitted", "validation.failed", "transport.error",
    ):
        assert f'capture("{event_type}"' in app
    assert 'sessionId ? "matter.resumed" : "matter.opened"' in app
    assert '"issue.revised" : "issue.saved"' in app
    assert '"redline.revised" : "redline.saved"' in app
    assert ".document-paper" in style and ".selection-tools" in style
    assert "appendInlineMarkdown" in app
    assert 'el("table", "document-table")' in app
    assert 'el(ordered ? "ol" : "ul", "document-list")' in app
    assert ".document-table th" in style and ".document-list li" in style
    assert ".capture-controls" in style and ".capture-status" in style
    assert "saved separately in the browser's IndexedDB" in guide
    assert "local-storage fallback when IndexedDB is unavailable" in guide


def test_workspace_can_edit_and_resume_latest_issue_and_redline_revisions() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'revise_issue: "issue"' in app
    assert 'revise_redline: "redline"' in app
    assert 'actionType = e.target.dataset.revising === "true" ? "revise_issue"' in app
    assert 'actionType = e.target.dataset.revising === "true" ? "revise_redline"' in app
    assert 'submittedRedlines = new Map();' in app
    assert '["submit_issue", "revise_issue"].includes(action.type)' in app
    assert '["propose_redline", "revise_redline"].includes(action.type)' in app
    assert 'submittedIssues.set(action.issue_id, action)' in app
    assert 'submittedRedlines.set(`${action.issue_id}|${action.document_id}|${action.section}`, action)' in app


def test_workspace_draft_store_has_tested_localstorage_fallback() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to verify workspace draft persistence")
    subprocess.run(
        [node, str(ROOT / "tests" / "draft_store.test.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_active_workspace_uses_lawyer_facing_language() -> None:
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "Guided review" in index and "Assessment review" in index
    assert "canonical scoring engine" not in index
    assert "Scored by the canonical" not in index
    assert "connecting to the scoring service" not in index
    assert 'document.createTextNode("review capacity ")' in app
    assert '"guided review"' in app and '"assessment review"' in app
    assert 'addEntry("client reply"' in app
    assert 'addEntry("supervising lawyer reply"' in app
