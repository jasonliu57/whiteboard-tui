# 新增 Card type

讀者：實作另一種 compile-time Card format 的貢獻者。

本文件擁有實作順序與 review checklist。設計理由在
[`architecture.md`](architecture.md)，持久化數值契約在
[`file-format.md`](file-format.md)。不要把這些契約複製到本文件。

whiteboardTUI 沒有 runtime format-plugin ABI。新 type 是編譯進
`whiteboard::core`、註冊至 stable array 的 source change。

## 1. 先分類變更

先判斷功能是否真的需要新 StaticFormatId。

- 在既有 payload family 上新增 visual/editor behavior，可能可重用
  `TextCardData`、`TodoCardData`、`CsvCardData` 或 `FolderCardData`。
- 新 syntax language 可能只需要 LanguageId、grammar/query integration 與 format
  factory，不需要新 payload family。
- 新 內容交換 encoding 即使不改 in-memory payload，也可能需要 SaveFormat 與
  內容 codec。
- 真正新的 semantic data model 需要新 `CardData` variant、`CardDataKind`、
  native codec、limits 與完整的往返測試。

只有 existing invariant 完全相同時才重用。不要只為避免 compatibility change，
就把無關 parallel arrays 或 semantic fields 塞進既有 payload。

## 2. 維持 stable identifiers

StaticFormatId 會寫入磁碟並由 Agent response 公開。既有 ID 絕不能 reorder、
renumber 或 reuse。在 `src/formats/registry.hpp` 目前範圍後加入 constant，增加
`src/formats/format.hpp` 的 `kCardFormatCount`，並在
`src/formats/registry.cpp` 相同位置 append factory。
同時依第 8 節更新共用格式契約。

Canonical ID table 位於 [`file-format.md`](file-format.md)。同一次變更必須更新
該表，並在變更說明中記錄 compatibility 影響。

變更 on-disk payload family 時，同步定義 native format ID、reader/writer、
資源限制與往返測試。專案只保留目前文件格式的 decoder；版本不符直接拒絕。

## 3. 選擇或新增 payload

Persistent Card shell 包含 position、StaticFormatId 與一個 `CardData`
value，不含 generic width、height、language、rows 或 format-specific flags。

使用既有 payload family：

1. 在 factory 建立 format/payload invariant；
2. 由 format implementation 維持所有 parallel data 一致；
3. 只有 semantics 完全相符時才重用該 family 的 native/內容 codecs。

新增 payload family：

1. 在 `src/model.hpp` 以明確 bounds 與 equality 定義 payload；
2. append 至 `CardData`，並新增 `CardDataKind`，不重排既有 values；
3. 在 `src/storage/binary.hpp` 新增 bounded write/read；
4. 在 allocation 或 live-model mutation 前驗證每個 count、byte length、enum、
   coordinate 與 relationship；
5. 更新 load-allocation estimate 與 hostile-input fixtures。

只有 loader 與 factory 應建立 StaticFormatId/CardData pairing。Rendering hot path
不應反覆重新驗證。

## 4. 實作 `CardFormat` callbacks

在 `src/formats/` 新增聚焦 implementation，並在 `registry.hpp` 宣告 factory。
Format 透過 `CardFormat` 提供普通 function pointers：

| Callback | 責任 |
|---|---|
| `measure` | 由 validated payload metadata 推導 visible extent |
| `draw` | 畫入提供的 Screen，不 mutation Board state |
| `begin` | 由 persistent content 初始化 transient editor session |
| `input` | 將一個 semantic InputEvent 轉成 view/stored action |
| `rebuild` | Decode 後 canonicalize 並重建 derived payload state |
| `swap_undo` | 為 undo/redo 交換一個 typed format undo token |
| `create_empty` | 以指定位置與可見尺寸建立有效空卡片 |

Returned `CardFormat` 還要定義 bounds、styles、border glyphs、title behavior、
wrap behavior。SaveFormat 由 registry 依 StaticFormatId 推導。

Format callback 刻意不取得 `Board&`。Cross-card action 必須回傳如
`focus_card` 的 narrow intent，由 TUI 在單一 mutation boundary 解析。

## 5. 建立具有有效空狀態的 factory

提供 `make_*_card(Pos, ...)` factory，回傳完全有效的 card：

- append 後的 StaticFormatId；
- 相符的 StaticFormatId 與完整 payload；
- 位於 format min/max extent 內的 payload metadata；
- editor invariant 所需的最少 rows/items/cells；
- 不包含 transient editor state。

