"""Terminal-friendly bidirectional radial hierarchy layout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..core.router import Rect, expand_path
from .hierarchy import HierarchyFacts


@dataclass(frozen=True)
class RadialSize:
    width: int
    height: int


@dataclass(frozen=True)
class RadialPlacement:
    key: str
    x: int
    y: int
    width: int
    height: int
    depth: int
    side: str

    @property
    def right(self) -> int:
        return self.x + self.width - 1

    @property
    def bottom(self) -> int:
        return self.y + self.height - 1

    @property
    def port_y(self) -> int:
        return self.y + self.height // 2

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class RadialEdge:
    parent: str
    child: str
    vertices: tuple[tuple[int, int], ...]

    @property
    def cells(self) -> tuple[tuple[int, int], ...]:
        return tuple(expand_path(list(self.vertices)))


@dataclass(frozen=True)
class RadialScene:
    placements: tuple[RadialPlacement, ...]
    edges: tuple[RadialEdge, ...]
    width: int
    height: int
    anchor_id: str
    top_level_sides: Mapping[str, str]


def layout_radial(
    facts: HierarchyFacts,
    children: Mapping[str, Sequence[str]],
    sizes: Mapping[str, RadialSize],
    *,
    anchor_id: str,
    summary_children: Sequence[str] | None = None,
    ring_gap: int = 5,
    vertical_gap: int = 1,
) -> RadialScene:
    """Place one complete subtree or a one-ring summary around its anchor."""

    if ring_gap < 3 or vertical_gap < 0:
        raise ValueError("invalid radial gutters")
    if anchor_id not in sizes:
        raise ValueError(f"missing radial size for {anchor_id!r}")
    if summary_children is None:
        visible_ids = facts.subtree_ids[anchor_id]
        visible = set(visible_ids)
        local_children = {
            key: tuple(child for child in children[key] if child in visible)
            for key in visible_ids
        }
        first_children = tuple(children[anchor_id])
    else:
        first_children = tuple(summary_children)
        if len(set(first_children)) != len(first_children):
            raise ValueError("radial summary children must be unique")
        if any(child not in children[anchor_id] for child in first_children):
            raise ValueError("radial summary child is not an immediate child")
        visible_ids = (anchor_id,) + first_children
        local_children = {key: () for key in visible_ids}
        local_children[anchor_id] = first_children
    if any(key not in sizes for key in visible_ids):
        raise ValueError("radial size map is incomplete")
    if any(sizes[key].width < 3 or sizes[key].height < 3 for key in visible_ids):
        raise ValueError("radial nodes need at least 3x3 cells")

    local_depth = {anchor_id: 0}
    side = {anchor_id: "center"}
    top_sides: dict[str, str] = {}

    def mark(key: str, level: int, branch_side: str) -> None:
        local_depth[key] = level
        side[key] = branch_side
        for child in local_children[key]:
            mark(child, level + 1, branch_side)

    for child in first_children:
        branch_side = "right" if facts.sibling_index[child] % 2 == 0 else "left"
        top_sides[child] = branch_side
        mark(child, 1, branch_side)

    max_depth = max(local_depth.values(), default=0)
    ring_width: dict[tuple[str, int], int] = {}
    for key in visible_ids:
        if local_depth[key]:
            index = (side[key], local_depth[key])
            ring_width[index] = max(ring_width.get(index, 0), sizes[key].width)

    x_by_key = {anchor_id: 0}
    right_x: dict[int, int] = {}
    cursor = sizes[anchor_id].width + ring_gap
    for level in range(1, max_depth + 1):
        if ("right", level) in ring_width:
            right_x[level] = cursor
            cursor += ring_width[("right", level)] + ring_gap
    left_right: dict[int, int] = {}
    cursor = -ring_gap - 1
    for level in range(1, max_depth + 1):
        if ("left", level) in ring_width:
            left_right[level] = cursor
            cursor -= ring_width[("left", level)] + ring_gap
    for key in visible_ids:
        if key == anchor_id:
            continue
        if side[key] == "right":
            x_by_key[key] = right_x[local_depth[key]]
        else:
            x_by_key[key] = left_right[local_depth[key]] - sizes[key].width + 1

    band_cache: dict[str, int] = {}

    def band_height(key: str) -> int:
        if key in band_cache:
            return band_cache[key]
        descendants = local_children[key]
        nested = (
            sum(band_height(child) for child in descendants)
            + vertical_gap * max(0, len(descendants) - 1)
        )
        result = max(sizes[key].height, nested)
        band_cache[key] = result
        return result

    by_side = {
        current: [child for child in first_children if top_sides[child] == current]
        for current in ("right", "left")
    }

    def stack_height(keys: Sequence[str]) -> int:
        return sum(band_height(key) for key in keys) + vertical_gap * max(0, len(keys) - 1)

    total_height = max(
        sizes[anchor_id].height,
        stack_height(by_side["right"]),
        stack_height(by_side["left"]),
    )
    y_by_key = {anchor_id: (total_height - sizes[anchor_id].height) // 2}

    def assign(key: str, top: int) -> None:
        band = band_height(key)
        y_by_key[key] = top + (band - sizes[key].height) // 2
        nested = local_children[key]
        if nested:
            child_top = top + (band - stack_height(nested)) // 2
            for child in nested:
                assign(child, child_top)
                child_top += band_height(child) + vertical_gap

    for current in ("right", "left"):
        keys = by_side[current]
        top = (total_height - stack_height(keys)) // 2 if keys else 0
        for key in keys:
            assign(key, top)
            top += band_height(key) + vertical_gap

    provisional = [
        RadialPlacement(
            key,
            x_by_key[key],
            y_by_key[key],
            sizes[key].width,
            sizes[key].height,
            local_depth[key],
            side[key],
        )
        for key in visible_ids
    ]
    min_x = min(item.x for item in provisional)
    min_y = min(item.y for item in provisional)
    placements = tuple(
        RadialPlacement(
            item.key,
            item.x - min_x,
            item.y - min_y,
            item.width,
            item.height,
            item.depth,
            item.side,
        )
        for item in provisional
    )
    placed = {item.key: item for item in placements}
    edges: list[RadialEdge] = []
    for parent in visible_ids:
        parent_box = placed[parent]
        for current in ("right", "left"):
            nested = [child for child in local_children[parent] if side[child] == current]
            if not nested:
                continue
            if current == "right":
                source = (parent_box.right + 1, parent_box.port_y)
                spine = min(placed[child].x for child in nested) - 2
                for child in nested:
                    target = (placed[child].x - 1, placed[child].port_y)
                    edges.append(RadialEdge(parent, child, (source, (spine, source[1]), (spine, target[1]), target)))
            else:
                source = (parent_box.x - 1, parent_box.port_y)
                spine = max(placed[child].right for child in nested) + 2
                for child in nested:
                    target = (placed[child].right + 1, placed[child].port_y)
                    edges.append(RadialEdge(parent, child, (source, (spine, source[1]), (spine, target[1]), target)))

    width = max(item.right for item in placements) + 1
    height = max(item.bottom for item in placements) + 1
    for index, item in enumerate(placements):
        for other in placements[index + 1 :]:
            if not (
                item.right < other.x
                or other.right < item.x
                or item.bottom < other.y
                or other.bottom < item.y
            ):
                raise ValueError(f"radial nodes overlap: {item.key!r}, {other.key!r}")
    for edge in edges:
        if any(item.rect.contains(cell) for cell in edge.cells for item in placements):
            raise ValueError(f"radial edge {edge.parent!r}->{edge.child!r} enters a node")
        if any(not (0 <= x < width and 0 <= y < height) for x, y in edge.cells):
            raise ValueError("radial edge leaves the natural extent")
    return RadialScene(placements, tuple(edges), width, height, anchor_id, top_sides)
