"""Deterministic comparison of expected, live, baseline, and disk states."""

from __future__ import annotations

import hashlib

from tools.whiteboard_automation.models import (
    CanonicalSnapshot,
    LiveCard,
    LiveEdge,
    LiveStatus,
)
from .models import ExpectedRun, Issue


def first_difference(left: bytes, right: bytes) -> int:
    for index, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte != right_byte:
            return index
    return min(len(left), len(right))


def compare_cards(
    expected: ExpectedRun,
    live_cards: dict[int, LiveCard],
) -> list[Issue]:
    issues: list[Issue] = []
    for card in expected.cards:
        live = live_cards.get(card.card_id)
        common = {"logical_id": card.logical_id, "card_id": card.card_id}
        if live is None:
            issues.append(Issue("CARD_MISSING", "Expected card is missing", common))
            continue
        fields = (
            ("format", card.card_format, live.card_format),
            ("x", card.x, live.x),
            ("y", card.y, live.y),
            ("width", card.width, live.width),
            ("height", card.height, live.height),
        )
        for field, wanted, observed in fields:
            if wanted != observed:
                issues.append(
                    Issue(
                        "CARD_METADATA_MISMATCH",
                        f"Card {field} does not match",
                        {**common, "field": field, "expected": wanted, "actual": observed},
                    )
                )
        if card.payload != live.payload:
            issues.append(
                Issue(
                    "CARD_PAYLOAD_MISMATCH",
                    "Card payload bytes do not match",
                    {
                        **common,
                        "expected_bytes": len(card.payload),
                        "actual_bytes": len(live.payload),
                        "first_difference": first_difference(card.payload, live.payload),
                        "expected_sha256": hashlib.sha256(card.payload).hexdigest(),
                        "actual_sha256": hashlib.sha256(live.payload).hexdigest(),
                    },
                )
            )
    return issues


def compare_edges(
    expected: ExpectedRun,
    live_edges: dict[int, LiveEdge],
) -> list[Issue]:
    issues: list[Issue] = []
    allowed: set[int] = set()
    for edge in expected.edges:
        common = {
            "from": edge.source_logical_id,
            "to": edge.target_logical_id,
            "source_card_id": edge.source_card_id,
            "target_card_id": edge.target_card_id,
        }
        matching = [
            live
            for live in live_edges.values()
            if live.source_card_id == edge.source_card_id
            and live.target_card_id == edge.target_card_id
        ]
        reverse = [
            live
            for live in live_edges.values()
            if live.source_card_id == edge.target_card_id
            and live.target_card_id == edge.source_card_id
        ]
        if edge.expected_present:
            if edge.expected_edge_id is None:
                issues.append(Issue("EDGE_RESULT_INVALID", "Successful edge lacks an ID", common))
                continue
            live = live_edges.get(edge.expected_edge_id)
            if live is None:
                details = dict(common)
                if matching:
                    details["actual_edge_ids"] = [item.edge_id for item in matching]
                issues.append(Issue("EDGE_MISSING", "Expected successful edge is missing", details))
                continue
            allowed.add(live.edge_id)
            if (
                live.source_card_id != edge.source_card_id
                or live.target_card_id != edge.target_card_id
            ):
                issues.append(
                    Issue(
                        "EDGE_ENDPOINT_MISMATCH",
                        "Recorded edge ID has different directed endpoints",
                        {
                            **common,
                            "edge_id": live.edge_id,
                            "actual_source": live.source_card_id,
                            "actual_target": live.target_card_id,
                        },
                    )
                )
            if len(matching) > 1:
                issues.append(
                    Issue(
                        "EDGE_DUPLICATE",
                        "Multiple live edges have the same directed endpoints",
                        {**common, "edge_ids": [item.edge_id for item in matching]},
                    )
                )
        else:
            if matching:
                issues.append(
                    Issue(
                        "FAILED_EDGE_PRESENT",
                        "An edge recorded as failed exists on the board",
                        {**common, "edge_ids": [item.edge_id for item in matching]},
                    )
                )
            if reverse:
                issues.append(
                    Issue(
                        "REVERSED_EDGE_PRESENT",
                        "A reversed edge exists for a failed declaration",
                        {**common, "edge_ids": [item.edge_id for item in reverse]},
                    )
                )

    for live in live_edges.values():
        if (
            live.source_card_id in expected.card_ids
            or live.target_card_id in expected.card_ids
        ) and live.edge_id not in allowed:
            issues.append(
                Issue(
                    "EXTRA_OWNED_EDGE",
                    "Live edge touching an owned card was not declared successful",
                    {
                        "edge_id": live.edge_id,
                        "source_card_id": live.source_card_id,
                        "target_card_id": live.target_card_id,
                    },
                )
            )
    return issues


def compare_status(
    expected: ExpectedRun,
    status: LiveStatus,
    baseline: CanonicalSnapshot | None,
) -> list[Issue]:
    successful_edges = sum(edge.expected_present for edge in expected.edges)
    minimum_cards = len(expected.cards)
    minimum_edges = successful_edges
    if baseline is not None:
        collisions = expected.card_ids & baseline.cards.keys()
        if not collisions:
            minimum_cards += baseline.live_cards
        expected_edge_ids = {
            edge.expected_edge_id
            for edge in expected.edges
            if edge.expected_present and edge.expected_edge_id is not None
        }
        if not (expected_edge_ids & baseline.edges.keys()):
            minimum_edges += baseline.live_edges
    issues: list[Issue] = []
    if status.live_cards < minimum_cards:
        issues.append(
            Issue(
                "CARD_COUNT_TOO_SMALL",
                "Live card count is smaller than the verified scope",
                {"minimum": minimum_cards, "actual": status.live_cards},
            )
        )
    if status.live_edges < minimum_edges:
        issues.append(
            Issue(
                "EDGE_COUNT_TOO_SMALL",
                "Live edge count is smaller than the verified scope",
                {"minimum": minimum_edges, "actual": status.live_edges},
            )
        )
    return issues


