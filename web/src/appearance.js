export function validateAppearance(value) {
  if (!['light', 'dark', 'system'].includes(value)) throw new TypeError('appearance 必須是 light、dark 或 system');
  return value;
}

/** CSS owns the palette; both the shell and ANSI terminal use its resolved colors. */
export function attachAppearance(root, terminal, { appearance = 'system', theme, onChange, signal }) {
  let mode = validateAppearance(appearance);
  let appliedMode;
  let appliedColor;
  const buttons = root.querySelectorAll('[data-action="appearance"]');
  const media = matchMedia('(prefers-color-scheme: dark)');
  const apply = () => {
    const resolved = mode === 'system' ? (media.matches ? 'dark' : 'light') : mode;
    if (mode === appliedMode && resolved === appliedColor) return;
    if (resolved !== appliedColor) {
      root.dataset.appearance = resolved;
      if (resolved === 'dark') root.dataset.webtuiTheme = 'catppuccin-mocha';
      else delete root.dataset.webtuiTheme;
      const css = getComputedStyle(root);
      const color = name => css.getPropertyValue(`--${name}`).trim();
      const palette = { background: color('background0'), foreground: color('foreground0'),
        cursor: color('foreground0'), cursorAccent: color('background0'),
        selectionBackground: color('background2'), selectionForeground: color('foreground0'),
        black: color('background0'), white: color('foreground0'),
        brightBlack: color('foreground2'), brightWhite: color('foreground0') };
      for (const [ansi, token] of Object.entries({ red: 'red', green: 'green', yellow: 'yellow', blue: 'blue', magenta: 'mauve', cyan: 'teal' })) {
        palette[ansi] = color(token);
        palette[`bright${ansi[0].toUpperCase()}${ansi.slice(1)}`] = color(token);
      }
      terminal.options.theme = { ...palette, ...theme };
      // Assigning theme already invalidates xterm's renderer.
      buttons.forEach(button => {
        button.textContent = resolved === 'dark' ? '☀' : '☾';
        button.setAttribute('aria-label', resolved === 'dark' ? '切換至日間模式' : '切換至夜間模式');
        button.title = button.getAttribute('aria-label');
      });
    }
    appliedMode = mode;
    appliedColor = resolved;
    onChange?.({ appearance: mode, resolvedAppearance: resolved });
  };
  media.addEventListener('change', () => { if (mode === 'system') apply(); }, { signal });
  apply();
  return { set(value) { mode = validateAppearance(value); apply(); },
    toggle() { mode = root.dataset.appearance === 'dark' ? 'light' : 'dark'; apply(); },
    get() { return { appearance: mode, resolvedAppearance: root.dataset.appearance }; } };
}
