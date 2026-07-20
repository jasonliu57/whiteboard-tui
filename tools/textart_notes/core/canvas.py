"""A collision-aware terminal-cell canvas with mergeable line segments."""

from __future__ import annotations

from dataclasses import dataclass

from .cell_width import char_width, is_mark_character, tab_advance
from .themes import EAST, NORTH, SOUTH, WEST, Theme, get_theme


class CanvasError(ValueError):
    """An out-of-bounds or cell-collision drawing operation."""


_CONT = object()


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class Canvas:
    def __init__(self, width: int, height: int, theme: str | Theme = "unicode-light") -> None:
        if width <= 0 or height <= 0:
            raise ValueError("canvas dimensions must be positive")
        self.width = width
        self.height = height
        self.theme = get_theme(theme) if isinstance(theme, str) else theme
        self._text: list[list[str | object | None]] = [
            [None for _ in range(width)] for _ in range(height)
        ]
        self._lines: list[list[int]] = [[0 for _ in range(width)] for _ in range(height)]

    def _check(self, x: int, y: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise CanvasError(f"cell ({x}, {y}) is outside {self.width}x{self.height}")

    def put_text(self, x: int, y: int, text: str, *, overwrite: bool = False) -> int:
        """Place one line and return the next x coordinate."""

        self._check(x, y)
        column = x
        anchor: int | None = None
        for character in text:
            if character in "\n\r":
                raise CanvasError("put_text accepts one line only")
            if character == "\t":
                spaces = tab_advance(column)
                for _ in range(spaces):
                    column = self.put_text(column, y, " ", overwrite=overwrite)
                anchor = None
                continue
            mark = is_mark_character(character)
            if mark and anchor is None:
                raise CanvasError("combining character has no preceding anchor")
            cells = char_width(character)
            if cells == 0:
                if anchor is None:
                    raise CanvasError("combining character has no preceding anchor")
                existing = self._text[y][anchor]
                if not isinstance(existing, str):
                    raise CanvasError("combining character anchor is unavailable")
                self._text[y][anchor] = existing + character
                continue
            if column + cells > self.width:
                raise CanvasError("text extends beyond the canvas")
            for target in range(column, column + cells):
                existing = self._text[y][target]
                if existing is not None and not overwrite:
                    kind = "wide continuation" if existing is _CONT else "text"
                    raise CanvasError(f"cannot overwrite {kind} at ({target}, {y})")
            if overwrite:
                self._clear_text_cell(column, y)
                if cells == 2:
                    self._clear_text_cell(column + 1, y)
            self._text[y][column] = character
            self._lines[y][column] = 0
            if cells == 2:
                self._text[y][column + 1] = _CONT
                self._lines[y][column + 1] = 0
            anchor = None if character.isspace() else column
            column += cells
        return column

    def _clear_text_cell(self, x: int, y: int) -> None:
        existing = self._text[y][x]
        if existing is _CONT:
            if x and isinstance(self._text[y][x - 1], str):
                self._text[y][x - 1] = None
        elif isinstance(existing, str) and x + 1 < self.width and self._text[y][x + 1] is _CONT:
            self._text[y][x + 1] = None
        self._text[y][x] = None

    def _connect(self, first: Point, second: Point) -> None:
        self._check(first.x, first.y)
        self._check(second.x, second.y)
        dx, dy = second.x - first.x, second.y - first.y
        direction = {
            (1, 0): (EAST, WEST),
            (-1, 0): (WEST, EAST),
            (0, 1): (SOUTH, NORTH),
            (0, -1): (NORTH, SOUTH),
        }.get((dx, dy))
        if direction is None:
            raise CanvasError("line path must move one orthogonal cell at a time")
        for point in (first, second):
            if self._text[point.y][point.x] is not None:
                raise CanvasError(f"line collides with text at ({point.x}, {point.y})")
        self._lines[first.y][first.x] |= direction[0]
        self._lines[second.y][second.x] |= direction[1]

    def draw_path(self, points: list[tuple[int, int]] | tuple[tuple[int, int], ...]) -> None:
        if len(points) < 2:
            raise CanvasError("a path needs at least two points")
        expanded: list[Point] = [Point(*points[0])]
        for target_xy in points[1:]:
            target = Point(*target_xy)
            current = expanded[-1]
            if current.x != target.x and current.y != target.y:
                raise CanvasError("path segments must be orthogonal")
            step_x = 0 if current.x == target.x else (1 if target.x > current.x else -1)
            step_y = 0 if current.y == target.y else (1 if target.y > current.y else -1)
            while current != target:
                current = Point(current.x + step_x, current.y + step_y)
                expanded.append(current)
        for first, second in zip(expanded, expanded[1:]):
            self._connect(first, second)

    def draw_box(self, x: int, y: int, width: int, height: int) -> None:
        if width < 2 or height < 2:
            raise CanvasError("a box needs width and height of at least two cells")
        right, bottom = x + width - 1, y + height - 1
        self._check(x, y)
        self._check(right, bottom)
        self.draw_path(((x, y), (right, y), (right, bottom), (x, bottom), (x, y)))

    def to_lines(self, *, trim_right: bool = True) -> list[str]:
        output: list[str] = []
        for y in range(self.height):
            pieces: list[str] = []
            for x in range(self.width):
                text = self._text[y][x]
                if text is _CONT:
                    continue
                if isinstance(text, str):
                    pieces.append(text)
                else:
                    pieces.append(self.theme.line(self._lines[y][x]) if self._lines[y][x] else " ")
            line = "".join(pieces)
            output.append(line.rstrip() if trim_right else line)
        return output

    def to_text(self, *, trim_right: bool = True) -> str:
        return "\n".join(self.to_lines(trim_right=trim_right))
