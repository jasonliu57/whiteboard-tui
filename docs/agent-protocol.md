# 本機 Agent 協定

讀者：本機 automation client 的 implementer 與 maintainer。

本文件定義 Unix socket wire contract。CLI 用法位於 [`automation.md`](automation.md)。Markdown 白板 skill 使用 `whiteboardctl` 與 `tools/whiteboard_automation`，不直接實作本協定。

## 分層

```text
whiteboard skill
  → Verification CLI
    → tools.whiteboard_automation
      → whiteboardctl
        → Unix socket
          → TUI thread / App
```

`whiteboardctl` 是參考 client。`tools.whiteboard_automation` 提供 Python subprocess adapter、typed response parser、batch encoder 與 canonical snapshot parser。

此協定是本機單一使用者介面。傳輸格式是 ASCII header 加 raw bytes body。

## Socket 與連線

預設 socket 是 `$XDG_RUNTIME_DIR/whiteboard-tui.sock`。缺少 `XDG_RUNTIME_DIR` 時使用 `/tmp/whiteboard-tui-$UID.sock`。Server 與 client 皆接受 `WHITEBOARD_TUI_SOCKET`。

Server 建立 mode `0600` 的 Unix-domain socket。事件迴圈管理八個 non-blocking client slots。

每個連線承載一個 request 與一個 response。Server 完成 response 後關閉連線。`snapshot` 的每一頁使用一條新連線。

Request 由同一條 TUI thread 依序 dispatch。每個 client slot 的 idle timeout 是 5000 ms。

`whiteboardctl` 對 connect、write 與 read 使用同一 monotonic deadline。`WHITEBOARDCTL_TIMEOUT_MS` 接受 `10..600000`，預設 5000 ms。

## Request framing

Request 結構：

```text
ASCII_HEADER LF
RAW_BODY_BYTES
```

Header words 以 ASCII space 分隔。Reference client 使用單一 space 與 canonical decimal integers。

Body 長度由 header 宣告。Server 在收到完整 body 後 dispatch request。

限制：

| 項目 | 限制 |
| --- | ---: |
| Header | 1024 bytes |
| Body | 262144 bytes |
| Response | 1048576 bytes |
| QUERY limit | 1..256 |
| SCREEN_PNG font pixels | 8..64 |
| BOARD_PNG max side | 256..2048 |

額外 bytes 回傳 `ERR trailing_bytes`。宣告 body 尚未收完便結束 write side 回傳 `ERR incomplete_request`。Idle timeout 關閉連線。

## Requests

唯讀 request：

```text
STATUS
VIEW
SCREEN_TEXT
SCREEN_PNG [PIXELS]
BOARD_PNG [MAX_SIDE [NAME|FORMAT|ID [VIEWPORT]]]
SNAPSHOT EXPECTED_REVISION_OR_- CARD_CURSOR EDGE_CURSOR GLYPH_CURSOR
GET CARD_ID
QUERY LEFT TOP RIGHT BOTTOM LIMIT
EDGES CARD_ID
PROPOSAL PROPOSAL_ID
```

Mutation 與 proposal request：

```text
CONNECT SOURCE_CARD TARGET_CARD [EXPECTED_REVISION]
DELETE_CARD CARD_ID EXPECTED_REVISION
DELETE_CARDS EXPECTED_REVISION BODY_BYTES\n<BODY>
PROPOSE NOTE|MARKDOWN|CODE X Y WIDTH HEIGHT BODY_BYTES\n<BODY>
CREATE_CARDS [EXPECTED_REVISION] BODY_BYTES\n<BODY>
REPLACE_CARD CARD_ID EXPECTED_REVISION WIDTH HEIGHT BODY_BYTES\n<BODY>
```

`DELETE_CARDS` body 每個非空行是一個 CardId。

`CREATE_CARDS` body 每個非空行是 `FORMAT X Y WIDTH HEIGHT`。

`PROPOSE` 與 `REPLACE_CARD` 文字使用可顯示的 strict UTF-8。

`REPLACE_CARD` body encoding 由 card 的 SaveFormat 決定：plain text、Markdown、Todo text、strict CSV 或 tab-separated Folder tree。

## Response framing

成功 response 以 `OK REVISION` 開頭。失敗 response 使用：

```text
ERR REASON [DETAIL]
```

所有文字 header 以 LF 結尾。Server 產生 canonical decimal integers。Binary 與 card bodies 依宣告 byte length 解析。

### Status 與 view

```text
OK REVISION STATUS LIVE_CARDS LIVE_EDGES DIRTY
OK REVISION VIEW MODE VIEW_X VIEW_Y VIEW_WIDTH VIEW_HEIGHT CURSOR_X CURSOR_Y SELECTED_OR_-
```

`DIRTY` 是 `0` 或 `1`。`MODE` 是 `BOARD`、`ACTIVE`、`SELECT`、`EDGE` 或 `GLYPH`。

### Screenshots

```text
OK REVISION SCREEN_TEXT WIDTH HEIGHT BODY_BYTES\n<BODY>
OK REVISION SCREEN_PNG WIDTH HEIGHT BODY_BYTES\n<PNG>
OK REVISION BOARD_PNG WIDTH HEIGHT BODY_BYTES\n<PNG>
```

