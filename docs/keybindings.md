# 按鍵參考

讀者：已了解 whiteboard modes、需要精確查詢輸入的人。

本文件擁有使用者可見的 keyboard 與 mouse mapping，不教授工作流程；任務導向
說明見 [`user-guide.md`](user-guide.md)。TUI-level bindings 宣告於
`src/tui/keymap.hpp`；active-card 文字輸入 則由 `src/formats/` 下對應檔案
實作。

## 表示法與優先序

- `Left`、`Right`、`Up`、`Down` 代表 terminal 方向鍵。
- `H J K L` 代表大寫字母；`h j k l` 代表小寫字母。
- `Shift+Tab` 需要 terminal 送出標準 back-tab sequence。
- Printable text 與 bracketed paste 只有在 proposal、prompt、context 與 global
  handling 之後才會到達 active editor。
- Export prompt 會先攔截自己的文字、Enter、Backspace 與 Escape；其他 global
  shortcuts 在該 prompt 不執行。
- 其餘 context 有 pending Agent proposal 時，Ctrl-G 與 Ctrl-D 優先。
- Ctrl-S、Ctrl-Q、Ctrl-E、Ctrl-Z、Ctrl-Y、Ctrl-R 在非 export-prompt context
  是 global；只有 GLYPH 會刻意拒絕 undo/redo。

## Global 與暫態輸入

| Context | 輸入 | 動作 |
|---|---|---|
| 非 export prompt | Ctrl-S | 儲存 project |
| 非 export prompt | Ctrl-Q | 即使 dirty 也強制離開 |
| Folder 是目前 target | Ctrl-E | 開啟 Folder export parent prompt |
| 可 undo 的 model context | Ctrl-Z | Undo |
| 可 undo 的 model context | Ctrl-Y 或 Ctrl-R | Redo |
| Pending Agent proposal | Ctrl-G | 接受並提交 proposal |
| Pending Agent proposal | Ctrl-D | 拒絕 proposal |
| Export prompt | Text 或 Paste | 附加 destination parent |
| Export prompt | Backspace | 移除前一個 UTF-8 character |
| Export prompt | Enter | 執行 export |
| Export prompt | Escape | 取消 export |
| Active card | Escape | 結束編輯並進入 SELECT |

## BOARD cursor

| 輸入 | 動作 |
|---|---|
| 方向鍵或 `h j k l` | 世界 cursor 移動一格 |
| Shift+方向鍵 | 同步平移 viewport/cursor，保持畫面位置 |
| Home | 將 cursor 移至世界原點並顯示它 |
| PageUp / PageDown | 移動一個 viewport 高度 |
| Tab 或 Shift+Tab | 選取 cursor 下的 card |
| Enter 或 `e` | 編輯 cursor 下的 card |
| Delete 或 `x` | 刪除 cursor 下的 card |
| `H J K L` | 將 cursor 下的 card 移動一格 |
| `n` | 建立並編輯 Note |
| `m` | 建立並編輯 Markdown card |
| `c` | 建立並編輯 C++ Code card |
| `t` | 建立並編輯 Todo card |
| `v` | 建立並編輯 CSV card |
| `f` | 建立並編輯 Folder card |
| `g` | 進入 EDGE mode |
| `i` | 進入 GLYPH DRAW |
| Ctrl-C 或 `y` | 複製 cursor 下的 card |
| Ctrl-X 或 `d` | 剪下 cursor 下的 card |
| Ctrl-V 或 `p` | 在 cursor 貼上 copied card |
| `u` | Undo |
| `q` | 只在 clean 時離開 |
| `Q` | 強制離開 |

BOARD 會拒絕 terminal text paste；文字 paste 必須在 active card。Card creation
與 paste 應從 BOARD 執行，不應在 SELECT 執行。

## SELECT

| 輸入 | 動作 |
|---|---|
| 方向鍵或 `h j k l` | 選取該方向第一張可見 card |
| Shift+方向鍵 | 平移但不改 selected CardId |
| `H J K L` | 將 selected card 移動一格 |
| Enter 或 `e` | 編輯 selected card |
| Delete 或 `x` | 刪除 selected card |
| Ctrl-C 或 `y` | 複製 selected card |
| Ctrl-X 或 `d` | 剪下 selected card |
| `c` | 將 selected Text-art 轉成 GLYPH SELECT；其他格式拒絕 |
| Escape | 回到 card 左上位置的 BOARD |

