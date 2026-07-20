#!/usr/bin/env python3
"""Render semantically grouped comparison tables with synchronized bands."""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, object_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.grid import (
    Column,
    GridRow,
    MeasuredRow,
    allocate_toward_demands,
    measure_row,
    measure_rows,
    render_table,
    table_content_budget,
)


RENDERER = "comparison-table"
MIN_COLUMN = 6
GUTTER = 2
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")
_ALIGNMENTS = {"auto", "left", "center", "right"}
_DEFAULT_STATUSES = {
    "yes", "no", "n/a", "pass", "fail", "ok", "todo", "done",
    "active", "blocked", "pending", "high", "medium", "low",
}


@dataclass(frozen=True)
class ComparisonColumn:
    column_id: str
    header: str
    align: str


@dataclass(frozen=True)
class Group:
    group_id: str
    header: str
    column_ids: tuple[str, ...]


@dataclass(frozen=True)
class Cell:
    text: str
    kind: str


@dataclass(frozen=True)
class Row:
    key: str
    label: str
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class Note:
    title: str
    key_header: str
    columns: tuple[ComparisonColumn, ...]
    groups: tuple[Group, ...]
    rows: tuple[Row, ...]
    statuses: frozenset[str]


@dataclass(frozen=True)
class HorizontalPage:
    indices: tuple[int, ...]
    group_ids: tuple[str, ...]
    columns: tuple[Column, ...]
    widths: tuple[int, ...]
    rows: tuple[MeasuredRow, ...]
    header_height: int


def _identifier(value: object, path: str) -> str:
    result = string_value(value, path, single_line=True, allow_tabs=False)
    if _ID_RE.fullmatch(result) is None:
        raise InputError(f"{path} must be a lowercase safe identifier of at most 32 characters")
    return result


def _cell(value: object, path: str) -> Cell:
    if value is None:
        return Cell("N/A", "null")
    if type(value) is bool:
        return Cell("yes" if value else "no", "boolean")
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise InputError(f"{path} must be a finite JSON number")
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise InputError(f"{path} must be a finite JSON number")
            return Cell(format(value, "f"), "number")
        return Cell(json.dumps(value, ensure_ascii=False, allow_nan=False), "number")
    if isinstance(value, str):
        return Cell(string_value(value, path, allow_empty=True), "string")
    raise InputError(f"{path} must be a string, finite number, boolean, or null")


def _normalize(data: dict[str, object]) -> Note:
    root = object_value(data, "input")
    required = {"title", "key_header", "columns", "column_groups", "rows"}
    check_keys(root, "input", required=required, allowed=required | {"status_tokens"})
    column_values = array_value(root["columns"], "columns")
    if not column_values:
        raise InputError("columns must not be empty")
    columns: list[ComparisonColumn] = []
    seen_columns: set[str] = set()
    for index, value in enumerate(column_values):
        path = f"columns[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "header"}, allowed={"id", "header", "align"})
        column_id = _identifier(record["id"], f"{path}.id")
        if column_id in seen_columns:
            raise InputError(f"duplicate column id {column_id!r}")
        seen_columns.add(column_id)
        align = record.get("align", "auto")
        if align not in _ALIGNMENTS:
            raise InputError(f"{path}.align must be auto, left, center, or right")
        columns.append(
            ComparisonColumn(column_id, string_value(record["header"], f"{path}.header"), str(align))
        )
    group_values = array_value(root["column_groups"], "column_groups")
    if not group_values:
        raise InputError("column_groups must not be empty")
    groups: list[Group] = []
    seen_groups: set[str] = set()
    flattened: list[str] = []
    for index, value in enumerate(group_values):
        path = f"column_groups[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "header", "column_ids"}, allowed={"id", "header", "column_ids"})
        group_id = _identifier(record["id"], f"{path}.id")
        if group_id in seen_groups:
            raise InputError(f"duplicate group id {group_id!r}")
        seen_groups.add(group_id)
        ids = tuple(_identifier(item, f"{path}.column_ids[{item_index}]") for item_index, item in enumerate(array_value(record["column_ids"], f"{path}.column_ids")))
        if not ids:
            raise InputError(f"{path}.column_ids must not be empty")
        flattened.extend(ids)
        groups.append(Group(group_id, string_value(record["header"], f"{path}.header"), ids))
    if flattened != [column.column_id for column in columns]:
        raise InputError("column_groups must concatenate to the declared column order exactly")
    row_values = array_value(root["rows"], "rows")
    if not row_values:
        raise InputError("rows must not be empty")
    rows: list[Row] = []
    seen_rows: set[str] = set()
    expected_cells = {column.column_id for column in columns}
    for index, value in enumerate(row_values):
        path = f"rows[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"key", "label", "cells"}, allowed={"key", "label", "cells"})
        key = _identifier(record["key"], f"{path}.key")
        if key in seen_rows:
            raise InputError(f"duplicate row key {key!r}")
        seen_rows.add(key)
        cells = object_value(record["cells"], f"{path}.cells")
        check_keys(cells, f"{path}.cells", required=expected_cells, allowed=expected_cells)
        rows.append(
            Row(
                key,
                string_value(record["label"], f"{path}.label"),
                tuple(_cell(cells[column.column_id], f"{path}.cells.{column.column_id}") for column in columns),
            )
        )
    statuses = set(_DEFAULT_STATUSES)
    if "status_tokens" in root:
        for index, value in enumerate(array_value(root["status_tokens"], "status_tokens")):
            statuses.add(string_value(value, f"status_tokens[{index}]", single_line=True, strip=True).casefold())
    return Note(
        string_value(root["title"], "title"),
        string_value(root["key_header"], "key_header"),
        tuple(columns),
        tuple(groups),
        tuple(rows),
        frozenset(statuses),
    )


