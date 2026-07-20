import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import createModule from '../../dist/runtime/whiteboard.mjs';
import { Engine } from '../../src/engine.js';

const engine = new Engine(await createModule());
engine.create(120, 40);
for (const [dx, dy, text] of [[-400, -120, 'Left'], [400, 120, 'Center'], [700, 200, 'Right']]) {
  engine.pan(dx, dy); engine.input(`n${text}`); engine.input('\x1b', true); engine.input('\x1b', true);
}
const documentBytes = [...engine.export()];
engine.create(80, 24); engine.input('i中A'); engine.input('\x1b', true);
const glyphBytes = [...engine.export()];
engine.destroy();

async function start(page, { bytes = documentBytes, readOnly = true } = {}) {
  await page.addInitScript(() => {
    const trace = window.mapTrace = { requests: [], replies: [], held: [], hold: false, pending: 0, maximum: 0, draws: 0,
      holdView: false, heldViews: [] };
    const NativeWorker = window.Worker;
    window.Worker = class extends NativeWorker {
      messages = new Map();
      postMessage(message, ...args) {
        this.messages.set(message.id, message); trace.requests.push(message);
        if (message.type === 'overview' && message.payload.enabled) {
          trace.pending++; trace.maximum = Math.max(trace.maximum, trace.pending);
        }
        return super.postMessage(message, ...args);
      }
      set onmessage(handler) {
        super.onmessage = event => {
          const message = this.messages.get(event.data.id);
          const overview = message?.type === 'overview' && message.payload.enabled;
          const deliver = () => {
            if (overview) trace.pending--;
            trace.replies.push({ type: message?.type, frame: event.data.frame?.byteLength, overview: event.data.overview });
            handler(event);
          };
          if (overview && trace.hold) trace.held.push(deliver);
          else if (message?.type === 'viewport' && trace.holdView) trace.heldViews.push(deliver);
          else deliver();
        };
      }
    };
    const draw = CanvasRenderingContext2D.prototype.strokeRect;
    CanvasRenderingContext2D.prototype.strokeRect = function(...args) {
      if (this.canvas.closest('.tiwb-minimap')) trace.draws++;
      return draw.apply(this, args);
    };
    window.releaseMap = () => { trace.hold = false; for (const deliver of trace.held.splice(0)) deliver(); };
    window.releaseMapView = () => { trace.holdView = false; for (const deliver of trace.heldViews.splice(0)) deliver(); };
  });
  await page.goto('/?mode=edit');
  await expect(page.locator('.tiwb-app')).toHaveAttribute('aria-busy', 'false');
  await page.evaluate(async ({ bytes, readOnly }) => {
    const { mountWhiteboard } = await import('/whiteboard.js');
    const host = document.createElement('div'); host.id = 'map-board';
    host.style.cssText = 'position:fixed;inset:0;z-index:20'; document.body.append(host);
    window.mapBoard = await mountWhiteboard(host, { document: new Uint8Array(bytes), readOnly,
      drafts: false, appearance: 'light', assetBaseUrl: '/runtime/', confirmDiscard: () => true });
    window.mapTrace.requests = []; window.mapTrace.replies = [];
  }, { bytes, readOnly });
  return page.locator('#map-board');
}
async function open(host) {
  await host.locator('[data-map="toggle"]').click();
  await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'false');
  await expect(host.locator('.tiwb-map-frame')).toBeVisible();
}
const queries = page => page.evaluate(() => window.mapTrace.requests.filter(r => r.type === 'overview' && r.payload.enabled).length);