## Text editors

除非該列另有說明，此表適用 Note、Markdown、Code 與 Text-art。

| 輸入 | 動作 |
|---|---|
| Text 或 Paste | 取代 selection 或在 cursor 插入 |
| Enter | 插入 newline |
| Tab 或 Shift+Tab | 插入 tab character |
| Backspace / Delete | 刪除 selection、前一個 cluster 或下一個 cluster |
| Left / Right | 依 UTF-8 display cluster 移動 |
| Up / Down | 移動 logical row；Markdown 則移動 visual wrapped row |
| Home / End | 移至 logical line 開頭／結尾 |
| PageUp / PageDown | 移動 inner visible height |
| Shift+movement | 擴大 selection |
| Ctrl-A | 全選文字 |
| Ctrl-C | 複製非空 selection |
| Ctrl-X | 剪下非空 selection |
| Ctrl-V | 貼上 text clipboard |
| Ctrl-B | Note/Text-art 套 style；Markdown 加 emphasis；Code 無動作 |
| Ctrl+方向鍵 | 調整 Note、Markdown、Code 尺寸；Text-art 固定 |
| Escape | 結束編輯並選取 card |

Markdown 的 Up/Down/PageUp/PageDown 依 visual soft-wrapped lines；Left/Right/
Home/End 保留 source-text semantics。Code 與 Note 可以 horizontal scroll。

## Todo editor

| 輸入 | 動作 |
|---|---|
| Up / Down | 選取前／後 item |
| Home / End | 選取第一／最後 item |
| Tab 或 Shift+Tab | 切換完成狀態 |
| Enter | 在 selected item 後插入新 item |
| Delete 或 Ctrl-X | 刪除 selected item；唯一 item 時清空 |
| Backspace | 移除 item 最後一個 UTF-8 character |
| Ctrl-B | 建立／循環 selected item 顏色 |
| Ctrl-C | 複製 selected item text |
| Ctrl-V | 將 text clipboard 附加至 selected item |
| Text 或 Paste | 附加至 selected item |
| Ctrl+方向鍵 | 調整 card 尺寸 |
| Escape | 結束編輯並選取 card |

## CSV editor

| 輸入 | 動作 |
|---|---|
| 方向鍵 | 移動一個 cell，不 wrap |
| Tab / Shift+Tab | 前往前／後 cell，跨 rows wrap |
| Home / End | 前往 row 第一／最後 column |
| Enter | 往下移；在最後一列新增 row |
| Delete | 清空目前 cell |
| Backspace | 移除 cell 最後一個 UTF-8 character |
| Ctrl-X | 刪除目前 row；唯一 row 時清空 |
| Ctrl-B | 建立／循環目前 cell sparse style |
| Ctrl-C | 複製目前 cell text |
| Ctrl-V | 將 text clipboard 附加至目前 cell |
| Text 或 Paste | 附加至目前 cell |
| PageUp | 依 cell content 重新計算 display column widths |
| Ctrl+方向鍵 | 調整 card 尺寸 |
| Escape | 結束編輯並選取 card |

## Folder editor

特殊的 `root` selection 代表 preorder entries 上方的 Folder name。

| 輸入 | 動作 |
|---|---|
| Up / Down | 在 visible root/entry rows 間移動 |
| Home / End | 選取 root／最後 visible entry |
| Left | 折疊 open directory，否則選取 parent |
| Right | 展開 directory 或進入第一個 visible child |
| Enter | 切換 directory collapse，或聚焦 referenced card |
| Ctrl-A | 在 selected subtree 後插入 empty directory |
| Tab | 將 selected subtree indent 至前一個 directory sibling |
| Shift+Tab | 將 selected subtree outdent |
| Delete 或 Ctrl-X | 移除 entry subtree，不刪 referenced cards |
| Backspace | 移除 selected name 最後 UTF-8 character |
| Ctrl-C | 複製 selected root/entry name |
| Ctrl-V，card clipboard | 插入 weak reference entry |
| Ctrl-V，text clipboard | 附加至 selected name |
| Text 或 Paste | 附加至 selected name |
| Ctrl+方向鍵 | 調整 card 尺寸 |
| Ctrl-E | 開啟 Folder export prompt |
| Escape | 結束編輯並選取 card |

## GLYPH

### GLYPH 共用輸入

