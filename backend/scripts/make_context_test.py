"""Genera data/context_haystack.txt: un documento largo (~4k tokens) con un dato escondido.

Es el "needle in a haystack" para el prompt `long-context`: el modelo debe LEER todo el
texto y recuperar un código secreto enterrado en el medio. Estresa la ventana de contexto
(los demás prompts son cortos). Determinista, sin dependencias. El cuerpo está en inglés
(producto english-first); el código secreto AZUL-4729 es un token opaco que el scorer busca.

  python scripts/make_context_test.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "context_haystack.txt"

SECTORS = [
    "north", "south", "east", "west", "central", "logistics", "mining",
    "textile", "naval", "agricultural", "chemical", "solar", "wind", "port",
]
STATUS = ["nominal", "elevated", "reduced", "stable", "moderate", "sustained"]
NEEDLE_LINE = 72  # índice 0-based → "Record 073"


def main() -> None:
    lines = []
    for i in range(1, 121):
        sector = SECTORS[i % len(SECTORS)]
        status = STATUS[(i * 7) % len(STATUS)]
        lines.append(
            f"Record {i:03d}: the {sector} sector reports {status} activity on shift "
            f"{i % 4 + 1}. Output within the expected margins and no notable incidents "
            f"to flag for the plant's daily operations report."
        )
    # El dato escondido (needle), enterrado a mitad del documento.
    lines[NEEDLE_LINE] = (
        "Record 073: ATTENTION — the secret access code for the central system is "
        "AZUL-4729. This information is confidential and must be remembered for the quarterly audit."
    )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    words = sum(len(line.split()) for line in lines)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, ~{words} words / ~{int(words * 1.4)} tokens)")


if __name__ == "__main__":
    main()
