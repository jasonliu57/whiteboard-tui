"""Public data model shared by every renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


THEME_NAMES = ("ascii", "unicode-light", "unicode-rich")
GLOBAL_MAX_WIDTH = 160
GLOBAL_MAX_HEIGHT = 100


class RenderError(Exception):
    """Base class for an expected renderer failure."""


class FitError(RenderError):
    """Valid input cannot fit the requested card constraints."""


class InputError(RenderError):
    """The input document does not satisfy the style schema."""


class ValidationError(InputError):
    """A rendered result violates the common output contract."""


@dataclass(frozen=True)
class RenderOptions:
    theme: str = "unicode-light"
    max_width: int = 120
    max_height: int = 70
    single_card: bool = False


@dataclass(frozen=True)
class CardDraft:
    logical_id: str
    text: str
    width: int
    height: int
    x: int = 0
    y: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderResult:
    renderer: str
    theme: str
    cards: tuple[CardDraft, ...]
