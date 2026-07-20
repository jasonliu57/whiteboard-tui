#!/usr/bin/env python3
"""Render discrete Grid matrices or exact bounded Axis matrices."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.boxes import frame_row, frame_rule
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import (
    array_value,
    check_keys,
    decimal_value,
    int_value,
    object_value,
    slug_value,
    string_value,
)
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.axis import AxisPoint, AxisRange, QuantizedGroup, quantize_points
from tools.textart_notes.layouts.grid import (
    Column,
    GridRow,
    MeasuredRow,
    allocate_widths,
    measure_rows,
    render_table,
    split_column_groups,
    table_content_budget,
)


RENDERER = "matrix-note"
GUTTER = 2
MARKERS = {
    "ascii": {"dot": "o", "circle": "O", "cross": "x", "alert": "!", "collision": "*"},
    "unicode-light": {"dot": "●", "circle": "○", "cross": "×", "alert": "!", "collision": "◆"},
    "unicode-rich": {"dot": "●", "circle": "○", "cross": "×", "alert": "!", "collision": "◆"},
}


@dataclass(frozen=True)
class Legend:
    legend_id: str
    label: str
    marker: str


@dataclass(frozen=True)
class AxisLabel:
    axis_id: str
    label: str


@dataclass(frozen=True)
class NamedLabel:
    item_id: str
    label: str


@dataclass(frozen=True)
class Cell:
    row_id: str
    column_id: str
    state_id: str
    label: str


@dataclass(frozen=True)
class GridMatrix:
    title: str
    row_axis: AxisLabel
    column_axis: AxisLabel
    rows: tuple[NamedLabel, ...]
    columns: tuple[NamedLabel, ...]
    cells: tuple[Cell, ...]
    legend: tuple[Legend, ...]
    row_label_width: int
    minimum_cell_width: int


@dataclass(frozen=True)
class NumericAxis:
    axis_id: str
    label: str
    minimum: Decimal
    maximum: Decimal


@dataclass(frozen=True)
class Point:
    point_id: str
    label: str
    x: Decimal
    y: Decimal
    state_id: str


@dataclass(frozen=True)
class AxisMatrix:
    title: str
    x_axis: NumericAxis
    y_axis: NumericAxis
    points: tuple[Point, ...]
    legend: tuple[Legend, ...]
    plot_height: int


Matrix = GridMatrix | AxisMatrix


def _legend(value: object) -> tuple[Legend, ...]:
    values = array_value(value, "legend")
    if not values:
        raise InputError("legend must not be empty")
    output: list[Legend] = []
    seen: set[str] = set()
    for index, item in enumerate(values):
        path = f"legend[{index}]"
        record = object_value(item, path)
        check_keys(record, path, required={"id", "label", "marker"}, allowed={"id", "label", "marker"})
        legend_id = slug_value(record["id"], f"{path}.id")
        if legend_id in seen:
            raise InputError(f"duplicate legend id {legend_id!r}")
        seen.add(legend_id)
        marker = record["marker"]
        if marker not in {"dot", "circle", "cross", "alert"}:
            raise InputError(f"{path}.marker must be dot, circle, cross, or alert")
        output.append(Legend(legend_id, string_value(record["label"], f"{path}.label", single_line=True), str(marker)))
    return tuple(output)


def _axis_label(value: object, path: str) -> AxisLabel:
    record = object_value(value, path)
    check_keys(record, path, required={"id", "label"}, allowed={"id", "label"})
    return AxisLabel(slug_value(record["id"], f"{path}.id"), string_value(record["label"], f"{path}.label", single_line=True))


def _named_labels(value: object, path: str) -> tuple[NamedLabel, ...]:
    values = array_value(value, path)
    if not values:
        raise InputError(f"{path} must not be empty")
    output: list[NamedLabel] = []
    seen: set[str] = set()
    for index, item in enumerate(values):
        item_path = f"{path}[{index}]"
        record = object_value(item, item_path)
        check_keys(record, item_path, required={"id", "label"}, allowed={"id", "label"})
        item_id = slug_value(record["id"], f"{item_path}.id")
        if item_id in seen:
            raise InputError(f"duplicate {path} id {item_id!r}")
        seen.add(item_id)
        output.append(NamedLabel(item_id, string_value(record["label"], f"{item_path}.label", single_line=True)))
    return tuple(output)


def _normalize_grid(root: dict[str, object]) -> GridMatrix:
    required = {"mode", "title", "row_axis", "column_axis", "rows", "columns", "cells", "legend", "layout"}
    check_keys(root, "input", required=required, allowed=required)
    rows = _named_labels(root["rows"], "rows")
    columns = _named_labels(root["columns"], "columns")
    legend = _legend(root["legend"])
    legend_ids = {item.legend_id for item in legend}
    row_ids = {item.item_id for item in rows}
    column_ids = {item.item_id for item in columns}
    cells: list[Cell] = []
    coordinates: set[tuple[str, str]] = set()
    for index, value in enumerate(array_value(root["cells"], "cells")):
        path = f"cells[{index}]"
        record = object_value(value, path)
        required_cell = {"row_id", "column_id", "state_id", "label"}
        check_keys(record, path, required=required_cell, allowed=required_cell)
        row_id = slug_value(record["row_id"], f"{path}.row_id")
        column_id = slug_value(record["column_id"], f"{path}.column_id")
        state_id = slug_value(record["state_id"], f"{path}.state_id")
        if row_id not in row_ids or column_id not in column_ids:
            raise InputError(f"{path} references an unknown matrix coordinate")
        if state_id not in legend_ids:
            raise InputError(f"{path}.state_id references unknown legend {state_id!r}")
        coordinate = (row_id, column_id)
        if coordinate in coordinates:
            raise InputError(f"duplicate matrix coordinate {coordinate!r}")
        coordinates.add(coordinate)
        cells.append(Cell(row_id, column_id, state_id, string_value(record["label"], f"{path}.label", allow_empty=True, single_line=True)))
    expected = {(row.item_id, column.item_id) for row in rows for column in columns}
    if coordinates != expected:
        missing = sorted(expected - coordinates)
        extra = sorted(coordinates - expected)
        raise InputError(f"cells must form a complete rectangle; missing={missing}, extra={extra}")
    layout = object_value(root["layout"], "layout")
    check_keys(layout, "layout", required={"row_label_width", "min_cell_width"}, allowed={"row_label_width", "min_cell_width"})
    return GridMatrix(
        string_value(root["title"], "title", single_line=True),
        _axis_label(root["row_axis"], "row_axis"),
        _axis_label(root["column_axis"], "column_axis"),
        rows,
        columns,
        tuple(cells),
        legend,
        int_value(layout["row_label_width"], "layout.row_label_width", minimum=4, maximum=80),
        int_value(layout["min_cell_width"], "layout.min_cell_width", minimum=4, maximum=40),
    )


def _numeric_axis(value: object, path: str) -> NumericAxis:
    record = object_value(value, path)
    check_keys(record, path, required={"id", "label", "min", "max"}, allowed={"id", "label", "min", "max"})
    minimum = decimal_value(record["min"], f"{path}.min")
    maximum = decimal_value(record["max"], f"{path}.max")
    if minimum >= maximum:
        raise InputError(f"{path}.min must be less than max")
    return NumericAxis(
        slug_value(record["id"], f"{path}.id"),
        string_value(record["label"], f"{path}.label", single_line=True),
        minimum,
        maximum,
    )


def _normalize_axis(root: dict[str, object]) -> AxisMatrix:
    required = {"mode", "title", "x_axis", "y_axis", "points", "legend", "plot_height"}
    check_keys(root, "input", required=required, allowed=required)
    x_axis = _numeric_axis(root["x_axis"], "x_axis")
    y_axis = _numeric_axis(root["y_axis"], "y_axis")
    if x_axis.axis_id == y_axis.axis_id:
        raise InputError("x_axis.id and y_axis.id must differ")
    legend = _legend(root["legend"])
    legend_ids = {item.legend_id for item in legend}
    values = array_value(root["points"], "points")
    if not values:
        raise InputError("points must not be empty")
    points: list[Point] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = f"points[{index}]"
        record = object_value(value, path)
        required_point = {"id", "label", "x", "y", "state_id"}
        check_keys(record, path, required=required_point, allowed=required_point)
        point_id = slug_value(record["id"], f"{path}.id")
        if point_id in seen:
            raise InputError(f"duplicate point id {point_id!r}")
        seen.add(point_id)
        x = decimal_value(record["x"], f"{path}.x")
        y = decimal_value(record["y"], f"{path}.y")
        if not x_axis.minimum <= x <= x_axis.maximum or not y_axis.minimum <= y <= y_axis.maximum:
            raise InputError(f"{path} is outside the inclusive axis bounds")
        state_id = slug_value(record["state_id"], f"{path}.state_id")
        if state_id not in legend_ids:
            raise InputError(f"{path}.state_id references unknown legend {state_id!r}")
        points.append(Point(point_id, string_value(record["label"], f"{path}.label", single_line=True), x, y, state_id))
    return AxisMatrix(
        string_value(root["title"], "title", single_line=True),
        x_axis,
        y_axis,
        tuple(points),
        legend,
        int_value(root["plot_height"], "plot_height", minimum=3, maximum=60),
    )


def _normalize(data: dict[str, object]) -> Matrix:
    root = object_value(data, "input")
    mode = root.get("mode")
    if mode == "grid":
        return _normalize_grid(root)
    if mode == "axis":
        return _normalize_axis(root)
    raise InputError("mode must be exactly 'grid' or 'axis'")


def _marker(legend: Legend, theme: str) -> str:
    return MARKERS[theme][legend.marker]


def _wrap(value: str, width: int, start_column: int = 0) -> list[str]:
    try:
        return wrap_line(value, width, start_column=start_column)
    except ValueError as error:
        raise FitError(str(error)) from error


def _full_rows(value: str, width: int) -> list[str]:
    return _wrap(value, width, 0)


def _legend_rows(legend: tuple[Legend, ...], width: int, theme: str, *, collision: bool = False) -> tuple[str, ...]:
    rows = _full_rows("Legend:", width)
    for item in legend:
        rows.extend(_full_rows(f"{_marker(item, theme)} [{item.legend_id}] {item.label}", width))
    if collision:
        rows.extend(_full_rows(f"{MARKERS[theme]['collision']} [collision] 2+ points share one quantized cell", width))
    return tuple(rows)


def _grid_context(note: GridMatrix, width: int) -> tuple[str, ...]:
    values = (
        f"MATRIX | {note.title}",
        f"Rows [{note.row_axis.axis_id}]: {note.row_axis.label}",
        f"Columns [{note.column_axis.axis_id}]: {note.column_axis.label}",
    )
    return tuple(row for value in values for row in _full_rows(value, width))


def _paginate_grid_rows(
    prefix: tuple[str, ...],
    legend: tuple[str, ...],
    columns: tuple[Column, ...],
    widths: tuple[int, ...],
    rows: tuple[MeasuredRow, ...],
    theme: str,
    max_height: int,
) -> tuple[tuple[MeasuredRow, ...], ...]:
    pages: list[tuple[MeasuredRow, ...]] = []
    current: list[MeasuredRow] = []

    def height(candidate: Sequence[MeasuredRow]) -> int:
        return len(prefix) + 1 + len(render_table(columns, widths, candidate, theme)) + 1 + len(legend)

    for row in rows:
        if height((row,)) > max_height:
            raise FitError(f"indivisible matrix row {row.key!r} cannot fit with repeated context")
        if current and height((*current, row)) > max_height:
            pages.append(tuple(current))
            current = []
        current.append(row)
    if current:
        pages.append(tuple(current))
    return tuple(pages)


def _render_grid(note: GridMatrix, options: RenderOptions) -> tuple[CardDraft, ...]:
    legends = {item.legend_id: item for item in note.legend}
    cell_map = {(cell.row_id, cell.column_id): cell for cell in note.cells}
    all_columns = (
        Column("row-label", note.row_axis.label, note.row_label_width, 1),
        *(Column(column.item_id, column.label, note.minimum_cell_width, 1) for column in note.columns),
    )
    groups = split_column_groups(all_columns, options.max_width, preserve_index=0)
    prefix = _grid_context(note, options.max_width)
    legend_rows = _legend_rows(note.legend, options.max_width, options.theme)
    cards: list[CardDraft] = []
    for group_index, indices in enumerate(groups):
        columns = tuple(all_columns[index] for index in indices)
        budget = table_content_budget(options.max_width, len(columns))
        widths = allocate_widths(budget, columns)
        data_indices = indices[1:]
        grid_rows = tuple(
            GridRow(
                row.item_id,
                (
                    row.label,
                    *(
                        (
                            f"{_marker(legends[cell_map[(row.item_id, note.columns[index - 1].item_id)].state_id], options.theme)} "
                            f"{cell_map[(row.item_id, note.columns[index - 1].item_id)].label}"
                        ).rstrip()
                        for index in data_indices
                    ),
                ),
            )
            for row in note.rows
        )
        measured = measure_rows(grid_rows, columns, widths)
        pages = _paginate_grid_rows(prefix, legend_rows, columns, widths, measured, options.theme, options.max_height)
        for page_index, page in enumerate(pages):
            lines = [*prefix, "", *render_table(columns, widths, page, options.theme), "", *legend_rows]
            row_start = next(index for index, row in enumerate(note.rows) if row.item_id == page[0].key)
            row_end = row_start + len(page)
            column_start = data_indices[0] - 1
            column_end = data_indices[-1]
            cards.append(
                CardDraft(
                    f"matrix-grid-r{row_start:04d}-{row_end:04d}-c{column_start:04d}-{column_end:04d}",
                    "\n".join(lines),
                    options.max_width,
                    len(lines),
                    x=group_index * (options.max_width + GUTTER),
                    y=page_index * (options.max_height + GUTTER),
                    metadata={
                        "mode": "grid",
                        "row_start": row_start,
                        "row_end": row_end,
                        "column_start": column_start,
                        "column_end": column_end,
                        "row_ids": [row.key for row in page],
                        "column_ids": [note.columns[index - 1].item_id for index in data_indices],
                        "legend_ids": [item.legend_id for item in note.legend],
                        "legend_repeated": True,
                    },
                )
            )
    return tuple(cards)


def _decimal_text(value: Decimal) -> str:
    normalized = Decimal(0) if value.is_zero() else value.normalize()
    return format(normalized, "f")


def _axis_context(note: AxisMatrix, width: int) -> tuple[str, ...]:
    values = (
        f"MATRIX | {note.title}",
        f"X [{note.x_axis.axis_id}] {note.x_axis.label}: {_decimal_text(note.x_axis.minimum)}..{_decimal_text(note.x_axis.maximum)}",
        f"Y [{note.y_axis.axis_id}] {note.y_axis.label}: {_decimal_text(note.y_axis.minimum)}..{_decimal_text(note.y_axis.maximum)}",
    )
    return tuple(row for value in values for row in _full_rows(value, width))


def _axis_group_rows(
    group: QuantizedGroup,
    points: dict[str, Point],
    legends: dict[str, Legend],
    width: int,
    theme: str,
) -> tuple[str, ...]:
    rows: list[str] = []
    if len(group.points) > 1:
        rows.extend(_full_rows(f"{MARKERS[theme]['collision']} collision cell ({group.qx},{group.qy}), {len(group.points)} points:", width))
        prefix = "  "
    else:
        prefix = ""
    for quantized in group.points:
        point = points[quantized.key]
        marker = _marker(legends[point.state_id], theme)
        value = (
            f"{prefix}{marker} [{point.point_id}] {point.label} "
            f"({_decimal_text(point.x)},{_decimal_text(point.y)}) -> ({group.qx},{group.qy})"
        )
        rows.extend(_full_rows(value, width))
    return tuple(rows)


def _paint_plot(groups: Sequence[QuantizedGroup], width: int, height: int, theme: str, legends: dict[str, Legend], points: dict[str, Point]) -> tuple[str, ...]:
    cells = [[" " for _ in range(width)] for _ in range(height)]
    for group in groups:
        if len(group.points) > 1:
            marker = MARKERS[theme]["collision"]
        else:
            marker = _marker(legends[points[group.points[0].key].state_id], theme)
        cells[group.qy][group.qx] = marker
    return tuple("".join(row) for row in cells)


def _render_axis(note: AxisMatrix, options: RenderOptions) -> tuple[CardDraft, ...]:
    if options.max_width < 12:
        raise FitError("axis matrix requires at least 12 cells of width")
    plot_width = options.max_width - 4
    x_range = AxisRange(Fraction(note.x_axis.minimum), Fraction(note.x_axis.maximum))
    y_range = AxisRange(Fraction(note.y_axis.minimum), Fraction(note.y_axis.maximum))
    groups = quantize_points(
        tuple(AxisPoint(point.point_id, Fraction(point.x), Fraction(point.y)) for point in note.points),
        x_range,
        y_range,
        plot_width=plot_width,
        plot_height=note.plot_height,
    )
    collision = any(len(group.points) > 1 for group in groups)
    prefix = _axis_context(note, options.max_width)
    legend_rows = _legend_rows(note.legend, options.max_width, options.theme, collision=collision)
    point_map = {point.point_id: point for point in note.points}
    legend_map = {item.legend_id: item for item in note.legend}
    measured = tuple(_axis_group_rows(group, point_map, legend_map, options.max_width, options.theme) for group in groups)
    fixed = len(prefix) + 1 + note.plot_height + 2 + 1 + len(_full_rows("Points:", options.max_width)) + 1 + len(legend_rows)
    capacity = options.max_height - fixed
    if capacity < 1:
        raise FitError("axis context, plot, and legend leave no point-label row")
    pages: list[tuple[int, int]] = []
    start = 0
    used = 0
    for index, rows in enumerate(measured):
        if len(rows) > capacity:
            ids = [point.key for point in groups[index].points]
            raise FitError(f"axis collision/point group {ids!r} is indivisible and cannot fit")
        if index > start and used + len(rows) > capacity:
            pages.append((start, index))
            start = index
            used = 0
        used += len(rows)
    pages.append((start, len(groups)))
    cards: list[CardDraft] = []
    for page_index, (start, end) in enumerate(pages):
        page_groups = groups[start:end]
        plot = _paint_plot(page_groups, plot_width, note.plot_height, options.theme, legend_map, point_map)
        plot_lines = [
            frame_rule(options.max_width, options.theme, position="top"),
            *(frame_row(options.max_width, options.theme, row) for row in plot),
            frame_rule(options.max_width, options.theme, position="bottom"),
        ]
        point_rows = [row for rows in measured[start:end] for row in rows]
        lines = [*prefix, "", *plot_lines, *(_full_rows("Points:", options.max_width)), *point_rows, "", *legend_rows]
        point_ids = [point.key for group in page_groups for point in group.points]
        cards.append(
            CardDraft(
                f"matrix-axis-{page_index:04d}",
                "\n".join(lines),
                options.max_width,
                len(lines),
                x=0,
                y=page_index * (options.max_height + GUTTER),
                metadata={
                    "mode": "axis",
                    "page_index": page_index,
                    "point_ids": point_ids,
                    "quantized": [
                        [point.key, group.qx, group.qy]
                        for group in page_groups
                        for point in group.points
                    ],
                    "collision_groups": [
                        [point.key for point in group.points]
                        for group in page_groups
                        if len(group.points) > 1
                    ],
                    "coordinate_origin": "plot-top-left",
                    "legend_ids": [item.legend_id for item in note.legend],
                    "legend_repeated": True,
                },
            )
        )
    return tuple(cards)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    cards = _render_grid(note, options) if isinstance(note, GridMatrix) else _render_axis(note, options)
    if options.single_card and len(cards) > 1:
        raise FitError(f"matrix requires {len(cards)} cards under --single-card")
    result = RenderResult(RENDERER, options.theme, cards)
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
