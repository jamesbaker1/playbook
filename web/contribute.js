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

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "contribute trace";

    const status = document.createElement("span");
    status.style.marginLeft = "10px";
    status.style.color = "var(--muted)";

    btn.addEventListener("click", async () => {
      btn.disabled = true;
      status.textContent = "uploading…";
      try {
        const payload = {
          app: "web-gym",
          handle: handle.value.trim() || null,
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
    wrap.appendChild(btn);
    wrap.appendChild(status);
    actionsRow.parentNode.insertBefore(wrap, actionsRow.nextSibling);
  };
})();
