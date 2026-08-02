/* playbook web gym — opt-in trace contribution.
 *
 * Self-contained: app.js only calls window.playbookContribute(result,
 * actionsRow, getTraceJson) when an episode ends. Everything else — consent
 * copy, upload, status — lives here. Uploaded scores are advisory; the
 * training pipeline replays every trace through the real engine before use. */

(function () {
  "use strict";

  const TRACE_ENDPOINT = "https://playbook-traces.james-baker1628.workers.dev/api/traces";

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
    status.style.marginLeft = "10px";
    status.style.color = "var(--muted)";

    btn.addEventListener("click", async () => {
      if (!consent.checked) {
        status.textContent = "confirm training-data consent first";
        consent.focus();
        return;
      }
      btn.disabled = true;
      status.textContent = "uploading…";
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
        const response = await fetch(TRACE_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const body = await response.json();
        if (response.ok && body.ok) {
          status.textContent = "received — thank you. it counts once it replays clean.";
          handle.disabled = true;
          background.disabled = true;
          consent.disabled = true;
        } else {
          btn.disabled = false;
          status.textContent = "rejected: " + (body.error || response.status);
        }
      } catch (err) {
        btn.disabled = false;
        status.textContent = "upload failed: " + err;
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