Body 長度恰好等於 `BODY_BYTES`。

### Cards

`GET` response：

```text
OK REVISION CARD CARD_ID FORMAT X Y WIDTH HEIGHT BODY_BYTES
<BODY_BYTES>
END
```

`QUERY` response：

```text
OK REVISION QUERY COUNT
CARD CARD_ID FORMAT X Y WIDTH HEIGHT BODY_BYTES
<BODY_BYTES>
...
END
```

每個 card body 後面有一個 framing LF。Body 內部 newline 屬於宣告 bytes。

協定 major 2：內容交換格式由 FORMAT 的 registry 契約推導，卡片沒有儲存種類或路徑。

Folder body：

```text
ROOT<TAB>NAME
DEPTH<TAB>DIR<TAB>-<TAB>COLLAPSED<TAB>NAME
DEPTH<TAB>CARD<TAB>CARD_ID<TAB>0<TAB>NAME
```

### Edges

```text
OK REVISION EDGES CARD_ID COUNT
EDGE EDGE_ID SOURCE_CARD SOURCE_SIDE TARGET_CARD TARGET_SIDE MODE STATE LEFT TOP RIGHT BOTTOM POINT_COUNT
POINT X Y
...
END
```

Side：`0=Top`、`1=Right`、`2=Bottom`、`3=Left`。

Mode：`0=Automatic`、`1=Manual`。State：`0=Ready`、`1=Blocked`。

### Proposals

```text
OK REVISION PROPOSAL PROPOSAL_ID PENDING
OK REVISION PROPOSAL PROPOSAL_ID REJECTED
OK REVISION PROPOSAL PROPOSAL_ID COMMITTED CARD_ID
```

### Mutations

```text
OK REVISION CONNECT EDGE_ID
OK REVISION DELETE_CARD CARD_ID
OK REVISION DELETE_CARDS COUNT
OK REVISION CREATE_CARDS COUNT FIRST_CARD_ID
OK REVISION REPLACE_CARD CARD_ID
```

`REVISION` 是 mutation commit 後的 revision。

## Transaction semantics

Socket parser 先建立 typed request。TUI 在 mutation 前驗證 revision、IDs、formats、dimensions、coordinates 與 content。

成功 mutation 透過 `App` commit，一次增加一個 revision 並加入一筆 history item。Rejected mutation 保持 document、indexes、history、dirty 與 revision。

`REPLACE_CARD`、`DELETE_CARD` 與 `DELETE_CARDS` 必須帶 expected revision。`CREATE_CARDS` 與 `CONNECT` 支援 optional expected revision。固定 automation client 會提供 revision。

Revision mismatch：

```text
ERR stale_revision CURRENT_REVISION
```

Proposal 是 pending TUI preview。使用者接受後才 commit。Server 保存最新 64 筆 proposal results。

## Canonical snapshot

第一頁 request：

```text
SNAPSHOT - 0 0 0
```

Page response：

```text
OK REVISION SNAPSHOT 2 NEXT_CARD NEXT_EDGE NEXT_GLYPH DONE BODY_BYTES
<BODY_BYTES>
```

Client 鎖定第一頁 `REVISION`。後續 request 帶入該 revision 與 server 回傳的三個 cursors。`DONE` 是 `0` 或 `1`。Cursors 是 opaque monotonic positions。

`whiteboardctl snapshot --output` 依序寫入：

```text
WHITEBOARD-SNAPSHOT 2
<all page bodies>
END
```

Page bodies 依序包含 `META`、`CARD`、`EDGE` 與 `GLYPH` records。Card 與 edge 依 slot ID 排序。Glyph 依 `(y,x)` 排序。

CARD record 為 `CARD ID FORMAT X Y WIDTH HEIGHT PAYLOAD_BYTES`，後接內容交換 payload
與 framing LF。Parser 直接切取 bytes。Snapshot 涵蓋 card ID、格式、位置、可見尺寸、
交換內容，以及 edges、glyphs 與 tombstone slot counts。

Card payload 不包含文字樣式、LanguageId、Todo 樣式、CSV 欄寬與儲存格樣式。
Snapshot bytes 或 SHA-256 相等，只表示上述涵蓋欄位一致，不能證明全部持久資料相同。
完整保存使用 [`file-format.md`](file-format.md) 定義的 `.tiwb`。

`whiteboardctl` 使用 sibling temporary file，完整成功後 atomic rename。

## Client implementation

Repository 內的 Python automation 使用：

- `tools/whiteboard_automation/client.py`
- `tools/whiteboard_automation/protocol.py`
- `tools/whiteboard_automation/snapshot.py`
- `tools/whiteboard_automation/batch.py`

Client 將 response 保持為 bytes，驗證完整 framing，再建立 typed models。Mutation timeout 與 transport failure 標記為 outcome unknown。

## Compatibility

公開協定目前為 major 2，遵循 semantic versioning。協定變更同步更新本文件、generated limits、server、reference client、shared Python parser 與 tests。不相容變更使用新的 major release。