def compare_owned_snapshot(
    expected: ExpectedRun,
    final: CanonicalSnapshot,
) -> list[Issue]:
    issues: list[Issue] = []
    for card in expected.cards:
        observed = final.cards.get(card.card_id)
        if observed is None:
            issues.append(
                Issue(
                    "SNAPSHOT_CARD_MISSING",
                    "Owned card is absent from the canonical snapshot",
                    {"logical_id": card.logical_id, "card_id": card.card_id},
                )
            )
            continue
        expected_values = (
            card.card_format,
            card.x,
            card.y,
            card.width,
            card.height,
            card.payload,
        )
        observed_values = (
            observed.card_format,
            observed.x,
            observed.y,
            observed.width,
            observed.height,
            observed.payload,
        )
        if expected_values != observed_values:
            issues.append(
                Issue(
                    "SNAPSHOT_CARD_MISMATCH",
                    "Owned card differs in canonical snapshot",
                    {"logical_id": card.logical_id, "card_id": card.card_id},
                )
            )
    return issues


def compare_baseline(
    baseline: CanonicalSnapshot,
    final: CanonicalSnapshot,
    expected: ExpectedRun,
) -> list[Issue]:
    issues: list[Issue] = []
    owned = expected.card_ids
    expected_edge_ids = {
        edge.expected_edge_id
        for edge in expected.edges
        if edge.expected_present and edge.expected_edge_id is not None
    }
    expected_card_slots = baseline.card_slots + len(expected.cards)
    expected_edge_slots = baseline.edge_slots + len(expected_edge_ids)
    if final.card_slots != expected_card_slots:
        issues.append(
            Issue(
                "CARD_SLOT_COUNT_MISMATCH",
                "Card slot growth does not match this materialization",
                {"expected": expected_card_slots, "actual": final.card_slots},
            )
        )
    if final.edge_slots != expected_edge_slots:
        issues.append(
            Issue(
                "EDGE_SLOT_COUNT_MISMATCH",
                "Edge slot growth does not match successful declared edges",
                {"expected": expected_edge_slots, "actual": final.edge_slots},
            )
        )
    for card_id in sorted(owned & baseline.cards.keys()):
        issues.append(
            Issue(
                "BASELINE_OWNERSHIP_COLLISION",
                "Owned CardId already existed in the baseline",
                {"card_id": card_id},
            )
        )
    for card_id, before in baseline.cards.items():
        after = final.cards.get(card_id)
        if after is None:
            issues.append(
                Issue("UNRELATED_CARD_REMOVED", "Baseline card was removed", {"card_id": card_id})
            )
        elif before.raw_record != after.raw_record:
            issues.append(
                Issue("UNRELATED_CARD_CHANGED", "Baseline card was modified", {"card_id": card_id})
            )
    for card_id in sorted(set(final.cards) - set(baseline.cards) - owned):
        issues.append(
            Issue("EXTRA_UNOWNED_CARD", "Unexpected unowned card was added", {"card_id": card_id})
        )
    for edge_id in sorted(expected_edge_ids & baseline.edges.keys()):
        issues.append(
            Issue(
                "BASELINE_EDGE_ID_COLLISION",
                "Recorded new EdgeId already existed in baseline",
                {"edge_id": edge_id},
            )
        )
    for edge_id, before in baseline.edges.items():
        after = final.edges.get(edge_id)
        if after is None:
            issues.append(
                Issue("UNRELATED_EDGE_REMOVED", "Baseline edge was removed", {"edge_id": edge_id})
            )
        elif before.raw_record != after.raw_record:
            issues.append(
                Issue("UNRELATED_EDGE_CHANGED", "Baseline edge was modified", {"edge_id": edge_id})
            )
    for edge_id in sorted(set(final.edges) - set(baseline.edges) - expected_edge_ids):
        issues.append(
            Issue("EXTRA_UNOWNED_EDGE", "Unexpected unowned edge was added", {"edge_id": edge_id})
        )
    if baseline.glyphs.keys() != final.glyphs.keys():
        issues.append(
            Issue(
                "UNRELATED_GLYPHS_CHANGED",
                "Glyph positions changed relative to baseline",
                {
                    "baseline": len(baseline.glyphs),
                    "actual": len(final.glyphs),
                },
            )
        )
    else:
        for position, before in baseline.glyphs.items():
            if before.raw_record != final.glyphs[position].raw_record:
                issues.append(
                    Issue(
                        "UNRELATED_GLYPHS_CHANGED",
                        "Glyph content changed relative to baseline",
                        {"x": position[0], "y": position[1]},
                    )
                )
                break
    return issues


def compare_live_and_disk(
    live: CanonicalSnapshot,
    disk: CanonicalSnapshot,
) -> list[Issue]:
    if live.raw == disk.raw:
        return []
    return [
        Issue(
            "LIVE_DISK_MISMATCH",
            "Canonical live and disk snapshots differ",
            {"live_sha256": live.digest, "disk_sha256": disk.digest},
        )
    ]
