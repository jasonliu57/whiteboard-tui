#!/usr/bin/env python3
"""Render ordered sentence notes with stable numbering and hanging wraps."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, object_value, string_value
from tools.textart_notes.core.themes import EAST, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.layouts.chain import ChainEntry, measure_chain, paginate_chain


RENDERER = "sentence-note"
GUTTER = 2


@dataclass(frozen=True)
class Sentence:
    text: str
    timestamp: str | None
    speaker: str | None
    tags: tuple[str, ...]


def _compact(value: object, path: str, forbidden: str) -> str:
    result = string_value(value, path, single_line=True, allow_tabs=False)
    if any(character in forbidden for character in result):
        raise InputError(f"{path} contains reserved punctuation")
    return result


def _normalize(data: dict[str, object]) -> tuple[str, tuple[Sentence, ...]]:
    root = object_value(data, "input")
    check_keys(root, "input", required={"title", "sentences"}, allowed={"title", "sentences"})
    title = string_value(root["title"], "title", single_line=True, allow_tabs=False)
    values = array_value(root["sentences"], "sentences")
    if not values:
        raise InputError("sentences must not be empty")
    sentences: list[Sentence] = []
    for index, value in enumerate(values):
        path = f"sentences[{index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"text"},
            allowed={"text", "timestamp", "speaker", "tags"},
        )
        tags: tuple[str, ...] = ()
        if "tags" in record:
            tag_values = array_value(record["tags"], f"{path}.tags")
            if not tag_values:
                raise InputError(f"{path}.tags must not be empty when present")
            parsed: list[str] = []
            for tag_index, tag_value in enumerate(tag_values):
                tag = _compact(tag_value, f"{path}.tags[{tag_index}]", "#[]<>")
                if any(character.isspace() for character in tag):
                    raise InputError(f"{path}.tags[{tag_index}] must be compact")
                if tag in parsed:
                    raise InputError(f"{path}.tags duplicates {tag!r}")
                parsed.append(tag)
            tags = tuple(parsed)
        sentences.append(
            Sentence(
                text=string_value(record["text"], f"{path}.text", single_line=True),
                timestamp=_compact(record["timestamp"], f"{path}.timestamp", "[]") if "timestamp" in record else None,
                speaker=_compact(record["speaker"], f"{path}.speaker", "<>") if "speaker" in record else None,
                tags=tags,
            )
        )
    return title, tuple(sentences)


def _metadata(sentence: Sentence) -> str:
    parts: list[str] = []
    if sentence.timestamp is not None:
        parts.append(f"[{sentence.timestamp}]")
    if sentence.speaker is not None:
        parts.append(f"<{sentence.speaker}>")
    parts.extend(f"#{tag}" for tag in sentence.tags)
    return " ".join(parts)


def _range_line(start: int, end: int, total: int, digits: int) -> str:
    return f"Range {start:0{digits}d}-{end:0{digits}d}/{total:0{digits}d}"


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    title, sentences = _normalize(data)
    total = len(sentences)
    digits = max(3, len(str(total)))
    title_entry = measure_chain((ChainEntry("title", "Title:", title),), options.max_width)[0]
    if text_width(_range_line(total, total, total, digits)) > options.max_width:
        raise FitError("range context cannot fit max_width")
    entries: list[ChainEntry] = []
    for number, sentence in enumerate(sentences, start=1):
        prefix = f"{number:0{digits}d}."
        metadata = _metadata(sentence)
        if metadata:
            prefix += " " + metadata
        entries.append(ChainEntry(f"sentence-{number:0{digits}d}", prefix, sentence.text))
    measured = measure_chain(tuple(entries), options.max_width)
    header_height = title_entry.height + 2
    pages = paginate_chain(measured, options.max_height, reserved_rows=header_height)
    if options.single_card and len(pages) > 1:
        raise FitError(f"sentence chain requires {len(pages)} complete-record cards")
    rule = get_theme(options.theme).line(EAST | WEST) * options.max_width
    cards: list[CardDraft] = []
    y = 0
    offset = 0
    for page_index, page in enumerate(pages):
        start = offset + 1
        end = offset + len(page)
        lines = [*title_entry.lines, _range_line(start, end, total, digits), rule]
        for entry in page:
            lines.extend(entry.lines)
        text = "\n".join(lines)
        cards.append(
            CardDraft(
                f"sentence-{page_index:03d}",
                text,
                options.max_width,
                len(lines),
                0,
                y,
                {
                    "range_start": start,
                    "range_end": end,
                    "sentence_count": total,
                    "number_width": digits,
                    "entry_ids": [entry.key for entry in page],
                },
            )
        )
        offset = end
        y += len(lines) + GUTTER
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
