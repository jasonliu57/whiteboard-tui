"""Evidence Pair specialization over the shared Grid engine."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from ..core.models import FitError
from .grid import Column, GridRow, MeasuredRow, measure_rows, table_content_budget


@dataclass(frozen=True)
class Pair:
    pair_id: str
    left: str
    right: str


@dataclass(frozen=True)
class SourceSlice:
    first_line: int
    lines: tuple[str, ...]

    @property
    def last_line(self) -> int:
        return self.first_line + len(self.lines) - 1


@dataclass(frozen=True)
class SourceAnchor:
    key: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ResolvedAnchor:
    key: str
    start_line: int
    end_line: int
    excerpt: tuple[tuple[int, str], ...]


def resolve_source_anchors(
    source: SourceSlice,
    anchors: Sequence[SourceAnchor],
) -> tuple[ResolvedAnchor, ...]:
    """Resolve inclusive source ranges without sorting or merging overlaps."""

    if source.first_line < 1 or not source.lines:
        raise ValueError("source slice needs a positive first line and at least one line")
    output: list[ResolvedAnchor] = []
    seen: set[str] = set()
    for anchor in anchors:
        if anchor.key in seen:
            raise ValueError(f"duplicate source anchor {anchor.key!r}")
        seen.add(anchor.key)
        if anchor.start_line > anchor.end_line:
            raise ValueError(f"source anchor {anchor.key!r} is reversed")
        if anchor.start_line < source.first_line or anchor.end_line > source.last_line:
            raise ValueError(f"source anchor {anchor.key!r} is outside the source slice")
        excerpt = tuple(
            (number, source.lines[number - source.first_line])
            for number in range(anchor.start_line, anchor.end_line + 1)
        )
        output.append(
            ResolvedAnchor(anchor.key, anchor.start_line, anchor.end_line, excerpt)
        )
    return tuple(output)


def pair_columns(
    left_label: str,
    right_label: str,
    ratio: Fraction,
    *,
    left_wrap: bool = True,
    right_wrap: bool = True,
) -> tuple[Column, Column]:
    if ratio <= 0 or ratio >= 1:
        raise ValueError("left ratio must be strictly between zero and one")
    return (
        Column("left", left_label, 1, ratio.numerator, "left", left_wrap),
        Column("right", right_label, 1, ratio.denominator - ratio.numerator, "left", right_wrap),
    )


def allocate_pair_widths(total: int, left_weight: int, right_weight: int) -> tuple[int, int]:
    """Allocate an exact evidence-pair budget using a left-floor policy."""

    if total < 2 or left_weight < 1 or right_weight < 1:
        raise FitError("evidence pair needs two positive widths and weights")
    left = total * left_weight // (left_weight + right_weight)
    right = total - left
    if left < 1 or right < 1:
        raise FitError("evidence-pair ratio leaves one side without a cell")
    return left, right


def measure_pairs(
    pairs: Sequence[Pair],
    columns: tuple[Column, Column],
    total_width: int,
    *,
    padding: int = 0,
) -> tuple[tuple[int, int], tuple[MeasuredRow, ...]]:
    budget = table_content_budget(total_width, 2, padding=padding)
    widths = allocate_pair_widths(budget, columns[0].weight, columns[1].weight)
    rows = tuple(GridRow(pair.pair_id, (pair.left, pair.right)) for pair in pairs)
    measured = measure_rows(rows, columns, widths, padding=padding)
    return (widths[0], widths[1]), measured


def measure_pairs_at_widths(
    pairs: Sequence[Pair],
    columns: tuple[Column, Column],
    widths: tuple[int, int],
    *,
    padding: int = 1,
) -> tuple[MeasuredRow, ...]:
    """Measure pairs at adapter-owned widths such as a Cornell cue ratio."""

    rows = tuple(GridRow(pair.pair_id, (pair.left, pair.right)) for pair in pairs)
    return measure_rows(rows, columns, widths, padding=padding)
