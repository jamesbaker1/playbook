/* playbook web gym — boots the real playbook_legal python package in
   webassembly and plays full episodes against it. no backend, no api. */

(async function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const bootLog = $("boot-log");
  const matterSelect = $("matter-select");
  const startBtn = $("start-btn");
  const budgetsEl = $("budgets");
  const transcript = $("transcript");
  const docList = $("doc-list");

  let driver = null;
  let stepNo = 0;
  let finished = false;
  let readSections = new Set();
  let submittedLabels = new Set();

  function markProgress(name) {
    const item = document.querySelector(`[data-progress="${name}"]`);
    if (item) item.classList.add("done");
  }

  console.log(
    "%cplaybook",
    "font-weight:bold",
    "— the scoring engine you are playing against is the same python package " +
      "the RL trainer and the benchmark use. no api, no reimplementation. " +
      "download the trace at the end: every point is accounted for. " +
      "engine source: https://github.com/jamesbaker1/playbook"
  );

  function boot(line, replace) {
    if (replace) bootLog.lastChild && bootLog.removeChild(bootLog.lastChild);
    bootLog.appendChild(document.createTextNode((bootLog.childNodes.length ? "\n" : "") + line));
  }

  /* ------------------------------------------------------------- bootstrap */

  let pyodide;
  try {
    pyodide = await loadPyodide();
    boot("python runtime ready");
    boot("loading pyyaml…");
    await pyodide.loadPackage("pyyaml", { messageCallback: () => {} });
    boot("fetching engine + matters…");

    const manifest = await (await fetch("manifest.json")).json();
    const files = manifest.files;
    for (const path of files) {
      const dir = "/site/" + path.split("/").slice(0, -1).join("/");
      pyodide.FS.mkdirTree(dir);
      const text = await (await fetch(path)).text();
      pyodide.FS.writeFile("/site/" + path, text);
    }
    boot(`mounted ${files.length} files`);

    pyodide.runPython("import sys; sys.path.insert(0, '/site'); sys.path.insert(0, '/site/pkg')");
    driver = pyodide.pyimport("driver");
    const matters = JSON.parse(driver.list_matters());
    boot(`playbook_legal imported — ${matters.length} matters, scoring engine live`);

    matterSelect.replaceChildren();
    for (const m of matters) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.id} — ${m.title.toLowerCase()}`;
      matterSelect.appendChild(opt);
    }
    matterSelect.disabled = false;
    startBtn.disabled = false;
    $("welcome-start").disabled = false;
    $("help-start").disabled = false;
    $("boot-status").textContent = `${matters.length} matters ready — choose one or try the guided matter`;
    $("engine-line").textContent =
      `pyodide ${pyodide.version} · playbook_legal 0.2.0 · ${matters.length} matters mounted`;
    boot("pick a matter above and open it.");
  } catch (err) {
    boot("boot failed: " + err);
    throw err;
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
    $("document-view").hidden = !documentMode;
    transcript.hidden = documentMode;
    document.querySelectorAll("#workspace-tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === view);
    });
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

  function doStep(action) {
    if (finished) return null;
    let resp;
    try {
      resp = JSON.parse(driver.step(JSON.stringify(action)));
    } catch (err) {
      addEntry("engine error", null, [el("div", "body error", String(err))]);
      return null;
    }
    stepNo += 1;
    updateBudgets(resp.observation);
    if (resp.terminated || resp.truncated) {
      finished = true;
      disableComposer();
    }
    return resp;
  }

  function readSection(docId, sec, link) {
    const resp = doStep({ type: "read_document", document_id: docId, section: sec });
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      readSections.add(docId + "§" + sec);
      if (link) link.classList.add("read");
      body.push(el("pre", "body doc-text", lr.content));
      $("document-view").replaceChildren(el("pre", "", lr.content));
      $("current-document").textContent = `${docId} §${sec}`;
      showWorkspace("document");
      markProgress("read");
    }
    addEntry(`read ${docId} §${sec}`, resp.reward, body);
    maybeScore(resp);
  }

  function ask(question) {
    const resp = doStep({ type: "ask_client", question });
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [el("div", "body", "q: " + question)];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      body.push(el("div", "body answer", lr.answer));
      markProgress("question");
    }
    addEntry("ask_client", resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
  }

  function search(query) {
    const resp = doStep({ type: "search_matter", query });
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
  }

  function submitIssue(payload) {
    const resp = doStep({ type: "submit_issue", ...payload });
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error + " " + (lr.missing || "")));
    else {
      submittedLabels.add(payload.issue_id);
      markProgress("issue");
      refreshLabels();
      body.push(el("div", "body", `${payload.severity} — ${payload.title}`));
      body.push(el("div", "body", "cites: " + payload.citations.join(", ")));
    }
    addEntry(`submit_issue [${payload.issue_id}]`, resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  function proposeRedline(payload) {
    const resp = doStep({ type: "propose_redline", ...payload });
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error + " " + (lr.missing || "")));
    else {
      body.push(el("pre", "body doc-text", payload.replacement_text));
      markProgress("redline");
    }
    addEntry(`propose_redline [${payload.issue_id}] ${payload.document_id} §${payload.section}`,
      resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  function submitFinal(summary) {
    const resp = doStep({ type: "submit_final", summary });
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
    const big = el("div", "big" + (r.critical_failure ? " capped" : ""),
      Math.round(r.normalized_score * 100) + " / 100");
    block.appendChild(big);
    block.appendChild(el("div", "sub",
      `raw ${r.raw_score} / ${r.max_score}` +
      (r.critical_failure ? " — CRITICAL FAILURE: score capped" : "") +
      (r.truncated ? " — out of steps" : "")));

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
    block.appendChild(table);

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
      $("main").hidden = true;
      $("boot").hidden = false;
      budgetsEl.hidden = true;
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
      document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tabform").forEach((f) => f.classList.remove("active"));
      btn.classList.add("active");
      $("form-" + btn.dataset.tab).classList.add("active");
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

  $("form-ask").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("ask-question").value.trim();
    if (q) { ask(q); $("ask-question").value = ""; }
  });

  $("form-search").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("search-query").value.trim();
    if (q) { search(q); $("search-query").value = ""; }
  });

  $("form-issue").addEventListener("submit", (e) => {
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
    if (submitIssue(payload)) {
      e.target.reset();
      $("quotes").replaceChildren();
    }
  });

  $("form-redline").addEventListener("submit", (e) => {
    e.preventDefault();
    const accepted = proposeRedline({
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
    const warning = submittedLabels.size === 0
      ? "You have not submitted any issues. Submit this final work product anyway?"
      : "Submitting ends this matter and calculates your score. Continue?";
    if (window.confirm(warning)) submitFinal(s);
  });

  /* ---------------------------------------------------------------- start */

  function startMatter() {
    const id = matterSelect.value;
    const payload = JSON.parse(driver.start(id, 0));
    const obs = payload.observation;
    stepNo = 0;
    finished = false;
    readSections = new Set();
    submittedLabels = new Set();
    refreshLabels();
    transcript.replaceChildren();
    $("current-document").textContent = "No section open";
    $("document-view").innerHTML = `<div class="empty-document"><p class="eyebrow">${obs.matter.matter_id}</p><h2>${obs.matter.title}</h2><p><strong>You are:</strong> ${obs.matter.role}</p><p>${obs.matter.assignment}</p><p class="start-hint">Start by opening the supervising-lawyer instructions and playbook from the matter file.</p></div>`;
    showWorkspace("document");
    document.querySelectorAll("#progress li").forEach((item) => item.classList.remove("done"));
    enableComposer();
    renderDocs(obs);
    updateBudgets(obs);
    budgetsEl.hidden = false;
    $("boot").hidden = true;
    $("main").hidden = false;

    const m = obs.matter;
    addEntry("matter opened — " + m.matter_id, null, [
      el("div", "body", m.title),
      el("div", "body", "you are: " + m.role),
      el("div", "body", "assignment: " + m.assignment),
      el("div", "body answer",
        "house rules: cite provisions as 'doc §section', operative provision first. " +
        "quotes must be verbatim — a fabricated quote is a critical failure. " +
        "every client question spends budget. finish before the steps run out."),
    ]);
  }

  startBtn.addEventListener("click", startMatter);
  $("welcome-start").addEventListener("click", () => {
    matterSelect.value = "ai_saas_001";
    startMatter();
  });
  $("help-start").addEventListener("click", () => {
    $("help-dialog").close();
    matterSelect.value = "ai_saas_001";
    startMatter();
  });
  $("help-btn").addEventListener("click", () => $("help-dialog").showModal());
  $("close-help").addEventListener("click", () => $("help-dialog").close());
})();
