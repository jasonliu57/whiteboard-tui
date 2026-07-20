import test from 'node:test';
import assert from 'node:assert/strict';
import { DraftStore } from '../src/drafts.js';

// Minimal transactional IDB test double: writes commit only after get succeeds.
function database(t) {
  const previous = globalThis.indexedDB;
  t.after(() => { globalThis.indexedDB = previous; });
  const records = new Map();
  const db = {
    failNext: false,
    createObjectStore(name) { assert.equal(name, 'drafts'); },
    close() {},
    transaction(name, mode) {
      assert.equal(name, 'drafts');
      let aborted = false;
      const writes = new Map();
      const tx = {
        abort() { aborted = true; },
        objectStore() {
          return {
            get(key) {
              const request = {};
              setImmediate(() => {
                if (db.failNext) {
                  db.failNext = false;
                  tx.error = new Error('storage unavailable');
                  tx.onabort();
                  return;
                }
                request.result = records.get(key);
                request.onsuccess?.();
                if (aborted) { tx.onabort(); return; }
                for (const [key, value] of writes) records.set(key, value);
                tx.oncomplete();
              });
              return request;
            },
            put(value, key) { assert.equal(mode, 'readwrite'); writes.set(key, value); },
          };
        },
      };
      return tx;
    },
  };
  globalThis.indexedDB = { open(name, version) {
    assert.equal(name, 'whiteboard-tui'); assert.equal(version, 1);
    const request = { result: db };
    setImmediate(() => { request.onupgradeneeded(); request.onsuccess(); });
    return request;
  } };
  return { db, records };
}

test('clear removes only this document and keeps a version tombstone', async t => {
  const { records } = database(t);
  const first = new DraftStore('article:first');
  const other = new DraftStore('article:other');
  await first.open(); await other.open();
  await first.write({ bytes: new Uint8Array([1]), name: 'first.tiwb' });
  await other.write({ bytes: new Uint8Array([2]), name: 'other.tiwb' });
  const version = first.version;
  await first.clear();
  assert.equal(await first.read(), undefined);
  assert.notEqual(first.version, version);
  assert.equal(records.get('article:first').bytes, undefined);
  assert.equal(records.get('article:first').name, undefined);
  assert.equal((await other.read()).name, 'other.tiwb');
  const reopened = new DraftStore('article:first');
  assert.equal(await reopened.open(), undefined);
  assert.equal(reopened.version, first.version);
  await reopened.write({ bytes: new Uint8Array([3]), name: 'new.tiwb' });
  assert.equal((await reopened.read()).name, 'new.tiwb');
});

test('a reset cannot resurrect a stale draft even when both tabs began empty', async t => {
  database(t);
  const reset = new DraftStore('article');
  const stale = new DraftStore('article');
  await reset.open(); await stale.open();
  await reset.clear();
  await assert.rejects(stale.write({ bytes: new Uint8Array([1]) }), /另一個頁面/);
  assert.equal(await reset.read(), undefined);
});

test('reset refuses to clear a draft updated by another tab', async t => {
  database(t);
  const reset = new DraftStore('article');
  const writer = new DraftStore('article');
  await reset.open(); await writer.open();
  await writer.write({ bytes: new Uint8Array([7]), name: 'newer.tiwb' });
  await assert.rejects(reset.clear(), /另一個頁面/);
  assert.equal((await writer.read()).name, 'newer.tiwb');
});

test('failed clear retains document bytes and the last acknowledged version', async t => {
  const { db } = database(t);
  const draft = new DraftStore('article');
  await draft.open();
  await draft.write({ bytes: new Uint8Array([1]), name: 'keep.tiwb' });
  const version = draft.version;
  db.failNext = true;
  await assert.rejects(draft.clear(), /storage unavailable/);
  assert.equal(draft.version, version);
  assert.equal((await draft.read()).name, 'keep.tiwb');
  await draft.clear();
  await draft.clear();
  assert.equal(await draft.read(), undefined);
});
