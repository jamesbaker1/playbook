// SPDX-License-Identifier: AGPL-3.0-only
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PlaybookScore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function diagnostics(breakdown) {
    const sections = [];
    if (breakdown.fabricated_quotes?.length) sections.push({
      title: "Fabricated quotes",
      lead: "These quotations could not be verified as verbatim text:",
      values: breakdown.fabricated_quotes.map(String),
      className: "critical",
    });
    if (breakdown.invalid_citations?.length) sections.push({
      title: "Invalid citations",
      lead: "Correct these citations:",
      values: breakdown.invalid_citations.map(String),
      className: "warning",
    });
    return sections;
  }

  function humanizeCriterion(value) {
    return String(value || "general").replaceAll("_", " ");
  }

  return { diagnostics, humanizeCriterion };
});
