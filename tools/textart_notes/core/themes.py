"""Glyph themes and line-junction lookup tables."""

from __future__ import annotations

from dataclasses import dataclass

from .models import THEME_NAMES, InputError

NORTH, EAST, SOUTH, WEST = 1, 2, 4, 8


@dataclass(frozen=True)
class Theme:
    name: str
    line_glyphs: dict[int, str]
    arrow_right: str
    arrow_down: str
    bullet: str
    checkbox_open: str
    checkbox_done: str

    def line(self, mask: int) -> str:
        return self.line_glyphs.get(mask, "+" if self.name == "ascii" else "┼")


_ASCII = {
    0: " ",
    NORTH: "|", SOUTH: "|", NORTH | SOUTH: "|",
    EAST: "-", WEST: "-", EAST | WEST: "-",
}
for _mask in range(1, 16):
    _ASCII.setdefault(_mask, "+")

_LIGHT = {
    0: " ",
    NORTH: "│", SOUTH: "│", NORTH | SOUTH: "│",
    EAST: "─", WEST: "─", EAST | WEST: "─",
    EAST | SOUTH: "┌", SOUTH | WEST: "┐",
    NORTH | EAST: "└", NORTH | WEST: "┘",
    NORTH | EAST | SOUTH: "├", NORTH | SOUTH | WEST: "┤",
    EAST | SOUTH | WEST: "┬", NORTH | EAST | WEST: "┴",
    NORTH | EAST | SOUTH | WEST: "┼",
}

_RICH = {
    0: " ",
    NORTH: "║", SOUTH: "║", NORTH | SOUTH: "║",
    EAST: "═", WEST: "═", EAST | WEST: "═",
    EAST | SOUTH: "╔", SOUTH | WEST: "╗",
    NORTH | EAST: "╚", NORTH | WEST: "╝",
    NORTH | EAST | SOUTH: "╠", NORTH | SOUTH | WEST: "╣",
    EAST | SOUTH | WEST: "╦", NORTH | EAST | WEST: "╩",
    NORTH | EAST | SOUTH | WEST: "╬",
}

THEMES = {
    "ascii": Theme("ascii", _ASCII, "->", "v", "*", "[ ]", "[x]"),
    "unicode-light": Theme("unicode-light", _LIGHT, "→", "↓", "•", "☐", "☑"),
    "unicode-rich": Theme("unicode-rich", _RICH, "⇒", "⇓", "◆", "□", "■"),
}


def get_theme(name: str) -> Theme:
    try:
        return THEMES[name]
    except KeyError as error:
        choices = ", ".join(THEME_NAMES)
        raise InputError(f"unknown theme {name!r}; expected one of: {choices}") from error
