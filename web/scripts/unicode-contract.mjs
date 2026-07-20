import { readFile } from 'node:fs/promises';

export async function readUnicodeContract() {
  const header = await readFile(new URL('../../src/text/unicode_width_table.hpp', import.meta.url), 'utf8');
  const version = header.match(/kUnicodeContractVersion\[\] = "([^"]+)"/)[1];
  const ranges = name => {
    const source = header.match(new RegExp(`${name}\\[\\] = \\{([\\s\\S]*?)\\n\\};`))[1];
    return [...source.matchAll(/\{0x([0-9A-F]+), 0x([0-9A-F]+)\}/gi)]
      .map(match => [parseInt(match[1], 16), parseInt(match[2], 16)]);
  };
  return { version, zeroWidth: ranges('kUnicodeZeroWidthIntervals'),
    control: ranges('kUnicodeControlIntervals'), wide: ranges('kUnicodeWideIntervals') };
}
