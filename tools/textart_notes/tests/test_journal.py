from __future__ import annotations

import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.journal_note import render


HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "journal" / "input.json"
GOLDEN = HERE / "golden" / "journal"


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def entry(day: str, entry_id: str) -> dict[str, object]:
    return {"date": day, "id": entry_id, "events": [{"id": f"{entry_id}-event", "text": "完成 work"}], "reflection": "learned", "next_steps": []}


class JournalTests(unittest.TestCase):
    def test_two_theme_goldens_and_determinism(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 72, 50, False)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))

    def test_decimal_metric_is_exact_and_canonical(self) -> None:
        data = fixture()
        data["entries"][0]["metrics"] = [  # type: ignore[index]
            {"label": "negative zero", "value": Decimal("-0.00")},
            {"label": "exponent", "value": Decimal("1.2300E+2")},
            {"label": "precision", "value": Decimal("123456789012345678901234567890.1200")},
        ]
        text = render(data, RenderOptions("ascii", 72, 50, False)).cards[0].text
        self.assertIn("negative zero = 0", text)
        self.assertIn("exponent = 123", text)
        self.assertIn("precision = 123456789012345678901234567890.12", text)
        data["entries"][0]["metrics"][0]["value"] = True  # type: ignore[index]
        with self.assertRaises(InputError):
            render(data, RenderOptions())

    def test_daily_positions_and_single_card(self) -> None:
        data = fixture()
        data["entries"].append(entry("2026-08-02", "second-day"))  # type: ignore[union-attr]
        result = render(data, RenderOptions("ascii", 72, 50, False))
        self.assertEqual(len(result.cards), 2)
        self.assertEqual(result.cards[1].y, result.cards[0].height + 2)
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 72, 50, True))

    def test_weekly_lane_missing_dates_and_week_boundary(self) -> None:
        data = {"journal_title": "Week", "timezone": "UTC", "view": "weekly", "week_start": "monday", "entries": [entry("2026-08-03", "mon"), entry("2026-08-05", "wed")]}
        result = render(data, RenderOptions("unicode-light", 72, 70, False))
        self.assertEqual(len(result.cards), 1)
        self.assertTrue(result.cards[0].metadata["lane_timeline"])
        self.assertEqual(result.cards[0].metadata["dates"], ["2026-08-03", "2026-08-05"])
        cross = copy.deepcopy(data)
        cross["entries"] = [entry("2026-08-02", "sun"), entry("2026-08-03", "mon")]
        self.assertEqual(len(render(cross, RenderOptions("ascii", 72, 70, False)).cards), 2)

    def test_long_day_splits_only_complete_records(self) -> None:
        data = {"journal_title": "Long", "timezone": "UTC", "entries": [{"date": "2026-08-01", "id": "long", "events": [{"id": f"event-{index}", "text": "內容 " * 12} for index in range(5)], "reflection": "repeat me", "next_steps": [{"id": "next", "text": "do it"}]}]}
        result = render(data, RenderOptions("ascii", 50, 20, False))
        self.assertGreater(len(result.cards), 1)
        ids = [item for card in result.cards for item in card.metadata["event_ids"] + card.metadata["next_step_ids"]]
        self.assertEqual(ids, [f"event-{index}" for index in range(5)] + ["next"])
        self.assertTrue(all("REFLECTION repeated" in card.text for card in result.cards))

    def test_closed_view_dates_and_empty_entry(self) -> None:
        data = fixture()
        data["view"] = []
        with self.assertRaises(InputError):
            render(data, RenderOptions())
        duplicate = {"journal_title": "x", "timezone": "UTC", "entries": [entry("2026-08-01", "one"), entry("2026-08-01", "two")]}
        with self.assertRaises(InputError):
            render(duplicate, RenderOptions())


if __name__ == "__main__":
    unittest.main()
