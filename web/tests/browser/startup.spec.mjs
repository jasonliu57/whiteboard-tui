import { test, expect } from '@playwright/test';
import createModule from '../../dist/runtime/whiteboard.mjs';
import { Engine } from '../../src/engine.js';

async function traceStartup(page) {
  await page.addInitScript(() => {
    const trace = window.startupTrace = { requests: [], visible: [] };
    const NativeWorker = window.Worker;
    window.Worker = class extends NativeWorker {
      postMessage(message, ...args) {
        trace.requests.push({ type: message.type, columns: message.payload?.columns, rows: message.payload?.rows });
        return super.postMessage(message, ...args);
      }
    };
    let previous;
    const sample = () => {
      const app = document.querySelector('.tiwb-app');
      const terminal = document.querySelector('.tiwb-terminal');
      const viewport = document.querySelector('.tiwb-viewport');
      if (!terminal || getComputedStyle(terminal).visibility !== 'visible') return;
      const rows = [...terminal.querySelectorAll('.xterm-rows > div')];
      const status = rows.findLast(row => row.textContent.trim());
      if (!status) return;
      const screen = terminal.querySelector('.xterm-screen').getBoundingClientRect();
      const data = { rows: rows.length, statusRow: rows.indexOf(status) + 1,
        rowHeight: status.getBoundingClientRect().height,
        width: screen.width, height: screen.height, viewportWidth: viewport.clientWidth, viewportHeight: viewport.clientHeight,
        loading: app.dataset.loading === 'true', busy: app.getAttribute('aria-busy'),
        text: rows.map(row => row.textContent.trim()).join('\n') };
      const key = JSON.stringify(data);
      if (key !== previous) { trace.visible.push(data); previous = key; }
    };
    new MutationObserver(sample).observe(document, { subtree: true, attributes: true, childList: true, characterData: true });
  });
}

async function ready(page) {
  await expect(page.locator('.tiwb-app')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('.tiwb-app')).not.toHaveAttribute('data-loading', 'true');
  await expect(page.locator('#startup-error')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.startupTrace.visible.length)).toBeGreaterThan(0);
  return page.evaluate(() => window.startupTrace);
}

function expectFittedFrames(trace) {
  expect(trace.visible.length).toBeGreaterThan(0);
  for (const frame of trace.visible) {
    expect(frame.loading).toBe(false);
    expect(frame.busy).toBe('false');
    expect(frame.statusRow).toBe(frame.rows);
    expect(frame.width).toBeLessThanOrEqual(frame.viewportWidth);
    expect(frame.height).toBeLessThanOrEqual(frame.viewportHeight);
    expect(frame.viewportHeight - frame.height).toBeLessThan(frame.rowHeight);
  }
}

for (const subset of ['latin', 'box']) {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    test(`delayed ${subset} font initializes the first visible frame at final dimensions ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await traceStartup(page);
      let release;
      const fontReady = new Promise(resolve => { release = resolve; });
      let requested = false;
      await page.route(`**/jetbrains-mono-${subset}-wght-normal.woff2`, async route => {
        requested = true; await fontReady; await route.continue();
      });
      await page.goto('/?mode=edit', { waitUntil: 'domcontentloaded' });
      await expect.poll(() => requested).toBe(true);
      await expect(page.locator('.tiwb-app')).toHaveAttribute('data-loading', 'true');
      expect(await page.locator('.tiwb-viewport').evaluate(el => el.clientHeight)).toBe(viewport.height - 48);
      expect(await page.evaluate(() => window.startupTrace.requests)).toEqual([]);
      expect(await page.locator('.xterm-screen').count()).toBe(0);
      release();
      const trace = await ready(page);
      expectFittedFrames(trace);
      expect(trace.requests.map(request => request.type)).toEqual(['init']);
      expect(trace.requests[0].rows).toBe(trace.visible[0].rows);
    });
  }
}

for (const pattern of ['**/*.woff2', '**/jetbrains-mono-box-wght-normal.woff2']) {
  test(`a failed web font uses stable fallback dimensions (${pattern})`, async ({ page }) => {
    await traceStartup(page);
    await page.route(pattern, route => route.abort('failed'));
    await page.goto('/?mode=edit');
    const trace = await ready(page);
    expectFittedFrames(trace);
    expect(trace.requests.map(request => request.type)).toEqual(['init']);
  });
}

test('a viewport change while WASM loads is settled before revealing the terminal', async ({ page }) => {
  await traceStartup(page);
  let release;
  const wasmReady = new Promise(resolve => { release = resolve; });
  await page.route('**/whiteboard.wasm', async route => { await wasmReady; await route.continue(); });
  await page.goto('/?mode=edit', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.startupTrace.requests.length)).toBe(1);
  await page.setViewportSize({ width: 390, height: 844 });
  release();
  const trace = await ready(page);
  expectFittedFrames(trace);
  expect(trace.requests.map(request => request.type)).toEqual(['init', 'resize']);
  expect(trace.visible.every(frame => frame.viewportWidth === 390)).toBe(true);
});

test('the first visible document is the saved article draft, and reset still restores the original', async ({ page }) => {
  const engine = new Engine(await createModule());
  let bytes;
  try {
    engine.create(80, 24); engine.input('nORIGINAL'); engine.resetInput();
    bytes = Buffer.from(engine.export());
  } finally { engine.destroy(); }
  await page.route('**/article.tiwb', route => route.fulfill({ body: bytes, contentType: 'application/octet-stream' }));
  await traceStartup(page);
  await page.goto('/?file=/article.tiwb&mode=edit');
  expectFittedFrames(await ready(page));
  await expect(page.locator('.xterm-rows')).toContainText('ORIGINAL');
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.type('nDRAFT');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+s');
  await expect(page.locator('.tiwb-save-state')).toHaveText('草稿已儲存');
  await page.reload();
  const restored = await ready(page);
  expectFittedFrames(restored);
  expect(restored.visible.every(frame => frame.text.includes('DRAFT'))).toBe(true);
  let dialogs = 0;
  page.on('dialog', async dialog => { dialogs++; await dialog.dismiss(); });
  await page.getByRole('button', { name: '恢復原稿', exact: true }).click();
  await expect(page.locator('.xterm-rows')).toContainText('ORIGINAL');
  await expect(page.locator('.xterm-rows')).not.toContainText('DRAFT');
  expect(dialogs).toBe(0);
  await page.reload();
  const reset = await ready(page);
  expectFittedFrames(reset);
  expect(reset.visible.every(frame => frame.text.includes('ORIGINAL') && !frame.text.includes('DRAFT'))).toBe(true);
});
