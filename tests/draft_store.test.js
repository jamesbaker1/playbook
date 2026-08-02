"use strict";

const assert = require("node:assert/strict");
const drafts = require("../web/draft-store.js");

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

(async () => {
  const storage = memoryStorage();
  const store = drafts.create({ indexedDB: null, storage });
  const value = { version: 1, fields: { "issue-title": "Training right" } };

  assert.equal(store.backend(), "localstorage");
  assert.equal(await store.set("matter-1", value), "localstorage");
  assert.deepEqual(await store.get("matter-1"), value);
  await store.delete("matter-1");
  assert.equal(await store.get("matter-1"), null);

  const brokenIndexedDb = { open() { throw new Error("blocked"); } };
  const degraded = drafts.create({ indexedDB: brokenIndexedDb, storage });
  assert.equal(await degraded.set("matter-2", value), "localstorage");
  assert.equal(degraded.backend(), "localstorage");
  assert.deepEqual(await degraded.get("matter-2"), value);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
