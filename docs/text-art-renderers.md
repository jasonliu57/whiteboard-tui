# 文字繪渲染器完整說明

本文件說明 whiteboardTUI 目前可執行的 21 種正式文字繪筆記
renderer、13 個共享布局模組、適用場景、輸入範例位置、統一 CLI、輸出
契約，以及安全寫入 `text-art` card 的方式。

正式筆記 renderer 位於 `tools/textart_notes/`。每個 renderer 都只讀取
UTF-8 JSON 並輸出 `payloads/*.txt` 與 `manifest.json`；只有
`materialize_textart.py` 可以連接明確指定的 Board socket。

## 1. 實作狀態

| 類型 | 狀態 | 說明 |
| --- | --- | --- |
| `tools/textart_notes/core/` | 已實作 | Terminal cell、換行、Canvas、框線、路由、主題、CLI、manifest 與驗證 |
| `tools/textart_notes/layouts/` | 已實作 | 13 個可重用幾何／分頁模組；細節見第 8 節 |
| 21 種正式筆記 renderer | 已實作 | 各有獨立 Python 入口、fixture、正式測試與至少兩個 theme golden |
| `fishbone_note.py` | 已實作 | 正式 Fishbone adapter；共享 Spine layout，支援三種 layout variant 與 branch-boundary split |
| `render_note.py` | 已實作 | 以 `--style` 統一分派全部 21 種 renderer |
| `materialize_textart.py` | 已實作 | 嚴格 preflight 後將 manifest 寫入明確指定的 Board socket |

每個 renderer 由自己的語意、golden 與決定性測試負責。共用 CLI 只測一次，
每個公開入口各有一次 smoke，Board integration 使用代表性 renderer 驗證完整
save/reload 路徑。

## 2. 核心名詞

### Renderer

Renderer 理解特定筆記法的語意資料，例如康乃爾筆記的線索、正文與摘要。它負責：

1. 驗證並正規化輸入。
2. 決定使用哪一個或哪些布局引擎。
3. 將文字量測成 terminal cell 尺寸。
4. 將布局結果畫成純文字。
5. 輸出 payload 與 card manifest。

### Layout engine

布局引擎只處理幾何，不直接決定文字內容或框線主題。它接收已量測的節點、關係與限制，輸出：

```text
node rectangles
region rectangles
ports
routed edge points
page or card assignments
```

### Text-art renderer

Text-art renderer 將布局結果光柵化為 terminal cells，包括：

- 框線。
- 箭頭。
- 交會 glyph。
- 已換行的文字。
- 空白與對齊。

### Materializer

Materializer 是唯一應接觸 live Board 的層。各 renderer 本身只產生檔案，不直接呼叫 `whiteboardctl`。

Materializer 必須拒絕任何非 `text-art` 格式。

## 3. 共用處理流程

```text
style-specific JSON
        │
        ▼
note renderer / adapter
        │
        ▼
normalize semantic data
        │
        ▼
measure terminal-cell extents
        │
        ▼
layout engine
        │
        ▼
typed layout result (rectangles / pages / routes)
        │
        ▼
text-art painter
        │
        ▼
validate / split into cards
        │
        ▼
payloads/*.txt + manifest.json
        │
        ▼
materialize_textart.py
        │
        ▼
whiteboardTUI text-art cards
```

布局與繪製分離後，同一份幾何可以切換 `ascii`、`unicode-light` 或 `unicode-rich`，不必重新計算節點位置。

## 4. 共用幾何模型

正式實作沒有強迫所有布局回傳一個過度抽象的 `Scene`。不同問題保留
最小且型別化的結果，例如 `MeasuredRow`、`ClusterLayout`、`FlowLayout`、
`RadialScene`、`DirectedScene`。共同的幾何語彙是：

- 以 terminal cell 表示的整數 rectangle 與 extent。
- 穩定 ID、作者順序與明確的 card/page assignment。
- Router 使用的 ports、保留格、直角 path 與 label rectangle。
- 可序列化到 card `metadata` 的 provenance 與 split facts。

Renderer 在進入布局前先用共享 cell-width／wrap 模組量測內容；布局模組
不猜字型寬度。布局完成後由共享 `Canvas` 將 rectangle 與 path 光柵化，
最後由 `validate_result()` 重新核對 payload、extent、ID 與相對座標。

## 5. 共用 text-art 限制

whiteboardTUI 的 `text-art` card 有以下特性：

- 不使用 soft-wrap；換行必須在 renderer 完成。
- 可見 extent 最大為 `160×100` terminal cells。
- 第一行不會自動成為標題。
- 格式不會自動畫一般卡片邊框；需要外框時必須畫進 payload。
- 卡片尺寸固定，payload 與 manifest 必須使用相同 cell geometry。
- 行首、行內空格與空白列有幾何意義。
- 預設避免 Emoji，因為不同終端可能給出不同顯示寬度。

共用寬度引擎必須：

- 一般英文與窄字元計為一格。
- 中文及 East Asian wide/full-width 字元計為兩格。
- Combining characters 計為零格並附著於前一個 anchor。
- Tab 依目前欄位套用 tab stop，不應永遠視為固定四個空格。
- 禁止把新 glyph 寫入雙寬字元的 continuation cell。

若內容超過 `160×100`，renderer 只在合法語意邊界分卡；不可切割的
語意單位（例如正式 flowchart 的完整 DAG）必須回報 FitError／exit 1。
任何 renderer 都不得為了 fit 而裁切文字或圖形。

## 6. 共用主題

| 主題 | 使用場景 | 建議 glyph |
| --- | --- | --- |
| `ascii` | SSH、舊終端、字型不完整 | `+ - | / \\ > <` |
| `unicode-light` | 一般 whiteboardTUI 筆記 | `┌ ┐ └ ┘ ─ │ ├ ┤ ┬ ┴ ┼` |
| `unicode-rich` | 強調框、主幹、密度與狀態 | `╔ ╗ ╚ ╝ ═ ║ ┏ ┓ ┗ ┛ ━ ┃ ░ ▒ ▓` |

主題只能改變繪製 glyph，不應改變輸入資料或布局語意。

## 7. 布局引擎快速選擇

| 問題特徵 | 首選引擎 | 實作位置／狀態 |
| --- | --- | --- |
| 多組原因匯向單一結果 | Spine | `layouts/spine.py` + `fishbone_note.py` |
| 單一有序路徑 | Chain | `layouts/chain.py` |
| 任意多對多關係或循環 | Directed Graph | `layouts/directed_graph.py` |
| 嚴格父子關係 | Hierarchy | `layouts/hierarchy.py` |
| 中央主題向外聯想 | Radial | `layouts/radial.py` |
| 規則列欄 | Grid | `layouts/grid.py` |
| 只強調分群與接近 | Cluster | `layouts/cluster.py` |
| 以兩個維度定位項目 | Axis | `layouts/axis.py` |
| 有判斷、分支與合流 | Flow | `layouts/flow.py` |
| 時間加角色或階段 | Timeline + Lanes | `layouts/timeline.py`、`layouts/lanes.py` |
| 左右內容逐項配對 | Evidence Pair | `layouts/evidence_pair.py` |
| 固定語意欄位與模板 | Schema Blocks | `layouts/schema_blocks.py` |
| 強調集合交集 | Set / Venn | 尚無正式布局或 renderer；改用 Matrix |

