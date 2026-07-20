# 使用 `whiteboardctl` 自動化

讀者：以 script 自動化一個正在執行的 whiteboardTUI instance 的使用者。

本文件擁有 CLI commands、body formats 與實用 recipes。精確 socket framing、byte
limits、parser rejection rules 與 transaction contract 由
[`agent-protocol.md`](agent-protocol.md) 擁有；內部 ownership 由
[`architecture.md`](architecture.md) 擁有。

## Automation 分層

Repository 內的固定 Python automation 共用 `tools/whiteboard_automation`：

- `client.py` 執行 `whiteboardctl` 與 `whiteboard-inspect`；
- `protocol.py` 解析 typed responses；
- `snapshot.py` 解析 canonical snapshot；
- `batch.py` 編解碼 card batches；
- `files.py` 提供 atomic output。

Automation scripts 透過這層呼叫 CLI。Script 保持 raw bytes，無需 JavaScript
`TextDecoder` 或 Base64 adapter。

## 連接 instance

TUI 啟動本機 Unix-domain socket。預設使用
`$XDG_RUNTIME_DIR/whiteboard-tui.sock`，否則退回
`/tmp/whiteboard-tui-$UID.sock`。同時執行多個白板時，server 與 client 要使用
相同 override：

```sh
WHITEBOARD_TUI_SOCKET=/tmp/project-a.sock \
  whiteboard_tui project-a.tiwb

WHITEBOARD_TUI_SOCKET=/tmp/project-a.sock \
  whiteboardctl status
```

`WHITEBOARDCTL_TIMEOUT_MS` 會改變 connect/write/read 共用的 monotonic
deadline。接受 10–600000 ms；無效值使用 5000 ms。

除 `snapshot` 內部分頁外，每次 `whiteboardctl` invocation 只開一個 connection、
送一個 request、讀一個 response 後關閉。`ERR reason` 會寫至 stderr，client 以
nonzero 結束。不要把此
socket 當成 remote authentication boundary。

## 命令摘要

```text
whiteboardctl status
whiteboardctl view
whiteboardctl screen-text
whiteboardctl screen-png [FONT_PIXELS]
whiteboardctl board-png [MAX_SIDE] [name|format|id] [viewport]
whiteboardctl snapshot --output FILE
whiteboardctl get CARD
whiteboardctl query LEFT TOP RIGHT BOTTOM [LIMIT]
whiteboardctl edges CARD
whiteboardctl connect SOURCE_CARD TARGET_CARD [REVISION]
whiteboardctl delete-card CARD REVISION
whiteboardctl delete-cards REVISION < FILE
whiteboardctl proposal ID
whiteboardctl propose note|markdown|code X Y W H < FILE
whiteboardctl create-cards [REVISION] < FILE
whiteboardctl replace-card CARD REVISION W H < FILE
```

## 檢查執行中白板

`status` 回傳目前 high-level TUI status。`view` 回報 automation 所需的 viewport
與 revision 資訊。

取得一張 card，或 query 一個 half-open 世界 rectangle：

```sh
whiteboardctl get 42
whiteboardctl query -100 -50 200 150 64
whiteboardctl edges 42
```

`query` 使用 card spatial index。LIMIT 預設 64，可接受 1–256。`get` 與
`query` 依 byte length frame card bodies，因此 body 可含 newline。進行 replacement
或 deletion 前請保留回傳 revision。

`edges` 回報 requested CardId 的 incident endpoints、route state/bounds 與
normalized orthogonal route points。

Revision-locked 的 canonical snapshot 以 atomic output 寫入檔案，供交換內容與幾何核對：

```sh
whiteboardctl snapshot --output live.snapshot
whiteboard-inspect snapshot board.tiwb --output disk.snapshot
```

