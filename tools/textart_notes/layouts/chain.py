"""Ordered Chain geometry with stable prefixes and hanging continuations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..core.cell_width import text_width
from ..core.models import FitError
from ..core.wrap import wrap_line


@dataclass(frozen=True)
class ChainEntry:
    key: str
    prefix: str
    text: str


@dataclass(frozen=True)
class MeasuredChainEntry:
    key: str
    prefix: str
    lines: tuple[str, ...]
    body_column: int

    @property
    def height(self) -> int:
        return len(self.lines)


def measure_chain(
    entries: Sequence[ChainEntry],
    width: int,
    *,
    start_column: int = 0,
    gap: str = " ",
) -> tuple[MeasuredChainEntry, ...]:
    """Wrap complete ordered entries with body-aligned hanging indentation."""

    if width < 1 or start_column < 0:
        raise ValueError("chain width must be positive and start_column non-negative")
    output: list[MeasuredChainEntry] = []
    for entry in entries:
        lead = entry.prefix + gap
        lead_width = text_width(lead, start=start_column)
        available = width - lead_width
        if available < 1:
            raise FitError(f"chain prefix for {entry.key!r} leaves no body width")
        lines: list[str] = []
        try:
            for hard_line in entry.text.split("\n"):
                wrapped = wrap_line(
                    hard_line,
                    available,
                    start_column=start_column + lead_width,
                )
                for line in wrapped:
                    lines.append((lead if not lines else " " * lead_width) + line)
        except ValueError as error:
            raise FitError(f"chain entry {entry.key!r}: {error}") from error
        output.append(
            MeasuredChainEntry(
                entry.key,
                entry.prefix,
                tuple(lines or [lead.rstrip()]),
                start_column + lead_width,
            )
        )
    return tuple(output)


def paginate_chain(
    entries: Sequence[MeasuredChainEntry],
    max_height: int,
    *,
    reserved_rows: int = 0,
    separator_rows: int = 0,
) -> tuple[tuple[MeasuredChainEntry, ...], ...]:
    """Greedily pack indivisible chain entries without renumbering them."""

    capacity = max_height - reserved_rows
    if capacity < 1 or separator_rows < 0:
        raise FitError("chain context leaves no usable card rows")
    pages: list[tuple[MeasuredChainEntry, ...]] = []
    current: list[MeasuredChainEntry] = []
    used = 0
    for entry in entries:
        if entry.height > capacity:
            raise FitError(f"chain entry {entry.key!r} is indivisible and too tall")
        cost = entry.height + (separator_rows if current else 0)
        if current and used + cost > capacity:
            pages.append(tuple(current))
            current = []
            used = 0
            cost = entry.height
        current.append(entry)
        used += cost
    if current:
        pages.append(tuple(current))
    return tuple(pages)
