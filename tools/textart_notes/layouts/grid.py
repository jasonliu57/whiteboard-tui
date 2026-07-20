"""Deterministic cell-aware Grid measurement, pagination, and painting."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from ..core.cell_width import pad_cells, text_width
from ..core.models import FitError
from ..core.themes import EAST, NORTH, SOUTH, WEST, get_theme
from ..core.wrap import wrap_line


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    minimum: int = 3
    weight: int = 1
    align: str = "left"
    wrap: bool = True


@dataclass(frozen=True)
class GridRow:
    key: str
    cells: tuple[str, ...]
    alignments: tuple[str, ...] | None = None


@dataclass(frozen=True)
class MeasuredRow:
    key: str
    cells: tuple[tuple[str, ...], ...]
    height: int
    alignments: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ShelfItem:
    key: str
    width: int
    height: int


@dataclass(frozen=True)
class ShelfPlacement:
    key: str
    x: int
    y: int
    row: int
    column: int


def pack_row_major(
    items: Sequence[ShelfItem],
    *,
    columns: int,
    gutter_x: int = 0,
    gutter_y: int = 0,
) -> tuple[ShelfPlacement, ...]:
    """Pack sized cards in stable shelf rows using their actual dimensions."""

    if columns < 1 or gutter_x < 0 or gutter_y < 0:
        raise ValueError("invalid row-major packing geometry")
    if any(item.width < 1 or item.height < 1 for item in items):
        raise ValueError("packed item dimensions must be positive")
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys):
        raise ValueError("packed item keys must be unique")
    placements: list[ShelfPlacement] = []
    y = 0
    for start in range(0, len(items), columns):
        row_items = items[start : start + columns]
        x = 0
        row = start // columns
        for column, item in enumerate(row_items):
            placements.append(ShelfPlacement(item.key, x, y, row, column))
            x += item.width + gutter_x
        y += max(item.height for item in row_items) + gutter_y
    return tuple(placements)


def allocate_widths(total: int, columns: Sequence[Column]) -> tuple[int, ...]:
    """Allocate an exact content-cell budget by minimums and integer weights."""

    if not columns:
        raise ValueError("at least one column is required")
    if any(column.minimum < 1 or column.weight < 1 for column in columns):
        raise ValueError("column minimums and weights must be positive")
    minimum = sum(column.minimum for column in columns)
    if total < minimum:
        raise FitError(f"grid needs at least {minimum} content cells; got {total}")
    widths = [column.minimum for column in columns]
    remainder = total - minimum
    weight_sum = sum(column.weight for column in columns)
    quotients = [remainder * column.weight // weight_sum for column in columns]
    for index, value in enumerate(quotients):
        widths[index] += value
    leftover = remainder - sum(quotients)
    # Largest fractional remainder, with stable column order as tie breaker.
    order = sorted(
        range(len(columns)),
        key=lambda index: (-(remainder * columns[index].weight % weight_sum), index),
    )
    for index in order[:leftover]:
        widths[index] += 1
    return tuple(widths)


def allocate_weighted(
    total: int,
    weights: Sequence[Fraction],
    minimums: Sequence[int],
) -> tuple[int, ...]:
    """Allocate exact cells by rational weights, then repair hard minimums."""

    if not weights or len(weights) != len(minimums):
        raise ValueError("weights and minimums must have equal non-zero arity")
    if any(weight <= 0 for weight in weights) or any(minimum < 1 for minimum in minimums):
        raise ValueError("weights and minimums must be positive")
    if sum(minimums) > total:
        raise FitError(f"column minima need {sum(minimums)} cells; got {total}")
    weight_sum = sum(weights, Fraction(0))
    raw = [Fraction(total) * weight / weight_sum for weight in weights]
    allocated = [value.numerator // value.denominator for value in raw]
    leftover = total - sum(allocated)
    order = sorted(
        range(len(weights)),
        key=lambda index: (-(raw[index] - allocated[index]), index),
    )
    for index in order[:leftover]:
        allocated[index] += 1
    for target, minimum in enumerate(minimums):
        deficit = minimum - allocated[target]
        while deficit > 0:
            donors = [
                index for index in range(len(weights))
                if index != target and allocated[index] > minimums[index]
            ]
            if not donors:
                raise FitError("cannot satisfy indivisible column widths")
            donor = max(donors, key=lambda index: (allocated[index] - minimums[index], -index))
            moved = min(deficit, allocated[donor] - minimums[donor])
            allocated[donor] -= moved
            allocated[target] += moved
            deficit -= moved
    return tuple(allocated)


def allocate_toward_demands(
    total: int,
    minimums: Sequence[int],
    demands: Sequence[int],
) -> tuple[int, ...]:
    """Grow hard minimums toward measured demands with stable tie-breaking."""

    if not minimums or len(minimums) != len(demands):
        raise ValueError("minimums and demands must have equal non-zero arity")
    if any(minimum < 1 for minimum in minimums):
        raise ValueError("minimums must be positive")
    if sum(minimums) > total:
        raise FitError(f"column minima need {sum(minimums)} cells; got {total}")
    widths = list(minimums)
    remaining = total - sum(widths)
    while remaining:
        unmet = [max(0, demand - widths[index]) for index, demand in enumerate(demands)]
        if max(unmet) > 0:
            target = max(range(len(widths)), key=lambda index: (unmet[index], -index))
        else:
            target = (total - sum(minimums) - remaining) % len(widths)
        widths[target] += 1
        remaining -= 1
    return tuple(widths)


def table_content_budget(total_width: int, column_count: int, *, padding: int = 1) -> int:
    """Return cells available to content after borders, separators, and padding."""

    if column_count < 1 or padding < 0:
        raise ValueError("invalid table geometry")
    fixed = column_count + 1 + 2 * padding * column_count
    budget = total_width - fixed
    if budget < column_count:
        raise FitError("table footprint leaves no usable content cells")
    return budget


def _cell_lines(value: str, width: int, *, start_column: int, wrap: bool) -> tuple[str, ...]:
    hard_lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    for hard_line in hard_lines:
        if wrap:
            try:
                output.extend(wrap_line(hard_line, width, start_column=start_column))
            except ValueError as error:
                raise FitError(str(error)) from error
        else:
            if "\t" in hard_line:
                from ..core.cell_width import expand_tabs

                hard_line = expand_tabs(hard_line, start=start_column)
            if text_width(hard_line) > width:
                raise FitError("nowrap grid cell exceeds its allocated width")
            output.append(hard_line)
    return tuple(output or [""])


def measure_row(
    row: GridRow,
    columns: Sequence[Column],
    widths: Sequence[int],
    *,
    padding: int = 1,
) -> MeasuredRow:
    if len(row.cells) != len(columns) or len(widths) != len(columns):
        raise ValueError("row, columns, and widths must have equal arity")
    if row.alignments is not None:
        if len(row.alignments) != len(columns):
            raise ValueError("row alignments must match column arity")
        if any(align not in {"left", "center", "right"} for align in row.alignments):
            raise ValueError("row alignments contain an unknown value")
    starts: list[int] = []
    column = 1 + padding
    for width in widths:
        starts.append(column)
        column += width + 2 * padding + 1
    cells = tuple(
        _cell_lines(value, width, start_column=start, wrap=spec.wrap)
        for value, spec, width, start in zip(row.cells, columns, widths, starts)
    )
    return MeasuredRow(row.key, cells, max(len(cell) for cell in cells), row.alignments)


def measure_rows(
    rows: Sequence[GridRow],
    columns: Sequence[Column],
    widths: Sequence[int],
    *,
    padding: int = 1,
) -> tuple[MeasuredRow, ...]:
    return tuple(measure_row(row, columns, widths, padding=padding) for row in rows)


def paginate_rows(rows: Sequence[MeasuredRow], capacity: int, *, separator_rows: int = 1) -> tuple[tuple[MeasuredRow, ...], ...]:
    """Pack complete measured rows; never divide a row across pages."""

    if capacity < 1 or separator_rows < 0:
        raise ValueError("invalid pagination geometry")
    pages: list[tuple[MeasuredRow, ...]] = []
    current: list[MeasuredRow] = []
    used = 0
    for row in rows:
        cost = row.height + (separator_rows if current else 0)
        if row.height > capacity:
            raise FitError(f"indivisible grid row {row.key!r} exceeds page capacity")
        if current and used + cost > capacity:
            pages.append(tuple(current))
            current = []
            used = 0
            cost = row.height
        current.append(row)
        used += cost
    if current:
        pages.append(tuple(current))
    return tuple(pages)


def split_column_groups(
    columns: Sequence[Column],
    total_width: int,
    *,
    preserve_index: int = 0,
    padding: int = 1,
) -> tuple[tuple[int, ...], ...]:
    """Greedily group columns while repeating one preserved key column."""

    if not 0 <= preserve_index < len(columns):
        raise ValueError("preserve_index is outside columns")
    remaining = [index for index in range(len(columns)) if index != preserve_index]
    if not remaining:
        budget = table_content_budget(total_width, 1, padding=padding)
        if columns[preserve_index].minimum > budget:
            raise FitError("preserved column cannot fit the table")
        return ((preserve_index,),)
    groups: list[tuple[int, ...]] = []
    current: list[int] = [preserve_index]
    for index in remaining:
        candidate = current + [index]
        budget = table_content_budget(total_width, len(candidate), padding=padding)
        if sum(columns[item].minimum for item in candidate) <= budget:
            current = candidate
            continue
        if len(current) == 1:
            raise FitError(f"column {columns[index].key!r} cannot fit beside preserved column")
        groups.append(tuple(current))
        current = [preserve_index, index]
        budget = table_content_budget(total_width, 2, padding=padding)
        if columns[preserve_index].minimum + columns[index].minimum > budget:
            raise FitError(f"column {columns[index].key!r} cannot fit beside preserved column")
    groups.append(tuple(current))
    return tuple(groups)


def _glyphs(theme: str) -> dict[str, str]:
    selected = get_theme(theme)
    return {
        "h": selected.line(EAST | WEST),
        "v": selected.line(NORTH | SOUTH),
        "tl": selected.line(EAST | SOUTH),
        "tr": selected.line(SOUTH | WEST),
        "bl": selected.line(NORTH | EAST),
        "br": selected.line(NORTH | WEST),
        "top": selected.line(EAST | SOUTH | WEST),
        "bottom": selected.line(NORTH | EAST | WEST),
        "left": selected.line(NORTH | EAST | SOUTH),
        "right": selected.line(NORTH | SOUTH | WEST),
        "cross": selected.line(NORTH | EAST | SOUTH | WEST),
    }


def _rule(widths: Sequence[int], theme: str, kind: str, padding: int) -> str:
    glyph = _glyphs(theme)
    ends = {
        "top": (glyph["tl"], glyph["top"], glyph["tr"]),
        "middle": (glyph["left"], glyph["cross"], glyph["right"]),
        "bottom": (glyph["bl"], glyph["bottom"], glyph["br"]),
    }
    left, junction, right = ends[kind]
    spans = [glyph["h"] * (width + 2 * padding) for width in widths]
    return left + junction.join(spans) + right


def _paint_row(
    row: MeasuredRow,
    columns: Sequence[Column],
    widths: Sequence[int],
    theme: str,
    padding: int,
) -> list[str]:
    vertical = _glyphs(theme)["v"]
    output: list[str] = []
    for line_index in range(row.height):
        cells: list[str] = []
        for cell_index, (lines, spec, width) in enumerate(zip(row.cells, columns, widths)):
            value = lines[line_index] if line_index < len(lines) else ""
            align = row.alignments[cell_index] if row.alignments is not None else spec.align
            cells.append(" " * padding + pad_cells(value, width, align=align) + " " * padding)
        output.append(vertical + vertical.join(cells) + vertical)
    return output


def render_table(
    columns: Sequence[Column],
    widths: Sequence[int],
    rows: Sequence[MeasuredRow],
    theme: str,
    *,
    padding: int = 1,
) -> list[str]:
    """Paint headers and measured rows into a closed terminal-cell table."""

    if len(columns) != len(widths):
        raise ValueError("columns and widths must have equal lengths")
    header = measure_row(
        GridRow("header", tuple(column.label for column in columns)),
        columns,
        widths,
        padding=padding,
    )
    output = [_rule(widths, theme, "top", padding)]
    output.extend(_paint_row(header, columns, widths, theme, padding))
    output.append(_rule(widths, theme, "middle", padding))
    for index, row in enumerate(rows):
        output.extend(_paint_row(row, columns, widths, theme, padding))
        output.append(
            _rule(widths, theme, "bottom" if index == len(rows) - 1 else "middle", padding)
        )
    if not rows:
        output[-1] = _rule(widths, theme, "bottom", padding)
    return output
