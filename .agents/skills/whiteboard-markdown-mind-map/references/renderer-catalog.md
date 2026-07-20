# Presentation 目錄

本文件供主 agent 使用。

主 agent 依 unit 的主要關係選擇原生格式、renderer 或原生 `text-art`，並在 `why` 記錄原因。

## 原生格式

| Format | 用途 |
| --- | --- |
| `note` | 短標籤、提醒、單一事實 |
| `markdown` | 段落、引文、完整說明 |
| `code` | 原始碼、命令、fixed-width 內容 |
| `csv` | 規則表格資料 |
| `todo` | Checklist |
| `folder` | 指向 unit anchors 的索引 |
| `text-art` | 完整固定格視覺內容 |

原生 `text-art` 使用 `kind: native`、`format: text-art` 與 `payload` fence。Payload 由設計稿提供完整 glyph、換行與縮排。Board edges 由 `Connections` 宣告。

## Renderers

| Key | 用途 | Fixture |
| --- | --- | --- |
| `outline` | 階層、章節、巢狀 agenda | `tools/textart_notes/tests/fixtures/outline/input.json` |
| `cornell` | Topic、cue、note 與 synthesis | `tools/textart_notes/tests/fixtures/cornell/input.json` |
| `mindmap` | Rooted theme 與 ownership tree | `tools/textart_notes/tests/fixtures/mindmap/input.json` |
| `concept-map` | Labelled concepts 與 cross-links | `tools/textart_notes/tests/fixtures/concept_map/input.json` |
| `flowchart` | Decision 或 process DAG | `tools/textart_notes/tests/fixtures/flowchart/input.json` |
| `comparison` | Options 與 shared criteria | `tools/textart_notes/tests/fixtures/comparison/input.json` |
| `timeline` | Stages、dates 與 lanes | `tools/textart_notes/tests/fixtures/timeline/input.json` |
| `qa` | Questions、answers、hints 與 tags | `tools/textart_notes/tests/fixtures/qa/input.json` |
| `atomic-card` | 可獨立使用的 concepts | `tools/textart_notes/tests/fixtures/atomic_card/input.json` |
| `sentence` | Ordered statements 與發言 | `tools/textart_notes/tests/fixtures/sentence/input.json` |
| `boxed` | Thematic groups 與 compact blocks | `tools/textart_notes/tests/fixtures/boxed/input.json` |
| `two-column` | Evidence/commentary 與 paired views | `tools/textart_notes/tests/fixtures/two_column/input.json` |
| `three-column` | 重複 triples | `tools/textart_notes/tests/fixtures/three_column/input.json` |
| `matrix` | Two axes 與 state grid | `tools/textart_notes/tests/fixtures/matrix/input.json` |
| `kanban` | Work items 與 status lanes | `tools/textart_notes/tests/fixtures/kanban/input.json` |
| `journal` | Dated records、reflection 與 metrics | `tools/textart_notes/tests/fixtures/journal/input.json` |
| `sketchnote` | Grouped keywords、icons 與 relations | `tools/textart_notes/tests/fixtures/sketchnote/input.json` |
| `annotated` | Source ranges 與 annotations | `tools/textart_notes/tests/fixtures/annotated/input.json` |
| `template` | 固定欄位與 blanks | `tools/textart_notes/tests/fixtures/template/input.json` |
| `summary` | Conclusion、evidence、application 與 source | `tools/textart_notes/tests/fixtures/summary/input.json` |
| `fishbone` | Cause families 與共同 effect | `tools/textart_notes/tests/fixtures/fishbone/input.json` |

主 agent 讀取所選 fixture，再建立 renderer JSON。

完整 schema、layout options 與 examples 位於 repository root 的 `docs/text-art-renderers.md`。

Theme 使用 `ascii`、`unicode-light` 或 `unicode-rich`。
