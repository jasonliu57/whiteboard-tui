"""Parser for the canonical whiteboard snapshot format."""

from __future__ import annotations

import hashlib

from .errors import ProtocolError
from .generated_card_formats import CARD_FORMATS
from .models import CanonicalSnapshot, SnapshotCard, SnapshotEdge, SnapshotGlyph
from .protocol import INT32_MAX, INT64_MAX, INT64_MIN, UINT32_MAX, ascii_text, integer


SNAPSHOT_MAGIC = b"WHITEBOARD-SNAPSHOT 2\n"


def parse_canonical_snapshot(raw: bytes) -> CanonicalSnapshot:
    if not raw.startswith(SNAPSHOT_MAGIC):
        raise ProtocolError("SNAPSHOT: invalid magic or schema version")
    offset = len(SNAPSHOT_MAGIC)

    def line() -> tuple[bytes, int, int]:
        nonlocal offset
        end = raw.find(b"\n", offset)
        if end < 0:
            raise ProtocolError("SNAPSHOT: unterminated record")
        start = offset
        offset = end + 1
        return raw[start:end], start, offset

    meta, _, _ = line()
    words = meta.split(b" ")
    if len(words) != 6 or words[0] != b"META":
        raise ProtocolError("SNAPSHOT: missing META record")
    card_slots = integer(words[1], "META card slots", minimum=0, maximum=UINT32_MAX)
    live_cards = integer(words[2], "META live cards", minimum=0, maximum=UINT32_MAX)
    edge_slots = integer(words[3], "META edge slots", minimum=0, maximum=UINT32_MAX)
    live_edges = integer(words[4], "META live edges", minimum=0, maximum=UINT32_MAX)
    glyph_count = integer(words[5], "META glyph count", minimum=0)
    if live_cards > card_slots or live_edges > edge_slots:
        raise ProtocolError("SNAPSHOT: META live counts exceed slot counts")
    cards: dict[int, SnapshotCard] = {}
    edges: dict[int, SnapshotEdge] = {}
    glyphs: dict[tuple[int, int], SnapshotGlyph] = {}
    phase = 0
    previous_card_id = -1
    previous_edge_id = -1
    previous_glyph_order: tuple[int, int] | None = None

    while True:
        record, start, after_header = line()
        if record == b"END":
            if offset != len(raw):
                raise ProtocolError("SNAPSHOT: trailing bytes after END")
            break
        fields = record.split(b" ")
        if fields[0] == b"CARD":
            if phase > 0 or len(fields) != 8:
                raise ProtocolError("SNAPSHOT: invalid or out-of-order CARD")
            card_id = integer(fields[1], "SNAPSHOT card id", minimum=0, maximum=UINT32_MAX)
            if card_id <= previous_card_id:
                raise ProtocolError("SNAPSHOT: CARD records are not strictly ordered")
            previous_card_id = card_id
            payload_size = integer(fields[7], "SNAPSHOT payload size", minimum=0)
            data_end = offset + payload_size
            if data_end >= len(raw) or raw[data_end:data_end + 1] != b"\n":
                raise ProtocolError("SNAPSHOT: truncated CARD data")
            payload = raw[offset:data_end]
            offset = data_end + 1
            card_format = ascii_text(fields[2], "SNAPSHOT card format")
            if card_format not in CARD_FORMATS:
                raise ProtocolError(f"SNAPSHOT: unknown card format {card_format!r}")
            contract = CARD_FORMATS[card_format]
            width = integer(fields[5], "SNAPSHOT card width", minimum=1, maximum=INT32_MAX)
            height = integer(fields[6], "SNAPSHOT card height", minimum=1, maximum=INT32_MAX)
            minimum = contract["minimum"]
            maximum = contract["maximum"]
            if not minimum[0] <= width <= maximum[0] or not minimum[1] <= height <= maximum[1]:
                raise ProtocolError(f"SNAPSHOT: dimensions violate the {card_format} contract")
            cards[card_id] = SnapshotCard(
                card_id=card_id,
                card_format=card_format,
                x=integer(fields[3], "SNAPSHOT card x", minimum=INT64_MIN, maximum=INT64_MAX),
                y=integer(fields[4], "SNAPSHOT card y", minimum=INT64_MIN, maximum=INT64_MAX),
                width=width,
                height=height,
                payload=payload,
                raw_record=raw[start:offset],
            )
        elif fields[0] == b"EDGE":
            if phase > 1 or len(fields) < 13:
                raise ProtocolError("SNAPSHOT: invalid EDGE record")
            phase = 1
            point_count = integer(fields[12], "SNAPSHOT point count", minimum=0)
            if len(fields) != 13 + point_count * 2:
                raise ProtocolError("SNAPSHOT: EDGE point count mismatch")
            edge_id = integer(fields[1], "SNAPSHOT edge id", minimum=0, maximum=UINT32_MAX)
            if edge_id <= previous_edge_id:
                raise ProtocolError("SNAPSHOT: EDGE records are not strictly ordered")
            previous_edge_id = edge_id
            points = tuple(
                (
                    integer(
                        fields[13 + index * 2],
                        "SNAPSHOT point x",
                        minimum=INT64_MIN,
                        maximum=INT64_MAX,
                    ),
                    integer(
                        fields[14 + index * 2],
                        "SNAPSHOT point y",
                        minimum=INT64_MIN,
                        maximum=INT64_MAX,
                    ),
                )
                for index in range(point_count)
            )
            edges[edge_id] = SnapshotEdge(
                edge_id=edge_id,
                source_card_id=integer(fields[2], "SNAPSHOT edge source", minimum=0, maximum=UINT32_MAX),
                source_side=integer(fields[3], "SNAPSHOT edge source side", minimum=0, maximum=3),
                target_card_id=integer(fields[4], "SNAPSHOT edge target", minimum=0, maximum=UINT32_MAX),
                target_side=integer(fields[5], "SNAPSHOT edge target side", minimum=0, maximum=3),
                mode=integer(fields[6], "SNAPSHOT edge mode", minimum=0, maximum=1),
                state=integer(fields[7], "SNAPSHOT edge state", minimum=0, maximum=1),
                route_bounds=(
                    integer(fields[8], "SNAPSHOT edge left", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(fields[9], "SNAPSHOT edge top", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(fields[10], "SNAPSHOT edge right", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(fields[11], "SNAPSHOT edge bottom", minimum=INT64_MIN, maximum=INT64_MAX),
                ),
                points=points,
                raw_record=raw[start:after_header],
            )
        elif fields[0] == b"GLYPH":
            phase = 2
            if len(fields) != 4:
                raise ProtocolError("SNAPSHOT: invalid GLYPH record")
            x = integer(fields[1], "SNAPSHOT glyph x", minimum=INT64_MIN, maximum=INT64_MAX)
            y = integer(fields[2], "SNAPSHOT glyph y", minimum=INT64_MIN, maximum=INT64_MAX)
            order = (y, x)
            if previous_glyph_order is not None and order <= previous_glyph_order:
                raise ProtocolError("SNAPSHOT: GLYPH records are not strictly ordered")
            previous_glyph_order = order
            key = (x, y)
            if key in glyphs:
                raise ProtocolError("SNAPSHOT: duplicate GLYPH position")
            codepoint = integer(fields[3], "SNAPSHOT glyph codepoint", minimum=0)
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise ProtocolError("SNAPSHOT: invalid Unicode scalar value")
            glyphs[key] = SnapshotGlyph(x, y, codepoint, raw[start:after_header])
        else:
            raise ProtocolError(f"SNAPSHOT: unknown record {ascii_text(fields[0], 'record')!r}")

    if len(cards) != live_cards or len(edges) != live_edges or len(glyphs) != glyph_count:
        raise ProtocolError("SNAPSHOT: META live counts do not match records")
    if cards and max(cards) >= card_slots:
        raise ProtocolError("SNAPSHOT: CARD id exceeds slot count")
    if edges and max(edges) >= edge_slots:
        raise ProtocolError("SNAPSHOT: EDGE id exceeds slot count")
    return CanonicalSnapshot(
        card_slots,
        live_cards,
        edge_slots,
        live_edges,
        glyph_count,
        cards,
        edges,
        glyphs,
        hashlib.sha256(raw).hexdigest(),
        raw,
    )
