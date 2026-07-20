"""Typed contracts for mind-map artifacts and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExpectedCard:
    logical_id: str
    card_id: int
    card_format: str
    x: int
    y: int
    width: int
    height: int
    payload_path: Path
    payload: bytes


@dataclass(frozen=True)
class ExpectedEdge:
    source_logical_id: str
    target_logical_id: str
    source_card_id: int
    target_card_id: int
    expected_present: bool
    expected_edge_id: int | None
    recorded_error: str | None


@dataclass(frozen=True)
class ExpectedRun:
    run_dir: Path
    cards: tuple[ExpectedCard, ...]
    edges: tuple[ExpectedEdge, ...]
    state: dict[str, str]
    artifact_digest: str

    @property
    def card_ids(self) -> frozenset[int]:
        return frozenset(card.card_id for card in self.cards)


@dataclass(frozen=True)
class PreflightRun:
    run_dir: Path
    cards: tuple[tuple[str, str, int, int, int, int, Path, bytes], ...]
    edges: tuple[tuple[str, str], ...]
    state: dict[str, str]
    artifact_digest: str


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            **self.details,
        }


class ValidationInputError(Exception):
    """Invalid verifier input or run artifact contract."""


class RevisionChangedError(Exception):
    """The live board changed while verification was running."""
