# whiteboardTUI 架構

讀者：變更 ownership、runtime flow、transaction 或 module boundary 的貢獻者。

本文件說明 whiteboardTUI 2.0.0 的執行期資料流、狀態 ownership、模組邊界
與持久化流程。它是維護者新增功能、拆分模組及審查資料複製時應遵守的架構
契約，不是逐一列出所有原始檔。

本文件是目前 repository 的 canonical 架構說明。精確的持久格式與 IPC 契約
分別見 [`file-format.md`](file-format.md) 與
[`agent-protocol.md`](agent-protocol.md)；新增格式的程序 checklist 見
[`adding-card-types.md`](adding-card-types.md)。

## 設計前提

whiteboardTUI 的文件與編輯控制器只有單一執行者。原生 `NativeTui` 以 `poll()`
整合終端與 Unix-socket Agent；瀏覽器版的 Worker 逐筆處理輸入、檔案與視野訊息。
兩種平台共用 `Tui`、`App`、`BoardDocument`、格式、索引與編解碼，沒有第二份
JavaScript 白板模型。

`TuiHost` 是建构時設定的固定平台 callback table，處理存檔等 host commands
與原生 modal input、preview、status。共用 `Tui` 不讀寫路徑、不開 socket。
`NativeTui` 擁有 Agent、proposal 與目錄匯出狀態；瀏覽器 Worker 擁有輸入逾時、
文件 generation 與唯讀輸入限制。原生平台以 `whiteboard::native` 將檔案結果
提交 App；瀏覽器直接提交經過驗證的 bytes。

永久狀態只有一個 owner：`BoardDocument`。TUI mode、active editor session、
viewport、clipboard、framebuffer 與尚未接受的 Agent proposal 都是暫態投影，
不能保存另一份可能與文件分歧的資料。

## 執行期資料流

```text
terminal bytes       Unix socket bytes       standalone .tiwb file
      │                      │                         │
 InputDecoder           AgentServer              bounded decoders
      │                      │                         │
 InputEvent             AgentRequest            temporary model
      └──────────────┬───────┘                         │
                     ▼                                 │
             Tui dispatch / formats ◀─────────────────┘
                     │
              App mutation facade
                     │
                     ▼
                BoardDocument
          ┌──────────┼──────────┐
          ▼          ▼          ▼
      Card/Edge   spatial     glyph/history
        slots      indexes      revision/dirty
          └──────────┼──────────┘
                     ▼
           framebuffer / thumbnail
                     │
          terminal, text, or PNG output
```

鍵盤操作、格式內編輯、undo/redo、已接受 proposal 與 Agent commit 最後都必須
匯入 `App`。查詢可以經由 TUI 邊界唯讀存取 model 與 index，但 parser 不會取得
可變的 `Board*`，因此解析失敗不能留下半套變更。

## 狀態 ownership 與穩定 ID

`BoardDocument` 擁有：

- `Board`，包含永久的 CardId 與 EdgeId slot vectors；
- 獨立於卡片的 Unicode glyph anchors；
- card 與 edge spatial indexes，以及 router scratch；
- history、dirty state、revision 與 affected-edge scratch。

刪除卡片或連邊只會在 slot 留下 tombstone，不會壓縮或重新編號。slot index
就是穩定 ID；CardId 同時參與 z-order。世界座標不是 identity，兩張卡片位於
相同座標或完全重疊都是合法狀態。

Folder entry 與 Edge 保存的是弱 CardId 引用。目標刪除或恢復時，引用不會被
偷偷改寫；使用端必須處理 tombstone 或暫時 dormant 的狀態。

`App` 透過 document member 的 reference alias 提供格式與 TUI 存取。
這些 alias 不擁有資料；mutation 必須透過 `App` operation 或顯式 document
access 維護一致性。

## Card 格式與文字編輯

所有格式以固定順序在編譯期註冊。`CardData` 是 text、todo、CSV 與 folder
payload family 的 variant；`CardFormat` 則是一張普通 function pointer table，
提供 measure、draw、editor lifecycle、input、rebuild、undo swap 與空卡片 factory。
`create-cards` 先由 registry batch builder 建立完整暫存 vector，再由 `App` 一次
提交。專案不使用 virtual base class，也不在執行期註冊 plugin。

只有格式實作能維護自己的平行結構，例如：

- text rows 與 style spans；
- todo item metadata；
- CSV cell styles 與欄寬；
- Folder preorder depth 與 selection。

`Board` 只理解外層位置、靜態格式 ID 與 opaque variant，不應
複製格式內部規則。

文字位置使用 UTF-8 byte offset，因為 Tree-sitter 與持久化 span 都以 byte
為準。`TextByteIndex` 將 256 個 logical rows 分成一個 block，並以 Fenwick
tree 計算 prefix bytes：

