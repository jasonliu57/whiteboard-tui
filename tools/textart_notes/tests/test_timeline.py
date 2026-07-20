from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.timeline_note import render


HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "timeline" / "input.json"
GOLDEN = HERE / "golden" / "timeline"


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def timestamp_data(*, spacing: str = "proportional", second: str = "2026-01-01T00:00:01.000001Z") -> dict[str, object]:
    timeline: dict[str, object] = {"kind": "timestamp", "spacing": spacing, "seconds_per_cell": 1}
    if spacing == "compressed":
        timeline["max_gap_cells"] = 2
    return {
        "schema": "timeline-note/v1", "title": "UTC events", "timeline": timeline,
        "events": [
            {"id": "first", "timestamp": "2026-01-01T00:00:00Z", "label": "First", "description": "start"},
            {"id": "second", "timestamp": second, "label": "第二", "description": "finish"},
        ],
    }


class TimelineTests(unittest.TestCase):
    def test_two_theme_goldens_and_determinism(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 84, 50, False)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))
            self.assertEqual(result.cards[0].metadata["engine"], "lane-timeline")

    def test_exact_proportional_and_compressed_gaps(self) -> None:
        proportional = render(timestamp_data(), RenderOptions("ascii", 64, 40, False))
        self.assertIn("normalized_timezone", proportional.cards[0].metadata)
        compressed = timestamp_data(spacing="compressed", second="2026-01-01T00:01:00Z")
        text = render(compressed, RenderOptions("ascii", 64, 40, False)).cards[0].text
        self.assertIn("omitted=58 cells", text)
        self.assertIn("delta=00:01:00", text)

    def test_proportional_guard_and_civil_date_edges(self) -> None:
        with self.assertRaises(FitError):
            render(timestamp_data(second="2026-01-01T00:00:25Z"), RenderOptions("ascii", 64, 60, False))
        for invalid in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"):
            data = timestamp_data(second="2026-01-01T00:00:01Z")
            data["events"][0]["timestamp"] = invalid  # type: ignore[index]
            with self.assertRaises(InputError):
                render(data, RenderOptions())
        early = timestamp_data(second="0001-01-01T00:00:01Z")
        early["events"] = [early["events"][1]]  # type: ignore[index]
        rendered = render(early, RenderOptions("ascii", 64, 40, False))
        self.assertTrue(rendered.cards[0].metadata["range_start"].startswith("0001-"))

    def test_atomic_group_pagination_and_single_card(self) -> None:
        data = fixture()
        data["events"][1]["stage_id"] = "discover"  # type: ignore[index]
        result = render(data, RenderOptions("ascii", 58, 19, False))
        owners = [card for card in result.cards if "brief" in card.metadata["event_ids"] or "spike" in card.metadata["event_ids"]]
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0].metadata["event_ids"][:2], ["brief", "spike"])
        self.assertEqual([card.x for card in result.cards], [index * 62 for index in range(len(result.cards))])
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 58, 19, True))

    def test_closed_schema_order_and_slug_errors(self) -> None:
        bad = fixture()
        bad["events"][0]["id"] = "bad_id"  # type: ignore[index]
        with self.assertRaises(InputError):
            render(bad, RenderOptions())
        reverse = timestamp_data(second="2025-12-31T23:59:59Z")
        with self.assertRaises(InputError):
            render(reverse, RenderOptions())
        malformed = timestamp_data()
        malformed["timeline"] = {"kind": "timestamp", "spacing": "compressed", "seconds_per_cell": 1}
        with self.assertRaises(InputError):
            render(malformed, RenderOptions())


if __name__ == "__main__":
    unittest.main()
