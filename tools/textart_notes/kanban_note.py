#!/usr/bin/env python3
"""Render ordered kanban lanes as deterministic static text-art snapshots."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.boxes import frame_glyphs, frame_row, frame_rule
from tools.textart_notes.core.cell_width import pad_cells
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, int_value, object_value, slug_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.lanes import (
    LaneBand,
    LaneItem,
    allocate_lane_widths,
    lane_positions,
    synchronized_bands,
)


RENDERER = "kanban-note"
MIN_LANE_WIDTH = 20
GUTTER = 1
GUTTER_X = 4
GUTTER_Y = 2
MAX_RECORDS = 9999


@dataclass(frozen=True)
class Item:
    item_id: str
    title: str
    assignee: str | None
    priority: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Lane:
    lane_id: str
    name: str
    items: tuple[Item, ...]
    wip_limit: int | None


@dataclass(frozen=True)
class Board:
    board_id: str
    title: str
    lanes: tuple[Lane, ...]


@dataclass(frozen=True)
class GroupPlan:
    index: int
    lanes: tuple[Lane, ...]
    widths: tuple[int, ...]
    positions: tuple[int, ...]
    header_height: int
    capacity: int
    measured_items: tuple[tuple[tuple[str, ...], ...], ...]


def _optional(record: dict[str, object], key: str, path: str) -> str | None:
    return string_value(record[key], path, single_line=True) if key in record else None


def _normalize(data: dict[str, object]) -> Board:
    root = object_value(data, "input")
    check_keys(root, "input", required={"board_id", "title", "lanes"}, allowed={"board_id", "title", "lanes"})
    lane_values = array_value(root["lanes"], "lanes")
    if not 1 <= len(lane_values) <= MAX_RECORDS:
        raise InputError(f"lanes must contain 1..{MAX_RECORDS} entries")
    lanes: list[Lane] = []
    lane_ids: set[str] = set()
    item_ids: set[str] = set()
    total_items = 0
    for lane_index, lane_value in enumerate(lane_values):
        path = f"lanes[{lane_index}]"
        record = object_value(lane_value, path)
        check_keys(record, path, required={"id", "name", "items"}, allowed={"id", "name", "items", "wip_limit"})
        lane_id = slug_value(record["id"], f"{path}.id", max_length=64)
        if lane_id in lane_ids:
            raise InputError(f"duplicate lane id {lane_id!r}")
        lane_ids.add(lane_id)
        values = array_value(record["items"], f"{path}.items")
        total_items += len(values)
        if total_items > MAX_RECORDS:
            raise InputError(f"kanban board may contain at most {MAX_RECORDS} items")
        items: list[Item] = []
        for item_index, item_value in enumerate(values):
            item_path = f"{path}.items[{item_index}]"
            item_record = object_value(item_value, item_path)
            check_keys(
                item_record,
                item_path,
                required={"id", "title"},
                allowed={"id", "title", "assignee", "priority", "tags"},
            )
            item_id = slug_value(item_record["id"], f"{item_path}.id", max_length=64)
            if item_id in item_ids:
                raise InputError(f"duplicate item id {item_id!r}")
            item_ids.add(item_id)
            tags = tuple(
                string_value(tag, f"{item_path}.tags[{tag_index}]", single_line=True)
                for tag_index, tag in enumerate(array_value(item_record.get("tags", []), f"{item_path}.tags"))
            )
            if len(tags) > 20:
                raise InputError(f"{item_path}.tags may contain at most 20 entries")
            items.append(
                Item(
                    item_id,
                    string_value(item_record["title"], f"{item_path}.title", single_line=True),
                    _optional(item_record, "assignee", f"{item_path}.assignee"),
                    _optional(item_record, "priority", f"{item_path}.priority"),
                    tags,
                )
            )
        wip_limit = (
            int_value(record["wip_limit"], f"{path}.wip_limit", minimum=0, maximum=MAX_RECORDS)
            if "wip_limit" in record
            else None
        )
        lanes.append(
            Lane(
                lane_id,
                string_value(record["name"], f"{path}.name", single_line=True),
                tuple(items),
                wip_limit,
            )
        )
    return Board(
        slug_value(root["board_id"], "board_id", max_length=64),
        string_value(root["title"], "title", single_line=True),
        tuple(lanes),
    )


def _wrap(value: str, width: int, start_column: int) -> list[str]:
    try:
        return wrap_line(value, width, start_column=start_column)
    except ValueError as error:
        raise FitError(str(error)) from error


def _box(lines: Sequence[str], width: int, theme: str) -> tuple[str, ...]:
    return (
        frame_rule(width, theme, position="top"),
        *(frame_row(width, theme, line) for line in lines),
        frame_rule(width, theme, position="bottom"),
    )


def _board_header(board: Board, width: int, group: int, band: int, theme: str) -> tuple[str, ...]:
    inner = width - 4
    if inner < 1:
        raise FitError("card is too narrow for kanban context")
    fields = (f"KANBAN | {board.title}", f"board:{board.board_id}", f"G{group:04d} B{band:04d}")
    rows = [row for field in fields for row in _wrap(field, inner, 2)]
    return _box(rows, width, theme)


def _lane_status(lane: Lane) -> str:
    count = len(lane.items)
    if lane.wip_limit is None:
        return f"{lane.name} [count:{count}]"
    warning = " !WIP-EXCEEDED" if count > lane.wip_limit else ""
    return f"{lane.name} [count:{count}/WIP:{lane.wip_limit}]{warning}"


def _lane_headers(lane: Lane, width: int, x: int) -> tuple[str, ...]:
    inner = width - 4
    return tuple(
        row
        for field in (f"lane:{lane.lane_id}", _lane_status(lane))
        for row in _wrap(field, inner, x + 2)
    )


def _item_fields(item: Item) -> tuple[str, ...]:
    fields = [f"{item.item_id} | {item.title}"]
    if item.assignee is not None:
        fields.append(f"assignee: {item.assignee}")
    if item.priority is not None:
        fields.append(f"priority: {item.priority}")
    if item.tags:
        fields.append("tags: " + " ".join(f"#{tag}" for tag in item.tags))
    return tuple(fields)


def _paint_item(item: Item, lane_width: int, lane_x: int, theme: str) -> tuple[str, ...]:
    item_width = lane_width - 2
    inner = item_width - 4
    if inner < 1:
        raise FitError(f"lane is too narrow for item {item.item_id!r}")
    item_x = lane_x + 1
    rows = [row for field in _item_fields(item) for row in _wrap(field, inner, item_x + 2)]
    return _box(rows, item_width, theme)


def _candidate(
    board: Board,
    lanes: tuple[Lane, ...],
    widths: tuple[int, ...],
    positions: tuple[int, ...],
    group: int,
    options: RenderOptions,
) -> GroupPlan:
    headers = tuple(_lane_headers(lane, width, x) for lane, width, x in zip(lanes, widths, positions))
    header_height = max(len(lines) for lines in headers)
    board_height = len(_board_header(board, options.max_width, group, 1, options.theme))
    capacity = options.max_height - board_height - 1 - (header_height + 3)
    if capacity < 1:
        raise FitError("board and lane context leaves no content row")
    measured: list[tuple[tuple[str, ...], ...]] = []
    for lane, width, x in zip(lanes, widths, positions):
        item_lines = tuple(_paint_item(item, width, x, options.theme) for item in lane.items)
        oversized = next((item.item_id for item, lines in zip(lane.items, item_lines) if len(lines) > capacity), None)
        if oversized is not None:
            raise FitError(f"item {oversized!r} cannot fit intact in lane {lane.lane_id!r}")
        measured.append(item_lines)
    return GroupPlan(group, lanes, widths, positions, header_height, capacity, tuple(measured))


def _groups(board: Board, options: RenderOptions) -> tuple[GroupPlan, ...]:
    if options.max_width < MIN_LANE_WIDTH:
        raise FitError(f"kanban requires max_width >= {MIN_LANE_WIDTH}")
    output: list[GroupPlan] = []
    offset = 0
    group = 1
    while offset < len(board.lanes):
        remaining = len(board.lanes) - offset
        maximum = min(remaining, (options.max_width + GUTTER) // (MIN_LANE_WIDTH + GUTTER))
        accepted: GroupPlan | None = None
        last_error: FitError | None = None
        for count in range(maximum, 0, -1):
            try:
                widths = allocate_lane_widths(options.max_width, count, gutter=GUTTER, minimum=MIN_LANE_WIDTH)
                positions = lane_positions(widths, gutter=GUTTER)
                accepted = _candidate(
                    board,
                    board.lanes[offset : offset + count],
                    widths,
                    positions,
                    group,
                    options,
                )
            except FitError as error:
                last_error = error
                continue
            break
        if accepted is None:
            if last_error is not None:
                raise last_error
            raise FitError("no lane group fits the requested card")
        output.append(accepted)
        offset += len(accepted.lanes)
        group += 1
    return tuple(output)


def _bands(group: GroupPlan) -> tuple[LaneBand, ...]:
    return synchronized_bands(
        tuple(
            tuple(LaneItem(item.item_id, len(lines)) for item, lines in zip(lane.items, measured))
            for lane, measured in zip(group.lanes, group.measured_items)
        ),
        group.capacity,
    )


def _paint_lane(
    lane: Lane,
    item_lines: tuple[tuple[str, ...], ...],
    width: int,
    x: int,
    header_height: int,
    content_height: int,
    item_range: tuple[int, int],
    theme: str,
) -> tuple[str, ...]:
    glyphs = frame_glyphs(theme)
    inner = width - 2
    headers = _lane_headers(lane, width, x)
    lines = [frame_rule(width, theme, position="top")]
    lines.extend(frame_row(width, theme, row) for row in headers)
    lines.extend(frame_row(width, theme) for _ in range(header_height - len(headers)))
    lines.append(frame_rule(width, theme, position="middle"))
    start, end = item_range
    content: list[str] = []
    if start < end:
        for index in range(start, end):
            if content:
                content.append(" " * inner)
            content.extend(item_lines[index])
    else:
        marker = "[empty]" if not lane.items else "[done]"
        content.append(pad_cells(marker, inner))
    content.extend(" " * inner for _ in range(content_height - len(content)))
    lines.extend(glyphs.vertical + row + glyphs.vertical for row in content)
    lines.append(frame_rule(width, theme, position="bottom"))
    return tuple(lines)


def _card(
    board: Board,
    group: GroupPlan,
    band: LaneBand,
    band_index: int,
    band_count: int,
    group_count: int,
    options: RenderOptions,
) -> CardDraft:
    lines = list(_board_header(board, options.max_width, group.index, band_index, options.theme))
    lines.append("")
    lane_blocks = tuple(
        _paint_lane(
            lane,
            measured,
            width,
            x,
            group.header_height,
            band.content_height,
            item_range,
            options.theme,
        )
        for lane, measured, width, x, item_range in zip(
            group.lanes,
            group.measured_items,
            group.widths,
            group.positions,
            band.ranges,
        )
    )
    for row in range(len(lane_blocks[0])):
        lines.append((" " * GUTTER).join(block[row] for block in lane_blocks))
    item_ids = {
        lane.lane_id: [item.item_id for item in lane.items[start:end]]
        for lane, (start, end) in zip(group.lanes, band.ranges)
    }
    warning_ids = [
        lane.lane_id
        for lane in group.lanes
        if lane.wip_limit is not None and len(lane.items) > lane.wip_limit
    ]
    logical_id = f"kanban-g{group.index:04d}-b{band_index:04d}"
    return CardDraft(
        logical_id,
        "\n".join(lines),
        options.max_width,
        len(lines),
        x=(group.index - 1) * (options.max_width + GUTTER_X),
        y=(band_index - 1) * (options.max_height + GUTTER_Y),
        metadata={
            "board_id": board.board_id,
            "group_index": group.index,
            "group_count": group_count,
            "band_index": band_index,
            "band_count": band_count,
            "lane_ids": [lane.lane_id for lane in group.lanes],
            "item_ids_by_lane": item_ids,
            "wip_exceeded_lane_ids": warning_ids,
            "snapshot": True,
        },
    )


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    board = _normalize(data)
    groups = _groups(board, options)
    planned = tuple((group, _bands(group)) for group in groups)
    count = sum(len(bands) for _, bands in planned)
    if options.single_card and count > 1:
        raise FitError(f"kanban snapshot requires {count} cards under --single-card")
    cards = tuple(
        _card(board, group, band, band_index, len(bands), len(groups), options)
        for group, bands in planned
        for band_index, band in enumerate(bands, start=1)
    )
    result = RenderResult(RENDERER, options.theme, cards)
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
