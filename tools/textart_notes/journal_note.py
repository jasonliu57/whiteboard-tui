#!/usr/bin/env python3
"""Render daily or bounded-week journals as Schema Block text-art cards."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import pad_cells, text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, decimal_value, object_value, slug_value, string_value
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_preserving_text
from tools.textart_notes.layouts.lanes import allocate_lane_widths, lane_positions
from tools.textart_notes.layouts.schema_blocks import Block, place_blocks


RENDERER = "journal-note"
MIN_DAILY_WIDTH = 30
MIN_WEEKLY_WIDTH = 40
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
OFFSET_RE = re.compile(r"([+-])(\d{2}):(\d{2})\Z", re.ASCII)


@dataclass(frozen=True)
class Record:
    record_id: str
    text: str


@dataclass(frozen=True)
class Metric:
    label: str
    value: str
    unit: str | None


@dataclass(frozen=True)
class Entry:
    entry_date: date
    entry_id: str
    events: tuple[Record, ...]
    reflection: str
    next_steps: tuple[Record, ...]
    mood: str | None
    metrics: tuple[Metric, ...]


@dataclass(frozen=True)
class Journal:
    title: str
    timezone: str
    view: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class DayPart:
    entry: Entry
    part_index: int
    part_count: int
    lines: tuple[str, ...]
    event_indices: tuple[int, ...]
    step_indices: tuple[int, ...]


def _text(value: object, path: str, *, allow_empty: bool = False, single_line: bool = False) -> str:
    result = string_value(value, path, allow_empty=allow_empty, single_line=single_line)
    if not allow_empty and not result.strip():
        raise InputError(f"{path} must not be whitespace-only")
    return result


def _date(value: object, path: str) -> date:
    raw = _text(value, path, single_line=True)
    if DATE_RE.fullmatch(raw) is None:
        raise InputError(f"{path} must be an exact ISO date YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as error:
        raise InputError(f"{path} is not a valid calendar date") from error
    if parsed.isoformat() != raw:
        raise InputError(f"{path} must be a normalized ISO date")
    return parsed


def _timezone(value: object) -> str:
    raw = _text(value, "timezone", single_line=True)
    if raw == "UTC":
        return raw
    match = OFFSET_RE.fullmatch(raw)
    if match is None:
        raise InputError("timezone must be UTC or a fixed offset like +08:00")
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise InputError("timezone offset must be between -14:00 and +14:00")
    return raw


def _records(value: object, path: str) -> tuple[Record, ...]:
    values = array_value(value, path)
    if len(values) > 1000:
        raise InputError(f"{path} must contain at most 1000 records")
    output: list[Record] = []
    for index, value in enumerate(values):
        item_path = f"{path}[{index}]"
        record = object_value(value, item_path)
        check_keys(record, item_path, required={"id", "text"}, allowed={"id", "text"})
        output.append(Record(slug_value(record["id"], f"{item_path}.id"), _text(record["text"], f"{item_path}.text")))
    return tuple(output)


def _number(value: object, path: str) -> str:
    number = decimal_value(value, path)
    if number.is_zero():
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if len(rendered) > 1000:
        raise InputError(f"{path} canonical value exceeds 1000 characters")
    return rendered


def _metrics(value: object, path: str) -> tuple[Metric, ...]:
    values = array_value(value, path)
    if len(values) > 100:
        raise InputError(f"{path} must contain at most 100 metrics")
    output: list[Metric] = []
    labels: set[str] = set()
    for index, value in enumerate(values):
        item_path = f"{path}[{index}]"
        record = object_value(value, item_path)
        check_keys(record, item_path, required={"label", "value"}, allowed={"label", "value", "unit"})
        label = _text(record["label"], f"{item_path}.label", single_line=True)
        if label in labels:
            raise InputError(f"duplicate metric label {label!r}")
        labels.add(label)
        raw_value = record["value"]
        rendered = _text(raw_value, f"{item_path}.value", single_line=True) if isinstance(raw_value, str) else _number(raw_value, f"{item_path}.value")
        unit = _text(record["unit"], f"{item_path}.unit", single_line=True) if "unit" in record else None
        output.append(Metric(label, rendered, unit))
    return tuple(output)


def _normalize(data: dict[str, object]) -> Journal:
    root = object_value(data, "input")
    allowed = {"journal_title", "timezone", "view", "week_start", "entries"}
    check_keys(root, "input", required={"journal_title", "timezone", "entries"}, allowed=allowed)
    title = _text(root["journal_title"], "journal_title")
    timezone_value = _timezone(root["timezone"])
    view_value = root.get("view", "daily")
    if not isinstance(view_value, str) or view_value not in {"daily", "weekly"}:
        raise InputError("view must be daily or weekly")
    if "week_start" in root:
        if view_value != "weekly":
            raise InputError("week_start is only valid for weekly view")
        if root["week_start"] != "monday":
            raise InputError("week_start must be monday")
    values = array_value(root["entries"], "entries")
    if not values or len(values) > 3660:
        raise InputError("entries must contain 1..3660 dates")
    entries: list[Entry] = []
    seen_entries: set[str] = set()
    previous: date | None = None
    for index, value in enumerate(values):
        path = f"entries[{index}]"
        record = object_value(value, path)
        required = {"date", "events", "reflection", "next_steps"}
        allowed_entry = required | {"id", "mood", "metrics"}
        check_keys(record, path, required=required, allowed=allowed_entry)
        entry_date = _date(record["date"], f"{path}.date")
        if previous is not None and entry_date <= previous:
            raise InputError("entry dates must be unique and strictly chronological")
        previous = entry_date
        entry_id = slug_value(record["id"], f"{path}.id") if "id" in record else f"date-{entry_date.strftime('%Y%m%d')}"
        if entry_id in seen_entries:
            raise InputError(f"duplicate entry id {entry_id!r}")
        seen_entries.add(entry_id)
        events = _records(record["events"], f"{path}.events")
        steps = _records(record["next_steps"], f"{path}.next_steps")
        ids: set[str] = set()
        for item in events + steps:
            if item.record_id in ids:
                raise InputError(f"{path} has duplicate event/next-step id {item.record_id!r}")
            ids.add(item.record_id)
        reflection = _text(record["reflection"], f"{path}.reflection", allow_empty=True)
        if not events and not reflection.strip() and not steps:
            raise InputError(f"{path} must contain an event, reflection, or next step")
        mood = _text(record["mood"], f"{path}.mood", single_line=True) if "mood" in record else None
        metrics = _metrics(record.get("metrics", []), f"{path}.metrics")
        entries.append(Entry(entry_date, entry_id, events, reflection, steps, mood, metrics))
    return Journal(title, timezone_value, view_value, tuple(entries))


def _glyphs(theme: str) -> Mapping[str, str]:
    selected = get_theme(theme)
    return {
        "tl": selected.line(EAST | SOUTH), "tr": selected.line(SOUTH | WEST),
        "bl": selected.line(NORTH | EAST), "br": selected.line(NORTH | WEST),
        "h": selected.line(EAST | WEST), "v": selected.line(NORTH | SOUTH),
        "lj": selected.line(NORTH | EAST | SOUTH), "rj": selected.line(NORTH | SOUTH | WEST),
        "marker": "o" if theme == "ascii" else ("◆" if theme == "unicode-rich" else "●"),
        "join": "--" if theme == "ascii" else ("━━" if theme == "unicode-rich" else "──"),
    }


def _wrap(text: str, width: int, *, start: int) -> list[str]:
    try:
        return wrap_preserving_text(text, width, start_column=start)
    except ValueError as error:
        raise FitError(str(error)) from error


def _content(content: str, width: int, glyphs: Mapping[str, str]) -> str:
    return glyphs["v"] + " " + pad_cells(content, width - 4) + " " + glyphs["v"]


def _field(label: str, value: str, inner: int, start: int) -> list[str]:
    prefix = f"{label}: "
    available = inner - text_width(prefix)
    if available < 1:
        raise FitError(f"journal block is too narrow for {label}")
    wrapped = _wrap(value, available, start=start + text_width(prefix))
    return [(prefix if index == 0 else " " * text_width(prefix)) + line for index, line in enumerate(wrapped)]


def _record(marker: str, item: Record, inner: int, start: int) -> list[str]:
    prefix = f"{marker} [{item.record_id}] "
    available = inner - text_width(prefix)
    if available < 1:
        raise FitError(f"journal block is too narrow for record {item.record_id!r}")
    wrapped = _wrap(item.text, available, start=start + text_width(prefix))
    return [(prefix if index == 0 else " " * text_width(prefix)) + line for index, line in enumerate(wrapped)]


def _rule(width: int, label: str, glyphs: Mapping[str, str]) -> str:
    middle = f" {label} "
    remaining = width - 2 - text_width(middle)
    if remaining < 0:
        raise FitError(f"journal block is too narrow for section {label}")
    return glyphs["lj"] + middle + glyphs["h"] * remaining + glyphs["rj"]


def _range(indices: Sequence[int], total: int) -> str:
    if total == 0:
        return "none"
    if not indices:
        return f"elsewhere/{total}"
    return f"{indices[0] + 1}-{indices[-1] + 1}/{total}"


def _day_block(journal: Journal, entry: Entry, selected: Sequence[tuple[str, int]], *, part_index: int, width: int, origin: int, theme: str, journal_context: bool) -> DayPart:
    if width < MIN_DAILY_WIDTH:
        raise FitError(f"Schema Blocks require at least {MIN_DAILY_WIDTH} cells")
    glyphs = _glyphs(theme)
    inner = width - 4
    body_start = origin + 2
    event_indices = tuple(index for kind, index in selected if kind == "event")
    step_indices = tuple(index for kind, index in selected if kind == "step")
    lines = [glyphs["tl"] + glyphs["h"] * (width - 2) + glyphs["tr"]]
    fields: list[tuple[str, str]] = []
    if journal_context:
        fields.extend((("JOURNAL", journal.title), ("TIMEZONE", journal.timezone)))
    fields.extend((("DATE", entry.entry_date.isoformat()), ("ENTRY", entry.entry_id), ("PAGE", f"{part_index:04d}")))
    if entry.mood is not None:
        fields.append(("MOOD", entry.mood))
    for metric in entry.metrics:
        value = f"{metric.label} = {metric.value}" + (f" {metric.unit}" if metric.unit else "")
        fields.append(("METRIC", value))
    for label, value in fields:
        lines.extend(_content(row, width, glyphs) for row in _field(label, value, inner, body_start))
    lines.append(_rule(width, f"EVENTS {_range(event_indices, len(entry.events))}", glyphs))
    if event_indices:
        for index in event_indices:
            lines.extend(_content(row, width, glyphs) for row in _record("*", entry.events[index], inner, body_start))
    else:
        lines.append(_content("(none)" if not entry.events else "(on another part)", width, glyphs))
    lines.append(_rule(width, "REFLECTION repeated", glyphs))
    for row in _wrap(entry.reflection if entry.reflection else "(none)", inner, start=body_start):
        lines.append(_content(row, width, glyphs))
    lines.append(_rule(width, f"NEXT STEPS {_range(step_indices, len(entry.next_steps))}", glyphs))
    if step_indices:
        for index in step_indices:
            lines.extend(_content(row, width, glyphs) for row in _record(">", entry.next_steps[index], inner, body_start))
    else:
        lines.append(_content("(none)" if not entry.next_steps else "(on another part)", width, glyphs))
    lines.append(glyphs["bl"] + glyphs["h"] * (width - 2) + glyphs["br"])
    return DayPart(entry, part_index, 1, tuple(lines), event_indices, step_indices)


def _day_parts(journal: Journal, entry: Entry, *, width: int, origin: int, max_height: int, theme: str, journal_context: bool) -> tuple[DayPart, ...]:
    units = tuple(("event", index) for index in range(len(entry.events))) + tuple(("step", index) for index in range(len(entry.next_steps)))
    if not units:
        part = _day_block(journal, entry, (), part_index=1, width=width, origin=origin, theme=theme, journal_context=journal_context)
        if len(part.lines) > max_height:
            raise FitError(f"entry {entry.entry_id!r} repeated context cannot fit")
        return (part,)
    output: list[DayPart] = []
    cursor = 0
    while cursor < len(units):
        best: DayPart | None = None
        for end in range(cursor + 1, len(units) + 1):
            candidate = _day_block(journal, entry, units[cursor:end], part_index=len(output) + 1, width=width, origin=origin, theme=theme, journal_context=journal_context)
            if len(candidate.lines) > max_height:
                break
            best = candidate
        if best is None:
            kind, index = units[cursor]
            item = entry.events[index] if kind == "event" else entry.next_steps[index]
            raise FitError(f"indivisible {kind} record {item.record_id!r} cannot fit with repeated context")
        output.append(best)
        cursor += len(best.event_indices) + len(best.step_indices)
    count = len(output)
    return tuple(replace(part, part_count=count) for part in output)


def _position(cards: Sequence[CardDraft]) -> tuple[CardDraft, ...]:
    output: list[CardDraft] = []
    y = 0
    for card in cards:
        output.append(replace(card, x=0, y=y))
        y += card.height + 2
    return tuple(output)


def _daily(journal: Journal, options: RenderOptions) -> tuple[CardDraft, ...]:
    if options.max_width < MIN_DAILY_WIDTH:
        raise FitError(f"daily journal needs width {MIN_DAILY_WIDTH}")
    cards: list[CardDraft] = []
    for entry in journal.entries:
        for part in _day_parts(journal, entry, width=options.max_width, origin=0, max_height=options.max_height, theme=options.theme, journal_context=True):
            cards.append(CardDraft(
                f"journal-{entry.entry_id}-p{part.part_index:03d}", "\n".join(part.lines), options.max_width, len(part.lines),
                metadata={
                    "style": "journal", "view": "daily", "timezone": journal.timezone,
                    "date": entry.entry_date.isoformat(), "entry_id": entry.entry_id,
                    "part_index": part.part_index, "part_count": part.part_count,
                    "event_ids": [entry.events[index].record_id for index in part.event_indices],
                    "next_step_ids": [entry.next_steps[index].record_id for index in part.step_indices],
                    "mood_supplied": entry.mood is not None, "metric_labels": [metric.label for metric in entry.metrics],
                    "layout_engines": ["schema-blocks"], "lane_timeline": False,
                    "missing_dates_synthesized": False,
                },
            ))
    return tuple(cards)


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _week_header(journal: Journal, start: date, width: int, theme: str, page: int) -> tuple[str, ...]:
    glyphs = _glyphs(theme)
    inner = width - 4
    lines = [glyphs["tl"] + glyphs["h"] * (width - 2) + glyphs["tr"]]
    fields = (("JOURNAL", journal.title), ("VIEW", "weekly / ordinal dates"), ("WEEK", f"{start.isoformat()} .. {(start + timedelta(days=6)).isoformat()}"), ("TIMEZONE", journal.timezone), ("PAGE", f"{page:04d}"))
    for label, value in fields:
        lines.extend(_content(row, width, glyphs) for row in _field(label, value, inner, 2))
    lines.append(_rule(width, "BOUNDED WEEK", glyphs))
    return tuple(lines)


def _weekly_height(header: Sequence[str], parts: Sequence[DayPart]) -> int:
    return len(header) + sum(len(part.lines) for part in parts) + max(0, len(parts) - 1) + 1


def _week_card(journal: Journal, start: date, parts: Sequence[DayPart], *, page: int, count: int, options: RenderOptions) -> CardDraft:
    header = _week_header(journal, start, options.max_width, options.theme, page)
    glyphs = _glyphs(options.theme)
    distinct = {part.entry.entry_date for part in parts}
    lane_used = len(distinct) > 1
    lane_width = allocate_lane_widths(4, 1, gutter=0, minimum=4)[0]
    lane_x = 2 + lane_positions((lane_width,), gutter=0)[0]
    lines = list(header)
    for offset, part in enumerate(parts):
        for row, block_line in enumerate(part.lines):
            prefix = (glyphs["marker"] + glyphs["join"] + " ") if lane_used and row == 0 else (glyphs["v"] + "   " if lane_used else "    ")
            lines.append(glyphs["v"] + " " + prefix + block_line + " " + glyphs["v"])
        if offset + 1 < len(parts):
            prefix = glyphs["v"] + "   " if lane_used else "    "
            lines.append(glyphs["v"] + " " + prefix + " " * (options.max_width - 8) + " " + glyphs["v"])
    lines.append(glyphs["bl"] + glyphs["h"] * (options.max_width - 2) + glyphs["br"])
    blocks = [Block(f"{part.entry.entry_id}-p{part.part_index}", part.lines) for part in parts]
    placements = place_blocks(blocks, start_y=len(header), gap=1)
    day_metadata = []
    for part, placement in zip(parts, placements):
        day_metadata.append({
            "entry_id": part.entry.entry_id, "date": part.entry.entry_date.isoformat(),
            "part_index": part.part_index, "part_count": part.part_count,
            "event_ids": [part.entry.events[index].record_id for index in part.event_indices],
            "next_step_ids": [part.entry.next_steps[index].record_id for index in part.step_indices],
            "schema_rect": {"x": 6, "y": placement.y, "width": options.max_width - 8, "height": placement.height},
            "mood_supplied": part.entry.mood is not None, "metric_labels": [metric.label for metric in part.entry.metrics],
        })
    return CardDraft(
        f"journal-week-{start.strftime('%Y%m%d')}-p{page:03d}", "\n".join(lines), options.max_width, len(lines),
        metadata={
            "style": "journal", "view": "weekly", "timezone": journal.timezone,
            "week_start": start.isoformat(), "week_end": (start + timedelta(days=6)).isoformat(),
            "week_page": page, "week_page_count": count,
            "entry_ids": [part.entry.entry_id for part in parts], "dates": [part.entry.entry_date.isoformat() for part in parts],
            "day_parts": day_metadata, "layout_engines": ["schema-blocks"] + (["lane-timeline"] if lane_used else []),
            "lane_timeline": lane_used, "timeline_mode": "ordinal" if lane_used else None,
            "timeline_lane": {"x": lane_x, "y": len(header), "width": lane_width, "height": sum(len(part.lines) for part in parts) + max(0, len(parts) - 1)} if lane_used else None,
            "missing_dates_synthesized": False,
        },
    )


def _weekly(journal: Journal, options: RenderOptions) -> tuple[CardDraft, ...]:
    if options.max_width < MIN_WEEKLY_WIDTH:
        raise FitError(f"weekly journal needs width {MIN_WEEKLY_WIDTH}")
    weeks: list[tuple[date, list[Entry]]] = []
    for entry in journal.entries:
        start = _week_start(entry.entry_date)
        if not weeks or weeks[-1][0] != start:
            weeks.append((start, [entry]))
        else:
            weeks[-1][1].append(entry)
    cards: list[CardDraft] = []
    for start, entries in weeks:
        header = _week_header(journal, start, options.max_width, options.theme, 1)
        capacity = options.max_height - len(header) - 1
        if capacity < 1:
            raise FitError("weekly header leaves no room for a Schema Block")
        grouped = [
            _day_parts(journal, entry, width=options.max_width - 8, origin=6, max_height=capacity, theme=options.theme, journal_context=False)
            for entry in entries
        ]
        batches: list[list[DayPart]] = []
        current: list[DayPart] = []
        for parts in grouped:
            if len(parts) > 1:
                if current:
                    batches.append(current)
                    current = []
                batches.extend([[part] for part in parts])
                continue
            candidate = current + [parts[0]]
            if _weekly_height(header, candidate) <= options.max_height:
                current = candidate
            else:
                if current:
                    batches.append(current)
                current = [parts[0]]
        if current:
            batches.append(current)
        cards.extend(_week_card(journal, start, batch, page=index, count=len(batches), options=options) for index, batch in enumerate(batches, start=1))
    return tuple(cards)


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    journal = _normalize(data)
    cards = _daily(journal, options) if journal.view == "daily" else _weekly(journal, options)
    if options.single_card and len(cards) != 1:
        raise FitError(f"{journal.view} journal semantics require {len(cards)} cards")
    result = RenderResult(RENDERER, options.theme, _position(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