將 factory 指派給 `CardFormat::create_empty`。Registry 的
`create_registered_card()` 驗證 ID、尺寸、座標、payload family 與
實測尺寸。TUI creation、Agent batch、tests 與 benchmark 共用這個入口。

## 6. 新增 editing 與 typed undo

若 format 需要 transient editing state，將 session type append 至
`FormatSession`。Cursor、selection、scroll、draft 與 syntax tree 屬於 session，
絕不屬於 persistent CardData。

每個 stored input action 必須：

1. 驗證完整操作；
2. 只透過 `FormatContext` mutation 自己的 payload；
3. 回傳 `FormatMutation::Stored`；
4. 提供能重現 undo/redo 的最小 typed swap token；
5. 只有 visible geometry 改變時才設定 `layout_changed`。

將新 token type append 至 `FormatUndo`；不要加入一個含其他 formats 無關欄位的
大型 snapshot union member。Full Card snapshot 保留給 card creation/deletion 與
明確 ownership boundary。

純 cursor/selection/scroll 變更回傳 `FormatMutation::View`，不標記 dirty。
Rejected operation 不改 payload、history、dirty state 或 revision。

## 7. 註冊 user 與 Agent entry points

只有 format 應能從 BOARD 直接建立時才新增 TUI creation action。更新 declarative
context binding/action dispatch，以及 [`keybindings.md`](keybindings.md) 與
[`user-guide.md`](user-guide.md) 中的同名項目。

是否透過 Agent 公開是另一個 public decision：

- `create-cards` 的 name parsing、geometry bounds 與 factory dispatch 由 registry
  batch builder 提供，TUI 只提交完成的 cards；
- `replace-card` 需要由既有 SaveFormat 選擇 strict body decoder；
- `propose` 只支援明確列出的 formats，且在使用者接受前維持 preview-only；
- `GET`/`QUERY` 必須回報 stable format，且不可使用可避免的完整 body
  intermediate copy。

任何 Agent change 都要在同一次變更更新
[`agent-protocol.md`](agent-protocol.md)、CLI usage、相關 shared generated limits、
malformed-input tests 與 compatibility 說明。

## 8. 明確定義內容交換

所有原生卡片資料一律內嵌於 `.tiwb`。若格式需要 Agent replacement 或 Folder
匯出，重用完全相符的 SaveFormat，或擴充 registry 與純內容 codecs。
提供 bounded decoder、語法失敗保持原資料的測試，以及明確的匯出格式說明。

新增或調整格式時：

1. 更新 `contracts/card-formats.json` 的格式名稱、尺寸上下限與 SaveFormat；
2. 執行 `python3 -B tools/generate_contract_schema.py`，產生 C++／Python 契約；
3. 由 format factory 套用產生的尺寸契約，並更新 `card_save_format()` 的 registry 映射。

Python automation 的 batch、response 與 snapshot parser 使用同一份產生的格式契約。

## 9. 只接入 build 一次

在 `CMakeLists.txt` 將 implementation source 加入 `whiteboard_core` 一次。避免從
headers 或 TUI aggregate include implementation `.cpp`。Public declaration 必須
通過 header-check target 獨立編譯；private helper 應維持 private，不出現在
install tree。

不要建立由 core/formats 反向指向 TUI、terminal、Agent transport、I/O
publication 或 image rendering 的 dependency。

## 10. 必要測試

至少涵蓋：

- factory invariants 與 min/max measurement；
- normal、hover、selected、editing visual states 的 draw behavior；
- 每個 input operation 與 no-op boundaries；
- active/inactive session 的 undo 再 redo；
- layout change 更新 spatial 與 incident-edge geometry；
- native save/load round trip 與 strict malformed input；
- 測內容交換 encode/decode limits；
- overlapping card positions 與 stable IDs；
- 若透過 Agent 公開，測 success、malformed/truncated input、stale revision 與
  transactional failure；
- isolated public-header compile 與 installed-package smoke tests；
- 任一 text-like content 的 Unicode cell-width cases。

執行 [`testing.md`](testing.md) 的 profiles；變更 IDs、limits、Unicode 或 schema
時也執行 generated-contract checks。

## Review checklist

開 pull request 前確認：

- persistent owner 仍只有 `BoardDocument`；
- 既有 numeric IDs 與 enum values 未移動；
- parser、renderer、callback 都沒有取得 mutable Board bypass；
- 所有不受信任 size 在 allocation 前受限；
- hot render/query path 不複製完整 payload；
- 每項變更只有一份 canonical 文件 owner，其他文件只連結而不複製 table 或
  command block；
- 所有受影響的繁中文件與實作契約一致；
- pull request 明確說明 compatibility 與 failure behavior。