## 8. 布局引擎使用場景

### 8.1 Spine 主幹型

**主要用途**：多組原因共同導向一個結果。

**適用格式**：

- 魚骨圖。
- Ishikawa 根因分析。
- 品質問題分類。
- 風險來源整理。

**輸入形狀**：

```json
{
  "effect": "交付延遲",
  "branches": [
    {"name": "流程", "side": "top", "nodes": ["審批過多", "需求反覆"]}
  ]
}
```

**布局方式**：

1. Adapter 先量測每條完整 branch，建立帶 `key/side/width/height` 的
   `SpineItem`。
2. `place_spine()` 保留輸入順序，讓每條 branch 擁有一段連續水平主幹；
   top items bottom-align、bottom items top-align 到同一條 spine。
3. Caller 提供 arrow width、effect rectangle 與 effect entry row；布局回傳
   branch placements、joint x、spine y 及 effect 座標。
4. 基礎 Spine 不處理文字、theme、分卡或繪製；正式 Fishbone adapter 才負責
   三種 layout variant、glyph、連續 branch pagination 與 metadata。

**適合時機**：讀者需要從分類原因一路讀向結果。

**不適合時機**：原因之間有循環、交叉關係或多個結果；此時應使用 Directed Graph。

**現行實作**：正式入口為 `tools/textart_notes/fishbone_note.py`，共享幾何為
`tools/textart_notes/layouts/spine.py`。

### 8.2 Chain 鏈式

**主要用途**：呈現嚴格順序或單一路徑。

**適用格式**：

- 五個為什麼。
- 因果鏈。
- 簡單時間軸。
- 句子式筆記。
- Roadmap。

**布局方式**：

- `measure_chain()` 接收已排序的 `ChainEntry(key, prefix, text)`，依固定寬度與
  實際起始欄位量測每個 entry。
- 換行後的 continuation 對齊本文起始欄；prefix 與輸入順序都保持不變。
- `paginate_chain()` 將量測完成且不可拆分的 entry 由上而下貪婪分頁，並把
  `reserved_rows` 與 `separator_rows` 算入高度；單一 entry 過高時回報
  `FitError`。
- 此基礎引擎不畫水平鏈、蛇形鏈或箭頭；線條與符號由各 renderer adapter
  負責。

**適合時機**：資料的核心語意是「先後順序」。

**不適合時機**：有多個 decision branch 時改用 Flow；有循環時改用 Directed Graph。

### 8.3 Directed Graph 有向圖

**主要用途**：呈現任意方向關係、循環與多對多連結。

**適用格式**：

- 因果迴路。
- 概念圖。
- 關係網絡。
- 系統相依圖。
- 複雜論證圖。

**布局方式**：

1. 找出 strongly connected components。
2. 將 component graph 分層。
3. 在每層內排序以降低 edge crossings。
4. 分配 node rectangles。
5. 以 ports 和 orthogonal router 產生 edge path。
6. 將 back edge 安排到主要圖形外圍。

**適合時機**：關係比閱讀順序更重要。

**不適合時機**：資料其實是嚴格樹狀或單一路徑；專用引擎會更緊湊。

**主要風險**：節點與 edge 過多時，單張 text-art 會迅速失去可讀性。應依 component 或主題分卡。

### 8.4 Hierarchy 階層型

**主要用途**：呈現父子結構、分解關係與層級論證。

**適用格式**：

- 樹狀圖。
- 議題樹。
- 邏輯樹。
- 金字塔。
- 大綱式筆記。
- 嚴格樹狀論證圖。

**布局方式**：

- `analyze_hierarchy()` 驗證 strict rooted tree：node key 唯一、每個非 root
  只有一個 parent、不可有 cycle 或 orphan，且不得超過深度上限。
- 引擎回傳 `parent`、`depth`、`sibling_index`、preorder 與 `subtree_ids`
  等 `HierarchyFacts`；輸入的 child order 是規範順序，不會自行重排。
- `flatten_hierarchy()` 則把巢狀輸入正規化成穩定的 preorder rows。
- 此模組只分析階層，不配置最終座標；Radial 或個別 renderer adapter 再使用
  這些 facts 產生幾何。

**適合時機**：每個節點只有一個主要 parent。

**不適合時機**：同一節點有多個 parent、cross-link 或循環；改用 Directed Graph。

### 8.5 Radial 放射型

**主要用途**：由中央主題向多方向延伸聯想。

**適用格式**：

- 心智圖。
- 生態系圖。
- 中央概念與周邊面向。

**布局方式**：

- root 使用中央 anchor；第一層 child 依 sibling index 交替放到右、左兩側。
- 後代沿用第一層 branch 的方向，並依 depth 進入下一個水平 ring；已量測的
  rectangle width 會決定相鄰 ring 的 x offset。
- 各 subtree band 依輸入順序垂直堆疊，連線使用 orthogonal spokes；也可只產生
  one-ring summary。
- 現行實作不分配上／下象限、不計算角度，也不是 aspect-aware radial solver。

**適合時機**：讀者應先看到中心，再自由探索各分支。

**不適合時機**：需要嚴格比較層級或精確流程順序。

**分卡原則**：這是 fit-driven 決策，沒有固定分支數或深度三層門檻。
Renderer 先嘗試容納完整 subtree；放不下時，以仍可容納的 child summaries
組成一張或多張 overview，再遞迴處理需要完整展開的 child branch。連 anchor
本身或不可拆 leaf 都放不下時回報 `FitError`。

### 8.6 Grid 網格型

**主要用途**：規則的列、欄、lane 或固定格子。

**適用格式**：

- 蓮花圖。
- 比較矩陣。
- SWOT。
- 5W1H。
- 六頂帽。
- 表格比較。
- 三欄式筆記。
- 看板。

**布局方式**：

1. Adapter 先定義欄位的 minimum、weight 或 measured demand；
   `allocate_widths()`、`allocate_weighted()` 或
   `allocate_toward_demands()` 在總 cell budget 內做確定性整數分配。
2. `measure_row()` 依已分配欄寬、alignment、wrap 設定與實際起始欄位量測
   cells；row height 取該列最高的 wrapped cell。
