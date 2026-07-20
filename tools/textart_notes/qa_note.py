#!/usr/bin/env python3
"""Render static expanded or reciprocally paired Q&A text-art cards."""

from __future__ import annotations

import re
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
from tools.textart_notes.core.schema import array_value, check_keys, object_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.schema_blocks import Block, split_blocks


RENDERER = "qa-note"
GUTTER = 2
PAIR_GAP = 4
_PAIR_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_DIFFICULTIES = {"easy", "medium", "hard"}


@dataclass(frozen=True)
class Item:
    pair_id: str
    question: str
    answer: str
    hint: str | None
    tags: tuple[str, ...]
    difficulty: str


@dataclass(frozen=True)
class Deck:
    title: str
    mode: str
    items: tuple[Item, ...]


def _normalize(data: dict[str, object]) -> Deck:
    root = object_value(data, "input")
    check_keys(root, "input", required={"title", "mode", "items"}, allowed={"title", "mode", "items"})
    mode = string_value(root["mode"], "mode", single_line=True, allow_tabs=False)
    if mode not in {"expanded", "separate"}:
        raise InputError("mode must be 'expanded' or 'separate'")
    values = array_value(root["items"], "items")
    if not values:
        raise InputError("items must not be empty")
    items: list[Item] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = f"items[{index}]"
        record = object_value(value, path)
        required = {"pair_id", "question", "answer", "tags", "difficulty"}
        check_keys(record, path, required=required, allowed=required | {"hint"})
        pair_id = string_value(record["pair_id"], f"{path}.pair_id", single_line=True, allow_tabs=False)
        if len(pair_id) > 40 or _PAIR_RE.fullmatch(pair_id) is None:
            raise InputError(f"{path}.pair_id must be a lowercase ASCII slug of at most 40 characters")
        if pair_id in seen:
            raise InputError(f"duplicate pair_id {pair_id!r}")
        seen.add(pair_id)
        tags: list[str] = []
        for tag_index, tag_value in enumerate(array_value(record["tags"], f"{path}.tags")):
            tag = string_value(tag_value, f"{path}.tags[{tag_index}]", single_line=True, allow_tabs=False)
            if tag in tags:
                raise InputError(f"{path}.tags duplicates {tag!r}")
            tags.append(tag)
        difficulty = string_value(record["difficulty"], f"{path}.difficulty", single_line=True, allow_tabs=False)
        if difficulty not in _DIFFICULTIES:
            raise InputError(f"{path}.difficulty must be easy, medium, or hard")
        items.append(
            Item(
                pair_id,
                string_value(record["question"], f"{path}.question"),
                string_value(record["answer"], f"{path}.answer"),
                string_value(record["hint"], f"{path}.hint") if "hint" in record else None,
                tuple(tags),
                difficulty,
            )
        )
    return Deck(string_value(root["title"], "title"), mode, tuple(items))


def _prefixed(prefix: str, text: str, width: int, start_column: int) -> tuple[str, ...]:
    prefix_width = text_width(prefix)
    available = width - prefix_width
    if available < 1:
        raise FitError(f"prefix {prefix!r} leaves no content width")
    output: list[str] = []
    try:
        for hard_line in text.split("\n"):
            wrapped = wrap_line(hard_line, available, start_column=start_column + prefix_width)
            output.extend((prefix if line_index == 0 else " " * prefix_width) + line for line_index, line in enumerate(wrapped))
    except ValueError as error:
        raise FitError(str(error)) from error
    return tuple(output or [prefix])


def _context_rows(deck: Deck, item: Item, inner: int, *, side: str | None = None, part: str | None = None) -> tuple[str, ...]:
    fields = [f"Deck: {deck.title}", f"Pair: {item.pair_id}"]
    if side is not None:
        fields.append(f"Side: {side}")
    fields.append(f"Difficulty: {item.difficulty}")
    fields.append("Tags: " + (", ".join(item.tags) if item.tags else "-"))
    if part is not None:
        fields.append(f"Part: {part}")
    output: list[str] = []
    for field in fields:
        output.extend(_prefixed("", field, inner, 2))
    return tuple(output)


def _expanded_block(deck: Deck, item: Item, options: RenderOptions) -> Block:
    inner = options.max_width - 4
    content: list[str] = []
    content.extend(_context_rows(deck, item, inner))
    content.extend(_prefixed("Q: ", item.question, inner, 2))
    if item.hint is not None:
        content.extend(_prefixed("Hint: ", item.hint, inner, 2))
    content.extend(_prefixed("A: ", item.answer, inner, 2))
    lines = [frame_rule(options.max_width, options.theme, position="middle", label="PAIR")]
    lines.extend(frame_row(options.max_width, options.theme, line) for line in content)
    return Block(item.pair_id, tuple(lines))


def _expanded(deck: Deck, options: RenderOptions) -> tuple[CardDraft, ...]:
    inner = options.max_width - 4
    header_text = _prefixed("Deck: ", deck.title, inner, 2)
    header = [frame_rule(options.max_width, options.theme, position="top", label="QA")]
    header.extend(frame_row(options.max_width, options.theme, line) for line in header_text)
    header.append(frame_row(options.max_width, options.theme, "Mode: expanded"))
    blocks = [_expanded_block(deck, item, options) for item in deck.items]
    pages = split_blocks(blocks, options.max_height, reserved_rows=len(header) + 1)
    if options.single_card and len(pages) > 1:
        raise FitError(f"expanded deck requires {len(pages)} complete-item cards")
    cards: list[CardDraft] = []
    y = 0
    for page_index, page in enumerate(pages):
        lines = list(header)
        for block in page:
            lines.extend(block.lines)
        lines.append(frame_rule(options.max_width, options.theme, position="bottom"))
        pair_ids = [block.key for block in page]
        text = "\n".join(lines)
        cards.append(
            CardDraft(
                f"qa-expanded-{pair_ids[0]}",
                text,
                options.max_width,
                len(lines),
                0,
                y,
                {
                    "mode": "expanded",
                    "pair_ids": pair_ids,
                    "page_index": page_index,
                    "page_count": len(pages),
                    "interactive_reveal": False,
                },
            )
        )
        y += len(lines) + GUTTER
    return tuple(cards)


