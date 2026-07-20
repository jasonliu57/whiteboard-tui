#!/usr/bin/env python3
"""Render Fishbone/Ishikawa notes as deterministic text-art cards."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.canvas import Canvas
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import (
    CardDraft,
    FitError,
    InputError,
    RenderOptions,
    RenderResult,
)
from tools.textart_notes.core.schema import (
    array_value,
    check_keys,
    object_value,
    string_value,
)
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_clusters
from tools.textart_notes.layouts.spine import SpineItem, SpineLayout, place_spine


RENDERER = "fishbone-note"
MAX_BRANCHES = 999
MAX_CAUSES_PER_BRANCH = 64
MAX_TEXT_CELLS = 4096
MAX_TOTAL_TEXT_CELLS = 100_000
CARD_GUTTER = 4
HEADER_ROWS = 2


@dataclass(frozen=True)
class LayoutVariant:
    name: str
    indent: int
    core_cap: int
    effect_padding: int
    separate_slash_row: bool


VARIANTS: Mapping[str, LayoutVariant] = {
    "classic": LayoutVariant("classic", 4, 24, 1, True),
    "boxed": LayoutVariant("boxed", 5, 20, 2, True),
    "compact": LayoutVariant("compact", 2, 36, 0, False),
}


@dataclass(frozen=True)
class Branch:
    index: int
    name: str
    side: str
    causes: tuple[str, ...]
    source_field: str

    @property
    def key(self) -> str:
        return f"branch-{self.index:03d}"


@dataclass(frozen=True)
class Fishbone:
    effect: str
    variant: str
    branches: tuple[Branch, ...]


@dataclass(frozen=True)
class BranchCell:
    branch: Branch
    top_lines: tuple[str, ...]
    bottom_lines: tuple[str, ...]
    width: int
    height: int

    def layout_item(self) -> SpineItem:
        return SpineItem(self.branch.key, self.branch.side, self.width, self.height)


@dataclass(frozen=True)
class EffectBox:
    lines: tuple[str, ...]
    width: int
    height: int
    entry_row: int


@dataclass(frozen=True)
class PagePlan:
    start: int
    end: int
    cells: tuple[BranchCell, ...]
    effect: EffectBox
    layout: SpineLayout


@dataclass(frozen=True)
class FishboneGlyphs:
    horizontal: str
    top_slant: str
    bottom_slant: str
    top_joint: str
    bottom_joint: str
    arrow: str


def _glyphs(theme_name: str) -> FishboneGlyphs:
    theme = get_theme(theme_name)
    return FishboneGlyphs(
        horizontal=theme.line(EAST | WEST),
        top_slant="\\" if theme_name == "ascii" else "╲",
        bottom_slant="/" if theme_name == "ascii" else "╱",
        top_joint=theme.line(NORTH | EAST | WEST),
        bottom_joint=theme.line(EAST | SOUTH | WEST),
        arrow="->" if theme_name == "ascii" else theme.line(EAST | WEST) + theme.arrow_right,
    )


def _text(value: object, path: str) -> tuple[str, int]:
    result = string_value(value, path, strip=True)
    try:
        cells = sum(text_width(line) for line in result.split("\n"))
    except ValueError as error:
        raise InputError(f"{path} has invalid terminal-cell text: {error}") from error
    if cells > MAX_TEXT_CELLS:
        raise InputError(f"{path} exceeds {MAX_TEXT_CELLS} terminal cells")
    return result, cells


def _normalize(data: dict[str, object]) -> Fishbone:
    root = object_value(data, "input")
    check_keys(
        root,
        "input",
        required={"effect", "branches"},
        allowed={"effect", "branches", "layout"},
    )
    effect, total_cells = _text(root["effect"], "effect")
    variant = string_value(
        root.get("layout", "classic"),
        "layout",
        single_line=True,
        allow_tabs=False,
        strip=True,
    )
    if variant not in VARIANTS:
        raise InputError("layout must be classic, boxed, or compact")

    raw_branches = array_value(root["branches"], "branches")
    if not 1 <= len(raw_branches) <= MAX_BRANCHES:
        raise InputError(f"branches must contain 1..{MAX_BRANCHES} items")

    branches: list[Branch] = []
    auto_index = 0
    for index, value in enumerate(raw_branches):
        path = f"branches[{index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"name"},
            allowed={"name", "side", "nodes", "causes"},
        )
        if "nodes" in record and "causes" in record:
            raise InputError(f"{path} cannot contain both nodes and causes")
        name, cells = _text(record["name"], f"{path}.name")
        total_cells += cells
        if total_cells > MAX_TOTAL_TEXT_CELLS:
            raise InputError(
                f"fishbone input exceeds {MAX_TOTAL_TEXT_CELLS} terminal cells"
            )

        side_value = string_value(
            record.get("side", "auto"),
            f"{path}.side",
            single_line=True,
            allow_tabs=False,
            strip=True,
        )
        if side_value not in {"top", "bottom", "auto"}:
            raise InputError(f"{path}.side must be top, bottom, or auto")
        if side_value == "auto":
            side = "top" if auto_index % 2 == 0 else "bottom"
            auto_index += 1
        else:
            side = side_value

        source_field = "causes" if "causes" in record else "nodes"
        raw_causes = array_value(record.get(source_field, []), f"{path}.{source_field}")
        if len(raw_causes) > MAX_CAUSES_PER_BRANCH:
            raise InputError(
                f"{path}.{source_field} may contain at most "
                f"{MAX_CAUSES_PER_BRANCH} causes"
            )
        causes: list[str] = []
        for cause_index, cause_value in enumerate(raw_causes):
            cause, cells = _text(
                cause_value, f"{path}.{source_field}[{cause_index}]"
            )
            total_cells += cells
            if total_cells > MAX_TOTAL_TEXT_CELLS:
                raise InputError(
                    f"fishbone input exceeds {MAX_TOTAL_TEXT_CELLS} terminal cells"
                )
            causes.append(cause)
        branches.append(
            Branch(index, name, side, tuple(causes), source_field)
        )
    return Fishbone(effect, variant, tuple(branches))


def _wrap(text: str, width: int, *, start_column: int) -> tuple[str, ...]:
    if width < 1:
        raise FitError("text has no horizontal room")
    rows: list[str] = []
    try:
        for hard_line in text.split("\n"):
            rows.extend(wrap_clusters(hard_line, width, start_column=start_column))
    except ValueError as error:
        raise FitError(str(error)) from error
    return tuple(rows)


def _label_specs(
    branch: Branch, variant: LayoutVariant
) -> tuple[tuple[str, str, str], ...]:
    if variant.name == "compact":
        causes = " | ".join(branch.causes) if branch.causes else "-"
        return ((causes, "", ""), (branch.name, "{", "}"))
    if variant.name == "boxed":
        nodes = tuple((cause, "[ ", " ]") for cause in branch.causes)
        return nodes + ((branch.name, "[[ ", " ]]"),)
    nodes = tuple((cause, "", "") for cause in branch.causes)
    return nodes + ((branch.name, "(", ")"),)


def _build_branch_cell(
    branch: Branch,
    variant: LayoutVariant,
    glyphs: FishboneGlyphs,
    *,
    segment_start: int,
    branch_budget: int,
    theme: str,
) -> BranchCell:
    specs = _label_specs(branch, variant)
    count = len(specs)
    max_decoration = max(text_width(prefix + suffix) for _, prefix, suffix in specs)
    structural = (count - 1) * variant.indent + max_decoration + 2
    core_width = min(variant.core_cap, branch_budget - structural)
    if core_width < 1:
        raise FitError(f"branch {branch.index + 1} is indivisibly too wide")

    measured: list[tuple[int, tuple[str, ...], int]] = []
    connector_x = 0
    for depth, (text, prefix, suffix) in enumerate(specs):
        label_x = depth * variant.indent
        core_start = segment_start + label_x + text_width(prefix)
        core_lines = _wrap(text, core_width, start_column=core_start)
        lines = tuple(prefix + line + suffix for line in core_lines)
        max_line_width = max(
            text_width(line, start=segment_start + label_x) for line in lines
        )
        slash_clearance = (count - depth - 1) * variant.indent
        connector_x = max(
            connector_x,
            label_x + max_line_width + 1 + slash_clearance,
        )
        measured.append((label_x, lines, depth))

    cell_width = connector_x + 1
    if cell_width > branch_budget:
        raise FitError(f"branch {branch.index + 1} is indivisibly too wide")
    cell_height = sum(
        len(lines) + (1 if variant.separate_slash_row else 0)
        for _, lines, _ in measured
    )

    top = Canvas(cell_width, cell_height, theme)
    bottom = Canvas(cell_width, cell_height, theme)
    row = 0
    label_rows: list[tuple[int, int, str]] = []
    slash_rows: list[tuple[int, int]] = []
    for label_x, lines, depth in measured:
        for line in lines:
            if line:
                top.put_text(label_x, row, line)
            label_rows.append((row, label_x, line))
            row += 1
        slash_row = row if variant.separate_slash_row else row - 1
        slash_x = connector_x - (len(measured) - depth - 1) * variant.indent
        top.put_text(slash_x, slash_row, glyphs.top_slant)
        slash_rows.append((slash_row, slash_x))
        if variant.separate_slash_row:
            row += 1

    for source_row, label_x, line in label_rows:
        if line:
            bottom.put_text(label_x, cell_height - 1 - source_row, line)
    for source_row, slash_x in slash_rows:
        bottom.put_text(
            slash_x, cell_height - 1 - source_row, glyphs.bottom_slant
        )
    return BranchCell(
        branch,
        tuple(top.to_lines(trim_right=False)),
        tuple(bottom.to_lines(trim_right=False)),
        cell_width,
        cell_height,
    )


def _effect_box_width(options: RenderOptions, variant: LayoutVariant) -> int:
    minimum = 2 + 2 * variant.effect_padding + 2
    desired = max(minimum, options.max_width // 3)
    return min(34, desired)


def _build_effect_box(
    effect: str,
    variant: LayoutVariant,
    *,
    theme: str,
    width: int,
    physical_x: int,
) -> EffectBox:
    inner_width = width - 2 - 2 * variant.effect_padding
    if inner_width < 1:
        raise FitError("effect box is indivisibly too narrow")
    text_x = physical_x + 1 + variant.effect_padding
    text_lines = _wrap(effect, inner_width, start_column=text_x)
    height = len(text_lines) + 2
    canvas = Canvas(width, height, theme)
    canvas.draw_box(0, 0, width, height)
    for row, line in enumerate(text_lines, start=1):
        if line:
            canvas.put_text(1 + variant.effect_padding, row, line)
    return EffectBox(
        tuple(canvas.to_lines(trim_right=False)), width, height, height // 2
    )


def _page_layout(
    cells: Sequence[BranchCell],
    effect: EffectBox,
    arrow_width: int,
) -> SpineLayout:
    return place_spine(
        [cell.layout_item() for cell in cells],
        arrow_width=arrow_width,
        effect_width=effect.width,
        effect_height=effect.height,
        effect_entry_row=effect.entry_row,
    )


def _plan_pages(
    note: Fishbone,
    options: RenderOptions,
    variant: LayoutVariant,
    glyphs: FishboneGlyphs,
) -> tuple[PagePlan, ...]:
    count = len(note.branches)
    worst_header = f"FISHBONE {count}/{count} B{count}-{count}/{count}"
    if text_width(worst_header) > options.max_width:
        raise FitError("continuation header is indivisibly too wide")

    effect_width = _effect_box_width(options, variant)
    arrow_width = text_width(glyphs.arrow)
    branch_budget = options.max_width - effect_width - arrow_width
    if branch_budget < 4:
        raise FitError("card is too narrow for one branch, arrow, and repeated effect")

    pages: list[PagePlan] = []
    start = 0
    while start < count:
        cells: list[BranchCell] = []
        span = 0
        accepted: PagePlan | None = None
        for end in range(start, count):
            try:
                cell = _build_branch_cell(
                    note.branches[end],
                    variant,
                    glyphs,
                    segment_start=span,
                    branch_budget=branch_budget - span,
                    theme=options.theme,
                )
            except FitError:
                if not cells:
                    raise
                break
            candidate_cells = tuple(cells + [cell])
            candidate_span = span + cell.width
            effect = _build_effect_box(
                note.effect,
                variant,
                theme=options.theme,
                width=effect_width,
                physical_x=candidate_span + arrow_width,
            )
            layout = _page_layout(candidate_cells, effect, arrow_width)
            if (
                layout.width > options.max_width
                or HEADER_ROWS + layout.height > options.max_height
            ):
                if not cells:
                    reason = "too wide" if layout.width > options.max_width else "too high"
                    raise FitError(
                        f"branch {note.branches[end].index + 1} is indivisibly {reason}"
                    )
                break
            cells.append(cell)
            span = candidate_span
            accepted = PagePlan(start, end + 1, tuple(cells), effect, layout)
        if accepted is None:
            raise FitError(f"branch {note.branches[start].index + 1} cannot fit")
        pages.append(accepted)
        start = accepted.end

    if options.single_card and len(pages) > 1:
        raise FitError("--single-card forbids the required branch-boundary split")
    return tuple(pages)


def _paint_page(
    plan: PagePlan,
    *,
    page_index: int,
    page_count: int,
    branch_total: int,
    theme: str,
    glyphs: FishboneGlyphs,
) -> tuple[str, tuple[dict[str, object], ...]]:
    header = (
        f"FISHBONE {page_index + 1}/{page_count} "
        f"B{plan.start + 1}-{plan.end}/{branch_total}"
    )
    width = max(plan.layout.width, text_width(header))
    height = HEADER_ROWS + plan.layout.height
    canvas = Canvas(width, height, theme)
    canvas.put_text(0, 0, header)

    by_key = {cell.branch.key: cell for cell in plan.cells}
    ownership: list[dict[str, object]] = []
    for placement in plan.layout.placements:
        cell = by_key[placement.key]
        lines = cell.top_lines if placement.side == "top" else cell.bottom_lines
        for row, line in enumerate(lines):
            if line.strip(" "):
                canvas.put_text(placement.x, HEADER_ROWS + placement.y + row, line)
        spine_y = HEADER_ROWS + plan.layout.spine_y
        if placement.width > 1:
            canvas.put_text(
                placement.x,
                spine_y,
                glyphs.horizontal * (placement.width - 1),
            )
        joint = glyphs.top_joint if placement.side == "top" else glyphs.bottom_joint
        canvas.put_text(placement.joint_x, spine_y, joint)
        ownership.append(
            {
                "branch_index": cell.branch.index,
                "name": cell.branch.name,
                "side": cell.branch.side,
                "source_field": cell.branch.source_field,
                "cause_count": len(cell.branch.causes),
                "segment_x": placement.x,
                "segment_width": placement.width,
                "joint_x": placement.joint_x,
            }
        )

    spine_y = HEADER_ROWS + plan.layout.spine_y
    canvas.put_text(plan.layout.spine_width, spine_y, glyphs.arrow)
    for row, line in enumerate(plan.effect.lines):
        canvas.put_text(
            plan.layout.effect_x,
            HEADER_ROWS + plan.layout.effect_y + row,
            line,
        )
    return canvas.to_text(), tuple(ownership)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    note = _normalize(data)
    variant = VARIANTS[note.variant]
    glyphs = _glyphs(options.theme)
    plans = _plan_pages(note, options, variant, glyphs)

    cards: list[CardDraft] = []
    next_x = 0
    for page_index, plan in enumerate(plans):
        logical_id = f"fishbone-{page_index:03d}"
        text, ownership = _paint_page(
            plan,
            page_index=page_index,
            page_count=len(plans),
            branch_total=len(note.branches),
            theme=options.theme,
            glyphs=glyphs,
        )
        lines = text.split("\n")
        width = max(text_width(line) for line in lines)
        previous_id = f"fishbone-{page_index - 1:03d}" if page_index else None
        next_id = (
            f"fishbone-{page_index + 1:03d}"
            if page_index + 1 < len(plans)
            else None
        )
        card = CardDraft(
            logical_id=logical_id,
            text=text,
            width=width,
            height=len(lines),
            x=next_x,
            y=0,
            metadata={
                "style": "fishbone",
                "engine": "spine",
                "layout": note.variant,
                "effect": note.effect,
                "card_order": page_index,
                "branch_range": {
                    "start_index": plan.start,
                    "end_index_exclusive": plan.end,
                    "total": len(note.branches),
                },
                "continuation": {
                    "part": page_index + 1,
                    "total": len(plans),
                    "previous_card_id": previous_id,
                    "next_card_id": next_id,
                },
                "spine_y": HEADER_ROWS + plan.layout.spine_y,
                "branch_ownership": list(ownership),
            },
        )
        cards.append(card)
        next_x += card.width + CARD_GUTTER

    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