3. `paginate_rows()` 只在完整 row 邊界垂直分頁；
   `split_column_groups()` 可在保留 key column 的前提下水平分組。
4. `render_table()` 才負責封閉表格的 frame、separator 與內容；基礎量測與寬度
   分配函式本身不畫框。跨頁策略與欄位語意仍由 adapter 決定。

**適合時機**：位置本身有固定的 row/column 意義。

**不適合時機**：節點之間的關係無法用列欄表示。

**分卡原則**：表格過寬時保留 key column，將其餘欄位分成多頁；過高時重複 header 並切分 rows。

### 8.7 Cluster 群集型

**主要用途**：顯示哪些項目彼此接近或同屬一組。

**適用格式**：

- 親和圖。
- 卡片分類。
- 群集圖。
- 方框筆記。
- 視覺速記的內容區塊。

**布局方式**：

- Adapter 必須先完成分群並依規範順序提供 items；此引擎不從 tag 或
  similarity 推論群組。
- 每個 item 提供一個以上的 measured size variant；variant 可依實際 x 欄位
  phase 選用，以正確處理 tab 寬度。
- `pack_shelves()` 以固定 horizontal／vertical gutter 做穩定的 first-fit
  shelf packing，且永不重排輸入。
- item 在空 shelf 仍超寬時回報 `FitError`。群組 region、外框、分頁與分卡由
  adapter 負責；現行實作沒有 guillotine packing。

**適合時機**：接近與分組比 edge 更重要。

**不適合時機**：讀者必須追蹤精確關係；改用 Directed Graph。

### 8.8 Set 集合型

> 可用性：目前沒有正式 Set/Venn layout 或筆記 renderer。以下是選型
> 邊界，不是可執行介面；二維 membership 請先用 `matrix_note.py`。

**主要用途**：表現 membership、intersection、union 與 difference。

**適用格式**：

- 二集合或三集合維恩圖。
- 集合包含關係。
- 共同特徵整理。

**布局方式**：

- 二集合使用兩個重疊橢圓或 rounded regions。
- 三集合使用固定三區模板。
- 元素依 membership signature 放入對應區域。

**適合時機**：交集本身就是主要問題。

**不適合時機**：四個以上集合；文字繪中交疊區難以辨識，應改用 membership matrix。

### 8.9 Axis 座標型

**主要用途**：依兩個獨立維度定位項目。

**適用格式**：

- 四象限。
- 利害關係人地圖。
- 風險矩陣。
- 優先矩陣。

**輸入形狀**：每個項目至少包含 `x_value`、`y_value` 和 label。

**布局方式**：

- 引擎接收精確的 `Fraction`、inclusive `AxisRange` 與 `AxisPoint`。
- `quantize_points()` 以 exact rational 與 half-up rounding 把 x/y 映射到整數
  plot cells；y 軸方向會反轉以符合 terminal row 座標。
- 多個 point 落在同一 cell 時會形成 collision group，保留第一次出現的 cell
  順序與該 cell 內的輸入順序。
- 軸線、marker、legend 與 collision label list 都由 renderer adapter 繪製；
  基礎 Axis 引擎不會自動位移重疊標籤。

**適合時機**：位置代表量化或序位意義。

**不適合時機**：只想表示一般分群；Cluster 會更自然。

### 8.10 Flow 流程型

**主要用途**：呈現有開始、處理、判斷、分支與合流的程序。

**適用格式**：

- 流程圖。
- 泳道圖。
- 演算法步驟。
- 事件處理流程。

**布局方式**：

- `layer_dag()` 驗證 DAG，使用 longest-path 分層，再依 branch rank 與作者輸入
  順序穩定排列同層節點。
- `place_flow()` 目前只做 top-down placement：每層的 measured rectangles
  置中，並遵守左右 clearance、layer gap 與 node gap。
- 基礎 Flow 不定義 node kind、port、route 或 glyph。正式 `flowchart` adapter
  只接受 `start`、`process`、`decision`、`end`，並負責 port 與 decision edge
  label 規則；路徑交由共用 orthogonal router。
- 正式流程圖視為一張不可拆分的 diagram；無法容納時回報 `FitError`，不裁切。

**適合時機**：讀者需要依箭頭實際執行或檢查流程。

**不適合時機**：只有簡單順序時 Chain 輸出更緊湊。

### 8.11 Lane Timeline

**主要用途**：同時呈現時間以及角色、階段、通道或接觸點。

**適用格式**：

- 多角色時間軸。
- 旅程圖。
- 病例紀錄。
- 專案演進。
- 日誌彙總。

**布局方式**：

- 一個 axis 表示時間。
- 另一個 axis 分配 lanes。
- 支援 ordinal stage 與 proportional time 兩種模式。
- 同一時間的事件可在不同 lane 垂直對齊。

**適合時機**：除了先後順序，還需要知道「誰」或「在哪個階段」。

**不適合時機**：只有單一路徑；Chain 會更簡潔。

**現行實作**：時間尺度由 `layouts/timeline.py` 計算；同步 lane bands
由 `layouts/lanes.py` 計算。`timeline_note.py`、`journal_note.py` 與
`kanban_note.py` 依需要重用其中一個或兩個模組。

### 8.12 Evidence Pair

**主要用途**：逐項對齊左右兩側的證據、原文、解釋或立場。

**適用格式**：

- 雙欄證據。
- 正反表。
- 左右分欄筆記。
- 批註式筆記。
- 康乃爾筆記的 cue/note 區。

**布局方式**：

- `allocate_pair_widths()` 依 adapter 提供的左右權重精確分配總寬度；
  `measure_pairs()`／`measure_pairs_at_widths()` 再透過 Grid 量測左右 cells，
  pair height 取兩側 wrapped height 最大值。
- `resolve_source_anchors()` 解析 inclusive source ranges，保留輸入順序與互相
  overlap 的 ranges，不排序或合併。
- Divider、relation marker、來源標記與 annotation 線條都由 renderer adapter
  繪製，不是 Evidence Pair 基礎布局自動產生。

**適合時機**：左右內容必須一一對應。

**不適合時機**：只是獨立多欄資料；使用 Grid。

### 8.13 Schema Blocks

**主要用途**：依固定語意模板配置區塊。

**適用格式**：

- SCQA。
- 5W2H。
- 康乃爾筆記。
- 填空模板。
- 摘要卡片。
- 問答卡片。

**布局方式**：

- 引擎接收已量測的 `Block(key, lines, repeat_header)`；不解析欄位語意。
- `place_blocks()` 從指定 `start_y` 起，以固定 gap 由上而下堆疊完整 blocks。
- `split_blocks()` 在 `max_height - reserved_rows` 內貪婪分頁，只在完整 block
  邊界切分；單一 block 過高時回報 `FitError`。
