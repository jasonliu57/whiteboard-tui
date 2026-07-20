#!/usr/bin/env python3
"""Render stable source-range annotations as Evidence Pair text-art cards."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import pad_cells
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, int_value, object_value, slug_value, string_value
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_preserving_line, wrap_preserving_text
from tools.textart_notes.layouts.evidence_pair import (
    ResolvedAnchor,
    SourceAnchor,
    SourceSlice,
    allocate_pair_widths,
    resolve_source_anchors,
)


RENDERER = "annotated-note"
MARKER_WIDTH = 3
MAX_LINE = 2_147_483_647
KINDS = ("comment", "important", "question")


@dataclass(frozen=True)
class Annotation:
    annotation_id: str
    start_line: int
    end_line: int
    kind: str
    body: str


@dataclass(frozen=True)
class Note:
    title: str
    source_id: str
    source_label: str
    source: SourceSlice
    annotations: tuple[Annotation, ...]
    anchors: tuple[ResolvedAnchor, ...]


@dataclass(frozen=True)
class MeasuredUnit:
    annotation: Annotation
    source_lines: tuple[str, ...]
    annotation_lines: tuple[str, ...]

    @property
    def height(self) -> int:
        return max(len(self.source_lines), len(self.annotation_lines))


def _normalize(data: dict[str, object]) -> Note:
    root = object_value(data, "input")
    check_keys(root, "input", required={"title", "source", "annotations"}, allowed={"title", "source", "annotations"})
    title = string_value(root["title"], "title", single_line=True, allow_tabs=False)
    raw_source = object_value(root["source"], "source")
    check_keys(raw_source, "source", required={"id", "label", "first_line", "lines"}, allowed={"id", "label", "first_line", "lines"})
    source_id = slug_value(raw_source["id"], "source.id", max_length=64)
    source_label = string_value(raw_source["label"], "source.label", single_line=True, allow_tabs=False)
    first_line = int_value(raw_source["first_line"], "source.first_line", minimum=1, maximum=MAX_LINE)
    raw_lines = array_value(raw_source["lines"], "source.lines")
    if not raw_lines:
        raise InputError("source.lines must not be empty")
    lines = tuple(
        string_value(value, f"source.lines[{index}]", allow_empty=True, single_line=True)
        for index, value in enumerate(raw_lines)
    )
    if first_line + len(lines) - 1 > MAX_LINE:
        raise InputError("source line range exceeds the supported maximum")
    source = SourceSlice(first_line, lines)

    raw_annotations = array_value(root["annotations"], "annotations")
    if not raw_annotations:
        raise InputError("annotations must not be empty")
    annotations: list[Annotation] = []
    anchors: list[SourceAnchor] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_annotations):
        path = f"annotations[{index}]"
        record = object_value(value, path)
        required = {"id", "start_line", "end_line", "kind", "body"}
        check_keys(record, path, required=required, allowed=required)
        annotation_id = slug_value(record["id"], f"{path}.id", max_length=64)
        if annotation_id in seen:
            raise InputError(f"duplicate annotation id {annotation_id!r}")
        seen.add(annotation_id)
        start = int_value(record["start_line"], f"{path}.start_line", minimum=1, maximum=MAX_LINE)
        end = int_value(record["end_line"], f"{path}.end_line", minimum=1, maximum=MAX_LINE)
        kind_value = record["kind"]
        if not isinstance(kind_value, str) or kind_value not in KINDS:
            raise InputError(f"{path}.kind must be comment, important, or question")
        body = string_value(record["body"], f"{path}.body")
        annotations.append(Annotation(annotation_id, start, end, kind_value, body))
        anchors.append(SourceAnchor(annotation_id, start, end))
    try:
        resolved = resolve_source_anchors(source, anchors)
    except ValueError as error:
        raise InputError(str(error)) from error
    return Note(title, source_id, source_label, source, tuple(annotations), resolved)


def _wrap(text: str, width: int, *, start: int) -> tuple[str, ...]:
    try:
        return tuple(wrap_preserving_text(text, width, start_column=start))
    except ValueError as error:
        raise FitError(str(error)) from error


def _widths(note: Note, total: int) -> tuple[int, int, int]:
    number_prefix = len(str(note.source.last_line)) + 1
    budget = total - MARKER_WIDTH - 4
    if budget < 2:
        raise FitError("annotated card has no Evidence Pair content width")
    left, right = allocate_pair_widths(budget, 11, 9)
    minimum_left = number_prefix + 4
    minimum_right = 8
    if budget < minimum_left + minimum_right:
        raise FitError(
            f"annotated card needs at least {minimum_left + minimum_right + MARKER_WIDTH + 4} cells"
        )
    left = max(minimum_left, min(left, budget - minimum_right))
    return left, budget - left, number_prefix


def _measure_source(anchor: ResolvedAnchor, left: int, prefix: int, *, start: int) -> tuple[str, ...]:
    body_width = left - prefix
    body_start = start + prefix
    number_width = prefix - 1
    output: list[str] = []
    for number, source_text in anchor.excerpt:
        try:
            wrapped = wrap_preserving_line(source_text, body_width, start_column=body_start)
        except ValueError as error:
            raise FitError(f"source line {number}: {error}") from error
        for visual_index, line in enumerate(wrapped):
            lead = f"{number:>{number_width}} " if visual_index == 0 else " " * prefix
            output.append(lead + line)
    return tuple(output)


def _range(annotation: Annotation) -> str:
    return f"L{annotation.start_line}" if annotation.start_line == annotation.end_line else f"L{annotation.start_line}-L{annotation.end_line}"


def _measure(note: Note, left: int, right: int, prefix: int) -> tuple[MeasuredUnit, ...]:
    right_start = left + MARKER_WIDTH + 3
    output: list[MeasuredUnit] = []
    for annotation, anchor in zip(note.annotations, note.anchors):
        descriptor = f"[{annotation.annotation_id}] {annotation.kind.upper()} {_range(annotation)}"
        output.append(
            MeasuredUnit(
                annotation,
                _measure_source(anchor, left, prefix, start=1),
                _wrap(descriptor, right, start=right_start) + _wrap(annotation.body, right, start=right_start),
            )
        )
    return tuple(output)


def _glyphs(theme: str) -> Mapping[str, str]:
    selected = get_theme(theme)
    ascii_theme = theme == "ascii"
    rich = theme == "unicode-rich"
    return {
        "tl": selected.line(EAST | SOUTH), "tr": selected.line(SOUTH | WEST),
        "bl": selected.line(NORTH | EAST), "br": selected.line(NORTH | WEST),
        "h": selected.line(EAST | WEST), "v": selected.line(NORTH | SOUTH),
        "lj": selected.line(NORTH | EAST | SOUTH), "rj": selected.line(NORTH | SOUTH | WEST),
        "cross": selected.line(NORTH | EAST | SOUTH | WEST),
        "bt": selected.line(NORTH | EAST | WEST),
        "comment": "\\->" if ascii_theme else ("┗━>" if rich else "└─>"),
        "important": "\\-!" if ascii_theme else ("┗━!" if rich else "└─!"),
        "question": "\\-?" if ascii_theme else ("┗━?" if rich else "└─?"),
        "continue": " | " if ascii_theme else (" ┃ " if rich else " │ "),
    }


def _rule(left: int, right: int, glyphs: Mapping[str, str], *, bottom: bool = False) -> str:
    if bottom:
        return glyphs["bl"] + glyphs["h"] * left + glyphs["bt"] + glyphs["h"] * MARKER_WIDTH + glyphs["bt"] + glyphs["h"] * right + glyphs["br"]
    return glyphs["lj"] + glyphs["h"] * left + glyphs["cross"] + glyphs["h"] * MARKER_WIDTH + glyphs["cross"] + glyphs["h"] * right + glyphs["rj"]


def _paint(
    note: Note,
    units: Sequence[MeasuredUnit],
    title_lines: Sequence[str],
    context_lines: Sequence[str],
    left: int,
    right: int,
    options: RenderOptions,
    index: int,
    count: int,
    y: int,
) -> CardDraft:
    glyphs = _glyphs(options.theme)
    lines = [glyphs["tl"] + glyphs["h"] * (options.max_width - 2) + glyphs["tr"]]
    for line in tuple(title_lines) + tuple(context_lines):
        lines.append(glyphs["v"] + pad_cells(line, options.max_width - 2) + glyphs["v"])
    lines.append(_rule(left, right, glyphs))
    lines.append(glyphs["v"] + pad_cells("SOURCE", left) + glyphs["v"] + " " * MARKER_WIDTH + glyphs["v"] + pad_cells("ANNOTATION", right) + glyphs["v"])
    for unit in units:
        lines.append(_rule(left, right, glyphs))
        for row in range(unit.height):
            source = unit.source_lines[row] if row < len(unit.source_lines) else ""
            annotation = unit.annotation_lines[row] if row < len(unit.annotation_lines) else ""
            marker = glyphs[unit.annotation.kind] if row == 0 else glyphs["continue"]
            lines.append(glyphs["v"] + pad_cells(source, left) + glyphs["v"] + marker + glyphs["v"] + pad_cells(annotation, right) + glyphs["v"])
    lines.append(_rule(left, right, glyphs, bottom=True))
    return CardDraft(
        logical_id=f"annotated-{index:03d}",
        text="\n".join(lines),
        width=options.max_width,
        height=len(lines),
        x=0,
        y=y,
        metadata={
            "style": "annotated",
            "source": {"id": note.source_id, "label": note.source_label, "first_line": note.source.first_line, "last_line": note.source.last_line},
            "annotation_ids": [unit.annotation.annotation_id for unit in units],
            "annotations": [
                {"id": unit.annotation.annotation_id, "start_line": unit.annotation.start_line, "end_line": unit.annotation.end_line, "kind": unit.annotation.kind}
                for unit in units
            ],
            "line_number_model": "contiguous-first-line",
            "split_policy": "complete-anchored-excerpt-per-annotation",
            "continuation_index": index + 1,
            "continuation_count": count,
        },
    )


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    left, right, prefix = _widths(note, options.max_width)
    title_lines = _wrap(note.title, options.max_width - 2, start=1)
    context = f"Source: {note.source_label} [{note.source_id}] | original lines {note.source.first_line}-{note.source.last_line}"
    context_lines = _wrap(context, options.max_width - 2, start=1)
    measured = _measure(note, left, right, prefix)
    base_height = 1 + len(title_lines) + len(context_lines) + 1 + 1 + 1
    pages: list[list[MeasuredUnit]] = []
    current: list[MeasuredUnit] = []
    used = base_height
    for unit in measured:
        cost = 1 + unit.height
        if base_height + cost > options.max_height:
            raise FitError(f"annotation {unit.annotation.annotation_id!r} and its complete anchored excerpt cannot fit")
        if current and used + cost > options.max_height:
            pages.append(current)
            current = []
            used = base_height
        current.append(unit)
        used += cost
    pages.append(current)
    if options.single_card and len(pages) != 1:
        raise FitError("annotated note requires multiple cards while --single-card is active")
    cards: list[CardDraft] = []
    y = 0
    for index, page in enumerate(pages):
        card = _paint(note, page, title_lines, context_lines, left, right, options, index, len(pages), y)
        cards.append(card)
        y += card.height + 2
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
