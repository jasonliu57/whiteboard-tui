# Web 小地圖量測

同一份 500 卡片文件、20 次量測；瀏覽器為 Chromium 153.0.8010.12，
主執行緒 4 倍 CPU 降速。桌面為 1280×800，手機尺寸模擬為 390×844。
量測期間未同時執行編譯或測試。[結果與環境資訊](baselines/web-minimap.json)
保留 Node/WASM 結果與瀏覽器的小地圖指標。

| 平移指標 | 收合 | 展開 |
| --- | ---: | ---: |
| 桌面完成繪製機會中位數／p95（ms） | 50.6／51.6 | 51.0／53.6 |
| 手機尺寸完成繪製機會中位數／p95（ms） | 50.1／50.6 | 50.1／50.3 |
| 桌面平均主執行緒 task（ms／操作） | 17.82 | 17.83 |
| 手機尺寸平均主執行緒 task（ms／操作） | 11.23 | 10.90 |
| 每次平移的 ANSI frame | 1 | 1 |
| 平移期間概覽查詢／底圖繪製 | 0／0 | 0／0 |

首次展開取得 12,008 bytes 的概覽，沒有 ANSI frame；往返約 1.0–1.1 ms。
Node/WASM 的概覽重建中位數 0.269 ms、快取複製 0.0018 ms、視野投影
0.0015 ms。重建計時不包含為失效快取而執行的文件載入，也不包含 Canvas 繪製。
Node fixture 為單列排列；瀏覽器 fixture 為 25×20 卡片排列，兩者用途不同。

平移只更新固定大小的視野投影與 DOM 框，因此不隨卡片數重新掃描／繪製底圖。
新增、移動、編輯、刪除與 undo／redo 仍需在 revision 改變後重建概覽；
這部分使用最多每 200 ms 一次的合併查詢，不能由平移結果推論為零成本。
收合／展開的微小時間差包含量測波動，不能據此宣稱展開更快。

繪製機會不是實體螢幕延遲；主執行緒 task 包含四次暖機及量測程式。
CPU 降速不套用至 Worker，手機尺寸模擬也不能代替實體手機驗證。

重現：先依 `web/README.md` 建置 WASM 與 Web 套件並啟動開發伺服器，再執行：

```sh
npm run benchmark --prefix web -- --cards 500 --samples 20 --output /tmp/minimap-wasm.json
npm run benchmark:browser --prefix web -- --samples 20 --cpu 4 --minimap --output /tmp/minimap-browser.json
```