def _natural(text: str, start: int) -> int:
    return max((text_width(line, start=start) for line in text.split("\n")), default=1)


def _worst_natural(text: str) -> int:
    return max(_natural(text, residue) for residue in range(4))


def _group_indices(note: Note) -> list[tuple[Group, tuple[int, ...]]]:
    lookup = {column.column_id: index for index, column in enumerate(note.columns)}
    return [(group, tuple(lookup[column_id] for column_id in group.column_ids)) for group in note.groups]


def _preferred_widths(note: Note) -> tuple[int, ...]:
    key_texts = [note.key_header] + [f"[{row.key}]\n{row.label}" for row in note.rows]
    values = [max(MIN_COLUMN, min(20, max(_worst_natural(text) for text in key_texts)))]
    group_by_column = {
        column_id: group.header for group in note.groups for column_id in group.column_ids
    }
    for index, column in enumerate(note.columns):
        texts = [group_by_column[column.column_id], column.header] + [row.cells[index].text for row in note.rows]
        values.append(max(MIN_COLUMN, min(24, max(_worst_natural(text) for text in texts))))
    return tuple(values)


def _horizontal_pages(note: Note, max_width: int) -> tuple[tuple[tuple[int, ...], tuple[str, ...]], ...]:
    preferred = _preferred_widths(note)
    pages: list[tuple[tuple[int, ...], tuple[str, ...]]] = []
    current_indices: list[int] = []
    current_groups: list[str] = []
    for group, indices in _group_indices(note):
        candidate = current_indices + list(indices)
        visible_count = 1 + len(candidate)
        minimum_footprint = MIN_COLUMN * visible_count + 3 * visible_count + 1
        if minimum_footprint > max_width:
            raise FitError(f"semantic group {group.group_id!r} cannot fit beside the key column")
        preferred_footprint = preferred[0] + sum(preferred[index + 1] for index in candidate) + 3 * visible_count + 1
        if current_indices and preferred_footprint > max_width:
            pages.append((tuple(current_indices), tuple(current_groups)))
            current_indices = list(indices)
            current_groups = [group.group_id]
        else:
            current_indices = candidate
            current_groups.append(group.group_id)
    pages.append((tuple(current_indices), tuple(current_groups)))
    return tuple(pages)


def _cell_alignment(column: ComparisonColumn, cell: Cell, statuses: frozenset[str]) -> str:
    if column.align != "auto":
        return column.align
    if cell.kind == "number":
        return "right"
    if cell.kind in {"boolean", "null"}:
        return "center"
    if "\n" not in cell.text and text_width(cell.text.strip()) <= 12 and cell.text.strip().casefold() in statuses:
        return "center"
    return "left"


