#!/usr/bin/env python3
"""Render hierarchical outline notes with semantic subtree splitting."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.boxes import frame_row, frame_rule
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, bool_value, check_keys, int_value, object_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line


RENDERER = "outline-note"
MIN_WIDTH = 12
MAX_INPUT_DEPTH = 64
MAX_INPUT_NODES = 10_000
GUTTER = 2
STATUSES = {"todo", "doing", "done", "blocked"}
STATUS_MARKERS = {"todo": "[ ] ", "doing": "[>] ", "done": "[x] ", "blocked": "[!] "}


@dataclass(frozen=True)
class Node:
    path: tuple[int, ...]
    text: str
    status: str | None
    children: tuple["Node", ...]


@dataclass(frozen=True)
class Outline:
    title: str
    children: tuple[Node, ...]
    numbering: bool
    depth_limit: int


@dataclass(frozen=True)
class Promotion:
    node: Node
    reason: str


@dataclass(frozen=True)
class PlannedCard:
    path: tuple[int, ...]
    reason: str
    page: int
    pages: int
    lines: tuple[str, ...]


def _normalize(data: dict[str, object]) -> Outline:
    root = object_value(data, "input")
    allowed = {"title", "children", "numbering", "depth_limit"}
    check_keys(root, "input", required={"title", "children"}, allowed=allowed)
    count = 0

    def parse(value: object, path: tuple[int, ...], location: str, depth: int) -> Node:
        nonlocal count
        if depth > MAX_INPUT_DEPTH:
            raise InputError(f"outline input exceeds safety depth {MAX_INPUT_DEPTH}")
        count += 1
        if count > MAX_INPUT_NODES:
            raise InputError(f"outline input exceeds safety node count {MAX_INPUT_NODES}")
        raw = object_value(value, location)
        check_keys(raw, location, required={"text"}, allowed={"text", "status", "children"})
        status = raw.get("status")
        if status is not None and (not isinstance(status, str) or status not in STATUSES):
            raise InputError(f"{location}.status must be one of: {', '.join(sorted(STATUSES))}")
        children = tuple(
            parse(child, path + (index,), f"{location}.children[{index - 1}]", depth + 1)
            for index, child in enumerate(
                array_value(raw.get("children", []), f"{location}.children"), start=1
            )
        )
        return Node(
            path,
            string_value(raw["text"], f"{location}.text", single_line=True, strip=True),
            str(status) if status is not None else None,
            children,
        )

    child_values = array_value(root["children"], "children")
    if not child_values:
        raise InputError("children must not be empty")
    children = tuple(
        parse(value, (index,), f"children[{index - 1}]", 1)
        for index, value in enumerate(child_values, start=1)
    )
    numbering = bool_value(root.get("numbering", False), "numbering")
    depth_limit = int_value(root.get("depth_limit", 5), "depth_limit", minimum=1, maximum=8)
    return Outline(
        string_value(root["title"], "title", single_line=True, strip=True),
        children,
        numbering,
        depth_limit,
    )


def _tree_tokens(theme: str) -> tuple[str, str]:
    if theme == "ascii":
        return "+- ", ": "
    if theme == "unicode-rich":
        return "┣━ ", "… "
    return "├─ ", "… "


def _path_label(path: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in path)


def _wrapped(prefix: str, text: str, width: int) -> list[str]:
    prefix_width = text_width(prefix)
    available = width - prefix_width
    if available < 1:
        raise FitError(f"outline prefix {prefix!r} leaves no room for text")
    rows = wrap_line(text, available, start_column=2 + prefix_width)
    return [prefix + rows[0]] + [" " * prefix_width + row for row in rows[1:]]


def _node_rows(
    node: Node,
    local_depth: int,
    outline: Outline,
    options: RenderOptions,
) -> tuple[list[str], list[Promotion]]:
    branch, reference = _tree_tokens(options.theme)
    indentation = "   " * max(0, local_depth - 1)
    numbering = f"{_path_label(node.path)} " if outline.numbering else ""
    status = STATUS_MARKERS.get(node.status or "", "")
    rows = _wrapped(indentation + branch + numbering + status, node.text, options.max_width - 4)
    promotions: list[Promotion] = []
    if not node.children:
        return rows, promotions
    if local_depth >= outline.depth_limit:
        for child in node.children:
            label = f"subtree {_path_label(child.path)}"
            rows.extend(_wrapped(indentation + "   " + reference, label, options.max_width - 4))
            promotions.append(Promotion(child, "depth"))
        return rows, promotions
    for child in node.children:
        child_rows, child_promotions = _node_rows(
            child, local_depth + 1, outline, options
        )
        rows.extend(child_rows)
        promotions.extend(child_promotions)
    return rows, promotions


def _reference_rows(node: Node, options: RenderOptions) -> list[str]:
    _, reference = _tree_tokens(options.theme)
    return _wrapped(reference, f"subtree {_path_label(node.path)}", options.max_width - 4)


def _header(outline: Outline, options: RenderOptions) -> list[str]:
    width = options.max_width
    content_width = width - 4
    title_rows = wrap_line(outline.title, content_width, start_column=2)
    return [frame_rule(width, options.theme, position="top", label="OUTLINE")] + [
        frame_row(width, options.theme, row) for row in title_rows
    ] + [frame_rule(width, options.theme, position="middle")]


def _plan_section(
    outline: Outline,
    root: Node | None,
    reason: str,
    options: RenderOptions,
) -> tuple[list[PlannedCard], list[Promotion]]:
    header = _header(outline, options)
    section_path = root.path if root is not None else ()
    context: list[str] = []
    if root is not None:
        marker = STATUS_MARKERS.get(root.status or "", "")
        number = f"{_path_label(root.path)} " if outline.numbering else ""
        context = _wrapped("* " + number + marker, root.text, options.max_width - 4)
    available = options.max_height - len(header) - len(context) - 1
    if available < 0:
        raise FitError(f"outline section {_path_label(section_path) or 'root'} header cannot fit")
    items = outline.children if root is None else root.children
    local_depth = 1 if root is None else 2
    candidates: list[tuple[list[str], list[Promotion]]] = []
    for item in items:
        if local_depth > outline.depth_limit:
            rendered = _reference_rows(item, options)
            promotions = [Promotion(item, "depth")]
        else:
            rendered, promotions = _node_rows(item, local_depth, outline, options)
        if len(rendered) > available:
            if not item.children:
                raise FitError(
                    f"indivisible leaf {_path_label(item.path)} cannot fit without cropping"
                )
            rendered = _reference_rows(item, options)
            promotions = [Promotion(item, "height")]
        if len(rendered) > available:
            raise FitError(f"subtree reference {_path_label(item.path)} cannot fit")
        candidates.append((rendered, promotions))
    if not items and len(context) + len(header) + 1 > options.max_height:
        raise FitError(f"indivisible section {_path_label(section_path)} cannot fit")

    blocks: list[list[str]] = []
    current: list[str] = []
    promotions_in_order: list[Promotion] = []
    for rendered, promotions in candidates:
        if current and len(current) + len(rendered) > available:
            blocks.append(current)
            current = []
        current.extend(rendered)
        promotions_in_order.extend(promotions)
    if current or not candidates:
        blocks.append(current)
    planned: list[PlannedCard] = []
    for page, block in enumerate(blocks, start=1):
        lines = list(header)
        lines.extend(frame_row(options.max_width, options.theme, row) for row in context + block)
        lines.append(frame_rule(options.max_width, options.theme, position="bottom"))
        planned.append(
            PlannedCard(section_path, reason, page, len(blocks), tuple(lines))
        )
    unique: dict[tuple[int, ...], Promotion] = {}
    for promotion in promotions_in_order:
        unique.setdefault(promotion.node.path, promotion)
    return planned, list(unique.values())


def _plan(outline: Outline, options: RenderOptions) -> list[PlannedCard]:
    planned: list[PlannedCard] = []
    queue: list[tuple[Node | None, str]] = [(None, "root")]
    visited: set[tuple[int, ...]] = set()
    while queue:
        root, reason = queue.pop(0)
        path = root.path if root is not None else ()
        if path in visited:
            continue
        visited.add(path)
        cards, promotions = _plan_section(outline, root, reason, options)
        planned.extend(cards)
        queue.extend((promotion.node, promotion.reason) for promotion in promotions)
    return planned


def _card_id(path: tuple[int, ...], page: int) -> str:
    section = "root" if not path else "-".join(str(part) for part in path)
    return f"outline-{section}-{page:03d}"


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    if options.max_width < MIN_WIDTH:
        raise FitError(f"outline cards require at least {MIN_WIDTH} cells of width")
    outline = _normalize(data)
    planned = _plan(outline, options)
    if options.single_card and len(planned) != 1:
        raise FitError(f"outline requires {len(planned)} semantic cards")
    cards: list[CardDraft] = []
    next_y = 0
    for item in planned:
        card = CardDraft(
            _card_id(item.path, item.page),
            "\n".join(item.lines),
            options.max_width,
            len(item.lines),
            min(24, len(item.path) * 4),
            next_y,
            {
                "section_path": list(item.path),
                "split_reason": item.reason,
                "page": item.page,
                "pages": item.pages,
                "numbering": outline.numbering,
                "depth_limit": outline.depth_limit,
            },
        )
        cards.append(card)
        next_y += card.height + GUTTER
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
