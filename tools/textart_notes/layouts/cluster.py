"""Deterministic shelf packing for measured cluster rectangles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..core.models import FitError


@dataclass(frozen=True)
class ClusterSize:
    width: int
    height: int


@dataclass(frozen=True)
class ClusterItem:
    """One item with optional physical-column phase variants.

    ``variants[(x + phase_offset) % len(variants)]`` is selected at a
    candidate x coordinate.  A single variant is sufficient for ordinary
    placement-independent rectangles.
    """

    key: str
    variants: tuple[ClusterSize, ...]
    phase_offset: int = 0

    def size_at(self, x: int) -> ClusterSize:
        if not self.variants:
            raise ValueError(f"cluster item {self.key!r} has no size variants")
        return self.variants[(x + self.phase_offset) % len(self.variants)]


@dataclass(frozen=True)
class ClusterPlacement:
    key: str
    x: int
    y: int
    width: int
    height: int
    shelf: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class ClusterLayout:
    placements: tuple[ClusterPlacement, ...]
    width: int
    height: int


def rectangles_overlap(first: ClusterPlacement, second: ClusterPlacement) -> bool:
    return not (
        first.right <= second.x
        or second.right <= first.x
        or first.bottom <= second.y
        or second.bottom <= first.y
    )


def pack_shelves(
    items: Sequence[ClusterItem],
    *,
    max_width: int,
    origin_x: int = 0,
    origin_y: int = 0,
    gutter_x: int = 2,
    gutter_y: int = 1,
) -> ClusterLayout:
    """Pack ordered, measured items into stable first-fit shelf rows."""

    if max_width < 1 or origin_x < 0 or origin_y < 0 or gutter_x < 0 or gutter_y < 0:
        raise ValueError("invalid cluster geometry")
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys):
        raise ValueError("cluster item keys must be unique")
    if any(
        size.width < 1 or size.height < 1
        for item in items
        for size in item.variants
    ):
        raise ValueError("cluster sizes must be positive")

    placements: list[ClusterPlacement] = []
    x = origin_x
    y = origin_y
    shelf = 0
    shelf_height = 0
    right_limit = origin_x + max_width
    for item in items:
        size = item.size_at(x)
        if x != origin_x and x + size.width > right_limit:
            x = origin_x
            y += shelf_height + gutter_y
            shelf += 1
            shelf_height = 0
            size = item.size_at(x)
        if x + size.width > right_limit:
            raise FitError(f"cluster item {item.key!r} is wider than an empty shelf")
        placements.append(
            ClusterPlacement(item.key, x, y, size.width, size.height, shelf)
        )
        shelf_height = max(shelf_height, size.height)
        x += size.width + gutter_x

    if not placements:
        return ClusterLayout((), 0, 0)
    width = max(item.right for item in placements) - origin_x
    height = max(item.bottom for item in placements) - origin_y
    return ClusterLayout(tuple(placements), width, height)