def _page_context(note: Note, indices: tuple[int, ...], group_ids: tuple[str, ...], max_width: int) -> HorizontalPage:
    group_for_column = {
        column_id: group for group in note.groups for column_id in group.column_ids
    }
    labels = [note.key_header] + [
        f"{group_for_column[note.columns[index].column_id].header}\n{note.columns[index].header}"
        for index in indices
    ]
    columns = [Column("key", labels[0], MIN_COLUMN, align="left", wrap=True)]
    columns.extend(
        Column(note.columns[index].column_id, labels[offset + 1], MIN_COLUMN, align="center", wrap=True)
        for offset, index in enumerate(indices)
    )
    budget = table_content_budget(max_width, len(columns), padding=1)
    texts: list[list[str]] = [[labels[0]] + [f"[{row.key}]\n{row.label}" for row in note.rows]]
    texts.extend([labels[offset + 1]] + [row.cells[index].text for row in note.rows] for offset, index in enumerate(indices))
    minimums = (MIN_COLUMN,) * len(columns)
    initial_demands = tuple(max(_worst_natural(text) for text in values) for values in texts)
    current = allocate_toward_demands(budget, minimums, initial_demands)
    history: list[tuple[int, ...]] = []
    while current not in history:
        history.append(current)
        starts: list[int] = []
        start = 2
        for width in current:
            starts.append(start)
            start += width + 3
        demands = tuple(max(_natural(text, starts[index]) for text in texts[index]) for index in range(len(texts)))
        following = allocate_toward_demands(budget, minimums, demands)
        if following == current:
            break
        current = following
    if current in history and history[-1] != current:
        current = min(history[history.index(current):])
    rows: list[GridRow] = []
    for row in note.rows:
        visible_cells = tuple(row.cells[index] for index in indices)
        rows.append(
            GridRow(
                row.key,
                (f"[{row.key}]\n{row.label}",) + tuple(cell.text for cell in visible_cells),
                ("left",) + tuple(
                    _cell_alignment(note.columns[index], cell, note.statuses)
                    for index, cell in zip(indices, visible_cells)
                ),
            )
        )
    measured = measure_rows(tuple(rows), tuple(columns), current, padding=1)
    header = measure_row(GridRow("header", tuple(labels)), tuple(columns), current, padding=1)
    return HorizontalPage(indices, group_ids, tuple(columns), current, measured, header.height)


def _title_lines(title: str, width: int) -> tuple[str, ...]:
    output: list[str] = []
    try:
        for hard_line in title.split("\n"):
            output.extend(wrap_line(hard_line, width, start_column=0))
    except ValueError as error:
        raise FitError(str(error)) from error
    return tuple(output or [""])


def _vertical_bands(pages: Sequence[HorizontalPage], title_height: int, max_height: int) -> tuple[tuple[int, int], ...]:
    fixed = [title_height + 1 + page.header_height + 1 for page in pages]
    used = list(fixed)
    bands: list[tuple[int, int]] = []
    start = 0
    for row_index in range(len(pages[0].rows)):
        costs = [page.rows[row_index].height + 1 for page in pages]
        if any(base + cost > max_height for base, cost in zip(fixed, costs)):
            raise FitError(f"comparison row {pages[0].rows[row_index].key!r} is indivisible")
        if row_index > start and any(value + cost > max_height for value, cost in zip(used, costs)):
            bands.append((start, row_index))
            start = row_index
            used = list(fixed)
        used = [value + cost for value, cost in zip(used, costs)]
    bands.append((start, len(pages[0].rows)))
    return tuple(bands)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    title = _title_lines(note.title, options.max_width)
    page_specs = _horizontal_pages(note, options.max_width)
    pages = tuple(_page_context(note, indices, groups, options.max_width) for indices, groups in page_specs)
    bands = _vertical_bands(pages, len(title), options.max_height)
    if options.single_card and (len(pages) != 1 or len(bands) != 1):
        raise FitError(f"comparison needs {len(pages) * len(bands)} cards")
    cards: list[CardDraft] = []
    for vertical_index, (row_start, row_end) in enumerate(bands):
        row_keys = [row.key for row in note.rows[row_start:row_end]]
        for horizontal_index, page in enumerate(pages):
            table = render_table(
                page.columns,
                page.widths,
                page.rows[row_start:row_end],
                options.theme,
                padding=1,
            )
            text = "\n".join((*title, *table))
            cards.append(
                CardDraft(
                    f"comparison-h{horizontal_index:02d}-v{vertical_index:02d}",
                    text,
                    options.max_width,
                    len(text.split("\n")),
                    horizontal_index * (options.max_width + GUTTER),
                    vertical_index * (options.max_height + GUTTER),
                    {
                        "horizontal_index": horizontal_index,
                        "horizontal_count": len(pages),
                        "vertical_index": vertical_index,
                        "vertical_count": len(bands),
                        "row_start": row_start,
                        "row_end": row_end,
                        "row_keys": row_keys,
                        "column_ids": [note.columns[index].column_id for index in page.indices],
                        "group_ids": list(page.group_ids),
                        "column_widths": list(page.widths),
                    },
                )
            )
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
