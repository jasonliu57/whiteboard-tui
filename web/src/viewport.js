// Gesture handling changes only the view. No terminal mouse packets are emitted.
export function attachViewport(element, { readOnly, cellSize, pan, zoom, getZoom }) {
  const controller = new AbortController();
  const pointers = new Map();
  let previous;
  let residualX = 0;
  let residualY = 0;
  const listen = (type, handler, options = {}) => element.addEventListener(type, handler,
    { ...options, signal: controller.signal, capture: true });
  const geometry = () => {
    const values = [...pointers.values()];
    const first = values[0];
    if (!first) return undefined;
    if (values.length === 1) return { ...first, distance: 0 };
    const second = values[1];
    return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2,
      distance: Math.hypot(first.x - second.x, first.y - second.y) };
  };
  const move = (x, y) => {
    const cell = cellSize();
    residualX += x / cell.width;
    residualY += y / cell.height;
    const dx = Math.trunc(residualX);
    const dy = Math.trunc(residualY);
    residualX -= dx;
    residualY -= dy;
    if (dx || dy) pan(dx, dy);
  };
  listen('pointerdown', event => {
    if (!readOnly() && event.pointerType !== 'touch' && event.button !== 1) return;
    event.preventDefault(); event.stopImmediatePropagation();
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    element.setPointerCapture(event.pointerId);
    previous = geometry();
  });
  listen('pointermove', event => {
    if (!pointers.has(event.pointerId)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const current = geometry();
    if (previous) {
      move(previous.x - current.x, previous.y - current.y);
      if (current.distance && previous.distance)
        zoom(getZoom() * current.distance / previous.distance, current);
    }
    previous = current;
  });
  const release = event => {
    if (!pointers.delete(event.pointerId)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (element.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId);
    previous = geometry();
  };
  listen('pointerup', release);
  listen('pointercancel', release);
  listen('wheel', event => {
    if (!readOnly() && !event.ctrlKey && !event.metaKey) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const unit = event.deltaMode === 1 ? cellSize().height : event.deltaMode === 2 ? element.clientHeight : 1;
    if (event.ctrlKey || event.metaKey)
      zoom(getZoom() * Math.exp(-event.deltaY * unit * 0.005), { x: event.clientX, y: event.clientY });
    else move(event.deltaX * unit, event.deltaY * unit);
  }, { passive: false });
  return {
    reset() {
      for (const id of pointers.keys()) if (element.hasPointerCapture(id)) element.releasePointerCapture(id);
      pointers.clear(); previous = undefined; residualX = residualY = 0;
    },
    dispose() { this.reset(); controller.abort(); }
  };
}
