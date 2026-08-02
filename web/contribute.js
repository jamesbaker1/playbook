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
  const automaticUploads = new Set();

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function postTrace(body, onRetry) {
    for (let attempt = 0; ; attempt += 1) {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
      let response;
      let failure;
      try {
        response = await fetch(TRACE_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal: controller.signal,
        });
      } catch (error) {
        failure = error;
      } finally {
        window.clearTimeout(timer);
      }

      if (failure) {
        if (attempt >= MAX_TRANSIENT_RETRIES) throw failure;
        onRetry(attempt + 1);
        await delay(500 * (2 ** attempt));
        continue;
      }

      // Every payload has an immutable contribution ID, so retrying the exact
      // serialized body cannot create a second stored contribution.
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

    const capture = window.playbookCaptureSession;
    const captureStatus = capture?.status?.();
    if (captureStatus?.enabled) {
      const wrap = document.createElement("div");
      wrap.className = "contribute contribute-automatic";
      const status = document.createElement("span");
      status.className = "contribute-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      wrap.append(status);
      actionsRow.parentNode.insertBefore(wrap, actionsRow);
      if (automaticUploads.has(captureStatus.session_id)) {
        status.textContent = "review activity contributed";
        return;
      }
      automaticUploads.add(captureStatus.session_id);
      status.textContent = "saving consented review activity…";
      (async () => {
        try {
          const policy = await getPolicy();
          if (!window.playbookAppVersion) throw new Error("engine version unavailable");
          const payload = window.PlaybookCapture.attachContribution({
            contribution_id: window.crypto.randomUUID(),
            app: "web-gym",
            app_version: window.playbookAppVersion,
            mode: window.playbookMode === "benchmark" ? "benchmark" : "learn",
            handle: null,
            background: null,
            consent: { version: policy.consent_version, training_and_evaluation: true },
            trace: JSON.parse(getTraceJson()),
          }, capture);
          const response = await postTrace(JSON.stringify(payload), (attempt) => {
            status.textContent = `saving consented review activity (${attempt})…`;
          });
          const body = await responseBody(response);
          status.textContent = response.ok && body.ok
            ? "review activity contributed"
            : "review activity could not be contributed";
        } catch {
          status.textContent = "review activity will remain on this device for now";
        }
      })();
      return;
    }

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
          contribution_id: window.crypto.randomUUID(),
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
        const uploadPayload = window.PlaybookCapture
          ? window.PlaybookCapture.attachContribution(payload, window.playbookCaptureSession)
          : payload;
        // Serialize once so every safe retry sends exactly the same trace.
        const response = await postTrace(JSON.stringify(uploadPayload), (attempt) => {
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