第一個命令在內部分頁並拒絕途中 revision 改變；第二個命令唯讀載入獨立 `.tiwb`。
兩者使用同一 canonical serializer，可直接做 byte comparison 或 SHA-256。
相等只表示 snapshot 涵蓋的欄位一致，不代表全部持久資料相同；欄位範圍見
[`agent-protocol.md`](agent-protocol.md#canonical-snapshot)。完整保存使用 `.tiwb`。
不要用 shell command substitution 承載 snapshot bytes。

## 擷取 terminal 或白板影像

擷取最後實際顯示的 framebuffer：

```sh
whiteboardctl screen-text > screen.txt
whiteboardctl screen-png > screen.png
whiteboardctl screen-png 32 > screen-32px.png
```

`screen-text` 移除 ANSI style，但保留 UTF-8 cell geometry 與 trailing spaces。
`screen-png` 接受 8–64 的 font pixel height，預設 24。以
`WHITEBOARD_TUI_SCREENSHOT_FONT` 選擇其他 monospaced Unicode font。

不 repaint TUI，直接 render 完整白板 thumbnail：

```sh
whiteboardctl board-png > board.png
whiteboardctl board-png 1200 format > board-formats.png
whiteboardctl board-png 1200 id viewport > board-ids.png
```

Maximum side 接受 256–2048 pixels，預設 1600。Label modes：

- `name`：Folder root name，其餘卡片使用格式名稱；
- `format`：stable format name；
- `id`：decimal CardId。

選用 `viewport` overlay 會標記 visible portion，不改 board bounds 或 scale。
Board thumbnail 包含 cards 與 saved edges，不含 Glyph、cursor、status line 或
proposals。

## 連接兩張卡片

```sh
whiteboardctl connect 12 19 108
```

TUI 依 card centers 相對位置選 facing ports、置中 finite route viewport，並呼叫
既有 automatic router 一次。成功會新增一條 edge、一筆 history 與一次 revision。
Missing/same endpoints 或無法 routing 都不改 model。`no_route_in_view` 失敗後
UI 可能仍停在置中位置。
REVISION 是 optional optimistic guard；自動 materializer 應一律提供。

## 批次建立空白卡片

`create-cards` 每個非空白行接受一筆 geometry record：

```sh
whiteboardctl create-cards 108 <<'EOF'
note 0 0 32 12
markdown 40 0 40 14
code 0 20 48 16
todo 56 20 32 12
csv 0 44 42 12
folder 50 44 36 14
text-art 94 44 24 8
EOF
```

每筆為 `FORMAT X Y WIDTH HEIGHT`。第一次建立 card 前會解析完整 body，驗證所有
formats、dimensions、coordinates 與 coordinate additions。成功時依 input order
配置 CardIds，整批只 commit 一筆 history 與一次 revision。Cards 可以重疊。

Text-art dimensions 是 visible fixed footprint；factory 會轉成 internal layout
metadata。

REVISION 可省略以相容互動式 scripts；可續跑的 materializer 應提供，避免在
baseline 與 batch commit 之間接受另一筆 mutation。

## 安全取代卡片內容

先讀取目前 revision，再帶 expected revision 送 replacement：

```sh
whiteboardctl get 42
whiteboardctl replace-card 42 108 40 14 < replacement.md
```

既有 card 決定 StaticFormatId、LanguageId、SaveFormat、position。
Replacement 改 semantic content 與 visible extent，但不轉換 card type。Stale
revision 會回傳目前 revision，且不 commit。

Body encoding 依既有 card：

| Format | Replacement body |
|---|---|
| Note、Markdown、Code、Text-art | UTF-8 text |
| Todo | `- [ ] text` / `- [x] text` lines |
| CSV | strict CSV |
| Folder | `get` 回傳的 tab-separated `ROOT`、`DIR`、`CARD` records |

Parsing、format limits 與 geometry 都在 temporary state 驗證。Folder `CARD`
records 保存 weak CardId references。成功 replacement 會將 content、spatial geometry、incident-edge geometry、
active syntax state、history 與 revision 作為一個 transaction 更新。內容在
正常 project save 時完整寫入單一 `.tiwb`。

## Transactional delete

以 expected revision 刪除一張 card：

```sh
whiteboardctl delete-card 42 108
```

Batch 每個非空白行一個 decimal CardId：

```sh
whiteboardctl delete-cards 108 <<'EOF'
4
8
12
EOF
```

Batch 在 mutation 前拒絕 malformed、duplicate、missing 或 stale IDs。成功只
建立一筆 history 並增加一次 revision。Deletion 留下 CardId tombstone、保留
dormant incident EdgeIds 與 Folder weak references。

## 送出由使用者核准的 proposal

Proposal 可帶 content，但不直接 mutation Board：

```sh
whiteboardctl propose markdown 10 5 40 14 < note.md
whiteboardctl proposal PROPOSAL_ID
```

Proposal formats 只有 Note、Markdown 與 C++ Code。TUI 顯示一個 pending green
preview。使用者以 Ctrl-G 接受、Ctrl-D 拒絕。只有接受時才配置 CardId、建立
history、標記 dirty 並增加 revision。最新 64 筆 proposal results 可查詢。

## Text-art renderer workflow

Python renderer 將 semantic JSON 編譯成 deterministic text-art generation。
`frozen_generation.py` 統一驗證 manifest、payload、terminal-cell geometry 與
create batch。Standalone materializer 再透過 shared client 寫入 Board。

```sh
python3 -m tools.textart_notes.render_note --help
python3 -m tools.textart_notes.materialize_textart --help
```

Renderer manifest path 與 immutability 由 [`file-format.md`](file-format.md) 規定。
Source-tree 執行方式見 [`building.md`](building.md)。

## Markdown 白板 skill workflow

Source tree 隨附 `.agents/skills/whiteboard-markdown-mind-map/`。這個 skill 將來源
Markdown、原生 card formats、text-art renderers、Imagegen 版面提案與最終驗證串成
一條 run。

主要入口：

```sh
python3 .agents/skills/whiteboard-markdown-mind-map/scripts/mindmap_tools.py --help
python3 .agents/skills/whiteboard-markdown-mind-map/scripts/verify_whiteboard.py --help
```

`mindmap_tools.py` 編譯 `plan.md`、renderer generations、unit layouts 與 card
batches。Renderer manifest validation 直接使用 `tools.textart_notes.frozen_generation`。

`verify_whiteboard.py preview` 管理 provisional cards 與 PNG cleanup。
`materialize` 管理 geometry preflight、baseline、multi-format cards、payloads、edges
與 mutation journal。`final` 比對 artifacts、live snapshot、disk snapshot 與 PNG。

Skill verifier 與 standalone text-art materializer 共用同一 client、response parsers、
batch encoders、card-format contract 與 Unicode cell-width implementation。

所有連接 Board 的 Python 操作命令都必須以 `--whiteboardctl` 指定執行檔路徑。
`final` 與 `check-attestation` 另須以 `--whiteboard-inspect` 指定唯讀工具路徑。
`preflight` 與 materializer 的 `--check-only` 可直接檢查檔案。

## Script 安全規則

- 將每個 response/revision 視為 per-instance state；不可跨 socket 或 board 重用。
- 依 declared byte length 解析 `CARD` body，絕不依 newline。
- Script 自己的資料驗證完成後才送出完整 batch input。
- 收到 `stale_revision` 時重新取得目前 state 並重評操作，不要盲目 retry。
- Automation script 不應移除 socket path、白板檔案。
- 會覆寫或刪除資料的測試只使用 copied boards 與 disposable output paths。

若要實作不依賴 `whiteboardctl` 的 client，請繼續閱讀
[`agent-protocol.md`](agent-protocol.md)。
