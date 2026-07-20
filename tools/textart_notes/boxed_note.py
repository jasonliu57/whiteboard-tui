#!/usr/bin/env python3
"""Render ordered boxed topics and optional group regions as text-art cards."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.canvas import Canvas
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, object_value, slug_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_preserving_line
from tools.textart_notes.layouts.cluster import ClusterItem, ClusterPlacement, ClusterSize, pack_shelves


RENDERER = "boxed-note"
TAB_PHASES = 4
PREFERRED_CONTENT_WIDTH = 30
MIN_CONTENT_WIDTH = 8
TOPIC_GUTTER_X = 2
SHELF_GUTTER_Y = 1
GROUP_GUTTER_Y = 1
GROUP_INSET_X = 2
CARD_GAP = 2
MAX_RECORDS = 9999


@dataclass(frozen=True)
class Topic:
    topic_id: str
    heading: str
    body: tuple[str, ...]
    emphasis: str


@dataclass(frozen=True)
class Group:
    group_id: str
    heading: str
    topics: tuple[Topic, ...]


@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    topics: tuple[Topic, ...] = ()
    groups: tuple[Group, ...] = ()


@dataclass(frozen=True)
class TopicVariant:
    inner_width: int
    width: int
    height: int
    heading_lines: tuple[str, ...]
    body_lines: tuple[str, ...]


@dataclass(frozen=True)
class MeasuredTopic:
    topic: Topic
    variants: tuple[TopicVariant, ...]

    def variant_at(self, x: int) -> TopicVariant:
        return self.variants[(x + 2) % TAB_PHASES]

    def cluster_item(self) -> ClusterItem:
        return ClusterItem(
            self.topic.topic_id,
            tuple(ClusterSize(item.width, item.height) for item in self.variants),
            phase_offset=2,
        )


@dataclass(frozen=True)
class PlacedTopic:
    measured: MeasuredTopic
    variant: TopicVariant
    x: int
    y: int
    group_id: str | None = None


@dataclass(frozen=True)
class Region:
    group: Group
    x: int
    y: int
    width: int
    height: int
    heading_lines: tuple[str, ...]
    topics: tuple[PlacedTopic, ...]
    segment_index: int = 1
    segment_count: int = 1


@dataclass
class Page:
    topics: list[PlacedTopic]
    regions: list[Region]
    used_height: int


def _text(value: object, path: str, *, tabs: bool = False) -> str:
    result = string_value(value, path, single_line=True, allow_tabs=tabs)
    if not any(not character.isspace() for character in result):
        raise InputError(f"{path} must contain visible text")
    return result


def _topic(value: object, path: str) -> Topic:
    record = object_value(value, path)
    check_keys(
        record,
        path,
        required={"id", "heading", "body"},
        allowed={"id", "heading", "body", "emphasis"},
    )
    values = array_value(record["body"], f"{path}.body")
    if not values:
        raise InputError(f"{path}.body must not be empty")
    emphasis = record.get("emphasis", "normal")
    if emphasis not in {"normal", "strong"}:
        raise InputError(f"{path}.emphasis must be normal or strong")
    return Topic(
        slug_value(record["id"], f"{path}.id", max_length=64),
        _text(record["heading"], f"{path}.heading"),
        tuple(_text(item, f"{path}.body[{index}]", tabs=True) for index, item in enumerate(values)),
        str(emphasis),
    )


def _normalize(data: dict[str, object]) -> Document:
    root = object_value(data, "input")
    has_topics = "topics" in root
    has_groups = "groups" in root
    if has_topics == has_groups:
        raise InputError("input must contain exactly one of topics or groups")
    content_key = "topics" if has_topics else "groups"
    check_keys(root, "input", required={"id", "title", content_key}, allowed={"id", "title", content_key})
    document_id = slug_value(root["id"], "id", max_length=64)
    title = _text(root["title"], "title")
    seen_topics: set[str] = set()
    if has_topics:
        values = array_value(root["topics"], "topics")
        if not 1 <= len(values) <= MAX_RECORDS:
            raise InputError(f"topics must contain 1..{MAX_RECORDS} entries")
        topics: list[Topic] = []
        for index, value in enumerate(values):
            topic = _topic(value, f"topics[{index}]")
            if topic.topic_id in seen_topics:
                raise InputError(f"duplicate topic id {topic.topic_id!r}")
            seen_topics.add(topic.topic_id)
            topics.append(topic)
        return Document(document_id, title, tuple(topics))

    raw_groups = array_value(root["groups"], "groups")
    if not 1 <= len(raw_groups) <= MAX_RECORDS:
        raise InputError(f"groups must contain 1..{MAX_RECORDS} entries")
    groups: list[Group] = []
    group_ids: set[str] = set()
    total = 0
    for group_index, value in enumerate(raw_groups):
        path = f"groups[{group_index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "heading", "topics"}, allowed={"id", "heading", "topics"})
        group_id = slug_value(record["id"], f"{path}.id", max_length=64)
        if group_id in group_ids:
            raise InputError(f"duplicate group id {group_id!r}")
        group_ids.add(group_id)
        values = array_value(record["topics"], f"{path}.topics")
        if not values:
            raise InputError(f"{path}.topics must not be empty")
        total += len(values)
        if total > MAX_RECORDS:
            raise InputError(f"boxed note may contain at most {MAX_RECORDS} topics")
        topics = []
        for topic_index, raw_topic in enumerate(values):
            topic = _topic(raw_topic, f"{path}.topics[{topic_index}]")
            if topic.topic_id in seen_topics:
                raise InputError(f"duplicate topic id {topic.topic_id!r}")
            seen_topics.add(topic.topic_id)
            topics.append(topic)
        groups.append(Group(group_id, _text(record["heading"], f"{path}.heading"), tuple(topics)))
    return Document(document_id, title, groups=tuple(groups))


def _wrap(text: str, width: int, *, start: int) -> tuple[str, ...]:
    try:
        return tuple(wrap_preserving_line(text, width, start_column=start))
    except ValueError as error:
        raise FitError(str(error)) from error


def _measure_topic(topic: Topic, outer_cap: int) -> MeasuredTopic:
    maximum = min(PREFERRED_CONTENT_WIDTH, outer_cap - 4)
    if maximum < 1:
        raise FitError(f"no content width remains for topic {topic.topic_id!r}")
    heading = f"[topic:{topic.topic_id}] {topic.heading}"
    variants: list[TopicVariant] = []
    for phase in range(TAB_PHASES):
        natural = max([text_width(heading, start=phase), *(text_width(line, start=phase) for line in topic.body)])
        inner = min(maximum, max(min(MIN_CONTENT_WIDTH, maximum), natural))
        heading_lines = _wrap(heading, inner, start=phase)
        body_lines = tuple(
            line
            for source in topic.body
            for line in _wrap(source, inner, start=phase)
        )
        variants.append(TopicVariant(inner, inner + 4, len(heading_lines) + len(body_lines) + 3, heading_lines, body_lines))
    return MeasuredTopic(topic, tuple(variants))


def _header(document: Document, width: int) -> tuple[str, ...]:
    if width < 5:
        raise FitError("boxed note requires max_width >= 5")
    return _wrap(f"[document:{document.document_id}] {document.title}", width - 4, start=2)


def _cluster(measured: Sequence[MeasuredTopic], max_width: int, *, origin_y: int = 0) -> tuple[PlacedTopic, ...]:
    layout = pack_shelves(
        [item.cluster_item() for item in measured],
        max_width=max_width,
        origin_y=origin_y,
        gutter_x=TOPIC_GUTTER_X,
        gutter_y=SHELF_GUTTER_Y,
    )
    by_id = {item.topic.topic_id: item for item in measured}
    return tuple(
        PlacedTopic(
            by_id[placed.key],
            by_id[placed.key].variant_at(placed.x),
            placed.x,
            placed.y,
        )
        for placed in layout.placements
    )


def _ungrouped_pages(document: Document, options: RenderOptions, header_height: int) -> list[Page]:
    body_y = header_height + 1
    capacity = options.max_height - body_y
    measured = [_measure_topic(topic, options.max_width) for topic in document.topics]
    placements = _cluster(measured, options.max_width)
    shelves: list[list[PlacedTopic]] = []
    for placed in placements:
        if not shelves or shelves[-1][0].y != placed.y:
            shelves.append([])
        shelves[-1].append(placed)
    pages: list[Page] = []
    current: list[PlacedTopic] = []
    used = 0
    for shelf in shelves:
        shelf_top = shelf[0].y
        shelf_height = max(item.variant.height for item in shelf)
        if shelf_height > capacity:
            raise FitError(f"topic shelf containing {shelf[0].measured.topic.topic_id!r} is taller than an empty card")
        required = shelf_height if not current else SHELF_GUTTER_Y + shelf_height
        if current and used + required > capacity:
            pages.append(Page(current, [], body_y + used))
            current = []
            used = 0
            required = shelf_height
        local_y = body_y + used + (SHELF_GUTTER_Y if current else 0)
        current.extend(
            PlacedTopic(item.measured, item.variant, item.x, local_y, None)
            for item in shelf
        )
        used += required
    if current:
        pages.append(Page(current, [], body_y + used))
    return pages


def _region(group: Group, topics: Sequence[Topic], max_width: int) -> Region:
    headings = _wrap(f"[group:{group.group_id}] {group.heading}", max_width - 4, start=2)
    origin_y = len(headings) + 2
    measured = [_measure_topic(topic, max_width - 2 * GROUP_INSET_X) for topic in topics]
    layout = pack_shelves(
        [item.cluster_item() for item in measured],
        max_width=max_width - 2 * GROUP_INSET_X,
        origin_x=GROUP_INSET_X,
        origin_y=origin_y,
        gutter_x=TOPIC_GUTTER_X,
        gutter_y=SHELF_GUTTER_Y,
    )
    by_id = {item.topic.topic_id: item for item in measured}
    placed = tuple(
        PlacedTopic(
            by_id[item.key],
            by_id[item.key].variant_at(item.x),
            item.x,
            item.y,
            group.group_id,
        )
        for item in layout.placements
    )
    right = max([4 + max(text_width(line) for line in headings), *(item.x + item.variant.width + GROUP_INSET_X for item in placed)])
    bottom = max(item.y + item.variant.height for item in placed) + 2
    return Region(group, 0, 0, min(max_width, right), bottom, headings, placed)


def _translate_region(region: Region, y: int, index: int, count: int) -> Region:
    return Region(
        region.group,
        0,
        y,
        region.width,
        region.height,
        region.heading_lines,
        tuple(
            PlacedTopic(item.measured, item.variant, item.x, item.y + y, item.group_id)
            for item in region.topics
        ),
        index,
        count,
    )


def _group_fragments(group: Group, max_width: int, capacity: int) -> list[Region]:
    complete = _region(group, group.topics, max_width)
    if complete.height <= capacity:
        return [complete]
    fragments: list[Region] = []
    offset = 0
    while offset < len(group.topics):
        accepted: Region | None = None
        end = offset
        while end < len(group.topics):
            candidate = _region(group, group.topics[offset : end + 1], max_width)
            if candidate.height > capacity:
                break
            accepted = candidate
            end += 1
        if accepted is None:
            raise FitError(f"indivisible topic {group.topics[offset].topic_id!r} cannot fit its group card")
        fragments.append(accepted)
        offset = end
    return fragments


def _grouped_pages(document: Document, options: RenderOptions, header_height: int) -> list[Page]:
    body_y = header_height + 1
    capacity = options.max_height - body_y
    if capacity < 1:
        raise FitError("boxed header leaves no room for a group")
    pages: list[Page] = []
    current = Page([], [], header_height)
    cursor = body_y
    for group in document.groups:
        fragments = _group_fragments(group, options.max_width, capacity)
        count = len(fragments)
        for fragment_index, fragment in enumerate(fragments, start=1):
            if current.regions and (fragment_index > 1 or cursor + fragment.height > options.max_height):
                pages.append(current)
                current = Page([], [], header_height)
                cursor = body_y
            if cursor + fragment.height > options.max_height:
                raise FitError(f"group {group.group_id!r} cannot fit an empty card")
            translated = _translate_region(fragment, cursor, fragment_index, count)
            current.regions.append(translated)
            current.topics.extend(translated.topics)
            current.used_height = cursor + fragment.height
            cursor = current.used_height + GROUP_GUTTER_Y
            if fragment_index < count:
                pages.append(current)
                current = Page([], [], header_height)
                cursor = body_y
    if current.regions:
        pages.append(current)
    return pages


def _paint(document: Document, page: Page, headings: Sequence[str], options: RenderOptions) -> str:
    canvas = Canvas(options.max_width, page.used_height, options.theme)
    canvas.draw_box(0, 0, options.max_width, len(headings) + 2)
    for row, line in enumerate(headings, start=1):
        canvas.put_text(2, row, line)
    for region in page.regions:
        canvas.draw_box(region.x, region.y, region.width, region.height)
        for row, line in enumerate(region.heading_lines, start=region.y + 1):
            canvas.put_text(region.x + 2, row, line)
    for topic in page.topics:
        canvas.draw_box(topic.x, topic.y, topic.variant.width, topic.variant.height)
        if topic.measured.topic.emphasis == "strong":
            canvas.put_text(topic.x + 1, topic.y, "!", overwrite=True)
        row = topic.y + 1
        for line in topic.variant.heading_lines:
            canvas.put_text(topic.x + 2, row, line)
            row += 1
        canvas.draw_path(((topic.x, row), (topic.x + topic.variant.width - 1, row)))
        row += 1
        for line in topic.variant.body_lines:
            canvas.put_text(topic.x + 2, row, line)
            row += 1
    return canvas.to_text()


def _overlap(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    x, y, width, height = first
    other_x, other_y, other_width, other_height = second
    return not (
        x + width <= other_x
        or other_x + other_width <= x
        or y + height <= other_y
        or other_y + other_height <= y
    )


def _validate_page_geometry(page: Page, options: RenderOptions) -> None:
    """Assert boxed-specific rectangle ownership and isolation invariants."""

    if not 1 <= page.used_height <= options.max_height:
        raise AssertionError("boxed page extent is outside its card")
    topic_rects = {
        item.measured.topic.topic_id: (item.x, item.y, item.variant.width, item.variant.height)
        for item in page.topics
    }
    if len(topic_rects) != len(page.topics):
        raise AssertionError("boxed page repeats a topic")
    for key, (x, y, width, height) in topic_rects.items():
        if x < 0 or y < 0 or x + width > options.max_width or y + height > page.used_height:
            raise AssertionError(f"boxed topic {key!r} leaves its card")
    topic_ids = list(topic_rects)
    for index, key in enumerate(topic_ids):
        if any(_overlap(topic_rects[key], topic_rects[other]) for other in topic_ids[index + 1 :]):
            raise AssertionError("boxed topics overlap")

    region_rects = {
        region.group.group_id: (region.x, region.y, region.width, region.height)
        for region in page.regions
    }
    if len(region_rects) != len(page.regions):
        raise AssertionError("boxed page repeats a region")
    region_ids = list(region_rects)
    for index, key in enumerate(region_ids):
        x, y, width, height = region_rects[key]
        if x < 0 or y < 0 or x + width > options.max_width or y + height > page.used_height:
            raise AssertionError(f"boxed region {key!r} leaves its card")
        if any(_overlap(region_rects[key], region_rects[other]) for other in region_ids[index + 1 :]):
            raise AssertionError("boxed regions overlap")

    member_ids: set[str] = set()
    for region in page.regions:
        region_rect = region_rects[region.group.group_id]
        expected = {item.measured.topic.topic_id for item in region.topics}
        if expected & member_ids:
            raise AssertionError("boxed topic belongs to multiple regions")
        member_ids.update(expected)
        rx, ry, rw, rh = region_rect
        for key in expected:
            if key not in topic_rects:
                raise AssertionError("boxed region member is absent from its page")
            x, y, width, height = topic_rects[key]
            if not (rx < x and ry < y and x + width < rx + rw and y + height < ry + rh):
                raise AssertionError(f"boxed topic {key!r} is not strictly inside its region")
        for key, rect in topic_rects.items():
            if key not in expected and _overlap(region_rect, rect):
                raise AssertionError(f"foreign boxed topic {key!r} intersects a region")
    if page.regions and member_ids != set(topic_rects):
        raise AssertionError("grouped boxed page has an unowned topic")


def _box_metadata(item: PlacedTopic) -> dict[str, object]:
    return {
        "id": item.measured.topic.topic_id,
        "group_id": item.group_id,
        "emphasis": item.measured.topic.emphasis,
        "x": item.x,
        "y": item.y,
        "width": item.variant.width,
        "height": item.variant.height,
    }


def _region_metadata(region: Region) -> dict[str, object]:
    return {
        "id": region.group.group_id,
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
        "segment_index": region.segment_index,
        "segment_count": region.segment_count,
        "topic_ids": [item.measured.topic.topic_id for item in region.topics],
    }


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    document = _normalize(data)
    headings = _header(document, options.max_width)
    header_height = len(headings) + 2
    if header_height >= options.max_height:
        raise FitError("boxed document header leaves no content rows")
    pages = (
        _grouped_pages(document, options, header_height)
        if document.groups
        else _ungrouped_pages(document, options, header_height)
    )
    if options.single_card and len(pages) != 1:
        raise FitError("boxed note requires multiple cards")
    cards: list[CardDraft] = []
    y = 0
    for index, page in enumerate(pages):
        _validate_page_geometry(page, options)
        text = _paint(document, page, headings, options)
        cards.append(
            CardDraft(
                f"boxed-{document.document_id}-{index:03d}",
                text,
                options.max_width,
                page.used_height,
                0,
                y,
                {
                    "document_id": document.document_id,
                    "card_index": index + 1,
                    "card_count": len(pages),
                    "topic_ids": [item.measured.topic.topic_id for item in page.topics],
                    "boxes": [_box_metadata(item) for item in page.topics],
                    "regions": [_region_metadata(region) for region in page.regions],
                },
            )
        )
        y += page.used_height + CARD_GAP
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


if __name__ == "__main__":
    raise SystemExit(run_renderer(RENDERER, render))
