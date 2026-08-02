"use strict";
const assert = require("assert");
const Capture = require("../web/capture.js");

class Storage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

const storage = new Storage();
const session = Capture.create({
  matterId: "ai_saas_001", sessionId: "123e4567-e89b-42d3-a456-426614174000",
  engineVersion: "0.3", consentVersion: "2026-08-02", storage,
});
assert.strictEqual(session.record("document.opened", {document_id: "msa"}, {}), null);
session.setConsent(true);
session.record("document.opened", {document_id: "msa", section: "2.1"}, {source: "outline"});
session.pause();
assert.strictEqual(session.record("search.submitted", {}, {query: "secret"}), null);
const restored = Capture.create({
  matterId: "ai_saas_001", sessionId: "123e4567-e89b-42d3-a456-426614174000",
  engineVersion: "0.3", consentVersion: "2026-08-02", storage,
});
assert.strictEqual(restored.status().paused, true);
assert.strictEqual(restored.record("search.submitted", {}, {query: "still secret"}), null);
restored.resume();
restored.record("issue.saved", {document_id: "msa", issue_id: "I-1"}, {priority: "high"});
const trace = restored.complete();
assert.deepStrictEqual(trace.events.map((event) => event.sequence), [1, 2, 3, 4, 5]);
assert(!JSON.stringify(trace).includes("secret"));
assert.strictEqual(Capture.consentFor(storage, "2026-08-02").training_and_evaluation, true);
assert.strictEqual(Capture.consentFor(storage, "outdated"), null);
const attached = Capture.attachContribution({trace: {}}, restored);
assert.strictEqual(attached.contribution_id, trace.contribution_id);
assert.strictEqual(attached.interaction_trace.matter_id, "ai_saas_001");
assert.strictEqual(attached.contribution_id, attached.interaction_trace.contribution_id);
assert.strictEqual(Capture.byteLength("é"), 2);
assert.strictEqual(Capture.byteLength("🧑‍⚖️"), Buffer.byteLength("🧑‍⚖️", "utf8"));

const declinedPayload = {contribution_id: "original", trace: {}};
assert.strictEqual(
  Capture.attachContribution(declinedPayload, {complete: () => null}).contribution_id,
  "original"
);

const quotaStorage = new Storage();
quotaStorage.setItem = () => { throw new Error("quota exceeded"); };
const memoryOnly = Capture.create({
  matterId: "ai_saas_001", engineVersion: "0.3",
  consentVersion: "2026-08-02", storage: quotaStorage,
});
assert.doesNotThrow(() => memoryOnly.setConsent(true));
assert(memoryOnly.record("document.opened", {document_id: "msa"}, {}));

const sizeStorage = new Storage();
const sizeLimited = Capture.create({
  matterId: "ai_saas_001", engineVersion: "0.3",
  consentVersion: "2026-08-02", storage: sizeStorage,
});
sizeLimited.setConsent(true);
const oversized = "é".repeat(Math.ceil(Capture.constants.MAX_BYTES / 2));
assert.strictEqual(sizeLimited.record("issue.drafted", {}, {text: oversized}), null);
assert.strictEqual(sizeLimited.snapshot().events.length, 1);
restored.setConsent(false);
assert.strictEqual(restored.snapshot(), null);
