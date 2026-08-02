/* playbook web gym — static client for the canonical scoring service. */

(async function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const bootLog = $("boot-log");
  const matterSelect = $("matter-select");
  const startBtn = $("start-btn");
  const budgetsEl = $("budgets");
  const transcript = $("transcript");
  const docList = $("doc-list");
  const API_BASE = "https://playbook-engine.james-baker1628.workers.dev";

  let driver = null;
  let stepNo = 0;
  let finished = false;
  let readSections = new Set();
  let submittedLabels = new Set();
  let submittedIssues = new Map();
  let redlinedLabels = new Set();
  let sectionCache = new Map();
  let questionsAsked = 0;
  let stepsRemaining = 0;
  let mobileView = "files";
  let guidedStartPending = false;
  let requestInFlight = false;
  let playMode = "learn";
  function setPlayMode(mode) {
    playMode = mode === "benchmark" ? "benchmark" : "learn";
    window.playbookMode = playMode;
    document.body.classList.toggle("mode-benchmark", playMode === "benchmark");
    document.querySelectorAll('input[name="play-mode"]').forEach((input) => {
      input.checked = input.value === playMode;
      input.closest(".mode-option").classList.toggle("selected", input.checked);
    });
    $("welcome-start").textContent = playMode === "benchmark" ? "Start sealed benchmark" : "Open the guided matter";
    $("mode-badge").textContent = playMode === "benchmark" ? "Benchmark mode" : "Learn mode";
  }
  document.querySelectorAll('input[name="play-mode"]').forEach((input) => {
    input.addEventListener("change", () => setPlayMode(input.value));
  });
  setPlayMode("learn");
  let episode = null;
  const mobileMedia = window.matchMedia("(max-width: 980px)");

  async function api(path, options = {}) {
    const response = await fetch(API_BASE + path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    let payload;
    try { payload = await response.json(); }
    catch (_) { throw new Error(`Scoring service returned ${response.status}.`); }
    if (!response.ok) {
      const detail = typeof payload.error === "object" ? payload.error.message : payload.error;
      throw new Error(detail || `Scoring service returned ${response.status}.`);
    }
    return payload;
  }

  driver = {
    async listMatters() { return api("/api/matters"); },
    async start(matterId, seed) {
      episode = { matter_id: matterId, seed, actions: [], trace: null };
      return api("/api/start", { method: "POST", body: JSON.stringify(episode) });
    },
    async step(action) {
      episode.actions.push(action);
      try {
        const response = await api("/api/step", {
          method: "POST",
          body: JSON.stringify({ matter_id: episode.matter_id, seed: episode.seed, actions: episode.actions }),
        });
        if (response.trace) episode.trace = response.trace;
        return response;
      } catch (error) {
        episode.actions.pop();
        throw error;
      }
    },
    trace() {
      if (!episode?.trace) throw new Error("The trace is available after the matter finishes.");
      return JSON.stringify(episode.trace, null, 2);
    },
  };

  $("welcome-start").disabled = false;
  $("welcome-start").addEventListener("click", () => {
    if (matterSelect.disabled) {
      guidedStartPending = true;
      $("welcome-start").textContent = "Opening when ready…";
      $("boot-status").textContent = "Preparing the guided matter…";
      return;
    }
    matterSelect.value = "ai_saas_001";
    startMatter();
  });

  function markProgress(name) {
    const item = document.querySelector(`[data-progress="${name}"]`);
    if (item) item.classList.add("done");
  }

  console.log(
    "%cplaybook",
    "font-weight:bold",
    "— the scoring engine you are playing against is the same python package " +
      "the RL trainer and benchmark use, served through the canonical API. " +
      "download the trace at the end: every point is accounted for. " +
      "engine source: https://github.com/jamesbaker1/playbook"
  );

  function boot(line, replace) {
    if (replace) bootLog.lastChild && bootLog.removeChild(bootLog.lastChild);
    bootLog.appendChild(document.createTextNode((bootLog.childNodes.length ? "\n" : "") + line));
  }

  /* ------------------------------------------------------------- bootstrap */

  try {
    boot("connecting to scoring service…");
    const response = await driver.listMatters();
    const matters = response.matters;

    matterSelect.replaceChildren();
    for (const m of matters) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.id === "ai_saas_001" ? "starter · " : ""}${m.title.toLowerCase()}`;
      matterSelect.appendChild(opt);
    }
    matterSelect.disabled = false;
    startBtn.disabled = false;
    $("welcome-start").disabled = false;
    $("help-start").disabled = false;
    $("boot-status").textContent = `${matters.length} matters ready — choose one or try the guided matter`;
    $("engine-line").textContent =
      `engine ${response.engine_version} · ${matters.length} matters available`;
    boot("scoring service ready.");
    if (guidedStartPending) {
      matterSelect.value = "ai_saas_001";
      startMatter();
    }
  } catch (err) {
    $("boot-status").textContent = "Scoring service unavailable";
    $("welcome-start").textContent = "Retry connection";
    boot("connection failed: " + err.message);
    $("welcome-start").onclick = () => window.location.reload();
  }

  /* ------------------------------------------------------------ rendering */

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function rewardBadge(reward) {
    const cls = reward > 0 ? "pos" : reward < 0 ? "neg" : "zero";
    const sign = reward > 0 ? "+" : "";
    return el("span", "rew " + cls, sign + reward.toFixed(2));
  }

  function showWorkspace(view) {
    const documentMode = view === "document";
    const reviewMode = view === "review";
    $("document-view").hidden = !documentMode;
    $("review-view").hidden = !reviewMode;
    transcript.hidden = documentMode || reviewMode;
    document.querySelectorAll("#workspace-tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === view);
    });
    if (mobileMedia.matches) setMobileView(view, false);
  }

  function setMobileView(view, chooseWorkspace = true) {
    mobileView = view;
    if (!mobileMedia.matches || $("main").hidden) {
      $("docs").hidden = false;
      $("file").hidden = false;
      $("composer").hidden = false;
      return;
    }
    $("docs").hidden = view !== "files";
    $("file").hidden = !["document", "review", "activity"].includes(view);
    $("composer").hidden = view !== "work";
    if (chooseWorkspace && ["document", "review", "activity"].includes(view)) {
      showWorkspace(view);
    }
    document.querySelectorAll("#mobile-nav button").forEach((button) => {
      if (button.dataset.mobileView === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
  }

  function parseCitation(citation) {
    const match = citation.match(/^\s*(.+?)\s+\u00a7\s*(.+?)\s*$/);
    return match ? { documentId: match[1], section: match[2] } : null;
  }

  function openCitation(citation) {
    const parsed = parseCitation(citation);
    if (!parsed) return;
    const cached = sectionCache.get(`${parsed.documentId}§${parsed.section}`);
    if (cached) {
      $("document-view").replaceChildren(el("pre", "", cached));
      $("current-document").textContent = `${parsed.documentId} §${parsed.section}`;
      showWorkspace("document");
      return;
    }
    if (finished) return;
    readSection(parsed.documentId, parsed.section, null);
  }

  function selectComposerTab(name) {
    document.querySelectorAll("#tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === name);
    });
    document.querySelectorAll(".tabform").forEach((form) => {
      form.classList.toggle("active", form.id === "form-" + name);
    });
    if (mobileMedia.matches) setMobileView("work");
  }

  function draftRedline(issue) {
    const redlineDirty = ["redline-section", "redline-text", "redline-rationale"]
      .some((id) => $(id).value.trim());
    const switchingIssue = $("redline-label").value && $("redline-label").value !== issue.issue_id;
    if (redlineDirty && switchingIssue && !window.confirm("Discard the current redline draft and switch issues?")) return;
    if (redlineDirty && switchingIssue) $("form-redline").reset();
    selectComposerTab("redline");
    $("redline-label").value = issue.issue_id;
    const operative = issue.citations.map(parseCitation).find(Boolean);
    if (operative) {
      const docOption = Array.from($("redline-doc").options)
        .find((option) => option.value === operative.documentId);
      if (docOption && !$("redline-section").value.trim()) {
        $("redline-doc").value = operative.documentId;
        $("redline-section").value = operative.section;
      }
    }
    if (!$("redline-rationale").value.trim()) {
      $("redline-rationale").value = issue.recommendation;
    }
    $("redline-text").focus();
    $("composer").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function renderReview() {
    const list = $("review-list");
    list.replaceChildren();
    $("review-count").textContent = submittedIssues.size;
    if (!submittedIssues.size) {
      const empty = el("div", "empty-review");
      empty.append(el("strong", "", "No issues submitted yet."),
        el("span", "", "Add an issue from the review pane and it will appear here."));
      list.appendChild(empty);
      return;
    }
    for (const issue of submittedIssues.values()) {
      const card = el("article", "issue-card severity-" + issue.severity);
      const head = el("div", "issue-card-head");
      const heading = el("div");
      heading.append(el("span", "issue-meta", issue.severity + " priority \u00b7 " + issue.issue_id),
        el("h3", "", issue.title));
      const status = el("span", "issue-status " + (redlinedLabels.has(issue.issue_id) ? "complete" : ""),
        redlinedLabels.has(issue.issue_id) ? "redline drafted" : "issue submitted");
      head.append(heading, status);
      card.appendChild(head);
      card.append(el("p", "issue-analysis", issue.analysis));
      const recommendation = el("div", "issue-recommendation");
      recommendation.append(el("strong", "", "Recommended position"), el("p", "", issue.recommendation));
      card.appendChild(recommendation);
      const footer = el("div", "issue-card-actions");
      const cites = el("div", "citation-list");
      issue.citations.forEach((citation) => {
        const parsed = parseCitation(citation);
        const cite = el("button", "citation-link", citation);
        cite.type = "button";
        const cached = parsed && sectionCache.has(`${parsed.documentId}§${parsed.section}`);
        cite.disabled = !parsed || (finished && !cached);
        cite.title = parsed ? (cached ? "Open reviewed section" : "Open cited section — costs one step") : "Citation cannot be opened automatically";
        if (parsed) cite.addEventListener("click", () => openCitation(citation));
        cites.appendChild(cite);
      });
      const draft = el("button", "draft-redline", redlinedLabels.has(issue.issue_id) ? "Draft another redline" : "Draft redline");
      draft.type = "button";
      draft.disabled = finished;
      draft.addEventListener("click", () => draftRedline(issue));
      footer.append(cites, draft);
      card.appendChild(footer);
      list.appendChild(card);
    }
  }

  function addEntry(kind, reward, bodyNodes) {
    const entry = el("div", "entry");
    const head = el("div", "entry-head");
    head.appendChild(el("span", "no", String(stepNo).padStart(2, "0")));
    head.appendChild(el("span", "kind", kind));
    if (reward !== null) head.appendChild(rewardBadge(reward));
    entry.appendChild(head);
    for (const node of bodyNodes) entry.appendChild(node);
    transcript.appendChild(entry);
    entry.scrollIntoView({ block: "end", behavior: "smooth" });
    return entry;
  }

  function updateBudgets(obs) {
    const b = obs.budgets;
    const s = b.steps_remaining, q = b.client_questions_remaining;
    stepsRemaining = s;
    budgetsEl.setAttribute("aria-label", `${s} steps remaining; ${q} client questions remaining`);
    budgetsEl.replaceChildren(
      document.createTextNode("steps "),
      s <= 5 ? el("b", "", String(s)) : document.createTextNode(String(s)),
      document.createTextNode(" · questions "),
      q <= 1 ? el("b", "", String(q)) : document.createTextNode(String(q))
    );
  }

  function renderDocs(obs) {
    docList.replaceChildren();
    for (const doc of obs.documents) {
      const wrap = el("div", "doc");
      wrap.appendChild(el("span", "doc-title", doc.title.toLowerCase()));
      const secs = el("div", "sections");
      for (const sec of doc.sections) {
        const a = el("a", readSections.has(doc.id + "§" + sec) ? "read" : "", "§" + sec);
        a.href = "#";
        a.addEventListener("click", (e) => {
          e.preventDefault();
          if (!finished) readSection(doc.id, sec, a);
        });
        secs.appendChild(a);
      }
      wrap.appendChild(secs);
      docList.appendChild(wrap);
    }
    const rd = $("redline-doc");
    rd.replaceChildren();
    for (const doc of obs.documents) {
      const opt = document.createElement("option");
      opt.value = doc.id;
      opt.textContent = doc.id;
      rd.appendChild(opt);
    }
  }

  /* ------------------------------------------------------------- episode */

  async function doStep(action) {
    if (finished || requestInFlight) return null;
    requestInFlight = true;
    $("composer").setAttribute("aria-busy", "true");
    let resp;
    try {
      resp = await driver.step(action);
    } catch (err) {
      addEntry("engine error", null, [el("div", "body error", String(err))]);
      return null;
    } finally {
      requestInFlight = false;
      $("composer").removeAttribute("aria-busy");
    }
    stepNo += 1;
    updateBudgets(resp.observation);
    if (resp.terminated || resp.truncated) {
      finished = true;
      disableComposer();
    }
    return resp;
  }

  async function readSection(docId, sec, link) {
    const resp = await doStep({ type: "read_document", document_id: docId, section: sec });
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      readSections.add(docId + "§" + sec);
      if (link) link.classList.add("read");
      body.push(el("pre", "body doc-text", lr.content));
      $("document-view").replaceChildren(el("pre", "", lr.content));
      sectionCache.set(`${docId}§${sec}`, lr.content);
      $("current-document").textContent = `${docId} §${sec}`;
      showWorkspace("document");
      markProgress("read");
    }
    addEntry(`read ${docId} §${sec}`, resp.reward, body);
    maybeScore(resp);
  }

  async function ask(question) {
    const resp = await doStep({ type: "ask_client", question });
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [el("div", "body", "q: " + question)];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      body.push(el("div", "body answer", lr.answer));
      questionsAsked += 1;
      markProgress("question");
    }
    addEntry("ask_client", resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function search(query) {
    const resp = await doStep({ type: "search_matter", query });
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else if (!lr.hits.length) body.push(el("div", "body", `"${query}" — no hits`));
    else {
      const list = el("div", "body");
      for (const h of lr.hits) {
        list.appendChild(el("div", "", `${h.document_id} §${h.section} — …${h.snippet}…`));
      }
      body.push(list);
    }
    addEntry(`search "${query}"`, resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function submitIssue(payload) {
    const resp = await doStep({ type: "submit_issue", ...payload });
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error + " " + (lr.missing || "")));
    else {
      submittedLabels.add(payload.issue_id);
      submittedIssues.set(payload.issue_id, payload);
      markProgress("issue");
      refreshLabels();
      renderReview();
      body.push(el("div", "body", `${payload.severity} — ${payload.title}`));
      body.push(el("div", "body", "cites: " + payload.citations.join(", ")));
    }
    addEntry(`submit_issue [${payload.issue_id}]`, resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function proposeRedline(payload) {
    const resp = await doStep({ type: "propose_redline", ...payload });
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error + " " + (lr.missing || "")));
    else {
      body.push(el("pre", "body doc-text", payload.replacement_text));
      markProgress("redline");
      redlinedLabels.add(payload.issue_id);
      renderReview();
    }
    addEntry(`propose_redline [${payload.issue_id}] ${payload.document_id} §${payload.section}`,
      resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function submitFinal(summary) {
    const resp = await doStep({ type: "submit_final", summary });
    if (!resp) return;
    addEntry("submit_final", resp.reward, [el("div", "body", summary)]);
    showWorkspace("activity");
    markProgress("finish");
    maybeScore(resp);
  }

  function maybeScore(resp) {
    if (!resp.result) return;
    const r = resp.result;
    const block = el("div", "score");
    const percent = Math.round(r.normalized_score * 100);
    const band = percent >= 85 ? "Strong review" : percent >= 70 ? "Sound foundation" :
      percent >= 50 ? "Developing review" : "Needs another pass";
    block.appendChild(el("p", "eyebrow", "PERFORMANCE BRIEF"));
    block.appendChild(el("h2", "score-title", band));
    const big = el("div", "big" + (r.critical_failure ? " capped" : ""),
      percent + " / 100");
    block.appendChild(big);
    block.appendChild(el("div", "sub",
      `raw ${r.raw_score} / ${r.max_score}` +
      (r.critical_failure ? " — CRITICAL FAILURE: score capped" : "") +
      (r.truncated ? " — out of steps" : "")));

    const breakdown = r.breakdown;
    const issueCount = breakdown.matched_issues.length;
    const redlineCount = breakdown.matched_redlines.length;
    const submittedCount = submittedIssues.size;
    const citationTotal = breakdown.valid_citation_count + breakdown.invalid_citations.length;
    const citationRate = citationTotal ? Math.round(100 * breakdown.valid_citation_count / citationTotal) : 0;
    const metrics = el("div", "score-metrics");
    for (const [value, label] of [
      [`${issueCount}/${submittedCount || 0}`, "supported issues"],
      [`${redlineCount}/${issueCount || 0}`, "issues redlined"],
      [`${citationRate}%`, "valid citations"],
      [String(r.steps), "steps used"],
    ]) {
      const card = el("div", "score-metric");
      card.append(el("strong", "", value), el("span", "", label));
      metrics.appendChild(card);
    }
    block.appendChild(metrics);

    const feedback = el("div", "score-feedback");
    const strengths = [];
    const focus = [];
    if (issueCount) strengths.push(`${issueCount} material issue${issueCount === 1 ? "" : "s"} grounded in the rubric.`);
    if (citationRate === 100 && citationTotal) strengths.push("Every submitted citation was valid.");
    if (redlineCount === issueCount && issueCount) strengths.push("Every credited issue was carried through to drafting.");
    if (breakdown.fabricated_quotes.length === 0) strengths.push("No quotation-integrity problems.");
    if (breakdown.unsupported_issues.length) focus.push(`${breakdown.unsupported_issues.length} submitted issue${breakdown.unsupported_issues.length === 1 ? " was" : "s were"} not sufficiently supported.`);
    if (breakdown.invalid_citations.length) focus.push(`Correct ${breakdown.invalid_citations.length} invalid citation${breakdown.invalid_citations.length === 1 ? "" : "s"}.`);
    if (redlineCount < issueCount) focus.push(`Draft operative language for ${issueCount - redlineCount} credited issue${issueCount - redlineCount === 1 ? "" : "s"}.`);
    const finalEvent = [...breakdown.reward_events].reverse().find((event) => event.type === "final_submission");
    if (finalEvent?.missing_issues?.length) focus.push(`The final update omitted ${finalEvent.missing_issues.length} material issue${finalEvent.missing_issues.length === 1 ? "" : "s"}.`);
    if (r.critical_failure) focus.unshift("Address the critical error before refining lower-priority work.");
    if (!focus.length) focus.push(percent >= 85 ? "Try a sealed benchmark next." : "Tighten analysis and drafting language to capture the remaining points.");
    for (const [title, items] of [["What worked", strengths.slice(0, 3)], ["Next focus", focus.slice(0, 3)]]) {
      const panel = el("section", "feedback-panel");
      panel.appendChild(el("h3", "", title));
      const list = el("ul");
      for (const item of items.length ? items : ["Complete another matter to establish a pattern."]) list.appendChild(el("li", "", item));
      panel.appendChild(list);
      feedback.appendChild(panel);
    }
    block.appendChild(feedback);

    block.appendChild(el("details", "score-detail"));
    const detail = block.lastChild;
    detail.appendChild(el("summary", "", "See the complete scoring audit"));

    const table = el("table");
    for (const ev of r.breakdown.reward_events) {
      const row = el("tr");
      row.appendChild(el("td", "", ev.type.replaceAll("_", " ")));
      row.appendChild(el("td", "", ev.criterion));
      const pts = el("td", "pts", (ev.points > 0 ? "+" : "") + ev.points.toFixed(2));
      pts.style.color = ev.points > 0 ? "var(--green)" : ev.points < 0 ? "var(--red)" : "var(--muted)";
      row.appendChild(pts);
      table.appendChild(row);
    }
    detail.appendChild(table);

    const actions = el("div", "actions-row");
    const dl = el("button", "", "download trace");
    dl.addEventListener("click", () => {
      const blob = new Blob([driver.trace()], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `playbook_trace_${r.matter_id}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    const again = el("button", "", "choose another matter");
    again.addEventListener("click", () => {
      document.body.classList.remove("matter-active");
      $("main").hidden = true;
      $("boot").hidden = false;
      budgetsEl.hidden = true;
      $("mode-badge").hidden = true;
      setPlayMode(playMode);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    actions.appendChild(dl);
    actions.appendChild(again);
    block.appendChild(actions);
    if (window.playbookContribute) window.playbookContribute(r, actions, () => driver.trace());
    transcript.appendChild(block);
    block.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  /* ------------------------------------------------------------- composer */

  function disableComposer() {
    document.querySelectorAll("#composer input, #composer textarea, #composer select, #composer button")
      .forEach((n) => (n.disabled = true));
  }

  function enableComposer() {
    document.querySelectorAll("#composer input, #composer textarea, #composer select, #composer button")
      .forEach((n) => (n.disabled = false));
  }

  function refreshLabels() {
    const dl = $("redline-label");
    dl.replaceChildren();
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = submittedLabels.size ? "Choose a submitted issue" : "Submit an issue first";
    dl.appendChild(prompt);
    for (const label of submittedLabels) {
      const opt = document.createElement("option");
      opt.value = label;
      dl.appendChild(opt);
    }
  }

  document.querySelectorAll("#tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectComposerTab(btn.dataset.tab);
    });
  });

  document.querySelectorAll("#workspace-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => showWorkspace(btn.dataset.view));
  });

  $("add-quote").addEventListener("click", () => {
    const row = el("div", "quote-row");
    const cite = document.createElement("input");
    cite.placeholder = "citation, e.g. msa §4.2";
    cite.className = "q-cite";
    const text = document.createElement("textarea");
    text.rows = 2;
    text.placeholder = "exact text from that section";
    text.className = "q-text";
    const rm = el("button", "remove", "remove");
    rm.type = "button";
    rm.addEventListener("click", () => row.remove());
    row.append(cite, text, rm);
    $("quotes").appendChild(row);
  });

  $("form-ask").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("ask-question").value.trim();
    if (q && await ask(q)) $("ask-question").value = "";
  });

  $("form-search").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("search-query").value.trim();
    if (q && await search(q)) $("search-query").value = "";
  });

  $("form-issue").addEventListener("submit", async (e) => {
    e.preventDefault();
    const quotes = [];
    document.querySelectorAll(".quote-row").forEach((row) => {
      const citation = row.querySelector(".q-cite").value.trim();
      const text = row.querySelector(".q-text").value.trim();
      if (citation && text) quotes.push({ citation, text });
    });
    const payload = {
      issue_id: $("issue-label").value.trim(),
      title: $("issue-title").value.trim(),
      severity: $("issue-severity").value,
      citations: $("issue-citations").value.split("\n").map((s) => s.trim()).filter(Boolean),
      analysis: $("issue-analysis").value.trim(),
      recommendation: $("issue-recommendation").value.trim(),
    };
    if (quotes.length) payload.quotes = quotes;
    if (await submitIssue(payload)) {
      e.target.reset();
      $("quotes").replaceChildren();
    }
  });

  $("form-redline").addEventListener("submit", async (e) => {
    e.preventDefault();
    const accepted = await proposeRedline({
      issue_id: $("redline-label").value.trim(),
      document_id: $("redline-doc").value,
      section: $("redline-section").value.trim().replace(/^§\s*/, ""),
      replacement_text: $("redline-text").value.trim(),
      rationale: $("redline-rationale").value.trim(),
    });
    if (accepted) e.target.reset();
  });

  $("form-finish").addEventListener("submit", (e) => {
    e.preventDefault();
    const s = $("final-summary").value.trim();
    if (!s) return;
    renderFinishPreflight();
    $("finish-dialog").showModal();
  });

  function renderFinishPreflight() {
    const sealed = playMode === "benchmark";
    $("finish-title").textContent = sealed ? "Submit this sealed attempt?" : "Ready to finish this review?";
    $("finish-confirm").textContent = sealed ? "Submit benchmark" : "Submit and see score";
    const rows = [
      ["Sections reviewed", readSections.size],
      ["Client questions asked", questionsAsked],
      ["Issues submitted", submittedIssues.size],
      ["Issues with draft language", `${redlinedLabels.size} of ${submittedIssues.size}`],
      ["Steps remaining", stepsRemaining],
    ];
    const checklist = $("finish-checklist");
    checklist.hidden = sealed;
    checklist.replaceChildren();
    rows.forEach(([label, value]) => {
      const row = el("div", "finish-row");
      row.append(el("span", "", label), el("strong", "", String(value)));
      checklist.appendChild(row);
    });
    const warnings = [];
    if (!readSections.size) warnings.push("You have not reviewed any provisions.");
    if (!submittedIssues.size) warnings.push("You have not submitted any issues. Your score may be very low.");
    const highWithoutDraft = Array.from(submittedIssues.values())
      .filter((issue) => ["high", "critical"].includes(issue.severity) && !redlinedLabels.has(issue.issue_id));
    if (highWithoutDraft.length) warnings.push(`${highWithoutDraft.length} high-priority issue(s) have no draft language. Confirm that is intentional.`);
    if (stepsRemaining <= 3) warnings.push(`Only ${stepsRemaining} steps remain.`);
    if (!warnings.length) warnings.push("No obvious workflow gaps found. This check does not assess legal correctness.");
    $("finish-warnings").hidden = sealed;
    $("finish-warnings").replaceChildren(...warnings.map((message) => el("p", "", message)));
  }

  $("finish-back").addEventListener("click", () => $("finish-dialog").close());
  $("finish-confirm").addEventListener("click", async () => {
    const summary = $("final-summary").value.trim();
    if (!summary) return;
    $("finish-dialog").close();
    await submitFinal(summary);
  });

  document.querySelectorAll("#mobile-nav button").forEach((button) => {
    button.addEventListener("click", () => setMobileView(button.dataset.mobileView));
  });
  mobileMedia.addEventListener("change", () => setMobileView(mobileView));

  /* ---------------------------------------------------------------- start */

  async function startMatter() {
    const id = matterSelect.value;
    startBtn.disabled = true;
    let payload;
    try {
      payload = await driver.start(id, 0);
    } catch (error) {
      $("boot-status").textContent = "Could not open matter";
      boot("request failed: " + error.message);
      return;
    } finally {
      startBtn.disabled = false;
    }
    const obs = payload.observation;
    stepNo = 0;
    finished = false;
    readSections = new Set();
    submittedLabels = new Set();
    submittedIssues = new Map();
    redlinedLabels = new Set();
    sectionCache = new Map();
    questionsAsked = 0;
    document.querySelectorAll(".tabform").forEach((form) => form.reset());
    $("quotes").replaceChildren();
    refreshLabels();
    renderReview();
    transcript.replaceChildren();
    $("current-document").textContent = "No section open";
    const empty = el("div", "empty-document");
    empty.append(el("p", "eyebrow", obs.matter.matter_id), el("h2", "", obs.matter.title));
    const role = el("p");
    role.append(el("strong", "", "You are: "), document.createTextNode(obs.matter.role));
    empty.append(role, el("p", "", obs.matter.assignment));
    if (id === "ai_saas_001") empty.append(el("p", "matter-time", "Starter matter · about 15–20 minutes · 30-step limit"));
    if (playMode === "learn") empty.append(el("p", "start-hint", "Start by opening the supervising-lawyer instructions and playbook from the matter file."));
    $("document-view").replaceChildren(empty);
    showWorkspace("document");
    document.querySelectorAll("#progress li").forEach((item) => item.classList.remove("done"));
    enableComposer();
    renderDocs(obs);
    updateBudgets(obs);
    budgetsEl.hidden = false;
    $("boot").hidden = true;
    $("main").hidden = false;
    document.body.classList.add("matter-active");
    $("mode-badge").hidden = false;
    window.scrollTo(0, 0);
    setMobileView("files");

    const m = obs.matter;
    addEntry("matter opened — " + m.matter_id, null, [
      el("div", "body", m.title),
      el("div", "body", "you are: " + m.role),
      el("div", "body", "assignment: " + m.assignment),
      ...(playMode === "learn" ? [el("div", "body answer",
        "house rules: cite provisions as 'doc §section', operative provision first. " +
        "quotes must be verbatim — a fabricated quote is a critical failure. " +
        "every client question spends budget. finish before the steps run out.")] : []),
    ]);
  }

  startBtn.addEventListener("click", startMatter);
  $("help-start").addEventListener("click", () => {
    $("help-dialog").close();
    setPlayMode("learn");
    matterSelect.value = "ai_saas_001";
    startMatter();
  });
  $("help-btn").addEventListener("click", () => $("help-dialog").showModal());
  $("close-help").addEventListener("click", () => $("help-dialog").close());
})();
