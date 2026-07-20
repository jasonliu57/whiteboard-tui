# 繁體中文文件

專案簡介與最短建置方式位於根目錄 [`README.md`](../README.md)。本目錄將
任務導向教學、參考契約、設計解釋與貢獻流程分開，使每項事實只有一份 canonical
owner。

## 使用 whiteboardTUI

- [`user-guide.md`](user-guide.md)：概念與完整 TUI 工作流程；
- [`keybindings.md`](keybindings.md)：各 context 的完整輸入參考；
- [`automation.md`](automation.md)：`whiteboardctl`、共用 Python automation 與
  Markdown 白板 skill。

- 原始碼目錄中的 `web/README.md`：瀏覽器版建置、編輯／唯讀、檔案、草稿與嵌入套件。

## 建置與貢獻

- [`building.md`](building.md)：相依套件、CMake 選項、建置、安裝與 Python
  工具的 source-tree 執行方式；
- [`testing.md`](testing.md)：CTest、sanitizer、generated contracts、PTY、
  benchmark 與套件驗證；
- [`adding-card-types.md`](adding-card-types.md)：新增 compile-time Card 格式的
  實作檢查表；

## 理解契約

- [`architecture.md`](architecture.md)：執行期資料流、ownership、transaction 與
  dependency direction；
- [`file-format.md`](file-format.md)：獨立 `.tiwb`、內容 codecs 與 renderer
  manifest 的 normative encoding；
- [`agent-protocol.md`](agent-protocol.md)：本機 socket framing 與 mutation
  semantics 的 normative contract。

## 專案政策

- [`third-party-notices.md`](third-party-notices.md)。
