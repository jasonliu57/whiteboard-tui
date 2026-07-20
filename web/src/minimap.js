// Owns only a disposable display projection. Document geometry and inverse
// projection remain in the core; navigation uses the existing view coordinator.
export function attachMinimap(root, { client, view, state, enabled, failure }) {
  const element = root.querySelector('.tiwb-minimap');
  const toggle = element.querySelector('[data-map="toggle"]');
  const panel = element.querySelector('.tiwb-map-panel');
  const surface = element.querySelector('.tiwb-map-surface');
  const canvas = surface.querySelector('canvas');
  const frame = surface.querySelector('.tiwb-map-frame');
  const context = canvas.getContext('2d');
  const abort = new AbortController();
  let opened = false, closed = false, pending = false, subscribed = false;
  let timer, animation, lastRequest = -Infinity;
  let scene, sceneKey, failedKey, metadata, plot, lastSize;
  const key = value => value && `${value.generation}:${value.revision}`;
  const active = () => opened && !closed && !document.hidden && enabled();
  const usable = () => active() && scene?.[1] > 0 && sceneKey === key(state());

  function overlay() {
    if (!active()) return;
    surface.setAttribute('aria-disabled', String(!usable()));
    frame.hidden = true;
    if (!scene?.[1]) return;
    if (!plot || !metadata || key(metadata) !== sceneKey || !metadata.rect) return;
    const [left, top, right, bottom] = metadata.rect;
    const outside = right <= 0 || bottom <= 0 || left >= 1 || top >= 1;
    if (outside) return;
    const x = Math.max(0, left), y = Math.max(0, top);
    const width = Math.min(plot.width, Math.max(2, (Math.min(1, right) - x) * plot.width));
    const height = Math.min(plot.height, Math.max(2, (Math.min(1, bottom) - y) * plot.height));
    Object.assign(frame.style, {
      left: `${plot.x + Math.min(x * plot.width, plot.width - width)}px`,
      top: `${plot.y + Math.min(y * plot.height, plot.height - height)}px`,
      width: `${width}px`, height: `${height}px`
    });
    frame.hidden = false;
  }

  function draw() {
    animation = undefined;
    if (!active() || !context) return;
    const width = surface.clientWidth, height = surface.clientHeight;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    plot = undefined;
    const cell = view.cellSize();
    const viewportHeight = root.querySelector('.tiwb-viewport').clientHeight;
    const bottom = Math.max(8, viewportHeight - (state().rows - 1) * cell.height + 8);
    element.style.bottom = `${bottom}px`;
    element.style.maxHeight = `${Math.max(44, viewportHeight - bottom - 8)}px`;
    if (!scene?.[1] || width < 20 || height < 20) { overlay(); return; }
    const aspect = scene[1] * cell.width / cell.height;
    const w = Math.max(2, Math.min(width - 16, (height - 16) * aspect));
    const h = Math.max(2, Math.min(height - 16, w / aspect));
    plot = { x: (width - w) / 2, y: (height - h) / 2, width: w, height: h };
    const css = getComputedStyle(root);
    const color = name => css.getPropertyValue(`--${name}`).trim();
    const colors = ['blue', 'green', 'yellow', 'mauve', 'teal', 'red', 'foreground1', 'foreground0'].map(color);
    const background = color('background2'), edge = color('foreground2'), glyph = color('foreground1');
    for (let i = 2; i < scene.length; i += 6) {
      const kind = scene[i], tint = scene[i + 1];
      const x = plot.x + scene[i + 2] * w, y = plot.y + scene[i + 3] * h;
      const endX = plot.x + scene[i + 4] * w, endY = plot.y + scene[i + 5] * h;
      if (kind === 2) {
        context.strokeStyle = tint ? colors[5] : edge;
        context.beginPath(); context.moveTo(x, y); context.lineTo(endX, endY); context.stroke();
      } else {
        const rw = Math.max(1, endX - x), rh = Math.max(1, endY - y);
        context.fillStyle = kind === 1 ? glyph : background;
        context.fillRect(x, y, rw, rh);
        if (kind === 0) { context.strokeStyle = colors[tint]; context.strokeRect(x, y, rw, rh); }
      }
    }
    overlay();
  }

  function redraw() {
    if (active() && animation === undefined) animation = requestAnimationFrame(draw);
  }

  function schedule() {
    if (!active() || pending || timer !== undefined || failedKey === key(state()) ||
        (subscribed && sceneKey === key(state()))) return;
    timer = setTimeout(async () => {
      timer = undefined;
      if (!active()) return;
      pending = true; subscribed = true; lastRequest = performance.now();
      const requested = key(state());
      try {
        await client.request('overview', { enabled: true, generation: state().generation });
      } catch (error) {
        if (active() && requested === key(state())) {
          failedKey = requested; scene = undefined; sceneKey = undefined;
          redraw(); failure(error);
        }
      } finally { pending = false; schedule(); }
    }, Math.max(0, 200 - (performance.now() - lastRequest)));
  }

  function pause() {
    clearTimeout(timer); timer = undefined;
    cancelAnimationFrame(animation); animation = undefined;
    if (subscribed) {
      subscribed = false;
      void client.request('overview', { enabled: false, generation: state().generation }).catch(() => {});
    }
  }

  function refresh() { if (active()) { overlay(); schedule(); redraw(); } }
  function setOpen(value) {
    opened = value;
    toggle.hidden = opened; panel.hidden = !opened;
    toggle.setAttribute('aria-expanded', String(opened));
    failedKey = undefined;
    if (opened) { lastRequest = -Infinity; refresh(); surface.focus({ preventScroll: true }); }
    else { pause(); toggle.focus({ preventScroll: true }); }
  }
  function navigate(x = 0.5, y = 0.5) {
    if (usable()) view.center({ generation: state().generation, revision: state().revision, x, y });
  }
  element.addEventListener('click', event => {
    if (!enabled()) return;
    const action = event.target.closest('[data-map]')?.dataset.map;
    if (action === 'toggle') setOpen(true);
    else if (action === 'close') setOpen(false);
  }, { signal: abort.signal });
  surface.addEventListener('click', event => {
    if (!plot || !usable()) return;
    if (!event.detail) { navigate(); return; }
    const rect = surface.getBoundingClientRect();
    const x = (event.clientX - rect.left - plot.x) / plot.width;
    const y = (event.clientY - rect.top - plot.y) / plot.height;
    // Include the outer stroke of cards at the content boundary and make the
    // surrounding padding target the nearest content edge.
    navigate(Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y)));
  }, { signal: abort.signal });
  element.addEventListener('keydown', event => {
    if (event.key === 'Escape' && opened) {
      event.preventDefault(); event.stopPropagation(); setOpen(false); return;
    }
    if (event.target !== surface || !active()) return;
    const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
    if (event.key !== 'Home' && !direction) return;
    event.preventDefault(); event.stopPropagation();
    if (event.key === 'Home') navigate();
    else view.pan(direction[0] * Math.max(1, Math.floor(state().columns / 4)),
      direction[1] * Math.max(1, Math.floor((state().rows - 1) / 4)));
  }, { signal: abort.signal });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause(); else refresh();
  }, { signal: abort.signal });
  const observer = new ResizeObserver(redraw);
  observer.observe(surface);

  return {
    update(data) {
      if (closed) return;
      if (sceneKey && !sceneKey.startsWith(`${state().generation}:`)) {
        scene = undefined; sceneKey = undefined; metadata = undefined;
        failedKey = undefined; lastRequest = -Infinity;
        redraw();
      }
      if (!active()) return;
      if (data.overviewBytes && key(data.overview) === key(state())) {
        const values = new Float32Array(data.overviewBytes);
        if (values[0] !== 1 || (values.length - 2) % 6 || values.length > 2 + 6 * 65536 ||
            !values.every(Number.isFinite)) throw new Error('小地圖資料無效');
        scene = values; sceneKey = key(data.overview); failedKey = undefined; redraw();
      }
      const size = `${state().columns}:${state().rows}`;
      if (size !== lastSize) { lastSize = size; redraw(); }
      if (data.overview) metadata = data.overview;
      overlay(); schedule();
    },
    refresh, redraw,
    dispose() { closed = true; pause(); abort.abort(); observer.disconnect(); scene = undefined; }
  };
}
