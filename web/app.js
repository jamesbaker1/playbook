// SPDX-License-Identifier: AGPL-3.0-only
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
  const API_BASE = window.PlaybookApiBase.resolve({
    search: window.location.search,
    storage: window.localStorage,
  });
  const draftStore = window.PlaybookDraftStore.create({
    indexedDB: window.indexedDB,
    storage: window.localStorage,
  });
  const RESUME_KEY = "playbook.unfinished-episode.v1";
  const DRAFT_KEY_PREFIX = "playbook.workspace-draft.v1.";
  const SITE_URL = "jamesbaker1.github.io/playbook";
  const capturePolicy = fetch("policy.json", { cache: "no-cache" })
    .then((response) => response.ok ? response.json() : null).catch(() => null);

  let driver = null;
  let stepNo = 0;
  let finished = false;
  let readSections = new Set();
  let submittedLabels = new Set();
  let submittedIssues = new Map();
  let submittedRedlines = new Map();
  let redlinedLabels = new Set();
  let sectionCache = new Map();
  let documentCache = new Map();
  let currentDocumentId = null;
  let currentSelection = null;
  let draftTimer = null;
  let captureControls = null;
  let knownCitations = new Set();
  let questionsAsked = 0;
  let stepsRemaining = 0;
  let mobileView = "files";
  let guidedStartPending = false;
  let requestInFlight = false;
  let playMode = "learn";
  let nextStepAction = null;
  let starterPayload = null;
  let currentObservation = null;
  let refusedNegotiations = new Set();
  let matterActive = false;
  let savedResume = null;
  const matterTitles = new Map();
  const ACTION_TABS = {
    ask_client: "ask", search_matter: "search", submit_issue: "issue",
    revise_issue: "issue", propose_redline: "redline", revise_redline: "redline",
    escalate: "escalate", send_markup: "negotiate",
    accept_counterparty: "negotiate", submit_final: "finish",
  };

  function capture(type, target = {}, data = {}, durationMs) {
    return window.playbookCaptureSession?.record(type, target, data, durationMs);
  }

  async function beginCapture(matterId, sessionId = null) {
    const policy = await capturePolicy;
    if (!policy?.consent_version || !window.PlaybookCapture) return;
    captureControls?.element?.remove();
    window.playbookCaptureSession = window.PlaybookCapture.create({
      storage: window.localStorage,
      consentVersion: policy.consent_version,
      matterId,
      engineVersion: window.playbookAppVersion || "unknown",
      ...(sessionId ? { sessionId } : {}),
    });
    captureControls = window.PlaybookCapture.mountControls(document.querySelector("header"), window.playbookCaptureSession);
    let openedRecorded = false;
    window.playbookCaptureSession.onStatus((status) => {
      if (status.enabled && !openedRecorded) {
        openedRecorded = true;
        capture(sessionId ? "matter.resumed" : "matter.opened", {}, { mode: playMode });
      }
    });
  }
  function setPlayMode(mode) {
    playMode = mode === "benchmark" ? "benchmark" : "learn";
    window.playbookMode = playMode;
    document.body.classList.toggle("mode-benchmark", playMode === "benchmark");
    document.querySelectorAll('input[name="play-mode"]').forEach((input) => {
      input.checked = input.value === playMode;
      input.closest(".mode-option").classList.toggle("selected", input.checked);
    });
    $("welcome-start").textContent = playMode === "benchmark" ? "start assessment review" : "start guided review";
    $("mode-badge").textContent = playMode === "benchmark" ? "assessment review" : "guided review";
  }
  document.querySelectorAll('input[name="play-mode"]').forEach((input) => {
    input.addEventListener("change", () => setPlayMode(input.value));
  });
  setPlayMode("learn");
  let episode = null;
  const mobileMedia = window.matchMedia("(max-width: 980px)");

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    let response;
    try {
      response = await fetch(API_BASE + path, {
        ...options,
        signal: options.signal || controller.signal,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      });
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The workspace took too long to respond. Please retry.");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
    let payload;
    try { payload = await response.json(); }
    catch (_) { throw new Error(`Workspace service returned ${response.status}.`); }
    if (!response.ok) {
      const detail = typeof payload.error === "object" ? payload.error.message : payload.error;
      throw new Error(detail || `Workspace service returned ${response.status}.`);
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
    activate(matterId, seed) {
      episode = { matter_id: matterId, seed, actions: [], trace: null };
    },
  };

  function savedEpisode() {
    try {
      const saved = JSON.parse(window.localStorage.getItem(RESUME_KEY));
      if (!saved || saved.version !== 1 || typeof saved.matter_id !== "string" ||
          !Number.isInteger(saved.seed) || !Array.isArray(saved.actions)) return null;
      return saved;
    } catch (_) {
      return null;
    }
  }

  function persistEpisode() {
    if (!matterActive || finished || !episode) return;
    try {
      window.localStorage.setItem(RESUME_KEY, JSON.stringify({
        version: 1,
        matter_id: episode.matter_id,
        seed: episode.seed,
        mode: playMode,
        actions: episode.actions,
        capture_session_id: window.playbookCaptureSession?.status?.().session_id || null,
      }));
    } catch (_) {
      // Storage can be disabled or full; the live matter remains usable.
    }
  }

  function draftKey() {
    return episode?.matter_id ? DRAFT_KEY_PREFIX + episode.matter_id : null;
  }

  async function persistWorkspaceDraft() {
    const key = draftKey();
    if (!key || !matterActive || finished) return;
    const fields = {};
    document.querySelectorAll("#composer input[id], #composer textarea[id], #composer select[id]")
      .forEach((field) => { fields[field.id] = field.value; });
    try {
      await draftStore.set(key, { version: 1, fields, currentDocumentId });
      $("save-status").hidden = false;
      $("save-status").textContent = "saved locally";
      const active = document.querySelector("#composer .tabform.active");
      const typeByForm = {
        "form-ask": "communication.draft_updated", "form-escalate": "communication.draft_updated",
        "form-negotiate": "counterparty.draft_updated", "form-issue": "issue.draft_updated",
        "form-redline": "redline.draft_updated", "form-finish": "final.draft_updated",
      };
      const eventType = typeByForm[active?.id];
      if (eventType) {
        const snapshot = {};
        active.querySelectorAll("input[id], textarea[id], select[id]").forEach((field) => {
          if (field.value) snapshot[field.id] = field.value;
        });
        if (Object.keys(snapshot).length) capture(eventType, {
          document_id: currentSelection?.documentId,
          section: currentSelection?.section,
          issue_id: snapshot["issue-label"] || snapshot["redline-label"] || snapshot["markup-label"],
        }, { snapshot });
      }
    } catch (_) {
      $("save-status").hidden = false;
      $("save-status").textContent = "save unavailable";
    }
  }

  function queueDraftSave() {
    if (!matterActive || finished) return;
    $("save-status").hidden = false;
    $("save-status").textContent = "saving…";
    window.clearTimeout(draftTimer);
    draftTimer = window.setTimeout(persistWorkspaceDraft, 500);
  }

  async function restoreWorkspaceDraft() {
    const key = draftKey();
    if (!key) return null;
    try {
      const saved = await draftStore.get(key);
      if (!saved || saved.version !== 1 || !saved.fields) return null;
      Object.entries(saved.fields).forEach(([id, value]) => {
        const field = $(id);
        if (field && typeof value === "string") field.value = value;
      });
      $("save-status").hidden = false;
      $("save-status").textContent = "draft restored";
      return typeof saved.currentDocumentId === "string" ? saved.currentDocumentId : null;
    } catch (_) { return null; }
  }

  function clearSavedEpisode() {
    try { window.localStorage.removeItem(RESUME_KEY); } catch (_) { /* optional storage */ }
    savedResume = null;
  }

  function confirmMatterReplacement(nextMatterId) {
    if (!matterActive || finished) return true;
    const target = nextMatterId && episode?.matter_id !== nextMatterId
      ? ` and switch to ${nextMatterId}` : "";
    return window.confirm(`Discard your unfinished ${episode?.matter_id || "matter"} review${target}?`);
  }

  window.addEventListener("beforeunload", (event) => {
    if (!matterActive || finished) return;
    event.preventDefault();
    event.returnValue = "";
  });

  // Warm the canonical starter while the matter list loads. A cold Python Worker
  // can take several seconds; parallelizing these requests removes a second wait.
  const starterWarmup = driver.start("ai_saas_001", 0)
    .then((payload) => { starterPayload = payload; return payload; })
    .catch(() => null);

  $("welcome-start").disabled = false;
  $("welcome-start").addEventListener("click", () => {
    if (matterSelect.disabled) {
      guidedStartPending = true;
      $("welcome-start").disabled = true;
      $("welcome-start").textContent = "connecting…";
      $("boot-status").textContent = "preparing the matter — a few seconds…";
      return;
    }
    matterSelect.value = "ai_saas_001";
    startMatter();
  });

  function markProgress(name) {
    const item = document.querySelector(`[data-progress="${name}"]`);
    if (item) item.classList.add("done");
  }

  function boot(line, replace) {
    if (replace) bootLog.lastChild && bootLog.removeChild(bootLog.lastChild);
    bootLog.appendChild(document.createTextNode((bootLog.childNodes.length ? "\n" : "") + line));
  }

  /* ------------------------------------------------------------- bootstrap */

  try {
    boot("preparing matter service…");
    const response = await driver.listMatters();
    const matters = response.matters;

    matterSelect.replaceChildren();
    for (const m of matters) {
      matterTitles.set(m.id, m.title);
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.id === "ai_saas_001" ? "starter · " : ""}${m.title.toLowerCase()}`;
      matterSelect.appendChild(opt);
    }
    matterSelect.disabled = false;
    startBtn.disabled = false;
    $("welcome-start").disabled = false;
    $("help-start").disabled = false;
    $("boot-status").textContent = `${matters.length} matters ready — choose one or start the guided review`;
    $("engine-line").textContent = `${matters.length} matters available`;
    window.playbookAppVersion = response.engine_version;
    boot("workspace ready.");
    if (guidedStartPending) {
      matterSelect.value = "ai_saas_001";
      await startMatter();
    }
    savedResume = savedEpisode();
    if (savedResume && matters.some((matter) => matter.id === savedResume.matter_id)) {
      $("resume-copy").textContent = `Resume ${savedResume.matter_id} with ${savedResume.actions.length} saved review action${savedResume.actions.length === 1 ? "" : "s"}?`;
      $("resume-dialog").showModal();
    } else if (savedResume) {
      clearSavedEpisode();
    }
  } catch (err) {
    $("boot-status").textContent = "workspace temporarily unavailable";
    $("welcome-start").textContent = "retry connection";
    $("welcome-start").disabled = false;
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
    return window.PlaybookCitations.parseCitation(citation);
  }

  function clearFieldErrors(id) {
    $(id).replaceChildren();
  }

  function addFieldError(container, message, suggestion, applySuggestion) {
    const row = el("div", "field-error");
    row.appendChild(el("span", "", message));
    if (suggestion) {
      const fix = el("button", "normalize-citation", `use ${suggestion}`);
      fix.type = "button";
      fix.addEventListener("click", applySuggestion);
      row.appendChild(fix);
    }
    container.appendChild(row);
  }

  function validateCitationLines() {
    const input = $("issue-citations");
    const errors = $("issue-citation-errors");
    clearFieldErrors("issue-citation-errors");
    const lines = input.value.split("\n");
    let valid = true;
    lines.forEach((line, index) => {
      if (!line.trim()) return;
      const result = window.PlaybookCitations.validateCitation(line, knownCitations);
      if (result.valid) return;
      valid = false;
      addFieldError(errors, `Line ${index + 1}: ${result.error}`, result.suggestion, () => {
        const current = input.value.split("\n");
        current[index] = result.suggestion;
        input.value = current.join("\n");
        validateCitationLines();
        input.focus();
      });
    });
    input.setAttribute("aria-invalid", String(!valid));
    if (!valid) capture("validation.failed", {}, { form: "issue", field: "citations" });
    return valid;
  }

  function sectionNumber(heading) {
    const match = String(heading).trim().match(/^(?:section\s+)?([0-9]+(?:\.[0-9]+)*)\b/i);
    return match ? match[1] : null;
  }

  function contentHash(value) {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return `fnv1a-${(hash >>> 0).toString(16).padStart(8, "0")}`;
  }

  function cacheDocumentSections(documentId, content) {
    const lines = String(content).split(/\r?\n/);
    let active = null;
    let buffer = [];
    const commit = () => {
      if (active) sectionCache.set(`${documentId} §${active}`, buffer.join("\n").trim());
    };
    for (const line of lines) {
      const heading = line.match(/^#{2,6}\s+(.+)$/);
      const next = heading && sectionNumber(heading[1]);
      if (next) {
        commit();
        active = next;
        buffer = [line];
      } else if (active) buffer.push(line);
    }
    commit();
  }

  function appendInlineMarkdown(parent, value) {
    const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
    let cursor = 0;
    for (const match of String(value).matchAll(pattern)) {
      if (match.index > cursor) parent.appendChild(document.createTextNode(value.slice(cursor, match.index)));
      const token = match[0];
      if (token.startsWith("**")) parent.appendChild(el("strong", "", token.slice(2, -2)));
      else if (token.startsWith("*")) parent.appendChild(el("em", "", token.slice(1, -1)));
      else parent.appendChild(el("code", "", token.slice(1, -1)));
      cursor = match.index + token.length;
    }
    if (cursor < value.length) parent.appendChild(document.createTextNode(value.slice(cursor)));
  }

  function tableCells(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  }

  function renderDocument(documentId, content, targetSection = null) {
    currentDocumentId = documentId;
    const canvas = $("document-view");
    const article = el("div", "document-paper");
    let currentSection = null;
    let paragraph = [];
    const flushParagraph = () => {
      if (!paragraph.length) return;
      const p = el("p", "document-paragraph");
      appendInlineMarkdown(p, paragraph.join(" ").trim());
      if (currentSection) p.dataset.section = currentSection;
      article.appendChild(p);
      paragraph = [];
    };
    const lines = String(content).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        const level = Math.min(heading[1].length + 1, 6);
        const title = heading[2].trim();
        const section = sectionNumber(title);
        if (section) currentSection = section;
        const node = el(`h${level}`, "document-heading");
        appendInlineMarkdown(node, title);
        if (currentSection) {
          node.dataset.section = currentSection;
          node.id = `section-${documentId}-${currentSection.replaceAll(".", "-")}`;
        }
        article.appendChild(node);
        continue;
      }
      const nextLine = lines[index + 1] || "";
      if (line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(nextLine)) {
        flushParagraph();
        const table = el("table", "document-table");
        if (currentSection) table.dataset.section = currentSection;
        const head = el("thead");
        const headerRow = el("tr");
        tableCells(line).forEach((cell) => {
          const th = el("th"); appendInlineMarkdown(th, cell); headerRow.appendChild(th);
        });
        head.appendChild(headerRow); table.appendChild(head);
        const body = el("tbody");
        index += 2;
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          const row = el("tr");
          tableCells(lines[index]).forEach((cell) => {
            const td = el("td"); appendInlineMarkdown(td, cell); row.appendChild(td);
          });
          body.appendChild(row);
          index += 1;
        }
        index -= 1;
        table.appendChild(body); article.appendChild(table);
        continue;
      }
      const listItem = line.match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
      if (listItem) {
        flushParagraph();
        const ordered = Boolean(listItem[2]);
        const list = el(ordered ? "ol" : "ul", "document-list");
        if (currentSection) list.dataset.section = currentSection;
        while (index < lines.length) {
          const item = lines[index].match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
          if (!item || Boolean(item[2]) !== ordered) break;
          const li = el("li"); appendInlineMarkdown(li, item[3].trim()); list.appendChild(li);
          index += 1;
        }
        index -= 1;
        article.appendChild(list);
        continue;
      }
      if (!line.trim()) flushParagraph();
      else paragraph.push(line.trim());
    }
    flushParagraph();
    canvas.replaceChildren(article);
    $("current-document").textContent = documentId;
    showWorkspace("document");
    const target = targetSection && article.querySelector(`[data-section="${CSS.escape(targetSection)}"]`);
    if (target) {
      target.scrollIntoView({ block: "start", behavior: "smooth" });
      target.classList.add("citation-target");
      window.setTimeout(() => target.classList.remove("citation-target"), 1800);
    }
    queueDraftSave();
    capture("document.viewed", { document_id: documentId, section: targetSection }, { cached: true });
  }

  function openCitation(citation) {
    const parsed = parseCitation(citation);
    if (!parsed) return;
    const cachedDocument = documentCache.get(parsed.documentId);
    if (cachedDocument) {
      renderDocument(parsed.documentId, cachedDocument, parsed.section);
      return;
    }
    if (finished) return;
    readDocument(parsed.documentId, parsed.section);
  }

  function selectComposerTab(name) {
    const requested = document.querySelector(`#tabs button[data-tab="${name}"]`);
    if (requested?.disabled) return;
    document.querySelectorAll("#tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === name);
    });
    document.querySelectorAll(".tabform").forEach((form) => {
      form.classList.toggle("active", form.id === "form-" + name);
    });
    if (mobileMedia.matches) setMobileView("work");
  }

  function firstUnreadSection(documentId) {
    return document.querySelector(`.sections a[data-document="${documentId}"]:not(.read)`);
  }

  function hasReadDocument(documentId) {
    return [...readSections].some((key) => key.startsWith(documentId + "§"));
  }

  function updateNextStep() {
    const redlineTab = document.querySelector('#tabs button[data-tab="redline"]');
    redlineTab.disabled = submittedIssues.size === 0 || finished;
    redlineTab.title = submittedIssues.size ? "draft language for a submitted issue" : "submit an issue first";
    if (finished || playMode !== "learn") return;

    let title, copy, label, action;
    const instructions = firstUnreadSection("instructions");
    const playbook = firstUnreadSection("playbook");
    const undrafted = [...submittedIssues.values()].find((issue) => !redlinedLabels.has(issue.issue_id));
    if (instructions && !hasReadDocument("instructions")) {
      title = "start with context";
      copy = "Read the supervising-lawyer instructions before reviewing contract language.";
      label = "open instructions";
      action = () => instructions.click();
    } else if (playbook && !hasReadDocument("playbook")) {
      title = "learn the client position";
      copy = "Open the playbook so you can compare the contract against the approved position.";
      label = "open playbook";
      action = () => playbook.click();
    } else if (questionsAsked === 0) {
      title = "resolve a decision-changing fact";
      copy = "Ask one focused question that could change the advice or negotiating position.";
      label = "ask the client";
      action = () => { selectComposerTab("ask"); $("ask-question").focus(); };
    } else if (!submittedIssues.size) {
      title = "record the first material issue";
      copy = "Connect the contract language, client playbook, and business consequence.";
      label = "add an issue";
      action = () => { selectComposerTab("issue"); $("issue-label").focus(); };
    } else if (undrafted && stepsRemaining > 5) {
      title = "turn analysis into language";
      copy = `Draft an operative fix for “${undrafted.title}.”`;
      label = "draft the redline";
      action = () => draftRedline(undrafted);
    } else {
      title = stepsRemaining <= 5 ? "finish the priority work" : "review and close the loop";
      copy = "Check your submitted issues, then give the supervising lawyer a concise priority update.";
      label = "review and finish";
      action = () => { showWorkspace("review"); selectComposerTab("finish"); };
    }
    $("next-step-title").textContent = title;
    $("next-step-copy").textContent = copy;
    $("next-step-action").textContent = label;
    nextStepAction = action;
  }

  $("next-step-action").addEventListener("click", () => nextStepAction?.());

  function draftRedline(issue) {
    const redlineDirty = ["redline-section", "redline-text", "redline-rationale"]
      .some((id) => $(id).value.trim());
    const switchingIssue = $("redline-label").value && $("redline-label").value !== issue.issue_id;
    if (redlineDirty && switchingIssue && !window.confirm("Discard the current redline draft and switch issues?")) return;
    if (switchingIssue) {
      $("form-redline").reset();
      resetRevisionForms();
    }
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
    const latest = operative && submittedRedlines.get(`${issue.issue_id}|${operative.documentId}|${operative.section}`);
    if (latest) {
      $("form-redline").dataset.revising = "true";
      $("redline-label").disabled = true;
      $("redline-doc").disabled = true;
      $("redline-section").readOnly = true;
      $("redline-text").value = latest.replacement_text;
      $("redline-rationale").value = latest.rationale;
      $("form-redline").querySelector("button[type='submit']").textContent = "save revised language";
    }
    $("redline-text").focus();
    $("composer").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function editIssue(issue) {
    const switchingIssue = $("form-issue").dataset.revising === "true" &&
      $("issue-label").value && $("issue-label").value !== issue.issue_id;
    const issueDirty = ["issue-title", "issue-citations", "issue-analysis", "issue-recommendation"]
      .some((id) => $(id).value.trim());
    if (switchingIssue && issueDirty && !window.confirm("Discard the current issue edits and switch issues?")) return;
    if (switchingIssue) {
      $("form-issue").reset();
      $("quotes").replaceChildren();
      resetRevisionForms();
    }
    selectComposerTab("issue");
    $("form-issue").dataset.revising = "true";
    $("issue-label").value = issue.issue_id;
    $("issue-label").readOnly = true;
    $("issue-title").value = issue.title;
    $("issue-severity").value = issue.severity;
    $("issue-citations").value = issue.citations.join("\n");
    $("issue-analysis").value = issue.analysis;
    $("issue-recommendation").value = issue.recommendation;
    $("quotes").replaceChildren();
    (issue.quotes || []).forEach((quote) => {
      $("add-quote").click();
      const row = $("quotes").lastElementChild;
      row.querySelector(".q-cite").value = quote.citation;
      row.querySelector(".q-text").value = quote.text;
    });
    $("form-issue").querySelector("button[type='submit']").textContent = "save issue changes";
    $("issue-title").focus();
  }

  function resetRevisionForms() {
    delete $("form-issue").dataset.revising;
    $("issue-label").readOnly = false;
    $("form-issue").querySelector("button[type='submit']").textContent = "submit issue";
    delete $("form-redline").dataset.revising;
    $("redline-label").disabled = false;
    $("redline-doc").disabled = false;
    $("redline-section").readOnly = false;
    $("form-redline").querySelector("button[type='submit']").textContent = "propose redline";
  }

  function renderReview() {
    const list = $("review-list");
    list.replaceChildren();
    $("review-count").textContent = submittedIssues.size;
    if (!submittedIssues.size) {
      const empty = el("div", "empty-review");
      empty.append(el("strong", "", "no issues submitted yet."),
        el("span", "", "add an issue from the review pane and it will appear here."));
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
      const negotiationEnabled = Object.hasOwn(currentObservation?.action_schemas || {}, "send_markup");
      const negotiation = currentObservation?.negotiation?.[issue.issue_id];
      if (negotiationEnabled) {
        const display = negotiationDisplay(issue.issue_id, negotiation);
        head.appendChild(el("span", `negotiation-chip ${display.cls}`, display.label));
      }
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
        const cached = parsed && sectionCache.has(`${parsed.documentId} §${parsed.section}`);
        cite.disabled = !parsed || (finished && !cached);
        cite.title = parsed ? (cached ? "Open reviewed section" : "Open cited document") : "Citation cannot be opened automatically";
        if (parsed) cite.addEventListener("click", () => openCitation(citation));
        cites.appendChild(cite);
      });
      const controls = el("div", "issue-card-buttons");
      const edit = el("button", "edit-issue", "Edit issue");
      edit.type = "button";
      edit.disabled = finished;
      edit.addEventListener("click", () => editIssue(issue));
      const draft = el("button", "draft-redline", redlinedLabels.has(issue.issue_id) ? "Edit draft language" : "Draft change");
      draft.type = "button";
      draft.disabled = finished;
      draft.addEventListener("click", () => draftRedline(issue));
      controls.append(edit, draft);
      footer.append(cites, controls);
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
    const parts = [document.createTextNode("review capacity "),
      s <= 5 ? el("b", "", String(s)) : document.createTextNode(String(s)),
      document.createTextNode(" · client questions "),
      q <= 1 ? el("b", "", String(q)) : document.createTextNode(String(q))];
    const labels = [`${s} review actions available`, `${q} client questions available`];
    if (Object.hasOwn(b, "escalations_remaining")) {
      parts.push(document.createTextNode(" · supervisor requests "), el("b", "", String(b.escalations_remaining)));
      labels.push(`${b.escalations_remaining} supervisor requests available`);
    }
    if (Object.hasOwn(b, "negotiation_rounds_remaining")) {
      parts.push(document.createTextNode(" · counterparty exchanges "), el("b", "", String(b.negotiation_rounds_remaining)));
      labels.push(`${b.negotiation_rounds_remaining} counterparty exchanges available`);
    }
    budgetsEl.setAttribute("aria-label", labels.join("; "));
    budgetsEl.replaceChildren(...parts);
  }

  function renderLearnedFacts(obs) {
    const list = $("learned-facts-list");
    const facts = Object.entries(obs?.learned_facts || {});
    list.replaceChildren();
    if (!facts.length) {
      list.appendChild(el("p", "learned-facts-empty", "Ask the client or supervising counsel to add verified facts here."));
      return;
    }
    for (const [key, value] of facts) {
      const fact = el("dl", "learned-fact");
      fact.append(el("dt", "", key.replaceAll("_", " ")), el("dd", "", String(value)));
      list.appendChild(fact);
    }
  }

  function configureActionTabs(obs) {
    const available = new Set(Object.keys(obs.action_schemas || {}).map((name) => ACTION_TABS[name]).filter(Boolean));
    document.querySelectorAll("#tabs button[data-tab]").forEach((button) => {
      button.hidden = !available.has(button.dataset.tab);
    });
    if (!document.querySelector("#tabs button.active:not([hidden])")) {
      selectComposerTab(document.querySelector("#tabs button:not([hidden])")?.dataset.tab);
    }
  }

  function renderDocs(obs) {
    docList.replaceChildren();
    knownCitations = new Set();
    currentObservation = obs;
    renderLearnedFacts(obs);
    refusedNegotiations = new Set();
    for (const doc of obs.documents) {
      const wrap = el("div", "doc");
      const title = el("div", "doc-heading");
      const open = el("button", "doc-title", doc.title);
      open.type = "button";
      open.addEventListener("click", () => {
        if (documentCache.has(doc.id)) renderDocument(doc.id, documentCache.get(doc.id));
        else if (!finished) readDocument(doc.id);
      });
      title.append(open, el("code", "doc-id", doc.id));
      wrap.appendChild(title);
      const secs = el("div", "sections");
      for (const sec of doc.sections) {
        const citation = `${doc.id} §${sec}`;
        knownCitations.add(citation);
        const section = el("span", "section-actions");
        const a = el("a", readSections.has(doc.id + "§" + sec) ? "read" : "", "§" + sec);
        a.href = "#";
        a.dataset.document = doc.id;
        a.dataset.section = sec;
        a.addEventListener("click", (e) => {
          e.preventDefault();
          if (documentCache.has(doc.id)) renderDocument(doc.id, documentCache.get(doc.id), sec);
          else if (!finished) readDocument(doc.id, sec);
        });
        const copy = el("button", "copy-citation", "copy citation");
        copy.type = "button";
        copy.title = `Copy ${citation}`;
        copy.setAttribute("aria-label", `Copy citation ${citation}`);
        copy.addEventListener("click", async () => {
          await navigator.clipboard.writeText(citation);
          copy.textContent = "copied";
          window.setTimeout(() => { copy.textContent = "copy citation"; }, 1200);
        });
        section.append(a, copy);
        secs.appendChild(section);
      }
      wrap.appendChild(secs);
      docList.appendChild(wrap);
    }
    const rd = $("redline-doc");
    const md = $("markup-doc");
    rd.replaceChildren();
    md.replaceChildren();
    for (const doc of obs.documents) {
      const opt = document.createElement("option");
      opt.value = doc.id;
      opt.textContent = doc.id;
      rd.appendChild(opt);
      md.appendChild(opt.cloneNode(true));
    }
  }

  /* ------------------------------------------------------------- episode */

  async function doStep(action, retry) {
    if (finished || requestInFlight) return null;
    // Keep a transport-safe snapshot so a retry cannot pick up later form or object mutations.
    const requestAction = JSON.parse(JSON.stringify(action));
    requestInFlight = true;
    $("save-status").hidden = false;
    $("save-status").textContent = "sending…";
    const composer = $("composer");
    const activeSubmit = composer.querySelector(".tabform.active button[type='submit']");
    const submitWasDisabled = activeSubmit ? activeSubmit.disabled : false;
    composer.setAttribute("aria-busy", "true");
    if (activeSubmit) activeSubmit.disabled = true;
    let resp;
    try {
      resp = await driver.step(requestAction);
    } catch (err) {
      $("save-status").hidden = false;
      $("save-status").textContent = "needs attention";
      capture("transport.error", {}, { action_type: requestAction.type, message: String(err) });
      const retryButton = el("button", "retry-step", "retry this action");
      retryButton.type = "button";
      retryButton.addEventListener("click", async () => {
        if (requestInFlight || finished) return;
        retryButton.disabled = true;
        await retry(requestAction);
      });
      addEntry("service unavailable", null, [
        el("div", "body error", String(err)),
        retryButton,
      ]);
      showWorkspace("activity");
      return null;
    } finally {
      requestInFlight = false;
      composer.removeAttribute("aria-busy");
      if (activeSubmit && !finished) activeSubmit.disabled = submitWasDisabled;
    }
    stepNo += 1;
    currentObservation = resp.observation;
    renderLearnedFacts(resp.observation);
    configureActionTabs(resp.observation);
    updateBudgets(resp.observation);
    if (resp.terminated || resp.truncated) {
      capture("matter.completed", {}, { action_type: requestAction.type, truncated: Boolean(resp.truncated) });
      window.playbookCaptureSession?.complete?.();
      finished = true;
      matterActive = false;
      clearSavedEpisode();
      draftStore.delete(draftKey());
      $("save-status").textContent = "delivered";
      disableComposer();
    } else {
      persistEpisode();
      persistWorkspaceDraft();
    }
    return resp;
  }

  async function readDocument(docId, targetSection = null) {
    if (documentCache.has(docId)) {
      renderDocument(docId, documentCache.get(docId), targetSection);
      return true;
    }
    const action = { type: "read_document", document_id: docId };
    const resp = await doStep(action, (retryAction) =>
      readDocument(retryAction.document_id, targetSection));
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      const descriptor = currentObservation.documents.find((doc) => doc.id === docId);
      (descriptor?.sections || []).forEach((sec) => readSections.add(docId + "§" + sec));
      document.querySelectorAll(`.sections a[data-document="${CSS.escape(docId)}"]`)
        .forEach((link) => link.classList.add("read"));
      body.push(el("pre", "body doc-text", lr.content));
      documentCache.set(docId, lr.content);
      cacheDocumentSections(docId, lr.content);
      capture("document.opened", { document_id: docId, section: targetSection }, { cached: false });
      renderDocument(docId, lr.content, targetSection);
      markProgress("read");
    }
    addEntry(`opened ${docId}`, resp.reward, body);
    updateNextStep();
    maybeScore(resp);
    return !lr.error;
  }

  async function ask(question) {
    const action = { type: "ask_client", question };
    const resp = await doStep(action, (retryAction) => ask(retryAction.question));
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [el("div", "body", "q: " + question)];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      body.push(el("div", "body answer", lr.answer));
      questionsAsked += 1;
      markProgress("question");
      capture("communication.sent", {}, { recipient: "client", question, answered: true });
    }
    addEntry("client reply", resp.reward, body);
    showWorkspace("activity");
    updateNextStep();
    maybeScore(resp);
    return !lr.error;
  }

  async function search(query) {
    capture("search.submitted", {}, { query });
    const action = { type: "search_matter", query };
    const resp = await doStep(action, (retryAction) => search(retryAction.query));
    if (!resp) return;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else if (!lr.hits.length) body.push(el("div", "body", `"${query}" — no hits`));
    else {
      const list = el("div", "body");
      for (const h of lr.hits) {
        const hit = el("button", "search-hit");
        hit.type = "button";
        hit.append(el("strong", "", `${h.document_id} §${h.section}`), el("span", "", `…${h.snippet}…`));
        hit.addEventListener("click", () => {
          capture("search.result_opened", { document_id: h.document_id, section: h.section }, { query });
          openCitation(`${h.document_id} §${h.section}`);
        });
        list.appendChild(hit);
      }
      body.push(list);
    }
    addEntry(`search "${query}"`, resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function submitIssue(payload, actionType = "submit_issue") {
    const action = { type: actionType, ...payload };
    const resp = await doStep(action, (retryAction) => submitIssue(retryAction, retryAction.type));
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error + " " + (lr.missing || "")));
    else {
      submittedLabels.add(payload.issue_id);
      submittedIssues.set(payload.issue_id, payload);
      capture(actionType === "revise_issue" ? "issue.revised" : "issue.saved", { issue_id: payload.issue_id }, { severity: payload.severity, citations: payload.citations });
      markProgress("issue");
      refreshLabels();
      renderNegotiation(resp.observation);
      renderReview();
      body.push(el("div", "body", `${payload.severity} — ${payload.title}`));
      body.push(el("div", "body", "cites: " + payload.citations.join(", ")));
    }
    addEntry(`${actionType === "revise_issue" ? "issue updated" : "issue saved"} · ${payload.issue_id}`, resp.reward, body);
    showWorkspace("review");
    updateNextStep();
    maybeScore(resp);
    return !lr.error;
  }

  async function proposeRedline(payload, actionType = "propose_redline") {
    const action = { type: actionType, ...payload };
    const resp = await doStep(action, (retryAction) => proposeRedline(retryAction, retryAction.type));
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [];
    if (lr.error) body.push(el("div", "body error", lr.error + " " + (lr.missing || "")));
    else {
      body.push(el("pre", "body doc-text", payload.replacement_text));
      markProgress("redline");
      redlinedLabels.add(payload.issue_id);
      submittedRedlines.set(`${payload.issue_id}|${payload.document_id}|${payload.section}`, payload);
      capture(actionType === "revise_redline" ? "redline.revised" : "redline.saved", { document_id: payload.document_id, section: payload.section, issue_id: payload.issue_id }, {
        replacement_text: payload.replacement_text, rationale: payload.rationale,
      });
      renderReview();
    }
    addEntry(`${actionType === "revise_redline" ? "draft updated" : "draft saved"} · ${payload.issue_id} · ${payload.document_id} §${payload.section}`,
      resp.reward, body);
    showWorkspace("review");
    updateNextStep();
    maybeScore(resp);
    return !lr.error;
  }

  async function escalate(topic, reason) {
    const resp = await doStep({ type: "escalate", topic, reason }, (action) => escalate(action.topic, action.reason));
    if (!resp) return false;
    const lr = resp.observation.last_result;
    const body = [el("div", "body", topic)];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      body.push(el("div", "body supervisor-guidance", lr.guidance));
      capture("communication.sent", {}, { recipient: "supervising_lawyer", topic, reason, answered: true });
    }
    addEntry("supervising lawyer reply", resp.reward, body);
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function sendMarkup(payload) {
    const resp = await doStep({ type: "send_markup", ...payload }, (action) => sendMarkup(action));
    if (!resp) return false;
    const lr = resp.observation.last_result;
    if (lr.response === "rejected") refusedNegotiations.add(payload.issue_id);
    else refusedNegotiations.delete(payload.issue_id);
    const body = [el("pre", "body doc-text", payload.proposed_text)];
    if (lr.error) body.push(el("div", "body error", lr.error));
    else {
      body.push(el("div", "body counterparty-response", lr.message));
      if (lr.counter_text) body.push(el("pre", "body counter-text", lr.counter_text));
      capture("counterparty.markup_sent", {
        document_id: payload.document_id, section: payload.section, issue_id: payload.issue_id,
      }, { proposed_text: payload.proposed_text, response: lr.response });
    }
    addEntry(`counterparty response · ${payload.issue_id}`, resp.reward, body);
    renderNegotiation(resp.observation);
    renderReview();
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  async function acceptCounterparty(issueId) {
    const resp = await doStep({ type: "accept_counterparty", issue_id: issueId }, (action) => acceptCounterparty(action.issue_id));
    if (!resp) return false;
    const lr = resp.observation.last_result;
    addEntry(`counterparty language accepted · ${issueId}`, resp.reward, [
      el("div", lr.error ? "body error" : "body counterparty-response", lr.error || lr.message),
    ]);
    if (!lr.error) capture("counterparty.accepted", { issue_id: issueId }, {});
    renderNegotiation(resp.observation);
    renderReview();
    showWorkspace("activity");
    maybeScore(resp);
    return !lr.error;
  }

  function negotiationDisplay(label, state) {
    if (state?.status === "closed") return { label: "settled", cls: "settled" };
    if (refusedNegotiations.has(label)) return { label: "refused", cls: "refused" };
    if (state?.last_counter_text) return { label: "countered", cls: "countered" };
    return { label: "open", cls: "open" };
  }

  function renderNegotiation(obs = currentObservation) {
    const holder = $("pending-counters");
    holder.replaceChildren();
    for (const [label, state] of Object.entries(obs?.negotiation || {})) {
      if (state.status === "closed" || !state.last_counter_text) continue;
      const card = el("article", "pending-counter");
      card.append(el("strong", "", `${label} · counterparty proposal`), el("pre", "", state.last_counter_text));
      if (Object.hasOwn(obs.action_schemas || {}, "accept_counterparty")) {
        const accept = el("button", "accept-counter", "accept counterparty language");
        accept.type = "button";
        accept.addEventListener("click", () => acceptCounterparty(label));
        card.appendChild(accept);
      }
      holder.appendChild(card);
    }
  }

  async function submitFinal(summary) {
    capture("final.submitted", {}, { summary });
    const action = { type: "submit_final", summary };
    const resp = await doStep(action, (retryAction) => submitFinal(retryAction.summary));
    if (!resp) return;
    addEntry("status report delivered", resp.reward, [el("div", "body", summary)]);
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
    const settledCount = (breakdown.settled_issues || []).length;
    const escalationCount = (breakdown.raised_escalations || []).length;
    const metrics = el("div", "score-metrics");
    for (const [value, label] of [
      [`${issueCount}/${submittedCount || 0}`, "supported issues"],
      [`${redlineCount}/${issueCount || 0}`, "issues redlined"],
      [`${citationRate}%`, "valid citations"],
      [String(r.steps), "steps used"],
      [String(settledCount), "issues settled"],
      [String(escalationCount), "escalations raised"],
    ]) {
      const card = el("div", "score-metric");
      card.append(el("strong", "", value), el("span", "", label));
      metrics.appendChild(card);
    }
    block.appendChild(metrics);

    const integrity = el("div", "score-integrity");
    function appendIntegrityList(title, lead, values, className) {
      const section = el("section", `integrity-panel ${className}`);
      section.append(el("h3", "", title), el("p", "", lead));
      const list = el("ul");
      for (const value of values) list.appendChild(el("li", "", String(value)));
      section.appendChild(list);
      integrity.appendChild(section);
    }
    // The helper guarantees score-capping quote failures are diagnosed first.
    for (const diagnosis of window.PlaybookScore.diagnostics(breakdown)) {
      appendIntegrityList(diagnosis.title, diagnosis.lead, diagnosis.values, diagnosis.className);
    }
    if (integrity.childElementCount) block.appendChild(integrity);

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
    if (!focus.length) focus.push(percent >= 85 ? "Try an assessment review next." : "Tighten analysis and drafting language to capture the remaining points.");
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
    detail.open = true;
    detail.appendChild(el("summary", "", "Complete scoring audit"));

    const table = el("table");
    const thead = el("thead");
    const header = el("tr");
    for (const label of ["criterion", "event", "points"]) header.appendChild(el("th", label === "points" ? "pts" : "", label));
    thead.appendChild(header);
    table.appendChild(thead);
    const tbody = el("tbody");
    for (const ev of r.breakdown.reward_events) {
      const row = el("tr");
      row.appendChild(el("td", "criterion-name", window.PlaybookScore.humanizeCriterion(ev.criterion)));
      row.appendChild(el("td", "", ev.type.replaceAll("_", " ")));
      const pts = el("td", "pts", (ev.points > 0 ? "+" : "") + ev.points.toFixed(2));
      pts.style.color = ev.points > 0 ? "var(--green)" : ev.points < 0 ? "var(--red)" : "var(--muted)";
      row.appendChild(pts);
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    detail.appendChild(table);

    const actions = el("div", "actions-row");
    const matterTitle = matterTitles.get(r.matter_id) || r.matter_id;
    const cardMetrics = [
      `${issueCount}/${submittedCount || 0} supported issues`,
      `${citationRate}% valid citations`,
      `${settledCount} settled · ${escalationCount} escalated`,
    ];
    const displayMode = playMode === "benchmark" ? "assessment review" : "guided review";
    const summaryText = `Playbook result — ${matterTitle} (${displayMode}): ${percent}/100, ${band.toLowerCase()}. ${cardMetrics.join("; ")}. ${SITE_URL}`;
    const cardButton = el("button", "", "download card");
    cardButton.addEventListener("click", () => downloadResultCard({
      matterId: r.matter_id, matterTitle, mode: displayMode, band, percent, metrics: cardMetrics,
    }));
    const copyButton = el("button", "", "copy summary");
    copyButton.addEventListener("click", async () => {
      await copyText(summaryText);
      copyButton.textContent = "summary copied";
      window.setTimeout(() => { copyButton.textContent = "copy summary"; }, 1800);
    });
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
    actions.appendChild(cardButton);
    actions.appendChild(copyButton);
    actions.appendChild(dl);
    actions.appendChild(again);
    block.appendChild(actions);
    if (window.playbookContribute) window.playbookContribute(r, actions, () => driver.trace());
    transcript.appendChild(block);
    block.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  async function copyText(value) {
    if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    document.execCommand("copy");
    field.remove();
  }

  function downloadResultCard(card) {
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 630;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#f5f1e8";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#1c1a18";
    ctx.font = "700 30px Arial, sans-serif";
    ctx.fillText("playbook", 76, 82);
    ctx.fillStyle = "#8b1e14";
    ctx.fillText(".", 202, 82);
    ctx.fillRect(76, 112, 1048, 4);

    ctx.fillStyle = "#6b655f";
    ctx.font = "700 18px Arial, sans-serif";
    ctx.fillText(`${card.mode.toUpperCase()} MODE  ·  ${card.matterId}`, 76, 168);
    ctx.fillStyle = "#1c1a18";
    ctx.font = "48px Georgia, serif";
    const title = card.matterTitle.length > 46 ? `${card.matterTitle.slice(0, 43)}…` : card.matterTitle;
    ctx.fillText(title, 76, 235);
    ctx.font = "700 112px Arial, sans-serif";
    ctx.fillText(`${card.percent}`, 76, 375);
    ctx.fillStyle = "#8b1e14";
    ctx.font = "42px Georgia, serif";
    ctx.fillText(card.band, 290, 355);

    ctx.fillStyle = "#1c1a18";
    ctx.font = "24px Arial, sans-serif";
    card.metrics.forEach((metric, index) => ctx.fillText(metric, 76 + index * 350, 470));
    ctx.fillStyle = "#6b655f";
    ctx.font = "20px Arial, sans-serif";
    ctx.fillText(SITE_URL, 76, 560);

    const save = (url) => {
      const a = document.createElement("a");
      a.href = url;
      a.download = `playbook_result_${card.matterId}.png`;
      a.click();
    };
    if (canvas.toBlob) canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      save(url);
      URL.revokeObjectURL(url);
    }, "image/png");
    else save(canvas.toDataURL("image/png"));
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
    for (const id of ["redline-label", "markup-label"]) {
      const dl = $(id);
      dl.replaceChildren();
      const prompt = document.createElement("option");
      prompt.value = "";
      prompt.textContent = submittedLabels.size ? "choose a submitted issue" : "submit an issue first";
      dl.appendChild(prompt);
      for (const label of submittedLabels) {
        const opt = document.createElement("option");
        opt.value = label;
        opt.textContent = label;
        dl.appendChild(opt);
      }
    }
  }

  document.querySelectorAll("#tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectComposerTab(btn.dataset.tab);
      if (btn.dataset.tab === "finish" && !$("final-summary").value.trim() && submittedIssues.size) {
        $("final-summary").value = buildStatusReport();
        queueDraftSave();
      }
    });
  });

  function buildStatusReport() {
    const ordered = [...submittedIssues.values()].sort((a, b) =>
      ["critical", "high", "medium", "low"].indexOf(a.severity) -
      ["critical", "high", "medium", "low"].indexOf(b.severity));
    const lines = ["Deal team —", "", "I have completed the current review. Key points:", ""];
    ordered.forEach((issue, index) => {
      const drafted = redlinedLabels.has(issue.issue_id) ? "Draft language prepared." : "Draft language remains open.";
      lines.push(`${index + 1}. ${issue.title} (${issue.severity}; ${issue.citations[0] || "citation pending"})`);
      lines.push(`${issue.recommendation} ${drafted}`, "");
    });
    lines.push("Please let me know if you would like to discuss any open authority or business points before signature.");
    return lines.join("\n");
  }

  function selectedIssueId(documentId, section) {
    const match = [...submittedIssues.values()].find((issue) =>
      issue.citations.some((citation) => {
        const parsed = parseCitation(citation);
        return parsed?.documentId === documentId && parsed?.section === section;
      }));
    return match?.issue_id || [...submittedIssues.keys()][0] || "";
  }

  function hideSelectionTools() {
    $("selection-tools").hidden = true;
  }

  $("document-view").addEventListener("mouseup", () => {
    window.setTimeout(() => {
      const selection = window.getSelection();
      const text = selection?.toString().trim();
      const anchor = selection?.anchorNode?.nodeType === Node.TEXT_NODE
        ? selection.anchorNode.parentElement : selection?.anchorNode;
      const sectionNode = anchor?.closest?.("[data-section]");
      if (!text || !sectionNode || !$("document-view").contains(sectionNode) || !currentDocumentId) {
        hideSelectionTools();
        return;
      }
      const section = sectionNode.dataset.section;
      currentSelection = { documentId: currentDocumentId, section, text: text.slice(0, 4000) };
      capture("selection.created", { document_id: currentDocumentId, section }, {
        content_hash: contentHash(text), length: text.length,
      });
      $("selection-citation").textContent = `${currentDocumentId} §${section}`;
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      const tools = $("selection-tools");
      tools.style.left = `${Math.max(12, Math.min(window.innerWidth - 360, rect.left))}px`;
      tools.style.top = `${Math.max(12, rect.top - 48)}px`;
      tools.hidden = false;
    }, 0);
  });

  document.querySelectorAll("[data-selection-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!currentSelection) return;
      const { documentId, section, text } = currentSelection;
      const citation = `${documentId} §${section}`;
      if (button.dataset.selectionAction === "copy") {
        await copyText(citation);
        button.textContent = "copied";
        window.setTimeout(() => { button.textContent = "copy citation"; }, 1200);
        return;
      }
      if (button.dataset.selectionAction === "issue") {
        resetRevisionForms();
        $("form-issue").reset();
        selectComposerTab("issue");
        let issueId = `${documentId}-${section.replaceAll(".", "-")}`;
        let suffix = 2;
        while (submittedIssues.has(issueId)) issueId = `${documentId}-${section.replaceAll(".", "-")}-${suffix++}`;
        $("issue-label").value = issueId;
        $("issue-title").value = `Review ${documentId} §${section}`;
        $("issue-citations").value = citation;
        $("issue-analysis").placeholder = `Explain why this language matters:\n“${text.slice(0, 220)}${text.length > 220 ? "…" : ""}”`;
        $("issue-analysis").focus();
      } else {
        if (!submittedIssues.size) {
          resetRevisionForms();
          $("form-issue").reset();
          selectComposerTab("issue");
          $("issue-citations").value = citation;
          $("issue-analysis").focus();
        } else {
          resetRevisionForms();
          $("form-redline").reset();
          selectComposerTab("redline");
          $("redline-label").value = selectedIssueId(documentId, section);
          $("redline-doc").value = documentId;
          $("redline-section").value = section;
          $("redline-text").value = text;
          $("redline-text").select();
        }
      }
      hideSelectionTools();
      queueDraftSave();
    });
  });

  document.querySelectorAll("#composer input, #composer textarea, #composer select")
    .forEach((field) => {
      field.addEventListener("input", queueDraftSave);
      field.addEventListener("change", queueDraftSave);
      field.addEventListener("blur", persistWorkspaceDraft);
    });

  document.addEventListener("keydown", (event) => {
    if (!matterActive || finished) return;
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.shiftKey && event.key.toLowerCase() === "f") {
      event.preventDefault();
      selectComposerTab("search");
      $("search-query").focus();
    } else if (event.altKey && event.key.toLowerCase() === "i") {
      event.preventDefault();
      selectComposerTab("issue");
      $("issue-title").focus();
    } else if (event.altKey && event.key.toLowerCase() === "r") {
      event.preventDefault();
      selectComposerTab("redline");
      $("redline-text").focus();
    }
  });

  document.querySelectorAll("#workspace-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => showWorkspace(btn.dataset.view));
  });

  $("add-quote").addEventListener("click", () => {
    const row = el("div", "quote-row");
    const cite = document.createElement("input");
    cite.placeholder = "citation, e.g. msa §4.2";
    cite.className = "q-cite";
    const citeTools = el("div", "quote-citation-tools");
    const insert = el("button", "insert-section", "insert §");
    insert.type = "button";
    insert.addEventListener("click", () => insertAtCursor(cite, "§"));
    const text = document.createElement("textarea");
    text.rows = 2;
    text.placeholder = "exact text from that section";
    text.className = "q-text";
    const rm = el("button", "remove", "remove");
    rm.type = "button";
    rm.addEventListener("click", () => row.remove());
    citeTools.append(cite, insert);
    row.append(citeTools, text, el("div", "quote-error"), rm);
    $("quotes").appendChild(row);
  });

  function insertAtCursor(input, value) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    input.setRangeText(value, start, end, "end");
    input.focus();
  }

  document.querySelectorAll(".insert-section[data-target]").forEach((button) => {
    button.addEventListener("click", () => insertAtCursor($(button.dataset.target), "§"));
  });

  $("issue-citations").addEventListener("input", () => clearFieldErrors("issue-citation-errors"));

  $("form-ask").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("ask-question").value.trim();
    if (q && await ask(q)) { $("ask-question").value = ""; persistWorkspaceDraft(); }
  });

  $("form-search").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("search-query").value.trim();
    if (q && await search(q)) { $("search-query").value = ""; persistWorkspaceDraft(); }
  });

  $("form-issue").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!validateCitationLines()) return;
    const quotes = [];
    let invalidQuoteCitation = false;
    const quoteChecks = [];
    document.querySelectorAll(".quote-row").forEach((row) => {
      const citation = row.querySelector(".q-cite").value.trim();
      const text = row.querySelector(".q-text").value.trim();
      const error = row.querySelector(".quote-error");
      error.replaceChildren();
      if (citation && text) {
        const check = window.PlaybookCitations.checkQuote(citation, text, knownCitations, sectionCache);
        quoteChecks.push({ row, error, check });
        if (check.status === "invalid") {
          invalidQuoteCitation = true;
          addFieldError(error, check.error, check.suggestion, () => {
            row.querySelector(".q-cite").value = check.suggestion;
            error.replaceChildren();
          });
        } else {
          quotes.push({ citation: check.citation, text });
        }
      }
    });
    if (invalidQuoteCitation) return;
    const payload = {
      issue_id: $("issue-label").value.trim(),
      title: $("issue-title").value.trim(),
      severity: $("issue-severity").value,
      citations: $("issue-citations").value.split("\n").map((s) => s.trim()).filter(Boolean)
        .map((citation) => window.PlaybookCitations.validateCitation(citation, knownCitations).citation),
      analysis: $("issue-analysis").value.trim(),
      recommendation: $("issue-recommendation").value.trim(),
    };
    if (quotes.length) payload.quotes = quotes;
    let hardFailure = false;
    let unreadQuote = false;
    quoteChecks.forEach(({ error, check }) => {
      if (check.status === "unread" || check.status === "fabricated") {
        error.appendChild(el("span", check.status === "fabricated" ? "hard-warning" : "", check.message));
        hardFailure ||= check.status === "fabricated";
        unreadQuote ||= check.status === "unread";
      }
    });
    const submit = async () => {
      const actionType = e.target.dataset.revising === "true" ? "revise_issue" : "submit_issue";
      if (!await submitIssue(payload, actionType)) return;
      e.target.reset();
      resetRevisionForms();
      $("quotes").replaceChildren();
      clearFieldErrors("issue-citation-errors");
      persistWorkspaceDraft();
    };
    if (hardFailure || unreadQuote) {
      capture("validation.warning", { issue_id: payload.issue_id }, {
        form: "issue", reason: hardFailure ? "quotation_mismatch" : "quotation_unread",
      });
      const warning = el("div", "submission-warning");
      warning.appendChild(el("strong", "", hardFailure ? "quotation check failed" : "quotation could not be checked"));
      const anyway = el("button", "submit-anyway", hardFailure ? "submit anyway" : "continue without verifying");
      anyway.type = "button";
      anyway.addEventListener("click", async () => {
        anyway.disabled = true;
        await submit();
      });
      warning.appendChild(anyway);
      $("issue-citation-errors").appendChild(warning);
      return;
    }
    await submit();
  });

  $("form-redline").addEventListener("submit", async (e) => {
    e.preventDefault();
    clearFieldErrors("redline-citation-errors");
    const section = $("redline-section").value.trim().replace(/^§\s*/, "");
    const citation = `${$("redline-doc").value} §${section}`;
    const citationResult = window.PlaybookCitations.validateCitation(citation, knownCitations);
    if (!citationResult.valid) {
      capture("validation.failed", {
        document_id: $("redline-doc").value, section,
        issue_id: $("redline-label").value,
      }, { form: "redline", field: "citation", message: citationResult.error });
      addFieldError($("redline-citation-errors"), citationResult.error, null, null);
      $("redline-section").setAttribute("aria-invalid", "true");
      return;
    }
    $("redline-section").setAttribute("aria-invalid", "false");
    const actionType = e.target.dataset.revising === "true" ? "revise_redline" : "propose_redline";
    const accepted = await proposeRedline({
      issue_id: $("redline-label").value.trim(),
      document_id: $("redline-doc").value,
      section,
      replacement_text: $("redline-text").value.trim(),
      rationale: $("redline-rationale").value.trim(),
    }, actionType);
    if (accepted) { e.target.reset(); resetRevisionForms(); persistWorkspaceDraft(); }
  });

  $("form-escalate").addEventListener("submit", async (e) => {
    e.preventDefault();
    const topic = $("escalate-topic").value.trim();
    const reason = $("escalate-reason").value.trim();
    if (topic && reason && await escalate(topic, reason)) { e.target.reset(); persistWorkspaceDraft(); }
  });

  $("form-negotiate").addEventListener("submit", async (e) => {
    e.preventDefault();
    const accepted = await sendMarkup({
      issue_id: $("markup-label").value,
      document_id: $("markup-doc").value,
      section: $("markup-section").value.trim().replace(/^§\s*/, ""),
      proposed_text: $("markup-text").value.trim(),
    });
    if (accepted) {
      $("markup-section").value = "";
      $("markup-text").value = "";
      persistWorkspaceDraft();
    }
  });

  $("markup-label").addEventListener("change", () => {
    const issue = submittedIssues.get($("markup-label").value);
    const operative = issue?.citations.map(parseCitation).find(Boolean);
    if (!operative) return;
    $("markup-doc").value = operative.documentId;
    $("markup-section").value = operative.section;
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
    $("finish-title").textContent = sealed ? "deliver this assessment review?" : "ready to finish this review?";
    $("finish-confirm").textContent = "deliver status report";
    const rows = [
      ["Sections reviewed", readSections.size],
      ["Client questions asked", questionsAsked],
      ["Issues submitted", submittedIssues.size],
      ["Issues with draft language", `${redlinedLabels.size} of ${submittedIssues.size}`],
      ...(currentObservation && Object.hasOwn(currentObservation.budgets, "escalations_remaining")
        ? [["Escalations raised", currentObservation.submitted_escalation_topics?.length || 0]] : []),
      ...(currentObservation && Object.hasOwn(currentObservation.budgets, "negotiation_rounds_remaining")
        ? [["Negotiated issues", Object.keys(currentObservation.negotiation || {}).length]] : []),
      ["Review capacity remaining", stepsRemaining],
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
    if (!submittedIssues.size) warnings.push("You have not recorded any issues. Confirm that the documents are acceptable as drafted.");
    const highWithoutDraft = Array.from(submittedIssues.values())
      .filter((issue) => ["high", "critical"].includes(issue.severity) && !redlinedLabels.has(issue.issue_id));
    if (highWithoutDraft.length) warnings.push(`${highWithoutDraft.length} high-priority issue(s) have no draft language. Confirm that is intentional.`);
    if (currentObservation && Object.hasOwn(currentObservation.budgets, "escalations_remaining") &&
        !(currentObservation.submitted_escalation_topics || []).length) {
      warnings.push("No matter has been escalated. Confirm that every decision remains within your authority.");
    }
    const openNegotiations = Object.values(currentObservation?.negotiation || {}).filter((state) => state.status !== "closed");
    if (openNegotiations.length) warnings.push(`${openNegotiations.length} negotiated issue(s) remain open. Confirm that the final update explains their status.`);
    if (stepsRemaining <= 3) warnings.push(`Only ${stepsRemaining} review actions remain available.`);
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

  async function startMatter(options = {}) {
    const resume = options.resume || null;
    const id = resume?.matter_id || matterSelect.value;
    const seed = resume?.seed ?? 0;
    if (!options.skipConfirm && !confirmMatterReplacement(id)) {
      matterSelect.value = episode?.matter_id || id;
      return;
    }
    if (matterActive && !finished) {
      capture("matter.discarded", {}, { replacement_matter_id: id });
      window.playbookCaptureSession?.complete?.();
      window.playbookCaptureSession = null;
      clearSavedEpisode();
    }
    startBtn.disabled = true;
    $("welcome-start").disabled = true;
    $("welcome-start").textContent = "opening matter…";
    $("boot-status").textContent = "opening the workspace…";
    let payload;
    try {
      if (id === "ai_saas_001" && seed === 0) {
        payload = starterPayload || await starterWarmup;
        if (payload) driver.activate(id, seed);
      }
      if (!payload) payload = await driver.start(id, seed);
      if (resume) {
        options.replayed = [];
        for (const action of resume.actions) options.replayed.push(await driver.step(action));
        if (options.replayed.length) payload = options.replayed.at(-1);
      }
    } catch (error) {
      if (resume) clearSavedEpisode();
      $("boot-status").textContent = "could not open matter";
      boot((resume ? "resume failed: " : "request failed: ") + error.message);
      $("welcome-start").textContent = "retry opening matter";
      $("welcome-start").disabled = false;
      return;
    } finally {
      startBtn.disabled = false;
    }
    guidedStartPending = false;
    starterPayload = null;
    $("welcome-start").disabled = false;
    $("welcome-start").textContent = "start guided review";
    const obs = payload.observation;
    stepNo = 0;
    finished = false;
    readSections = new Set();
    submittedLabels = new Set();
    submittedIssues = new Map();
    submittedRedlines = new Map();
    redlinedLabels = new Set();
    sectionCache = new Map();
    documentCache = new Map();
    currentDocumentId = null;
    currentSelection = null;
    knownCitations = new Set();
    questionsAsked = 0;
    if (resume) {
      resume.actions.forEach((action, index) => {
        const result = options.replayed[index]?.observation?.last_result || {};
        if (result.error) return;
        if (action.type === "read_document") {
          if (action.section) {
            readSections.add(action.document_id + "§" + action.section);
            if (result.content) sectionCache.set(`${action.document_id} §${action.section}`, result.content);
          } else if (result.content) {
            documentCache.set(action.document_id, result.content);
            cacheDocumentSections(action.document_id, result.content);
            const descriptor = obs.documents.find((doc) => doc.id === action.document_id);
            (descriptor?.sections || []).forEach((sec) => readSections.add(action.document_id + "§" + sec));
          }
        } else if (action.type === "ask_client") questionsAsked += 1;
        else if (["submit_issue", "revise_issue"].includes(action.type)) {
          submittedLabels.add(action.issue_id);
          submittedIssues.set(action.issue_id, action);
        } else if (["propose_redline", "revise_redline"].includes(action.type)) {
          redlinedLabels.add(action.issue_id);
          submittedRedlines.set(`${action.issue_id}|${action.document_id}|${action.section}`, action);
        }
      });
      stepNo = resume.actions.length;
    }
    document.querySelectorAll(".tabform").forEach((form) => form.reset());
    resetRevisionForms();
    $("quotes").replaceChildren();
    refreshLabels();
    renderReview();
    transcript.replaceChildren();
    $("current-document").textContent = "no document open";
    const empty = el("div", "empty-document");
    empty.append(el("p", "eyebrow", obs.matter.matter_id), el("h2", "", obs.matter.title));
    const role = el("p");
    role.append(el("strong", "", "You are: "), document.createTextNode(obs.matter.role));
    empty.append(role, el("p", "", obs.matter.assignment));
    if (id === "ai_saas_001") empty.append(el("p", "matter-time", "Starter matter · about 15–20 minutes"));
    if (playMode === "learn") empty.append(el("p", "start-hint", "start by opening the supervising-lawyer instructions and playbook from the matter file."));
    $("document-view").replaceChildren(empty);
    showWorkspace("document");
    document.querySelectorAll("#progress li").forEach((item) => item.classList.remove("done"));
    if (resume) {
      const restoredProgress = {
        read_document: "read", ask_client: "question", submit_issue: "issue",
        revise_issue: "issue", propose_redline: "redline", revise_redline: "redline", submit_final: "finish",
      };
      resume.actions.forEach((action) => markProgress(restoredProgress[action.type]));
    }
    enableComposer();
    configureActionTabs(obs);
    renderDocs(obs);
    renderNegotiation(obs);
    renderReview();
    matterActive = true;
    const restoredDocumentId = await restoreWorkspaceDraft();
    if (restoredDocumentId && documentCache.has(restoredDocumentId)) {
      renderDocument(restoredDocumentId, documentCache.get(restoredDocumentId));
    }
    updateBudgets(obs);
    updateNextStep();
    budgetsEl.hidden = false;
    $("boot").hidden = true;
    $("main").hidden = false;
    document.body.classList.add("matter-active");
    matterActive = !finished;
    $("mode-badge").hidden = false;
    window.scrollTo(0, 0);
    setMobileView("files");
    await beginCapture(id, resume?.capture_session_id || null);

    const m = obs.matter;
    addEntry("matter opened — " + m.matter_id, null, [
      el("div", "body", m.title),
      el("div", "body", "you are: " + m.role),
      el("div", "body", "assignment: " + m.assignment),
      ...(playMode === "learn" ? [el("div", "body answer",
        "house rules: cite provisions as 'doc §section', operative provision first. " +
        "quotes must be verbatim. Use client and supervising-lawyer requests for points that can change your advice.")] : []),
    ]);
    if (resume) addEntry(`review resumed — ${resume.actions.length} saved actions restored`, null, [
      el("div", "body answer", "Restored with the saved matter, seed, and exact action sequence."),
    ]);
    persistEpisode();
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
  $("resume-confirm").addEventListener("click", async () => {
    const saved = savedResume;
    $("resume-dialog").close();
    if (!saved) return;
    setPlayMode(saved.mode);
    matterSelect.value = saved.matter_id;
    await startMatter({ resume: saved, skipConfirm: true });
  });
  $("resume-discard").addEventListener("click", () => {
    clearSavedEpisode();
    $("resume-dialog").close();
  });
})();
