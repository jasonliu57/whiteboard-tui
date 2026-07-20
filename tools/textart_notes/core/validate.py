"""Contract validation for options, card drafts, and complete results."""

from __future__ import annotations

import json
import re

from .cell_width import text_width, validate_combining_anchors
from .models import (
    GLOBAL_MAX_HEIGHT,
    GLOBAL_MAX_WIDTH,
    THEME_NAMES,
    CardDraft,
    RenderOptions,
    RenderResult,
    ValidationError,
)


_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def validate_options(options: RenderOptions) -> None:
    if not isinstance(options, RenderOptions):
        raise ValidationError("options must be a RenderOptions instance")
    if options.theme not in THEME_NAMES:
        raise ValidationError(f"unsupported theme: {options.theme}")
    if type(options.max_width) is not int:
        raise ValidationError("max_width must be an integer")
    if type(options.max_height) is not int:
        raise ValidationError("max_height must be an integer")
    if type(options.single_card) is not bool:
        raise ValidationError("single_card must be a boolean")
    if not 1 <= options.max_width <= GLOBAL_MAX_WIDTH:
        raise ValidationError(f"max_width must be between 1 and {GLOBAL_MAX_WIDTH}")
    if not 1 <= options.max_height <= GLOBAL_MAX_HEIGHT:
        raise ValidationError(f"max_height must be between 1 and {GLOBAL_MAX_HEIGHT}")


def validate_card(card: CardDraft, options: RenderOptions) -> None:
    if not _SLUG_RE.fullmatch(card.logical_id):
        raise ValidationError(f"invalid card id: {card.logical_id!r}")
    if card.text.endswith("\n") or "\r" in card.text:
        raise ValidationError(f"{card.logical_id}: draft text must not contain a final newline or CR")
    if not 1 <= card.width <= min(options.max_width, GLOBAL_MAX_WIDTH):
        raise ValidationError(f"{card.logical_id}: invalid width {card.width}")
    if not 1 <= card.height <= min(options.max_height, GLOBAL_MAX_HEIGHT):
        raise ValidationError(f"{card.logical_id}: invalid height {card.height}")
    if card.x < 0 or card.y < 0:
        raise ValidationError(f"{card.logical_id}: relative coordinates cannot be negative")
    lines = card.text.split("\n")
    if len(lines) != card.height:
        raise ValidationError(
            f"{card.logical_id}: declared height {card.height}, actual line count {len(lines)}"
        )
    for index, line in enumerate(lines, start=1):
        try:
            validate_combining_anchors(line)
            width = text_width(line)
        except ValueError as error:
            raise ValidationError(f"{card.logical_id}: invalid line {index}: {error}") from error
        if width > card.width:
            raise ValidationError(
                f"{card.logical_id}: line {index} is {width} cells, exceeds width {card.width}"
            )
    try:
        json.dumps(dict(card.metadata), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{card.logical_id}: metadata is not JSON serializable") from error


def validate_result(result: RenderResult, options: RenderOptions) -> None:
    validate_options(options)
    if not _SLUG_RE.fullmatch(result.renderer):
        raise ValidationError(f"invalid renderer id: {result.renderer!r}")
    if result.theme != options.theme:
        raise ValidationError("result theme does not match render options")
    if not result.cards:
        raise ValidationError("renderer returned no cards")
    if options.single_card and len(result.cards) != 1:
        from .models import FitError

        raise FitError("input requires multiple cards while --single-card is active")
    seen: set[str] = set()
    for card in result.cards:
        if card.logical_id in seen:
            raise ValidationError(f"duplicate card id: {card.logical_id}")
        seen.add(card.logical_id)
        validate_card(card, options)
