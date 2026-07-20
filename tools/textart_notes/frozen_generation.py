"""Load and freeze one validated renderer generation."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from tools.whiteboard_automation.batch import CreateCardSpec, encode_create_cards
from tools.textart_notes.core.cell_width import text_width, validate_combining_anchors
from tools.textart_notes.core.contracts import (
    MANIFEST_VERSION,
    MAX_AGENT_REQUEST_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_MANIFEST_CARDS,
    MAX_TOTAL_PAYLOAD_BYTES,
)
from tools.textart_notes.core.models import (
    GLOBAL_MAX_HEIGHT,
    GLOBAL_MAX_WIDTH,
    THEME_NAMES,
    InputError,
)
from tools.textart_notes.core.schema import check_keys, int_value, slug_value
from tools.textart_notes.core.strict_json import StrictJsonError, loads_object


MAX_REQUEST_BYTES = MAX_AGENT_REQUEST_BYTES
MAX_CARDS = MAX_MANIFEST_CARDS
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class ManifestError(Exception):
    """The manifest, payload, path, or geometry is invalid."""


@dataclass(frozen=True)
class MaterialCard:
    logical_id: str
    payload_name: str
    payload: bytes
    payload_sha256: str
    width: int
    height: int
    relative_x: int
    relative_y: int
    absolute_x: int
    absolute_y: int


@dataclass(frozen=True)
class MaterializationPlan:
    manifest_path: str
    manifest_sha256: str
    renderer: str
    theme: str
    origin_x: int
    origin_y: int
    cards: tuple[MaterialCard, ...]
    create_body: bytes


def _integer(value: object, path: str, *, minimum: int, maximum: int) -> int:
    try:
        return int_value(value, path, minimum=minimum, maximum=maximum)
    except InputError as error:
        raise ManifestError(str(error)) from error


def _expect_keys(value: Mapping[str, object], path: str, expected: set[str]) -> None:
    try:
        check_keys(value, path, required=expected, allowed=expected)
    except InputError as error:
        raise ManifestError(str(error)) from error


def _slug(value: object, path: str) -> str:
    try:
        return slug_value(value, path)
    except InputError as error:
        raise ManifestError(str(error)) from error


def open_directory_chain(path: Path, label: str) -> int:
    """Resolve one directory, then open its physical path component by component."""

    try:
        absolute = Path(path).resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(absolute.anchor or os.sep, flags)
        for component in absolute.parts[1:]:
            try:
                next_descriptor = os.open(component, flags | nofollow, dir_fd=descriptor)
            except BaseException:
                os.close(descriptor)
                raise
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except (OSError, RuntimeError) as error:
        raise ManifestError(f"cannot safely open {label}: {error}") from error


def _open_relative_directory_chain(parent: int, components: Sequence[str], label: str) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.dup(parent)
    try:
        for component in components:
            if not component or component in {".", ".."} or "/" in component:
                raise ManifestError(f"invalid {label} component")
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise ManifestError(f"cannot safely open {label}: {error}") from error
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular_fd(descriptor: int, *, limit: int, label: str) -> bytes:
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ManifestError(f"{label} must be a regular file")
        if info.st_size > limit:
            raise ManifestError(f"{label} exceeds {limit} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ManifestError(f"{label} exceeds {limit} bytes")
        return b"".join(chunks)
    except OSError as error:
        raise ManifestError(f"cannot read {label}: {error}") from error


def _decode_json(raw: bytes) -> dict[str, object]:
    try:
        return loads_object(raw, label="manifest")
    except StrictJsonError as error:
        raise ManifestError(str(error)) from error


def _validate_payload(raw: bytes, *, logical_id: str, width: int, height: int) -> None:
    label = f"payload for {logical_id}"
    if not raw:
        raise ManifestError(f"{label} is empty")
    if len(raw) > MAX_REQUEST_BYTES:
        raise ManifestError(f"{label} exceeds {MAX_REQUEST_BYTES} bytes")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise ManifestError(f"{label} must contain exactly one final newline")
    if b"\r" in raw:
        raise ManifestError(f"{label} must not contain carriage returns")
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ManifestError(f"{label} is not strict UTF-8: {error}") from error
    lines = text.split("\n")
    if len(lines) != height:
        raise ManifestError(f"{label} has {len(lines)} lines, expected {height}")
    for index, line in enumerate(lines, start=1):
        try:
            validate_combining_anchors(line)
            cells = text_width(line)
        except ValueError as error:
            raise ManifestError(f"{label} line {index} is invalid: {error}") from error
        if cells > width:
            raise ManifestError(f"{label} line {index} is {cells} cells, exceeds {width}")


def _absolute_coordinate(origin: int, relative: int, extent: int, path: str) -> int:
    value = origin + relative
    if not INT64_MIN <= value <= INT64_MAX:
        raise ManifestError(f"{path} overflows signed 64-bit coordinates")
    if value > INT64_MAX - extent:
        raise ManifestError(f"{path} plus extent overflows signed 64-bit coordinates")
    return value


def load_plan(
    manifest_path: str | Path,
    *,
    origin_x: int,
    origin_y: int,
) -> MaterializationPlan:
    """Open, freeze, and validate one renderer manifest without Board access."""

    if type(origin_x) is not int or not INT64_MIN <= origin_x <= INT64_MAX:
        raise ManifestError("origin_x must be a signed 64-bit integer")
    if type(origin_y) is not int or not INT64_MIN <= origin_y <= INT64_MAX:
        raise ManifestError("origin_y must be a signed 64-bit integer")
    absolute = Path(os.path.abspath(manifest_path))
    parent_fd = open_directory_chain(absolute.parent, "manifest directory")
    manifest_fd = -1
    payload_fd = -1
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            manifest_fd = os.open(absolute.name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise ManifestError(f"cannot safely open manifest: {error}") from error
        manifest_raw = _read_regular_fd(manifest_fd, limit=MAX_MANIFEST_BYTES, label="manifest")
        root = _decode_json(manifest_raw)
        _expect_keys(
            root,
            "manifest",
            {"manifest_version", "generation", "renderer", "theme", "cards"},
        )
        if type(root["manifest_version"]) is not int or root["manifest_version"] != MANIFEST_VERSION:
            raise ManifestError(f"manifest.manifest_version must equal {MANIFEST_VERSION}")
        generation = root["generation"]
        if not isinstance(generation, str) or re.fullmatch(r"[0-9a-f]{64}", generation) is None:
            raise ManifestError("manifest.generation must be a lowercase SHA-256 digest")

        renderer = _slug(root["renderer"], "manifest.renderer")
        theme = root["theme"]
        if theme not in THEME_NAMES:
            raise ManifestError("manifest.theme is not a supported theme")
        raw_cards = root["cards"]
        if not isinstance(raw_cards, list) or not 1 <= len(raw_cards) <= MAX_CARDS:
            raise ManifestError(f"manifest.cards must contain 1..{MAX_CARDS} entries")

        payload_fd = _open_relative_directory_chain(
            parent_fd,
            ("generations", generation, "payloads"),
            "payload directory",
        )

        cards: list[MaterialCard] = []
        seen: set[str] = set()
        total_payload = 0
        for index, value in enumerate(raw_cards):
            path = f"manifest.cards[{index}]"
            if not isinstance(value, dict):
                raise ManifestError(f"{path} must be an object")
            _expect_keys(
                value,
                path,
                {"id", "format", "payload", "width", "height", "x", "y", "metadata"},
            )
            logical_id = _slug(value["id"], f"{path}.id")
            if logical_id in seen:
                raise ManifestError(f"duplicate card id {logical_id!r}")
            seen.add(logical_id)
            if value["format"] != "text-art":
                raise ManifestError(f"{path}.format must equal 'text-art'")
            expected_payload = f"generations/{generation}/payloads/{logical_id}.txt"
            if value["payload"] != expected_payload:
                raise ManifestError(f"{path}.payload must equal {expected_payload!r}")
            width = _integer(value["width"], f"{path}.width", minimum=1, maximum=GLOBAL_MAX_WIDTH)
            height = _integer(value["height"], f"{path}.height", minimum=1, maximum=GLOBAL_MAX_HEIGHT)
            relative_x = _integer(value["x"], f"{path}.x", minimum=0, maximum=INT64_MAX)
            relative_y = _integer(value["y"], f"{path}.y", minimum=0, maximum=INT64_MAX)
            if not isinstance(value["metadata"], dict):
                raise ManifestError(f"{path}.metadata must be an object")
            absolute_x = _absolute_coordinate(origin_x, relative_x, width, f"{path}.x")
            absolute_y = _absolute_coordinate(origin_y, relative_y, height, f"{path}.y")
            payload_name = f"{logical_id}.txt"
            try:
                descriptor = os.open(payload_name, flags, dir_fd=payload_fd)
            except OSError as error:
                raise ManifestError(f"cannot safely open payload for {logical_id}: {error}") from error
            try:
                payload = _read_regular_fd(
                    descriptor,
                    limit=MAX_REQUEST_BYTES,
                    label=f"payload for {logical_id}",
                )
            finally:
                os.close(descriptor)
            _validate_payload(payload, logical_id=logical_id, width=width, height=height)
            total_payload += len(payload)
            if total_payload > MAX_TOTAL_PAYLOAD_BYTES:
                raise ManifestError(f"aggregate payloads exceed {MAX_TOTAL_PAYLOAD_BYTES} bytes")
            cards.append(
                MaterialCard(
                    logical_id,
                    expected_payload,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    width,
                    height,
                    relative_x,
                    relative_y,
                    absolute_x,
                    absolute_y,
                )
            )
        create_body = encode_create_cards(
            CreateCardSpec("text-art", card.absolute_x, card.absolute_y, card.width, card.height)
            for card in cards
        )
        if len(create_body) > MAX_REQUEST_BYTES:
            raise ManifestError(f"create-cards batch exceeds {MAX_REQUEST_BYTES} bytes")
        return MaterializationPlan(
            str(absolute),
            hashlib.sha256(manifest_raw).hexdigest(),
            str(renderer),
            str(theme),
            origin_x,
            origin_y,
            tuple(cards),
            create_body,
        )
    finally:
        if payload_fd >= 0:
            os.close(payload_fd)
        if manifest_fd >= 0:
            os.close(manifest_fd)
        os.close(parent_fd)
