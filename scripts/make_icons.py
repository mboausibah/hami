#!/usr/bin/env python3
"""Generate Hami's shield icons (original artwork) as PNGs without image libraries.

    python scripts/make_icons.py   -> clients/extension/icons/icon{16,32,48,128}.png
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "clients" / "extension" / "icons"
GREEN = (11, 93, 75)
WHITE = (255, 255, 255)


def inside_shield(x: float, y: float) -> bool:
    """Shield in unit square: flat top with rounded shoulders, pointed bottom."""
    if y < 0.08 or y > 0.95:
        return False
    half = 0.40 if y < 0.55 else 0.40 * (1 - ((y - 0.55) / 0.40) ** 1.6)
    top_curve = 0.08 + 0.05 * (abs(x - 0.5) / 0.40) ** 2
    return abs(x - 0.5) <= half and y >= top_curve


def on_check(x: float, y: float, w: float) -> bool:
    """Check mark from (0.33,0.52) to (0.46,0.66) to (0.69,0.38)."""
    def seg(ax, ay, bx, by):  # noqa: ANN001, ANN202
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        px, py = ax + t * dx, ay + t * dy
        return (x - px) ** 2 + (y - py) ** 2 <= w * w
    return seg(0.33, 0.52, 0.46, 0.66) or seg(0.46, 0.66, 0.69, 0.38)


def render(size: int) -> bytes:
    ss = 4
    w = 0.075 if size >= 32 else 0.10
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / size
                    y = (py + (sy + 0.5) / ss) / size
                    if inside_shield(x, y):
                        c = WHITE if on_check(x, y, w) else GREEN
                        acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]; acc[3] += 255
            n = ss * ss
            a = acc[3] // n
            if a:
                cov = acc[3] / 255
                row += bytes([int(acc[0] / cov), int(acc[1] / cov), int(acc[2] / cov), a])
            else:
                row += bytes([0, 0, 0, 0])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        (OUT / f"icon{size}.png").write_bytes(render(size))
    print(f"icons -> {OUT}")


if __name__ == "__main__":
    main()
