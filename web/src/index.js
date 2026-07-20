import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import 'whiteboard:webtui';
import './style.css';
import { attachAppearance, validateAppearance } from './appearance.js';
import { createShell, attachPanels } from './shell.js';
import { WorkerClient } from './client.js';
import { DraftStore } from './drafts.js';
import { attachViewport } from './viewport.js';
import { attachView } from './view.js';
import { attachMinimap } from './minimap.js';
import { unicodeProvider } from 'whiteboard:unicode';
import { MAX_FILE_BYTES } from './engine.js';

const initialized = new WeakSet();
const terminalSetup = '\x1b[?1049h\x1b[?25l\x1b[?2004h\x1b[?1002h\x1b[?1006h';
/** Mount a self-contained whiteboard. Import whiteboard-tui-web/style.css once. */
export async function mountWhiteboard(container, options = {}) {
  if (!(container instanceof HTMLElement)) throw new TypeError('需要可見的白板容器');
  if (initialized.has(container)) throw new Error('此容器已有白板');
  const assetBase = new URL(options.assetBaseUrl ?? './runtime/', options.assetBaseUrl ? document.baseURI : import.meta.url);
  if (!assetBase.pathname.endsWith('/') || assetBase.origin !== location.origin)
    throw new Error('assetBaseUrl 必須是同來源且以 / 結尾的資產目錄');
  if (options.document !== undefined && (!(options.document instanceof Uint8Array) || options.document.byteLength > MAX_FILE_BYTES))
    throw new Error('請提供不超過 32 MiB 的 .tiwb 原稿');
  // Own an immutable source snapshot, independent of the caller and local draft.
  const original = options.document?.slice();
  const originalName = options.name || 'whiteboard.tiwb';
  validateAppearance(options.appearance ?? 'system');
  const root = createShell(container, options);
  initialized.add(container);
  const $ = selector => root.querySelector(selector);
  const viewport = $('.tiwb-viewport');
  const terminalElement = $('.tiwb-terminal');
  const modeButton = $('[data-action="mode"]');
  const resetButton = $('[data-action="reset"]');
  resetButton.hidden = !original;
  $('.tiwb-reset-help').hidden = !original;
  const fileInput = $('.tiwb-file');
  const nameLabel = $('.tiwb-name');
  const saveLabel = $('.tiwb-save-state');
  const message = $('.tiwb-message');
  const notice = $('.tiwb-notice');
  const gestureLayer = $('.tiwb-gesture');
  const zoomLabels = root.querySelectorAll('.tiwb-zoom');
  const abort = new AbortController();
  let disposed = false;
  let ready = false;
  let loading = true;
  let busy = false;
  let panelOpen = false;
  let readOnly = options.readOnly ?? matchMedia('(pointer: coarse)').matches;
  let name = options.name || 'whiteboard.tiwb';
  let state;
  let minimap;
  let savedRevision;
  let saveQueue = Promise.resolve();
  let draftsReady = false;
  const drafts = new DraftStore(options.draftKey ?? 'default');
  const report = (text, isError = false) => {
    if (disposed) return;
    message.textContent = text;
    message.dataset.error = String(isError);
    notice.dataset.visible = String(isError);
  };
  const failure = error => {
    report(error.message || String(error), true);
    try { options.onError?.(error); } catch (callbackError) { console.error(callbackError); }
  };
  function notifyChange() {
    try { options.onChange?.({ ...state, name }); } catch (error) { failure(error); }
  }
  function documentUI() {
    if (nameLabel.textContent !== name) { nameLabel.textContent = name; nameLabel.title = name; }
    const label = state.dirty ? '有未儲存修改'
      : savedRevision === `${state.generation}:${state.revision}` ? '草稿已儲存' : '文件未修改';
    if (saveLabel.textContent !== label) saveLabel.textContent = label;
    if (saveLabel.dataset.dirty !== String(state.dirty)) saveLabel.dataset.dirty = String(state.dirty);
  }
  const terminal = new Terminal({ fontSize: 16, fontFamily: getComputedStyle(root).getPropertyValue('--font-family').trim(),
    lineHeight: 1, scrollback: 0, cursorBlink: false, allowProposedApi: true,
    disableStdin: readOnly });
  const fit = new FitAddon();
  terminal.loadAddon(fit);
  terminal.unicode.register(unicodeProvider);
  terminal.unicode.activeVersion = unicodeProvider.version;
  const appearance = attachAppearance(root, terminal, { appearance: options.appearance,
    theme: options.theme, signal: abort.signal, onChange: value => {
      minimap?.redraw();
      try { options.onAppearanceChange?.(value); } catch (error) { failure(error); }
    } });
  const update = data => {
    if (disposed) return;
    // Overview queries have no ANSI delta. Ignore an obsolete read-only result
    // if the document has already advanced while that query was outstanding.
    if (data.overviewBytes && state && (data.state.generation < state.generation ||
        (data.state.generation === state.generation && BigInt(data.state.revision) < BigInt(state.revision)))) return;
    const changed = !state || Object.keys(data.state).some(key => state[key] !== data.state[key]);
    state = data.state;
    if (data.frame?.byteLength) view.write(data.frame);
    documentUI();
    if (changed) notifyChange();
    if (state.saveRequested) void saveDraft().catch(failure);
    minimap?.update(data);
  };
  const client = new WorkerClient(new URL('whiteboard.worker.js', assetBase), update, failure);

  const dimensions = () => {
    const proposed = fit.proposeDimensions();
    if (!proposed || viewport.clientWidth < 1 || viewport.clientHeight < 1) return null;
    const columns = Math.max(2, Math.min(500, proposed.cols));
    const rows = Math.max(2, Math.min(250, proposed.rows, Math.floor(50000 / columns)));
    return { columns, rows };
  };
  const view = attachView({ terminal, element: terminalElement, viewport, dimensions, client,
    enabled: () => ready && !loading && !busy && !disposed,
    state: () => state, labels: zoomLabels, failure });
  minimap = attachMinimap(root, { client, view, state: () => state, failure,
    enabled: () => ready && !loading && !busy && !disposed });
  const scheduleFit = () => view.fit();
  const observer = new ResizeObserver(scheduleFit);
  observer.observe(viewport);
  const gestures = attachViewport(viewport, { readOnly: () => readOnly,
    cellSize: view.cellSize, pan: view.pan, zoom: view.zoom, getZoom: view.getZoom });
  const modeUI = () => {
    root.dataset.readonly = String(readOnly);
    modeButton.setAttribute('aria-pressed', String(readOnly));
    modeButton.textContent = readOnly ? '唯讀中' : '編輯中';
    terminal.options.disableStdin = readOnly || loading || busy;
    gestureLayer.hidden = !readOnly;
    if (readOnly) terminal.blur();
    minimap.refresh();
  };
  modeUI();
  const panels = attachPanels(root, abort.signal, open => {
    panelOpen = open;
    gestures.reset();
    // Key and onData guards block panel input without invalidating xterm's renderer.
    if (open) terminal.blur();
  });
  const fullscreenUI = () => {
    root.querySelectorAll('[data-action="fullscreen"]').forEach(button => {
      button.disabled = !document.fullscreenEnabled;
      const label = document.fullscreenElement === root ? '離開全螢幕' : '進入全螢幕';
      button.setAttribute('aria-label', label); button.title = label;
      button.setAttribute('aria-pressed', String(document.fullscreenElement === root));
    });
    scheduleFit();
  };
  document.addEventListener('fullscreenchange', fullscreenUI, { signal: abort.signal });
  fullscreenUI();
  const toggleFullscreen = async () => {
    if (document.fullscreenElement === root) await document.exitFullscreen();
    else await root.requestFullscreen();
  };

  const ensureReady = () => { if (disposed || !ready) throw new Error('白板尚未就緒或已關閉'); };
  const transition = async action => {
    ensureReady();
    if (busy) throw new Error('正在切換文件，請稍候');
    busy = true; root.setAttribute('aria-busy', 'true'); modeUI();
    resetButton.disabled = true;
    gestures.reset();
    try { await view.settle(); ensureReady(); return await action(); }
    finally {
      busy = false;
      if (!disposed) { resetButton.disabled = loading; root.setAttribute('aria-busy', String(loading)); modeUI(); scheduleFit(); }
    }
  };
  const confirmReplace = async () => {
    // Startup cannot accept input. Otherwise query behind all accepted input,
    // since the last state received on the main thread may still be clean.
    const current = loading ? state : (await client.request('sync')).state;
    return !current.dirty || await (options.confirmDiscard ?? (() =>
      window.confirm('目前有未儲存修改。要捨棄修改並開啟另一份文件嗎？')))();
  };

  async function openDocument(bytes, filename = 'whiteboard.tiwb') {
    if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_FILE_BYTES)
      throw new Error('請選擇不超過 32 MiB 的 .tiwb 檔案');
    return transition(async () => {
      if (!await confirmReplace()) return false;
      const copy = bytes.slice().buffer;
      await client.request('open', { bytes: copy }, [copy]);
      name = filename;
      documentUI();
      notifyChange();
      report('已匯入文件');
      return true;
    });
  }

  async function snapshotDocument() {
    ensureReady();
    const filename = name;
    const snapshot = await client.request('export');
    return { bytes: new Uint8Array(snapshot.bytes), name: filename,
      generation: snapshot.state.generation, revision: snapshot.state.revision };
  }

  async function exportDocument() {
    if (busy) throw new Error('正在切換文件，請稍候');
    return snapshotDocument();
  }

  function saveDraft() {
    if (busy) return Promise.reject(new Error('正在切換文件，請稍候'));
    const job = saveQueue.then(async () => {
      ensureReady();
      if (!draftsReady) throw new Error('此瀏覽器無法儲存本機草稿，請匯出 .tiwb');
      const snapshot = await snapshotDocument();
      await drafts.write({ bytes: snapshot.bytes, name: snapshot.name });
      savedRevision = `${snapshot.generation}:${snapshot.revision}`;
      await client.request('saved', { generation: snapshot.generation, revision: snapshot.revision });
      if (state.generation === snapshot.generation && state.revision === snapshot.revision)
        report('草稿已儲存在這個瀏覽器');
    });
    saveQueue = job.catch(() => {});
    return job;
  }

  async function resetToOriginal() {
    if (!original) throw new Error('此白板沒有可恢復的原稿');
    return transition(async () => {
      // Drain accepted saves while input and new saves are blocked. Nothing from
      // the previous document may be written after the draft has been cleared.
      await saveQueue;
      const copy = original.slice().buffer;
      await client.request('open', { bytes: copy }, [copy]);
      name = originalName;
      savedRevision = undefined;
      gestures.reset();
      documentUI();
      notifyChange();
      if (options.drafts !== false) {
        try {
          if (!draftsReady) throw new Error('本機草稿無法使用');
          await drafts.clear();
        } catch (error) {
          throw new Error(`已恢復原稿，但本機草稿未清除：${error.message}。重新開啟時可能恢復舊草稿。`);
        }
      }
      report('已恢復原稿，本機草稿已清除');
    });
  }

  async function setReadOnly(value) {
    return transition(async () => {
      readOnly = Boolean(value); gestures.reset(); modeUI();
      await client.request('mode', { readOnly });
      report(readOnly ? '唯讀：拖曳平移、雙指縮放' : '編輯：按 n 建立筆記，Enter 編輯');
    });
  }

  async function newDocument() {
    return transition(async () => {
      if (!await confirmReplace()) return false;
      await client.request('new', { columns: terminal.cols, rows: terminal.rows });
      name = 'whiteboard.tiwb'; documentUI();
      notifyChange();
      report('已建立空白文件'); return true;
    });
  }

  async function download() {
    const snapshot = await exportDocument();
    const url = URL.createObjectURL(new Blob([snapshot.bytes], { type: 'application/octet-stream' }));
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = snapshot.name.endsWith('.tiwb') ? snapshot.name : `${snapshot.name}.tiwb`;
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    report('已發起 .tiwb 下載');
  }

  const input = terminal.onData(text => { if (ready && !loading && !readOnly && !busy && !panelOpen) void client.input(text).catch(failure); });
  terminal.attachCustomKeyEventHandler(event => {
    if (loading || readOnly || busy || panelOpen) return false;
    if (event.ctrlKey && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (event.type === 'keydown') void saveDraft().catch(failure);
      return false;
    }
    return true;
  });
  const actions = {
    new: newDocument, open: () => fileInput.click(), export: download, save: saveDraft, reset: resetToOriginal,
    mode: () => setReadOnly(!readOnly), minus: () => view.zoom(view.getZoom() / 1.15, undefined, true), plus: () => view.zoom(view.getZoom() * 1.15, undefined, true),
    appearance: () => appearance.toggle(),
    fullscreen: toggleFullscreen, 'close-panel': () => panels.close(true),
    dismiss: () => { notice.dataset.visible = 'false'; }
  };
  root.addEventListener('click', event => {
    const button = event.target.closest('button[data-action]');
    if (!button || !ready || loading || busy || button.disabled) return;
    const action = button.dataset.action;
    if (['new', 'open', 'export', 'save', 'reset'].includes(action)) panels.close(true);
    // File pickers and fullscreen must run directly inside the user gesture.
    try { void Promise.resolve(actions[action]()).catch(failure); } catch (error) { failure(error); }
  }, { signal: abort.signal });
  const importFile = async file => {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) throw new Error('檔案上限為 32 MiB');
    await openDocument(new Uint8Array(await file.arrayBuffer()), file.name);
  };
  fileInput.addEventListener('change', () => {
    void importFile(fileInput.files[0]).catch(failure); fileInput.value = '';
  }, { signal: abort.signal });
  root.addEventListener('dragover', event => { event.preventDefault(); }, { signal: abort.signal });
  root.addEventListener('drop', event => {
    event.preventDefault(); void importFile(event.dataTransfer.files[0]).catch(failure);
  }, { signal: abort.signal });
  window.addEventListener('beforeunload', event => {
    if (state?.dirty) { event.preventDefault(); event.returnValue = ''; }
  }, { signal: abort.signal });

  function dispose() {
    if (disposed) return;
    disposed = true; ready = false;
    view.dispose();
    minimap.dispose();
    abort.abort(); observer.disconnect(); gestures.dispose(); input.dispose();
    client.dispose(); terminal.dispose(); drafts.close(); root.remove(); initialized.delete(container);
  }

  try {
    // xterm measures and caches glyph dimensions in open(). Load the actual
    // Latin and box-drawing subsets first; if either fails, measure its fallback.
    await document.fonts.load(`${terminal.options.fontSize}px ${terminal.options.fontFamily}`, 'W─').catch(() => {});
    await document.fonts.ready;
    terminal.open(terminalElement);
    view.write(terminalSetup);
    const size = dimensions();
    if (!size) throw new Error('白板容器必須有可見的寬度與高度');
    terminal.resize(size.columns, size.rows);
    await client.request('init', { ...size, readOnly });
    ready = true;
    let draft;
    if (options.drafts !== false) {
      try { draft = await drafts.open(); draftsReady = true; }
      catch (error) { failure(new Error(`本機草稿無法使用：${error.message}`)); }
    }
    $('[data-action="save"]').disabled = !draftsReady;
    // Validate the source before allowing reset; a saved draft then takes priority.
    if (original) await openDocument(original, originalName);
    if (draft && options.restoreDraft !== false) {
      try {
        await openDocument(new Uint8Array(draft.bytes), draft.name);
        savedRevision = `${state.generation}:${state.revision}`;
        documentUI();
        report('已恢復本機草稿');
      } catch (error) {
        failure(new Error(`草稿無法恢復，已保留${original ? '原稿' : '空白文件'}與儲存資料：${error.message}`));
      }
    } else if (!original && (options.drafts === false || draftsReady)) report(readOnly ? '唯讀：拖曳平移、雙指縮放' : '按 n 建立筆記，或匯入 .tiwb');
    // Consume every ANSI delta, including source/draft loads, while hidden.
    // The container can resize during startup, so reveal only a painted frame
    // whose geometry still matches both the terminal and the Worker.
    for (;;) {
      const size = dimensions();
      if (!size) throw new Error('白板容器必須有可見的寬度與高度');
      if (size.columns !== state.columns || size.rows !== state.rows) {
        terminal.resize(size.columns, size.rows);
        await client.request('resize', size);
      }
      await new Promise(resolve => terminal.write('', resolve));
      await new Promise(resolve => {
        terminal.refresh(0, terminal.rows - 1);
        // xterm queues its renderer first. Waiting for that animation frame also
        // lets offscreen embeds finish mounting, where onRender is suspended.
        requestAnimationFrame(resolve);
      });
      const current = dimensions();
      if (current?.columns === state.columns && current.rows === state.rows &&
          terminal.cols === state.columns && terminal.rows === state.rows) break;
    }
    loading = false;
    modeUI();
    resetButton.disabled = false;
    delete root.dataset.loading;
    root.inert = false;
    root.setAttribute('aria-busy', 'false');
    scheduleFit();
    return { open: openDocument, export: exportDocument, newDocument, saveDraft, resetToOriginal, setReadOnly,
      setAppearance(value) { ensureReady(); appearance.set(value); },
      getAppearance: () => appearance.get(),
      getState: () => state && { ...state, name }, dispose };
  } catch (error) { dispose(); throw error; }
}