- 現行基礎模組不拆 block，也不推論 named region、比例或 sizing mode；欄位
  label、frame 與跨卡 repeated header 由各 renderer adapter 負責。

**適合時機**：欄位名稱和閱讀順序穩定。

**不適合時機**：內容關係自由且需要自動發現布局。

## 9. 筆記渲染器使用場景

以下 21 個 renderer 都已可執行。`--style` 是統一 dispatcher 的 key；
每個 fixture 位於 `tools/textart_notes/tests/fixtures/<fixture>/input.json`。

| 筆記樣式 | `--style`／fixture | 正式腳本 | 主要幾何 | Card 粒度 |
| --- | --- | --- | --- | --- |
| 大綱式 | `outline` | `outline_note.py` | Tree adapter | 完整 branch／subtree |
| 康乃爾 | `cornell` | `cornell_note.py` | Schema Blocks + Evidence Pair + Grid | 完整 cue/note pair |
| 心智圖 | `mindmap` | `mindmap_note.py` | Hierarchy + Radial | overview 與完整 branch |
| 概念圖 | `concept-map`／`concept_map` | `concept_map_note.py` | Directed Graph | 完整 weak component |
| 流程圖 | `flowchart` | `flowchart_note.py` | Flow | 整張 DAG；不可切割 |
| 表格比較 | `comparison` | `comparison_table_note.py` | Grid | 同步 row bands／column groups |
| 時間軸 | `timeline` | `timeline_note.py` | Timeline + Lanes | 完整日期／stage group |
| 問答式 | `qa` | `qa_note.py` | Schema Blocks | 完整 item 或 Q/A 對應卡 |
| 原子卡片 | `atomic-card`／`atomic_card` | `atomic_card_note.py` | Grid packing | 一概念一卡 |
| 句子式 | `sentence` | `sentence_note.py` | Chain | 完整句子範圍 |
| 方框式 | `boxed` | `boxed_note.py` | Cluster | 完整 topic／group segment |
| 左右分欄 | `two-column`／`two_column` | `two_column_note.py` | Evidence Pair + Grid | 完整 pair bands |
| 三欄式 | `three-column`／`three_column` | `three_column_note.py` | Grid | 完整 rows |
| 矩陣式 | `matrix` | `matrix_note.py` | Axis 或 Grid | 完整 row/column block |
| 看板式 | `kanban` | `kanban_note.py` | Lanes | 同步 lane bands |
| 日誌式 | `journal` | `journal_note.py` | Lanes + Schema Blocks | 完整 day record／week band |
| 視覺速記 | `sketchnote` | `sketchnote.py` | Cluster + grid router | 完整 block／group segment |
| 批註式 | `annotated` | `annotated_note.py` | Evidence Pair | 完整 source-range group |
| 填空模板 | `template` | `template_note.py` | Template adapter | 完整 repeatable unit |
| 摘要卡片 | `summary` | `summary_card_note.py` | Fixed schema adapter | 一個 summary 一卡 |
| 魚骨圖 | `fishbone` | `fishbone_note.py` | Spine | 完整且連續的 branch range |

### 9.1 大綱式筆記 renderer

**正式腳本**：`tools/textart_notes/outline_note.py`

**適用場景**：

- 課堂章節整理。
- 會議議程與決議層級。
- 文件目錄摘要。
- 主題分解與複習提綱。

**輸入重點**：root 為 `title`、`children`、`numbering`、`depth_limit`；
每個節點有 `text`、`status`、`children`。

**生成方式**：

- 專用 outline adapter 依作者順序遞迴處理巢狀 `children`，而不是呼叫共享
  `layouts/hierarchy.py`。
- 目前只有一種 branch-glyph 縮排大綱幾何；theme 只替換 branch 與 reference
  glyph，沒有另一個 compact-tree layout。
- 長行採 hanging indent，第二行對齊正文而不是編號。
- 到達 `depth_limit` 或完整 subtree 超過卡片高度時，父卡放置 subtree
  reference，再把該 subtree 提升為後續完整 card；完整 sibling block 也是
  垂直分頁的最小單位。

**不建議使用**：節點間有大量交叉引用；改用概念圖。

### 9.2 康乃爾筆記 renderer

**正式腳本**：`tools/textart_notes/cornell_note.py`

**適用場景**：

- 課程筆記。
- 考試複習。
- 讀書會。
- 需要線索與摘要的知識整理。

**輸入重點**：`topic`、`pairs[{id,cue,note}]`、`summary`、
`cue_ratio`、`metadata`。

**生成方式**：

- 外框與底部 summary 使用 Schema Blocks。
- 左側 cue 與右側 note 使用 Evidence Pair。
- Cue 欄通常占 25% 至 35%，正文使用剩餘寬度。
- Summary 永遠跨越完整底部寬度。

**限制**：若 cue/note 很多，應在 pair 邊界分卡，且每張重複 topic header。

### 9.3 心智圖 renderer

**正式腳本**：`tools/textart_notes/mindmap_note.py`

**適用場景**：

- 腦力激盪。
- 概念總覽。
- 讀書章節鳥瞰。
- 中央主題與多個平行面向。

**輸入重點**：`root_id` 與有序
`nodes[{id,label,detail,children}]`；資料必須形成一棵嚴格樹。

**生成方式**：

- Hierarchy 先驗證單一 parent、作者 sibling order 與 subtree facts。
- Radial 將第一層 branch 依 sibling index 穩定交錯到左右兩側，後續
  子樹沿相同側向展開。
- 文字框與 connector 必須保留至少一格間距。
- 分支順序由輸入固定，確保 deterministic output。

**限制**：文字繪不適合十幾條分支同時圍繞中心。建議主圖只留第一層摘要，其餘生成子卡。

### 9.4 概念圖 renderer

**正式腳本**：`tools/textart_notes/concept_map_note.py`

**適用場景**：

- 理論關係。
- 系統概念。
- 原因與結果網絡。
- 詞彙之間帶關係詞的連結。

**輸入重點**：`id`、`title`、`concepts[{id,label,detail}]`，以及
`edges[{id,from,to,relation}]`。

**生成方式**：

- 使用 Directed Graph engine。
- 關係詞放在 edge 的空白水平段或專用 label box。
- 先分層，再路由 back edges。
- SCC 內部與 self-loop 使用外圍 cycle lanes；condensation DAG 的 edge
  使用 forward lanes。
- 只在完整 weakly connected component 邊界分卡。

**限制**：若關係詞比節點文字還長，應提高 edge corridor spacing；不能讓 label 覆蓋其他 edge。

### 9.5 流程圖筆記 renderer

**正式腳本**：`tools/textart_notes/flowchart_note.py`

**適用場景**：

- 操作 SOP。
- 演算法。
- 事件處理。
- Debug decision path。

