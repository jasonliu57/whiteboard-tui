import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { execFileSync } from 'node:child_process';
import createModule from '../../build/web/web/whiteboard.mjs';
import { Engine, MAX_INPUT_BYTES } from '../src/engine.js';
import { createUnicodeProvider } from '../src/unicode.js';
import { readUnicodeContract } from '../scripts/unicode-contract.mjs';

const engine = new Engine(await createModule());
const inspector = resolve(process.env.WHITEBOARD_INSPECT || '../build/standalone/whiteboard-inspect');
const fixture = resolve(process.env.WHITEBOARD_FIXTURE || '../build/standalone/whiteboard_web_fixture');

test('native and WASM round-trip every format, stable slots, styles, edges and Unicode', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'whiteboard-web-'));
  try {
    const native = join(directory, 'native.tiwb');
    const browser = join(directory, 'browser.tiwb');
    execFileSync(fixture, [native]);
    const bytes = new Uint8Array(await readFile(native));
    engine.create(80, 24); engine.open(bytes);
    assert.equal(engine.state().cards, 7);
    assert.equal(engine.state().edges, 1);
    const overview = engine.overview();
    const kinds = [...overview].filter((_, index) => index >= 2 && (index - 2) % 6 === 0);
    assert.equal(kinds.filter(kind => kind === 0).length, 7);
    assert.equal(kinds.filter(kind => kind === 1).length, 2);
    assert.equal(kinds.filter(kind => kind === 2).length, 1);
    assert.deepEqual(engine.export(), bytes);
    await writeFile(browser, engine.export());
    const nativeSnapshot = join(directory, 'native.snapshot');
    const browserSnapshot = join(directory, 'browser.snapshot');
    execFileSync(inspector, ['snapshot', native, '--output', nativeSnapshot]);
    execFileSync(inspector, ['snapshot', browser, '--output', browserSnapshot]);
    assert.deepEqual(await readFile(browserSnapshot), await readFile(nativeSnapshot));
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('editing, undo, redo and stale save acknowledgement retain document state', () => {
  engine.create(80, 24);
  engine.input('nHello 中文 e\u0301');
  const original = engine.export();
  const saved = engine.state();
  engine.markSaved(saved.revision); assert.equal(engine.state().dirty, false);
  engine.input('!');
  engine.markSaved(saved.revision); assert.equal(engine.state().dirty, true);
  engine.input('\x1b', true); engine.input('\x1b', true);
  engine.input('\x1a'); assert.deepEqual(engine.export(), original);
  engine.input('\x12'); assert.notDeepEqual(engine.export(), original);
});

test('damaged and unsupported files leave the active document and history intact', () => {
  engine.create(80, 24); engine.input('nPreserve me');
  const before = engine.export(); const state = engine.state();
  for (const mutation of [bytes => bytes[4] = 10, bytes => bytes[bytes.length - 1] ^= 1]) {
    const bytes = before.slice(); mutation(bytes);
    assert.throws(() => engine.open(bytes));
    assert.deepEqual(engine.export(), before);
    assert.deepEqual(engine.state(), state);
  }
  assert.throws(() => engine.open(before.subarray(0, 20)));
  assert.throws(() => engine.input('x'.repeat(MAX_INPUT_BYTES + 1)));
  assert.deepEqual(engine.export(), before);
});

test('viewport changes and clearing interactions do not edit the document', () => {
  engine.create(80, 24); engine.input('nStable');
  const bytes = engine.export(); const revision = engine.state().revision;
  engine.resetInput(); engine.pan(17, -25); engine.resize(40, 12);
  assert.equal(engine.state().x, '17'); assert.equal(engine.state().y, '-25');
  assert.equal(engine.state().revision, revision);
  assert.deepEqual(engine.export(), bytes);
  assert.throws(() => engine.resize(100000, 100000));
});

test('an unterminated paste is bounded and the decoder recovers after rejection', () => {
  engine.create(80, 24);
  const before = engine.export();
  engine.input('\x1b[200~' + 'x'.repeat(MAX_INPUT_BYTES - 6));
  assert.equal(engine.pendingInput(), MAX_INPUT_BYTES);
  assert.throws(() => engine.input('x'), /pending input/);
  assert.equal(engine.pendingInput(), 0);
  assert.deepEqual(engine.export(), before);
  engine.input('nRecovered');
  assert.equal(engine.state().cards, 1);
});

test('browser Unicode provider uses the shared width contract', async () => {
  const provider = createUnicodeProvider(await readUnicodeContract());
  assert.equal(provider.version, '16.0.0');
  for (const [text, width] of [['A', 1], ['中', 2], ['「', 2], ['」', 2], ['『', 2], ['』', 2], ['─', 1], ['\u0301', 0], ['😀', 2]])
    assert.equal(provider.wcwidth(text.codePointAt(0)), width);
  assert.equal(provider.charProperties(0x301, 2), 3);
});

test('overview is a cached display projection and navigation preserves document bytes', () => {
  engine.create(80, 24);
  assert.deepEqual([...engine.overview()], [1, 0]);
  assert.equal(engine.overviewView(), null);
  assert.throws(() => engine.centerOverview(0.5, 0.5));
  engine.pan(-300, -200); engine.input('nMap 「text」');
  engine.input('\x1b', true); engine.input('\x1b', true);
  const bytes = engine.export(), before = engine.state();
  const scene = engine.overview();
  assert.equal(scene.length, 8);
  assert.equal(scene[0], 1);
  assert.deepEqual([...scene.slice(4)], [0, 0, 1, 1]);
  const frame = engine.frame(); assert.ok(frame.length);
  assert.deepEqual(engine.overview(), scene);
  assert.equal(engine.frame().length, 0); // the query did not consume/reset ANSI
  assert.throws(() => engine.centerOverview(Infinity, 0));
  assert.throws(() => engine.centerOverview(0, -1));
  engine.centerOverview(0.5, 0.5);
  assert.notEqual(engine.state().x, before.x);
  assert.equal(engine.state().revision, before.revision);
  assert.deepEqual(engine.export(), bytes);
  assert.equal(engine.overviewView().length, 4);
  engine.pan(1500, 2000);
  assert.deepEqual(engine.overview(), scene);
  assert.ok(engine.overviewView()[0] > 1);
  engine.input('nAnother');
  assert.throws(() => engine.centerOverview(0.5, 0.5), /小地圖正在更新/);
  assert.ok(engine.overview().length > scene.length);
  engine.open(bytes);
  assert.equal(engine.overviewView(), null);
  assert.throws(() => engine.centerOverview(0.5, 0.5));
  assert.deepEqual(engine.overview(), scene);
});

test('oversized overviews reject atomically and recover for a new document', () => {
  engine.create(80, 24); engine.input('i');
  engine.input('\x1b[200~' + 'x'.repeat(65537) + '\x1b[201~');
  const bytes = engine.export(), state = engine.state();
  assert.throws(() => engine.overview(), /內容過多/);
  assert.equal(engine.overviewView(), null);
  assert.deepEqual(engine.state(), state);
  assert.deepEqual(engine.export(), bytes);
  engine.create(80, 24);
  assert.deepEqual([...engine.overview()], [1, 0]);
});
