#!/usr/bin/env python3
"""Render fixed three-column semantic notes with complete-row pagination."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import char_width, pad_cells, text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, decimal_value, object_value, string_value
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.grid import (
    Column,
    GridRow,
    MeasuredRow,
    allocate_weighted,
    measure_row,
    measure_rows,
    render_table,
    table_content_budget,
)


RENDERER = "three-column"
GUTTER = 2
_KEY_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str


@dataclass(frozen=True)
class Note:
    title: str
    columns: tuple[ColumnSpec, ColumnSpec, ColumnSpec]
    rows: tuple[tuple[str, str, str], ...]
    width_mode: str
    ratios: tuple[Fraction, Fraction, Fraction] | None
    footer: str | None


def _fraction(value: object, path: str) -> Fraction:
    result = Fraction(decimal_value(value, path))
    if result <= 0:
        raise InputError(f"{path} must be positive")
    return result


def _normalize(data: dict[str, object]) -> Note:
    root = object_value(data, "input")
    allowed = {"title", "columns", "rows", "widths", "footer"}
    check_keys(root, "input", required={"title", "columns", "rows"}, allowed=allowed)
    column_values = array_value(root["columns"], "columns")
    if len(column_values) != 3:
        raise InputError("columns must contain exactly three declarations")
    columns: list[ColumnSpec] = []
    seen: set[str] = set()
    for index, value in enumerate(column_values):
        path = f"columns[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"key", "label"}, allowed={"key", "label"})
        key = string_value(record["key"], f"{path}.key", single_line=True, allow_tabs=False)
        if _KEY_RE.fullmatch(key) is None:
            raise InputError(f"{path}.key must be a lowercase ASCII key")
        if key in seen:
            raise InputError(f"duplicate column key {key!r}")
        seen.add(key)
        columns.append(ColumnSpec(key, string_value(record["label"], f"{path}.label")))
    row_values = array_value(root["rows"], "rows")
    if not row_values:
        raise InputError("rows must not be empty")
    rows: list[tuple[str, str, str]] = []
    keys = {column.key for column in columns}
    for index, value in enumerate(row_values):
        path = f"rows[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required=keys, allowed=keys)
        rows.append(tuple(
            string_value(record[column.key], f"{path}.{column.key}", allow_empty=True)
            for column in columns
        ))
    mode = "ratio"
    ratios: tuple[Fraction, Fraction, Fraction] | None = (Fraction(1),) * 3
    if "widths" in root:
        widths = object_value(root["widths"], "widths")
        if widths.get("mode") == "ratio":
            check_keys(widths, "widths", required={"mode", "ratios"}, allowed={"mode", "ratios"})
            values = array_value(widths["ratios"], "widths.ratios")
            if len(values) != 3:
                raise InputError("widths.ratios must contain exactly three numbers")
            parsed = tuple(_fraction(value, f"widths.ratios[{index}]") for index, value in enumerate(values))
            ratios = (parsed[0], parsed[1], parsed[2])
        elif widths.get("mode") == "measured":
            check_keys(widths, "widths", required={"mode"}, allowed={"mode"})
            mode = "measured"
            ratios = None
        else:
            raise InputError("widths.mode must be 'ratio' or 'measured'")
    footer = string_value(root["footer"], "footer") if "footer" in root else None
    return Note(
        string_value(root["title"], "title"),
        (columns[0], columns[1], columns[2]),
        tuple(rows),
        mode,
        ratios,
        footer,
    )


def _indivisible(texts: Sequence[str]) -> int:
    maximum = 1
    for text in texts:
        for hard_line in text.split("\n"):
            for character in hard_line:
                maximum = max(maximum, 4 if character == "\t" else char_width(character))
    return maximum


def _starts(widths: Sequence[int]) -> tuple[int, int, int]:
    return 1, widths[0] + 2, widths[0] + widths[1] + 3


def _natural(text: str, start: int) -> int:
    return max((text_width(line, start=start) for line in text.split("\n")), default=1)


def _widths(note: Note, total_width: int) -> tuple[int, int, int]:
    budget = table_content_budget(total_width, 3, padding=0)
    texts = tuple(
        (note.columns[index].label,) + tuple(row[index] for row in note.rows)
        for index in range(3)
    )
    minimums = tuple(_indivisible(values) for values in texts)
    if note.width_mode == "ratio":
        assert note.ratios is not None
        allocated = allocate_weighted(budget, note.ratios, minimums)
        return allocated[0], allocated[1], allocated[2]
    current = allocate_weighted(budget, (Fraction(1),) * 3, minimums)
    history: list[tuple[int, ...]] = []
    while current not in history:
        history.append(current)
        starts = _starts(current)
        demands = tuple(
            Fraction(max(1, max(_natural(value, starts[index]) for value in texts[index])))
            for index in range(3)
        )
        following = allocate_weighted(budget, demands, minimums)
        if following == current:
            return current[0], current[1], current[2]
        current = following
    selected = min(history[history.index(current):])
    return selected[0], selected[1], selected[2]


def _wrap_span(text: str, width: int, start: int = 1) -> tuple[str, ...]:
    output: list[str] = []
    try:
        for hard_line in text.split("\n"):
            output.extend(wrap_line(hard_line, width, start_column=start))
    except ValueError as error:
        raise FitError(str(error)) from error
    return tuple(output or [""])


def _span_border(width: int, theme: str, *, top: bool) -> str:
    selected = get_theme(theme)
    left = selected.line(EAST | SOUTH) if top else selected.line(NORTH | EAST)
    right = selected.line(SOUTH | WEST) if top else selected.line(NORTH | WEST)
    return left + selected.line(EAST | WEST) * (width - 2) + right


def _connector(widths: Sequence[int], theme: str, *, downward: bool) -> str:
    selected = get_theme(theme)
    horizontal = selected.line(EAST | WEST)
    left = selected.line(NORTH | EAST | SOUTH)
    right = selected.line(NORTH | SOUTH | WEST)
    middle = selected.line(EAST | SOUTH | WEST) if downward else selected.line(NORTH | EAST | WEST)
    return left + middle.join(horizontal * width for width in widths) + right


def _paint(
    title: tuple[str, ...],
    columns: tuple[Column, Column, Column],
    widths: tuple[int, int, int],
    rows: tuple[MeasuredRow, ...],
    footer: tuple[str, ...] | None,
    options: RenderOptions,
) -> str:
    selected = get_theme(options.theme)
    vertical = selected.line(NORTH | SOUTH)
    table = render_table(columns, widths, rows, options.theme, padding=0)
    lines = [_span_border(options.max_width, options.theme, top=True)]
    lines.extend(vertical + pad_cells(line, options.max_width - 2) + vertical for line in title)
    lines.append(_connector(widths, options.theme, downward=True))
    lines.extend(table[1:-1])
    if footer is None:
        lines.append(table[-1])
    else:
        lines.append(_connector(widths, options.theme, downward=False))
        lines.extend(vertical + pad_cells(line, options.max_width - 2) + vertical for line in footer)
        lines.append(_span_border(options.max_width, options.theme, top=False))
    return "\n".join(lines)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    widths = _widths(note, options.max_width)
    columns = tuple(Column(column.key, column.label, 1, align="left", wrap=True) for column in note.columns)
    grid_columns = (columns[0], columns[1], columns[2])
    grid_rows = tuple(GridRow(f"row-{index:03d}", row) for index, row in enumerate(note.rows))
    measured = measure_rows(grid_rows, grid_columns, widths, padding=0)
    header = measure_row(
        GridRow("header", tuple(column.label for column in note.columns)),
        grid_columns,
        widths,
        padding=0,
    )
    title = _wrap_span(note.title, options.max_width - 2)
    footer = _wrap_span(note.footer, options.max_width - 2) if note.footer is not None else None
    fixed = 1 + len(title) + 1 + header.height + 1 + (len(footer) + 1 if footer else 0)
    pages: list[tuple[MeasuredRow, ...]] = []
    current: list[MeasuredRow] = []
    used = fixed
    for row in measured:
        cost = row.height + 1
        if fixed + cost > options.max_height:
            raise FitError(f"{row.key} is indivisible and exceeds max_height")
        if current and used + cost > options.max_height:
            pages.append(tuple(current))
            current = []
            used = fixed
        current.append(row)
        used += cost
    pages.append(tuple(current))
    if options.single_card and len(pages) > 1:
        raise FitError(f"{len(pages)} complete-row cards are required")
    cards: list[CardDraft] = []
    y = 0
    row_start = 0
    for index, page in enumerate(pages):
        text = _paint(title, grid_columns, widths, page, footer, options)
        height = len(text.split("\n"))
        row_end = row_start + len(page)
        cards.append(
            CardDraft(
                f"three-column-{index:03d}",
                text,
                options.max_width,
                height,
                0,
                y,
                {
                    "row_start": row_start,
                    "row_end": row_end,
                    "column_keys": [column.key for column in note.columns],
                    "column_widths": list(widths),
                    "row_heights": [row.height for row in page],
                    "width_mode": note.width_mode,
                    "footer_repeated": footer is not None,
                    "continuation": index > 0,
                },
            )
        )
        row_start = row_end
        y += height + GUTTER
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
