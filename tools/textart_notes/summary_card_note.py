#!/usr/bin/env python3
"""Render fixed-schema summary cards as deterministic text-art."""

from __future__ import annotations

import hashlib
import json
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


RENDERER = "summary-card"
MIN_WIDTH = 24
GUTTER = 2


@dataclass(frozen=True)
class Summary:
    topic: str
    conclusion: str
    evidence: tuple[str, ...]
    application: str
    source: str
    tags: tuple[str, ...]


def _normalize(data: dict[str, object]) -> tuple[Summary, ...]:
    root = object_value(data, "input")
    check_keys(root, "input", required={"summaries"}, allowed={"summaries"})
    records = array_value(root["summaries"], "summaries")
    if not records:
        raise InputError("summaries must not be empty")
    output: list[Summary] = []
    for index, value in enumerate(records):
        path = f"summaries[{index}]"
        record = object_value(value, path)
        required = {"topic", "conclusion", "evidence", "application", "source", "tags"}
        check_keys(record, path, required=required, allowed=required)
        evidence_values = array_value(record["evidence"], f"{path}.evidence")
        if not evidence_values:
            raise InputError(f"{path}.evidence must not be empty")
        evidence = tuple(
            string_value(item, f"{path}.evidence[{item_index}]", strip=True)
            for item_index, item in enumerate(evidence_values)
        )
        tag_values = array_value(record["tags"], f"{path}.tags")
        tags = tuple(
            string_value(
                item,
                f"{path}.tags[{item_index}]",
                single_line=True,
                allow_tabs=False,
                strip=True,
            )
            for item_index, item in enumerate(tag_values)
        )
        if len(tags) != len(set(tags)):
            raise InputError(f"{path}.tags must not contain duplicates")
        output.append(
            Summary(
                topic=string_value(record["topic"], f"{path}.topic", strip=True),
                conclusion=string_value(record["conclusion"], f"{path}.conclusion", strip=True),
                evidence=evidence,
                application=string_value(record["application"], f"{path}.application", strip=True),
                source=string_value(
                    record["source"],
                    f"{path}.source",
                    single_line=True,
                    allow_tabs=False,
                    strip=True,
                ),
                tags=tags,
            )
        )
    return tuple(output)


def _wrapped(value: str, width: int, *, start_column: int, prefix: str = "") -> list[str]:
    prefix_width = text_width(prefix)
    available = width - prefix_width
    if available < 1:
        raise FitError("summary prefix leaves no room for content")
    output: list[str] = []
    first = True
    for hard_line in value.split("\n"):
        rows = wrap_line(hard_line, available, start_column=start_column + prefix_width)
        for row in rows:
            output.append((prefix if first else " " * prefix_width) + row)
            first = False
    return output or [prefix]


def _semantic_id(summary: Summary) -> str:
    stable = json.dumps(
        {
            "topic": summary.topic,
            "conclusion": summary.conclusion,
            "source": summary.source,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "summary-" + hashlib.sha256(stable).hexdigest()[:16]


def _render_one(summary: Summary, options: RenderOptions, logical_id: str, y: int) -> CardDraft:
    width = options.max_width
    content_width = width - 4
    content_column = 2
    if content_width < 1:
        raise FitError("summary frame leaves no content width")
    sections: list[tuple[str, list[str]]] = [
        ("TOPIC", _wrapped(summary.topic, content_width, start_column=content_column)),
        (
            "CORE CONCLUSION",
            _wrapped(summary.conclusion, content_width, start_column=content_column),
        ),
    ]
    evidence_rows: list[str] = []
    for item in summary.evidence:
        evidence_rows.extend(
            _wrapped(item, content_width, start_column=content_column, prefix="- ")
        )
    sections.append(("EVIDENCE", evidence_rows))
    sections.append(
        ("APPLICATION", _wrapped(summary.application, content_width, start_column=content_column))
    )
    tag_text = ", ".join(summary.tags) if summary.tags else "-"
    footer = f"SRC: {summary.source} | TAGS: {tag_text}"
    sections.append(
        ("SOURCE + TAGS", _wrapped(footer, content_width, start_column=content_column))
    )

    lines = [frame_rule(width, options.theme, position="top", label="SUMMARY CARD")]
    for label, rows in sections:
        lines.append(frame_rule(width, options.theme, position="middle", label=label))
        lines.extend(frame_row(width, options.theme, row) for row in rows)
    lines.append(frame_rule(width, options.theme, position="bottom"))
    if len(lines) > options.max_height:
        raise FitError(
            f"summary {logical_id} needs {len(lines)} rows; split the source into core claims"
        )
    return CardDraft(
        logical_id=logical_id,
        text="\n".join(lines),
        width=width,
        height=len(lines),
        x=0,
        y=y,
        metadata={
            "semantic_unit": "source-or-core-claim",
            "source": summary.source,
            "tags": list(summary.tags),
        },
    )


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    summaries = _normalize(data)
    if options.single_card and len(summaries) != 1:
        raise FitError(f"{len(summaries)} complete summary records require multiple cards")
    if options.max_width < MIN_WIDTH:
        raise FitError(f"summary cards require at least {MIN_WIDTH} cells of width")
    cards: list[CardDraft] = []
    counts: dict[str, int] = {}
    next_y = 0
    for summary in summaries:
        base_id = _semantic_id(summary)
        occurrence = counts.get(base_id, 0) + 1
        counts[base_id] = occurrence
        logical_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
        card = _render_one(summary, options, logical_id, next_y)
        cards.append(card)
        next_y += card.height + GUTTER
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
