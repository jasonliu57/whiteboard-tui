"""Native file portability, validation and read-only inspection."""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib


def u8(n: int) -> bytes: return struct.pack('<B', n)
def u32(n: int) -> bytes: return struct.pack('<I', n)
def u64(n: int) -> bytes: return struct.pack('<Q', n)
def i32(n: int) -> bytes: return struct.pack('<i', n)
def i64(n: int) -> bytes: return struct.pack('<q', n)
def string(s: bytes) -> bytes: return u32(len(s)) + s


def project(cards: bytes = u32(0), *, version: int = 11, glyphs: bytes = u32(0)) -> bytes:
    result = u32(0x42574954) + u32(version) + u32(3)
    for tag, payload in ((0x44524143, cards), (0x45474445, u32(0)), (0x50594C47, glyphs)):
        result += u32(tag) + u64(len(payload)) + u32(zlib.crc32(payload)) + payload
    return result


def note(payload: bytes = b'embedded') -> bytes:
    return (u32(1) + u8(1) + i64(2) + i64(3) + u32(0)
            + i32(12) + i32(5) + u32(0) + u32(0) + u32(1) + string(payload))


class NativeFileTests(unittest.TestCase):
    inspect: Path

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix='tiwb-native-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def snapshot(self, source: Path, *, ok: bool = True) -> bytes:
        output = self.root / 'out.snapshot'
        result = subprocess.run([str(self.inspect), 'snapshot', str(source), '--output', str(output)], capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr.decode())
        return output.read_bytes() if ok else result.stderr

    def test_native_file_is_portable(self) -> None:
        original = self.root / 'original.tiwb'
        original.write_bytes(project(note('中文\n[relative](missing.md)'.encode())))
        expected = self.snapshot(original)
        moved = self.root / 'empty' / 'renamed.tiwb'
        moved.parent.mkdir()
        moved.write_bytes(original.read_bytes())
        original.unlink()
        self.assertEqual(self.snapshot(moved), expected)
        self.assertTrue(expected.startswith(b'WHITEBOARD-SNAPSHOT 2\n'))

    def test_native_open_ignores_sidecars(self) -> None:
        source = self.root / 'board.tiwb'
        source.write_bytes(project(note()))
        sidecar = self.root / '.board.tiwb.tmp.interrupted'
        sidecar.write_bytes(b'incomplete snapshot')
        self.snapshot(source)
        self.assertEqual(sidecar.read_bytes(), b'incomplete snapshot')

    def test_bad_checksum_is_rejected(self) -> None:
        source = self.root / 'bad.tiwb'
        data = bytearray(project(note()))
        data[-1] ^= 1
        source.write_bytes(data)
        self.snapshot(source, ok=False)

    def test_truncated_project_is_rejected(self) -> None:
        source = self.root / 'bad.tiwb'
        source.write_bytes(project(note())[:-1])
        self.snapshot(source, ok=False)

    def test_trailing_bytes_are_rejected(self) -> None:
        source = self.root / 'bad.tiwb'
        source.write_bytes(project(note()) + b'x')
        self.snapshot(source, ok=False)

    def test_unknown_format_is_rejected(self) -> None:
        source = self.root / 'bad.tiwb'
        source.write_bytes(project(u32(1) + u8(1) + i64(0) + i64(0) + u32(99)))
        self.snapshot(source, ok=False)

    def test_unsupported_version_is_rejected(self) -> None:
        source = self.root / 'unsupported.tiwb'
        for version in (0, 0xFFFFFFFF):
            with self.subTest(version=version):
                content = project(note(), version=version)
                source.write_bytes(content)
                self.snapshot(source, ok=False)
                self.assertEqual(source.read_bytes(), content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('inspect', type=Path)
    arguments, remaining = parser.parse_known_args()
    NativeFileTests.inspect = arguments.inspect.resolve()
    unittest.main(argv=[__file__, *remaining])
