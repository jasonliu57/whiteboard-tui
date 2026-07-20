# whiteboardTUI 瀏覽器版

瀏覽器版使用與原生程式相同的 C++ 文件、編輯控制器、Unicode 字寬契約與
`.tiwb` format 11 編解碼。WASM 在單一 Web Worker 中執行，xterm.js 負責畫面
與編輯輸入。所有檔案處理都在使用者裝置上進行。

本目錄同時產生可嵌入套件與完整靜態頁面，不依賴 Astro、個人網站、Agent 或
後端服務。原生版的 CMake 建置不需要 Node、npm 或 Emscripten。

本專案自有程式碼採 MIT License，完整條款隨套件提供於 `dist/LICENSE`。
第三方程式碼與字型維持各自授權，聲明與全文隨產物提供於
`dist/THIRD_PARTY_NOTICES.md` 與 `dist/licenses/`。

## 建置

需要 CMake 4.3 以上、Ninja、Node 22 以上與已啟用的 Emscripten SDK。
驗證的工具鏈為 Emscripten 6.0.0。從 repository 根目錄執行：

```sh
emcmake cmake -S . -B build/web -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
  -DWHITEBOARD_WARNINGS_AS_ERRORS=ON
cmake --build build/web --target whiteboard_web -j2
npm ci --prefix web
npm run build --prefix web
npm run dev --prefix web
```

`emcmake` 應來自已啟用的 SDK。CMake 下載並核對固定版本 Abseil 的 SHA-256，
以同一個 WASM 工具鏈建置；Tree-sitter 來源已在 repository 中。
可用 CMake 的 `FETCHCONTENT_SOURCE_DIR_ABSEIL` 明確指定離線來源目錄。

預覽位址為 `http://127.0.0.1:4173/`。`scripts/serve.mjs` 是開發預覽工具，
正式網站只需部署 `web/dist/` 中的靜態檔案。

若 WASM 使用不同的 build directory，將含有 `whiteboard.mjs`、
`whiteboard.wasm` 與 `licenses/` 的產物目錄傳給前端建置：

```sh
npm run build --prefix web -- /absolute/path/to/build/web
```

## 使用

- **編輯**：使用現有白板快捷鍵；`n` 建立筆記，Enter 編輯、Esc 離開。
  工具列的操作說明提供主要按鍵。文件選單提供新建、匯入、匯出與保存，
  Ctrl-S 儲存本機草稿。
- **版面**：48 px 單行頂列，其餘空間為白板與原有 TUI 狀態列。選單與說明
  浮在白板上方；容器寬度不足 720 px 時將顯示設定收進選單。獨立頁面使用
  `100dvh` 與裝置安全區，支援瀏覽器全螢幕。嵌入版只使用呼叫端容器。
  終端在字型就緒後量測；原稿／草稿與符合容器尺寸的首幀繪製完成後才顯示，
  載入期間保留版面大小。字型下載失敗時使用備用字型，不阻止白板啟動。
- **配色**：日間採 WebTUI basic light，夜間採 Catppuccin Mocha。CSS 與 ANSI
  色盤同步，切換不重建 Worker、不修改文件或 undo history。尚未手動選擇時
  跟隨系統；點擊日／夜按鈕後固定使用該配色，獨立頁面會記住選擇。
- **唯讀**：與編輯共用文件與畫面，只接收視野平移與縮放。
  拖曳／滾輪平移、雙指或 Ctrl-滾輪縮放；其他白板輸入不轉送。
  觸控裝置預設唯讀，使用者可以切換模式。
- **匯入**：選擇或拖入一個 `.tiwb`。先驗證完整暫存文件，再替換目前文件；
  失敗保留文件與 history。有未儲存修改時，先確認是否捨棄。
  新建與匯入會先等待已接受的輸入取得最新狀態；貼上或按鍵序列尚未接收完整時，
  保留目前文件並提示完成輸入後再試。
- **匯出**：下載完整 `.tiwb`，與原生版互通。發起下載不會將文件標為已儲存。
- **小地圖**：右下角「地圖」展開內容概覽，顯示卡片、既有連線、Glyph 占位與
  目前視野框。點按跳轉，維持縮放；地圖上的 Home 可置中。
  地圖取得焦點時，方向鍵每次平移約四分之一視野，Esc 收合並返回開啟按鈕。
  唯讀與編輯模式皆可使用，展開不阻擋卡片編輯；空文件顯示空白地圖。
  主題跟隨白板，窄容器會縮小或捲動小地圖浮層，不改變終端欄列數。
- **草稿**：IndexedDB 儲存完整 `.tiwb` 與名稱，transaction 完成後才確認儲存。
  只有按儲存草稿、Ctrl-S 或呼叫 `saveDraft()` 才保存，重新開頁時恢復。
  停止輸入、切換分頁與離開頁面都不會自動儲存。其他分頁已更新相同草稿時
  拒絕覆寫，使用者仍可匯出目前文件。