**輸入重點**：`schema_version`、`id`、`title`、
`nodes[{id,kind,label,details}]` 與帶明確 source/target port 的 edges；kind
只接受 `start/process/decision/end`。

**生成方式**：

- 使用 Flow engine。
- Start/end、process、decision 使用各自的可見標記與 box content。
- 節點依 DAG layer 由上而下排列；同層分支在水平方向展開，edge 使用
  orthogonal routes。正式 schema 沒有 left-to-right orientation 選項。
- Decision 的出口 label 必須靠近正確 port。

**限制**：正式 schema 是可達、無循環的單一 DAG，且整圖不可切割；
複雜循環、多對多關係或泳道資料應改用概念圖或另一個專用 adapter。

### 9.6 表格比較法 renderer

**正式腳本**：`tools/textart_notes/comparison_table_note.py`

**適用場景**：

- 產品比較。
- 理論比較。
- 技術選型。
- 方案優缺點分析。

**輸入重點**：`title`、`key_header`、columns、column groups、rows 與
`status_tokens`；每列 `cells` 必須完整覆蓋欄位。

**生成方式**：

- 使用 Grid engine。
- 第一欄通常作為 item key。
- Numeric values 可右對齊，短狀態可置中，其餘文字左對齊。
- Cell wrapping 完成後才決定 row height。

**限制**：過寬時保留第一欄，將其餘欄分成多張卡；每張都重複 title 與 header。

### 9.7 時間軸筆記 renderer

**正式腳本**：`tools/textart_notes/timeline_note.py`

**適用場景**：

- 歷史事件。
- 專案里程碑。
- 病例紀錄。
- 產品版本演進。

**輸入重點**：`schema`、`title`、`timeline`（日期或 stage 尺度）、
`lanes` 與 events；ordinal 事件使用 `stage_id`，timestamp 事件使用可
UTC 正規化的時間欄位。

**生成方式**：

- 沒有 lanes 時，renderer 以 `STAGE/TIME + EVENTS` 的兩欄 grouped table
  顯示；有 lanes 時，使用 Lanes 的同步欄寬分配，把同一 stage／timestamp 的
  events 放進各 lane column。
- Timeline 共用模組計算 ordinal、proportional 或 compressed gap；同一時間的
  events 保持在同一個不可拆 group。
- 分頁只在完整 simultaneous group 邊界進行，後頁 header 會攜帶上一組的
  boundary context。
- 現行 renderer 不畫上下交錯的軸旁 label；所有 event 內容都在 table／lane
  rows 內換行。

**限制**：時間跨度極不均勻時，proportional mode 可能產生大量空白；應允許 compressed scale。

### 9.8 問答式筆記 renderer

**正式腳本**：`tools/textart_notes/qa_note.py`

**適用場景**：

- 主動回憶。
- 面試準備。
- 語言學習。
- FAQ。

**輸入重點**：`title`、`mode`（`expanded` 或 `separate`）與
`items[{pair_id,question,answer,hint,tags,difficulty}]`。

**生成方式**：

- 展開模式：一張卡同時顯示 Q、hint、A。
- 分離模式：問題與答案各生成一張 text-art card，manifest 記錄 pair ID。
- 使用 Schema Blocks 保持欄位一致。

**限制**：Text-art card 無法真正隱藏或翻面。需要互動揭曉時只能由上層 UI 管理，不應由純文字假裝支援。

### 9.9 卡片式筆記 renderer

**正式腳本**：`tools/textart_notes/atomic_card_note.py`

**適用場景**：

- Zettelkasten。
- 研究摘錄。
- 永久筆記。
- 長期累積的知識庫。

**輸入重點**：`collection_title` 與
`concepts[{id,title,body,tags,references,source}]`。

**生成方式**：

- 每個概念產生一張 text-art card。
- Card 內包含一致的 metadata header 與正文區。
- 多卡位置由 Grid row-major packing 決定，但每個概念仍是獨立 card。
- Cross-reference 以可見 ID 與 metadata 呈現；正式 materializer 永遠不
  建立 Board edge。

**限制**：不要把多個概念為了省卡而合併，否則失去 atomic note 的用途。

### 9.10 句子式筆記 renderer

**正式腳本**：`tools/textart_notes/sentence_note.py`

**適用場景**：

- 快速講座。
- 內容密集會議。
- 即時逐點記錄。
- 帶時間戳的簡短觀察。

**輸入重點**：`title` 與有序
`sentences[{text,timestamp,speaker,tags}]`。

**生成方式**：

- 使用 Chain 的順序語意，但通常不畫箭頭。
- 每句使用 stable numbering。
- Wrapped continuation 使用 hanging indent。
- 只能在完整句子邊界分卡。

**限制**：如果句子已開始形成主題層級，應改用大綱式筆記。

### 9.11 方框筆記 renderer

**正式腳本**：`tools/textart_notes/boxed_note.py`

**適用場景**：

- 平板式視覺整理。
- 平行主題摘要。
- 無明確先後順序的區塊筆記。

**輸入重點**：`id`、`title`、
`groups[{id,heading,topics[{id,heading,body[],emphasis}]}]`；亦支援正式
schema 定義的 ungrouped topics 形狀。

**生成方式**：

- 先量測各 box，再以 Cluster packing 排列。
- Group region 與 topic 都使用 deterministic shelf packing。
- `strong` topic 在框線上有可見 `!`，但不改變文字大小。

**限制**：若 box 間有大量箭頭，應轉為概念圖或流程圖。

### 9.12 左右分欄法 renderer

**正式腳本**：`tools/textart_notes/two_column_note.py`

**適用場景**：

- 原文與解釋。
- 翻譯對照。
- 程式碼與說明。
- 論點與證據。

**輸入重點**：`title`、`columns{left,right}`（每側含 `label/wrap`）、
`width_ratio{left,right}` 與 `pairs[{id,left,right}]`。

**生成方式**：

- 使用 Evidence Pair。
- 每一 pair 高度依左右兩側實際換行共同決定。
- 程式碼側可設定 `wrap=false`，改以分卡或加寬處理。

**限制**：左右資料若不是逐項對應，應使用一般 Grid。

### 9.13 三欄式筆記 renderer

**正式腳本**：`tools/textart_notes/three_column_note.py`

**適用場景**：

- 事實／解釋／行動。
- 觀察／推論／問題。
- 工作會議與研究分析。

**輸入重點**：恰三個 `columns[{key,label}]`、`rows`、`widths` 與
可選 `footer`。

**生成方式**：

- 使用 Grid。
- 欄寬可固定比例或依內容量測。
- 每列高度取三欄 wrapped height 最大值。
- 分頁時每張重複欄位名稱。

**限制**：每欄長篇內容會讓表格非常高；此時可改成每列一張摘要卡片。

### 9.14 矩陣式筆記 renderer

