from __future__ import annotations

import unittest

from tools.whiteboard_automation.errors import ProtocolError
from tools.whiteboard_automation.protocol import (
    parse_card_response,
    parse_connect_response,
    parse_create_cards_response,
    parse_delete_cards_response,
    parse_query_response,
    parse_replace_card_response,
    parse_status,
    parse_view,
)
from tools.whiteboard_automation.snapshot import (
    SNAPSHOT_MAGIC,
    parse_canonical_snapshot,
)


def card_response(
    payload: bytes,
    *,
    revision: int = 7,
    card_id: int = 0,
    x: int = 1,
) -> bytes:
    return (
        f"OK {revision} CARD {card_id} note {x} 2 12 5 {len(payload)}\n".encode(
            "ascii"
        )
        + payload
        + b"\nEND\n"
    )


def snapshot(glyphs: tuple[tuple[int, int, int], ...]) -> bytes:
    body = bytearray(SNAPSHOT_MAGIC)
    body.extend(f"META 1 1 0 0 {len(glyphs)}\n".encode("ascii"))
    payload = "中文".encode()
    body.extend(f"CARD 0 note 0 0 12 5 {len(payload)}\n".encode("ascii"))
    body.extend(payload)
    body.extend(b"\n")
    for x, y, codepoint in glyphs:
        body.extend(f"GLYPH {x} {y} {codepoint}\n".encode("ascii"))
    body.extend(b"END\n")
    return bytes(body)


class ProtocolTests(unittest.TestCase):
    def test_typed_response_parsers_accept_exact_framing(self) -> None:
        self.assertEqual(parse_status(b"OK 7 STATUS 2 1 0\n").revision, 7)
        self.assertIsNone(
            parse_view(b"OK 7 VIEW BOARD 0 0 80 24 2 3 -\n").selected_card_id
        )
        query = parse_query_response(
            b"OK 7 QUERY 1\nCARD 4 note -2 3 12 5 2\nA\n\nEND\n"
        )
        self.assertEqual((query.revision, query.cards[0].payload), (7, b"A\n"))
        self.assertEqual(
            parse_create_cards_response(b"OK 8 CREATE_CARDS 2 10\n").count,
            2,
        )
        self.assertEqual(
            parse_delete_cards_response(b"OK 9 DELETE_CARDS 2\n").count,
            2,
        )

    def test_noncanonical_integer_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_status(b"OK 07 STATUS 2 1 0\n")

    def test_card_payload_is_byte_exact(self) -> None:
        for payload in (b"", "中文\nEND\n\n".encode(), b"a\tb\n"):
            with self.subTest(payload=payload):
                self.assertEqual(parse_card_response(card_response(payload)).payload, payload)

    def test_card_rejects_invalid_framing(self) -> None:
        valid = card_response(b"abc")
        header, rest = valid.split(b"\n", 1)
        words = header.split(b" ")
        words[-1] = b"4"
        for value in (b" ".join(words) + b"\n" + rest, valid[:-1], valid + b"extra"):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                parse_card_response(value)

    def test_mutation_response_parsers_are_strict(self) -> None:
        created = parse_create_cards_response(b"OK 4 CREATE_CARDS 2 9\n")
        self.assertEqual(
            (created.revision, created.count, created.first_card_id),
            (4, 2, 9),
        )
        connected = parse_connect_response(b"OK 5 CONNECT 3\n")
        self.assertEqual((connected.revision, connected.object_id), (5, 3))
        with self.assertRaises(ProtocolError):
            parse_create_cards_response(b"OK 04 CREATE_CARDS 2 9\n")

    def test_snapshot_requires_canonical_order(self) -> None:
        ordered = snapshot(((2, 1, 65), (1, 2, 0x4E2D)))
        parsed = parse_canonical_snapshot(ordered)
        self.assertEqual(parsed.cards[0].payload, "中文".encode())
        unordered = ordered.replace(
            b"GLYPH 2 1 65\nGLYPH 1 2 20013\n",
            b"GLYPH 1 2 20013\nGLYPH 2 1 65\n",
        )
        with self.assertRaises(ProtocolError):
            parse_canonical_snapshot(unordered)

    def test_card_coordinates_must_be_canonical_signed_integers(self) -> None:
        for coordinate in ("+1", "01", "-0", "x", str(2**63), str(-(2**63) - 1)):
            raw = (
                f"OK 9 CARD 50 text-art {coordinate} 4 3 1 2\n".encode("ascii")
                + b"A\n\nEND\n"
            )
            with self.subTest(coordinate=coordinate), self.assertRaises(ProtocolError):
                parse_card_response(raw)

    def test_error_and_trailing_data_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "ERR stale_revision"):
            parse_replace_card_response(b"ERR stale_revision 9\n")
        with self.assertRaises(ProtocolError):
            parse_create_cards_response(b"OK 1 CREATE_CARDS 2 3\ntrailing")


if __name__ == "__main__":
    unittest.main()
