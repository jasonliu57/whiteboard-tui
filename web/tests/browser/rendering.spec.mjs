import { test, expect } from '@playwright/test';
import createModule from '../../dist/runtime/whiteboard.mjs';
import { Engine } from '../../src/engine.js';

async function start(page, { readOnly = false, confirm = false } = {}) {
  await page.addInitScript(() => {
    const trace = window.viewTrace = { requests: [], replies: [], held: [], hold: [], pending: 0, maximumPending: 0 };
    const NativeWorker = window.Worker;
    window.Worker = class extends NativeWorker {
      types = new Map();
      postMessage(message, ...args) {
        this.types.set(message.id, message.type);
        trace.requests.push(message);
        if (message.type === 'viewport') {
          trace.pending++;
          trace.maximumPending = Math.max(trace.maximumPending, trace.pending);
        }
        return super.postMessage(message, ...args);
      }
      set onmessage(handler) {
        super.onmessage = event => {
          const type = this.types.get(event.data.id);
          const deliver = () => {
            if (type === 'viewport') trace.pending--;
            trace.replies.push({ type, state: event.data.state, bytes: event.data.frame?.byteLength });
            handler(event);
          };
          if (trace.hold.includes(type)) trace.held.push(deliver);
          else deliver();
        };
      }
    };
    window.releaseViews = () => {
      trace.hold = [];
      for (const deliver of trace.held.splice(0)) deliver();
    };
  });
  await page.goto('/?mode=edit');
  await expect(page.locator('.tiwb-app')).toHaveAttribute('aria-busy', 'false');
  await page.evaluate(async ({ readOnly, confirm }) => {
    const { mountWhiteboard } = await import('/whiteboard.js');
    const host = document.createElement('div');
    host.id = 'review-board'; host.style.cssText = 'position:fixed;inset:0;z-index:20';
    document.body.append(host);
    window.confirmCount = 0;
    window.reviewBoard = await mountWhiteboard(host, { drafts: false, readOnly,
      appearance: 'light', assetBaseUrl: '/runtime/', confirmDiscard: () => { window.confirmCount++; return confirm; } });
    window.viewTrace.requests = []; window.viewTrace.replies = [];
  }, { readOnly, confirm });
  return page.locator('#review-board');
}

async function note(page, text) {
  await page.locator('#review-board .xterm-helper-textarea').focus();
  await page.keyboard.type('n');
  await page.keyboard.insertText(text);
  await page.keyboard.press('Escape');
  await expect(page.locator('#review-board .xterm-rows')).toContainText(text);
}

async function visibleFrame(page) {
  return page.evaluate(() => {
    const host = document.querySelector('#review-board');
    const cover = host.querySelector('.tiwb-frame-cover');
    const rows = (cover?.shadowRoot ?? host.querySelector('.tiwb-terminal')).querySelector('.xterm-rows');
    return { font: getComputedStyle(rows).fontSize,
      lines: [...rows.children].map(row => ({ text: row.textContent, rect: row.getBoundingClientRect().toJSON() })) };
  });
}

for (const fallback of [false, true]) {
  test(`CJK punctuation occupies exactly two cells across zoom levels (fallback=${fallback})`, async ({ page }) => {
    if (fallback) await page.route('**/*.woff2', route => route.abort('failed'));
    const host = await start(page);
    await host.locator('.xterm-helper-textarea').focus();
    await page.keyboard.type('l'.repeat(35) + 'j'.repeat(10));
    await note(page, 'A「中文」B『』C「」D');
    for (const action of [null, 'plus', 'minus', 'minus']) {
      if (action) {
        const before = await page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length);
        await host.locator(`.tiwb-toolbar [data-action="${action}"]`).click();
        await expect.poll(() => page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length)).toBeGreaterThan(before);
        await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
      }
      const geometry = await host.locator('.tiwb-terminal').evaluate(element => {
        const cell = element.querySelector('.xterm-screen').clientWidth / window.reviewBoard.getState().columns;
        const row = element.querySelectorAll('.xterm-rows > div');
        const body = [...row].find(r => r.textContent.includes('A「中文」'));
        const border = [...row].find(r => r.textContent.includes('╔'));
        const positions = target => {
          const result = [];
          const walk = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
          while (walk.nextNode()) {
            const text = walk.currentNode;
            for (let i = 0; i < text.length; i++) {
              const range = document.createRange(); range.setStart(text, i); range.setEnd(text, i + 1);
              const r = range.getBoundingClientRect(); result.push({ char: text.textContent[i], x: r.x, width: r.width });
            }
          }
          return result;
        };
        return { cell, text: positions(body), border: positions(border) };
      });
      for (const char of geometry.text.filter(c => '「」『』中文'.includes(c.char)))
        expect(Math.abs(char.width - geometry.cell * 2)).toBeLessThan(0.1);
      // DOM spans round fractional advances independently; allow a subpixel
      // difference across the row, but never the multi-cell punctuation drift.
      expect(Math.abs(geometry.text.findLast(c => c.char === '║').x - geometry.border.find(c => c.char === '╗').x)).toBeLessThan(1);
    }
  });
}

