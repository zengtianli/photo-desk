"""Losslessly recompress the PNG entries of an .icns for the app bundle.

Usage: compress_icon.py <source.icns> <output.icns>

The source icon (icon/AppIcon.icns) is left untouched. Every PNG entry is decoded and
re-encoded with maximum zlib compression; ancillary chunks (sRGB, eXIf, ...) are carried over
byte for byte, and the new entry is used only if its decoded pixels are identical and it is
smaller. Entry types, order and non-PNG entries stay as they are, so the icon looks the same
at every size. Fails loudly instead of shipping a changed icon.
"""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image

SIGNATURE = b'\x89PNG\r\n\x1a\n'


def chunks(png: bytes):
    if not png.startswith(SIGNATURE):
        raise ValueError('not a PNG')
    offset = len(SIGNATURE)
    while offset < len(png):
        length, kind = struct.unpack('>I4s', png[offset:offset + 8])
        yield kind, png[offset:offset + 12 + length]
        offset += 12 + length


def pixels(png: bytes):
    image = Image.open(io.BytesIO(png))
    image.load()
    return image.mode, image.size, image.tobytes()


def recompress(png: bytes) -> bytes:
    image = Image.open(io.BytesIO(png))
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', optimize=True, compress_level=9)
    fresh = dict((kind, raw) for kind, raw in chunks(buffer.getvalue()) if kind == b'IHDR')
    original = list(chunks(png))
    if fresh.get(b'IHDR') != dict(original).get(b'IHDR'):
        return png  # different bit depth or colour type: keep the original entry
    ancillary = [raw for kind, raw in original if kind not in (b'IHDR', b'IDAT', b'IEND')]
    data = [raw for kind, raw in chunks(buffer.getvalue()) if kind == b'IDAT']
    candidate = SIGNATURE + fresh[b'IHDR'] + b''.join(ancillary) + b''.join(data) + dict(original)[b'IEND']
    if pixels(candidate) != pixels(png):
        raise SystemExit('re-encoded icon entry differs from the original pixels')
    return candidate if len(candidate) < len(png) else png


def main(source: str, output: str) -> None:
    data = Path(source).read_bytes()
    if data[:4] != b'icns' or struct.unpack('>I', data[4:8])[0] != len(data):
        raise SystemExit(f'{source}: not an .icns file')
    entries, offset = [], 8
    while offset < len(data):
        kind, length = struct.unpack('>4sI', data[offset:offset + 8])
        body = data[offset + 8:offset + length]
        entries.append((kind, recompress(body) if body.startswith(SIGNATURE) else body))
        offset += length
    body = b''.join(kind + struct.pack('>I', len(value) + 8) + value for kind, value in entries)
    result = b'icns' + struct.pack('>I', len(body) + 8) + body
    Path(output).write_bytes(result)
    print(f'{source}: {len(data):,} -> {len(result):,} bytes ({len(entries)} entries, pixels identical)')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