**正式腳本**：`tools/textart_notes/matrix_note.py`

**適用場景**：

- 重要性／急迫性矩陣。
- RACI。
- 風險機率／影響矩陣。
- 角色與責任分析。

**輸入重點**：`mode`、row/column axes、rows、columns、cells、legend
與 layout；正式支援離散 `grid` 與座標 `axis` 兩種模式。

**生成方式**：

- 離散 cell 資料使用 Grid。
- 自由點位使用 Axis。
- 可用 `● ○ × !` 或密度 glyph 表示短狀態。
- Legend 必須屬於同一張卡或在每張分卡重複。

**限制**：Cell 內不適合長段落；改用代碼並附 legend。

### 9.15 看板式筆記 renderer

**正式腳本**：`tools/textart_notes/kanban_note.py`

**適用場景**：

- TODO／DOING／DONE。
- 專案工作追蹤。
- 審核狀態。
- 個人任務板。

**輸入重點**：`board_id`、`title` 與有序
`lanes[{id,name,wip_limit,items[{id,title,assignee,priority,tags}]}]`。

**生成方式**：

- 使用同步 Lanes engine；太寬時切 lane groups，太高時所有 group 使用
  同一組 vertical item bands。
- Lane header 顯示名稱、數量和可選 WIP limit。
- 每個 item 使用緊湊 box。
- Lane 內維持輸入順序，不自動依文字重新排序。

**限制**：生成的是靜態 snapshot；Text-art payload 內部不能拖曳單一工作項目。

### 9.16 日誌式筆記 renderer

**正式腳本**：`tools/textart_notes/journal_note.py`

**適用場景**：

- 工作日誌。
- 學習反思。
- 實驗紀錄。
- 每日事件與下一步。

**輸入重點**：`journal_title`、`timezone`、`view` 與
`entries[{id,date,events,reflection,next_steps,mood,metrics}]`。

**生成方式**：

- 單日內容使用 Schema Blocks。
- 多日總覽使用 Lane Timeline。
- 預設一日或一週一張 card。
- Date header 與 section labels 必須在分卡後保留。

**限制**：不要在一張卡累積無限日期；Text-art 固定 extent 不適合無界日誌。

### 9.17 視覺速記 renderer

**正式腳本**：`tools/textart_notes/sketchnote.py`

**適用場景**：

- 演講重點。
- 創意會議。
- 記憶輔助。
- 關鍵詞與少量視覺關係。

**輸入重點**：`id`、`title`、groups；每個 block 有
`id/keyword/body/icon/importance`，icon 是
`idea/person/action/warning/question/note` 之一，可選 relations 以
block ID 連接。

**生成方式**：

- 使用有限且穩定的文字圖示庫。
- Cluster 安排主題區塊。
- 少量明確同群組關係交給共享 bounded grid router；全文件最多四條、
  每群組最多兩條，cross-group relation 明確回報 FitError。
- Importance 以 `*`／`!` 與額外 padding row 顯示，不任意放大字型。

**限制**：這不是 bitmap illustration renderer。任意手繪、照片或複雜人物不應強行轉成 ASCII。

### 9.18 批註式筆記 renderer

**正式腳本**：`tools/textart_notes/annotated_note.py`

**適用場景**：

- 閱讀文章。
- 論文批註。
- 教材說明。
- Source code review 摘要。

**輸入重點**：`title`、
`source{id,label,first_line,lines}` 與
`annotations[{id,start_line,end_line,kind,body}]`。

**生成方式**：

- 左側原文使用 stable line number。
- 右側批註使用 Evidence Pair 對齊 anchor。
- 中間以 `│`, `└─`, `!`, `?` 等 marker 指向原文。
- 分卡時保留原始行號，不重新從一開始編號。

**限制**：跨多行 annotation 不能只依畫面換行位置保存 anchor，必須保存原始 source range。

### 9.19 填空模板式 renderer

**正式腳本**：`tools/textart_notes/template_note.py`

**適用場景**：

- 例行會議。
- 訪談。
- 實驗紀錄。
- Incident report。
- 5W2H、SCQA 等固定方法。

**輸入重點**：`schema{template_id,version,title,fields,repeatable_sections}`
與對應的 `values{fields,repeatable_sections}`。

**生成方式**：

- 專用 template adapter 直接量測並排列固定欄位與 repeatable units；它遵守
  Schema Blocks 的完整 block 分頁語意，但未呼叫共享
  `layouts/schema_blocks.py`。
- 未填欄位呈現空白線、placeholder 或 checkbox。
- Repeatable section 依內容新增 row，但仍受最大高度限制。
- Template 本身與資料分離，方便重用。

**限制**：模板欄位太自由時會退化成通用文件；應保持明確的固定語意。

### 9.20 摘要卡片 renderer

**正式腳本**：`tools/textart_notes/summary_card_note.py`

**適用場景**：

- 書籍摘要。
- 論文整理。
- 技術文章重點。
- 會議決策摘要。

**輸入重點**：`summaries[]`；每筆包含 `topic`、`conclusion`、
`evidence`、`application`、`source`、`tags`。

**生成方式**：

- 專用 fixed-schema adapter 直接量測並繪製完整摘要；它沒有呼叫共享
  `layouts/schema_blocks.py`，且單筆 summary 不會再拆分。
- 預設區塊順序為主題、核心結論、證據、應用。
- Source 和 tags 放在緊湊 footer。
- 一個來源或一個核心主張產生一張卡。

**限制**：大量逐段摘錄應先使用卡片式筆記，再由摘要卡片保存綜合結論。

### 9.21 魚骨圖 renderer

**正式腳本**：`tools/textart_notes/fishbone_note.py`

**適用場景**：

- Ishikawa 根因分析。
- 品質問題分類。
- 風險來源與障礙整理。
- 多組 causes 收斂到一個 effect。

**輸入重點**：root 只接受 `effect`、`branches` 與 optional `layout`；
`layout` 是 `classic`、`boxed`、`compact` 之一。每條 branch 使用 `name`、
optional `side=top|bottom|auto`，以及互斥的 `nodes` 或 `causes` 陣列。這個
shape 可接受早期範例使用的主要欄位；互動模式、`result/category` 與非
canonical side aliases 不屬於現行 renderer contract，會被拒絕。

**生成方式**：

- 所有 `auto` sides 在全文件範圍先依 auto branch 序列交替決定；明示 side
  不消耗 parity，分卡後也不重設。
- Adapter 以實際 terminal x phase 量測 CJK、combining、spacing mark、tab 與
  multiline labels，再把完整 branch rectangles 交給共享 Spine layout。
- `classic/boxed/compact` 決定內容幾何；`ascii/unicode-light/unicode-rich`
  只替換等寬 glyph，兩個軸彼此獨立。
