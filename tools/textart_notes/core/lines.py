"""Compositional helpers for already-rendered text lines."""

from __future__ import annotations

from .cell_width import pad_cells, text_width


def join_columns(columns: list[list[str]], widths: list[int], separator: str = " │ ") -> list[str]:
    if len(columns) != len(widths):
        raise ValueError("columns and widths must have equal lengths")
    height = max((len(column) for column in columns), default=0)
    output: list[str] = []
    for row in range(height):
        cells: list[str] = []
        for column, width in zip(columns, widths):
            value = column[row] if row < len(column) else ""
            if text_width(value) > width:
                raise ValueError("column value exceeds declared width")
            cells.append(pad_cells(value, width))
        output.append(separator.join(cells))
    return output


def horizontal_rule(width: int, theme: str = "unicode-light") -> str:
    if width < 0:
        raise ValueError("width cannot be negative")
    return ("-" if theme == "ascii" else "─") * width
