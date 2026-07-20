"""Safe, deterministic payload and manifest materialization."""

from __future__ import annotations

import json
import hashlib
import itertools
import os
import shutil
from pathlib import Path
from typing import Mapping

from .contracts import MANIFEST_VERSION
from .models import RenderOptions, RenderResult, ValidationError
from .validate import validate_result


_temporary_sequence = itertools.count()


def _generation_id(
    result: RenderResult,
    payloads: Mapping[str, bytes] | None = None,
) -> str:
    cards = []

    for card in result.cards:
        cards.append(
            {
                "id": card.logical_id,
                "width": card.width,
                "height": card.height,
                "x": card.x,
                "y": card.y,
                "metadata": dict(card.metadata),
                "payload_sha256": hashlib.sha256(
                    payloads[f"{card.logical_id}.txt"]
                    if payloads is not None
                    else (card.text + "\n").encode("utf-8")
                ).hexdigest(),
            }
        )

    seed = json.dumps(
        {
            "manifest_version": MANIFEST_VERSION,
            "renderer": result.renderer,
            "theme": result.theme,
            "cards": cards,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def manifest_data(
    result: RenderResult,
    generation: str | None = None,
) -> dict[str, object]:
    selected_generation = generation or _generation_id(result)
    cards: list[dict[str, object]] = []
    for card in result.cards:
        cards.append(
            {
                "id": card.logical_id,
                "format": "text-art",
                "payload": (
                    f"generations/{selected_generation}/payloads/"
                    f"{card.logical_id}.txt"
                ),
                "width": card.width,
                "height": card.height,
                "x": card.x,
                "y": card.y,
                "metadata": dict(card.metadata),
            }
        )
    return {
        "manifest_version": MANIFEST_VERSION,
        "generation": selected_generation,
        "renderer": result.renderer,
        "theme": result.theme,
        "cards": cards,
    }


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    descriptor = -1
    temporary = path

    for _ in range(128):
        temporary = path.with_name(
            f".{path.name}.tmp-{os.getpid()}-{next(_temporary_sequence)}"
        )

        try:
            descriptor = os.open(temporary, flags, 0o600)
            break
        except FileExistsError:
            continue
        except OSError as error:
            raise ValidationError(
                f"cannot create safe temporary output {temporary.name}: {error}"
            ) from error

    if descriptor < 0:
        raise ValidationError(
            f"cannot allocate a unique temporary output for {path.name}"
        )

    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _safe_target(root: Path, path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symbolic link")
    if not path.resolve(strict=False).is_relative_to(root):
        raise ValidationError(f"{label} resolves outside output directory")


def _generation_matches(
    directory: Path,
    payloads: dict[str, bytes],
    manifest: bytes,
) -> bool:
    if directory.is_symlink() or not directory.is_dir():
        return False

    expected = {Path("manifest.json"): manifest}
    expected.update(
        {
            Path("payloads") / name: content
            for name, content in payloads.items()
        }
    )
    actual: dict[Path, bytes] = {}

    for path in directory.rglob("*"):
        if path.is_symlink():
            return False

        if path.is_file():
            actual[path.relative_to(directory)] = path.read_bytes()

    return actual == expected


def write_result(result: RenderResult, options: RenderOptions, output_dir: str | Path) -> Path:
    """Write one immutable generation, then atomically switch its manifest."""

    validate_result(result, options)
    root = Path(output_dir)
    if root.is_symlink():
        raise ValidationError("output directory must not be a symbolic link")
    if root.exists() and not root.is_dir():
        raise ValueError(f"output path is not a directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve()
    payloads = {
        f"{card.logical_id}.txt": (card.text + "\n").encode("utf-8")
        for card in result.cards
    }
    generation = _generation_id(result, payloads)
    data = manifest_data(result, generation)
    manifest_bytes = (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    generations = root / "generations"
    _safe_target(resolved_root, generations, "generation directory")

    if generations.exists() and not generations.is_dir():
        raise ValidationError("generation target exists and is not a directory")

    generations.mkdir(exist_ok=True)
    _safe_target(resolved_root, generations, "generation directory")
    final_generation = generations / generation
    _safe_target(resolved_root, final_generation, "generation")

    if final_generation.exists():
        if not _generation_matches(
            final_generation,
            payloads,
            manifest_bytes,
        ):
            raise ValidationError(
                f"existing generation {generation} does not match its digest"
            )
    else:
        temporary = generations / (
            f".{generation}.tmp-{os.getpid()}-{next(_temporary_sequence)}"
        )
        _safe_target(resolved_root, temporary, "temporary generation")

        try:
            temporary.mkdir(mode=0o700)
            payload_dir = temporary / "payloads"
            payload_dir.mkdir(mode=0o700)

            for name, content in payloads.items():
                _atomic_write(
                    payload_dir / name,
                    content,
                )

            _atomic_write(
                temporary / "manifest.json",
                manifest_bytes,
            )
            _fsync_directory(payload_dir)
            _fsync_directory(temporary)
            try:
                temporary.rename(final_generation)
            except OSError as error:
                # Another writer may have published the same content-addressed
                # generation after our existence check.  Accept only an exact,
                # immutable match; every other collision remains an error.
                if not _generation_matches(
                    final_generation,
                    payloads,
                    manifest_bytes,
                ):
                    raise ValidationError(
                        f"cannot publish generation {generation}: {error}"
                    ) from error
                shutil.rmtree(temporary)
            _fsync_directory(generations)
        except BaseException:
            if temporary.exists() and not temporary.is_symlink():
                shutil.rmtree(temporary)
            raise

    manifest_path = root / "manifest.json"
    _safe_target(resolved_root, manifest_path, "manifest target")
    _atomic_write(manifest_path, manifest_bytes)
    return manifest_path