- 超寬或上下 branch 合併後超高時，以作者順序只在完整 branch 邊界貪婪
  分卡。每張重複 effect、continuation header 與完整 ownership metadata。
- `--style fishbone` 的輸出 renderer identity 固定為 `fishbone-note`，所有
  cards 都是 `text-art`，可直接交給共用 materializer。

**限制**：一條 branch 最多 64 causes，而且是不可拆的最小單位；空卡仍
無法容納時回報 `FitError`。Planner 不重排 branches，也不做最佳 packing；
循環、多 effect 或跨 branch edge 應改用 Concept Map。

## 10. 引擎組合模式

Renderer 組合多個引擎時，必須指定幾何責任邊界。以下列出各組合的責任分配。

### 10.1 康乃爾筆記

```text
Schema Blocks：決定整體 cue / notes / summary 區域
Evidence Pair：只在 cue 與 notes 區域內逐列對齊
```

### 10.2 心智圖

```text
Radial：將第一層分支穩定交錯分配到左右兩側並排列矩形
Hierarchy：驗證 parent/preorder/subtree facts 與 ownership
```

### 10.3 日誌總覽

```text
Lane Timeline：排列日期與事件
Schema Blocks：繪製每個日期的事件／反思／下一步
```

組合時不應讓兩個引擎同時決定同一節點的最終座標。

## 11. CLI 使用方式

### 11.1 Fishbone renderer

Fishbone 使用正式共用 dispatcher；`classic`、`boxed`、`compact` 由 fixture
JSON 的 `layout` 欄位選擇：

```sh
python3 -B -m tools.textart_notes.render_note \
  --style fishbone \
  --input tools/textart_notes/tests/fixtures/fishbone/input.json \
  --output-dir /tmp/fishbone-render \
  --theme unicode-light \
  --max-width 160 \
  --max-height 100
```

正式入口把 `classic/boxed/compact` 放在 JSON 的 `layout` 欄位；共用
`--theme` 仍只控制 glyph。輸出的 `manifest.json` 可直接交給
`materialize_textart.py`。

### 11.2 正式共用介面

每個 renderer 都可以直接執行，並使用同一組參數：

```sh
python3 -B -m tools.textart_notes.cornell_note \
  --input tools/textart_notes/tests/fixtures/cornell/input.json \
  --output-dir /tmp/cornell-render \
  --theme unicode-light \
  --max-width 120 \
  --max-height 70
```

也可以從統一 dispatcher 選 style：

```sh
python3 -B -m tools.textart_notes.render_note \
  --style concept-map \
  --input tools/textart_notes/tests/fixtures/concept_map/input.json \
  --output-dir /tmp/concept-map-render \
  --theme unicode-rich \
  --max-width 160 \
  --max-height 100
```

列出 21 個 style key、manifest renderer name 與 module：

```sh
python3 -B -m tools.textart_notes.render_note --list-styles
```

共用參數：

| 參數 | 說明 |
| --- | --- |
| `--input FILE` | UTF-8 JSON 輸入 |
| `--output-dir DIR` | payload 與 manifest 輸出位置 |
| `--theme THEME` | `ascii`、`unicode-light`、`unicode-rich` |
| `--max-width N` | 每張 card 最大 cell width，不得超過 160 |
| `--max-height N` | 每張 card 最大 cell height，不得超過 100 |
| `--check-only` | 驗證並布局，但不寫檔 |
| `--single-card` | 超出一張 card 時失敗，不自動分割 |

所有正式 renderer 都不使用 random seed；各布局依問題使用作者順序、
stable ID、port rank、座標或完整 path 作 deterministic tie-break。正式
exit codes：

```text
0  成功
1  輸入有效但無法在指定 card 限制內布局
2  輸入、schema 或字元資料無效
```

`--check-only` 仍會完成 JSON/schema、cell measurement、layout 與 output
contract 驗證，只是不建立 output directory。各 style 的可執行 JSON
範例位於 `tools/textart_notes/tests/fixtures/`；schema 是 closed object，
未知欄位、duplicate JSON keys、非有限數字、非法控制字元與沒有 anchor
的 combining mark 都會被拒絕。

## 12. 輸出契約

單卡與多卡 renderer 都輸出相同 manifest：

```json
{
  "manifest_version": 2,
  "generation": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "renderer": "cornell-note",
  "theme": "unicode-light",
  "cards": [
    {
      "id": "cornell-000",
      "format": "text-art",
      "payload": "generations/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef/payloads/cornell-000.txt",
      "width": 96,
      "height": 48,
      "x": 0,
      "y": 0,
      "metadata": {}
    }
  ]
}
```

必要條件：

- Writer 只輸出 `manifest_version: 2`；`generation` 是小寫 64-hex digest。
- `format` 必須固定為 `text-art`。
- `id` 在同一 manifest 內唯一且穩定。
- `id` 必須是 lowercase ASCII slug；payload path 固定為
  `generations/<generation>/payloads/<id>.txt`。
- `width`、`height` 是可見 card footprint，範圍分別為 `1..160`、
  `1..100`。
- Payload 行數恰等於 `height`；每行 cell width 不得超過 `width`。
- Payload 是 strict UTF-8、沒有 CR，檔尾恰有一個 LF。
- `x`、`y` 是非負的多卡相對位置，不直接代表 live Board 絕對位置；
  materializer 才加上 caller 提供、可為負的 signed 64-bit origin。
- `metadata` 必須是可 JSON 序列化的 object，用於保存布局、分卡與
  provenance；materializer 不將它解讀成 Board edge 命令。
- Card 順序、ID、座標、payload bytes 與 manifest bytes 對相同輸入
  和參數完全 deterministic。

目前可執行 contract 位於原始碼目錄 `tools/textart_notes/core/` 下的
`manifest.schema.json`、`protocol_limits.json` 與 `contracts.py`。Manifest 必須使用
`manifest_version: 2`，payload 位於 `generations/<generation>/payloads/`。

## 13. Materializer 與 Board 邊界

正式命令範例：

```sh
python3 -B -m tools.textart_notes.materialize_textart \
  --manifest /tmp/concept-map-render/manifest.json \
  --socket /tmp/my-explicit-board.sock \
  --origin-x 100 \
  --origin-y -20 \
  --result /tmp/concept-map-materialization.json \
  --whiteboardctl build/vcpkg-release/whiteboardctl \
  --timeout 5
```

`--manifest`、`--socket`、兩個 origin 與 `--result` 在共用 parser 中都
必須明確提供。非 check-only 執行時，也必須以 `--whiteboardctl` 指定執行檔路徑，
result path 必須是尚不存在的新 regular file 路徑。
`--check-only` 只完成 manifest、payload 與 geometry
preflight；它不檢查或連接 socket、不檢查 ctl executable／operational
timeout，也不檢查或建立 result path。

