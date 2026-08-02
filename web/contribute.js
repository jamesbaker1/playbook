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

  window.playbookContribute = function (result, actionsRow, getTraceJson) {
    if (!TRACE_ENDPOINT) return;

    const wrap = document.createElement("div");
    wrap.style.marginTop = "10px";

    const note = document.createElement("div");
    note.textContent =
      "contribute this trace to the public training corpus? anonymous — just your " +
      "actions and scores. every trace is re-verified by replay before it trains anything.";
    note.style.color = "var(--muted)";
    note.style.marginBottom = "6px";

    const handle = document.createElement("input");
    handle.placeholder = "sign it (optional handle)";
    handle.maxLength = 40;
    handle.style.marginBottom = "6px";

    const background = document.createElement("select");
    background.setAttribute("aria-label", "Professional background (optional)");
    background.style.marginBottom = "6px";
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

    const consentLabel = document.createElement("label");
    consentLabel.style.display = "flex";
    consentLabel.style.gap = "8px";
    consentLabel.style.margin = "4px 0 8px";
    const consent = document.createElement("input");
    consent.type = "checkbox";
    consent.style.width = "auto";
    consentLabel.append(consent, document.createTextNode(
      "I agree that this trace may be used to train and evaluate AI models."
    ));

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "contribute trace";

    const status = document.createElement("span");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.style.marginLeft = "10px";
    status.style.color = "var(--muted)";

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
      status.textContent = "Uploading your trace…";
      try {
        const payload = {
          app: "web-gym",
          app_version: "0.3",
          mode: window.playbookMode === "benchmark" ? "benchmark" : "learn",
          handle: handle.value.trim() || null,
          background: background.value || null,
          consent: {
            version: "2026-08-01",
            training_and_evaluation: true,
          },
          trace: JSON.parse(getTraceJson()),
        };
        // Serialize once so every safe retry sends exactly the same trace.
        const response = await postTrace(JSON.stringify(payload), (attempt) => {
          status.textContent = `The service is busy. Retrying (${attempt}/${MAX_TRANSIENT_RETRIES})…`;
        });
        const body = await responseBody(response);
        if (response.ok && body.ok) {
          submitted = true;
          status.textContent = "Received — thank you. It counts once it replays clean.";
          handle.disabled = true;
          background.disabled = true;
          consent.disabled = true;
        } else {
          btn.disabled = false;
          const reason = body.error || `server error ${response.status}`;
          status.textContent = response.status >= 500 || response.status === 429
            ? `The service is temporarily unavailable (${reason}). Please try again.`
            : `This trace was not accepted: ${reason}.`;
        }
      } catch (err) {
        btn.disabled = false;
        if (err && err.name === "AbortError") {
          status.textContent =
            "The upload timed out. It may have arrived, so wait a moment before trying again.";
        } else {
          status.textContent =
            "The connection was interrupted. It may have arrived, so wait a moment before trying again.";
        }
      } finally {
        uploading = false;
      }
    });

    wrap.appendChild(note);
    wrap.appendChild(handle);
    wrap.appendChild(document.createElement("br"));
    wrap.appendChild(background);
    wrap.appendChild(consentLabel);
    wrap.appendChild(btn);
    wrap.appendChild(status);
    actionsRow.parentNode.insertBefore(wrap, actionsRow.nextSibling);
  };
})();
