"""Exact time scaling helpers shared by temporal note renderers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaledGap:
    raw_cells: int
    drawn_cells: int
    omitted_cells: int


def ceil_scaled_cells(delta: int, units_per_cell: int) -> int:
    """Map a non-negative exact integer delta using mathematical ceiling."""

    if delta < 0:
        raise ValueError("timeline delta cannot be negative")
    if units_per_cell < 1:
        raise ValueError("timeline units_per_cell must be positive")
    return (delta + units_per_cell - 1) // units_per_cell


def scale_gap(delta: int, units_per_cell: int, *, cap: int | None = None) -> ScaledGap:
    """Return raw and explicitly capped connector-cell counts."""

    raw = ceil_scaled_cells(delta, units_per_cell)
    if cap is None:
        return ScaledGap(raw, raw, 0)
    if cap < 1:
        raise ValueError("timeline cap must be positive")
    drawn = min(raw, cap)
    return ScaledGap(raw, drawn, raw - drawn)