- 單行內容改動只更新所在 block 的差值；
- 插入或刪除 row 等結構變更才重建 index；
- style 依 row 分組，以排序後的 boundary events canonicalize；
- edit history 只保存受影響 row 的 patch，不複製整份 style table。

## Spatial、連邊與 render

卡片空間索引是以 `64 × 32` 世界座標 cell 組成的稀疏 hash grid。每張卡片依
half-open bounds 自動加入相交 cells；移動、調整尺寸、刪除與復原會同步更新。
Query 以 generation marks 去除跨 cell 重複項目，再檢查精確 rectangle overlap。
範圍過大的 query 直接掃描永久 CardId slots，避免建立巨大的 cell traversal。

Edge 使用永久 slots 與 incident adjacency。正交線段分別進入 horizontal 與
vertical interval index。卡片改變時只查詢 incident 或 bounds 相交的 edges，
再以 generation marks 去重並更新那些 cache entries，不掃描所有連邊。router
只能在明確且有限的 rectangle 內運作。

render 每幀重建完整 framebuffer，但 terminal presenter 只輸出相對於上一幀改變的
連續 cell 區段；首次呈現與 resize 會建立完整基準。render 不會完整掃描 model：

1. card grid 與 edge interval indexes 產生可見 cards 與 segments；
2. viewport 範圍內的 glyph anchors 一併送入 framebuffer；
3. `PaintLayer + CardId` 決定重疊 ownership；
4. terminal text、screenshot PNG 與一般畫面共用同一份 framebuffer；
5. board thumbnail 直接掃描永久 geometry，但不改變 TUI state。

`FontRasterizer` 統一擁有 screenshot 與 thumbnail encoder 共用的 FreeType
face、metrics 與 lifecycle，避免各輸出路徑重複初始化或複製 font state。

`render/overview` 提供原生 thumbnail 與 Web 小地圖共用的範圍／座標投影。
卡片使用 `CardSpatial` 的既有矩形，連線使用既有折點；可選擇納入 Glyph bounds。
原生 PNG／標籤仍屬於 image rendering，Web 不連結 PNG 或 FreeType。
投影先計算整數座標差，再轉成浮點數，避免靠近 i64 邊界的小範圍丟失精度；
逆投影在 C++ 內驗證與截限，前端不以 Number 表示絕對世界座標。

## 輸入與 mutation transaction

`InputDecoder` 將 terminal framing、UTF-8、paste 與 mouse packet 轉成語意化
的 `InputEvent`。靜態 key bindings 先選出 TUI action；只有未被高優先序 global
state 消耗的 event 才會交給 active format。

每次 mutation 都遵守相同順序：

1. 將所有不可信輸入解析並驗證成暫時 typed state。
2. 以 `checked_*` helpers 與格式上限檢查座標、大小及配置量。
3. 透過 `App` 套用一次 model change。
4. 視需要更新 card/edge indexes 與 active syntax state。
5. 推入一筆 typed history record；若操作刻意不支援 undo，則標記
   `untracked_dirty`。
6. revision 只增加一次，然後 repaint。

Agent replace/delete 還必須提供呼叫端預期的 revision。commit 前任一步驟失敗
時，Board、indexes、history、dirty state 與 revision 都必須保持原樣。

## 持久化資料流

原生 `.tiwb` 是完整內嵌的 sectioned little-endian snapshot。Card 只擁有
position、StaticFormatId 與 CardData，內容交換格式由 registry 推導。
純串流 decoder 驗證大小、section CRC、EOF、counts、卡片格式、座標、關係與
Glyph Unicode scalar；卡片字串不檢查 UTF-8 合法性，未知 LanguageId 不會被拒絕。
驗證範圍見 [`file-format.md`](file-format.md)。所有格式重建及索引建立成功後
才替換 live document。

`AtomicFileWriter` 的 save 順序為：

1. 在目標 parent directory 建立 private、no-follow、exclusive temporary file。
2. 寫入完整快照，flush、fsync 並 close。
3. 原子替換 `.tiwb`，再 fsync parent directory。
4. 完成後才標記 history 儲存點並清除 untracked dirty。

若第 3 步的目錄同步失敗，檔案已發布但持久性未確認，必須保留這個錯誤差異。
載入只讀取指定的 `.tiwb`，嚴格驗證文件格式後建立暫存模型，再一次提交。
格式或內容驗證失敗時，目前文件與磁碟保持不變。

