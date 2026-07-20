# Artifact 契約

本文件供主 agent 使用。

## 檔案

| 檔案 | 作者 | 內容 |
| --- | --- | --- |
| `work/design.md` | 設計 agent | 卡片構想與閱讀順序 |
| `plan.md` | 主 agent | Presentation plan |
| `work/provisional-unit-layout.tsv` | 主 agent | 預覽 unit origins |
| `unit-layout.tsv` | 主 agent | 最終 unit origins |
| `layout-reference.png` | Imagegen | 版面提案 |
| `units.tsv`、`unit-members.tsv`、`unit-edges.tsv` | Artifact CLI | Unit 編譯結果 |
| `cards.tsv`、`edges.tsv`、`layout.tsv` | Artifact CLI | Card 編譯結果 |
| `renderer-inputs/`、`payloads/`、`work/rendered/` | Artifact CLI | Renderer 與 payload 產物 |
| `card-map.tsv`、`edge-results.tsv` | Verification CLI | Board IDs 與 edge 結果 |
| `final.png`、`work/verification/` | Verification CLI | 最終影像與驗證證據 |

## `plan.md`

頂層 section 順序為 `Design`、`Units`、`Groups`、`Connections`。

Unit ID 使用小寫 ASCII、數字與連字號。

````markdown
# Design

一句話說明讀者收穫與閱讀順序。

# Units

## u-entry

kind: native
format: markdown
group: core
title: 核心入口
why: 保存完整說明。

~~~payload
# 核心入口

這張卡片提供全圖入口。
~~~

## u-outline

kind: renderer
renderer: outline
group: core
title: 內容綱要
why: 以階層呈現主要關係。
theme: unicode-light
max-width: 120
max-height: 70
single-card: false

~~~input
{
  "title": "內容綱要",
  "numbering": true,
  "depth_limit": 3,
  "children": [
    {"text": "主題", "children": [{"text": "細節"}]}
  ]
}
~~~

# Groups

- `core`: 核心內容

# Connections

```tsv
from	to
u-entry	u-outline
```
````

Native unit 欄位為 `kind`、`format`、`group`、`title`、`why` 與 `payload` fence。

Renderer unit 欄位為 `kind`、`renderer`、`group`、`title`、`why` 與 `input` fence。選用欄位為 `theme`、`max-width`、`max-height` 與 `single-card`。

`group: -` 表示獨立 unit。

Todo payload 每行使用 `- [ ] 文字` 或 `- [x] 文字`。
CSV payload 使用標準 CSV；`prepare` 將 quoting 與行尾編譯為 Board 的 canonical
內容交換格式，並以空白儲存格補齊較短的列。CSV 的 quoted 多行儲存格與
空白列皆可保留。Todo 與 CSV 不會額外附加終端換行。

Folder payload 使用 tab-separated `ROOT`、`DIR`、`CARD` records，
`@UNIT-ID` 指向 unit anchor；不能使用 Markdown 清單：

```text
ROOT	索引
0	DIR	-	0	主題
1	CARD	@u-entry	0	核心入口
1	CARD	@u-outline	0	內容綱要
```

Entry 欄位依序為 `depth`、`kind`、`target`、`collapsed`、`name`。
`DIR` 的 target 必須是 `-`；`CARD` 的 target 使用 `@UNIT-ID`，collapsed 必須為 `0`。
Materialize 會將 unit reference 解析為白板內的 CardId。

Connections 以 unit ID 表示方向。

## Layout

兩份 unit layout 使用相同 TSV：

```tsv
id	x	y
u-entry	0	0
u-outline	48	0
```

座標是 unit 左上角。`x` 向右增加。`y` 向下增加。

`expand-layout` 將 unit origin 與 renderer member offset 合成 card layout。

## `state.tsv`

```tsv
key	value
source	notes/topic.md
board_file	boards/topic.tiwb
socket	/tmp/whiteboard.sock
phase	planned
revision	12
dirty	0
saved	0
```

`phase` 依序為 `planned`、`positioned`、`materializing`、`materialized`、`saved`。

## CLI

Artifact CLI 提供：

- `prepare`：編譯 plan 與 renderer outputs。
- `expand-layout`：驗證 unit geometry 並寫出 card layout。
- `build-batch`：產生 `create-cards` batch。
- `validate-units`：說明 unit layout errors 與 warnings。
- `validate-layout`：說明 card layout errors 與 warnings。

Warnings 說明視覺風險，exit code 為 `0`。

Geometry errors 說明衝突位置與規則，exit code 為 `1`，輸出檔保持原值。

Input errors 說明檔案、欄位或資料原因，exit code 為 `2`。

Run 使用 `prepare`、`expand-layout` 與 `build-batch`。兩個 validate command 用於版面診斷。
