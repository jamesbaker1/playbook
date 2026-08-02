"use strict";
const assert = require("node:assert/strict");
const citations = require("../web/citation.js");
const known = new Set(["msa §4.2", "playbook §3"]);
const cache = new Map([["msa §4.2", "Provider MAY   use Customer Data for analytics only."]]);
for (const [input, suggestion] of [["MSA §4.2", "msa §4.2"], ["msa 4.2", "msa §4.2"], ["msa sec. 4.2", "msa §4.2"]]) {
  const result = citations.validateCitation(input, known);
  assert.equal(result.valid, false, input);
  assert.equal(result.suggestion, suggestion, input);
}
const annotated = citations.validateCitation("msa § 4.2 (training)", known);
assert.equal(annotated.valid, false);
assert.match(annotated.error, /exactly|unknown/i);
assert.equal(citations.validateCitation("dpa §5.1", known).valid, false);
assert.equal(citations.validateCitation("msa §99", known).valid, false);
assert.equal(citations.validateCitation("msa §4.2", known).valid, true);
assert.equal(citations.checkQuote("msa §4.2", "provider may use customer data", known, cache).status, "valid");
assert.equal(citations.checkQuote("msa §4.2", "Provider may sell Customer Data", known, cache).status, "fabricated");
assert.match(citations.checkQuote("msa §4.2", "not verbatim", known, cache).message, /critical failure/);
assert.equal(citations.checkQuote("playbook §3", "some quote", known, cache).status, "unread");
assert.equal(citations.normalizeQuote("  Mixed\n  CASE\ttext "), "mixed case text");
console.log("citation helper tests passed");