`storage/card_content.hpp` 只提供文字／Todo／CSV 編解碼。Folder export 是明確
產生副本的獨立操作。Canonical snapshot 供 Agent 分頁與磁碟交換內容核對，
涵蓋欄位見 [`agent-protocol.md`](agent-protocol.md#canonical-snapshot)。
完整持久資料由 `.tiwb` 保存。

## Agent 邊界

`AgentServer` 擁有八個固定、non-blocking client slots。每個占用中的 slot 都
獨立加入 TUI 的 `poll()` set，並且一次只承載一個 request。header/body/response
上限、五秒 inactivity deadline、word count 與 numeric bounds 都會在 typed
`AgentRequest` 進入 TUI 前完成檢查。

成功解析的 mutation 仍在單一 event loop 中逐筆 commit。socket mode 是
`0600`；清理 stale path 前會驗證 type、owner、liveness 與 inode。

server parser 沒有 Board pointer。TUI 在 bounded buffer 中建立 response，再
move 回 server。大型 card body 只計數一次，並直接串流到最終 response buffer，
不先建立中介 string copy。

## Python automation 邊界

`tools.whiteboard_automation` 擁有唯一的 Python `whiteboardctl` client、wire
response parsers、canonical snapshot parser、batch codecs 與 atomic file output。
Standalone materializer 與 whiteboard skill verifier 都依賴這個 package。

`contracts/card-formats.json` 是 format dimensions 與 SaveFormat 的 canonical
source。Generator 產生 `src/generated/card_formats.hpp` 與
`tools/whiteboard_automation/generated_card_formats.py`。

## Python renderer 邊界

`tools.textart_notes` 的 renderers 是 deterministic Python modules，沒有 Board
access。公開 JSON input 共用一個 strict decoder，只接受：

- UTF-8；
- 沒有 duplicate key 的 object root；
- finite numbers；
- 符合 geometry、payload 與 card-count 上限的內容。

renderer 只產生已驗證的 text-art drafts。`write_result` 先發布 immutable
`generations/<sha256>/` tree，再原子替換 root `manifest.json`。相同 generation
的 concurrent writers 只有在所有 bytes 一致時才會收斂。

`frozen_generation.py` 以 no-follow descriptor 開啟每一層 directory 與 payload，
freeze payload bytes，驗證 manifest、Unicode cell geometry 與 create batch。
Standalone materializer 與 skill compiler 共用這份 frozen plan。Materializer 再
透過 `tools.whiteboard_automation` 實體化到指定白板。Reader 與 writer 都使用 manifest version 2。

## Build targets 與依賴方向

Exported targets 與 direct dependency rules 為：

| Target | 擁有 | 可直接依賴 |
|---|---|---|
| `whiteboard::tree_sitter` | 隨附的 parser runtime | 無其他 CMake target |
| `whiteboard::tree_sitter_markdown` | 隨附的 Markdown block parser/scanner | 無其他 CMake target |
| `whiteboard::tree_sitter_markdown_inline` | 隨附的 Markdown inline parser/scanner | 無其他 CMake target |
| `whiteboard::tree_sitter_cpp` | 隨附的 C++ parser/scanner | 無其他 CMake target |
| `whiteboard::core` | document/model、formats、text、style、syntax | Abseil 與四個隨附 parser targets |
| `whiteboard::codec` | 純串流文件與內容編解碼 | `whiteboard::core` |
| `whiteboard::io` | 原生 persistence、Folder export 與 canonical snapshot | `whiteboard::codec` |
| `whiteboard::board_render` | 平台共用 framebuffer rendering 與概覽幾何 | `whiteboard::core` |
| `whiteboard::render` | image rendering 與 font rasterizer | `whiteboard::board_render` |
| `whiteboard::agent` | protocol parser 與 Unix-socket transport | 不依賴 Board/model target |
| `whiteboard::tui` | event loop、modes 與 orchestration | core、I/O、render、Agent |

`whiteboard_tui` 連結 TUI target；`whiteboardctl` 連結 Agent 與 I/O targets 以提供
atomic snapshot；`whiteboard-inspect` 連結 I/O target 做唯讀磁碟檢查。
TUI mode handlers 由一個 private runtime translation unit 聚合。

## 瀏覽器執行與儲存

`src/platform/web/entry.cpp` 提供有界 C ABI，`web/src/engine.js` 管理跨 WASM
邊界的 buffer 複製與生命週期。`web/src/worker.js` 擁有單一 Engine，以 Promise
佇列逐筆完成操作；`web/src/client.js` 對應請求與回覆。畫面由共用
`TerminalPresenter` 產生 ANSI，交由 xterm.js 呈現。瀏覽器 Unicode provider
由 C++ 固定字寬表在 build 時產生。

`web/src/view.js` 合併同一批視野手勢，最多維持一個尚未完成的 viewport request。
Worker 一次套用尺寸與平移後才 render；尺寸未變時保留 presenter 的增量基準。
已產生的 ANSI 必須依序消耗，不能透過丟棄回覆來合併畫面。縮放的 anchor transform
與平移量在送出前累積，尺寸與字型每批只量測／套用一次。
字型或終端尺寸改變期間，以隔離 CSS 的暫時 DOM 畫面覆蓋舊視野，等 ANSI 解析與
繪製完成再揭露新畫面；此副本只保存顯示狀態，不持有第二份 document 或 history。
文件／模式切換先停止接受新輸入、取消待送手勢並等待已送出的視野操作完成。
新建／匯入的捨棄確認使用排在已接受輸入之後的 Worker 狀態查詢，不讀取可能過期的
主執行緒 dirty 快取；尚未解碼完成的輸入會阻止替換，保留原文件與 decoder。

小地圖使用相同 Worker／Engine，沒有平行 document、空間索引或導航佇列。
WebSession 依文件 revision 快取有界幾何投影，成功 open／new 會失效；Worker
附加 generation。概覽查詢只複製 Float32 幾何，不呼叫 `TerminalPresenter`。
概覽啟用時，既有回覆附加固定四個 Float64 視野座標；平移不重新掃描文件。
`web/src/minimap.js` 保存可丟棄的顯示快照，以 Canvas 畫底圖、單一 DOM 框顯示
視野；文件變更至多每 200 ms 合併查詢一次，同時最多一個概覽請求。收合、頁面
隱藏或 dispose 會停止查詢。主題與尺寸變動使用同一份快照重畫。
點擊置中透過 `view.js` 合併進 viewport 操作；Worker 在改動視野前拒絕舊
generation／revision 的導航。文件切換一起取消尚未送出的導航。
浮層是終端 viewport 的同層元素，不改變終端尺寸，也不啟用會阻擋編輯的選單狀態。

唯讀模式只改變輸入接線：鍵盤、貼上和卡片滑鼠事件不送入控制器；手勢只呼叫
viewport 平移或調整字體與終端尺寸。同一份文件、繪圖和索引繼續使用。
模式切換會清除不完整輸入與互動狀態，輸入 epoch 防止舊事件跨越切換。

完整 `.tiwb` 快照透過 Blob 下載或寫入 IndexedDB。草稿寫入在 transaction
內比較版本，防止其他分頁被覆寫；成功後只在文件 generation 與 revision
仍相符時標記儲存點。下載不清除 dirty。原生 `AtomicFileWriter` 不參與瀏覽器
流程，瀏覽器 target 不連結 Agent、原生 I/O 或 PNG／FreeType。

`web/` 產出同一來源的嵌入套件與獨立靜態頁面，外部網站只提供容器、初始文件
及託管設定。API、限制與操作流程見原始碼目錄中的 `web/README.md`。

## 模組拆分判準

拆分檔案或 target 時，依序檢查：

1. **誰擁有資料**：每份永久可變資料只能有一個 owner；其他模組取得 reference、
   view、ID 或 immutable snapshot。
2. **mutation 往哪裡走**：所有變更必須匯入 `App`／`BoardDocument` transaction
   boundary，不能由 parser、renderer 或 transport 旁路寫入。
3. **依賴是否單向**：格式與 I/O 可以依賴 core contract；core 不應反向依賴 TUI、
   terminal 或 Agent transport。
4. **資料是否真的需要複製**：優先使用 caller-owned scratch、`string_view`、move、
   stable ID 與局部 patch。只有跨 transaction lifetime 或 immutable publication
   才建立 owned copy。
5. **暫態與永久狀態是否混合**：viewport、selection、draft、active syntax session
   不應滲入持久 model；Card/Edge/Glyph identity 也不應藏在 mode-local cache。
6. **失敗是否原子**：解析、驗證與配置先在 temporary state 完成，commit 後才更新
   index、history、revision 與 dirty。
7. **效能成本由誰負責**：高頻 query 的 scratch 由呼叫端重用；不要在 helper 內
   隱藏全量 scan、排序或大型配置。

若拆分只是把同一份狀態複製到另一個 class，或新增雙向 callback 讓 ownership
更難判斷，就不是真正的模組化。

## 架構變更檢查表

提交架構相關變更前，至少確認：

- 沒有新增平行 Board、Card、Edge、Glyph、history 或 revision owner；
- 新 mutation 具備完整的 validate／commit／index refresh／history／dirty 流程；
- tombstone、重疊座標與 stable ID 語意仍成立；
- parser、Agent 與檔案 input 的 byte/count/geometry 上限仍在配置前檢查；
- render 或 query hot path 沒有新增全 model scan、重複排序或不必要 payload copy；
- 單檔發布前失敗保留原檔，發布後的同步失敗有明確錯誤資訊；
- public headers 沒有洩漏 private storage、TUI 或格式實作；
- `whiteboard::tree_sitter_cpp`、`core`、`io`、`render`、`agent`、`tui` 的依賴方向
  沒有形成 cycle；
- 對應 unit、integration、install-package 與 sanitizer tests 已更新。
