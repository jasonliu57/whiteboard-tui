#!/usr/bin/env python3
"""Render ordinal or timestamp point events as Chain/Lane Timeline cards."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cell_width import pad_cells, text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, int_value, object_value, slug_value, string_value
from tools.textart_notes.core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_preserving_text
from tools.textart_notes.layouts.lanes import allocate_lane_widths
from tools.textart_notes.layouts.timeline import scale_gap


RENDERER = "timeline-note"
PROPORTIONAL_LIMIT = 24
MAX_SECONDS_PER_CELL = 315_360_000
TIMESTAMP_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"T(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?P<fraction>\.\d{1,6})?(?P<zone>Z|[+-]\d{2}:\d{2})\Z"
)


@dataclass(frozen=True)
class Lane:
    lane_id: str
    label: str


@dataclass(frozen=True)
class Event:
    event_id: str
    label: str
    description: str
    lane_id: str | None


@dataclass(frozen=True)
class Group:
    key: str
    display_key: str
    order: int
    events: tuple[Event, ...]


@dataclass(frozen=True)
class Timeline:
    title: str
    kind: str
    spacing: str
    seconds_per_cell: int | None
    max_gap_cells: int | None
    lanes: tuple[Lane, ...]
    groups: tuple[Group, ...]

    @property
    def engine(self) -> str:
        return "lane-timeline" if self.lanes else "chain"


def _text(value: object, path: str, *, single_line: bool) -> str:
    result = string_value(value, path, single_line=single_line, allow_tabs=not single_line)
    if not result.strip():
        raise InputError(f"{path} must not be whitespace-only")
    return result


def _timestamp(value: object, path: str) -> tuple[int, str]:
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        raise InputError(f"{path} must be strict RFC 3339 with seconds and numeric offset or Z")
    match = TIMESTAMP_RE.fullmatch(value)
    assert match is not None
    zone = match.group("zone")
    if zone == "-00:00":
        raise InputError(f"{path} must not use unknown offset -00:00")
    if zone != "Z":
        hours = int(zone[1:3])
        minutes = int(zone[4:6])
        if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
            raise InputError(f"{path} offset must be between -14:00 and +14:00")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if zone == "Z" else value)
        normalized = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise InputError(f"{path} is not a UTC-normalizable civil-date instant") from error
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = normalized - epoch
    instant = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    canonical = (
        f"{normalized.year:04d}-{normalized.month:02d}-{normalized.day:02d}"
        f"T{normalized.hour:02d}:{normalized.minute:02d}:{normalized.second:02d}"
    )
    if normalized.microsecond:
        canonical += f".{normalized.microsecond:06d}"
    return instant, canonical + "Z"


def _lanes(root: Mapping[str, object]) -> tuple[Lane, ...]:
    if "lanes" not in root:
        return ()
    values = array_value(root["lanes"], "lanes")
    if len(values) < 2:
        raise InputError("lanes must contain at least two lanes or be omitted")
    output: list[Lane] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = f"lanes[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "label"}, allowed={"id", "label"})
        lane_id = slug_value(record["id"], f"{path}.id")
        if lane_id in seen:
            raise InputError(f"duplicate lane id {lane_id!r}")
        seen.add(lane_id)
        output.append(Lane(lane_id, _text(record["label"], f"{path}.label", single_line=True)))
    return tuple(output)


def _event_lane(record: Mapping[str, object], path: str, lanes: tuple[Lane, ...]) -> str | None:
    if not lanes:
        if "lane_id" in record:
            raise InputError(f"{path}.lane_id is forbidden when lanes are absent")
        return None
    lane_id = slug_value(record["lane_id"], f"{path}.lane_id")
    if lane_id not in {lane.lane_id for lane in lanes}:
        raise InputError(f"{path}.lane_id references unknown lane {lane_id!r}")
    return lane_id


def _normalize(data: dict[str, object]) -> Timeline:
    root = object_value(data, "input")
    allowed = {"schema", "title", "timeline", "lanes", "events"}
    check_keys(root, "input", required={"schema", "title", "timeline", "events"}, allowed=allowed)
    if root["schema"] != "timeline-note/v1":
        raise InputError("schema must equal timeline-note/v1")
    title = _text(root["title"], "title", single_line=True)
    lanes = _lanes(root)
    raw_timeline = object_value(root["timeline"], "timeline")
    events = array_value(root["events"], "events")
    if not events:
        raise InputError("events must not be empty")
    kind = raw_timeline.get("kind")
    event_ids: set[str] = set()

    if kind == "ordinal":
        check_keys(raw_timeline, "timeline", required={"kind", "stages"}, allowed={"kind", "stages"})
        raw_stages = array_value(raw_timeline["stages"], "timeline.stages")
        if not raw_stages:
            raise InputError("timeline.stages must not be empty")
        stages: list[Lane] = []
        positions: dict[str, int] = {}
        for index, value in enumerate(raw_stages):
            path = f"timeline.stages[{index}]"
            record = object_value(value, path)
            check_keys(record, path, required={"id", "label"}, allowed={"id", "label"})
            stage_id = slug_value(record["id"], f"{path}.id")
            if stage_id in positions:
                raise InputError(f"duplicate stage id {stage_id!r}")
            positions[stage_id] = index
            stages.append(Lane(stage_id, _text(record["label"], f"{path}.label", single_line=True)))
        parsed: list[tuple[int, str, str, Event]] = []
        previous = -1
        used: set[str] = set()
        for index, value in enumerate(events):
            path = f"events[{index}]"
            record = object_value(value, path)
            required = {"id", "stage_id", "label", "description"} | ({"lane_id"} if lanes else set())
            check_keys(record, path, required=required, allowed=required)
            event_id = slug_value(record["id"], f"{path}.id")
            if event_id in event_ids:
                raise InputError(f"duplicate event id {event_id!r}")
            event_ids.add(event_id)
            stage_id = slug_value(record["stage_id"], f"{path}.stage_id")
            if stage_id not in positions:
                raise InputError(f"{path}.stage_id references unknown stage {stage_id!r}")
            order = positions[stage_id]
            if order < previous:
                raise InputError("ordinal events must already be in declared stage order")
            previous = order
            used.add(stage_id)
            parsed.append((order, stage_id, stages[order].label, Event(
                event_id,
                _text(record["label"], f"{path}.label", single_line=True),
                _text(record["description"], f"{path}.description", single_line=False),
                _event_lane(record, path, lanes),
            )))
        unused = [stage.lane_id for stage in stages if stage.lane_id not in used]
        if unused:
            raise InputError(f"every stage must be referenced; unused: {', '.join(unused)}")
        groups: list[Group] = []
        for order, stage_id, label, event in parsed:
            if not groups or groups[-1].order != order:
                groups.append(Group(stage_id, f"{label} [{stage_id}]", order, (event,)))
            else:
                last = groups[-1]
                groups[-1] = Group(last.key, last.display_key, last.order, last.events + (event,))
        return Timeline(title, "ordinal", "ordinal", None, None, lanes, tuple(groups))

    if kind != "timestamp":
        raise InputError("timeline.kind must be ordinal or timestamp")
    spacing = raw_timeline.get("spacing")
    if spacing == "proportional":
        required_timeline = {"kind", "spacing", "seconds_per_cell"}
        max_gap = None
    elif spacing == "compressed":
        required_timeline = {"kind", "spacing", "seconds_per_cell", "max_gap_cells"}
        max_gap = None
    else:
        raise InputError("timeline.spacing must be proportional or compressed")
    check_keys(raw_timeline, "timeline", required=required_timeline, allowed=required_timeline)
    if spacing == "compressed":
        max_gap = int_value(raw_timeline["max_gap_cells"], "timeline.max_gap_cells", minimum=1, maximum=24)
    seconds_per_cell = int_value(raw_timeline["seconds_per_cell"], "timeline.seconds_per_cell", minimum=1, maximum=MAX_SECONDS_PER_CELL)
    parsed_ts: list[tuple[int, str, Event]] = []
    previous_instant: int | None = None
    for index, value in enumerate(events):
        path = f"events[{index}]"
        record = object_value(value, path)
        required = {"id", "timestamp", "label", "description"} | ({"lane_id"} if lanes else set())
        check_keys(record, path, required=required, allowed=required)
        event_id = slug_value(record["id"], f"{path}.id")
        if event_id in event_ids:
            raise InputError(f"duplicate event id {event_id!r}")
        event_ids.add(event_id)
        instant, canonical = _timestamp(record["timestamp"], f"{path}.timestamp")
        if previous_instant is not None and instant < previous_instant:
            raise InputError("timestamp events must already be in normalized UTC order")
        previous_instant = instant
        parsed_ts.append((instant, canonical, Event(
            event_id,
            _text(record["label"], f"{path}.label", single_line=True),
            _text(record["description"], f"{path}.description", single_line=False),
            _event_lane(record, path, lanes),
        )))
    groups_ts: list[Group] = []
    for instant, canonical, event in parsed_ts:
        if not groups_ts or groups_ts[-1].order != instant:
            groups_ts.append(Group(canonical, canonical, instant, (event,)))
        else:
            last = groups_ts[-1]
            groups_ts[-1] = Group(last.key, last.display_key, last.order, last.events + (event,))
    return Timeline(title, "timestamp", spacing, seconds_per_cell, max_gap, lanes, tuple(groups_ts))


def _glyphs(theme: str) -> Mapping[str, str]:
    selected = get_theme(theme)
    return {
        "tl": selected.line(EAST | SOUTH), "tr": selected.line(SOUTH | WEST),
        "bl": selected.line(NORTH | EAST), "br": selected.line(NORTH | WEST),
        "h": selected.line(EAST | WEST), "v": selected.line(NORTH | SOUTH),
        "lj": selected.line(NORTH | EAST | SOUTH), "rj": selected.line(NORTH | SOUTH | WEST),
        "cross": selected.line(NORTH | EAST | SOUTH | WEST), "bt": selected.line(NORTH | EAST | WEST),
        "marker": "o" if theme == "ascii" else ("◆" if theme == "unicode-rich" else "●"),
        "gap": ":" if theme == "ascii" else "⋮",
    }


def _wrap(text: str, width: int, *, start: int) -> list[str]:
    try:
        return wrap_preserving_text(text, width, start_column=start)
    except ValueError as error:
        raise FitError(str(error)) from error


def _widths(model: Timeline, total: int) -> tuple[int, ...]:
    lane_count = len(model.lanes) or 1
    column_count = lane_count + 1
    usable = total - column_count - 1
    key_minimum = 16 if model.kind == "timestamp" else 8
    minimum = key_minimum + lane_count * 12
    if usable < minimum:
        raise FitError(f"timeline width {total} cannot preserve time and lane minimums")
    desired = max(key_minimum, min(28, max(text_width(group.display_key) + 2 for group in model.groups)))
    key = min(desired, usable - lane_count * 12)
    lanes = allocate_lane_widths(usable - key, lane_count, gutter=0, minimum=12)
    return (key,) + lanes


def _origins(widths: Sequence[int]) -> tuple[int, ...]:
    output: list[int] = []
    cursor = 1
    for width in widths:
        output.append(cursor)
        cursor += width + 1
    return tuple(output)


def _outer(width: int, glyphs: Mapping[str, str], *, bottom: bool = False) -> str:
    return (glyphs["bl"] if bottom else glyphs["tl"]) + glyphs["h"] * (width - 2) + (glyphs["br"] if bottom else glyphs["tr"])


def _table_rule(widths: Sequence[int], glyphs: Mapping[str, str], *, bottom: bool = False) -> str:
    if bottom:
        return glyphs["bl"] + glyphs["bt"].join(glyphs["h"] * width for width in widths) + glyphs["br"]
    return glyphs["lj"] + glyphs["cross"].join(glyphs["h"] * width for width in widths) + glyphs["rj"]


def _row(cells: Sequence[str], widths: Sequence[int], glyphs: Mapping[str, str]) -> str:
    return glyphs["v"] + glyphs["v"].join(pad_cells(cell, width) for cell, width in zip(cells, widths)) + glyphs["v"]


def _span(text: str, width: int, glyphs: Mapping[str, str]) -> str:
    return glyphs["v"] + pad_cells(text, width - 2) + glyphs["v"]


def _event_lines(events: Sequence[Event], width: int, *, start: int) -> list[str]:
    output: list[str] = []
    for index, event in enumerate(events):
        if index:
            output.append("")
        output.extend(_wrap(f"[{event.event_id}] {event.label}", width, start=start))
        output.extend(_wrap("  " + event.description.replace("\n", "\n  "), width, start=start))
    return output or [""]


def _group_rows(model: Timeline, group: Group, widths: Sequence[int], origins: Sequence[int], glyphs: Mapping[str, str]) -> list[str]:
    keys = _wrap(f"{glyphs['marker']} {group.display_key}", widths[0], start=origins[0])
    lane_lines: list[list[str]] = []
    if model.lanes:
        for index, lane in enumerate(model.lanes, start=1):
            lane_lines.append(_event_lines([event for event in group.events if event.lane_id == lane.lane_id], widths[index], start=origins[index]))
    else:
        lane_lines.append(_event_lines(group.events, widths[1], start=origins[1]))
    height = max(len(keys), *(len(lines) for lines in lane_lines))
    output: list[str] = []
    for row_index in range(height):
        cells = [keys[row_index] if row_index < len(keys) else glyphs["v"]]
        cells.extend(lines[row_index] if row_index < len(lines) else "" for lines in lane_lines)
        output.append(_row(cells, widths, glyphs))
    return output


def _raw_gap(model: Timeline, first: Group, second: Group) -> int:
    if model.kind == "ordinal":
        return 1
    assert model.seconds_per_cell is not None
    return scale_gap(second.order - first.order, model.seconds_per_cell * 1_000_000).raw_cells


def _duration(delta: int) -> str:
    days, rest = divmod(delta, 86_400_000_000)
    hours, rest = divmod(rest, 3_600_000_000)
    minutes, rest = divmod(rest, 60_000_000)
    seconds, micros = divmod(rest, 1_000_000)
    value = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if micros:
        value += f".{micros:06d}"
    return (f"{days}d+" if days else "") + value


def _gap_rows(model: Timeline, first: Group, second: Group, widths: Sequence[int], origins: Sequence[int], glyphs: Mapping[str, str]) -> list[str]:
    raw = _raw_gap(model, first, second)
    annotation: list[str] = []
    drawn = raw
    if model.spacing == "compressed":
        assert model.max_gap_cells is not None and model.seconds_per_cell is not None
        scaled = scale_gap(second.order - first.order, model.seconds_per_cell * 1_000_000, cap=model.max_gap_cells)
        drawn = scaled.drawn_cells
        if scaled.omitted_cells:
            annotation.extend(_wrap(f"{glyphs['gap']} omitted={scaled.omitted_cells} cells", widths[0], start=origins[0]))
            annotation.extend(_wrap(f"delta={_duration(second.order - first.order)}", widths[0], start=origins[0]))
    count = max(drawn, len(annotation))
    return [_row([annotation[index] if index < len(annotation) else glyphs["v"]] + [""] * (len(widths) - 1), widths, glyphs) for index in range(count)]


def _scale(model: Timeline) -> str:
    if model.kind == "ordinal":
        return "ordinal; one connector cell per stage boundary"
    assert model.seconds_per_cell is not None
    if model.spacing == "proportional":
        return f"proportional; {model.seconds_per_cell}s/cell; raw-gap limit={PROPORTIONAL_LIMIT}"
    return f"compressed; {model.seconds_per_cell}s/cell; gap cap={model.max_gap_cells} cells"


def _page_lines(model: Timeline, groups: Sequence[Group], previous: Group | None, widths: Sequence[int], options: RenderOptions) -> list[str]:
    glyphs = _glyphs(options.theme)
    origins = _origins(widths)
    engine = "Lane Timeline" if model.lanes else "Chain"
    headers = [
        f"Timeline: {model.title}",
        f"Mode: {model.kind}/{model.spacing} | Engine: {engine}",
        f"Range: {groups[0].display_key} -> {groups[-1].display_key}",
        f"Scale: {_scale(model)}",
    ]
    if previous is not None:
        if model.kind == "timestamp":
            headers.append(f"Context: after {previous.display_key}; delta={_duration(groups[0].order - previous.order)}; boundary connector={_raw_gap(model, previous, groups[0])} cells carried here")
        else:
            headers.append(f"Context: after {previous.display_key}; ordinal boundary connector carried here")
    lines = [_outer(options.max_width, glyphs)]
    for header in headers:
        lines.extend(_span(line, options.max_width, glyphs) for line in _wrap(header, options.max_width - 2, start=1))
    lines.append(_table_rule(widths, glyphs))
    labels = ["TIME (UTC)" if model.kind == "timestamp" else "STAGE"] + ([lane.label for lane in model.lanes] if model.lanes else ["EVENTS"])
    wrapped_labels = [_wrap(label, width, start=origin) for label, width, origin in zip(labels, widths, origins)]
    for row_index in range(max(len(value) for value in wrapped_labels)):
        lines.append(_row([value[row_index] if row_index < len(value) else "" for value in wrapped_labels], widths, glyphs))
    lines.append(_table_rule(widths, glyphs))
    for index, group in enumerate(groups):
        if index:
            lines.extend(_gap_rows(model, groups[index - 1], group, widths, origins, glyphs))
        lines.extend(_group_rows(model, group, widths, origins, glyphs))
    lines.append(_table_rule(widths, glyphs, bottom=True))
    return lines


def _check_gap_policy(model: Timeline) -> None:
    if model.kind == "timestamp" and model.spacing == "proportional":
        for first, second in zip(model.groups, model.groups[1:]):
            raw = _raw_gap(model, first, second)
            if raw > PROPORTIONAL_LIMIT:
                raise FitError(f"proportional gap needs {raw} cells; use compressed")


def _pages(model: Timeline, widths: Sequence[int], options: RenderOptions) -> list[tuple[tuple[Group, ...], list[str], Group | None]]:
    pages: list[tuple[tuple[Group, ...], list[str], Group | None]] = []
    start = 0
    while start < len(model.groups):
        previous = model.groups[start - 1] if start else None
        best: tuple[int, list[str]] | None = None
        for end in range(start + 1, len(model.groups) + 1):
            candidate = _page_lines(model, model.groups[start:end], previous, widths, options)
            if len(candidate) <= options.max_height:
                best = end, candidate
        if best is None:
            raise FitError(f"indivisible simultaneous group {model.groups[start].key!r} cannot fit")
        end, lines = best
        pages.append((model.groups[start:end], lines, previous))
        if options.single_card and end < len(model.groups):
            raise FitError("timeline requires semantic pagination while --single-card is active")
        start = end
    return pages


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    model = _normalize(data)
    widths = _widths(model, options.max_width)
    _check_gap_policy(model)
    pages = _pages(model, widths, options)
    cards: list[CardDraft] = []
    for index, (groups, lines, previous) in enumerate(pages):
        metadata: dict[str, object] = {
            "style": "timeline", "page": index + 1, "page_count": len(pages),
            "engine": model.engine, "temporal_kind": model.kind, "spacing": model.spacing,
            "range_start": groups[0].key, "range_end": groups[-1].key,
            "group_ids": [group.key for group in groups],
            "event_ids": [event.event_id for group in groups for event in group.events],
            "lane_ids": [lane.lane_id for lane in model.lanes],
        }
        if model.kind == "timestamp":
            metadata.update({"normalized_timezone": "UTC", "seconds_per_cell": model.seconds_per_cell})
        if model.spacing == "compressed":
            metadata["max_gap_cells"] = model.max_gap_cells
        if previous is not None:
            metadata["previous_group"] = previous.key
            metadata["boundary_connector_cells"] = _raw_gap(model, previous, groups[0])
        cards.append(CardDraft(
            logical_id=f"timeline-{index:03d}", text="\n".join(lines),
            width=options.max_width, height=len(lines),
            x=index * (options.max_width + 4), y=0, metadata=metadata,
        ))
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
