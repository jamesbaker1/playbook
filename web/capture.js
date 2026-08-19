// SPDX-License-Identifier: AGPL-3.0-only
/* Matter-scoped semantic interaction capture for synthetic Playbook matters.
 * Captures meaningful workspace events, never pixels, pointer trails, or keystrokes. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PlaybookCapture = api;
})(typeof window !== "undefined" ? window : globalThis, function (root) {
  "use strict";

  const SCHEMA_VERSION = "1";
  const STORAGE_PREFIX = "playbook.interaction-trace.v1.";
  const CONSENT_KEY = "playbook.capture-consent.v1";
  const MAX_EVENTS = 2500;
  const MAX_BYTES = 4_000_000;
  const ALLOWED_TYPES = /^(matter|document|search|selection|issue|redline|communication|counterparty|fact|final|capture|validation|transport)\.[a-z0-9_.-]+$/;
  const uuid = () => root.crypto?.randomUUID?.() || "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.random() * 16 | 0;
    return (c === "x" ? r : (r & 3) | 8).toString(16);
  });
  const now = () => new Date().toISOString();
  const byteLength = (value) => {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(text).byteLength;
    // Browser targets provide TextEncoder; this fallback keeps older test and
    // embedded runtimes conservative for non-ASCII input.
    return unescape(encodeURIComponent(text)).length;
  };

  function readJson(storage, key, fallback) {
    try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; }
  }

  function consentFor(storage, version) {
    const value = readJson(storage, CONSENT_KEY, null);
    return value?.version === version && value?.training_and_evaluation === true ? value : null;
  }

  function decisionFor(storage, version) {
    const value = readJson(storage, CONSENT_KEY, null);
    return value?.version === version && typeof value?.training_and_evaluation === "boolean" ? value : null;
  }

  function create(options) {
    const storage = options.storage || root.localStorage;
    const policyVersion = String(options.consentVersion || "");
    const matterId = String(options.matterId || "");
    if (!policyVersion || !/^[a-z0-9_]{1,64}$/.test(matterId)) {
      throw new Error("capture requires a policy version and valid matter ID");
    }
    const sessionId = String(options.sessionId || uuid());
    const key = STORAGE_PREFIX + sessionId;
    let trace = readJson(storage, key, null) || {
      schema_version: SCHEMA_VERSION,
      session_id: sessionId,
      contribution_id: uuid(),
      matter_id: matterId,
      engine_version: String(options.engineVersion || "unknown"),
      consent_version: policyVersion,
      started_at: now(),
      completed_at: null,
      events: [],
    };
    let decision = decisionFor(storage, policyVersion);
    let enabled = decision?.training_and_evaluation === true;
    const lastCaptureBoundary = [...trace.events].reverse().find((event) =>
      event?.type === "capture.paused" || event?.type === "capture.resumed"
    );
    // A paused session stays paused across refreshes. Only an explicit resume
    // creates the boundary that permits capture to continue.
    let paused = enabled && lastCaptureBoundary?.type === "capture.paused";
    const listeners = new Set();

    function persist() {
      try { storage.setItem(key, JSON.stringify(trace)); } catch { /* quota: retain in memory */ }
    }
    function storeDecision(value) {
      try { storage.setItem(CONSENT_KEY, JSON.stringify(value)); } catch { /* retain in memory */ }
    }
    function notify() { listeners.forEach((fn) => fn(status())); }
    function status() { return { enabled, paused, decided: Boolean(decision), consent_version: policyVersion, session_id: sessionId }; }
    function setConsent(accepted) {
      enabled = accepted === true;
      paused = false;
      if (enabled) {
        decision = {
          version: policyVersion, training_and_evaluation: true, recorded_at: now(),
        };
        storeDecision(decision);
        record("capture.consented", {}, {});
      } else {
        decision = {
          version: policyVersion, training_and_evaluation: false, recorded_at: now(),
        };
        storeDecision(decision);
        trace.events = [];
        persist();
      }
      notify();
      return status();
    }
    function record(type, target, data, durationMs) {
      if (!enabled || paused || !ALLOWED_TYPES.test(type) || trace.events.length >= MAX_EVENTS) return null;
      const event = {
        event_id: uuid(), sequence: trace.events.length + 1, occurred_at: now(), type,
        target: {
          document_id: target?.document_id ?? null,
          section: target?.section ?? null,
          issue_id: target?.issue_id ?? null,
        },
        data: data && typeof data === "object" ? data : {},
        duration_ms: Number.isFinite(durationMs) && durationMs >= 0 ? Math.round(durationMs) : null,
      };
      trace.events.push(event);
      if (byteLength(trace) > MAX_BYTES) {
        trace.events.pop();
        return null;
      }
      persist();
      return event;
    }
    function pause() {
      if (!enabled || paused) return status();
      record("capture.paused", {}, {});
      paused = true; notify(); return status();
    }
    function resume() {
      if (!enabled || !paused) return status();
      paused = false;
      record("capture.resumed", {}, {});
      notify(); return status();
    }
    function complete() { if (enabled) { trace.completed_at = now(); persist(); } return snapshot(); }
    function snapshot() { return enabled ? JSON.parse(JSON.stringify(trace)) : null; }
    function discard() {
      trace.events = [];
      try { storage.removeItem(key); } catch { /* already discarded in memory */ }
    }
    function onStatus(fn) { listeners.add(fn); fn(status()); return () => listeners.delete(fn); }

    return { status, setConsent, record, pause, resume, complete, snapshot, discard, onStatus };
  }

  function attachContribution(payload, capture) {
    const interaction = capture?.complete?.();
    if (!interaction) return payload;
    return { ...payload, contribution_id: interaction.contribution_id, interaction_trace: interaction };
  }

  function mountControls(container, session) {
    if (!container || !root.document) return null;
    const wrap = root.document.createElement("div");
    wrap.className = "capture-controls";
    const statusButton = root.document.createElement("button");
    statusButton.type = "button";
    statusButton.className = "capture-status";
    statusButton.setAttribute("aria-haspopup", "dialog");
    const dialog = root.document.createElement("dialog");
    dialog.className = "capture-dialog";
    const heading = root.document.createElement("h2");
    heading.textContent = "Contribute how you review";
    const copy = root.document.createElement("p");
    copy.textContent = "With your permission, Playbook records meaningful actions in this synthetic matter—documents and sections used, searches, selections, drafts, revisions, and communications. It never records your screen, raw keystrokes, pointer trail, other tabs, or other applications.";
    const controls = root.document.createElement("div");
    controls.className = "dialog-actions";
    const decline = root.document.createElement("button");
    decline.type = "button"; decline.textContent = "Don’t contribute";
    const accept = root.document.createElement("button");
    accept.type = "button"; accept.className = "primary"; accept.textContent = "Allow capture";
    controls.append(decline, accept);
    dialog.append(heading, copy, controls);
    wrap.append(statusButton, dialog);
    container.appendChild(wrap);
    const render = (state) => {
      statusButton.textContent = !state.enabled ? "Capture off" : state.paused ? "Capture paused" : "Capture on";
      statusButton.setAttribute("aria-pressed", String(state.enabled && !state.paused));
    };
    session.onStatus(render);
    statusButton.addEventListener("click", () => {
      const state = session.status();
      if (!state.enabled) dialog.showModal();
      else if (state.paused) session.resume();
      else session.pause();
    });
    decline.addEventListener("click", () => { session.setConsent(false); dialog.close(); });
    accept.addEventListener("click", () => { session.setConsent(true); dialog.close(); });
    if (!session.status().decided) root.setTimeout(() => dialog.showModal(), 0);
    return { element: wrap, dialog, showConsent: () => dialog.showModal() };
  }

  return { create, mountControls, attachContribution, consentFor, decisionFor, byteLength, constants: { SCHEMA_VERSION, MAX_EVENTS, MAX_BYTES } };
});
