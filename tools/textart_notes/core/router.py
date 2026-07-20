"""Small deterministic orthogonal-routing primitives."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Collection


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def contains(self, point: tuple[int, int], *, interior_only: bool = False) -> bool:
        px, py = point
        inset = 1 if interior_only else 0
        return (
            self.x + inset <= px < self.x + self.width - inset
            and self.y + inset <= py < self.y + self.height - inset
        )


def expand_path(vertices: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not vertices:
        return []
    cells = [vertices[0]]
    for target in vertices[1:]:
        x, y = cells[-1]
        tx, ty = target
        if x != tx and y != ty:
            raise ValueError("route segments must be orthogonal")
        dx = 0 if x == tx else (1 if tx > x else -1)
        dy = 0 if y == ty else (1 if ty > y else -1)
        while (x, y) != target:
            x, y = x + dx, y + dy
            cells.append((x, y))
    return cells


def orthogonal_route(
    start: tuple[int, int],
    end: tuple[int, int],
    obstacles: tuple[Rect, ...] = (),
) -> list[tuple[int, int]]:
    """Choose a deterministic one- or two-bend route avoiding interiors.

    More complex graph styles may add lanes around this primitive; the shared
    invariant is that returned vertices are orthogonal and deterministic.
    """

    if start[0] == end[0] or start[1] == end[1]:
        candidates = [[start, end]]
    else:
        candidates = [
            [start, (end[0], start[1]), end],
            [start, (start[0], end[1]), end],
        ]
    for candidate in candidates:
        cells = expand_path(candidate)
        if not any(rect.contains(cell, interior_only=True) for rect in obstacles for cell in cells[1:-1]):
            return candidate
    # Deterministically search horizontal escape lanes above, then below.
    top = min([start[1], end[1], *(rect.y for rect in obstacles)]) - 1
    bottom = max([start[1], end[1], *(rect.y + rect.height - 1 for rect in obstacles)]) + 1
    for lane in (top, bottom):
        candidate = [start, (start[0], lane), (end[0], lane), end]
        cells = expand_path(candidate)
        if not any(rect.contains(cell, interior_only=True) for rect in obstacles for cell in cells[1:-1]):
            return candidate
    raise ValueError("no orthogonal route found")


def shortest_grid_route(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    width: int,
    height: int,
    blocked: Collection[tuple[int, int]] = (),
    monotone_vertical: bool = False,
) -> tuple[tuple[int, int], ...]:
    """Return a deterministic shortest cell-by-cell orthogonal route.

    Cost is cell count, then bends.  With ``monotone_vertical`` the path may
    move only toward the end row (or horizontally) and stays between endpoint
    rows.  Endpoints are always allowed even if included in ``blocked``.
    """

    if width < 1 or height < 1:
        raise ValueError("route bounds must be positive")
    if not all(0 <= x < width and 0 <= y < height for x, y in (start, end)):
        raise ValueError("route endpoint is outside bounds")
    obstacles = set(blocked) - {start, end}
    vertical_step = 0 if start[1] == end[1] else (1 if end[1] > start[1] else -1)
    horizontal_step = 0 if start[0] == end[0] else (1 if end[0] > start[0] else -1)
    directions: list[tuple[int, int, str]] = []
    if vertical_step:
        directions.append((0, vertical_step, "v"))
    if horizontal_step:
        directions.append((horizontal_step, 0, "h"))
        directions.append((-horizontal_step, 0, "h"))
    else:
        directions.extend(((1, 0, "h"), (-1, 0, "h")))
    if not monotone_vertical and vertical_step:
        directions.append((0, -vertical_step, "v"))
    if not directions:
        return (start,)

    start_state = (start[0], start[1], "")
    best: dict[tuple[int, int, str], tuple[int, int]] = {start_state: (0, 0)}
    previous: dict[tuple[int, int, str], tuple[int, int, str]] = {}
    queue: list[tuple[int, int, int, tuple[int, int, str]]] = [(0, 0, 0, start_state)]
    sequence = 0
    final: tuple[int, int, str] | None = None
    lower_y, upper_y = sorted((start[1], end[1]))
    while queue:
        steps, bends, _, state = heapq.heappop(queue)
        if best.get(state) != (steps, bends):
            continue
        x, y, prior = state
        if (x, y) == end:
            final = state
            break
        for dx, dy, direction in directions:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if monotone_vertical and not lower_y <= ny <= upper_y:
                continue
            if (nx, ny) in obstacles:
                continue
            cost = (steps + 1, bends + int(bool(prior) and prior != direction))
            next_state = (nx, ny, direction)
            if next_state in best and best[next_state] <= cost:
                continue
            best[next_state] = cost
            previous[next_state] = state
            sequence += 1
            heapq.heappush(queue, (cost[0], cost[1], sequence, next_state))
    if final is None:
        raise ValueError(f"no bounded orthogonal route from {start} to {end}")
    path: list[tuple[int, int]] = []
    state = final
    while True:
        path.append((state[0], state[1]))
        if state == start_state:
            break
        state = previous[state]
    path.reverse()
    if len(set(path)) != len(path):
        raise ValueError("orthogonal router produced a repeated cell")
    return tuple(path)


def validate_cell_route(
    path: Collection[tuple[int, int]],
    *,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> None:
    cells = tuple(path)
    if not cells:
        raise ValueError("route is empty")
    if start is not None and cells[0] != start:
        raise ValueError("route start does not match its port")
    if end is not None and cells[-1] != end:
        raise ValueError("route end does not match its port")
    if len(set(cells)) != len(cells):
        raise ValueError("route repeats a cell")
    if any(abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1 for a, b in zip(cells, cells[1:])):
        raise ValueError("route contains non-adjacent cells")
