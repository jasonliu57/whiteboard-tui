import { mountWhiteboard } from './whiteboard.js';
try {
  const preferenceKey = 'whiteboard-appearance';
  let savedAppearance = 'system';
  try { savedAppearance = localStorage.getItem(preferenceKey) || 'system'; } catch { /* Preferences are optional. */ }
  const options = { appearance: ['light', 'dark', 'system'].includes(savedAppearance) ? savedAppearance : 'system',
    onAppearanceChange({ appearance, resolvedAppearance }) {
      document.documentElement.dataset.appearance = resolvedAppearance;
      try { localStorage.setItem(preferenceKey, appearance); } catch { /* Display still works without preference storage. */ }
    } };

  const query = new URLSearchParams(location.search);
  if (query.get('mode') === 'read') options.readOnly = true;
  if (query.get('mode') === 'edit') options.readOnly = false;
  if (query.has('file')) {
    const url = new URL(query.get('file'), location.href);
    if (url.origin !== location.origin) throw new Error('公開白板必須位於相同網站');
    const response = await fetch(url);
    if (!response.ok) throw new Error(`無法讀取白板：HTTP ${response.status}`);
    const length = Number(response.headers.get('content-length'));
    if (length > 32 * 1024 * 1024) throw new Error('檔案上限為 32 MiB');
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 32 * 1024 * 1024) { await reader.cancel(); throw new Error('檔案上限為 32 MiB'); }
      chunks.push(value);
    }
    options.document = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { options.document.set(chunk, offset); offset += chunk.byteLength; }
    options.name = decodeURIComponent(url.pathname.split('/').pop());
    options.draftKey = `public:${url.pathname}`;
  }
  const board = await mountWhiteboard(document.querySelector('#whiteboard'), options);
  window.addEventListener('storage', event => {
    if (event.key === preferenceKey || event.key === null)
      board.setAppearance(['light', 'dark'].includes(event.newValue) ? event.newValue : 'system');
  });
  window.addEventListener('pagehide', event => { if (!event.persisted) board.dispose(); });
} catch (error) {
  const message = document.querySelector('#startup-error');
  message.hidden = false; message.textContent = error.message;
}
