from __future__ import annotations

import unittest

from tools.whiteboard_automation.batch import (
    CreateCardSpec,
    decode_create_cards,
    encode_create_cards,
    encode_delete_cards,
)


class BatchTests(unittest.TestCase):
    def test_create_batch_round_trip_is_canonical(self) -> None:
        cards = (
            CreateCardSpec("note", -10, 20, 12, 5),
            CreateCardSpec("text-art", 4, 8, 20, 6),
        )
        encoded = encode_create_cards(cards)
        self.assertEqual(decode_create_cards(encoded), cards)

    def test_delete_batch_is_canonical(self) -> None:
        self.assertEqual(encode_delete_cards((4, 8)), b"4\n8\n")

    def test_invalid_create_batches_are_rejected(self) -> None:
        for value in (
            b"",
            b"note 0 0 12 5",
            b"note 00 0 12 5\n",
            b"unknown 0 0 12 5\n",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_create_cards(value)


if __name__ == "__main__":
    unittest.main()
