"""One strict JSON decoder for all public textart-notes inputs."""

from __future__ import annotations

import json
from decimal import Decimal


class StrictJsonError(ValueError):
    """JSON was not strict UTF-8, finite, duplicate-free, or object-shaped."""


def loads_object(raw: bytes | str, *, label: str) -> dict[str, object]:
    def reject_constant(value: str) -> object:
        raise StrictJsonError(f"{label} contains non-finite JSON number {value}")

    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}

        for key, value in pairs:
            if key in result:
                raise StrictJsonError(
                    f"{label} contains duplicate JSON object key {key!r}"
                )

            result[key] = value

        return result

    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        value = json.loads(
            text,
            parse_float=Decimal,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except UnicodeDecodeError as error:
        raise StrictJsonError(f"{label} is not strict UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise StrictJsonError(
            f"invalid {label} JSON at line {error.lineno}, column {error.colno}"
        ) from error
    except StrictJsonError:
        raise
    except ValueError as error:
        raise StrictJsonError(f"invalid {label} JSON number: {error}") from error

    if not isinstance(value, dict):
        raise StrictJsonError(f"{label} top-level value must be an object")

    return value
