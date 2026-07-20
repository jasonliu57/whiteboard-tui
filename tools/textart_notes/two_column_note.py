#!/usr/bin/env python3
"""Render paired Evidence Pair notes as deterministic text-art cards."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import pad_cells, text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import (
    array_value,
    bool_value,
    check_keys,
    int_value,
    object_value,
    string_value,
)
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.evidence_pair import Pair, measure_pairs, pair_columns
from tools.textart_notes.layouts.grid import Column, GridRow, MeasuredRow, measure_row


RENDERER = "two-column-note"
GUTTER = 2
_PAIR_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}\Z")


@dataclass(frozen=True)
class Side:
    label: str
    wrap: bool


@dataclass(frozen=True)
class Note:
    title: str
    left: Side
    right: Side
    left_weight: int
    right_weight: int
    pairs: tuple[Pair, ...]


def _side(value: object, path: str) -> Side:
    record = object_value(value, path)
    check_keys(record, path, required={"label", "wrap"}, allowed={"label", "wrap"})
    return Side(
        string_value(record["label"], f"{path}.label"),
        bool_value(record["wrap"], f"{path}.wrap"),
    )


def _normalize(data: dict[str, object]) -> Note:
    root = object_value(data, "input")
    required = {"title", "columns", "width_ratio", "pairs"}
    check_keys(root, "input", required=required, allowed=required)
    columns = object_value(root["columns"], "columns")
    check_keys(columns, "columns", required={"left", "right"}, allowed={"left", "right"})
    ratio = object_value(root["width_ratio"], "width_ratio")
    check_keys(ratio, "width_ratio", required={"left", "right"}, allowed={"left", "right"})
    values = array_value(root["pairs"], "pairs")
    if not values:
        raise InputError("pairs must not be empty")
    pairs: list[Pair] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = f"pairs[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "left", "right"}, allowed={"id", "left", "right"})
        pair_id = string_value(record["id"], f"{path}.id", single_line=True, allow_tabs=False)
        if _PAIR_ID_RE.fullmatch(pair_id) is None:
            raise InputError(f"{path}.id must be a safe ASCII identifier of at most 40 characters")
        if pair_id in seen:
            raise InputError(f"{path}.id duplicates {pair_id!r}")
        seen.add(pair_id)
        pairs.append(
            Pair(
                pair_id,
                string_value(record["left"], f"{path}.left", allow_empty=True),
                string_value(record["right"], f"{path}.right", allow_empty=True),
            )
        )
    return Note(
        title=string_value(root["title"], "title"),
        left=_side(columns["left"], "columns.left"),
        right=_side(columns["right"], "columns.right"),
        left_weight=int_value(ratio["left"], "width_ratio.left", minimum=1, maximum=1000),
        right_weight=int_value(ratio["right"], "width_ratio.right", minimum=1, maximum=1000),
        pairs=tuple(pairs),
    )


def _wrapped(text: str, width: int, start_column: int) -> tuple[str, ...]:
    output: list[str] = []
    try:
        for hard_line in text.split("\n"):
            output.extend(wrap_line(hard_line, width, start_column=start_column))
    except ValueError as error:
        raise FitError(str(error)) from error
    return tuple(output or [""])


def _glyphs(theme: str) -> dict[str, str]:
    selected = get_theme(theme)
    return {
        "h": selected.line(EAST | WEST),
        "v": selected.line(NORTH | SOUTH),
        "tl": selected.line(EAST | SOUTH),
        "tr": selected.line(SOUTH | WEST),
        "bl": selected.line(NORTH | EAST),
        "br": selected.line(NORTH | WEST),
        "left": selected.line(NORTH | EAST | SOUTH),
        "right": selected.line(NORTH | SOUTH | WEST),
        "down": selected.line(EAST | SOUTH | WEST),
        "up": selected.line(NORTH | EAST | WEST),
        "cross": selected.line(NORTH | EAST | SOUTH | WEST),
    }


def _rule(widths: tuple[int, int], glyph: dict[str, str], kind: str) -> str:
    ends = {
        "title": (glyph["left"], glyph["down"], glyph["right"]),
        "bottom": (glyph["bl"], glyph["up"], glyph["br"]),
    }
    left, middle, right = ends[kind]
    return left + glyph["h"] * widths[0] + middle + glyph["h"] * widths[1] + right


def _pair_rule(pair_id: str, widths: tuple[int, int], glyph: dict[str, str]) -> str:
    marker = f"[{pair_id}]"
    marker_width = text_width(marker)
    side = 0 if marker_width + 2 <= widths[0] else 1 if marker_width + 2 <= widths[1] else -1
    if side < 0:
        raise FitError(f"pair marker {marker!r} cannot fit either evidence column")
    segments = [glyph["h"] * widths[0], glyph["h"] * widths[1]]
    segments[side] = glyph["h"] + marker + glyph["h"] * (widths[side] - marker_width - 1)
    return glyph["left"] + segments[0] + glyph["cross"] + segments[1] + glyph["right"]


def _paint_row(row: MeasuredRow, widths: tuple[int, int], glyph: dict[str, str]) -> list[str]:
    output: list[str] = []
    for line_index in range(row.height):
        left = row.cells[0][line_index] if line_index < len(row.cells[0]) else ""
        right = row.cells[1][line_index] if line_index < len(row.cells[1]) else ""
        output.append(
            glyph["v"] + pad_cells(left, widths[0]) + glyph["v"]
            + pad_cells(right, widths[1]) + glyph["v"]
        )
    return output


def _paint_card(
    title: tuple[str, ...],
    header: MeasuredRow,
    rows: tuple[MeasuredRow, ...],
    widths: tuple[int, int],
    options: RenderOptions,
) -> str:
    glyph = _glyphs(options.theme)
    lines = [glyph["tl"] + glyph["h"] * (options.max_width - 2) + glyph["tr"]]
    lines.extend(glyph["v"] + pad_cells(line, options.max_width - 2) + glyph["v"] for line in title)
    lines.append(_rule(widths, glyph, "title"))
    lines.extend(_paint_row(header, widths, glyph))
    for row in rows:
        lines.append(_pair_rule(row.key, widths, glyph))
        lines.extend(_paint_row(row, widths, glyph))
    lines.append(_rule(widths, glyph, "bottom"))
    return "\n".join(lines)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    ratio = Fraction(note.left_weight, note.left_weight + note.right_weight)
    columns = pair_columns(
        note.left.label,
        note.right.label,
        ratio,
        left_wrap=note.left.wrap,
        right_wrap=note.right.wrap,
    )
    widths, measured = measure_pairs(note.pairs, columns, options.max_width, padding=0)
    title = _wrapped(note.title, options.max_width - 2, 1)
    header_columns = (
        Column("left", note.left.label, 1, align="left", wrap=True),
        Column("right", note.right.label, 1, align="left", wrap=True),
    )
    header = measure_row(
        GridRow("header", (note.left.label, note.right.label)),
        header_columns,
        widths,
        padding=0,
    )
    fixed = 1 + len(title) + 1 + header.height + 1
    pages: list[tuple[MeasuredRow, ...]] = []
    current: list[MeasuredRow] = []
    used = fixed
    for row in measured:
        cost = 1 + row.height
        if fixed + cost > options.max_height:
            raise FitError(f"pair {row.key!r} is indivisible and exceeds max_height")
        if current and used + cost > options.max_height:
            pages.append(tuple(current))
            current = []
            used = fixed
        current.append(row)
        used += cost
    pages.append(tuple(current))
    if options.single_card and len(pages) > 1:
        raise FitError(f"{len(pages)} complete-pair cards are required")
    cards: list[CardDraft] = []
    y = 0
    for index, page in enumerate(pages):
        text = _paint_card(title, header, page, widths, options)
        height = len(text.split("\n"))
        cards.append(
            CardDraft(
                logical_id=f"two-column-{index:03d}",
                text=text,
                width=options.max_width,
                height=height,
                x=0,
                y=y,
                metadata={
                    "style": "two_column",
                    "pair_ids": [row.key for row in page],
                    "pair_heights": [row.height for row in page],
                    "column_widths": list(widths),
                    "width_ratio": [note.left_weight, note.right_weight],
                    "wrap": [note.left.wrap, note.right.wrap],
                    "continuation_index": index,
                    "continuation_count": len(pages),
                },
            )
        )
        y += height + GUTTER
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
