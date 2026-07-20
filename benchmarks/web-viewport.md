# Web 視野修正量測

基準為 `f71a4f62e8df902b74a9d1a5d8c6e4f1f9b8277a`，修正版包含
`view.js` 的手勢合併與畫面保留，以及 Worker 的 `viewport` 操作。
兩版使用相同 WASM；Chromium 153.0.8010.12、主執行緒 4 倍 CPU 降速、
每組 20 次量測，桌面 1280×800、手機尺寸模擬 390×844。
量測期間未同時執行其他測試。原始輸出保存在
[web-viewport-chromium.json](baselines/web-viewport-chromium.json)。

| 指標 | 修正前 | 修正後 |
| --- | ---: | ---: |
| 每次按鈕縮放的 Worker request／ANSI frame | 2／2 | 1／1 |
| Worker 固定 resize＋pan 情境的平均 ANSI bytes | 6482.05 | 5783.00 |
| 桌面／手機尺寸 click handler 中位數（ms） | 13.6／12.4 | 0.2／0.1 |
| 桌面／手機尺寸完成繪製機會中位數（ms） | 33.6／33.2 | 66.6／66.7 |
| 桌面／手機尺寸平均主執行緒 task（ms／操作） | 25.15／21.16 | 32.28／27.17 |

合併操作可減少一半 Worker request 與核心 render 次數；固定 Worker 情境的
ANSI 傳輸量減少約 10.8%。快速手勢在送出前合併，最多一個 viewport request
等待完成，避免慢 Worker 造成無界堆積，且不丟棄任何已產生的增量 ANSI。

保留舊 DOM 畫面並等待新畫面就緒有額外成本：此環境的單次按鈕縮放完成時間與
主執行緒 task 都增加。click handler 變短主要來自延後工作，不能解讀為整體
CPU 工作減少。這次的效能改善在 Worker、傳輸與佇列；整體延遲並未改善。
主執行緒 task 包含四次暖機與量測程式，繪製機會也不等於實體螢幕顯示延遲。
手機尺寸模擬與主執行緒降速不能代表實體手機、GPU 或 Worker 效能。

重現時，分別啟動基準版與修正版的開發伺服器，再以修正版量測程式執行：

```sh
node web/scripts/benchmark-browser.mjs --url http://127.0.0.1:4173/ --samples 20 --cpu 4 --baseline --output /tmp/viewport-before.json
node web/scripts/benchmark-browser.mjs --url http://127.0.0.1:4173/ --samples 20 --cpu 4 --output /tmp/viewport-after.json
```