def _side_blocks(prefix: str, text: str, options: RenderOptions) -> list[Block]:
    inner = options.max_width - 4
    blocks: list[Block] = []
    for index, hard_line in enumerate(text.split("\n")):
        rows = _prefixed(prefix, hard_line, inner, 2)
        lines = [frame_rule(options.max_width, options.theme, position="middle", label="CONTENT")]
        lines.extend(frame_row(options.max_width, options.theme, row) for row in rows)
        blocks.append(Block(f"line-{index:03d}", tuple(lines)))
    return blocks


def _plan_side(deck: Deck, item: Item, side: str, options: RenderOptions) -> tuple[list[list[Block]], int]:
    inner = options.max_width - 4
    static_context = _context_rows(deck, item, inner, side=side, part="1/1")
    reserved = 1 + len(static_context) + 1
    if side == "question":
        blocks = _side_blocks("Q: ", item.question, options)
        if item.hint is not None:
            blocks.extend(_side_blocks("Hint: ", item.hint, options))
    else:
        blocks = _side_blocks("A: ", item.answer, options)
    return split_blocks(blocks, options.max_height, reserved_rows=reserved), reserved


def _paint_side(
    deck: Deck,
    item: Item,
    side: str,
    pages: list[list[Block]],
    options: RenderOptions,
    ids: Sequence[str],
    counterpart_ids: Sequence[str],
    pair_order: int,
    card_order_start: int,
    x: int,
    y: int,
) -> tuple[list[CardDraft], int]:
    inner = options.max_width - 4
    cards: list[CardDraft] = []
    next_y = y
    for part_index, page in enumerate(pages):
        lines = [frame_rule(options.max_width, options.theme, position="top", label="QA")]
        context = _context_rows(deck, item, inner, side=side, part=f"{part_index + 1}/{len(pages)}")
        lines.extend(frame_row(options.max_width, options.theme, row) for row in context)
        for block in page:
            lines.extend(block.lines)
        lines.append(frame_rule(options.max_width, options.theme, position="bottom"))
        text = "\n".join(lines)
        cards.append(
            CardDraft(
                ids[part_index],
                text,
                options.max_width,
                len(lines),
                x,
                next_y,
                {
                    "mode": "separate",
                    "pair_id": item.pair_id,
                    "side": side,
                    "counterpart_side": "answer" if side == "question" else "question",
                    "part_index": part_index,
                    "part_count": len(pages),
                    "counterpart_ids": list(counterpart_ids),
                    "pair_order": pair_order,
                    "card_order": card_order_start + part_index,
                    "tags": list(item.tags),
                    "difficulty": item.difficulty,
                    "interactive_reveal": False,
                },
            )
        )
        next_y += len(lines) + GUTTER
    return cards, next_y


def _validate_pairs(cards: Sequence[CardDraft]) -> None:
    by_id = {card.logical_id: card for card in cards}
    for order, card in enumerate(cards):
        metadata = card.metadata
        if metadata.get("card_order") != order:
            raise InputError("separate card_order must equal manifest order")
        counterparts = metadata.get("counterpart_ids")
        if not isinstance(counterparts, list) or not counterparts:
            raise InputError("separate card requires counterpart IDs")
        for counterpart_id in counterparts:
            counterpart = by_id.get(counterpart_id)
            if counterpart is None:
                raise InputError("separate counterpart ID does not exist")
            if counterpart.metadata.get("pair_id") != metadata.get("pair_id"):
                raise InputError("separate counterpart belongs to another pair")
            if card.logical_id not in counterpart.metadata.get("counterpart_ids", []):
                raise InputError("separate counterpart metadata is not reciprocal")


def _separate(deck: Deck, options: RenderOptions) -> tuple[CardDraft, ...]:
    if options.single_card:
        raise FitError("--single-card is incompatible with separate Q/A mode")
    cards: list[CardDraft] = []
    base_y = 0
    card_order = 0
    for pair_order, item in enumerate(deck.items):
        question_pages, _ = _plan_side(deck, item, "question", options)
        answer_pages, _ = _plan_side(deck, item, "answer", options)
        question_ids = [f"qa-{item.pair_id}-q-{index:03d}" for index in range(len(question_pages))]
        answer_ids = [f"qa-{item.pair_id}-a-{index:03d}" for index in range(len(answer_pages))]
        questions, question_end = _paint_side(
            deck, item, "question", question_pages, options, question_ids, answer_ids,
            pair_order, card_order, 0, base_y,
        )
        card_order += len(questions)
        answers, answer_end = _paint_side(
            deck, item, "answer", answer_pages, options, answer_ids, question_ids,
            pair_order, card_order, options.max_width + PAIR_GAP, base_y,
        )
        card_order += len(answers)
        cards.extend(questions)
        cards.extend(answers)
        base_y = max(question_end, answer_end) + PAIR_GAP
    _validate_pairs(cards)
    return tuple(cards)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    if options.max_width < 16:
        raise FitError("Q&A cards require at least 16 cells of width")
    deck = _normalize(data)
    try:
        cards = _expanded(deck, options) if deck.mode == "expanded" else _separate(deck, options)
    except ValueError as error:
        raise FitError(str(error)) from error
    result = RenderResult(RENDERER, options.theme, cards)
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
