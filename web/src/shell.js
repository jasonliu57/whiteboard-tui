let nextId = 0;

export function createShell(container, { backLink, fontFamily } = {}) {
  const root = document.createElement('section');
  const id = `tiwb-${++nextId}`;
  root.className = 'tiwb-app';
  root.dataset.loading = 'true';
  root.inert = true;
  root.setAttribute('aria-busy', 'true');
  root.setAttribute('aria-label', 'Whiteboard');
  if (fontFamily) root.style.setProperty('--font-family', fontFamily);
  const zoom = `<button type="button" size-="small" data-action="minus" aria-label="縮小">−</button>
    <output class="tiwb-zoom" aria-label="縮放比例">100%</output>
    <button type="button" size-="small" data-action="plus" aria-label="放大">＋</button>`;
  const appearance = `<button type="button" size-="small" data-action="appearance" aria-label="切換配色">☀</button>`;
  const fullscreen = `<button type="button" size-="small" data-action="fullscreen" aria-label="進入全螢幕" title="進入全螢幕">⛶</button>`;
  // Constant markup only. Caller-supplied text is assigned using DOM properties.
  root.innerHTML = `<div class="tiwb-toolbar" role="group" aria-label="白板工具">
    <a class="tiwb-back" aria-label="返回網站" title="返回網站" hidden>←</a>
    <span class="tiwb-brand" title="whiteboardTUI">wb<span>▌</span></span>
    <button type="button" size-="small" class="tiwb-desktop" data-panel="file" aria-expanded="false" aria-controls="${id}-file">文件 ▾</button>
    <div class="tiwb-document"><span class="tiwb-name"></span><span class="tiwb-save-state" role="status"></span></div>
    <button type="button" size-="small" data-action="reset" aria-label="恢復原稿" title="恢復原稿並清除此白板的本機草稿（不會詢問）" hidden><span aria-hidden="true">↺</span></button>
    <button type="button" size-="small" data-action="mode" aria-pressed="false">唯讀中</button>
    <div class="tiwb-zoom-controls tiwb-desktop">${zoom}</div>
    <div class="tiwb-desktop">${appearance}${fullscreen}<button type="button" size-="small" data-panel="help" aria-expanded="false" aria-controls="${id}-help" aria-label="操作說明" title="操作說明">?</button></div>
    <button type="button" size-="small" class="tiwb-mobile" data-panel="file" aria-expanded="false" aria-controls="${id}-file" aria-label="白板選單">⋯</button>
  </div>
  <div class="tiwb-popover tiwb-file-menu" id="${id}-file" hidden role="group" aria-label="文件與顯示設定">
    <div class="tiwb-panel-caption">文件</div>
    <button type="button" size-="small" data-action="new">新建</button>
    <button type="button" size-="small" data-action="open">匯入 .tiwb</button>
    <button type="button" size-="small" data-action="export">匯出 .tiwb</button>
    <button type="button" size-="small" data-action="save" aria-label="儲存草稿">儲存草稿 <kbd>Ctrl S</kbd></button>
    <div class="tiwb-mobile tiwb-menu-settings"><div class="tiwb-panel-caption">顯示</div>
      <div class="tiwb-zoom-controls">${zoom}</div><div>${appearance}${fullscreen}</div>
      <button type="button" size-="small" data-panel="help" aria-controls="${id}-help" aria-expanded="false">操作說明</button>
    </div>
  </div>
  <div class="tiwb-popover tiwb-help" id="${id}-help" hidden role="region" aria-label="操作說明">
    <div class="tiwb-panel-caption">操作說明 <button type="button" size-="small" data-action="close-panel" aria-label="關閉操作說明">×</button></div>
    <p><kbd>n</kbd> 筆記　<kbd>m</kbd> Markdown　<kbd>c</kbd> 程式碼<br><kbd>t</kbd> 待辦　<kbd>v</kbd> CSV　<kbd>f</kbd> Folder</p>
    <p><kbd>Enter</kbd> 編輯卡片　<kbd>Esc</kbd> 離開編輯<br>方向鍵或 <kbd>hjkl</kbd> 移動游標<br><kbd>Shift HJKL</kbd> 移動卡片</p>
    <p><kbd>g</kbd> 編輯連線　<kbd>i</kbd> 編輯 Glyph<br><kbd>Ctrl Z</kbd> 復原　<kbd>Ctrl R</kbd> 重做<br><kbd>Ctrl S</kbd> 儲存本機草稿</p>
    <p>唯讀：拖曳或滾輪平移，雙指或 Ctrl＋滾輪縮放。編輯時可用滑鼠中鍵平移。</p>
    <p>草稿保存在這個瀏覽器；匯出 .tiwb 可備份完整文件。</p>
    <p class="tiwb-reset-help" hidden>↺ 直接恢復原稿並清除此白板的本機草稿，不顯示確認；需要保留修改請先匯出。</p>
  </div>
  <div class="tiwb-viewport"><div class="tiwb-terminal"></div><div class="tiwb-gesture" hidden></div></div>
  <aside class="tiwb-minimap" aria-label="白板小地圖">
    <button type="button" data-map="toggle" aria-expanded="false" aria-controls="${id}-map">地圖</button>
    <div class="tiwb-map-panel" id="${id}-map" hidden>
      <div class="tiwb-map-heading">地圖<button type="button" data-map="close" aria-label="收合地圖">×</button></div>
      <button type="button" class="tiwb-map-surface" aria-label="地圖，點擊跳轉；方向鍵平移，Home 回到內容中央">
        <canvas aria-hidden="true"></canvas><span class="tiwb-map-frame" hidden></span>
      </button>
    </div>
  </aside>
  <div class="tiwb-notice"><span class="tiwb-message" role="status" aria-live="polite">正在載入白板…</span><button type="button" size-="small" data-action="dismiss" aria-label="關閉提示">×</button></div>
  <input class="tiwb-file" type="file" accept=".tiwb" hidden>`;
  if (backLink) {
    const url = new URL(backLink.href, document.baseURI);
    if (!['http:', 'https:'].includes(url.protocol)) throw new TypeError('返回連結必須是 HTTP 或 HTTPS URL');
    const link = root.querySelector('.tiwb-back');
    link.href = url.href;
    link.title = backLink.label || '返回網站';
    link.setAttribute('aria-label', link.title);
    link.hidden = false;
    root.querySelector('.tiwb-brand').hidden = true;
  }
  container.append(root);
  return root;
}

