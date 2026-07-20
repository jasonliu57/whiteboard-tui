# 使用者指南

讀者：使用 whiteboardTUI 終端介面的人。

本文件擁有使用者可見的概念與任務流程。為了完成操作，文中會提到必要的主要
按鍵；各 context 的完整輸入參考由 [`keybindings.md`](keybindings.md) 擁有。
實作結構、wire encoding 與建置方式刻意不在本文件範圍內。

## 啟動、儲存與離開

以下列方式開啟新白板或既有白板：

```sh
whiteboard_tui [board-file]
```

未提供檔案參數時，TUI 使用目前工作目錄下的 `whiteboard.tiwb`。Terminal 最後
一列是 status line，通常顯示目前 mode 或 active card、世界座標、白板路徑；有未
儲存變更時會顯示 `*`。Folder export prompt 開啟時，該列會暫時改為輸入提示。

- Ctrl-S 儲存完整 project。
- BOARD/SELECT 的 `q` 只在 project clean 時離開。
- BOARD/SELECT 的 `Q`，或非 export-prompt context 的 Ctrl-Q，即使有未儲存變更
  也會強制離開。

`.tiwb` 包含完整白板，複製這一個檔案即可搬移。Ctrl-S 使用單檔原子儲存；
開啟只讀取該檔案。若顯示「file published; durability not confirmed」，表示
新檔案已替換，但系統未確認目錄同步，白板仍標記未儲存。
開啟時會驗證格式與內容；無效文件會顯示錯誤並退出，保留原檔。

## 工作模型

白板是無邊界的稀疏世界，目前 terminal viewport 只顯示其中一部分。四種相關
mode 操作不同物件：

- BOARD 移動世界 cursor 並建立 cards；
- SELECT 保持一個 CardId 被選取，供導覽、移動或編輯；
- GLYPH 編輯由個別 Unicode character anchors 組成的稀疏層；
- EDGE 建立與調整 cards 之間的正交連線。

Cards 可以使用相同位置或完全重疊。穩定 CardId 才是 identity，座標不是。
Folder entry 與 Edge 都引用 CardId；刪除 card 會留下該 ID 的 tombstone，使 undo
能還原相同 identity。

## 導覽與選取卡片

BOARD 具有世界 cursor。方向鍵或 `h j k l` 每次移動一格。Shift+方向鍵平移
viewport，同時讓 cursor 維持在同一個畫面 cell。Home 回到世界原點；PageUp、
PageDown 以一個 viewport 高度移動。

把 cursor 放在 card 上按 Tab 進入 SELECT。SELECT 中的方向鍵會選取該方向上
第一張可見 card。Escape 回到 selected card 左上位置的 BOARD。選取導覽依空間
關係，而不是插入順序。

Mouse 可直接操作同一個 model：左鍵點 card 會選取，左鍵點空白會放置 BOARD
cursor，中鍵拖曳平移 viewport。SELECT 中左鍵拖曳 card 會合併成一筆可 undo
操作；再次點擊已選 card 則進入編輯。

## 建立與排列卡片

BOARD 中的主要建立鍵為：

| 按鍵 | Card |
|---|---|
| `n` | Note |
| `m` | Markdown |
| `c` | C++ Code |
| `t` | Todo |
| `v` | CSV |
| `f` | Folder |

Card 會建立在 BOARD cursor，並立即開啟 editor。Text-art 由 GLYPH selection
建立，不使用 BOARD creation key。

在 BOARD 或 SELECT 使用 `H J K L`，可移動 cursor 下方或 selected card。
允許重疊。編輯時以 Ctrl+方向鍵調整除 fixed-footprint Text-art 之外的格式；
format 會把尺寸限制在自己的最小與最大 extent。

Card clipboard 會複製 semantic content 與 formatting。Ctrl-C/Ctrl-X/Ctrl-V 及 BOARD aliases `y d p` 分別複製、剪下、
貼上 card。貼上會在 BOARD cursor 建立內容獨立的卡片副本。

Ctrl-Z undo；Ctrl-Y 或 Ctrl-R redo 一般 model change。一個 batch、drag、resize
或 accepted Agent mutation 只形成一筆 history。刻意同時跨越 Glyph 與 Card
model 的操作不能 undo；TUI 會清除不相容 history，但仍將 project 標記為 dirty。

## 編輯卡片內容

在 card 上按 Enter 或 `e` 進入 active editor。Escape 回到 SELECT，再按一次
Escape 回 BOARD。點擊空白也會離開 editor，並把 BOARD cursor 放在該處。

### Note

Note 是 plain UTF-8 文字編輯器，每個 logical line 對應一個顯示 row。Selection
支援 copy、cut、paste 與 Ctrl-B style spans。匯出的 plain text 包含文字，但
不含這些 spans。

### Markdown

