import { chromium } from '@playwright/test';
import { parseArgs } from 'node:util';
import { writeFile } from 'node:fs/promises';

const { values } = parseArgs({ options: {
  url: { type: 'string', default: 'http://127.0.0.1:4173/' },
  samples: { type: 'string', default: '20' },
  cpu: { type: 'string', default: '4' }, output: { type: 'string' }, baseline: { type: 'boolean', default: false },
  minimap: { type: 'boolean', default: false }
} });
const samples = Number(values.samples), cpu = Number(values.cpu);
if (!Number.isInteger(samples) || samples < 1 || samples > 1000 || !Number.isFinite(cpu) || cpu < 1)
  throw new Error('samples must be 1..1000; cpu must be >= 1');
const stats = times => {
  times.sort((a, b) => a - b);
  return { median_ms: times[Math.floor(times.length / 2)],
    p95_ms: times[Math.ceil(times.length * .95) - 1] };
};
if (values.minimap && values.baseline) throw new Error('--minimap requires a build with overview support');
let mapFixture;
if (values.minimap) {
  const { default: createModule } = await import('../../build/web/web/whiteboard.mjs');
  const { Engine } = await import('../src/engine.js');
  const engine = new Engine(await createModule()); engine.create(120, 40);
  let x = 0, y = 0;
  for (let i = 0; i < 500; i++) {
    const nextX = (i % 25) * 30, nextY = Math.floor(i / 25) * 12;
    engine.pan(nextX - x, nextY - y); x = nextX; y = nextY;
    engine.input(`nCard ${i}`); engine.input('\x1b', true); engine.input('\x1b', true);
  }
  mapFixture = [...engine.export()]; engine.destroy();
}
const browser = await chromium.launch({ headless: true });
try {
  const result = { schema: 1, browser: browser.version(), cpu_throttle: cpu, samples,
    // The second animation callback is a paint opportunity, not a physical display measurement.
    menu: {}, worker: {}, viewport: {} };
  for (const mobile of [false, true]) {
    const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 800 },
      isMobile: mobile, hasTouch: mobile });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: cpu });
    await cdp.send('Performance.enable');
    await page.addInitScript(() => {
      const trace = window.viewportBenchmark = { pending: 0, requests: [], frames: [], mapQueries: 0, mapBytes: 0, mapFrames: 0, mapTimes: [], mapDraws: 0 };
      const NativeWorker = window.Worker;
      window.Worker = class extends NativeWorker {
        types = new Map();
        mapStarts = new Map();
        postMessage(message, ...args) {
          this.types.set(message.id, message.type);
          if (message.type === 'overview' && message.payload.enabled) {
            trace.mapQueries++; this.mapStarts.set(message.id, performance.now());
          }
          if (['viewport', 'resize', 'pan'].includes(message.type)) {
            trace.pending++;
            trace.requests.push(message.type);
          }
          return super.postMessage(message, ...args);
        }
        set onmessage(handler) {
          super.onmessage = event => {
            if (this.mapStarts.has(event.data.id)) {
              trace.mapBytes += event.data.overviewBytes?.byteLength || 0;
              trace.mapTimes.push(performance.now() - this.mapStarts.get(event.data.id));
              trace.mapFrames += Number(Boolean(event.data.frame));
              this.mapStarts.delete(event.data.id);
            }
            if (['viewport', 'resize', 'pan'].includes(this.types.get(event.data.id))) {
              trace.pending--;
              if (event.data.frame) trace.frames.push(event.data.frame.byteLength);
            }
            handler(event);
          };
        }
      };
      const draw = CanvasRenderingContext2D.prototype.strokeRect;
      CanvasRenderingContext2D.prototype.strokeRect = function(...args) {
        if (this.canvas.closest('.tiwb-minimap')) trace.mapDraws++;
        return draw.apply(this, args);
      };
    });
    await page.goto(values.url);
    await page.waitForSelector('.tiwb-app:not([inert])[aria-busy="false"]');
    const times = await page.evaluate(async count => {
      const root = document.querySelector('.tiwb-app');
      const button = [...root.querySelectorAll('.tiwb-toolbar [data-panel="file"]')].find(item => item.offsetWidth);
      const handler = [], paint = [];
      for (let i = 0; i < count + 3; i++) {
        await new Promise(requestAnimationFrame);
        const start = performance.now();
        button.click();
        const end = performance.now();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        if (i >= 3) { handler.push(end - start); paint.push(performance.now() - start); }
        button.click();
      }
      return { handler, paint };
    }, samples);
    result.menu[mobile ? 'mobile' : 'desktop'] = {
      click_handler: stats(times.handler), click_to_paint_opportunity: stats(times.paint)
    };
    // Both the old split requests and the combined viewport request are traced,
    // so the same benchmark can measure a baseline build at --url.
    const tasksBefore = await cdp.send('Performance.getMetrics');
    const viewportTimes = await page.evaluate(async count => {
      const root = document.querySelector('.tiwb-app');
      const trace = window.viewportBenchmark;
      const handler = [], complete = [], requests = [], frames = [], bytes = [];
      for (let i = 0; i < count + 4; i++) {
        await new Promise(requestAnimationFrame);
        trace.requests = []; trace.frames = [];
        const button = root.querySelector(`.tiwb-toolbar [data-action="${i % 2 ? 'minus' : 'plus'}"]`);
        const start = performance.now();
        button.click();
        const handled = performance.now() - start;
        do {
          await new Promise(requestAnimationFrame);
          if (performance.now() - start > 10000) throw new Error('Viewport failed to settle');
        } while (!trace.requests.length || trace.pending || root.querySelector('.tiwb-frame-cover'));
        await new Promise(requestAnimationFrame);
        if (i >= 4) {
          handler.push(handled); complete.push(performance.now() - start);
          requests.push(trace.requests.length); frames.push(trace.frames.length);
          bytes.push(trace.frames.reduce((sum, size) => sum + size, 0));
        }
      }
      return { handler, complete, requests, frames, bytes };
    }, samples);
    const tasksAfter = await cdp.send('Performance.getMetrics');
    const taskDuration = metrics => metrics.metrics.find(metric => metric.name === 'TaskDuration').value;
    result.viewport[mobile ? 'mobile' : 'desktop'] = {
      click_handler: stats(viewportTimes.handler), completion_paint_opportunity: stats(viewportTimes.complete),
      request_counts: viewportTimes.requests, frame_counts: viewportTimes.frames, ansi_bytes: viewportTimes.bytes,
      // Includes the four warm-up operations and the measurement code itself.
      main_thread_task_ms_per_operation: 1000 * (taskDuration(tasksAfter) - taskDuration(tasksBefore)) / (samples + 4)
    };
    if (mobile) {
      await page.evaluate(() => {
        window.tapDelays = [];
        let released;
        const button = document.querySelector('.tiwb-toolbar .tiwb-mobile[data-panel="file"]');
        button.addEventListener('pointerup', () => { released = performance.now(); });
        button.addEventListener('click', () => window.tapDelays.push(performance.now() - released));
      });
      const button = page.locator('.tiwb-toolbar .tiwb-mobile[data-panel="file"]');
      for (let i = 0; i < samples; i++) await button.tap();
      result.menu.mobile.touch_release_to_click = stats(await page.evaluate(() => window.tapDelays));
    } else {
      result.worker = await page.evaluate(async ({ count, baseline }) => {
        const worker = new Worker(new URL('runtime/whiteboard.worker.js', location.href), { type: 'module' });
        const pending = new Map();
        let id = 0, views = [], start = 0;
        worker.onmessage = ({ data }) => {
          if (data.frame) views.push({ ms: performance.now() - start, bytes: data.frame.byteLength });
          const job = pending.get(data.id);
          if (job) { pending.delete(data.id); data.error ? job.reject(new Error(data.error)) : job.resolve(data); }
        };
        const request = (type, payload = {}) => new Promise((resolve, reject) => {
          const next = ++id; pending.set(next, { resolve, reject });
          worker.postMessage({ id: next, type, payload });
        });
        try {
          const init = await request('init', { columns: 120, rows: 40, readOnly: false });
          await request('input', { text: 'nBenchmark', epoch: init.epoch });
          await new Promise(resolve => setTimeout(resolve, 80));
          const edits = [], escapes = [], exports = [];
          for (let i = 0; i < count; i++) {
            views = []; start = performance.now();
            await request('input', { text: 'x', epoch: init.epoch });
            await new Promise(resolve => setTimeout(resolve, 70));
            edits.push(views.length);
            views = []; start = performance.now();
            await request('input', { text: '\x1b', epoch: init.epoch });
            await new Promise(resolve => setTimeout(resolve, 70));
            escapes.push(views.find(view => view.bytes > 0)?.ms);
            views = [];
            await request('export');
            exports.push(views.length);
            await request('input', { text: '\r', epoch: init.epoch });
            await new Promise(resolve => setTimeout(resolve, 70));
          }
          const viewport = {};
          for (const strategy of baseline ? ['split'] : ['split', 'combined']) {
            await request('resize', { columns: 120, rows: 40 });
            const current = await request(baseline ? 'export' : 'sync');
            await request('pan', { dx: -Number(current.state.x), dy: -Number(current.state.y) });
            const times = [], counts = [], bytes = [];
            for (let i = 0; i < count; i++) {
              const size = i % 2 ? { columns: 120, rows: 40, dx: -3, dy: -2 }
                : { columns: 124, rows: 42, dx: 3, dy: 2 };
              views = []; start = performance.now();
              if (strategy === 'split') {
                await Promise.all([request('resize', size), request('pan', size)]);
              } else await request('viewport', { ...size, generation: init.state.generation });
              times.push(performance.now() - start);
              counts.push(views.length); bytes.push(views.reduce((sum, view) => sum + view.bytes, 0));
            }
            viewport[strategy] = { times, counts, bytes };
          }
          return { input_frame_counts: edits, export_frame_counts: exports, escape_first_changed_frame_ms: escapes, viewport };
        } finally { worker.terminate(); }
      }, { count: samples, baseline: values.baseline });
      if (result.worker.escape_first_changed_frame_ms.some(value => value == null)) throw new Error('Escape did not produce a changed frame');
      result.worker.escape_first_changed_frame = stats(result.worker.escape_first_changed_frame_ms);
      delete result.worker.escape_first_changed_frame_ms;
      for (const entry of Object.values(result.worker.viewport)) {
        entry.round_trip = stats(entry.times); delete entry.times;
      }
      result.wasm_sha256 = await page.evaluate(async () => {
        const bytes = await (await fetch(new URL('runtime/whiteboard.wasm', location.href))).arrayBuffer();
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
      });
    }
    if (values.minimap) {
      await page.evaluate(async bytes => {
        const { mountWhiteboard } = await import(new URL('whiteboard.js', location.href));
        const host = document.createElement('div'); host.id = 'benchmark-map';
        host.style.cssText = 'position:fixed;inset:0;z-index:20'; document.body.append(host);
        window.mapBenchmarkApp = await mountWhiteboard(host, { document: new Uint8Array(bytes),
          drafts: false, readOnly: true, assetBaseUrl: new URL('runtime/', location.href).href });
      }, mapFixture);
      const mapResult = { cards: 500 };
      for (const opened of [false, true]) {
        if (opened) {
          await page.locator('#benchmark-map [data-map="toggle"]').click();
          await page.locator('#benchmark-map .tiwb-map-surface[aria-disabled="false"]').waitFor();
          mapResult.initial_query = await page.evaluate(() => ({ count: window.viewportBenchmark.mapQueries,
            bytes: window.viewportBenchmark.mapBytes, ansi_frames: window.viewportBenchmark.mapFrames,
            round_trip_ms: window.viewportBenchmark.mapTimes.at(-1) }));
        }
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const before = await cdp.send('Performance.getMetrics');
        const measured = await page.evaluate(async count => {
          const trace = window.viewportBenchmark;
          const queries = trace.mapQueries, draws = trace.mapDraws;
          const times = [], frames = [];
          for (let i = 0; i < count + 4; i++) {
            await new Promise(requestAnimationFrame);
            trace.requests = []; trace.frames = [];
            const start = performance.now();
            document.querySelector('#benchmark-map .tiwb-viewport').dispatchEvent(
              new WheelEvent('wheel', { deltaX: i % 2 ? -24 : 24, bubbles: true, cancelable: true }));
            do {
              await new Promise(requestAnimationFrame);
              if (performance.now() - start > 10000) throw new Error('Minimap pan failed to settle');
            } while (!trace.requests.length || trace.pending);
            await new Promise(requestAnimationFrame);
            if (i >= 4) { times.push(performance.now() - start); frames.push(trace.frames.length); }
          }
          return { times, frames, overview_queries: trace.mapQueries - queries, base_draw_calls: trace.mapDraws - draws };
        }, samples);
        const after = await cdp.send('Performance.getMetrics');
        mapResult[opened ? 'expanded' : 'collapsed'] = {
          completion_paint_opportunity: stats(measured.times), frame_counts: measured.frames,
          overview_queries: measured.overview_queries, base_draw_calls: measured.base_draw_calls,
          main_thread_task_ms_per_operation: 1000 * (taskDuration(after) - taskDuration(before)) / (samples + 4)
        };
      }
      result.minimap ??= {};
      result.minimap[mobile ? 'mobile' : 'desktop'] = mapResult;
    }
    await context.close();
  }
  const json = JSON.stringify(result, null, 2) + '\n';
  if (values.output) await writeFile(values.output, json);
  console.log(json);
} finally { await browser.close(); }