for (const deviceScaleFactor of [1, 2]) {
  test(`box glyphs use the bundled font and keep their cells across zoom (DPR=${deviceScaleFactor})`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor });
    const page = await context.newPage();
    try {
      const host = await start(page);
      await host.locator('.xterm-helper-textarea').focus();
      await page.keyboard.type('l'.repeat(48) + 'j'.repeat(12));
      await note(page, '「中文」é');
      await host.locator('.xterm-helper-textarea').focus();
      await page.keyboard.press('Enter'); await page.keyboard.press('End'); await page.keyboard.press('Enter');
      await page.keyboard.insertText('─│╭╯═║█'); await page.keyboard.press('Escape');
      await expect(host.locator('.xterm-rows')).toContainText('─│╭╯═║█');
      const cdp = await context.newCDPSession(page);
      await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
      for (const [action, count, zoom] of [[null, 0, '100%'], ['minus', 1, '87%'], ['minus', 5, '50%'], ['plus', 12, '200%']]) {
        if (action) {
          const before = await page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length);
          await host.locator(`.tiwb-toolbar [data-action="${action}"]`).evaluate((button, count) => {
            for (let i = 0; i < count; i++) button.click();
          }, count);
          await expect.poll(() => page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length)).toBeGreaterThan(before);
          await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
        }
        await expect(host.locator('.tiwb-zoom').first()).toHaveText(zoom);
        const samples = await host.locator('.tiwb-terminal').evaluate(element => {
          const cell = element.querySelector('.xterm-screen').clientWidth / window.reviewBoard.getState().columns;
          const spans = [...element.querySelectorAll('.xterm-rows span')].filter(span =>
            /[\u2500-\u259f]/u.test(span.textContent) && /^[\u2500-\u259f ]+$/u.test(span.textContent));
          return ['normal', 'bold'].map((weight, index) => {
            const span = spans.find(span => span.classList.contains('xterm-bold') === (weight === 'bold'));
            if (!span) throw new Error(`Missing ${weight} box glyphs`);
            span.dataset.fontSample = index;
            return { index, width: span.getBoundingClientRect().width, expected: span.textContent.length * cell };
          });
        });
        const { root } = await cdp.send('DOM.getDocument');
        for (const sample of samples) {
          expect(Math.abs(sample.width - sample.expected)).toBeLessThan(1);
          const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: `#review-board [data-font-sample="${sample.index}"]` });
          const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
          expect(fonts.length).toBeGreaterThan(0);
          for (const font of fonts) {
            expect(font.familyName).toBe('JetBrains Mono');
            expect(font.isCustomFont).toBe(true);
          }
        }
        await host.screenshot({ path: `test-results/box-font-dpr${deviceScaleFactor}-${zoom.slice(0, -1)}.png` });
      }
    } finally { await context.close(); }
  });
}

test('zoom preserves the painted frame until one combined viewport response is rendered', async ({ page }) => {
  const host = await start(page);
  await note(page, 'Stable 「frame」');
  const bytes = await page.evaluate(async () => [...(await window.reviewBoard.export()).bytes]);
  const before = await visibleFrame(page);
  await page.evaluate(() => { window.viewTrace.hold = ['viewport']; });
  await host.locator('.tiwb-toolbar [data-action="minus"]').click();
  await expect.poll(() => page.evaluate(() => window.viewTrace.held.length)).toBe(1);
  await expect(host.locator('.tiwb-terminal')).toHaveCSS('opacity', '0');
  expect(await visibleFrame(page)).toEqual(before);
  // Copied renderer CSS must not leak back into the live renderer.
  await expect(host.locator('.tiwb-terminal .xterm-rows')).toHaveCSS('font-size', '13.9px');
  await page.screenshot({ path: 'test-results/zoom-held.png' });
  const requests = await page.evaluate(() => window.viewTrace.requests.filter(r => ['resize', 'pan', 'viewport'].includes(r.type)));
  expect(requests.map(r => r.type)).toEqual(['viewport']);
  await page.evaluate(() => window.releaseViews());
  await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
  const after = await visibleFrame(page);
  expect(after.font).toBe('13.9px');
  expect(after.lines.at(-1).text).toContain('SELECT');
  expect(await page.evaluate(async () => [...(await window.reviewBoard.export()).bytes])).toEqual(bytes);
  await page.screenshot({ path: 'test-results/zoom-settled.png' });
});

