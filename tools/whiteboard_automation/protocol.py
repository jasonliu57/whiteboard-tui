"""Byte-exact parsers for whiteboardctl textual responses."""

from __future__ import annotations

from .errors import ProtocolError
from .generated_card_formats import CARD_FORMATS
from .models import (
    CreateCardsResponse,
    DeleteCardsResponse,
    EdgeResponse,
    LiveCard,
    LiveEdge,
    LiveStatus,
    MutationResponse,
    QueryResponse,
    ViewState,
)


UINT32_MAX = 2**32 - 1
UINT64_MAX = 2**64 - 1
INT32_MAX = 2**31 - 1
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
VIEW_MODES = {"BOARD", "ACTIVE", "SELECT", "EDGE", "GLYPH"}


def ascii_text(value: bytes, context: str) -> str:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError(f"{context}: expected ASCII") from error


def integer(
    value: bytes,
    context: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    text = ascii_text(value, context)
    if not text or text in {"+", "-"}:
        raise ProtocolError(f"{context}: invalid integer")
    try:
        result = int(text, 10)
    except ValueError as error:
        raise ProtocolError(f"{context}: invalid integer {text!r}") from error
    if str(result).encode("ascii") != value:
        raise ProtocolError(f"{context}: non-canonical integer {text!r}")
    if minimum is not None and result < minimum:
        raise ProtocolError(f"{context}: integer below {minimum}")
    if maximum is not None and result > maximum:
        raise ProtocolError(f"{context}: integer above {maximum}")
    return result


def _single_header(raw: bytes, context: str) -> list[bytes]:
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise ProtocolError(f"{context}: expected one newline-terminated header")
    words = raw[:-1].split(b" ")
    if any(not word for word in words):
        raise ProtocolError(f"{context}: malformed response words")
    if words[0] == b"ERR":
        raise ProtocolError(f"{context}: {ascii_text(raw[:-1], context)}")
    return words


def parse_status(raw: bytes) -> LiveStatus:
    words = _single_header(raw, "STATUS")
    if len(words) != 6 or words[0] != b"OK" or words[2] != b"STATUS":
        raise ProtocolError("STATUS: invalid header")
    dirty = integer(words[5], "STATUS dirty", minimum=0)
    if dirty not in {0, 1}:
        raise ProtocolError("STATUS: dirty must be 0 or 1")
    return LiveStatus(
        revision=integer(words[1], "STATUS revision", minimum=0, maximum=UINT64_MAX),
        live_cards=integer(words[3], "STATUS card count", minimum=0, maximum=UINT32_MAX),
        live_edges=integer(words[4], "STATUS edge count", minimum=0, maximum=UINT32_MAX),
        dirty=bool(dirty),
    )


def parse_view(raw: bytes) -> ViewState:
    words = _single_header(raw, "VIEW")
    if len(words) != 11 or words[0] != b"OK" or words[2] != b"VIEW":
        raise ProtocolError("VIEW: invalid header")
    mode = ascii_text(words[3], "VIEW mode")
    if mode not in VIEW_MODES:
        raise ProtocolError(f"VIEW: unknown mode {mode!r}")
    selected = None if words[10] == b"-" else integer(
        words[10], "VIEW selected", minimum=0, maximum=UINT32_MAX
    )
    return ViewState(
        revision=integer(words[1], "VIEW revision", minimum=0, maximum=UINT64_MAX),
        mode=mode,
        viewport_x=integer(words[4], "VIEW viewport x", minimum=INT64_MIN, maximum=INT64_MAX),
        viewport_y=integer(words[5], "VIEW viewport y", minimum=INT64_MIN, maximum=INT64_MAX),
        viewport_width=integer(words[6], "VIEW viewport width", minimum=1, maximum=INT32_MAX),
        viewport_height=integer(words[7], "VIEW viewport height", minimum=1, maximum=INT32_MAX),
        cursor_x=integer(words[8], "VIEW cursor x", minimum=INT64_MIN, maximum=INT64_MAX),
        cursor_y=integer(words[9], "VIEW cursor y", minimum=INT64_MIN, maximum=INT64_MAX),
        selected_card_id=selected,
    )


def _card_at(
    raw: bytes,
    offset: int,
    *,
    revision: int,
    context: str,
) -> tuple[LiveCard, int]:
    header_end = raw.find(b"\n", offset)
    if header_end < 0:
        raise ProtocolError(f"{context}: missing CARD header newline")
    words = raw[offset:header_end].split(b" ")
    if len(words) != 8 or words[0] != b"CARD" or any(not word for word in words):
        raise ProtocolError(f"{context}: invalid CARD header")
    body_size = integer(words[7], f"{context} body size", minimum=0)
    body_begin = header_end + 1
    body_end = body_begin + body_size
    if body_end >= len(raw):
        raise ProtocolError(f"{context}: truncated CARD body")
    if raw[body_end:body_end + 1] != b"\n":
        raise ProtocolError(f"{context}: missing CARD body terminator")
    card_format = ascii_text(words[2], f"{context} format")
    if card_format not in CARD_FORMATS:
        raise ProtocolError(f"{context}: unknown card format {card_format!r}")
    contract = CARD_FORMATS[card_format]
    width = integer(words[5], f"{context} width", minimum=1, maximum=INT32_MAX)
    height = integer(words[6], f"{context} height", minimum=1, maximum=INT32_MAX)
    minimum = contract["minimum"]
    maximum = contract["maximum"]
    if not minimum[0] <= width <= maximum[0] or not minimum[1] <= height <= maximum[1]:
        raise ProtocolError(f"{context}: dimensions violate the {card_format} contract")
    return (
        LiveCard(
            revision=revision,
            card_id=integer(words[1], f"{context} id", minimum=0, maximum=UINT32_MAX),
            card_format=card_format,
            x=integer(words[3], f"{context} x", minimum=INT64_MIN, maximum=INT64_MAX),
            y=integer(words[4], f"{context} y", minimum=INT64_MIN, maximum=INT64_MAX),
            width=width,
            height=height,
            payload=raw[body_begin:body_end],
        ),
        body_end + 1,
    )


def parse_card_response(raw: bytes) -> LiveCard:
    header_end = raw.find(b"\n")
    if header_end < 0:
        raise ProtocolError("CARD: missing header newline")
    words = raw[:header_end].split(b" ")
    if len(words) != 10 or words[0] != b"OK" or words[2] != b"CARD":
        raise ProtocolError("CARD: invalid header")
    revision = integer(words[1], "CARD revision", minimum=0, maximum=UINT64_MAX)
    synthetic = b" ".join((b"CARD", *words[3:])) + raw[header_end:]
    card, offset = _card_at(synthetic, 0, revision=revision, context="CARD")
    if synthetic[offset:] != b"END\n":
        raise ProtocolError("CARD: invalid END terminator or trailing bytes")
    return card


def parse_query_response(raw: bytes) -> QueryResponse:
    header_end = raw.find(b"\n")
    if header_end < 0:
        raise ProtocolError("QUERY: missing header newline")
    words = raw[:header_end].split(b" ")
    if len(words) != 4 or words[0] != b"OK" or words[2] != b"QUERY":
        raise ProtocolError("QUERY: invalid header")
    revision = integer(words[1], "QUERY revision", minimum=0, maximum=UINT64_MAX)
    count = integer(words[3], "QUERY count", minimum=0, maximum=256)
    offset = header_end + 1
    cards: list[LiveCard] = []
    for index in range(count):
        card, offset = _card_at(raw, offset, revision=revision, context=f"QUERY card {index}")
        cards.append(card)
    if raw[offset:] != b"END\n":
        raise ProtocolError("QUERY: invalid END terminator or trailing bytes")
    if len({card.card_id for card in cards}) != len(cards):
        raise ProtocolError("QUERY: duplicate CardId")
    return QueryResponse(revision=revision, cards=tuple(cards))


def parse_edges_response(raw: bytes) -> EdgeResponse:
    lines = raw.splitlines(keepends=True)
    if len(lines) < 2 or lines[-1] != b"END\n":
        raise ProtocolError("EDGES: missing END terminator")
    header = lines[0][:-1].split(b" ") if lines[0].endswith(b"\n") else []
    if len(header) != 5 or header[0] != b"OK" or header[2] != b"EDGES":
        raise ProtocolError("EDGES: invalid header")
    revision = integer(header[1], "EDGES revision", minimum=0, maximum=UINT64_MAX)
    card_id = integer(header[3], "EDGES card id", minimum=0, maximum=UINT32_MAX)
    expected_count = integer(header[4], "EDGES count", minimum=0, maximum=UINT32_MAX)
    edges: list[LiveEdge] = []
    index = 1
    while index < len(lines) - 1:
        line = lines[index]
        if not line.endswith(b"\n"):
            raise ProtocolError("EDGES: unterminated EDGE line")
        words = line[:-1].split(b" ")
        if len(words) != 13 or words[0] != b"EDGE":
            raise ProtocolError("EDGES: invalid EDGE record")
        point_count = integer(words[12], "EDGE point count", minimum=0)
        points: list[tuple[int, int]] = []
        index += 1
        for _ in range(point_count):
            if index >= len(lines) - 1 or not lines[index].endswith(b"\n"):
                raise ProtocolError("EDGES: truncated POINT records")
            point = lines[index][:-1].split(b" ")
            if len(point) != 3 or point[0] != b"POINT":
                raise ProtocolError("EDGES: invalid POINT record")
            points.append(
                (
                    integer(point[1], "POINT x", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(point[2], "POINT y", minimum=INT64_MIN, maximum=INT64_MAX),
                )
            )
            index += 1
        edges.append(
            LiveEdge(
                revision=revision,
                edge_id=integer(words[1], "EDGE id", minimum=0, maximum=UINT32_MAX),
                source_card_id=integer(words[2], "EDGE source", minimum=0, maximum=UINT32_MAX),
                source_side=integer(words[3], "EDGE source side", minimum=0, maximum=3),
                target_card_id=integer(words[4], "EDGE target", minimum=0, maximum=UINT32_MAX),
                target_side=integer(words[5], "EDGE target side", minimum=0, maximum=3),
                mode=integer(words[6], "EDGE mode", minimum=0, maximum=1),
                state=integer(words[7], "EDGE state", minimum=0, maximum=1),
                route_bounds=(
                    integer(words[8], "EDGE left", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(words[9], "EDGE top", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(words[10], "EDGE right", minimum=INT64_MIN, maximum=INT64_MAX),
                    integer(words[11], "EDGE bottom", minimum=INT64_MIN, maximum=INT64_MAX),
                ),
                points=tuple(points),
            )
        )
    if len(edges) != expected_count:
        raise ProtocolError(f"EDGES: header declared {expected_count}, parsed {len(edges)}")
    if len({edge.edge_id for edge in edges}) != len(edges):
        raise ProtocolError("EDGES: duplicate edge id")
    return EdgeResponse(revision=revision, card_id=card_id, edges=tuple(edges))


def parse_create_cards_response(raw: bytes) -> CreateCardsResponse:
    words = _single_header(raw, "CREATE_CARDS")
    if len(words) != 5 or words[0] != b"OK" or words[2] != b"CREATE_CARDS":
        raise ProtocolError("CREATE_CARDS: invalid response")
    count = integer(words[3], "CREATE_CARDS count", minimum=1, maximum=UINT32_MAX)
    first_card_id = integer(
        words[4], "CREATE_CARDS first CardId", minimum=0, maximum=UINT32_MAX
    )
    if first_card_id + count > UINT32_MAX:
        raise ProtocolError("CREATE_CARDS: CardId range reaches the reserved sentinel")
    return CreateCardsResponse(
        revision=integer(words[1], "CREATE_CARDS revision", minimum=0, maximum=UINT64_MAX),
        count=count,
        first_card_id=first_card_id,
    )


def _parse_mutation_response(raw: bytes, operation: bytes, context: str) -> MutationResponse:
    words = _single_header(raw, context)
    if len(words) != 4 or words[0] != b"OK" or words[2] != operation:
        raise ProtocolError(f"{context}: invalid response")
    return MutationResponse(
        revision=integer(words[1], f"{context} revision", minimum=0, maximum=UINT64_MAX),
        object_id=integer(words[3], f"{context} object id", minimum=0, maximum=UINT32_MAX),
    )


def parse_replace_card_response(raw: bytes) -> MutationResponse:
    return _parse_mutation_response(raw, b"REPLACE_CARD", "REPLACE_CARD")


def parse_connect_response(raw: bytes) -> MutationResponse:
    return _parse_mutation_response(raw, b"CONNECT", "CONNECT")


def parse_delete_cards_response(raw: bytes) -> DeleteCardsResponse:
    words = _single_header(raw, "DELETE_CARDS")
    if len(words) != 4 or words[0] != b"OK" or words[2] != b"DELETE_CARDS":
        raise ProtocolError("DELETE_CARDS: invalid response")
    return DeleteCardsResponse(
        revision=integer(words[1], "DELETE_CARDS revision", minimum=0, maximum=UINT64_MAX),
        count=integer(words[3], "DELETE_CARDS count", minimum=1, maximum=UINT32_MAX),
    )
