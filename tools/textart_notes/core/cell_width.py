"""Terminal-cell measurement without external wcwidth dependencies."""

from __future__ import annotations

from .unicode_width_table import (
    CONTROL_INTERVALS,
    MARK_INTERVALS,
    WIDE_INTERVALS,
    WHITESPACE_INTERVALS,
    ZERO_WIDTH_INTERVALS,
    interval_contains,
)

DEFAULT_TAB_STOP = 4


def is_mark_character(character: str) -> bool:
    """Return whether a code point belongs to an anchored Unicode mark cluster."""

    if len(character) != 1:
        raise ValueError("is_mark_character expects exactly one code point")
    return interval_contains(ord(character), MARK_INTERVALS)


def is_control_character(character: str) -> bool:
    if len(character) != 1:
        raise ValueError("is_control_character expects exactly one code point")
    return interval_contains(ord(character), CONTROL_INTERVALS)


def is_whitespace_character(character: str) -> bool:
    if len(character) != 1:
        raise ValueError("is_whitespace_character expects exactly one code point")
    return interval_contains(ord(character), WHITESPACE_INTERVALS)


def char_width(character: str) -> int:
    """Return the terminal width of one Unicode code point.

    The renderer contract deliberately uses the stable East Asian Width model
    instead of querying the active terminal. Ambiguous-width characters count
    as one cell in every renderer.
    """

    if len(character) != 1:
        raise ValueError("char_width expects exactly one code point")
    if character in "\n\r\t":
        raise ValueError("control whitespace needs position-aware handling")
    codepoint = ord(character)
    if interval_contains(codepoint, CONTROL_INTERVALS):
        raise ValueError(f"unsupported control character U+{codepoint:04X}")
    if interval_contains(codepoint, ZERO_WIDTH_INTERVALS):
        return 0
    return 2 if interval_contains(codepoint, WIDE_INTERVALS) else 1


def tab_advance(column: int, tab_stop: int = DEFAULT_TAB_STOP) -> int:
    if tab_stop <= 0:
        raise ValueError("tab_stop must be positive")
    return tab_stop - (column % tab_stop)


def text_width(text: str, *, start: int = 0, tab_stop: int = DEFAULT_TAB_STOP) -> int:
    """Measure a single logical line in terminal cells."""

    column = start
    for character in text:
        if character in "\n\r":
            raise ValueError("text_width accepts one line only")
        if character == "\t":
            column += tab_advance(column, tab_stop)
        else:
            column += char_width(character)
    return column - start


def validate_combining_anchors(text: str) -> None:
    """Reject combining marks that have no visible glyph anchor on the line."""

    anchored = False
    for character in text:
        if character == "\t" or is_whitespace_character(character):
            anchored = False
            continue
        if is_control_character(character):
            raise ValueError(f"unsupported control character U+{ord(character):04X}")
        if is_mark_character(character):
            if not anchored:
                raise ValueError("combining character has no preceding anchor")
        else:
            anchored = True


def cell_clusters(text: str) -> tuple[str, ...]:
    """Return indivisible base-plus-mark clusters while preserving whitespace.

    All Unicode mark categories stay with their visible anchor, including
    class-zero spacing marks (``Mc``) that consume terminal cells.
    """

    validate_combining_anchors(text)
    clusters: list[str] = []
    for character in text:
        if is_mark_character(character):
            clusters[-1] += character
        else:
            clusters.append(character)
    return tuple(clusters)


def expand_tabs(text: str, *, start: int = 0, tab_stop: int = DEFAULT_TAB_STOP) -> str:
    """Expand tabs using terminal-cell positions, preserving all other text."""

    pieces: list[str] = []
    column = start
    for character in text:
        if character in "\n\r":
            raise ValueError("expand_tabs accepts one line only")
        if character == "\t":
            count = tab_advance(column, tab_stop)
            pieces.append(" " * count)
            column += count
        else:
            pieces.append(character)
            column += char_width(character)
    return "".join(pieces)


def split_prefix(text: str, max_cells: int, *, start: int = 0) -> tuple[str, str]:
    """Split at the largest code-point boundary that fits ``max_cells``.

    Combining marks remain attached to the preceding visible code point. A
    wide character is never divided across the boundary.
    """

    if max_cells < 0:
        raise ValueError("max_cells cannot be negative")
    validate_combining_anchors(text)
    expanded = expand_tabs(text, start=start)
    used = 0
    split_at = 0
    for cluster in cell_clusters(expanded):
        width = text_width(cluster, start=start + used)
        if width and used + width > max_cells:
            break
        used += width
        split_at += len(cluster)
    return expanded[:split_at], expanded[split_at:]


def pad_cells(text: str, width: int, *, align: str = "left") -> str:
    """Pad a line to exactly ``width`` terminal cells."""

    current = text_width(text)
    if current > width:
        raise ValueError(f"text width {current} exceeds target width {width}")
    remaining = width - current
    if align == "left":
        return text + " " * remaining
    if align == "right":
        return " " * remaining + text
    if align == "center":
        left = remaining // 2
        return " " * left + text + " " * (remaining - left)
    raise ValueError(f"unknown alignment: {align}")
