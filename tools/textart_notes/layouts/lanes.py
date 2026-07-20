"""Shared deterministic width and synchronized-band helpers for lane layouts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..core.models import FitError


@dataclass(frozen=True)
class LaneItem:
    key: str
    height: int


@dataclass(frozen=True)
class LaneBand:
    ranges: tuple[tuple[int, int], ...]
    content_height: int


def allocate_lane_widths(
    total_width: int,
    count: int,
    *,
    gutter: int = 1,
    minimum: int = 1,
) -> tuple[int, ...]:
    """Allocate equal lane widths with stable left-to-right remainders."""

    if count < 1 or total_width < 1 or gutter < 0 or minimum < 1:
        raise ValueError("invalid lane geometry")
    usable = total_width - gutter * (count - 1)
    base, remainder = divmod(usable, count)
    if base < minimum:
        raise FitError("lane group cannot preserve its minimum width")
    return tuple(base + (1 if index < remainder else 0) for index in range(count))


def lane_positions(widths: Sequence[int], *, gutter: int = 1) -> tuple[int, ...]:
    if not widths or any(width < 1 for width in widths) or gutter < 0:
        raise ValueError("invalid lane widths")
    positions: list[int] = []
    cursor = 0
    for width in widths:
        positions.append(cursor)
        cursor += width + gutter
    return tuple(positions)


def synchronized_bands(
    lanes: Sequence[Sequence[LaneItem]],
    capacity: int,
    *,
    item_gap: int = 1,
    empty_height: int = 1,
) -> tuple[LaneBand, ...]:
    """Greedily advance each lane while keeping every item indivisible."""

    if not lanes:
        raise ValueError("at least one lane is required")
    if capacity < 1 or item_gap < 0 or empty_height < 1:
        raise ValueError("invalid synchronized-band geometry")
    for lane in lanes:
        for item in lane:
            if item.height < 1:
                raise ValueError("lane item heights must be positive")
            if item.height > capacity:
                raise FitError(f"indivisible lane item {item.key!r} exceeds band capacity")
    cursors = [0] * len(lanes)
    bands: list[LaneBand] = []
    first = True
    while first or any(cursor < len(lane) for cursor, lane in zip(cursors, lanes)):
        first = False
        ranges: list[tuple[int, int]] = []
        heights: list[int] = []
        for index, lane in enumerate(lanes):
            start = cursors[index]
            end = start
            used = 0
            while end < len(lane):
                cost = lane[end].height + (item_gap if used else 0)
                if used + cost > capacity:
                    break
                used += cost
                end += 1
            if start < len(lane) and end == start:
                raise FitError(f"indivisible lane item {lane[start].key!r} cannot fit")
            cursors[index] = end
            ranges.append((start, end))
            heights.append(used if used else empty_height)
        bands.append(LaneBand(tuple(ranges), max(heights)))
    return tuple(bands)
