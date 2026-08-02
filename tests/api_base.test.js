"use strict";

const assert = require("node:assert/strict");
const apiBase = require("../web/api-base.js");

function storage(value, throws = false) {
  return { getItem(key) {
    assert.equal(key, apiBase.STORAGE_KEY);
    if (throws) throw new Error("storage disabled");
    return value;
  } };
}

assert.equal(apiBase.resolve({ search: "?api=http%3A%2F%2Flocalhost%3A8787", storage: storage("https://stored.example") }), "http://localhost:8787");
assert.equal(apiBase.resolve({ storage: storage("https://stored.example/") }), "https://stored.example");
assert.equal(apiBase.resolve({ storage: storage(null) }), apiBase.DEFAULT_API_BASE);
assert.equal(apiBase.resolve({ storage: storage(null, true) }), apiBase.DEFAULT_API_BASE);
assert.equal(apiBase.resolve({ search: "?api=javascript%3Aalert(1)", storage: storage("https://stored.example") }), "https://stored.example");
assert.equal(apiBase.normalize("https://user:secret@example.com"), null);
assert.equal(apiBase.normalize("https://example.com/api"), null);
assert.equal(apiBase.normalize("https://example.com?token=secret"), null);

console.log("api base tests passed");
