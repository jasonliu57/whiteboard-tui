# Design

Read left to right through every native card format and a rendered outline.

# Units

## u-note

kind: native
format: note
group: -
title: Note
why: Preserve Unicode and line breaks.

~~~payload
獨立白板
é / 中文
~~~

## u-markdown

kind: native
format: markdown
group: -
title: Markdown
why: Preserve Markdown source.

~~~payload
# 白板筆記

**完整內容**與 `inline code`。
~~~

## u-code

kind: native
format: code
group: -
title: Code
why: Preserve indentation and source text.

~~~payload
int main() {
    return 0;
}
~~~

## u-todo

kind: native
format: todo
group: -
title: Todo
why: Preserve completed and pending items.

~~~payload
- [x] 儲存
- [ ] 搬移
~~~

## u-csv

kind: native
format: csv
group: -
title: CSV
why: Preserve quoted cells and Unicode.

~~~payload
name,value
"中文","x,y"
quote,"a""b"
"line
break",value
""
~~~

## u-folder

kind: native
format: folder
group: -
title: Folder
why: Preserve references to native and rendered card IDs.

~~~payload
ROOT	索引
0	CARD	@u-note	0	筆記
0	DIR	-	0	內容
1	CARD	@u-outline	0	大綱
~~~

## u-art

kind: native
format: text-art
group: -
title: Text art
why: Preserve fixed cell geometry.

~~~payload
┌──────┐
│ 中文 │
└──────┘
~~~

## u-outline

kind: renderer
renderer: outline
group: -
title: Outline
why: Compile a renderer payload before writing the board.
theme: unicode-light
max-width: 36
max-height: 20
single-card: true

~~~input
{
  "title": "流程",
  "numbering": true,
  "children": [
    {"text": "儲存"},
    {"text": "搬移", "children": [{"text": "重開"}]}
  ]
}
~~~

# Groups

# Connections

```tsv
from	to
u-note	u-markdown
u-markdown	u-code
u-code	u-todo
u-todo	u-csv
u-csv	u-folder
u-folder	u-art
u-art	u-outline
```
