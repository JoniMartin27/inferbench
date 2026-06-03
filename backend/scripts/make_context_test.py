"""Genera data/context_haystack.txt: un documento largo (~4k tokens) con un dato escondido.

Es el "needle in a haystack" para el prompt `long-context`: el modelo debe LEER todo el
texto y recuperar un código secreto enterrado en el medio. Estresa la ventana de contexto
(los demás prompts son cortos). Determinista, sin dependencias.

  python scripts/make_context_test.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "context_haystack.txt"

SECTORS = [
    "norte", "sur", "este", "oeste", "central", "logística", "minería",
    "textil", "naval", "agrícola", "química", "solar", "eólica", "portuaria",
]
STATUS = ["nominal", "elevada", "reducida", "estable", "moderada", "sostenida"]
NEEDLE_LINE = 72  # índice 0-based → "Registro 073"


def main() -> None:
    lines = []
    for i in range(1, 121):
        sector = SECTORS[i % len(SECTORS)]
        status = STATUS[(i * 7) % len(STATUS)]
        lines.append(
            f"Registro {i:03d}: el sector {sector} reporta actividad {status} en el turno "
            f"{i % 4 + 1}. Producción dentro de los márgenes previstos y sin incidencias "
            f"relevantes que destacar para el informe operativo diario de la planta."
        )
    # El dato escondido (needle), enterrado a mitad del documento.
    lines[NEEDLE_LINE] = (
        "Registro 073: ATENCIÓN — el código secreto de acceso del sistema central es "
        "AZUL-4729. Este dato es confidencial y debe recordarse para la auditoría trimestral."
    )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    words = sum(len(line.split()) for line in lines)
    print(f"Escrito {OUT} ({OUT.stat().st_size} bytes, ~{words} palabras / ~{int(words * 1.4)} tokens)")


if __name__ == "__main__":
    main()