Materializer 的實際流程：

1. 完整讀取 manifest。
2. 拒絕非 `text-art` format。
3. 驗證所有 payload 與尺寸。
4. 將相對位置加上 caller 提供的 Board origin。
5. 以一次 `create-cards` 建立空卡。
6. 從 `FIRST_CARD_ID + manifest index` 建立 mapping，不掃描 Board。
7. 立即 durable checkpoint mapping，按每次回傳的新 revision 串行
   `replace-card`。
8. 對每張 card 執行精確 `get`，核對 format、位置、extent 與 payload bytes。
9. 保存 `complete` 或 `partial` result state；部分失敗不自動刪卡。

Preflight 先將父目錄轉成實體路徑，再拒絕 manifest file／payload symlink、FIFO、
path traversal、duplicate keys、NaN/Infinity、非 canonical path、資源上限與
signed 64-bit 座標 overflow。每個 ctl subprocess 有明確 timeout，而且會解析
stdout 的 `ERR`；不能只信任 process exit code。

Renderer 不應：

- 自行選擇 live Board。
- 自行猜測 socket。
- 掃描 Board 重新辨識 CardId。
- 建立 Markdown、Note、CSV 或其他格式卡片。
- 在布局失敗後默默裁切 payload。

`delete-cards` 會留下 tombstone、增加 revision/history 並讓 Board dirty，
因此不是 transaction rollback。Materializer 不自動 cleanup、resume
或儲存 `.tiwb`。只有使用者選定的 TUI 負責 Board path 與存檔；測試中
的 Ctrl-S/Ctrl-Q 只會送到 test-owned PTY。

## 14. 分卡策略

不同布局應在不同語意邊界分卡：

| Renderer 類型 | 優先分卡邊界 |
| --- | --- |
| Hierarchy / Radial | 完整 branch、subtree 或 overview/detail ownership |
| Directed Graph | 完整 weakly connected component |
| Grid | 完整 row/column group，並重複 header |
| Flow | 正式 flowchart 是不可切割的完整 DAG；超限回報 FitError |
| Timeline | 日期、時段或 stage |
| Evidence Pair | 完整 pair |
| Schema Blocks | 完整 record、entry 或 section |
| Cluster | 完整 item、block 或 group segment |
| Spine / Fishbone | 完整且連續的 branch range；每張重複 effect 與 continuation header |

永遠不要在以下位置切割：

- 雙寬字元中間。
- Box border 中間而不補完邊界。
- 一條 annotation anchor 中間。
- Decision node 與其出口 label 之間。
- Table header 與第一列資料之間。

## 15. Renderer 選擇範例

| 使用者需求 | Renderer `--style` | 布局與用途 |
| --- | --- | --- |
|「整理造成部署失敗的原因」| `fishbone` | Spine；多組原因導向單一結果 |
|「列出五次追問為什麼」| `timeline` | 無 lanes 的 Chain；按序呈現單一路徑因果追問 |
|「畫服務之間的循環依賴」| `concept-map` | Directed Graph；具有循環與多對多 edge |
|「整理一份章節大綱」| `outline` | Hierarchy；嚴格父子層級 |
|「腦力激盪產品功能」| `mindmap` | Radial；中央主題向外發散 |
|「比較三個資料庫」| `comparison` | Grid；固定比較欄位 |
|「整理事件與不同角色接觸點」| `timeline` | Lane Timeline；時間和角色同時重要 |
|「原文旁逐段寫評論」| `annotated` | Evidence Pair；原文與批註逐項對齊 |
|「建立固定事故回報表」| `template` | Schema Blocks；欄位固定且可重用 |
|「每個研究概念獨立保存」| `atomic-card` | 一概念一卡 |

## 16. 不適合純文字繪的場景

以下需求不應勉強使用 text-art renderer：

- 需要照片、自由手繪或精確視覺造型。
- 需要任意縮放曲線或高密度科學繪圖。
- 需要互動收合、翻卡或拖曳卡片內部元素。
- 需要四集合以上且必須精確呈現所有 Venn regions。
- 需要在單張卡內顯示數百個 graph nodes。
- 依賴 Emoji 顏色或平台特定 glyph 才能理解。

這些情況應改用多張 text-art cards、一般 whiteboard cards，或 bitmap/vector rendering。

## 17. 實作、範例與測試位置

```text
tools/textart_notes/
├── core/                 cell width、wrap、Canvas、router、CLI、manifest
├── layouts/              13 個共享幾何／分頁模組（含 spine.py）
├── *_note.py             20 個符合 *_note.py 命名的入口（含 fishbone_note.py）
├── sketchnote.py         其餘 1 個入口；合計 21 個
├── render_note.py        21-style dispatcher
├── materialize_textart.py
├── integration_tests/    隔離 PTY、socket、save/reload 測試
└── tests/
    ├── fixtures/<style>/input.json
    ├── golden/<style>/{ascii,unicode-light}.txt
    ├── test_<style>.py
    ├── test_core_*.py
    ├── test_layout_*.py
    ├── test_dispatcher.py
    └── test_materializer.py
```

一般測試（不連 Board）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tools/textart_notes/tests -p 'test_*.py' -v
```

隔離 Board 測試（自行建立 `/tmp/wbmat-*`、PTY、socket 與 `.tiwb`）：

```sh
WHITEBOARD_TEXTART_INTEGRATION=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest -v \
  tools.textart_notes.integration_tests.test_materializer_board
```

隔離 suite 分別驗證 preview cleanup、runner attestation，以及 materializer 的
create/replace/delete、存檔與重新載入。每個案例自行持有 PTY、socket、board 與
temporary workspace。

可重現的輸入、golden output 與 regression evidence 位於
`tools/textart_notes/tests/fixtures/`、`tools/textart_notes/tests/golden/` 與
對應的 `test_*.py`。

## 18. 完成標準

21 個正式筆記 renderer 都以以下條件作為 release gate：

1. 有明確 JSON schema 與錯誤訊息。
2. 相同輸入與參數產生完全相同的輸出。
3. 所有 CJK、窄字元、combining character 與 tab 測試通過。
4. 不產生超過 `160×100` 的 card。
5. 分卡只發生在合法語意邊界。
6. Manifest 中所有格式皆為 `text-art`。
7. Payload 尺寸與 manifest 完全一致。
8. ASCII 與 Unicode theme 都有 golden tests。
9. Renderer 不接觸 live Board。
10. 代表性 manifest 能經 Materializer 存檔、重新載入並逐 byte 核對。

以上條件已由正式 suite 與隔離 Board suite 驗證。正式 Fishbone adapter
是 `tools/textart_notes/fishbone_note.py`，透過共用 dispatcher 輸出目前的
versioned manifest，並可交給 materializer。
