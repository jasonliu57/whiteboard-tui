import { build } from 'esbuild';
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { readUnicodeContract } from './unicode-contract.mjs';
import { webtuiStyles } from './webtui-styles.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const wasmDirectory = resolve(web, process.argv[2] || '../build/web/web');
const out = resolve(web, 'dist');
await mkdir(resolve(out, 'runtime'), { recursive: true });
for (const name of ['whiteboard.mjs', 'whiteboard.wasm'])
  await cp(resolve(wasmDirectory, name), resolve(out, 'runtime', name));

const contract = await readUnicodeContract();
const plugins = [{ name: 'unicode-contract', setup(builder) {
  builder.onResolve({ filter: /^whiteboard:unicode$/ }, () => ({ path: 'contract', namespace: 'unicode-contract' }));
  builder.onLoad({ filter: /.*/, namespace: 'unicode-contract' }, () => ({
    contents: `import { createUnicodeProvider } from './unicode.js'; export const unicodeProvider = createUnicodeProvider(${JSON.stringify(contract)});`,
    resolveDir: resolve(web, 'src'), loader: 'js'
  }));
} }, { name: 'webtui', setup(builder) {
  builder.onResolve({ filter: /^whiteboard:webtui$/ }, () => ({ path: 'styles', namespace: 'webtui' }));
  builder.onLoad({ filter: /.*/, namespace: 'webtui' }, async () => ({ contents: await webtuiStyles(), loader: 'css' }));
} }];

await build({ entryPoints: [resolve(web, 'src/index.js')], outfile: resolve(out, 'whiteboard.js'),
  bundle: true, format: 'esm', target: 'es2022', minify: true, plugins, legalComments: 'linked', external: ['./fonts/*'] });
await build({ entryPoints: [resolve(web, 'src/worker.js')], outfile: resolve(out, 'runtime/whiteboard.worker.js'),
  bundle: true, format: 'esm', target: 'es2022', minify: true, external: ['./whiteboard.mjs'] });
for (const name of ['index.html', 'standalone.js', 'standalone.css', '_headers'])
  await cp(resolve(web, 'standalone', name), resolve(out, name));
await cp(resolve(web, 'src/index.d.ts'), resolve(out, 'index.d.ts'));
await cp(resolve(web, '../LICENSE'), resolve(out, 'LICENSE'));
await cp(resolve(web, '../docs/third-party-notices.md'), resolve(out, 'THIRD_PARTY_NOTICES.md'));
await mkdir(resolve(out, 'fonts'), { recursive: true });
await cp(resolve(web, 'node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2'), resolve(out, 'fonts/jetbrains-mono-latin-wght-normal.woff2'));
await cp(resolve(web, 'fonts/jetbrains-mono-box-wght-normal.woff2'), resolve(out, 'fonts/jetbrains-mono-box-wght-normal.woff2'));
await mkdir(resolve(out, 'licenses'), { recursive: true });
await cp(resolve(wasmDirectory, 'licenses'), resolve(out, 'licenses'), { recursive: true });
for (const [name, path] of [
  ['xterm', 'node_modules/@xterm/xterm/LICENSE'],
  ['addon-fit', 'node_modules/@xterm/addon-fit/LICENSE'],
  ['webtui', 'licenses/webtui.txt'],
  ['jetbrains-mono', 'node_modules/@fontsource-variable/jetbrains-mono/LICENSE'],
  ['jetbrains-mono-box', 'fonts/OFL.txt'],
  ['tree-sitter', '../vendor/tree-sitter/LICENSE'],
  ['tree-sitter-unicode', '../vendor/tree-sitter/lib/src/unicode/LICENSE'],
  ['tree-sitter-cpp', '../vendor/tree-sitter-cpp/LICENSE'],
  ['tree-sitter-markdown', '../vendor/tree-sitter-markdown/LICENSE']
]) await cp(resolve(web, path), resolve(out, 'licenses', `${name}.txt`));
const pkg = JSON.parse(await readFile(resolve(web, 'package.json'), 'utf8'));
await writeFile(resolve(out, 'build.json'), JSON.stringify({ version: pkg.version, fileFormat: 11, unicode: contract.version }, null, 2) + '\n');
console.log(`Browser package and standalone page: ${out}`);
