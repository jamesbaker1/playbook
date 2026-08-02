/* playbook web gym — opt-in trace contribution.
 *
 * Self-contained: app.js only calls window.playbookContribute(result,
 * actionsRow, getTraceJson) when an episode ends. Everything else — consent
 * copy, upload, status — lives here. Uploaded scores are advisory; the
 * training pipeline replays every trace through the real engine before use. */

(function () {
  "use strict";

  const TRACE_ENDPOINT = "https://playbook-traces.james-baker1628.workers.dev/api/traces";
  const UPLOAD_TIMEOUT_MS = 20000;
  const MAX_TRANSIENT_RETRIES = 2;
  const TRANSIENT_STATUSES = new Set([429, 502, 503, 504]);

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function postTrace(body, onRetry) {
    for (let attempt = 0; ; attempt += 1) {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
      let response;
      try {
        response = await fetch(TRACE_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timer);
      }

      // Retry only when the server explicitly reports a transient failure. A
      // network error or timeout is ambiguous: the Worker may have stored the
      // trace before the response was lost, and its API has no idempotency key.
      if (!TRANSIENT_STATUSES.has(response.status) || attempt >= MAX_TRANSIENT_RETRIES) {
        return response;
      }
      onRetry(attempt + 1);
      await delay(500 * (2 ** attempt));
    }
  }

  async function responseBody(response) {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

  let policyPromise;

  function getPolicy() {
    if (!policyPromise) {
      policyPromise = fetch("policy.json", { cache: "no-cache" }).then((response) => {
        if (!response.ok) throw new Error("contribution policy unavailable");
        return response.json();
      });
    }
    return policyPromise;
  }

  window.playbookContribute = function (result, actionsRow, getTraceJson) {
    if (!TRACE_ENDPOINT) return;

    const wrap = document.createElement("div");
    wrap.className = "contribute";

    const note = document.createElement("p");
    note.className = "contribute-note";
    note.textContent =
      "contribute this trace to the public training corpus? the raw contribution stores " +
      "your actions, score, mode, optional background, and optional handle. every trace " +
      "is re-verified by replay before use.";

    const detail = document.createElement("p");
    detail.className = "contribute-detail";
    detail.textContent =
      "your handle stays with the restricted raw contribution for provenance, but is " +
      "excluded from training exports.";

    const fields = document.createElement("div");
    fields.className = "contribute-fields";

    const handle = document.createElement("input");
    handle.placeholder = "sign it (optional handle)";
    handle.setAttribute("aria-label", "optional contributor handle");
    handle.maxLength = 40;

    const background = document.createElement("select");
    background.setAttribute("aria-label", "professional background (optional)");
    for (const [value, label] of [
      ["", "background (optional)"],
      ["lawyer", "lawyer"],
      ["legal_professional", "other legal professional"],
      ["law_student", "law student"],
      ["other", "other"],
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      background.appendChild(option);
    }
    fields.append(handle, background);

    const consentLabel = document.createElement("label");
    consentLabel.className = "contribute-consent";
    const consent = document.createElement("input");
    consent.type = "checkbox";
    consentLabel.append(consent, document.createTextNode(
      "i agree that this trace may be used to train and evaluate AI models."
    ));

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "contribute trace";

    const status = document.createElement("span");
    status.className = "contribute-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const submitRow = document.createElement("div");
    submitRow.className = "contribute-submit";
    submitRow.append(btn, status);

    let submitted = false;
    let uploading = false;

    btn.addEventListener("click", async () => {
      if (submitted || uploading) return;
      if (!consent.checked) {
        status.textContent = "confirm training-data consent first";
        consent.focus();
        return;
      }
      uploading = true;
      btn.disabled = true;
      status.textContent = "uploading your trace…";
      try {
        const policy = await getPolicy();
        if (!window.playbookAppVersion) throw new Error("engine version unavailable");
        const payload = {
          app: "web-gym",
          app_version: window.playbookAppVersion,
          mode: window.playbookMode === "benchmark" ? "benchmark" : "learn",
          handle: handle.value.trim() || null,
          background: background.value || null,
          consent: {
            version: policy.consent_version,
            training_and_evaluation: true,
          },
          trace: JSON.parse(getTraceJson()),
        };
        // Serialize once so every safe retry sends exactly the same trace.
        const response = await postTrace(JSON.stringify(payload), (attempt) => {
          status.textContent = `the service is busy. retrying (${attempt}/${MAX_TRANSIENT_RETRIES})…`;
        });
        const body = await responseBody(response);
        if (response.ok && body.ok) {
          submitted = true;
          status.textContent = "received — thank you. it counts once it replays clean.";
          handle.disabled = true;
          background.disabled = true;
          consent.disabled = true;
        } else {
          btn.disabled = false;
          const reason = body.error || `server error ${response.status}`;
          status.textContent = response.status >= 500 || response.status === 429
            ? `the service is temporarily unavailable (${reason}). please try again.`
            : `this trace was not accepted: ${reason}.`;
        }
      } catch (err) {
        btn.disabled = false;
        if (err && err.name === "AbortError") {
          status.textContent =
            "the upload timed out. it may have arrived, so wait a moment before trying again.";
        } else {
          status.textContent =
            "the connection was interrupted. it may have arrived, so wait a moment before trying again.";
        }
      } finally {
        uploading = false;
      }
    });

    wrap.append(note, detail, fields, consentLabel, submitRow);
    actionsRow.parentNode.insertBefore(wrap, actionsRow);
  };
})();
