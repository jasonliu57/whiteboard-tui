"""Revision-guarded, journaled materialization for compiled mind-map runs."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from tools.whiteboard_automation.batch import CreateCardSpec, encode_create_cards

from .artifacts import (
    CardRow,
    MindMapInputError,
    PreflightRun,
    atomic_write,
    atomic_write_bytes,
    load_card_map,
    load_cards,
    load_preflight_run,
    resolve_materialized_payloads,
    resolve_run_path,
)
from tools.whiteboard_automation.errors import CtlError, ProtocolError
from tools.whiteboard_automation.client import WhiteboardCtlClient
from tools.whiteboard_automation.models import LiveCard
from .models import RevisionChangedError
from .persistence import load_baseline_evidence, update_state


JOURNAL_SCHEMA = 1


@dataclass(frozen=True)
class MaterializationOutcome:
    revision: int
    cards: int
    successful_edges: int
    failed_edges: int


class MaterializationJournal:
    def __init__(self, path: Path, artifact_digest: str) -> None:
        self.path = path
        self.events: list[dict[str, object]] = []
        if path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                self.events = [json.loads(line) for line in lines if line]
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise MindMapInputError(f"{path}: invalid materialization journal: {error}") from error
            if not self.events:
                raise MindMapInputError(f"{path}: empty materialization journal")
            for index, event in enumerate(self.events):
                if not isinstance(event, dict) or event.get("sequence") != index:
                    raise MindMapInputError(f"{path}: invalid journal sequence at {index}")
            header = self.events[0]
            if (
                header.get("event") != "START"
                or header.get("schema") != JOURNAL_SCHEMA
                or header.get("artifact_digest") != artifact_digest
            ):
                raise MindMapInputError(
                    f"{path}: journal belongs to a different artifact revision"
                )
        else:
            self.add(
                "START",
                schema=JOURNAL_SCHEMA,
                artifact_digest=artifact_digest,
            )

    def add(self, event: str, **details: object) -> dict[str, object]:
        record: dict[str, object] = {
            "sequence": len(self.events),
            "event": event,
            **details,
        }
        self.events.append(record)
        serialized = "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for item in self.events
        )
        atomic_write(self.path, serialized)
        return record

    def matching(self, event: str, **fields: object) -> list[dict[str, object]]:
        return [
            item
            for item in self.events
            if item.get("event") == event
            and all(item.get(key) == value for key, value in fields.items())
        ]

    def last_revision(self) -> int | None:
        for event in reversed(self.events):
            revision = event.get("revision")
            if isinstance(revision, int) and revision >= 0:
                return revision
        return None


@contextmanager
def materialization_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise MindMapInputError(
                f"another materialization process holds {path}"
            ) from error
        yield
    finally:
        os.close(descriptor)


def _build_batch(preflight: PreflightRun) -> bytes:
    return encode_create_cards(
        CreateCardSpec(card_format, x, y, width, height)
        for _, card_format, x, y, width, height, _, _ in preflight.cards
    )


def _baseline_revision(run_dir: Path) -> int:
    evidence = load_baseline_evidence(run_dir, required=True)
    assert evidence is not None
    return evidence[1]


def _write_card_map(path: Path, cards: list[CardRow], first_card_id: int) -> dict[str, int]:
    mapping = {
        card.logical_id: first_card_id + card.index
        for card in cards
    }
    lines = ["id\tcard_id"]
    lines.extend(f"{card.logical_id}\t{mapping[card.logical_id]}" for card in cards)
    atomic_write(path, "\n".join(lines) + "\n")
    return mapping


def _load_or_restore_card_map(
    run_dir: Path,
    cards: list[CardRow],
    journal: MaterializationJournal,
) -> dict[str, int]:
    created = journal.matching("CREATE_OK")
    if len(created) != 1:
        if journal.matching("CREATE_BEGIN"):
            raise MindMapInputError(
                "card creation was interrupted before its response was journaled; "
                "refusing to create a second batch"
            )
        raise MindMapInputError("materialization journal has no completed card batch")
    event = created[0]
    first = event.get("first_card_id")
    count = event.get("count")
    if not isinstance(first, int) or count != len(cards):
        raise MindMapInputError("materialization journal has an invalid CREATE_OK record")
    expected = {card.logical_id: first + card.index for card in cards}
    path = run_dir / "card-map.tsv"
    if not path.exists():
        return _write_card_map(path, cards, first)
    actual = load_card_map(path, set(expected))
    if actual != expected:
        raise MindMapInputError("card-map.tsv differs from the journaled card batch")
    return actual


def _card_metadata_matches(card: CardRow, card_id: int, live: LiveCard, position: tuple[int, int]) -> bool:
    x, y = position
    return (
        live.card_id == card_id
        and live.card_format == card.card_format
        and live.x == x
        and live.y == y
        and live.width == card.width
        and live.height == card.height
    )


def _write_replace_results(
    path: Path,
    cards: list[CardRow],
    journal: MaterializationJournal,
) -> None:
    lines = ["id\tcard_id\tstatus\trevision"]
    for card in cards:
        completed = journal.matching("REPLACE_OK", logical_id=card.logical_id)
        if completed:
            event = completed[-1]
            lines.append(
                f"{card.logical_id}\t{event['card_id']}\tOK\t{event['revision']}"
            )
    atomic_write(path, "\n".join(lines) + "\n")


def _replace_cards(
    preflight: PreflightRun,
    cards: list[CardRow],
    mapping: dict[str, int],
    payloads: dict[str, bytes],
    client: WhiteboardCtlClient,
    journal: MaterializationJournal,
    revision: int,
) -> int:
    positions = {
        logical_id: (x, y)
        for logical_id, _, x, y, _, _, _, _ in preflight.cards
    }
    results_path = preflight.run_dir / "work" / "replace-results.tsv"
    for card in cards:
        card_id = mapping[card.logical_id]
        payload = payloads[card.logical_id]
        completed = journal.matching("REPLACE_OK", logical_id=card.logical_id)
        live = client.get_card(card_id)
        if live.revision != revision:
            raise RevisionChangedError(
                f"card {card_id} read revision {live.revision}, expected {revision}"
            )
        if not _card_metadata_matches(card, card_id, live, positions[card.logical_id]):
            raise MindMapInputError(
                f"card {card_id} no longer matches the journaled batch geometry"
            )
        if completed:
            if live.payload != payload:
                raise MindMapInputError(
                    f"card {card_id} differs from its journaled replacement"
                )
            continue
        pending = journal.matching("REPLACE_BEGIN", logical_id=card.logical_id)
        if pending:
            if live.payload != payload:
                raise MindMapInputError(
                    f"replacement of card {card_id} was interrupted with an uncertain outcome"
                )
            journal.add(
                "REPLACE_OK",
                logical_id=card.logical_id,
                card_id=card_id,
                revision=revision,
                recovered=True,
            )
            _write_replace_results(results_path, cards, journal)
            continue
        if live.payload == payload:
            journal.add(
                "REPLACE_OK",
                logical_id=card.logical_id,
                card_id=card_id,
                revision=revision,
                already_matched=True,
            )
            _write_replace_results(results_path, cards, journal)
            continue
        journal.add(
            "REPLACE_BEGIN",
            logical_id=card.logical_id,
            card_id=card_id,
            expected_revision=revision,
        )
        response = client.replace_card(
            card_id,
            revision,
            card.width,
            card.height,
            payload,
        )
        if response.object_id != card_id:
            raise ProtocolError(
                f"REPLACE_CARD returned CardId {response.object_id}, expected {card_id}"
            )
        revision = response.revision
        journal.add(
            "REPLACE_OK",
            logical_id=card.logical_id,
            card_id=card_id,
            revision=revision,
        )
        _write_replace_results(results_path, cards, journal)
        update_state(
            preflight.run_dir / "state.tsv",
            {"revision": str(revision), "dirty": "1", "saved": "0"},
        )
    return revision


def _edge_results(journal: MaterializationJournal) -> dict[tuple[str, str], dict[str, object]]:
    results: dict[tuple[str, str], dict[str, object]] = {}
    for event in journal.events:
        if event.get("event") != "EDGE_RESULT":
            continue
        source = event.get("from")
        target = event.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            raise MindMapInputError("materialization journal has an invalid EDGE_RESULT")
        pair = (source, target)
        if pair in results:
            raise MindMapInputError(f"materialization journal repeats edge {source}->{target}")
        results[pair] = event
    return results


def _write_edge_results(
    path: Path,
    declared: tuple[tuple[str, str], ...],
    results: dict[tuple[str, str], dict[str, object]],
) -> None:
    lines = ["from\tto\tstatus\tedge_id\terror"]
    for pair in declared:
        event = results.get(pair)
        if event is None:
            continue
        if event["status"] == "OK":
            lines.append(f"{pair[0]}\t{pair[1]}\tOK\t{event['edge_id']}\t")
        else:
            error = str(event["error"])
            if any(character in error for character in "\t\r\n"):
                raise MindMapInputError(f"edge error is not TSV-safe: {error!r}")
            lines.append(f"{pair[0]}\t{pair[1]}\tERROR\t\t{error}")
    atomic_write(path, "\n".join(lines) + "\n")


def _connect_edges(
    preflight: PreflightRun,
    mapping: dict[str, int],
    client: WhiteboardCtlClient,
    journal: MaterializationJournal,
    revision: int,
) -> tuple[int, dict[tuple[str, str], dict[str, object]]]:
    results = _edge_results(journal)
    partial = preflight.run_dir / "work" / "edge-results.partial.tsv"
    for source, target in preflight.edges:
        pair = (source, target)
        if pair in results:
            continue
        pending = journal.matching("EDGE_BEGIN", **{"from": source, "to": target})
        if pending:
            response = client.edges(mapping[source])
            if response.revision != revision:
                raise RevisionChangedError(
                    f"edge recovery read revision {response.revision}, expected {revision}"
                )
            matches = [
                edge
                for edge in response.edges
                if edge.source_card_id == mapping[source]
                and edge.target_card_id == mapping[target]
            ]
            if len(matches) == 1:
                event = journal.add(
                    "EDGE_RESULT",
                    **{"from": source, "to": target},
                    status="OK",
                    edge_id=matches[0].edge_id,
                    revision=revision,
                    recovered=True,
                )
            elif not matches:
                event = journal.add(
                    "EDGE_RESULT",
                    **{"from": source, "to": target},
                    status="ERROR",
                    edge_id=None,
                    error="INTERRUPTED_UNCERTAIN",
                    revision=revision,
                )
            else:
                raise MindMapInputError(
                    f"interrupted edge {source}->{target} produced duplicates"
                )
            results[pair] = event
            _write_edge_results(partial, preflight.edges, results)
            continue
        journal.add(
            "EDGE_BEGIN",
            **{"from": source, "to": target},
            source_card_id=mapping[source],
            target_card_id=mapping[target],
            expected_revision=revision,
        )
        try:
            response = client.connect(mapping[source], mapping[target], revision)
        except CtlError as error:
            exact = error.stderr.decode("utf-8", errors="replace").rstrip("\r\n")
            if not exact.startswith("ERR ") or exact.startswith("ERR stale_revision "):
                raise
            event = journal.add(
                "EDGE_RESULT",
                **{"from": source, "to": target},
                status="ERROR",
                edge_id=None,
                error=exact,
                revision=revision,
            )
        else:
            revision = response.revision
            event = journal.add(
                "EDGE_RESULT",
                **{"from": source, "to": target},
                status="OK",
                edge_id=response.object_id,
                error=None,
                revision=revision,
            )
        results[pair] = event
        _write_edge_results(partial, preflight.edges, results)
        update_state(
            preflight.run_dir / "state.tsv",
            {"revision": str(revision), "dirty": "1", "saved": "0"},
        )
    return revision, results


def run_materialization(
    preflight: PreflightRun,
    client: WhiteboardCtlClient,
) -> MaterializationOutcome:
    run_dir = preflight.run_dir
    work = run_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    with materialization_lock(work / "materialization.lock"):
        current_preflight = load_preflight_run(run_dir)
        if current_preflight.artifact_digest != preflight.artifact_digest:
            raise MindMapInputError(
                "materialization inputs changed after preflight; rerun the fixed command"
            )
        preflight = current_preflight
        cards = load_cards(resolve_run_path(run_dir, "cards.tsv", context="cards.tsv"))
        batch = _build_batch(preflight)
        atomic_write_bytes(work / "create.cards", batch)
        journal = MaterializationJournal(
            work / "materialization.jsonl",
            preflight.artifact_digest,
        )
        created = journal.matching("CREATE_OK")
        if not created:
            if journal.matching("CREATE_BEGIN"):
                raise MindMapInputError(
                    "card creation has an unresolved prior attempt; refusing duplicate creation"
                )
            status = client.status()
            baseline_revision = _baseline_revision(run_dir)
            if status.revision != baseline_revision:
                raise RevisionChangedError(
                    f"live revision {status.revision} changed since baseline {baseline_revision}"
                )
            update_state(
                run_dir / "state.tsv",
                {
                    "phase": "materializing",
                    "revision": str(status.revision),
                    "dirty": "1" if status.dirty else "0",
                    "saved": "0",
                    "materialization_artifact_digest": preflight.artifact_digest,
                },
            )
            journal.add("CREATE_BEGIN", expected_revision=status.revision, count=len(cards))
            response = client.create_cards(batch, status.revision)
            if response.count != len(cards):
                raise ProtocolError(
                    f"CREATE_CARDS returned count {response.count}, expected {len(cards)}"
                )
            journal.add(
                "CREATE_OK",
                revision=response.revision,
                count=response.count,
                first_card_id=response.first_card_id,
            )
            revision = response.revision
        else:
            if len(created) != 1 or not isinstance(created[0].get("revision"), int):
                raise MindMapInputError("materialization journal has invalid CREATE_OK records")
            revision = int(created[0]["revision"])

        mapping = _load_or_restore_card_map(run_dir, cards, journal)
        current = client.status()
        latest = journal.last_revision()
        last_event = journal.events[-1].get("event")
        recoverable_increment = (
            latest is not None
            and current.revision == latest + 1
            and last_event in {"REPLACE_BEGIN", "EDGE_BEGIN"}
        )
        if latest is None or (current.revision != latest and not recoverable_increment):
            raise RevisionChangedError(
                f"live revision {current.revision} differs from journal revision {latest}"
            )
        revision = current.revision
        payloads = resolve_materialized_payloads(run_dir, cards, mapping)
        revision = _replace_cards(
            preflight,
            cards,
            mapping,
            payloads,
            client,
            journal,
            revision,
        )
        revision, edge_results = _connect_edges(
            preflight,
            mapping,
            client,
            journal,
            revision,
        )
        if len(edge_results) != len(preflight.edges):
            raise MindMapInputError("not every declared edge has a terminal result")
        final_edge_path = run_dir / "edge-results.tsv"
        _write_edge_results(final_edge_path, preflight.edges, edge_results)
        final_status = client.status()
        if final_status.revision != revision:
            raise RevisionChangedError(
                f"live revision changed {revision}->{final_status.revision} after materialization"
            )
        journal.add(
            "COMPLETE",
            revision=revision,
            cards=len(cards),
            edges=len(edge_results),
        )
        update_state(
            run_dir / "state.tsv",
            {
                "phase": "materialized",
                "revision": str(revision),
                "dirty": "1" if final_status.dirty else "0",
                "saved": "0",
            },
        )
        successes = sum(event.get("status") == "OK" for event in edge_results.values())
        return MaterializationOutcome(
            revision=revision,
            cards=len(cards),
            successful_edges=successes,
            failed_edges=len(edge_results) - successes,
        )
