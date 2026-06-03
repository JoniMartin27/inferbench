"""Genera las imágenes de prueba para el benchmark multimodal (sin dependencias — solo
zlib+struct de la stdlib). Cada imagen tiene un ground-truth conocido para puntuar la
respuesta del modelo de visión con un checklist de atributos (ver data/prompts.json):

  data/vision_scene.png  — 3 figuras de 3 colores (círculo rojo, cuadrado azul,
                           triángulo verde): prueba reconocimiento de forma+color y conteo.
  data/vision_count.png  — 4 círculos naranjas en rejilla 2×2: prueba conteo.

  python scripts/make_vision_test.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
WHITE = (255, 255, 255)


# ---- toolkit de dibujo sobre un buffer RGB plano (índice (y*W+x)*3) ----
def canvas(w: int, h: int, bg=WHITE) -> bytearray:
    return bytearray(bytes(bg) * (w * h))


def _put(buf: bytearray, w: int, x: int, y: int, color) -> None:
    i = (y * w + x) * 3
    buf[i : i + 3] = bytes(color)


def circle(buf: bytearray, w: int, h: int, cx: int, cy: int, r: int, color) -> None:
    for y in range(max(0, cy - r), min(h, cy + r + 1)):
        for x in range(max(0, cx - r), min(w, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                _put(buf, w, x, y, color)


def rect(buf: bytearray, w: int, h: int, x0: int, y0: int, x1: int, y1: int, color) -> None:
    for y in range(max(0, y0), min(h, y1)):
        for x in range(max(0, x0), min(w, x1)):
            _put(buf, w, x, y, color)


def triangle(buf: bytearray, w: int, h: int, p0, p1, p2, color) -> None:
    xs, ys = (p0[0], p1[0], p2[0]), (p0[1], p1[1], p2[1])

    def edge(a, b, p):
        return (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])

    for y in range(max(0, min(ys)), min(h, max(ys) + 1)):
        for x in range(max(0, min(xs)), min(w, max(xs) + 1)):
            p = (x, y)
            d1, d2, d3 = edge(p0, p1, p), edge(p1, p2, p), edge(p2, p0, p)
            inside = not (((d1 < 0) or (d2 < 0) or (d3 < 0)) and ((d1 > 0) or (d2 > 0) or (d3 > 0)))
            if inside:
                _put(buf, w, x, y, color)


def write_png(path: Path, w: int, h: int, buf: bytearray) -> None:
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # byte de filtro "None" por fila
        raw += buf[y * w * 3 : (y + 1) * w * 3]

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"Escrito {path} ({path.stat().st_size} bytes)")


def main() -> None:
    W = H = 256
    RED, BLUE, GREEN, ORANGE = (220, 40, 40), (40, 70, 210), (40, 175, 70), (240, 140, 30)

    # Escena: 3 figuras, 3 colores → reconocimiento forma+color y conteo (=3)
    scene = canvas(W, H)
    circle(scene, W, H, 66, 70, 44, RED)            # círculo rojo, arriba-izquierda
    rect(scene, W, H, 150, 26, 232, 108, BLUE)      # cuadrado azul, arriba-derecha
    triangle(scene, W, H, (128, 138), (84, 226), (172, 226), GREEN)  # triángulo verde, abajo
    write_png(DATA / "vision_scene.png", W, H, scene)

    # Conteo: 4 círculos naranjas en rejilla 2×2
    count = canvas(W, H)
    for cx, cy in ((75, 75), (181, 75), (75, 181), (181, 181)):
        circle(count, W, H, cx, cy, 38, ORANGE)
    write_png(DATA / "vision_count.png", W, H, count)


if __name__ == "__main__":
    main()
