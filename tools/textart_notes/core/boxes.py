"""High-level framed text helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .canvas import Canvas
from .cell_width import pad_cells, text_width
from .themes import EAST, NORTH, SOUTH, WEST, get_theme
from .wrap import wrap_line


@dataclass(frozen=True)
class FrameGlyphs:
    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    horizontal: str
    vertical: str
    left_join: str
    right_join: str


def frame_glyphs(theme: str) -> FrameGlyphs:
    selected = get_theme(theme)
    return FrameGlyphs(
        selected.line(EAST | SOUTH),
        selected.line(SOUTH | WEST),
        selected.line(NORTH | EAST),
        selected.line(NORTH | WEST),
        selected.line(EAST | WEST),
        selected.line(NORTH | SOUTH),
        selected.line(NORTH | EAST | SOUTH),
        selected.line(NORTH | SOUTH | WEST),
    )


def frame_rule(width: int, theme: str, *, position: str, label: str = "") -> str:
    """Return a top, middle, or bottom frame row of exactly ``width`` cells."""

    if width < 2:
        raise ValueError("frame width must be at least two")
    glyphs = frame_glyphs(theme)
    ends = {
        "top": (glyphs.top_left, glyphs.top_right),
        "middle": (glyphs.left_join, glyphs.right_join),
        "bottom": (glyphs.bottom_left, glyphs.bottom_right),
    }
    try:
        left, right = ends[position]
    except KeyError as error:
        raise ValueError(f"unknown frame rule position: {position}") from error
    decoration = f" {label} " if label else ""
    remaining = width - 2 - text_width(decoration)
    if remaining < 0:
        raise ValueError(f"frame label {label!r} does not fit width {width}")
    return left + decoration + glyphs.horizontal * remaining + right


def frame_row(width: int, theme: str, content: str = "", *, padding: int = 1) -> str:
    """Frame and pad one measured content row."""

    if padding < 0:
        raise ValueError("padding cannot be negative")
    glyphs = frame_glyphs(theme)
    available = width - 2 - padding * 2
    if available < 0:
        raise ValueError("frame is too narrow for its padding")
    return glyphs.vertical + " " * padding + pad_cells(content, available) + " " * padding + glyphs.vertical


def boxed_text(
    title: str,
    body: str,
    *,
    width: int,
    theme: str = "unicode-light",
    padding: int = 1,
) -> str:
    """Render a titled box; height grows to fit the wrapped body."""

    if width < 4 + padding * 2:
        raise ValueError("box is too narrow")
    inner_width = width - 2 - padding * 2
    body_lines: list[str] = []
    for logical in body.splitlines() or [""]:
        body_lines.extend(wrap_line(logical, inner_width))
    height = len(body_lines) + 3
    canvas = Canvas(width, height, theme)
    canvas.draw_box(0, 0, width, height)
    if title:
        canvas.put_text(2, 0, f" {title} ", overwrite=True)
    for row, line in enumerate(body_lines, start=2):
        canvas.put_text(1 + padding, row, pad_cells(line, inner_width))
    return canvas.to_text()
