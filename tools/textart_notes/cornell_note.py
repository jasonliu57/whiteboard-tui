#!/usr/bin/env python3
"""Render Cornell notes from spanning Schema Blocks and Evidence Pairs."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.boxes import frame_row
from tools.textart_notes.core.cell_width import pad_cells
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, decimal_value, object_value, string_value
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.evidence_pair import Pair, measure_pairs_at_widths
from tools.textart_notes.layouts.grid import Column, MeasuredRow, measure_row, render_table, GridRow, table_content_budget
from tools.textart_notes.layouts.schema_blocks import Block


RENDERER = "cornell-note"
GUTTER = 2
_PAIR_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_METADATA_KEYS = ("course", "date", "source")


@dataclass(frozen=True)
class Cornell:
    topic: str
    pairs: tuple[Pair, ...]
    summary: str
    cue_ratio: Fraction
    metadata: tuple[tuple[str, str], ...]


def _ratio(value: object) -> Fraction:
    result = Fraction(decimal_value(value, "cue_ratio"))
    if not Fraction(1, 4) <= result <= Fraction(7, 20):
        raise InputError("cue_ratio must be between 0.25 and 0.35")
    return result


def _normalize(data: dict[str, object]) -> Cornell:
    root = object_value(data, "input")
    required = {"topic", "pairs", "summary", "cue_ratio"}
    check_keys(root, "input", required=required, allowed=required | {"metadata"})
    values = array_value(root["pairs"], "pairs")
    if not values:
        raise InputError("pairs must not be empty")
    pairs: list[Pair] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = f"pairs[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "cue", "note"}, allowed={"id", "cue", "note"})
        pair_id = string_value(record["id"], f"{path}.id", single_line=True, allow_tabs=False)
        if _PAIR_RE.fullmatch(pair_id) is None:
            raise InputError(f"{path}.id must be a lowercase ASCII slug")
        if pair_id in seen:
            raise InputError(f"duplicate pair id {pair_id!r}")
        seen.add(pair_id)
        pairs.append(
            Pair(
                pair_id,
                f"[{pair_id}] " + string_value(record["cue"], f"{path}.cue"),
                string_value(record["note"], f"{path}.note"),
            )
        )
    metadata: list[tuple[str, str]] = []
    if "metadata" in root:
        record = object_value(root["metadata"], "metadata")
        check_keys(record, "metadata", required=set(), allowed=set(_METADATA_KEYS))
        for key in _METADATA_KEYS:
            if key in record:
                metadata.append((key, string_value(record[key], f"metadata.{key}")))
    return Cornell(
        string_value(root["topic"], "topic"),
        tuple(pairs),
        string_value(root["summary"], "summary"),
        _ratio(root["cue_ratio"]),
        tuple(metadata),
    )


def _round_half_up(value: Fraction) -> int:
    return (value.numerator * 2 + value.denominator) // (value.denominator * 2)


def _widths(total_width: int, ratio: Fraction) -> tuple[int, int]:
    budget = table_content_budget(total_width, 2, padding=1)
    cue = _round_half_up(Fraction(budget) * ratio)
    note = budget - cue
    if cue < 5 or note < 8:
        raise FitError("Cornell columns require at least 5 cue and 8 note cells")
    return cue, note


def _wrapped(text: str, width: int, start: int) -> tuple[str, ...]:
    output: list[str] = []
    try:
        for hard_line in text.split("\n"):
            output.extend(wrap_line(hard_line, width, start_column=start))
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
    }


def _span_border(width: int, glyph: dict[str, str], *, top: bool) -> str:
    return (
        (glyph["tl"] if top else glyph["bl"])
        + glyph["h"] * (width - 2)
        + (glyph["tr"] if top else glyph["br"])
    )


def _connector(widths: tuple[int, int], glyph: dict[str, str], *, downward: bool) -> str:
    middle = glyph["down"] if downward else glyph["up"]
    return (
        glyph["left"]
        + glyph["h"] * (widths[0] + 2)
        + middle
        + glyph["h"] * (widths[1] + 2)
        + glyph["right"]
    )


def _paint(
    header: Block,
    summary: Block,
    columns: tuple[Column, Column],
    widths: tuple[int, int],
    rows: tuple[MeasuredRow, ...],
    options: RenderOptions,
) -> str:
    glyph = _glyphs(options.theme)
    table = render_table(columns, widths, rows, options.theme, padding=1)
    lines = [_span_border(options.max_width, glyph, top=True)]
    lines.extend(frame_row(options.max_width, options.theme, line) for line in header.lines)
    lines.append(_connector(widths, glyph, downward=True))
    lines.extend(table[1:-1])
    lines.append(_connector(widths, glyph, downward=False))
    lines.extend(frame_row(options.max_width, options.theme, line) for line in summary.lines)
    lines.append(_span_border(options.max_width, glyph, top=False))
    return "\n".join(lines)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    widths = _widths(options.max_width, note.cue_ratio)
    columns = (
        Column("cue", "CUE / 線索", 5, align="left", wrap=True),
        Column("note", "NOTES / 筆記", 8, align="left", wrap=True),
    )
    rows = measure_pairs_at_widths(note.pairs, columns, widths, padding=1)
    header_lines: list[str] = list(_wrapped(f"TOPIC: {note.topic}", options.max_width - 4, 2))
    for key, value in note.metadata:
        header_lines.extend(_wrapped(f"{key.upper()}: {value}", options.max_width - 4, 2))
    summary_lines = _wrapped(f"SUMMARY: {note.summary}", options.max_width - 4, 2)
    header = Block("header", tuple(header_lines), repeat_header=True)
    summary = Block("summary", summary_lines, repeat_header=True)
    header_measure = measure_row(
        GridRow("header", tuple(column.label for column in columns)),
        columns,
        widths,
        padding=1,
    )
    fixed = 5 + header.height + header_measure.height + summary.height
    pages: list[tuple[MeasuredRow, ...]] = []
    current: list[MeasuredRow] = []
    used = fixed
    for row in rows:
        cost = row.height + (1 if current else 0)
        if fixed + row.height > options.max_height:
            raise FitError(f"Cornell pair {row.key!r} is indivisible with repeated summary")
        if current and used + cost > options.max_height:
            pages.append(tuple(current))
            current = []
            used = fixed
            cost = row.height
        current.append(row)
        used += cost
    pages.append(tuple(current))
    if options.single_card and len(pages) > 1:
        raise FitError(f"Cornell note requires {len(pages)} complete-pair cards")
    ratio_text = format(float(note.cue_ratio), ".4f").rstrip("0").rstrip(".")
    cards: list[CardDraft] = []
    y = 0
    for page_index, page in enumerate(pages):
        text = _paint(header, summary, columns, widths, page, options)
        height = len(text.split("\n"))
        cards.append(
            CardDraft(
                f"cornell-{page_index:03d}",
                text,
                options.max_width,
                height,
                0,
                y,
                {
                    "page_index": page_index,
                    "page_count": len(pages),
                    "pair_ids": [row.key for row in page],
                    "cue_ratio": ratio_text,
                    "column_widths": list(widths),
                    "summary_repeated": True,
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
