# 白板與 renderer 檔案格式

本文件說明 whiteboardTUI 2.0.0 的持久化契約。`.tiwb` 是自足的單一文件；
所有卡片內容、樣式、位置、Folder 結構、連邊與 Glyph 都內嵌。開啟不解析
相對或絕對的外部內容路徑，不讀取 sidecar，也不修改磁碟。

執行期 ownership 見 [`architecture.md`](architecture.md)。

## `.tiwb` 原生 envelope

所有多 byte 整數皆為 little-endian。

| 欄位 | 型別 | 值 |
|---|---|---|
| magic | u32 | `0x42574954` |
| format ID | u32 | `11` |
| section count | u32 | `3` |

三個 section 依序為 `CARD`（`0x44524143`）、`EDGE`（`0x45474445`）、
`GLYP`（`0x50594C47`）。每個 section 包含 `u32 tag`、`u64 payload length`、
`u32 IEEE CRC-32` 和 payload。Reader 要求恰好消耗宣告長度，並檢查全檔 EOF。
不支援的文件版本、錯誤的 section、未知 StaticFormatId、尾隨 bytes，以及
未通過結構或幾何檢查的資料都會被拒絕。

字串為 `u32 byte length` 後接原始 bytes。文字預期使用 UTF-8，原生 decoder
依長度讀取，不檢查 UTF-8 合法性。

## CARD section

先保存 `u32` 永久 CardId slot count。每個 slot 保存 `u8 alive`；存活的卡片
接著保存 `i64 x`、`i64 y`、`u32 StaticFormatId` 和完整格式資料。
刪除後的空槽仍然保留，因此 CardId 不會重新編號。

內容交換格式由 registry 推導，用於 Agent 與明確匯出。每張卡片的持久狀態
只包含位置、StaticFormatId 與完整格式資料。

| StaticFormatId | Format | Payload family | 內容交換格式 |
|---|---|---|---|
| 0 | note | text | PlainText |
| 1 | markdown | text | Markdown |
| 2 | code | text | PlainText |
| 3 | todo | todo | TodoText |
| 4 | csv | CSV | Csv |
| 5 | folder | folder | FolderTree |
| 6 | text-art | text | PlainText |

ID 只能 append，不可 reorder 或 reuse。每個 payload 先保存 layout：兩個 i32。

- Text：u32 LanguageId（0 plain text、1 Markdown、2 C++），u32 span count，
  每筆 span 的 u32 row/begin-byte/end-byte 與三個 u8 style，最後是 u32 line count
  和每行的 length-prefixed string。Spans 以 row/byte canonical order 保存。
- Todo：u32 item count；每筆依序是文字、u8 done 與三個 u8 style。
- CSV：u32 column-width count 與 i32 widths，u32 sparse-style count 與
  row/column/style records，最後是 u32 row count，每行 u32 cell count 與字串。
- Folder：root name、u32 entry count；每筆是 u8 kind、u32 depth、name、
  u32 target CardId、u8 collapsed。目錄是白板內的虛擬結構。

原生 decoder 不拒絕未知 LanguageId。卡片索引不屬於檔案格式；Loader 讀取資料、
執行格式重建，驗證 layout 與座標後重建 sparse grid。

## EDGE section

先保存 u32 永久 EdgeId slot count 和各 slot 的 u8 alive marker。存活連邊
保存 source/target CardId 與 port side、route mode/state、finite route bounds，
以及 u32 point count 與各 point 的 i64 x/y。

Loader 驗證 endpoints、enums、bounds 與正交幾何，正規化多餘 points，重建
incident adjacency，並依卡片推導 collision state。引用 tombstone card 的連邊
可保持 dormant。App 在提交文件前重建 edge spatial index。

## GLYP section

保存 u32 count，接著每筆 i64 x、i64 y、u32 Unicode scalar。Writer 依 y/x
排序，確保相同模型的輸出可重現。Loader 拒絕無效、control、zero-width anchor、
座標溢位，以及單格／雙格 footprint 重疊。

## Reader 限制

配置記憶體前檢查：全檔／任一 section 上限 1 GiB；累計估算配置量 512 MiB；
CardId／EdgeId slots 最多 10,000,000；一般重複項目最多 50,000,000；一條 edge
最多 4,096 points；單一字串最多 64 MiB。Count 必須能由剩餘 bytes 容納。
所有解碼、格式重建與驗證先在暫存模型執行，失敗時目前白板保持不變。

## 單檔儲存

Writer 在目標同目錄建立 mode-0600、exclusive、no-follow 暫存檔，寫入完整
快照，依序 flush、fsync、close，再原子替換目標並 fsync 父目錄。
Loader 只讀取指定文件；殘留暫存檔不參與開啟流程。

只有檔案與目錄同步都成功，App 才標記目前 history 位置已儲存。若替換已成功
而目錄同步失敗，回報「file published; durability not confirmed」，保留 dirty。
History、revision、viewport、編輯 session 與空間索引不存入文件。

## 內容交換與匯出

`storage/card_content.hpp` 提供純內容 codecs，供 Agent replacement 和 Folder
匯出使用，不負責載入其他檔案。Plain/Markdown 是 UTF-8 line bytes；Todo 是
`- [ ] text`／`- [x] text`；CSV 使用嚴格 quote/comma/newline parser。
Folder exchange 使用 ROOT 與 preorder entries 的 tab-separated 格式。

內容 decoder 上限為 256 MiB，文字／Todo 最多 100,000 logical lines；CSV 最多
1,000,000 rows、10,000,000 cells 與 512 MiB 估算配置量。先建立暫存內容再提交。
這些交換格式不包含全部視覺 metadata；完整保存必須使用 `.tiwb`。

## Text-art manifest

Renderer 輸出為：

```text
OUTPUT/
├── manifest.json
└── generations/
    └── SHA256/
        ├── manifest.json
        └── payloads/LOGICAL-ID.txt
```

Root 與 generation manifest 都包含 `manifest_version: 2`、一個小寫 64-hex
generation、renderer/theme，以及一筆以上的 text-art card record。Payload path
必須恰好為 `generations/<generation>/payloads/<logical-id>.txt`。產生的 schema
與限制位於 `tools/textart_notes/core/`；請透過
`tools/generate_contract_schema.py` 重新產生。

Generation 內容不可變。Writer 會完整 fsync 一個 generation，之後以原子方式
切換 root manifest。每個 manifest 明確引用一個 immutable generation；清理
未被引用的 generation 前必須先識別 references。Reader 與 writer 使用
`manifest_version: 2`，不接受缺少版本或版本不符的 manifest。

## 瀏覽器傳輸與草稿

瀏覽器版以同一 decoder 處理選取檔案的 bytes，以同一 encoder 產生下載與
IndexedDB 草稿；格式 ID 與內嵌內容相同。瀏覽器不使用 POSIX 原子檔案發布流程。
IndexedDB transaction 完成後，以文件 generation 與 revision 確認儲存點；
較早的儲存完成回覆不能清除較新修改的 dirty state。

瀏覽器入口的檔案與資源預算見原始碼目錄中的 `web/README.md`，
這些上限不改變 `.tiwb` 格式。下載請求只能確認已發起，無法確認使用者磁碟寫入。
