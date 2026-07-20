# whiteboardTUI

whiteboardTUI 是提供 Linux、macOS、WSL2 原生終端與獨立瀏覽器版的 C++20 無限白板。它將
Note、Markdown、Code、Todo、CSV、Folder、Text-art、Unicode Glyph，以及
正交邊內容放在同一個稀疏的世界座標空間中，同時讓
應用程式保持本機執行、具確定性，並方便以鍵盤操作。

[詳細文件](docs/README.md)

## 重點功能

* 單一核心的 WASM／xterm.js 瀏覽器版，提供編輯、觸控唯讀、檔案匯入匯出與本機草稿；
* 七種編譯期卡片格式，另加一個獨立的稀疏 Unicode Glyph 圖層；
* 在同一個 TUI 中提供 BOARD、SELECT、GLYPH 與 EDGE 工作流程；
* 穩定的 CardId 與 EdgeId 槽位、可透過交易復原的模型變更，以及
  有界的世界座標算術；
* 完全內嵌的獨立 `.tiwb`，具有每個區段的 CRC 與單檔原子儲存；
* 本機 mode-`0600` Unix socket 自動化 API、`whiteboardctl` 參考用戶端，以及
  共用 canonical serializer 的唯讀 `whiteboard-inspect`；
* 具確定性的 Python 文字藝術渲染器，以及內容定址資訊清單；
* 匯出的 CMake targets，供核心、I/O、渲染、Agent 與 TUI 使用端使用。

## 快速開始

準備 vcpkg，將 `VCPKG_ROOT` 指向它的絕對路徑，再執行一致的 Release 流程：

```sh
export VCPKG_ROOT=/absolute/path/vcpkg
cmake --preset vcpkg-release
cmake --build --preset vcpkg-release
ctest --preset vcpkg-release
./build/vcpkg-release/whiteboard_tui [board-file]
```

`vcpkg.json` 管理 Abseil、FreeType 與 libpng；Tree-sitter runtime 與三套 grammar
已隨 source 提供。支援矩陣、vcpkg baseline、macOS 與 WSL2 設定都在
[建置文件](docs/building.md)。原生 Windows executable 不在支援範圍。

應用程式會以 BOARD 模式開啟。使用方向鍵移動，以 `n` 建立 Note，
按 Enter 編輯卡片，按 Ctrl-S 儲存，並在白板處於乾淨狀態時
按 `q` 離開。完整工作流程請參閱[使用者指南](docs/user-guide.md)，
依情境而定的按鍵請參閱[按鍵綁定參考](docs/keybindings.md)。

如需 Debug/sanitizer 組建、安裝、匯出的 CMake targets，以及 Python
renderer/materializer 工具，請從[建置](docs/building.md)開始。

瀏覽器版的獨立建置、靜態部署與嵌入套件用法見原始碼目錄中的 `web/README.md`。
原生建置不需要瀏覽器工具鏈。

## 文件

| 需求             | 文件                                           |
| -------------- | -------------------------------------------- |
| 學習 TUI 與卡片工作流程 | [使用者指南](docs/user-guide.md)                  |
| 查詢按鍵或滑鼠動作      | [按鍵綁定](docs/keybindings.md)                  |
| 建置並安裝專案        | [建置](docs/building.md)                       |
| 了解擁有權與資料流程     | [架構](docs/architecture.md)                   |
| 實作另一種卡片類型      | [新增卡片類型](docs/adding-card-types.md)          |
| 實作持久化資料     | [檔案格式](docs/file-format.md)                  |
| 自動化執行中的白板      | [使用 `whiteboardctl` 自動化](docs/automation.md) |
| 將 Markdown 製成白板知識圖 | [Automation 與 source-tree skill](docs/automation.md#markdown-白板-skill-workflow) |
| 實作 Agent 用戶端   | [本機 Agent 協定](docs/agent-protocol.md)        |
| 執行測試與基準測試      | [測試](docs/testing.md)                        |

## 授權

本專案自有程式碼採用 [MIT License](LICENSE)。第三方程式碼、相依套件與字型
維持各自授權，詳見[第三方聲明](docs/third-party-notices.md)。
