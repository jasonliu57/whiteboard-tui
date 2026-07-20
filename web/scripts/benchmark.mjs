import { performance } from 'node:perf_hooks';
import { parseArgs } from 'node:util';
import { writeFile, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import createModule from '../../build/web/web/whiteboard.mjs';
import { Engine } from '../src/engine.js';

const { values } = parseArgs({ options: { cards: { type: 'string', default: '500' },
  samples: { type: 'string', default: '20' }, output: { type: 'string' } } });
const cards = Number(values.cards), samples = Number(values.samples);
if (!Number.isInteger(cards) || cards < 1 || cards > 10000 || !Number.isInteger(samples) || samples < 1 || samples > 1000)
  throw new Error('cards must be 1..10000; samples must be 1..1000');
const startup = performance.now();
const module = await createModule();
const engine = new Engine(module);
engine.create(120, 40);
const startupMs = performance.now() - startup;
for (let i = 0; i < cards; i++) {
  engine.input(`nCard ${i}: 中文 e\u0301`);
  engine.input('\x1b', true); engine.input('\x1b', true);
  engine.pan(20, 0);
}
engine.pan(-20 * cards, 0);
const bytes = engine.export();
const measure = (action, prepare = () => {}) => {
  prepare(); action();
  const times = [];
  for (let i = 0; i < samples; i++) { prepare(); const start = performance.now(); action(); times.push(performance.now() - start); }
  times.sort((a, b) => a - b);
  return { median_ms: times[Math.floor(times.length / 2)], p95_ms: times[Math.min(times.length - 1, Math.ceil(times.length * .95) - 1)] };
};
const operations = {
  decode: measure(() => engine.open(bytes)),
  encode: measure(() => engine.export()),
  frame: measure(() => engine.frame()),
  pan_and_frame: measure(() => { engine.pan(-1, 0); engine.frame(); }),
  overview_build: measure(() => engine.overview(), () => engine.open(bytes)),
  overview_cached: measure(() => engine.overview()),
  overview_view: measure(() => engine.overviewView())
};
const result = { schema: 1, runtime: process.version, platform: process.platform, architecture: process.arch,
  wasm_sha256: createHash('sha256').update(await readFile(new URL('../../build/web/web/whiteboard.wasm', import.meta.url))).digest('hex'),
  cards, samples, document_bytes: bytes.byteLength, wasm_memory_capacity_bytes: module.HEAPU8.byteLength,
  startup_ms: startupMs, overview_bytes: engine.overview().byteLength, operations };
const text = JSON.stringify(result, null, 2) + '\n';
if (values.output) await writeFile(values.output, text);
console.log(text);
engine.destroy();