test('bursts coalesce and a slow Worker has at most one viewport request in flight', async ({ page }) => {
  const host = await start(page, { readOnly: true });
  await page.evaluate(() => { window.viewTrace.hold = ['viewport']; });
  await host.locator('.tiwb-toolbar [data-action="minus"]').click();
  await expect.poll(() => page.evaluate(() => window.viewTrace.held.length)).toBe(1);
  await page.evaluate(() => {
    const root = document.querySelector('#review-board');
    for (let i = 0; i < 20; i++) root.querySelector('.tiwb-toolbar [data-action="minus"]').click();
    for (let i = 0; i < 10; i++) root.querySelector('.tiwb-viewport').dispatchEvent(new WheelEvent('wheel', { deltaX: 16, bubbles: true, cancelable: true }));
  });
  expect(await page.evaluate(() => window.viewTrace.requests.filter(r => r.type === 'viewport').length)).toBe(1);
  await page.evaluate(() => window.releaseViews());
  await expect(host.locator('.tiwb-zoom').first()).toHaveText('50%');
  await expect.poll(() => page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length)).toBe(2);
  await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
  const result = await page.evaluate(() => ({ maximum: window.viewTrace.maximumPending,
    requests: window.viewTrace.requests.filter(r => r.type === 'viewport'), state: window.reviewBoard.getState() }));
  expect(result.maximum).toBe(1);
  expect(result.requests).toHaveLength(2);
  expect(result.state.dirty).toBe(false);
  expect(result.state.revision).toBe('0');
  // Two 8px cells for each wheel event, plus the independently anchored zoom.
  expect(result.requests[1].payload.dx).toBe(20 + Math.round(640 / 8 - 640 / 5));
});

test('repeated anchored zoom round trips preserve position and same-scale gestures retain translation', async ({ page }) => {
  const host = await start(page, { readOnly: true });
  for (let i = 0; i < 4; i++) {
    for (const action of ['plus', 'minus']) {
      const count = await page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length);
      await host.locator(`.tiwb-toolbar [data-action="${action}"]`).click();
      await expect.poll(() => page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length)).toBe(count + 1);
      await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
    }
  }
  expect(await page.evaluate(() => window.reviewBoard.getState())).toMatchObject({ x: '0', y: '0', dirty: false });
  await page.evaluate(() => {
    window.viewTrace.requests = []; window.viewTrace.replies = [];
    const viewport = document.querySelector('#review-board .tiwb-viewport');
    // Two opposite scale changes with different anchors compose to a pan.
    for (const [clientX, deltaY] of [[300, -40], [700, 40]])
      viewport.dispatchEvent(new WheelEvent('wheel', { ctrlKey: true, clientX, clientY: 200, deltaY, bubbles: true, cancelable: true }));
  });
  await expect.poll(() => page.evaluate(() => window.viewTrace.replies.filter(r => r.type === 'viewport').length)).toBe(1);
  await expect(host.locator('.tiwb-zoom').first()).toHaveText('100%');
  const result = await page.evaluate(() => ({ state: window.reviewBoard.getState(), requests: window.viewTrace.requests }));
  expect(result.state.x).not.toBe('0');
  expect(result.state.y).toBe('0');
  expect(result.requests.filter(r => r.type === 'viewport')).toHaveLength(1);
});

for (const operation of ['new', 'open']) {
  test(`${operation} checks Worker dirty state even before the latest input reply arrives`, async ({ page }) => {
    await start(page);
    const engine = new Engine(await createModule());
    engine.create(80, 24);
    const empty = [...engine.export()]; engine.destroy();
    const result = await page.evaluate(async ({ operation, empty }) => {
      window.viewTrace.hold = ['input'];
      const textarea = document.querySelector('#review-board .xterm-helper-textarea');
      textarea.focus();
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', code: 'KeyN', keyCode: 78, which: 78, bubbles: true, cancelable: true }));
      const before = window.reviewBoard.getState();
      const accepted = operation === 'new' ? await window.reviewBoard.newDocument()
        : await window.reviewBoard.open(new Uint8Array(empty));
      window.releaseViews();
      return { before, accepted, confirms: window.confirmCount, after: window.reviewBoard.getState(),
        sync: window.viewTrace.replies.filter(r => r.type === 'sync') };
    }, { operation, empty });
    expect(result.before.dirty).toBe(false);
    expect(result.accepted).toBe(false);
    expect(result.confirms).toBe(1);
    expect(result.after.dirty).toBe(true);
    expect(result.after.cards).toBe(1);
    expect(result.after.generation).toBe(0);
    expect(result.sync).toHaveLength(1);
    expect(result.sync[0].bytes).toBeUndefined();
  });
}

