"""Typed responses exposed by whiteboard command-line automation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LiveStatus:
    revision: int
    live_cards: int
    live_edges: int
    dirty: bool

    @property
    def cards(self) -> int:
        return self.live_cards

    @property
    def edges(self) -> int:
        return self.live_edges


@dataclass(frozen=True)
class ViewState:
    revision: int
    mode: str
    viewport_x: int
    viewport_y: int
    viewport_width: int
    viewport_height: int
    cursor_x: int
    cursor_y: int
    selected_card_id: int | None


@dataclass(frozen=True)
class LiveCard:
    revision: int
    card_id: int
    card_format: str
    x: int
    y: int
    width: int
    height: int
    payload: bytes

    @property
    def format_name(self) -> str:
        return self.card_format


@dataclass(frozen=True)
class QueryResponse:
    revision: int
    cards: tuple[LiveCard, ...]


@dataclass(frozen=True)
class LiveEdge:
    revision: int
    edge_id: int
    source_card_id: int
    source_side: int
    target_card_id: int
    target_side: int
    mode: int
    state: int
    route_bounds: tuple[int, int, int, int]
    points: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class EdgeResponse:
    revision: int
    card_id: int
    edges: tuple[LiveEdge, ...]


@dataclass(frozen=True)
class CreateCardsResponse:
    revision: int
    count: int
    first_card_id: int


@dataclass(frozen=True)
class MutationResponse:
    revision: int
    object_id: int


@dataclass(frozen=True)
class DeleteCardsResponse:
    revision: int
    count: int


@dataclass(frozen=True)
class SnapshotCard:
    card_id: int
    card_format: str
    x: int
    y: int
    width: int
    height: int
    payload: bytes
    raw_record: bytes


@dataclass(frozen=True)
class SnapshotEdge:
    edge_id: int
    source_card_id: int
    source_side: int
    target_card_id: int
    target_side: int
    mode: int
    state: int
    route_bounds: tuple[int, int, int, int]
    points: tuple[tuple[int, int], ...]
    raw_record: bytes


@dataclass(frozen=True)
class SnapshotGlyph:
    x: int
    y: int
    codepoint: int
    raw_record: bytes


@dataclass(frozen=True)
class CanonicalSnapshot:
    card_slots: int
    live_cards: int
    edge_slots: int
    live_edges: int
    glyph_count: int
    cards: dict[int, SnapshotCard]
    edges: dict[int, SnapshotEdge]
    glyphs: dict[tuple[int, int], SnapshotGlyph]
    digest: str
    raw: bytes = field(repr=False)