export function attachPanels(root, signal, onToggle) {
  let opener;
  let active;
  const panels = { file: root.querySelector('.tiwb-file-menu'), help: root.querySelector('.tiwb-help') };
  const buttons = [...root.querySelectorAll('[data-panel]')];
  const activate = next => {
    if (active === next) return;
    const wasOpen = Boolean(active);
    if (active) panels[active].hidden = true;
    active = next;
    if (wasOpen !== Boolean(active)) onToggle(Boolean(active));
    if (active) panels[active].hidden = false;
    buttons.forEach(button => button.setAttribute('aria-expanded', String(button.dataset.panel === active)));
  };
  const close = (restoreFocus = false) => {
    if (!active) return;
    activate(undefined);
    if (restoreFocus) opener?.focus({ preventScroll: true });
  };
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-panel]');
    if (!button || root.inert) return;
    if (active === button.dataset.panel) { close(); return; }
    if (!button.closest('.tiwb-popover')) opener = button;
    activate(button.dataset.panel);
    panels[active].querySelector('button:not(:disabled)')?.focus({ preventScroll: true });
  }, { signal });
  document.addEventListener('pointerdown', event => {
    if (!root.contains(event.target) || !event.target.closest('.tiwb-popover, [data-panel]')) close();
  }, { signal, capture: true });
  root.addEventListener('keydown', event => {
    if (event.key === 'Escape' && active) {
      event.preventDefault(); event.stopPropagation(); close(true);
    }
  }, { signal, capture: true });
  return { close };
}
