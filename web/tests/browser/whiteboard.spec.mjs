import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function start(page, query = '?mode=edit') {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/${query}`);
  await expect(page.locator('.tiwb-message')).not.toHaveText('正在載入白板…');
  await expect(page.locator('#startup-error')).toBeHidden();
  await expect(page.locator('.tiwb-app')).toBeVisible();
  return errors;
}
async function typeNote(page, text) {
  await expect(page.locator('.tiwb-app')).toHaveAttribute('aria-busy', 'false');
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.type('n');
  await page.keyboard.insertText(text);
  await expect(page.locator('.tiwb-save-state')).toHaveText('有未儲存修改');
}
async function fileAction(page, action) {
  if (await page.locator('.tiwb-file-menu').isHidden())
    await page.locator('.tiwb-toolbar [data-panel="file"]:visible').click();
  await page.locator(`.tiwb-file-menu [data-action="${action}"]`).click();
}
async function download(page) {
  const pending = page.waitForEvent('download');
  await fileAction(page, 'export');
  const file = await pending;
  return { name: file.suggestedFilename(), bytes: await readFile(await file.path()) };
}

test('desktop edits, exports, restores drafts and rejects corrupt imports', async ({ page }) => {
  const errors = await start(page);
  await typeNote(page, 'Hello 中文');
  await fileAction(page, 'save');
  await expect(page.locator('.tiwb-message')).toHaveText('草稿已儲存在這個瀏覽器');
  const original = await download(page);
  expect(original.bytes.subarray(0, 4).toString()).toBe('TIWB');
  await page.reload();
  await expect(page.locator('.tiwb-message')).toHaveText('已恢復本機草稿');
  expect((await download(page)).bytes).toEqual(original.bytes);
  await page.locator('.tiwb-file').setInputFiles({ name: 'broken.tiwb', mimeType: 'application/octet-stream', buffer: Buffer.from('broken') });
  await expect(page.locator('.tiwb-message')).toHaveAttribute('data-error', 'true');
  expect((await download(page)).bytes).toEqual(original.bytes);
  expect(errors).toEqual([]);
  await page.screenshot({ path: 'test-results/desktop.png' });
});

test('read-only blocks keys, paste and card dragging while permitting viewport gestures', async ({ page }) => {
  const errors = await start(page);
  await typeNote(page, 'Read only');
  const original = await download(page);
  await page.getByRole('button', { name: '編輯中', exact: true }).click();
  await expect(page.getByRole('button', { name: '唯讀中', exact: true })).toBeVisible();
  const rect = await page.locator('.tiwb-viewport').boundingBox();
  await page.mouse.move(rect.x + 100, rect.y + 90); await page.mouse.down();
  await page.mouse.move(rect.x + 240, rect.y + 170, { steps: 8 }); await page.mouse.up();
  await page.keyboard.type('nnnxxx');
  await page.keyboard.insertText('不得寫入');
  await page.getByRole('button', { name: '放大', exact: true }).click();
  await expect(page.locator('.tiwb-zoom').first()).not.toHaveText('100%');
  expect((await download(page)).bytes).toEqual(original.bytes);
  await page.getByRole('button', { name: '唯讀中', exact: true }).click();
  expect((await download(page)).bytes).toEqual(original.bytes);
  expect(errors).toEqual([]);
});

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
  test('touch layout defaults to read-only and supports rotation and pinch', async ({ page }) => {
    const errors = await start(page, '');
    await expect(page.getByRole('button', { name: '唯讀中', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '唯讀中', exact: true }).click();
    await typeNote(page, '手機白板 · Touch');
    await page.getByRole('button', { name: '編輯中', exact: true }).click();
    const before = await download(page);
    const viewport = page.locator('.tiwb-viewport');
    const box = await viewport.boundingBox();
    const touch = await page.context().newCDPSession(page);
    const first = { id: 10, x: box.x + 80, y: box.y + 100 };
    await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [first] });
    await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [first, { id: 11, x: box.x + 180, y: box.y + 100 }] });
    await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [first, { id: 11, x: box.x + 230, y: box.y + 100 }] });
    await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect(page.locator('.tiwb-zoom').first()).not.toHaveText('100%');
    await page.getByRole('button', { name: '白板選單', exact: true }).click();
    await expect(page.locator('.tiwb-file-menu')).toBeVisible();
    await page.touchscreen.tap(box.x + 20, box.y + 500);
    await expect(page.locator('.tiwb-file-menu')).toBeHidden();
    await page.screenshot({ path: 'test-results/mobile-portrait.png' });
    await page.setViewportSize({ width: 844, height: 390 });
    await expect(page.locator('.tiwb-app')).toBeVisible();
    expect((await download(page)).bytes).toEqual(before.bytes);
    expect(errors).toEqual([]);
    await page.screenshot({ path: 'test-results/mobile-landscape.png' });
  });
});

test('compact containers keep one toolbar row and all controls reachable without page scrolling', async ({ page }) => {
  await start(page, '?mode=read');
  for (const size of [{ width: 320, height: 568 }, { width: 768, height: 1024 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(size);
    await expect(page.locator('.tiwb-toolbar')).toHaveCSS('height', '48px');
    const geometry = await page.evaluate(() => {
      const app = document.querySelector('.tiwb-app');
      const viewport = document.querySelector('.tiwb-viewport');
      const term = document.querySelector('.xterm-viewport');
      return { width: app.clientWidth, height: app.clientHeight, boardHeight: viewport.clientHeight,
        scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight,
        terminalBackground: getComputedStyle(term).backgroundColor };
    });
    expect(geometry.width).toBe(size.width);
    expect(geometry.height).toBe(size.height);
    expect(geometry.boardHeight).toBe(size.height - 48);
    expect(geometry.scrollWidth).toBe(size.width);
    expect(geometry.scrollHeight).toBe(size.height);
    await page.locator('.tiwb-toolbar [data-panel="file"]:visible').click();
    await expect(page.getByRole('button', { name: '匯出 .tiwb', exact: true })).toBeInViewport();
    await page.keyboard.press('Escape');
  }
});

test('two tabs cannot silently overwrite the same local draft', async ({ page, context }) => {
  await start(page);
  const other = await context.newPage();
  await start(other);
  await typeNote(page, 'First tab');
  await fileAction(page, 'save');
  await expect(page.locator('.tiwb-message')).toHaveText('草稿已儲存在這個瀏覽器');
  await typeNote(other, 'Second tab');
  await fileAction(other, 'save');
  await expect(other.locator('.tiwb-message')).toContainText('另一個頁面已更新草稿');
  const original = await download(page);
  const conflicting = await download(other);
  expect(conflicting.bytes).not.toEqual(original.bytes);
  await page.reload();
  await expect(page.locator('.tiwb-message')).toHaveText('已恢復本機草稿');
  expect((await download(page)).bytes).toEqual(original.bytes);
});

test('Worker rejects obsolete input and save acknowledgements across document changes', async ({ page }) => {
  await start(page);
  const result = await page.evaluate(async () => {
    const worker = new Worker('/runtime/whiteboard.worker.js', { type: 'module' });
    let next = 1;
    const pending = new Map();
    worker.onmessage = ({ data }) => {
      const callback = pending.get(data.id);
      if (!callback) return;
      pending.delete(data.id);
      if (data.error) callback.reject(new Error(data.error)); else callback.resolve(data);
    };
    const request = (type, payload) => new Promise((resolve, reject) => {
      const id = next++; pending.set(id, { resolve, reject }); worker.postMessage({ id, type, payload });
    });
    try {
      const init = await request('init', { columns: 80, rows: 24, readOnly: false });
      await request('input', { text: 'nOld', epoch: init.epoch });
      const old = await request('export');
      const fresh = await request('new', { columns: 80, rows: 24 });
      await request('input', { text: 'nNew', epoch: fresh.epoch });
      const afterStaleSave = await request('saved', { generation: old.state.generation, revision: old.state.revision });
      const beforeReadOnly = await request('export');
      const mode = await request('mode', { readOnly: true });
      await request('input', { text: 'nnxxx\x1a', epoch: mode.epoch });
      await request('pan', { dx: 15, dy: 6 });
      const afterReadOnly = await request('export');
      const edit = await request('mode', { readOnly: false });
      const staleInput = await request('input', { text: 'nWrong', epoch: mode.epoch });
      return { dirty: afterStaleSave.state.dirty, revision: afterStaleSave.state.revision,
        oldRevision: old.state.revision, before: [...new Uint8Array(beforeReadOnly.bytes)],
        after: [...new Uint8Array(afterReadOnly.bytes)], pan: afterReadOnly.state.x,
        unchanged: staleInput.state.revision === edit.state.revision };
    } finally { worker.terminate(); }
  });
  expect(result.revision).toBe(result.oldRevision);
  expect(result.dirty).toBe(true);
  expect(result.after).toEqual(result.before);
  expect(result.pan).toBe('15');
  expect(result.unchanged).toBe(true);
});

test('the embedding API mounts independently and releases its container for reuse', async ({ page }) => {
  await start(page);
  await typeNote(page, 'Embedding API');
  const original = await download(page);
  const result = await page.evaluate(async bytes => {
    const { mountWhiteboard } = await import('/whiteboard.js');
    const container = document.createElement('div');
    container.style.height = '480px';
    document.body.append(container);
    const board = await mountWhiteboard(container, { document: new Uint8Array(bytes),
      name: 'embedded.tiwb', drafts: false, readOnly: true, assetBaseUrl: '/runtime/' });
    const state = board.getState();
    const exported = await board.export();
    board.dispose();
    const emptyAfterDispose = container.children.length === 0;
    const replacement = await mountWhiteboard(container, { drafts: false });
    const emptyDocument = replacement.getState().cards === 0;
    replacement.dispose(); container.remove();
    return { state, bytes: [...exported.bytes], emptyAfterDispose, emptyDocument };
  }, [...original.bytes]);
  expect(result.state.name).toBe('embedded.tiwb');
  expect(result.state.cards).toBe(1);
  expect(result.state.readOnly).toBe(true);
  expect(Buffer.from(result.bytes)).toEqual(original.bytes);
  expect(result.emptyAfterDispose).toBe(true);
  expect(result.emptyDocument).toBe(true);
});

test('appearance follows the system, persists the choice and preserves document bytes', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  const errors = await start(page);
  const app = page.locator('.tiwb-app');
  await expect(app).toHaveAttribute('data-appearance', 'light');
  await expect(app).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  await expect(page.locator('[data-action="system"]')).toHaveCount(0);
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(app).toHaveAttribute('data-appearance', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(app).toHaveAttribute('data-appearance', 'light');
  await typeNote(page, '日間與夜間 · Theme');
  const original = await download(page);
  await page.getByRole('button', { name: '切換至夜間模式', exact: true }).click();
  await expect(app).toHaveAttribute('data-appearance', 'dark');
  await expect(app).toHaveCSS('background-color', 'rgb(30, 30, 46)');
  expect((await download(page)).bytes).toEqual(original.bytes);
  await page.screenshot({ path: 'test-results/theme-dark.png' });
  await fileAction(page, 'save');
  await expect(page.locator('.tiwb-message')).toHaveText('草稿已儲存在這個瀏覽器');
  await page.reload();
  await expect(app).toHaveAttribute('data-appearance', 'dark');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(app).toHaveAttribute('data-appearance', 'dark');
  await page.getByRole('button', { name: '切換至日間模式', exact: true }).click();
  await expect(app).toHaveAttribute('data-appearance', 'light');
  await page.screenshot({ path: 'test-results/theme-light.png' });
  expect(errors).toEqual([]);
});

test('menus overlay the viewport, Escape restores focus, and fullscreen retains the document', async ({ page }) => {
  await start(page);
  const viewport = page.locator('.tiwb-viewport');
  const initial = await viewport.boundingBox();
  expect(initial.height).toBeGreaterThan(740);
  await page.getByRole('button', { name: '操作說明', exact: true }).click();
  await expect(page.locator('.tiwb-help')).toBeVisible();
  expect(await viewport.boundingBox()).toEqual(initial);
  await page.keyboard.press('Escape');
  await expect(page.locator('.tiwb-help')).toBeHidden();
  await expect(page.getByRole('button', { name: '操作說明', exact: true })).toBeFocused();
  await typeNote(page, 'Fullscreen');
  const before = await download(page);
  await page.getByRole('button', { name: '操作說明', exact: true }).click();
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.type('nnxxx');
  await page.keyboard.insertText('blocked paste');
  await page.keyboard.press('Escape');
  expect((await download(page)).bytes).toEqual(before.bytes);
  await page.getByRole('button', { name: '進入全螢幕', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.className)).toBe('tiwb-app');
  expect((await download(page)).bytes).toEqual(before.bytes);
  await page.getByRole('button', { name: '離開全螢幕', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  expect((await download(page)).bytes).toEqual(before.bytes);
});

test('embedded themes stay isolated and changing appearance preserves history and revision', async ({ page }) => {
  await start(page);
  const result = await page.evaluate(async () => {
    const { mountWhiteboard } = await import('/whiteboard.js');
    const originalBody = getComputedStyle(document.body).backgroundColor;
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;inset:80px 20px 20px;z-index:10';
    document.body.append(host);
    const board = await mountWhiteboard(host, { appearance: 'light', drafts: false });
    window.themeBoard = board;
    window.themeHost = host;
    return { originalBody, body: getComputedStyle(document.body).backgroundColor };
  });
  expect(result.body).toBe(result.originalBody);
  await page.locator('.tiwb-app').last().locator('.xterm-helper-textarea').focus();
  await page.keyboard.type('nTheme transaction');
  await expect.poll(() => page.evaluate(() => window.themeBoard.getState().cards)).toBe(1);
  const states = await page.evaluate(async () => {
    const snapshot = await window.themeBoard.export();
    const before = window.themeBoard.getState();
    window.themeBoard.setAppearance('dark');
    const after = window.themeBoard.getState();
    const next = await window.themeBoard.export();
    const theme = window.themeBoard.getAppearance();
    return { before, after, theme, same: [...snapshot.bytes].join() === [...next.bytes].join() };
  });
  expect(states.before.dirty).toBe(true);
  expect(states.after).toEqual(states.before);
  expect(states.same).toBe(true);
  expect(states.theme).toEqual({ appearance: 'dark', resolvedAppearance: 'dark' });
  await page.locator('.tiwb-app').last().locator('.xterm-helper-textarea').focus();
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+z');
  await expect.poll(() => page.evaluate(() => window.themeBoard.getState().revision)).not.toBe(states.after.revision);
  await page.evaluate(() => { window.themeBoard.dispose(); window.themeHost.remove(); });
});

test('idle and hidden pages never save; manual saving and menus preserve undo and redo', async ({ page }) => {
  await start(page);
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.press('n');
  const emptyNote = (await download(page)).bytes;
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.insertText('Manual draft');
  const edited = (await download(page)).bytes;
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(1200);
  const stored = await page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open('whiteboard-tui', 1);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const tx = db.transaction('drafts');
      const read = tx.objectStore('drafts').get('default');
      tx.oncomplete = () => { db.close(); resolve(Boolean(read.result)); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    };
  }));
  expect(stored).toBe(false);
  await expect(page.locator('.tiwb-save-state')).toHaveText('有未儲存修改');
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.press('Control+s');
  await expect(page.locator('.tiwb-save-state')).toHaveText('草稿已儲存');
  await page.getByRole('button', { name: '操作說明', exact: true }).click();
  await page.keyboard.press('Escape');
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+z');
  expect((await download(page)).bytes).toEqual(emptyNote);
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.press('Control+r');
  expect((await download(page)).bytes).toEqual(edited);
});

test('Worker renders complete input once, applies Escape immediately and preserves fragmented sequences', async ({ page }) => {
  await start(page);
  const result = await page.evaluate(async () => {
    const worker = new Worker('/runtime/whiteboard.worker.js', { type: 'module' });
    const pending = new Map();
    let id = 0, events = 0;
    worker.onmessage = ({ data }) => {
      if (data.event === 'view') events++;
      const job = pending.get(data.id);
      if (job) { pending.delete(data.id); data.error ? job.reject(new Error(data.error)) : job.resolve(data); }
    };
    const request = (type, payload = {}) => new Promise((resolve, reject) => {
      const next = ++id; pending.set(next, { resolve, reject }); worker.postMessage({ id: next, type, payload });
    });
    try {
      const init = await request('init', { columns: 80, rows: 24, readOnly: false });
      const input = text => request('input', { text, epoch: init.epoch });
      await input('nText');
      await new Promise(resolve => setTimeout(resolve, 80));
      const idleEvents = events;
      const escape = await input('\x1b');
      await input('\x1b');
      await input('\x1a');
      const undone = await request('export');
      await input('\x12');
      await input('\r');
      await input('\x1b[200~partial ');
      await new Promise(resolve => setTimeout(resolve, 80));
      await input('中文\x1b[201~');
      const pasted = await request('export');
      await input('\x1b'); await input('\x1b');
      const beforeArrow = await request('export');
      await input('\x1b['); await input('C');
      const afterArrow = await request('export');
      return { idleEvents, escapeBytes: escape.frame.byteLength, exportFrame: undone.frame,
        undoneCards: undone.state.cards, pasted: new TextDecoder().decode(pasted.bytes),
        arrowPreserves: [...new Uint8Array(beforeArrow.bytes)].join() === [...new Uint8Array(afterArrow.bytes)].join() };
    } finally { worker.terminate(); }
  });
  expect(result.idleEvents).toBe(0);
  expect(result.escapeBytes).toBeGreaterThan(0);
  expect(result.exportFrame).toBeUndefined();
  expect(result.undoneCards).toBe(1);
  expect(result.pasted).toContain('partial 中文');
  expect(result.arrowPreserves).toBe(true);
});
