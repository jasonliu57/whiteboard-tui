"""Deterministic terminal-cell placement for spine-and-branch diagrams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SpineItem:
    """One already-measured branch block above or below the shared spine."""

    key: str
    side: str
    width: int
    height: int


@dataclass(frozen=True)
class SpinePlacement:
    key: str
    side: str
    x: int
    y: int
    width: int
    height: int
    joint_x: int


@dataclass(frozen=True)
class SpineLayout:
    placements: tuple[SpinePlacement, ...]
    spine_y: int
    spine_width: int
    effect_x: int
    effect_y: int
    effect_width: int
    effect_height: int
    width: int
    height: int


def place_spine(
    items: Sequence[SpineItem],
    *,
    arrow_width: int,
    effect_width: int,
    effect_height: int,
    effect_entry_row: int,
) -> SpineLayout:
    """Place ordered branch rectangles around one horizontal result spine.

    The caller owns text measurement, painting, pagination, and branch
    semantics. This primitive preserves input order, bottom-aligns top items,
    top-aligns bottom items, and centers the effect's declared entry row on the
    spine. Rectangles never overlap because every item owns one consecutive
    horizontal segment.
    """

    if not items:
        raise ValueError("spine layout requires at least one item")
    if arrow_width < 1:
        raise ValueError("arrow_width must be positive")
    if effect_width < 1 or effect_height < 1:
        raise ValueError("effect dimensions must be positive")
    if not 0 <= effect_entry_row < effect_height:
        raise ValueError("effect_entry_row is outside the effect rectangle")

    seen: set[str] = set()
    normalized: list[SpineItem] = []
    for item in items:
        if not item.key or item.key in seen:
            raise ValueError(f"spine item key must be non-empty and unique: {item.key!r}")
        seen.add(item.key)
        if item.side not in {"top", "bottom"}:
            raise ValueError(f"spine item {item.key!r} has invalid side {item.side!r}")
        if item.width < 1 or item.height < 1:
            raise ValueError(f"spine item {item.key!r} dimensions must be positive")
        normalized.append(item)

    top_height = max(
        (item.height for item in normalized if item.side == "top"), default=0
    )
    bottom_height = max(
        (item.height for item in normalized if item.side == "bottom"), default=0
    )
    above = max(top_height, effect_entry_row)
    below = max(bottom_height, effect_height - effect_entry_row - 1)
    spine_y = above

    cursor = 0
    placements: list[SpinePlacement] = []
    for item in normalized:
        y = spine_y - item.height if item.side == "top" else spine_y + 1
        placements.append(
            SpinePlacement(
                key=item.key,
                side=item.side,
                x=cursor,
                y=y,
                width=item.width,
                height=item.height,
                joint_x=cursor + item.width - 1,
            )
        )
        cursor += item.width

    effect_x = cursor + arrow_width
    effect_y = spine_y - effect_entry_row
    return SpineLayout(
        placements=tuple(placements),
        spine_y=spine_y,
        spine_width=cursor,
        effect_x=effect_x,
        effect_y=effect_y,
        effect_width=effect_width,
        effect_height=effect_height,
        width=effect_x + effect_width,
        height=above + 1 + below,
    )
