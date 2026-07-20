"""Strict JSON-schema-shaped normalization helpers for style adapters."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from .models import InputError
from .cell_width import (
    is_control_character,
    is_mark_character,
    is_whitespace_character,
)


_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def object_value(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise InputError(f"{path} must be an object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise InputError(f"{path} keys must be strings")
    return result


def array_value(value: object, path: str) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise InputError(f"{path} must be an array")
    return list(value)


def check_keys(
    value: Mapping[str, object],
    path: str,
    *,
    required: set[str] | frozenset[str],
    allowed: set[str] | frozenset[str],
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise InputError(f"{path} is missing: {', '.join(missing)}")
    if unknown:
        raise InputError(f"{path} has unknown keys: {', '.join(unknown)}")


def validate_characters(value: str, path: str, *, allow_newlines: bool = True, allow_tabs: bool = True) -> None:
    anchored = False
    for character in value:
        if character == "\n":
            if not allow_newlines:
                raise InputError(f"{path} must be one line")
            anchored = False
            continue
        if character == "\t":
            if not allow_tabs:
                raise InputError(f"{path} must not contain tabs")
            anchored = False
            continue
        is_mark = is_mark_character(character)
        if is_control_character(character):
            raise InputError(f"{path} contains unsupported character U+{ord(character):04X}")
        if is_mark:
            if not anchored:
                raise InputError(f"{path} has a combining character without an anchor")
        else:
            anchored = not is_whitespace_character(character)


def string_value(
    value: object,
    path: str,
    *,
    allow_empty: bool = False,
    single_line: bool = False,
    allow_tabs: bool = True,
    strip: bool = False,
) -> str:
    if not isinstance(value, str):
        raise InputError(f"{path} must be a string")
    normalized = value.strip() if strip else value
    if not allow_empty and not normalized:
        raise InputError(f"{path} must not be empty")
    validate_characters(
        normalized,
        path,
        allow_newlines=not single_line,
        allow_tabs=allow_tabs,
    )
    return normalized


def bool_value(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise InputError(f"{path} must be a boolean")
    return value


def int_value(value: object, path: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise InputError(f"{path} must be an integer")
    if not minimum <= value <= maximum:
        raise InputError(f"{path} must be between {minimum} and {maximum}")
    return value


def decimal_value(value: object, path: str) -> Decimal:
    """Return a finite, exact decimal value while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise InputError(f"{path} must be a finite JSON number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise InputError(f"{path} must be a finite JSON number") from error
    if not result.is_finite():
        raise InputError(f"{path} must be a finite JSON number")
    return Decimal(0) if result.is_zero() else result


def slug_value(value: object, path: str, *, max_length: int = 80) -> str:
    slug = string_value(value, path, single_line=True, allow_tabs=False)
    if len(slug) > max_length or not _SLUG_RE.fullmatch(slug):
        raise InputError(f"{path} must be a lowercase ASCII slug of at most {max_length} characters")
    return slug
