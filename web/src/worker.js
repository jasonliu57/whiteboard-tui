import createModule from './whiteboard.mjs';
import { Engine } from './engine.js';

let engine;
let readOnly = false;
let generation = 0;
let columns = 0, rows = 0;
let lastState;
let overviewActive = false;
let overviewKey;
let overviewHasContent = false;
let inputEpoch = 0;
let flushTimer;
let chain = Promise.resolve();

function view(render = true, overviewBuilt = false) {
  lastState = { ...engine.state(), generation, readOnly };
  if (overviewBuilt) overviewKey = { generation, revision: lastState.revision };
  return { state: lastState, ...(render ? { frame: engine.frame() } : {}),
    ...(overviewActive && overviewKey ? { overview: { ...overviewKey, rect: engine.overviewView() } } : {}) };
}

function cancelInput() {
  clearTimeout(flushTimer);
  inputEpoch++;
  engine.resetInput();
}

function resize(size) {
  if (size.columns === columns && size.rows === rows) return false;
  engine.resize(size.columns, size.rows);
  columns = size.columns; rows = size.rows;
  return true;
}

async function dispatch(message) {
  const { id, type, payload = {} } = message;
  try {
    let extra = {};
    let render = true;
    switch (type) {
      case 'init':
        if (engine) throw new Error('白板已初始化');
        engine = new Engine(await createModule());
        engine.create(payload.columns, payload.rows);
        columns = payload.columns; rows = payload.rows;
        readOnly = Boolean(payload.readOnly);
        break;
      case 'input': {
        if (readOnly || payload.epoch !== inputEpoch) { render = false; break; }
        clearTimeout(flushTimer);
        // xterm emits a complete Escape key event; it is not a native PTY byte fragment.
        engine.input(payload.text, payload.text === '\x1b');
        if (!engine.pendingInput()) break;
        const epoch = inputEpoch;
        flushTimer = setTimeout(() => {
          chain = chain.then(() => {
            if (readOnly || epoch !== inputEpoch) return;
            try {
              engine.input('', true);
              const update = view();
              postMessage({ event: 'view', ...update }, [update.frame.buffer]);
            } catch (error) { postMessage({ event: 'error', error: error.message }); }
          });
        }, 40);
        break;
      }
      case 'mode':
        cancelInput();
        readOnly = Boolean(payload.readOnly);
        break;
      case 'sync':
        // A queued query is a barrier for all accepted input. Do not cancel a
        // fragmented paste/escape or force its timeout merely to replace a file.
        if (engine.pendingInput()) throw new Error('輸入尚未完成，請完成貼上或稍後再切換文件');
        render = false;
        break;
      case 'resize': render = resize(payload); break;
      case 'overview':
        render = false;
        if (payload.generation !== generation) break;
        overviewActive = Boolean(payload.enabled);
        if (overviewActive) {
          const geometry = engine.overview();
          overviewHasContent = geometry[1] > 0;
          extra.overviewBytes = geometry.buffer;
        }
        break;
      case 'viewport':
        if (payload.generation !== generation) { render = false; break; }
        if (payload.center && (!overviewKey || !overviewHasContent || payload.center.revision !== overviewKey.revision ||
            overviewKey.generation !== generation || payload.center.revision !== lastState.revision ||
            ![payload.center.x, payload.center.y].every(value => Number.isFinite(value) && value >= 0 && value <= 1))) {
          render = false; extra.navigationRejected = true; break;
        }
        render = resize(payload);
        if (payload.center) { engine.centerOverview(payload.center.x, payload.center.y); render = true; }
        if (payload.dx || payload.dy) {
          engine.pan(payload.dx, payload.dy);
          render = true;
        }
        break;
      case 'pan':
        render = Boolean(payload.dx || payload.dy);
        if (render) engine.pan(payload.dx, payload.dy);
        break;
      case 'open':
        engine.open(new Uint8Array(payload.bytes));
        overviewKey = undefined;
        cancelInput();
        generation++;
        break;
      case 'new':
        engine.create(payload.columns, payload.rows);
        overviewKey = undefined;
        columns = payload.columns; rows = payload.rows;
        cancelInput();
        generation++;
        break;
      case 'export': extra.bytes = engine.export().buffer; render = false; break;
      case 'saved':
        render = payload.generation === generation;
        if (render) engine.markSaved(payload.revision);
        break;
      default: throw new Error('未知白板操作');
    }
    const update = view(render, Boolean(extra.overviewBytes));
    postMessage({ id, ...update, ...extra, epoch: inputEpoch },
      [...(update.frame ? [update.frame.buffer] : []), ...(extra.bytes ? [extra.bytes] : []),
        ...(extra.overviewBytes ? [extra.overviewBytes] : [])]);
  } catch (error) { postMessage({ id, error: error.message }); }
}

self.onmessage = ({ data }) => { chain = chain.then(() => dispatch(data)); };