Markdown 共用文字 editor，加入 incremental block/inline highlighting，並依 card
寬度 soft-wrap logical lines，不插入 newline。Ctrl-B 會以 Markdown emphasis
markers 包住目前 selection。

### Code

Code 目前預設 C++ highlighting。它使用 logical lines 與 horizontal scrolling，
而不是 Markdown soft wrap。Syntax style 以白板 metadata 保存；匯出的 source
content 仍是一般文字。

### Todo

Todo 是 item list。上下移動 item、Tab 切換完成狀態、Enter 插入下一項，輸入
文字會附加到 selected item。Item color 與 completion state 隨 item 一起移動。

### CSV

CSV 是二維 cell editor。方向鍵與 Tab 改變 active cell，Enter 前往下一列或在
最後新增 row，輸入或貼上的文字附加到 cell。PageUp 依內容重新計算顯示欄寬。
CSV 內容解析 嚴格且 transactional。

### Folder

Folder 是 virtual preorder tree。Directory 擁有 name 與 collapsed state；card
entry 是 weak CardId reference，不擁有或刪除 target。使用方向鍵導覽或折疊，
在 card entry 按 Enter 聚焦 target，Ctrl-A 新增 directory，Tab/Shift-Tab 對
subtree indent/outdent。將 copied card 貼到 Folder 會建立 reference。

### Text-art

Text-art 共用 plain text content，但沒有邊框，並保留精確 Glyph selection
footprint。空白也參與 hit testing。它不 soft-wrap、不 resize，內容可轉回 Glyph
anchors。

完整 editing matrices、selection modifiers 與 clipboard edge cases 見
[`keybindings.md`](keybindings.md)。

## 繪製 Glyph 並轉換 Text-art

在 BOARD 按 `i` 進入 GLYPH DRAW。輸入或貼上可顯示 Unicode；單寬字元前進一格，
雙寬字元前進兩格，space 清除目前 cell。此層保存 character anchors，不保存
terminal escape sequence，也不接受獨立 combining mark。

按 Tab 進入 GLYPH SELECT，移動另一個角落，之後可：

- Ctrl-C/Ctrl-X 複製或剪下 sparse selection；
- Delete 清除 selection；
- `H J K L` 以可移動 preview 開始 PLACE；
- `c` 將 selection 轉成 fixed Text-art card。

PLACE 會暫時隱藏來源；Enter 原子覆寫 destination，Escape 則還原來源。Selected
Text-art 使用 `c` 轉回 Glyph。兩個方向都會先驗證完整 footprint，再改變任一
model。

GLYPH edits 不參與 Ctrl-Z/Ctrl-Y history，仍以 Ctrl-S 正常儲存。

## 以正交 Edge 連接卡片

從 BOARD 或 SELECT 按 `g` 進入 EDGE browse。建立 edge：

1. 將 cursor 移到 source card 邊框並按 Enter；
2. 朝 target 移動；需要時在空白 cell 按 Enter 加入 waypoint；
3. 以 `a` 選 automatic routing，或以 `m` 選 L-shaped manual segment；
4. 在有效 target-card 邊框按 Enter，提交完整 edge。

綠色 preview 有效，紅色則 blocked。Backspace 移除最後 waypoint，Escape 取消
draft。Browse 中 Tab 循環重疊可見 segments；`m` 或 Enter 編輯 selected internal
segment；`r` 在目前 viewport 重新 routing；Delete 刪除 edge。任何 EDGE phase
按 `q` 都會捨棄尚未提交的 draft/edit 並回到 BOARD。

Edges 可以交叉而不形成 graph junction。Route points 與 CardId endpoints 會持久
保存；draft waypoints 只存在到 commit。

## 匯出 Folder

讓 Folder 成為目前 target（active、selected，或位於 cursor 下）後按 Ctrl-E。
輸入 destination parent path，按 Enter 寫出或 Escape 取消。Export 會走訪 Folder
tree 並 materialize referenced card content，不改變 Folder weak references。
匯出不受信任的 project 前請先檢查 paths。

## Agent proposals

Automation 可送出 Note、Markdown 或 Code proposal。Proposal 是 preview，不是
mutation；接受前不配置 CardId、不進 history、不標記 dirty。有 pending proposal
時，在 BOARD 或 SELECT 以 Ctrl-G 接受，Ctrl-D 可在非 export-prompt context
拒絕；其他 mode 接受時會提示先回到白板。Client recipes 見
[`automation.md`](automation.md)，framing contract 見
[`agent-protocol.md`](agent-protocol.md)。

## 下一步

- [`keybindings.md`](keybindings.md)：每個 context 的精確按鍵；
- [`automation.md`](automation.md)：screenshot、query、batch creation、
  replacement、deletion 與 proposal；
- [`building.md`](building.md)：編譯或安裝專案；
- [`architecture.md`](architecture.md)：contributor-level data flow。
