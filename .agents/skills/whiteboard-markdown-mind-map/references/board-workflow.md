# Board 工作流程

本文件供主 agent 使用。

## Board 綁定

`state.tsv` 記錄來源、Board file、Unix socket、phase、revision、dirty 與 saved。

Verification CLI 透過 `whiteboardctl` 使用該 socket。
操作命令必須明確指定執行檔路徑。以下範例使用 `build/vcpkg-release/`；
其他建置或安裝目錄請填入對應路徑。

## Preview

`work/preview.cards` 包含 provisional card geometry。

```sh
python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py preview --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl
```

`preview` 依序執行 `status`、`view`、`query`、`create-cards`、`board-png`、`delete-cards` 與 `status`。

輸出：

- `work/preview.ids`
- `work/preview.raw.png`
- `work/preview-result.json`

`preview-result.json` 記錄範圍、CardIds、revisions、viewport 與 PNG metadata。

## Imagegen

Imagegen edit mode 讀取 `work/preview.raw.png`。

Prompt 提供 unit ID、標題、用途、群組與 connections。

成果寫入 `layout-reference.png`。

主 agent 將視覺提案轉成 `unit-layout.tsv`。

## Materialize

主 agent 將 `phase` 寫為 `positioned`。

```sh
python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py materialize --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl
```

`materialize` 依序完成 geometry preflight、baseline snapshot、card batch、payload replacements、edge connections 與結果記錄。

主要輸出：

- `card-map.tsv`
- `edge-results.tsv`
- `work/create.cards`
- `work/materialization.jsonl`
- `work/verification/baseline.snapshot`
- `work/verification/baseline.json`

每次 Board mutation 帶入 expected revision。Journal 在 mutation 前後記錄狀態。Artifact 修改由主 agent 使用 `apply_patch` 完成。

## Save

使用者在 whiteboardTUI 按 `Ctrl-S`。

`.tiwb` 使用 format 11，內嵌所有卡片內容、Folder CardId references 與連邊。
`payloads/`、renderer manifests 與其他 run artifacts 是編譯及驗證的輸入，
不是白板重開時的依賴。儲存成功後，只複製 `.tiwb` 即可在其他目錄開啟。

`final` 與 `check-attestation` 仍需要 run artifacts，以比對設計預期與白板內容；
它們透過 `whiteboard-inspect` 讀取 `.tiwb`，不自行解碼檔案或解析外部 payload 路徑。
Revision 屬於執行期狀態，重開白板後若要取得有效 attestation，須重新執行 `final`。

## Final

```sh
python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py final --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl --whiteboard-inspect build/vcpkg-release/whiteboard-inspect
python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py check-attestation --run-dir "$RUN_DIR" --whiteboardctl build/vcpkg-release/whiteboardctl --whiteboard-inspect build/vcpkg-release/whiteboard-inspect
```

`final` 比對 artifacts、live cards、live edges、live snapshot、disk snapshot 與 Board PNG。

`check-attestation` 比對 artifact digest、revision、dirty 與兩份 snapshot digest。

完成訊號：

```text
ATTESTATION result=CURRENT
```

證據位於 `final.png` 與 `work/verification/`。
