"""Canonical whiteboardctl batch encoders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .generated_card_formats import CARD_FORMATS


@dataclass(frozen=True)
class CreateCardSpec:
    card_format: str
    x: int
    y: int
    width: int
    height: int


def _validate_create_card(card: CreateCardSpec, context: str) -> None:
    if card.card_format not in CARD_FORMATS:
        raise ValueError(f"{context} has unknown format {card.card_format!r}")
    if any(type(value) is not int for value in (card.x, card.y, card.width, card.height)):
        raise ValueError(f"{context} geometry must use integers")
    if not -(2**63) <= card.x <= 2**63 - 1 or not -(2**63) <= card.y <= 2**63 - 1:
        raise ValueError(f"{context} has an out-of-range coordinate")
    contract = CARD_FORMATS[card.card_format]
    minimum = contract["minimum"]
    maximum = contract["maximum"]
    if (
        not minimum[0] <= card.width <= maximum[0]
        or not minimum[1] <= card.height <= maximum[1]
    ):
        raise ValueError(f"{context} has invalid dimensions for {card.card_format}")
    if card.x > 2**63 - 1 - card.width or card.y > 2**63 - 1 - card.height:
        raise ValueError(f"{context} overflows its coordinate extent")


def encode_create_cards(cards: Iterable[CreateCardSpec]) -> bytes:
    rows = tuple(cards)
    if not rows:
        raise ValueError("create-cards batch must contain at least one card")
    for index, card in enumerate(rows, start=1):
        _validate_create_card(card, f"create-cards row {index}")
    return "".join(
        f"{card.card_format} {card.x} {card.y} {card.width} {card.height}\n"
        for card in rows
    ).encode("ascii")


def decode_create_cards(data: bytes) -> tuple[CreateCardSpec, ...]:
    """Parse the canonical format emitted by :func:`encode_create_cards`."""

    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("create-cards batch must be ASCII") from error
    if not text.endswith("\n"):
        raise ValueError("create-cards batch must end with a newline")
    rows: list[CreateCardSpec] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        words = line.split(" ")
        if len(words) != 5 or any(not word for word in words):
            raise ValueError(f"create-cards line {line_number} must contain five words")
        card_format = words[0]
        if card_format not in CARD_FORMATS:
            raise ValueError(f"create-cards line {line_number} has unknown format {card_format!r}")
        values: list[int] = []
        for name, word in zip(("x", "y", "width", "height"), words[1:]):
            try:
                value = int(word, 10)
            except ValueError as error:
                raise ValueError(f"create-cards line {line_number} has invalid {name}") from error
            if str(value) != word:
                raise ValueError(f"create-cards line {line_number} has non-canonical {name}")
            values.append(value)
        x, y, width, height = values
        if not -(2**63) <= x <= 2**63 - 1 or not -(2**63) <= y <= 2**63 - 1:
            raise ValueError(f"create-cards line {line_number} has an out-of-range coordinate")
        card = CreateCardSpec(card_format, x, y, width, height)
        _validate_create_card(card, f"create-cards line {line_number}")
        rows.append(card)
    if not rows:
        raise ValueError("create-cards batch must contain at least one card")
    return tuple(rows)


def encode_delete_cards(card_ids: Iterable[int]) -> bytes:
    values = tuple(card_ids)
    if not values:
        raise ValueError("delete-cards batch must contain at least one CardId")
    if any(card_id < 0 for card_id in values):
        raise ValueError("CardIds must be non-negative")
    if len(values) != len(set(values)):
        raise ValueError("delete-cards batch contains duplicate CardIds")
    return "".join(f"{card_id}\n" for card_id in values).encode("ascii")
