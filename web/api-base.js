// SPDX-License-Identifier: AGPL-3.0-only
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PlaybookApiBase = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_API_BASE = "https://playbook-engine.james-baker1628.workers.dev";
  const STORAGE_KEY = "playbook.api-base.v1";

  function normalize(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value.trim());
      if ((url.protocol !== "http:" && url.protocol !== "https:") ||
          url.username || url.password || url.pathname !== "/" || url.search || url.hash) return null;
      return url.origin;
    } catch (_) {
      return null;
    }
  }

  function resolve(options = {}) {
    const fallback = normalize(options.defaultBase) || DEFAULT_API_BASE;
    const search = typeof options.search === "string" ? options.search : "";
    const queryBase = normalize(new URLSearchParams(search).get("api"));
    if (queryBase) return queryBase;
    try {
      const storedBase = normalize(options.storage && options.storage.getItem(STORAGE_KEY));
      if (storedBase) return storedBase;
    } catch (_) {
      // Storage is optional (and may be blocked by browser privacy settings).
    }
    return fallback;
  }

  return { DEFAULT_API_BASE, STORAGE_KEY, normalize, resolve };
});
