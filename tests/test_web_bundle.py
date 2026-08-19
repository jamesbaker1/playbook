"""Smoke-test the web-gym site build.

Kept deliberately architecture-agnostic: the web delivery layer is evolving
(engine-in-browser vs. worker-served), so this only asserts that the build script
runs and produces the core static assets it declares. Episode/scoring correctness
is covered by the environment and driver-independent test suites.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import ROOT

POSTS_SRC = ROOT / "docs" / "posts"


def _build_site(out: Path) -> Path:
    subprocess.run(
        [sys.executable, str(ROOT / "web" / "build_site.py"), str(out)],
        check=True,
        capture_output=True,
    )
    return out


def _build_site_module():
    """The renderer itself, for tests that need to build a synthetic corpus."""
    sys.path.insert(0, str(ROOT / "web"))
    try:
        import build_site
    finally:
        sys.path.pop(0)
    return build_site


def _front_matter(path: Path) -> dict[str, str]:
    """The post's front matter, as raw ``key: value`` strings.

    Deliberately re-parsed here rather than imported: the assertions below are
    checking that the renderer moved the author's metadata onto the page, so the
    test reads that metadata a different way than the code under test does.
    """
    raw = path.read_text(encoding="utf-8-sig")
    assert raw.startswith("---"), f"{path.name}: post must open with '---' front matter"
    _, front_matter, _ = raw.split("---", 2)
    fields = {}
    for line in front_matter.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


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


def test_markdown_posts_render_to_static_pages(tmp_path: Path) -> None:
    """Every post in docs/posts gets a page, driven by what is actually there.

    Nothing here names a slug: the placeholder post is expected to be deleted the
    moment real writing lands, and this suite has to keep passing when it is.
    """
    out = _build_site(tmp_path / "dist")

    sources = sorted(POSTS_SRC.glob("*.md"))
    assert sources, "expected at least one markdown post in docs/posts"
    index = (out / "posts" / "index.html").read_text(encoding="utf-8")

    for source in sources:
        page = out / "posts" / f"{source.stem}.html"
        assert page.exists(), f"unrendered post: {source.name}"
        post = page.read_text(encoding="utf-8")
        meta = _front_matter(source)
        title = html.escape(meta["title"])

        assert f"<h1>{title}</h1>" in post, f"{source.name}: title missing from the page"
        assert f"<title>{title} — playbook</title>" in post
        assert 'property="og:type" content="article"' in post
        assert (
            'property="og:image" content="https://jamesbaker1.github.io/playbook/og-card.png"'
            in post
        )
        # A post that was published elsewhere first names that home in front
        # matter; the rest point at their own page.
        canonical = (
            meta.get("canonical")
            or f"https://jamesbaker1.github.io/playbook/posts/{source.stem}.html"
        )
        assert f'rel="canonical" href="{canonical}"' in post
        assert f'property="og:url" content="{canonical}"' in post
        assert 'rel="icon"' in post and 'href="../style.css"' in post

        # Front matter is metadata, never body copy — in the page or the index.
        assert not post.lstrip().startswith("---")
        for key, value in meta.items():
            assert f"{key}: {value}" not in post, f"{source.name}: front matter leaked into page"
            assert f"{key}: {value}" not in index, f"{source.name}: front matter leaked into index"

        # The index lists this post, by title, linking to its page.
        assert f'<a href="{source.stem}.html">{title}</a>' in index, (
            f"{source.name}: missing from the writing index"
        )
        assert html.escape(meta["description"]) in index

    landing = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="posts/"' in landing
    assert (out / "posts.css").exists()


def test_renderer_supports_the_markdown_elements_posts_rely_on(tmp_path: Path) -> None:
    """Element coverage lives on a synthetic post, so real posts stay free to
    use whatever subset of markdown they need."""
    build_site = _build_site_module()
    posts_dir = tmp_path / "posts-src"
    posts_dir.mkdir()
    (posts_dir / "sample.md").write_text(
        "---\ntitle: Sample\ndate: 2026-01-02\ndescription: Elements.\n---\n\n"
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "```python\nprint(1)\n```\n\n"
        "> quoted\n\n"
        "[a link](../)\n",
        encoding="utf-8",
    )

    out = tmp_path / "dist"
    build_site.build_posts(out, posts_dir)
    post = (out / "posts" / "sample.html").read_text(encoding="utf-8")

    assert "<table>" in post and "<pre>" in post and "<blockquote>" in post
    assert 'class="table-scroll"' in post


def test_canonical_front_matter_overrides_the_self_url(tmp_path: Path) -> None:
    """``canonical:`` moves the canonical link and og:url; everything else stays local."""
    build_site = _build_site_module()
    posts_dir = tmp_path / "posts-src"
    posts_dir.mkdir()
    (posts_dir / "syndicated.md").write_text(
        "---\ntitle: Syndicated\ndate: 2026-01-02\ndescription: Published elsewhere first.\n"
        "canonical: https://example.com/blog/syndicated/\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (posts_dir / "local.md").write_text(
        "---\ntitle: Local\ndate: 2026-01-03\ndescription: Published only here.\n---\n\nBody.\n",
        encoding="utf-8",
    )

    out = tmp_path / "dist"
    build_site.build_posts(out, posts_dir)

    syndicated = (out / "posts" / "syndicated.html").read_text(encoding="utf-8")
    assert 'rel="canonical" href="https://example.com/blog/syndicated/"' in syndicated
    assert 'property="og:url" content="https://example.com/blog/syndicated/"' in syndicated
    assert "<title>Syndicated — playbook</title>" in syndicated
    assert 'name="description" content="Published elsewhere first."' in syndicated

    local = (out / "posts" / "local.html").read_text(encoding="utf-8")
    self_url = f"{build_site.SITE_URL}posts/local.html"
    assert f'rel="canonical" href="{self_url}"' in local
    assert f'property="og:url" content="{self_url}"' in local

    # The writing index links the page built here, never the canonical host.
    index = (out / "posts" / "index.html").read_text(encoding="utf-8")
    assert '<a href="syndicated.html">Syndicated</a>' in index
    assert "example.com" not in index


def test_post_pages_load_katex_and_leave_math_delimiters_intact(tmp_path: Path) -> None:
    """Math is rendered client-side, so the build's job is to ship the loader and
    hand KaTeX its delimiters unmangled."""
    build_site = _build_site_module()
    posts_dir = tmp_path / "posts-src"
    posts_dir.mkdir()
    (posts_dir / "math.md").write_text(
        "---\ntitle: Math\ndate: 2026-01-02\ndescription: Formulas.\n---\n\n"
        "Display:\n\n$$x = \\frac{a}{b}$$\n\n"
        "Inline \\(s = \\sum_{i=1}^{n} w_i c_i\\) mid-sentence.\n\n"
        "Prose naming the delimiter, `$$`, is not math.\n",
        encoding="utf-8",
    )

    out = tmp_path / "dist"
    build_site.build_posts(out, posts_dir)
    post = (out / "posts" / "math.html").read_text(encoding="utf-8")

    version = build_site.KATEX_VERSION
    assert f"katex@{version}/dist/katex.min.css" in post
    assert f"katex@{version}/dist/katex.min.js" in post
    assert f"katex@{version}/dist/contrib/auto-render.min.js" in post
    assert "renderMathInElement(" in post
    assert post.count("integrity=\"sha384-") == 3, "each pinned KaTeX asset needs an SRI hash"

    # Delimiters survive markdown; KaTeX consumes them in the browser.
    assert "$$x = \\frac{a}{b}$$" in post
    assert "\\(s = \\sum_{i=1}^{n} w_i c_i\\)" in post
    # Markdown must not have eaten the backslashes or read _ as emphasis.
    assert "<em>" not in post
    assert "(s = " not in post.replace("\\(s = ", "")
    # A delimiter merely mentioned in a code span stays code, not math.
    assert "<code>$$</code>" in post

    # The gym and the writing index carry no math and must not pay for KaTeX.
    assert "katex" not in (out / "posts" / "index.html").read_text(encoding="utf-8").lower()
    assert "katex" not in (ROOT / "web" / "index.html").read_text(encoding="utf-8").lower()


def test_post_figures_are_copied_and_resolve_from_a_post_page(tmp_path: Path) -> None:
    build_site = _build_site_module()
    posts_dir = tmp_path / "posts-src"
    (posts_dir / "assets").mkdir(parents=True)
    (posts_dir / "assets" / "figure.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2"></svg>', encoding="utf-8"
    )
    (posts_dir / "figured.md").write_text(
        "---\ntitle: Figured\ndate: 2026-01-02\ndescription: With a figure.\n---\n\n"
        "![A caption](assets/figure.svg)\n",
        encoding="utf-8",
    )

    out = tmp_path / "dist"
    build_site.build_posts(out, posts_dir)

    copied = out / "posts" / "assets" / "figure.svg"
    assert copied.exists(), "post assets were not copied into the build"
    post = (out / "posts" / "figured.html").read_text(encoding="utf-8")
    assert '<img alt="A caption" src="assets/figure.svg"' in post
    # The page sits at posts/<slug>.html, so the relative src resolves to the copy.
    assert (out / "posts" / "figured.html").parent.joinpath("assets/figure.svg").exists()


def test_real_post_assets_ship_with_the_site(tmp_path: Path) -> None:
    """Whatever is in docs/posts/assets reaches the build, glob-driven."""
    out = _build_site(tmp_path / "dist")
    sources = [path for path in POSTS_SRC.glob("assets/**/*") if path.is_file()]
    assert sources, "expected at least one file in docs/posts/assets"
    for source in sources:
        relative = source.relative_to(POSTS_SRC / "assets")
        assert (out / "posts" / "assets" / relative).exists(), f"asset not shipped: {relative}"

    # Every asset a post embeds must be one the build actually copied.
    for page in (out / "posts").glob("*.html"):
        text = page.read_text(encoding="utf-8")
        for name in re.findall(r'<img[^>]+src="assets/([^"]+)"', text):
            assert (out / "posts" / "assets" / name).exists(), (
                f"{page.name} embeds a missing asset: {name}"
            )


def test_post_index_survives_an_empty_posts_directory(tmp_path: Path) -> None:
    build_site = _build_site_module()

    out = tmp_path / "dist"
    empty = tmp_path / "no-posts"
    empty.mkdir()
    assert build_site.build_posts(out, empty) == []
    index = (out / "posts" / "index.html").read_text(encoding="utf-8")
    assert "nothing published yet" in index


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
