import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import postcss from 'postcss';

const require = createRequire(import.meta.url);

/** Scope official components and tokens without applying WebTUI's page reset to xterm or the host. */
export async function webtuiStyles() {
  const files = ['@webtui/css/base.css', '@webtui/css/components/button.css', '@webtui/theme-catppuccin'];
  const sheets = [];
  for (const file of files) {
    const css = postcss.parse(await readFile(require.resolve(file), 'utf8'));
    css.walkRules(rule => {
      if (file.endsWith('/base.css') && rule.selector !== ':root') { rule.remove(); return; }
      if (file === '@webtui/theme-catppuccin' && !rule.selector.startsWith('[data-webtui-theme')) { rule.remove(); return; }
      rule.selectors = rule.selectors.map(selector => selector === ':root' ? '.tiwb-app'
        : selector.startsWith('[data-webtui-theme') ? `.tiwb-app${selector}` : `.tiwb-app ${selector}`);
    });
    sheets.push(css.toString());
  }
  return '@layer base, components;\n' + sheets.join('\n');
}
