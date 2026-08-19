"""Genera data/context_haystack.txt: un documento largo (~4k tokens) con datos escondidos.

Es el "needle in a haystack" de los prompts `long-context` y `long-context-count`. Un único
needle con un código opaco se resolvía casando una cadena, y el historial real lo confirmaba:
6 resultados, 83% en el techo y solo DOS notas posibles (0 o 100) — un prompt así no ordena
modelos, solo dice "sí/no". Esta versión mete tres dificultades reales:

  1. TRES códigos, no uno: dos anulados (uno revocado, otro caducado) y uno ACTIVO. Casar
     "el código" ya no basta: hay que leer el estado de cada uno y elegir.
  2. El código bueno vive DESPUÉS de los señuelos y del centro del documento, donde más
     cuesta (los señuelos aparecen antes: quien se quede con el primero, falla).
  3. Un conteo agregado: exactamente 7 registros marcados INCIDENT, con 100+ registros que
     dicen "no notable incidents". Quien busque la palabra "incident" cuenta de más.

Determinista, sin dependencias. Cuerpo en inglés (producto english-first).

  python scripts/make_context_test.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "context_haystack.txt"

SECTORS = [
    "north",
    "south",
    "east",
    "west",
    "central",
    "logistics",
    "mining",
    "textile",
    "naval",
    "agricultural",
    "chemical",
    "solar",
    "wind",
    "port",
]
STATUS = ["nominal", "elevated", "reduced", "stable", "moderate", "sustained"]

N_RECORDS = 120
# Los tres códigos. El ACTIVO va después de los dos anulados y pasado el centro del documento.
REVOKED_LINE, EXPIRED_LINE, ACTIVE_LINE = 21, 46, 87
# Registros marcados como incidente. Son 7: la respuesta del prompt de conteo.
INCIDENT_LINES = [12, 29, 38, 55, 64, 91, 108]


def main() -> None:
    lines = []
    for i in range(1, N_RECORDS + 1):
        sector = SECTORS[i % len(SECTORS)]
        status = STATUS[(i * 7) % len(STATUS)]
        lines.append(
            f"Record {i:03d}: the {sector} sector reports {status} activity on shift "
            f"{i % 4 + 1}. Output within the expected margins and no notable incidents "
            f"to flag for the plant's daily operations report."
        )

    # Señuelo 1: código revocado (aparece el PRIMERO — quien se quede con el primero, falla).
    lines[REVOKED_LINE] = (
        f"Record {REVOKED_LINE + 1:03d}: NOTICE - the access code BRONCE-1188 was REVOKED "
        "after the February audit and must no longer be used by any operator."
    )
    # Señuelo 2: código caducado.
    lines[EXPIRED_LINE] = (
        f"Record {EXPIRED_LINE + 1:03d}: NOTICE - the temporary access code VERDE-2051 "
        "EXPIRED at the end of the last quarter and grants no access to the central system."
    )
    # El bueno: el único ACTIVO, enterrado pasada la mitad del documento.
    lines[ACTIVE_LINE] = (
        f"Record {ACTIVE_LINE + 1:03d}: NOTICE - the ACTIVE access code for the central "
        "system is AZUL-4729. It is the only valid code and replaces every earlier one."
    )
    # Los 7 incidentes reales, para el prompt de conteo agregado.
    for n, idx in enumerate(INCIDENT_LINES, start=1):
        sector = SECTORS[(idx + 1) % len(SECTORS)]
        lines[idx] = (
            f"Record {idx + 1:03d}: INCIDENT - the {sector} sector halted the line for "
            f"{n * 5} minutes after a pressure alarm. Logged as incident number {n} of the month."
        )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    words = sum(len(line.split()) for line in lines)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, ~{words} words / ~{int(words * 1.4)} tokens)")
    print(
        f"  active code AZUL-4729 at line {ACTIVE_LINE + 1}, decoys at "
        f"{REVOKED_LINE + 1} (revoked) and {EXPIRED_LINE + 1} (expired)"
    )
    print(f"  {len(INCIDENT_LINES)} INCIDENT records: {[i + 1 for i in INCIDENT_LINES]}")


if __name__ == "__main__":
    main()
