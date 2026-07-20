"""Exact deterministic mapping for bounded two-dimensional terminal axes."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence


@dataclass(frozen=True)
class AxisRange:
    minimum: Fraction
    maximum: Fraction

    def __post_init__(self) -> None:
        if self.minimum >= self.maximum:
            raise ValueError("axis minimum must be less than maximum")


@dataclass(frozen=True)
class AxisPoint:
    key: str
    x: Fraction
    y: Fraction


@dataclass(frozen=True)
class QuantizedPoint:
    key: str
    x: Fraction
    y: Fraction
    qx: int
    qy: int


@dataclass(frozen=True)
class QuantizedGroup:
    qx: int
    qy: int
    points: tuple[QuantizedPoint, ...]


def round_half_up(value: Fraction) -> int:
    """Round an exact rational to nearest integer, with ties away from zero."""

    sign = -1 if value < 0 else 1
    numerator = abs(value.numerator)
    quotient, remainder = divmod(numerator, value.denominator)
    if remainder * 2 >= value.denominator:
        quotient += 1
    return sign * quotient


def quantize(value: Fraction, bounds: AxisRange, span: int) -> int:
    """Map an inclusive bounded value to an integer span using half-up ties."""

    if span < 0:
        raise ValueError("axis span cannot be negative")
    if not bounds.minimum <= value <= bounds.maximum:
        raise ValueError("axis value is outside its inclusive bounds")
    ratio = (value - bounds.minimum) / (bounds.maximum - bounds.minimum)
    return round_half_up(ratio * span)


def quantize_points(
    points: Sequence[AxisPoint],
    x_range: AxisRange,
    y_range: AxisRange,
    *,
    plot_width: int,
    plot_height: int,
) -> tuple[QuantizedGroup, ...]:
    """Quantize points and retain first-cell and per-cell input order."""

    if plot_width < 1 or plot_height < 1:
        raise ValueError("plot dimensions must be positive")
    keys = [point.key for point in points]
    if len(set(keys)) != len(keys):
        raise ValueError("axis point keys must be unique")
    grouped: OrderedDict[tuple[int, int], list[QuantizedPoint]] = OrderedDict()
    for point in points:
        qx = quantize(point.x, x_range, plot_width - 1)
        from_bottom = quantize(point.y, y_range, plot_height - 1)
        qy = plot_height - 1 - from_bottom
        measured = QuantizedPoint(point.key, point.x, point.y, qx, qy)
        grouped.setdefault((qx, qy), []).append(measured)
    return tuple(
        QuantizedGroup(qx, qy, tuple(values))
        for (qx, qy), values in grouped.items()
    )