- **恢復原稿**：有初始文件時，頂列顯示 ↺。點擊後直接恢復原稿並清除此文件
  的本機草稿，不顯示確認，也不保留舊 undo history；需要保留修改請先匯出。
  恢復會等待已接受的儲存完成，其他文件的草稿不受影響。若儲存不可用或其他
  分頁已更新草稿，保留其資料並明確回報未清除，不會靜默覆蓋。

草稿屬於同一個瀏覽器與網站來源；清除網站資料會移除草稿。可攜式文件與備份
使用匯出的 `.tiwb`。草稿不包含 undo history、viewport 或編輯 session。
清除草稿後僅保留不含文件內容的版本標記，防止舊分頁再次寫回已清除的草稿。

網站公開白板可以使用：

```text
/whiteboard/?file=boards/example.tiwb&mode=read
```

`file` 只接受同來源的公開 URL；`mode` 可為 `read` 或 `edit`。公開文件與訪客
草稿各自獨立；瀏覽器不會把訪客修改寫回網站資產。唯讀是互動模式，公開檔案
仍能下載。有草稿時優先恢復草稿，↺ 回到此次開頁時取得的原稿；若更新原稿而
不想沿用舊草稿，可改用新的公開檔名／draftKey。

## 嵌入其他網站

建置後執行 `npm pack ./web --pack-destination build/web`，即可取得包含完整
執行資產的套件。安裝指定版本的套件，匯入 CSS，並將套件 `dist/runtime/`
整個目錄複製到網站的公開資產目錄。

```js
import { mountWhiteboard } from 'whiteboard-tui-web';
import 'whiteboard-tui-web/style.css';

const board = await mountWhiteboard(document.querySelector('#board'), {
  assetBaseUrl: '/assets/whiteboard/2.2.1/',
  readOnly: true,
  appearance: 'system',
  backLink: { href: '/', label: '返回網站' },
  draftKey: 'example-board',
});

// bytes 是呼叫端取得的完整 .tiwb Uint8Array。
await board.open(bytes, 'example.tiwb');
const exported = await board.export();
await board.setReadOnly(false);
board.setAppearance('light');

// 路由離開或元件卸載時，釋放 Worker、終端與事件監聽器。
board.dispose();
```

容器必須有可見的寬度與高度，例如 `height: 80dvh`。`assetBaseUrl` 必須以 `/`
結尾，指向同一版本的 `whiteboard.worker.js`、`whiteboard.mjs` 與
`whiteboard.wasm`。直接載入獨立 bundle 時，預設使用該 bundle 旁的 `runtime/`。

`mountWhiteboard` 回傳的 API 包含 `open`、`export`、`newDocument`、`saveDraft`、
`resetToOriginal`、`setReadOnly`、`setAppearance`、`getAppearance`、`getState`、`dispose`。完整型別見
[`src/index.d.ts`](src/index.d.ts)。`open` 與 `newDocument` 在使用者取消替換時
回傳 `false`，解析失敗則 reject。

可設定 `document`／`name` 作為原稿，套件保留自己的 bytes 副本；之後的匯入、
新建、草稿恢復與呼叫端修改不會改變恢復目標。沒有原稿時隱藏 ↺，呼叫
`resetToOriginal()` 會 reject。`onChange`／`onError` 接收通知，
`confirmDiscard` 接管替換確認。`drafts: false` 關閉草稿功能，
`restoreDraft: false` 關閉啟動恢復，直接顯示原稿。損毀草稿會回報錯誤並保留
原稿（無原稿則保留空白文件），不刪除保存的資料。多個獨立文件應使用不同
`draftKey`。世界座標與 revision 在 JavaScript API 中使用十進位字串，避免
64-bit 整數精度損失。

`appearance` 接受 `light`、`dark`、`system`；`onAppearanceChange` 回報使用者
偏好及實際配色，宿主可將它與網站設定同步。嵌入套件不讀寫宿主的偏好儲存。
獨立頁面以 `whiteboard-appearance` 儲存選擇。`theme` 可明確覆寫 xterm 色盤。
WebTUI 元件與主題只作用於 `.tiwb-app`，不套用全頁 reset。套件內含字型；
若透過 bundler 嵌入，須處理 CSS 的 `fonts/` URL。直接複製 bundle 時，保留
同層的 `fonts/`。可由 `whiteboard-tui-web/build.json` 讀取版本並建立資產 URL。

## 託管設定與資源限制

- 以 HTTPS 或本機 HTTP 提供靜態資產，`.wasm` MIME 為 `application/wasm`。
- CSP 需要 `script-src 'self' 'wasm-unsafe-eval'` 與 `worker-src 'self'`。
  xterm.js 會建立動態樣式，需要白板頁允許 inline styles。可參考
  [`standalone/_headers`](standalone/_headers)，嵌入站點自行設定白板頁標頭。
- JS、Worker、WASM 與 CSS 必須一起部署並使用一致版本；版本化 URL 可設定
  immutable cache。獨立頁面與發布清單應採可更新的快取政策。
- 使用單執行緒 WASM，不需要 SharedArrayBuffer、COOP／COEP 或 WebSocket。
- 檔案匯入／匯出上限 32 MiB；decoder 估算配置預算 128 MiB；WASM 記憶體
  初始 64 MiB、成長上限 512 MiB。配置預算不等於整個頁面的實際記憶體使用量。
