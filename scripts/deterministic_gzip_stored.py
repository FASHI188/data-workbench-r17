#!/usr/bin/env python3
from __future__ import annotations

import binascii
import csv
import io
import struct
from pathlib import Path


def gzip_store_bytes(data: bytes) -> bytes:
    """Return a byte-for-byte deterministic gzip stream without zlib dependency.

    The stream uses a fixed RFC1952 header and RFC1951 stored DEFLATE blocks.
    This deliberately trades compression ratio for cross-runtime byte identity.
    """
    out = bytearray(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff")
    if not data:
        out.append(0x01)
        out.extend(struct.pack("<HH", 0, 0xFFFF))
    else:
        for offset in range(0, len(data), 65535):
            chunk = data[offset : offset + 65535]
            final = offset + len(chunk) >= len(data)
            out.append(0x01 if final else 0x00)
            length = len(chunk)
            out.extend(struct.pack("<HH", length, 0xFFFF ^ length))
            out.extend(chunk)
    out.extend(struct.pack("<II", binascii.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF))
    return bytes(out)


def deterministic_csv_gz(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    plain = text.getvalue().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip_store_bytes(plain))
