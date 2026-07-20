export class WorkerClient {
  constructor(url, update, failure) {
    this.worker = new Worker(url, { type: 'module', name: 'whiteboard' });
    this.pending = new Map();
    this.nextId = 1;
    this.epoch = 0;
    this.closed = false;
    this.worker.onmessage = ({ data }) => {
      if (data.epoch !== undefined) this.epoch = data.epoch;
      const request = this.pending.get(data.id);
      if (request) this.pending.delete(data.id);
      if (data.error) {
        const error = new Error(data.error);
        if (request) request.reject(error); else failure(error);
        return;
      }
      if (data.state) {
        try { update(data); } catch (error) { failure(error); }
      }
      request?.resolve(data);
    };
    this.worker.onerror = (event) => {
      const error = new Error(event.message || '白板執行環境發生錯誤');
      this.dispose(error);
      failure(error);
    };
    this.worker.onmessageerror = () => {
      const error = new Error('白板訊息無法解析');
      this.dispose(error);
      failure(error);
    };
  }

  request(type, payload = {}, transfer = []) {
    if (this.closed) return Promise.reject(new Error('白板已關閉'));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try { this.worker.postMessage({ id, type, payload }, transfer); }
      catch (error) { this.pending.delete(id); reject(error); }
    });
  }

  input(text) { return this.request('input', { text, epoch: this.epoch }); }

  dispose(error = new Error('白板已關閉')) {
    if (this.closed) return;
    this.closed = true;
    this.worker.terminate();
    for (const request of this.pending.values()) request.reject(error);
    this.pending.clear();
  }
}
