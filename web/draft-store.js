/* IndexedDB-backed workspace drafts with a localStorage fallback. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PlaybookDraftStore = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const DB_NAME = "playbook-workspace";
  const STORE_NAME = "drafts";

  function create(options = {}) {
    const indexedDB = options.indexedDB;
    const storage = options.storage;
    let databasePromise = null;
    let fallback = !indexedDB;

    function openDatabase() {
      if (fallback) return Promise.reject(new Error("IndexedDB unavailable"));
      if (databasePromise) return databasePromise;
      databasePromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = () => {
          if (!request.result.objectStoreNames.contains(STORE_NAME)) {
            request.result.createObjectStore(STORE_NAME);
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("IndexedDB open failed"));
        request.onblocked = () => reject(new Error("IndexedDB upgrade blocked"));
      }).catch((error) => {
        fallback = true;
        databasePromise = null;
        throw error;
      });
      return databasePromise;
    }

    async function idbOperation(mode, operation) {
      const database = await openDatabase();
      return new Promise((resolve, reject) => {
        const transaction = database.transaction(STORE_NAME, mode);
        const request = operation(transaction.objectStore(STORE_NAME));
        request.onsuccess = () => resolve(request.result ?? null);
        request.onerror = () => reject(request.error || new Error("IndexedDB operation failed"));
        transaction.onabort = () => reject(transaction.error || new Error("IndexedDB transaction aborted"));
      });
    }

    function fallbackGet(key) {
      if (!storage) return null;
      try { return JSON.parse(storage.getItem(key)); } catch { return null; }
    }

    return {
      async get(key) {
        if (!fallback) {
          try {
            const value = await idbOperation("readonly", (store) => store.get(key));
            if (value !== null) return value;
            const legacy = fallbackGet(key);
            if (legacy !== null) {
              await idbOperation("readwrite", (store) => store.put(legacy, key));
              try { storage?.removeItem(key); } catch { /* migrated in primary storage */ }
            }
            return legacy;
          }
          catch { fallback = true; }
        }
        return fallbackGet(key);
      },
      async set(key, value) {
        if (!fallback) {
          try { await idbOperation("readwrite", (store) => store.put(value, key)); return "indexeddb"; }
          catch { fallback = true; }
        }
        if (!storage) throw new Error("Browser storage unavailable");
        storage.setItem(key, JSON.stringify(value));
        return "localstorage";
      },
      async delete(key) {
        if (!fallback) {
          try { await idbOperation("readwrite", (store) => store.delete(key)); }
          catch { fallback = true; }
        }
        try { storage?.removeItem(key); } catch { /* optional fallback */ }
      },
      backend() { return fallback ? "localstorage" : "indexeddb"; },
    };
  }

  return { create, constants: { DB_NAME, STORE_NAME } };
});
