"use strict";

const assert = require("node:assert/strict");
const score = require("../web/score.js");

const sections = score.diagnostics({
  fabricated_quotes: ["msa §4.2: invented warranty"],
  invalid_citations: ["msa §99.1", "dpa §404"],
});
assert.deepEqual(sections.map((section) => section.title), ["Fabricated quotes", "Invalid citations"]);
assert.deepEqual(sections[0].values, ["msa §4.2: invented warranty"]);
assert.deepEqual(sections[1].values, ["msa §99.1", "dpa §404"]);
assert.equal(score.humanizeCriterion("liability_supercap"), "liability supercap");

console.log("score helpers: ok");
