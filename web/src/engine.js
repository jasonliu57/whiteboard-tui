const encoder = new TextEncoder();
const decoder = new TextDecoder();
export const MAX_FILE_BYTES = 32 * 1024 * 1024;
export const MAX_INPUT_BYTES = 1024 * 1024;

// The same adapter runs in the browser Worker and in interoperability tests.
export class Engine {
  constructor(module) { this.module = module; }

  check(ok) {
    if (ok) return;
    const heap = this.module.HEAPU8;
    const start = this.module._wb_error();
    const end = heap.indexOf(0, start);
    throw new Error(decoder.decode(heap.subarray(start, end)));
  }

  withBytes(bytes, call) {
    const pointer = this.module._malloc(Math.max(1, bytes.byteLength));
    if (!pointer) throw new Error('白板記憶體不足');
    try {
      this.module.HEAPU8.set(bytes, pointer);
      this.check(call(pointer, bytes.byteLength));
    } finally { this.module._free(pointer); }
  }

  result() {
    const start = this.module._wb_result();
    return this.module.HEAPU8.slice(start, start + this.module._wb_result_size());
  }

  create(columns, rows) { this.check(this.module._wb_create(columns, rows)); }
  destroy() { this.module._wb_destroy(); }
  resetInput() { this.check(this.module._wb_reset_input()); }
  pendingInput() { return this.module._wb_pending_input(); }
  resize(columns, rows) { this.check(this.module._wb_resize(columns, rows)); }
  pan(dx, dy) { this.check(this.module._wb_pan(dx, dy)); }
  overview() { this.check(this.module._wb_overview()); return new Float32Array(this.result().buffer); }
  overviewView() {
    this.check(this.module._wb_overview_view());
    const bytes = this.result();
    return bytes.length ? [...new Float64Array(bytes.buffer)] : null;
  }
  centerOverview(x, y) { this.check(this.module._wb_overview_center(x, y)); }

  input(text, flush = false) {
    const bytes = encoder.encode(text);
    if (bytes.byteLength > MAX_INPUT_BYTES) throw new Error('單次輸入上限為 1 MiB');
    this.withBytes(bytes, (p, n) => this.module._wb_input(p, n, Number(flush)));
  }

  open(bytes) {
    if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_FILE_BYTES)
      throw new Error('請選擇不超過 32 MiB 的 .tiwb 檔案');
    this.withBytes(bytes, (p, n) => this.module._wb_open(p, n));
  }

  export() { this.check(this.module._wb_export()); return this.result(); }
  frame() { this.check(this.module._wb_frame()); return this.result(); }
  state() { this.check(this.module._wb_state()); return JSON.parse(decoder.decode(this.result())); }
  markSaved(revision) {
    this.withBytes(encoder.encode(revision), (p, n) => this.module._wb_mark_saved(p, n));
  }
}
