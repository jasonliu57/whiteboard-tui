export class DraftStore {
  constructor(key) { this.key = key; this.version = null; }

  async open() {
    this.db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('whiteboard-tui', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('drafts');
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('請關閉其他白板頁面後重試草稿儲存'));
      request.onsuccess = () => resolve(request.result);
    });
    this.db.onversionchange = () => this.db.close();
    return this.read();
  }

  read() {
    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction('drafts', 'readonly');
      const request = transaction.objectStore('drafts').get(this.key);
      transaction.oncomplete = () => {
        const record = request.result;
        this.version = record?.version ?? null;
        resolve(record?.bytes ? record : undefined);
      };
      transaction.onabort = () => reject(transaction.error);
    });
  }

  write(record) {
    return new Promise((resolve, reject) => {
      if (!this.db) { reject(new Error('本機草稿尚未啟用')); return; }
      const transaction = this.db.transaction('drafts', 'readwrite');
      const store = transaction.objectStore('drafts');
      const request = store.get(this.key);
      const version = crypto.randomUUID();
      let conflict;
      request.onsuccess = () => {
        if ((request.result?.version ?? null) !== this.version) {
          conflict = new Error('另一個頁面已更新草稿。請先匯出目前文件，再重新開啟頁面。');
          transaction.abort();
          return;
        }
        store.put({ ...record, version, updatedAt: Date.now() }, this.key);
      };
      transaction.oncomplete = () => { this.version = version; resolve(); };
      transaction.onabort = () => reject(conflict || transaction.error || new Error('草稿儲存失敗'));
    });
  }

  // Keep a version tombstone so a stale tab cannot resurrect a cleared draft.
  // The document bytes and filename are removed; other draft keys are untouched.
  clear() { return this.write({}); }

  close() { this.db?.close(); }
}