test('overview navigation preserves the document, zoom and terminal dimensions', async ({ page }) => {
  const host = await start(page);
  const before = await page.evaluate(async () => ({ bytes: [...(await window.mapBoard.export()).bytes], state: window.mapBoard.getState() }));
  expect(await queries(page)).toBe(0);
  await open(host);
  const after = await page.evaluate(() => window.mapBoard.getState());
  expect(after).toEqual(before.state);
  expect(await page.evaluate(() => window.mapTrace.replies.filter(r => r.type === 'overview').every(r => r.frame === undefined))).toBe(true);
  await host.locator('.tiwb-map-surface').press('Home');
  await expect.poll(() => page.evaluate(() => window.mapBoard.getState().x)).not.toBe(before.state.x);
  await expect(host.locator('.tiwb-zoom').first()).toHaveText('100%');
  expect(await page.evaluate(async () => [...(await window.mapBoard.export()).bytes])).toEqual(before.bytes);
  const state = await page.evaluate(() => window.mapBoard.getState());
  expect(state).toMatchObject({ columns: before.state.columns, rows: before.state.rows,
    revision: before.state.revision, dirty: false });
  expect(await page.evaluate(() => window.mapTrace.requests.filter(r => r.type === 'viewport').length)).toBe(1);
  const panelBottom = await host.locator('.tiwb-map-panel').evaluate(el => el.getBoundingClientRect().bottom);
  const statusTop = await host.locator('.tiwb-terminal .xterm-rows > div').last().evaluate(el => el.getBoundingClientRect().top);
  expect(panelBottom).toBeLessThan(statusTop);
  // Choose a painted card in the actual canvas, independent of its projection.
  const card = await host.locator('canvas').evaluate(canvas => {
    const ctx = canvas.getContext('2d'), pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
      const i = (y * canvas.width + x) * 4;
      if (pixels[i + 2] > pixels[i] + 50 && pixels[i + 3] > 100)
        return { x: x * canvas.clientWidth / canvas.width, y: y * canvas.clientHeight / canvas.height };
    }
    throw new Error('No card was drawn');
  });
  await host.locator('.tiwb-map-surface').click({ position: card });
  await expect.poll(() => page.evaluate(() => BigInt(window.mapBoard.getState().x) < -300n)).toBe(true);
  await expect(host.locator('.xterm-rows')).toContainText('Left');
  await page.screenshot({ path: 'test-results/minimap-desktop.png' });
});

test('panning changes only the overlay; closing and hiding suspend overview work', async ({ page }) => {
  const host = await start(page);
  await open(host);
  const before = await page.evaluate(() => ({ draws: window.mapTrace.draws, state: window.mapBoard.getState() }));
  await host.locator('.tiwb-map-surface').focus();
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight');
  await expect.poll(() => page.evaluate(() => window.mapBoard.getState().x)).not.toBe(before.state.x);
  await page.waitForTimeout(250);
  expect(await queries(page)).toBe(1);
  expect(await page.evaluate(() => window.mapTrace.draws)).toBe(before.draws);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => page.evaluate(() => window.mapTrace.requests.filter(r => r.type === 'overview' && !r.payload.enabled).length)).toBe(1);
  await page.waitForTimeout(250);
  expect(await queries(page)).toBe(1);
  await page.evaluate(() => {
    delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => queries(page)).toBe(2);
  await host.locator('.tiwb-map-surface').press('Escape');
  await expect(host.locator('[data-map="toggle"]')).toBeFocused();
  await expect(host.locator('.tiwb-map-panel')).toBeHidden();
  await page.waitForTimeout(250);
  expect(await queries(page)).toBe(2);
});

test('an open map permits editing, updates after undo/redo and bounds its request queue', async ({ page }) => {
  const host = await start(page, { readOnly: false });
  await open(host);
  await page.evaluate(() => { window.mapTrace.hold = true; });
  await host.locator('.xterm-helper-textarea').focus();
  await page.keyboard.type('nNew content');
  await expect.poll(() => page.evaluate(() => window.mapTrace.held.length)).toBe(1);
  await page.keyboard.insertText(' '.repeat(20) + 'More');
  expect(await page.evaluate(() => window.mapTrace.maximum)).toBe(1);
  await page.evaluate(() => window.releaseMap());
  await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => window.mapBoard.getState().cards)).toBe(4);
  await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'false');
  const beforeUndo = await queries(page);
  await page.keyboard.press('Control+z');
  await expect.poll(() => queries(page)).toBeGreaterThan(beforeUndo);
  await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'false');
  const beforeRedo = await queries(page);
  await page.keyboard.press('Control+r');
  await expect.poll(() => queries(page)).toBeGreaterThan(beforeRedo);
  expect(await page.evaluate(() => window.mapTrace.maximum)).toBe(1);
});

