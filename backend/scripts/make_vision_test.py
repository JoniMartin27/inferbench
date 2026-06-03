"""Genera data/vision_test.png: un círculo rojo sobre fondo blanco.

Imagen sintética, simple y reproducible (sin dependencias — solo zlib+struct de la
stdlib) para el prompt de benchmark multimodal. Un círculo rojo centrado es
inequívoco de describir, así que permite puntuar la respuesta del modelo de visión.

  python scripts/make_vision_test.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "vision_test.png"
W = H = 224
CX = CY = 112
R = 72


def _png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, color RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    rows = bytearray()
    for y in range(H):
        rows.append(0)  # byte de filtro "None" al inicio de cada fila
        for x in range(W):
            inside = (x - CX) ** 2 + (y - CY) ** 2 <= R * R
            rows += bytes((220, 30, 30)) if inside else bytes((255, 255, 255))
    OUT.write_bytes(_png(W, H, bytes(rows)))
    print(f"Escrito {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