- 單次及尚未完成的終端輸入上限 1 MiB；畫面最多 500 欄、250 列及 50,000 格。
- 縮放為 50%–200%。套件包含 JetBrains Mono Latin 與框線／方塊字元子集，
  中文由裝置上的等寬中文字型顯示。可透過 `fontFamily` 同時指定工具列與終端字型。
  終端行高為 1.0，減少框線的垂直接縫；首次量測前會等待兩份字型子集載入。
  框線子集僅 2.8 KiB，來源與重製方式見 [字型子集說明](fonts/README.md)。
  終端量測與顯示使用一致的 CJK 標點間距，`「」『』` 沿用共用的兩格字寬契約。
- 小地圖依內容範圍投影，平移只更新視野框；文件修改最多每 200 ms 更新一次底圖。
  收合或頁面隱藏時停止概覽更新。每份概覽最多 65,536 個幾何元素，超過時顯示
  「內容過多，小地圖暫不可用」，完整白板仍可正常操作。極遠、極小的物件會共用
  小地圖像素；概覽適合粗略導航，精細定位仍用白板的平移／縮放。
- 原生 Agent、Folder 實體目錄匯出、PNG 匯出不屬於瀏覽器入口。

## 驗證與 benchmark

先以原生 CMake 建置啟用 `BUILD_TESTING` 的 `whiteboard_web_fixture` 與
`whiteboard-inspect`，再執行：

```sh
WHITEBOARD_INSPECT=/absolute/path/to/whiteboard-inspect \
WHITEBOARD_FIXTURE=/absolute/path/to/whiteboard_web_fixture \
  npm test --prefix web
node web/node_modules/@playwright/test/cli.js install chromium
npm run test:browser --prefix web
npm run benchmark --prefix web -- --cards 500 --samples 20
# 先啟動 npm run dev --prefix web；Chromium 以 4 倍 CPU 降速測量互動。
npm run benchmark:browser --prefix web -- --samples 20 --cpu 4
npm run benchmark:browser --prefix web -- --samples 20 --cpu 4 --minimap
```

互通測試預設使用 `build/standalone/` 內明確命名的原生測試產物，可透過上述
變數指定其他建置位置。Node 測試與 benchmark 使用 `build/web/web/` 的 WASM。

測試涵蓋七種格式、樣式、tombstone、連線、Unicode、檔案驗證、undo／redo、
儲存版本檢查、輸入上限、桌面編輯、草稿恢復與衝突、手機觸控唯讀、
主題切換、容器隔離、浮層焦點與全螢幕；首幀測試包含字型延遲／失敗、
載入中改變尺寸，以及文章草稿恢復與原稿重設。
Playwright 以 Chromium 模擬觸控與尺寸；實體 iOS／Android 裝置仍應另行驗證。
另涵蓋不同縮放與備用字型下的標點實際寬度、延遲 Worker 回覆時的舊畫面保留、
視野事件合併、縮放定位、文件切換的輸入競態，以及未完成貼上的保留。
小地圖測試包含 C++／WASM 共用投影、極端 i64 座標、Glyph、輸出上限、舊回覆、
文件切換、鍵盤／觸控、編輯與 undo／redo，以及平移不重取或重畫底圖。

WASM benchmark 測量 Node 中的核心初始化、編解碼、重繪與平移；
`wasm_memory_capacity_bytes` 是線性記憶體容量，不是手機峰值 RAM 或 UI FPS。
可用 `--output FILE` 保存 JSON。原生 benchmark 保留在
[`../benchmarks/`](../benchmarks/)。

瀏覽器 benchmark 測量桌面／手機選單事件處理、觸控放開至 click 的時間、
Esc 首個變動畫面與輸入／匯出的 frame 次數。`viewport` 結果另包含縮放的
request／frame 次數、ANSI bytes、完成時的繪製機會、事件處理時間與平均主執行緒
task 耗時；`worker.viewport` 在相同核心比較分開 resize／pan 與合併操作。
這次修正的實測結果與畫面保留成本見 [視野量測紀錄](../benchmarks/web-viewport.md)。
主執行緒 task 耗時包含四次暖機與量測程式。以 `--baseline` 可測量尚未支援
合併操作的舊版頁面，搭配 `--url`／`--output` 保存比較結果。
兩次 animation callback 間隔
只代表瀏覽器繪製機會，不是實體螢幕顯示延遲。`--cpu` 只降低頁面主執行緒
速度，不代表手機的 CPU、GPU 或 Worker 效能。

`--minimap` 使用 500 張卡片比較收合／展開時的平移耗時、主執行緒 task、
ANSI frame、概覽請求與底圖繪製次數，另記錄首次概覽傳輸量與往返時間。
Node benchmark 的 `overview_build` 在計時外重新載入文件以失效快取，
`overview_cached` 測量快取複製，`overview_view` 測量目前視野的固定大小投影。
實測資料與限制見 [小地圖量測紀錄](../benchmarks/web-minimap.md)。
