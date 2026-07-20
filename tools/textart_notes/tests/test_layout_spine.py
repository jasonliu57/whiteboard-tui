from __future__ import annotations

import unittest

from tools.textart_notes.layouts.spine import SpineItem, place_spine


class SpineLayoutTests(unittest.TestCase):
    def test_order_alignment_effect_entry_and_determinism(self) -> None:
        items = (
            SpineItem("top-a", "top", 5, 4),
            SpineItem("bottom", "bottom", 6, 3),
            SpineItem("top-b", "top", 4, 2),
        )
        first = place_spine(
            items,
            arrow_width=2,
            effect_width=10,
            effect_height=5,
            effect_entry_row=2,
        )
        self.assertEqual(
            first,
            place_spine(
                items,
                arrow_width=2,
                effect_width=10,
                effect_height=5,
                effect_entry_row=2,
            ),
        )
        self.assertEqual((first.width, first.height, first.spine_y), (27, 8, 4))
        self.assertEqual((first.effect_x, first.effect_y), (17, 2))
        self.assertEqual(
            [(item.key, item.x, item.y, item.joint_x) for item in first.placements],
            [("top-a", 0, 0, 4), ("bottom", 5, 5, 10), ("top-b", 11, 2, 14)],
        )

    def test_rectangles_are_disjoint_and_touch_only_their_spine_segment(self) -> None:
        layout = place_spine(
            (
                SpineItem("a", "top", 8, 5),
                SpineItem("b", "bottom", 7, 6),
                SpineItem("c", "top", 9, 3),
            ),
            arrow_width=2,
            effect_width=12,
            effect_height=4,
            effect_entry_row=2,
        )
        for index, item in enumerate(layout.placements):
            self.assertEqual(item.joint_x, item.x + item.width - 1)
            if item.side == "top":
                self.assertEqual(item.y + item.height, layout.spine_y)
            else:
                self.assertEqual(item.y, layout.spine_y + 1)
            for other in layout.placements[index + 1 :]:
                self.assertFalse(
                    item.x < other.x + other.width
                    and other.x < item.x + item.width
                    and item.y < other.y + other.height
                    and other.y < item.y + item.height
                )

    def test_invalid_inputs_are_rejected(self) -> None:
        arguments = {
            "arrow_width": 2,
            "effect_width": 8,
            "effect_height": 3,
            "effect_entry_row": 1,
        }
        with self.assertRaises(ValueError):
            place_spine((), **arguments)
        with self.assertRaises(ValueError):
            place_spine(
                (SpineItem("a", "top", 2, 2), SpineItem("a", "bottom", 2, 2)),
                **arguments,
            )
        for item in (
            SpineItem("a", "left", 2, 2),
            SpineItem("a", "top", 0, 2),
            SpineItem("a", "bottom", 2, 0),
        ):
            with self.subTest(item=item), self.assertRaises(ValueError):
                place_spine((item,), **arguments)
        with self.assertRaises(ValueError):
            place_spine(
                (SpineItem("a", "top", 2, 2),),
                arrow_width=2,
                effect_width=8,
                effect_height=3,
                effect_entry_row=3,
            )


if __name__ == "__main__":
    unittest.main()
