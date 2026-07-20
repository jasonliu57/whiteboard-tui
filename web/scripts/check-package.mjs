import { access, readFile } from 'node:fs/promises';
const base = new URL('../dist/', import.meta.url);
for (const name of ['whiteboard.js', 'whiteboard.css', 'index.d.ts', 'index.html', 'standalone.js',
  'runtime/whiteboard.mjs', 'runtime/whiteboard.wasm', 'runtime/whiteboard.worker.js', 'build.json',
  'LICENSE', 'THIRD_PARTY_NOTICES.md',
  'fonts/jetbrains-mono-latin-wght-normal.woff2', 'fonts/jetbrains-mono-box-wght-normal.woff2',
  'licenses/jetbrains-mono.txt', 'licenses/jetbrains-mono-box.txt'])
  await access(new URL(name, base));
const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url)));
const manifest = JSON.parse(await readFile(new URL('build.json', base)));
if (manifest.version !== pkg.version) throw new Error('Build the current package version before packing');