test('stale overview replies cannot restore an old document after replacement', async ({ page }) => {
  const host = await start(page);
  await page.evaluate(() => { window.mapTrace.hold = true; });
  await host.locator('[data-map="toggle"]').click();
  await expect.poll(() => page.evaluate(() => window.mapTrace.held.length)).toBe(1);
  await page.evaluate(() => window.mapBoard.newDocument());
  const fresh = await page.evaluate(() => window.mapBoard.getState());
  await page.evaluate(() => window.releaseMap());
  await expect.poll(() => page.evaluate(() => window.mapTrace.replies.some(r => r.type === 'overview' && r.overview?.rect === null))).toBe(true);
  expect(await page.evaluate(() => window.mapBoard.getState())).toEqual(fresh);
  await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'true');
  await expect(host.locator('.tiwb-map-frame')).toBeHidden();
});

test('glyph-only content appears and delayed overview disposal is safe', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const host = await start(page, { bytes: glyphBytes });
  await open(host);
  expect(await page.evaluate(() => window.mapBoard.getState().cards)).toBe(0);
  await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'false');
  await host.locator('[data-map="close"]').click();
  await page.evaluate(() => { window.mapTrace.hold = true; });
  await host.locator('[data-map="toggle"]').click();
  await expect.poll(() => page.evaluate(() => window.mapTrace.held.length)).toBe(1);
  await page.evaluate(() => { window.mapBoard.dispose(); window.releaseMap(); });
  await expect(host.locator('.tiwb-app')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('document replacement drains accepted navigation and cancels a queued map click', async ({ page }) => {
  const host = await start(page);
  await open(host);
  await page.evaluate(() => { window.mapTrace.holdView = true; });
  await host.locator('.tiwb-map-surface').click();
  await expect.poll(() => page.evaluate(() => window.mapTrace.heldViews.length)).toBe(1);
  await page.evaluate(() => {
    document.querySelector('#map-board .tiwb-map-surface').click();
    window.nextDocument = window.mapBoard.newDocument();
  });
  expect(await page.evaluate(() => window.mapTrace.requests.some(r => r.type === 'new'))).toBe(false);
  await page.evaluate(async () => { window.releaseMapView(); await window.nextDocument; });
  await expect.poll(() => page.evaluate(() => window.mapTrace.replies.some(r => r.type === 'overview' && r.overview?.rect === null))).toBe(true);
  await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'true');
  expect(await page.evaluate(() => window.mapBoard.getState())).toMatchObject({ cards: 0, dirty: false, x: '0', y: '0' });
  expect(await page.evaluate(() => window.mapTrace.requests.filter(r => r.type === 'viewport').length)).toBe(1);
});

test('an edit racing a map click still synchronizes an independently resized terminal', async ({ page }) => {
  const host = await start(page, { readOnly: false });
  await open(host);
  await page.evaluate(() => {
    const host = document.querySelector('#map-board');
    const textarea = host.querySelector('.xterm-helper-textarea'); textarea.focus();
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', code: 'KeyN', keyCode: 78, which: 78, bubbles: true }));
    host.querySelector('.tiwb-map-surface').click();
    host.style.width = '900px';
  });
  await expect.poll(() => page.evaluate(() => window.mapBoard.getState().cards)).toBe(4);
  await expect(host.locator('.tiwb-notice')).toContainText('小地圖正在更新');
  await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
  const geometry = await page.evaluate(() => {
    const screen = document.querySelector('#map-board .xterm-screen');
    const state = window.mapBoard.getState();
    return { columns: state.columns, width: screen.clientWidth,
      rows: state.rows, renderedRows: screen.querySelector('.xterm-rows').children.length };
  });
  expect(geometry.columns).toBe(90);
  expect(geometry.width).toBe(geometry.columns * 10);
  expect(geometry.renderedRows).toBe(geometry.rows);
});

