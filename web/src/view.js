// Coordinates transient viewport requests and xterm presentation. Document state
// stays in the Worker; every returned ANSI delta is still consumed in order.
export function attachView({ terminal, element, viewport, dimensions, client, enabled, state, labels, failure }) {
  let closed = false;
  let scheduled;
  let active;
  let fitPending = false;
  let zoom = 1;
  let appliedZoom = 1;
  let transform = { scale: 1, x: 0, y: 0 };
  let dx = 0, dy = 0;
  let center;
  let remainderX = 0, remainderY = 0;
  let cover;
  let written = Promise.resolve();
  const abort = new AbortController();

  const cellSize = () => {
    const screen = element.querySelector('.xterm-screen');
    return { width: (screen?.clientWidth || element.clientWidth) / terminal.cols,
      height: (screen?.clientHeight || element.clientHeight) / terminal.rows };
  };
  const label = () => labels.forEach(output => { output.textContent = `${Math.round(zoom * 100)}%`; });

  function holdFrame() {
    if (cover) return;
    const screen = element.querySelector('.xterm-screen');
    const rows = screen?.querySelector('.xterm-rows');
    if (!rows) return;
    cover = document.createElement('div');
    cover.className = 'tiwb-frame-cover';
    cover.setAttribute('aria-hidden', 'true');
    cover.inert = true;
    cover.style.background = getComputedStyle(element.querySelector('.xterm-viewport')).backgroundColor;
    // Isolate the frozen renderer's CSS: live font/theme changes must not resize
    // the cover, and copied xterm selectors must not override the live terminal.
    const shadow = cover.attachShadow({ mode: 'open' });
    const wrapper = document.createElement('div');
    wrapper.className = element.querySelector('.xterm').className;
    const frozen = document.createElement('div');
    frozen.className = 'xterm-screen';
    frozen.style.cssText = screen.style.cssText;
    for (const style of screen.querySelectorAll('style')) frozen.append(style.cloneNode(true));
    frozen.append(rows.cloneNode(true));
    wrapper.append(frozen);
    shadow.append(wrapper);
    viewport.append(cover);
    element.dataset.presenting = 'true';
  }

  function reveal() {
    delete element.dataset.presenting;
    cover?.remove(); cover = undefined;
  }

  // Dispose must also release waits if xterm drops a queued write callback.
  function waitFor(register) {
    return new Promise(resolve => {
      if (closed) { resolve(); return; }
      const finish = () => { abort.signal.removeEventListener('abort', finish); resolve(); };
      abort.signal.addEventListener('abort', finish, { once: true });
      register(finish);
    });
  }

  async function paint() {
    await waitFor(done => written.then(done));
    if (closed) return;
    await waitFor(done => {
      // Queue xterm first, then reveal after its renderer had a paint opportunity.
      // This also settles offscreen embeds, whose onRender event is suspended.
      if (cover) terminal.refresh(0, terminal.rows - 1);
      requestAnimationFrame(done);
    });
  }

  async function apply(targetZoom, motion, panX, panY, targetCenter) {
    // Drain older writes before taking a visual snapshot or changing geometry.
    await waitFor(done => written.then(done));
    if (closed) return;
    const before = cellSize();
    const fontSize = Math.round(16 * targetZoom * 10) / 10;
    const changedFont = fontSize !== terminal.options.fontSize;
    if (changedFont) {
      holdFrame();
      terminal.options.fontSize = fontSize;
    }
    appliedZoom = targetZoom;
    const size = dimensions();
    if (!size) { await paint(); return; }
    if (size.columns !== terminal.cols || size.rows !== terminal.rows) {
      holdFrame();
      terminal.resize(size.columns, size.rows);
    }
    if (!targetCenter && (motion.x || motion.y)) {
      const after = cellSize();
      // Compose event anchors in screen space before measuring once. Calibrate
      // the effective anchor to xterm's actual (rounded) cell dimensions. A zoom
      // out/in at different anchors can also leave a pure translation.
      if (Math.abs(1 - motion.scale) > 1e-8) {
        remainderX += motion.x / (1 - motion.scale) * (1 / before.width - 1 / after.width);
        remainderY += motion.y / (1 - motion.scale) * (1 / before.height - 1 / after.height);
      } else {
        remainderX -= motion.x / after.width;
        remainderY -= motion.y / after.height;
      }
      const shiftX = Math.round(remainderX), shiftY = Math.round(remainderY);
      remainderX -= shiftX; remainderY -= shiftY;
      panX += shiftX; panY += shiftY;
    }
    const current = state();
    if (targetCenter && targetCenter.generation !== current.generation) return;
    let rejected = false;
    if (size.columns !== current.columns || size.rows !== current.rows || panX || panY || targetCenter) {
      const result = await client.request('viewport', { ...size, dx: panX, dy: panY,
        generation: current.generation, ...(targetCenter ? { center: targetCenter } : {}) });
      rejected = result.navigationRejected;
      if (rejected && (size.columns !== result.state.columns || size.rows !== result.state.rows)) {
        // The Worker rejects stale navigation before changing anything. Keep an
        // independently changed terminal size in sync even when the click loses
        // its race with an edit; never reveal ANSI for mismatched dimensions.
        await client.request('viewport', { ...size, generation: result.state.generation, dx: 0, dy: 0 });
      }
    }
    if (!closed) await paint();
    if (rejected) throw new Error('小地圖正在更新，請再次選擇位置');
  }

  function flush() {
    scheduled = undefined;
    if (closed || !enabled()) return;
    if (!center && !dx && !dy && zoom === appliedZoom && !transform.x && !transform.y) {
      if (!fitPending) return;
      fitPending = false;
      const size = dimensions();
      if (!size || (size.columns === terminal.cols && size.rows === terminal.rows)) return;
    }
    const target = zoom, motion = transform, panX = dx, panY = dy, targetCenter = center;
    center = undefined;
    dx = dy = 0; transform = { scale: 1, x: 0, y: 0 }; fitPending = false;
    active = apply(target, motion, panX, panY, targetCenter).catch(error => {
      if (!closed) failure(error);
    }).finally(() => {
      reveal();
      active = undefined;
      // paint() already waited for the next animation frame. Start the next
      // accumulated batch here, without adding an idle frame to every gesture.
      if (center || fitPending || dx || dy || zoom !== appliedZoom || transform.x || transform.y) flush();
    });
  }

  function schedule(immediate = false) {
    if (closed || active || scheduled !== undefined || !enabled()) return;
    if (immediate) {
      // A discrete toolbar click need not wait an extra frame. Still merge all
      // changes in this task and keep the same one-request backpressure.
      scheduled = null;
      queueMicrotask(() => { if (scheduled === null) flush(); });
    } else scheduled = requestAnimationFrame(flush);
  }

  // A frozen frame uses the previous mouse geometry. Allow keyboard editing and
  // viewport gestures, but block new card mouse interactions until it appears.
  // Mouseup must still finish a drag that began before the geometry changed.
  for (const type of ['mousedown', 'mousemove', 'wheel']) {
    element.addEventListener(type, event => {
      if (cover) { event.preventDefault(); event.stopImmediatePropagation(); }
    }, { capture: true, passive: false, signal: abort.signal });
  }

  return {
    write(bytes) {
      let finish;
      const parsed = new Promise(resolve => { finish = resolve; });
      terminal.write(bytes, finish);
      written = parsed;
    },
    cellSize,
    getZoom: () => zoom,
    center(target) {
      if (closed || !enabled()) return;
      // Finish the accepted operation, replacing only gestures not yet sent.
      center = target; dx = dy = 0;
      transform = { scale: 1, x: 0, y: 0 };
      zoom = appliedZoom; remainderX = remainderY = 0; label(); schedule(true);
    },
    fit() { if (!closed && enabled()) { fitPending = true; schedule(); } },
    pan(x, y) {
      if (closed || !enabled()) return;
      dx += x; dy += y; schedule();
    },
    zoom(next, point, immediate = false) {
      if (closed || !enabled() || !Number.isFinite(next)) return;
      next = Math.max(0.5, Math.min(2, next));
      if (Math.abs(next - zoom) < 0.002) return;
      const rect = element.getBoundingClientRect();
      const anchor = point ? { x: point.x - rect.left, y: point.y - rect.top }
        : { x: rect.width / 2, y: rect.height / 2 };
      const ratio = next / zoom;
      transform = { scale: transform.scale * ratio,
        x: ratio * transform.x + (1 - ratio) * anchor.x,
        y: ratio * transform.y + (1 - ratio) * anchor.y };
      zoom = next; label(); schedule(immediate);
    },
    async settle() {
      // Called with input/gestures blocked before a document or mode transition.
      cancelAnimationFrame(scheduled); scheduled = undefined;
      center = undefined;
      dx = dy = 0; transform = { scale: 1, x: 0, y: 0 }; fitPending = false;
      await active;
      zoom = appliedZoom; remainderX = remainderY = 0; label();
    },
    dispose() {
      closed = true;
      cancelAnimationFrame(scheduled);
      abort.abort(); reveal();
    }
  };
}