test('document replacement drains an accepted zoom and cancels queued gestures', async ({ page }) => {
  const host = await start(page, { confirm: true });
  await note(page, 'Old document');
  await page.evaluate(() => { window.viewTrace.hold = ['viewport']; });
  await host.locator('.tiwb-toolbar [data-action="minus"]').click();
  await expect.poll(() => page.evaluate(() => window.viewTrace.held.length)).toBe(1);
  await page.evaluate(() => {
    document.querySelector('#review-board .tiwb-toolbar [data-action="minus"]').click();
    window.replacement = window.reviewBoard.newDocument();
  });
  expect(await page.evaluate(() => window.viewTrace.requests.some(r => r.type === 'new'))).toBe(false);
  await page.evaluate(async () => { window.releaseViews(); await window.replacement; });
  await expect(host.locator('.tiwb-frame-cover')).toHaveCount(0);
  const state = await page.evaluate(() => window.reviewBoard.getState());
  expect(state).toMatchObject({ generation: 1, cards: 0, dirty: false, x: '0', y: '0' });
  expect(await page.evaluate(() => window.viewTrace.requests.filter(r => r.type === 'viewport').length)).toBe(1);
  await expect(host.locator('.tiwb-zoom').first()).toHaveText('87%');
});

test('disposing while a zoom reply is delayed releases the cover and its pending waits', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const host = await start(page);
  await page.evaluate(() => { window.viewTrace.hold = ['viewport']; });
  await host.locator('.tiwb-toolbar [data-action="plus"]').click();
  await expect.poll(() => page.evaluate(() => window.viewTrace.held.length)).toBe(1);
  await page.evaluate(() => { window.reviewBoard.dispose(); window.releaseViews(); });
  await expect(host.locator('.tiwb-app')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Worker barriers preserve incomplete paste and reject stale viewport generations', async ({ page }) => {
  await start(page);
  const result = await page.evaluate(async () => {
    const worker = new Worker('/runtime/whiteboard.worker.js', { type: 'module' });
    let next = 0;
    const pending = new Map();
    worker.onmessage = ({ data }) => {
      const job = pending.get(data.id);
      if (job) { pending.delete(data.id); data.error ? job.reject(new Error(data.error)) : job.resolve(data); }
    };
    const request = (type, payload = {}) => new Promise((resolve, reject) => {
      const id = ++next; pending.set(id, { resolve, reject }); worker.postMessage({ id, type, payload });
    });
    try {
      const init = await request('init', { columns: 80, rows: 24 });
      await request('input', { text: 'nKeep', epoch: init.epoch });
      await request('input', { text: '\x1b[200~ incomplete', epoch: init.epoch });
      let error;
      try { await request('sync'); } catch (e) { error = e.message; }
      await request('input', { text: ' paste\x1b[201~', epoch: init.epoch });
      const synced = await request('sync');
      const original = await request('export');
      const moved = await request('viewport', { columns: 90, rows: 30, dx: 5, dy: -3, generation: 0 });
      const unchanged = await request('viewport', { columns: 90, rows: 30, dx: 0, dy: 0, generation: 0 });
      const afterMove = await request('export');
      const fresh = await request('new', { columns: 80, rows: 24 });
      const stale = await request('viewport', { columns: 90, rows: 30, dx: 10, dy: 10, generation: 0 });
      return { error, syncFrame: synced.frame, movedFrame: moved.frame.byteLength, moved: moved.state,
        noChangeFrame: unchanged.frame, staleFrame: stale.frame, fresh: fresh.state, stale: stale.state,
        text: new TextDecoder().decode(original.bytes), same: [...new Uint8Array(original.bytes)].join() === [...new Uint8Array(afterMove.bytes)].join() };
    } finally { worker.terminate(); }
  });
  expect(result.error).toContain('輸入尚未完成');
  expect(result.text).toContain('Keep incomplete paste');
  expect(result.syncFrame).toBeUndefined();
  expect(result.movedFrame).toBeGreaterThan(0);
  expect(result.moved).toMatchObject({ columns: 90, rows: 30, x: '5', y: '-3' });
  expect(result.noChangeFrame).toBeUndefined();
  expect(result.same).toBe(true);
  expect(result.staleFrame).toBeUndefined();
  expect(result.stale).toEqual(result.fresh);
});
