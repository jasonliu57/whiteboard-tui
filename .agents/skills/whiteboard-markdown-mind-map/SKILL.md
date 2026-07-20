---
name: whiteboard-markdown-mind-map
description: 讀取 Markdown，設計卡片，編譯白板 artifacts，取得版面提案，寫入 whiteboardTUI，並驗證存檔。使用者要求把 Markdown 視覺化或製成白板知識圖時使用。
---

# Markdown 白板知識圖

所有命令從 repository root 執行。

Board 操作明確指定本次使用的執行檔。以下命令以 `build/vcpkg-release/` 為例；
使用其他建置或安裝目錄時，填入對應路徑。

## 角色

設計 agent 的唯一輸入是來源 Markdown 與下列提問：

> 假如要用一張白板筆記清楚、結構化地表達這份資料，卡片內容、視覺形式、關係與閱讀順序應如何設計？

設計 agent 使用 `apply_patch` 寫入 `work/design.md`。內容包含讀者收穫、卡片構想、卡片關係與閱讀順序。這份設計稿完成設計 agent 的工作。

主 agent 讀取來源、`work/design.md` 與三份 reference：

- [artifact-contract.md](references/artifact-contract.md)：檔案格式與 CLI。
- [renderer-catalog.md](references/renderer-catalog.md)：原生格式與 renderer。
- [board-workflow.md](references/board-workflow.md)：Board run 流程。

主 agent 使用 `apply_patch` 維護 `plan.md`、兩份 unit layout 與 `state.tsv`。

## 工具

- `scripts/mindmap_tools.py`：編譯 plan、展開座標、產生 batch、解釋版面 errors 與 warnings。
- `scripts/verify_whiteboard.py`：執行 preview、materialize、final 與 attestation。
- `tools/textart_notes/render_note.py`：把 renderer input 編譯成 text-art cards。
- `$imagegen`：根據 Board 預覽產生版面參考圖。
- `apply_patch`：原子修改文字 artifacts。

## Run

1. 在來源旁建立 `<source-stem>.mindmap/` 與 `work/`。
2. 啟動一位設計 agent，傳入來源 Markdown、提問與 `work/design.md` 路徑。
3. 主 agent 讀取設計稿與 references。
4. 主 agent 將設計稿整理成 `plan.md`，並建立 `state.tsv`。
5. 編譯 presentation artifacts：

   ```sh
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/mindmap_tools.py prepare --run-dir "$RUN_DIR"
   ```

6. 主 agent 寫入 `work/provisional-unit-layout.tsv`。
7. 展開 provisional layout 並建立 preview batch：

   ```sh
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/mindmap_tools.py expand-layout --run-dir "$RUN_DIR" --layout work/provisional-unit-layout.tsv --output work/provisional-layout.tsv
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/mindmap_tools.py build-batch --run-dir "$RUN_DIR" --layout work/provisional-layout.tsv --output work/preview.cards
   ```

8. 取得 Board 預覽：

   ```sh
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py preview --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl
   ```

9. 使用 `$imagegen` edit mode 讀取 `work/preview.raw.png`，提供 unit 摘要與 connections，將提案存為 `layout-reference.png`。
10. 主 agent 依提案寫入 `unit-layout.tsv`。
11. 展開最終 card layout：

   ```sh
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/mindmap_tools.py expand-layout --run-dir "$RUN_DIR" --layout unit-layout.tsv --output layout.tsv
   ```

12. 主 agent 將 `state.tsv` 的 `phase` 更新為 `positioned`。
13. 寫入 cards、payloads 與 edges：

   ```sh
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py materialize --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl
   ```

14. 使用者在 whiteboardTUI 按 `Ctrl-S`。
15. 驗證 live Board、disk Board 與最終影像：

   ```sh
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py final --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl --whiteboard-inspect build/vcpkg-release/whiteboard-inspect
   python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py check-attestation --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl --whiteboard-inspect build/vcpkg-release/whiteboard-inspect
   ```

16. `ATTESTATION result=CURRENT` 完成 run。

## 回報

回報來源、run 目錄、Board 檔案、revision、卡片數、edge 結果與驗證結果。

附上 `work/design.md`、`plan.md`、`layout-reference.png`、`unit-layout.tsv`、`layout.tsv`、`final.png` 與 `work/verification/report.md`。