test('compact touch layout, theme changes and map controls stay within their host', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    const host = await start(page);
    await host.locator('[data-map="toggle"]').tap();
    await expect(host.locator('.tiwb-map-surface')).toHaveAttribute('aria-disabled', 'false');
    const original = await page.evaluate(async () => [...(await window.mapBoard.export()).bytes]);
    await page.evaluate(() => window.mapBoard.setAppearance('dark'));
    await expect(host.locator('.tiwb-app')).toHaveAttribute('data-appearance', 'dark');
    await page.setViewportSize({ width: 280, height: 430 });
    const panel = await host.locator('.tiwb-map-panel').boundingBox();
    expect(panel.x).toBeGreaterThanOrEqual(0); expect(panel.x + panel.width).toBeLessThanOrEqual(280);
    expect(panel.y).toBeGreaterThanOrEqual(48); expect(panel.y + panel.height).toBeLessThan(430);
    await host.locator('.tiwb-map-surface').tap();
    await expect.poll(() => page.evaluate(() => window.mapBoard.getState().x)).not.toBe('0');
    expect(await page.evaluate(async () => [...(await window.mapBoard.export()).bytes])).toEqual(original);
    await page.screenshot({ path: 'test-results/minimap-mobile.png' });
  } finally { await context.close(); }
});

test('Worker rejects obsolete navigation and centers precisely beyond Number safe integers', async ({ page }) => {
  const directory = await mkdtemp(join(tmpdir(), 'whiteboard-overview-'));
  let bytes;
  try {
    const path = join(directory, 'extreme.tiwb');
    execFileSync(resolve(process.env.WHITEBOARD_FIXTURE || '../build/standalone/whiteboard_web_fixture'), [path, 'overview-extreme']);
    bytes = [...await readFile(path)];
  } finally { await rm(directory, { recursive: true, force: true }); }
  await start(page);
  const result = await page.evaluate(async bytes => {
    const worker = new Worker('/runtime/whiteboard.worker.js', { type: 'module' });
    let next = 0; const pending = new Map();
    worker.onmessage = ({ data }) => { const job = pending.get(data.id); pending.delete(data.id); data.error ? job.reject(new Error(data.error)) : job.resolve(data); };
    const request = (type, payload = {}) => new Promise((resolve, reject) => {
      const id = ++next; pending.set(id, { resolve, reject }); worker.postMessage({ id, type, payload });
    });
    try {
      await request('init', { columns: 80, rows: 24 });
      const opened = await request('open', { bytes: new Uint8Array(bytes).buffer });
      const original = await request('export');
      const overview = await request('overview', { enabled: true, generation: opened.state.generation });
      const centered = await request('viewport', { columns: 80, rows: 24, generation: opened.state.generation,
        center: { revision: opened.state.revision, x: 0.5, y: 0.5 } });
      const exported = await request('export');
      await request('input', { text: 'nChanged', epoch: opened.epoch });
      const stale = await request('viewport', { columns: 100, rows: 40, generation: opened.state.generation,
        center: { revision: opened.state.revision, x: 0.5, y: 0.5 } });
      const fresh = await request('new', { columns: 80, rows: 24 });
      const obsolete = await request('viewport', { columns: 100, rows: 40, generation: opened.state.generation,
        center: { revision: opened.state.revision, x: 0.5, y: 0.5 } });
      const empty = await request('overview', { enabled: true, generation: fresh.state.generation });
      const invalid = await request('viewport', { columns: 100, rows: 40, generation: fresh.state.generation,
        center: { revision: fresh.state.revision, x: 0.5, y: 0.5 } });
      return { queryFrame: overview.frame, state: centered.state, original: [...new Uint8Array(original.bytes)],
        exported: [...new Uint8Array(exported.bytes)], stale, obsolete, fresh: fresh.state, empty: empty.overview, invalid };
    } finally { worker.terminate(); }
  }, bytes);
  expect(result.queryFrame).toBeUndefined();
  expect(result.state.x).toBe(((1n << 63n) - 1n - 240n).toString());
  expect(result.state.y).toBe((-(1n << 63n) + 183n).toString());
  expect(result.exported).toEqual(result.original);
  expect(result.stale.navigationRejected).toBe(true);
  expect(result.stale.state.columns).toBe(80);
  expect(result.stale.frame).toBeUndefined();
  expect(result.obsolete.state).toEqual(result.fresh);
  expect(result.empty.rect).toBeNull();
  expect(result.invalid.navigationRejected).toBe(true);
  expect(result.invalid.state).toEqual(result.fresh);
});
