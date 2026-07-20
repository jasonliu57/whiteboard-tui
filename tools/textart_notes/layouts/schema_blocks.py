"""Semantic vertical splitting for fixed and repeatable schema blocks."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.models import FitError


@dataclass(frozen=True)
class Block:
    key: str
    lines: tuple[str, ...]
    repeat_header: bool = False

    @property
    def height(self) -> int:
        return len(self.lines)


@dataclass(frozen=True)
class BlockPlacement:
    key: str
    y: int
    height: int


def place_blocks(
    blocks: list[Block],
    *,
    start_y: int = 0,
    gap: int = 0,
) -> tuple[BlockPlacement, ...]:
    """Stack measured schema blocks with deterministic non-overlapping rows."""

    if start_y < 0 or gap < 0:
        raise ValueError("schema-block placement requires non-negative coordinates")
    output: list[BlockPlacement] = []
    cursor = start_y
    for block in blocks:
        if block.height < 1:
            raise ValueError(f"schema block {block.key!r} has no rows")
        output.append(BlockPlacement(block.key, cursor, block.height))
        cursor += block.height + gap
    return tuple(output)


def split_blocks(blocks: list[Block], max_height: int, *, reserved_rows: int = 0) -> list[list[Block]]:
    """Pack complete semantic blocks without cropping or splitting a block."""

    capacity = max_height - reserved_rows
    if capacity <= 0:
        raise FitError("reserved rows leave no room for schema blocks")
    pages: list[list[Block]] = []
    current: list[Block] = []
    used = 0
    for block in blocks:
        if block.height > capacity:
            raise FitError(f"schema block {block.key!r} is taller than one card")
        if current and used + block.height > capacity:
            pages.append(current)
            current = []
            used = 0
        current.append(block)
        used += block.height
    if current:
        pages.append(current)
    return pages
