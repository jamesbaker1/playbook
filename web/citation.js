// SPDX-License-Identifier: AGPL-3.0-only
/* Citation parsing and quote checks shared by the browser UI and unit tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PlaybookCitations = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function normalizeQuote(text) {
    return String(text).toLowerCase().trim().split(/\s+/).filter(Boolean).join(" ");
  }

  function parseCitation(value) {
    const match = String(value).match(/^\s*([^\s§]+)\s+§\s*([^\s]+)\s*$/);
    return match ? { documentId: match[1], section: match[2] } : null;
  }

  function normalizationCandidate(value) {
    const match = String(value).match(/^\s*([^\s§]+)\s+(?:(?:sec(?:tion)?\.)\s*)?§?\s*([^\s]+)\s*$/i);
    if (!match) return null;
    return `${match[1].toLowerCase()} §${match[2]}`;
  }

  function validateCitation(value, knownCitations) {
    const raw = String(value).trim();
    const parsed = parseCitation(raw);
    const candidate = normalizationCandidate(raw);
    if (!parsed) {
      const error = raw.includes("§")
        ? "Use exactly document §section, without notes or extra text."
        : "Use document §section (the § symbol is required).";
      return { valid: false, error, suggestion: candidate };
    }
    const normalized = `${parsed.documentId.toLowerCase()} §${parsed.section}`;
    if (parsed.documentId !== parsed.documentId.toLowerCase()) {
      return { valid: false, error: "Document ids are lowercase.", suggestion: normalized };
    }
    const documents = new Set(Array.from(knownCitations, (citation) => citation.split(" §", 1)[0]));
    if (!documents.has(parsed.documentId)) {
      return { valid: false, error: `Unknown document id “${parsed.documentId}”.`, suggestion: null };
    }
    if (!knownCitations.has(normalized)) {
      return { valid: false, error: `Unknown section “${parsed.section}” in ${parsed.documentId}.`, suggestion: null };
    }
    return { valid: true, citation: normalized, parsed };
  }

  function checkQuote(citation, quote, knownCitations, sectionCache) {
    const result = validateCitation(citation, knownCitations);
    if (!result.valid) return { status: "invalid", ...result };
    const content = sectionCache.get(result.citation);
    if (content === undefined) {
      return { status: "unread", citation: result.citation, message: "cited section not yet read — quote cannot be verified" };
    }
    const verbatim = normalizeQuote(content).includes(normalizeQuote(quote));
    return verbatim
      ? { status: "valid", citation: result.citation }
      : { status: "fabricated", citation: result.citation,
          message: `this is not verbatim text of ${result.citation}; a non-verbatim quote is a critical failure` };
  }

  return { normalizeQuote, parseCitation, normalizationCandidate, validateCitation, checkQuote };
});