| 輸入 | 動作 |
|---|---|
| 方向鍵 | 移動 cursor 或 selection/placement endpoint |
| Shift+方向鍵（DRAW/PLACE） | 同步平移 viewport 與 cursor/preview |
| Ctrl-C（DRAW/SELECT） | 複製 cursor 下 glyph 或 sparse selection |
| Ctrl-X（SELECT） | 剪下 sparse selection |
| Ctrl-V（DRAW/SELECT） | 在 cursor 貼上 glyph clipboard |
| Ctrl-Z / Ctrl-Y / Ctrl-R | 拒絕：GLYPH 沒有 undo/redo |

PLACE 中的 clipboard shortcuts 不會改變 preview；Enter 或 Escape 結束 PLACE 後
才能再次複製、剪下或貼上。

### GLYPH DRAW

| 輸入 | 動作 |
|---|---|
| 可顯示 Unicode 或 Paste | 寫入 anchors，依 cell width 前進 |
| Space | 清除目前 cell |
| Enter | 往下一列 |
| Backspace | 左移並刪除該處完整 glyph |
| Delete | 右移並刪除該處完整 glyph |
| Tab 或 Shift+Tab | 從 cursor 開始 GLYPH SELECT |
| Escape | 回到 BOARD |

### GLYPH SELECT

| 輸入 | 動作 |
|---|---|
| 方向鍵 | 移動 active selection corner |
| Shift+方向鍵 | 不改 rectangle，切換 active corner |
| `H J K L` | 朝該方向一格開始 PLACE |
| `c` | 將 selected rectangle 轉成 Text-art |
| Delete | 清除 selected glyphs |
| Tab、Shift+Tab、Enter 或 Escape | 回到 GLYPH DRAW |

### GLYPH PLACE

| 輸入 | 動作 |
|---|---|
| 方向鍵或 `H J K L` | 移動 placement preview |
| Enter | 原子覆寫 destination 並 commit |
| Escape | 取消並還原來源 |
| Tab 或 Shift+Tab | 保持 PLACE 並顯示 commit/cancel 提示 |

## EDGE

| Context | 輸入 | 動作 |
|---|---|---|
| 任一 EDGE phase | 方向鍵或 `h j k l` | 移動 cursor 或可移 segment |
| 任一 EDGE phase | Shift+方向鍵 | 平移並更新 preview |
| Browse | Enter 或 `n` | 從 card border 開始；Enter 也可編輯 selected segment |
| Browse | Tab / Shift+Tab | 循環 visible edge/segment candidates |
| Browse | `m` | 編輯 selected internal segment |
| Browse | `r` | 在目前 viewport reroute selected edge |
| Browse | Delete 或 `x` | 刪除 selected edge |
| Build | `a` | 下一段使用 automatic |
| Build | `m` | 下一段使用 manual L-shape |
| Build | Tab / Shift+Tab | 切換 manual horizontal/vertical priority |
| Build | Enter | 加 waypoint，或在有效 target border commit |
| Build | Backspace | 移除前一 waypoint |
| Edit | Enter | 提交 segment movement |
| Build/Edit | Escape | 取消 draft/edit 並回到 Browse |
| Browse | Escape | 回到 BOARD |
| 任一 EDGE phase | `q` | 捨棄 draft/edit 並回到 BOARD |

## Mouse 與滾輪

| Context | 輸入 | 動作 |
|---|---|---|
| BOARD | 左鍵點空白 cell | 放置 cursor |
| BOARD | 左鍵點 card | 選取 card |
| BOARD | 右鍵 | 依 mouse-cell/cursor 差平移 |
| BOARD/SELECT | 中鍵拖曳 | 平移 viewport |
| SELECT | 左鍵點另一 card | 改變 selection |
| SELECT | 左鍵點 selected card | 未拖曳則 release 時編輯 |
| SELECT | 左鍵拖曳 | 移動 card，合併為一筆 undo |
| SELECT | 左鍵點空白 cell | 回到該處 BOARD |
| Active card | 左鍵點空白 cell | 結束編輯並回到該處 BOARD |
| 使用方向鍵的 mode | 滾輪上／下 | 等同 Up/Down |
| 使用方向鍵的 mode | Shift+滾輪或水平滾輪 | 等同 Left/Right |

Mouse coordinates 是 terminal cells，不是 pixels。滾輪轉成方向鍵後，仍由 mode
規則決定要移動 content、selection 或 viewport。
