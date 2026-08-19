"""Audita la CAPACIDAD DISCRIMINATIVA de la batería de prompts, sin ejecutar inferencia.

Un benchmark solo sirve si sus notas ordenan modelos. Este script mide si la batería lo hace,
releyendo las respuestas ya guardadas en el historial (`raw_output`) y re-puntuándolas con el
scorer actual. Reporta, por prompt:

  n           respuestas evaluables en el historial
  niveles     cuántas notas DISTINTAS produce (2 niveles = el prompt solo dice sí/no)
  techo       % de respuestas con 100 (si es alto, el prompt ya no separa a los buenos)
  suelo       % con 0
  std         dispersión (si es ~0, el prompt no aporta información)

Y, cuando se le pasa `--compare`, vuelve a puntuar cada respuesta con el scorer VIEJO
(checklist de keywords) y con el nuevo (`checks`) para ver cuánto cambia la nota y qué
respuestas perfectas dejan de serlo (falsos positivos que el checklist dejaba pasar).

Uso (NUNCA escribe en la BD; ábrela siempre en solo lectura):

    python scripts/audit_scoring.py                      # BD por defecto de la app
    python scripts/audit_scoring.py --db copia.sqlite --compare
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.benchmark import (  # noqa: E402
    _quality_checks,
    _quality_keywords,
    _failed_checks,
    load_prompts,
)


def _default_db() -> str:
    env = os.environ.get("INFERBENCH_DB_PATH")
    if env:
        return env
    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = Path(appdata) / "InferBench" / "inferbench.sqlite"
        if cand.exists():
            return str(cand)
    return str(Path(__file__).resolve().parent.parent / "data" / "inferbench.sqlite")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=_default_db())
    ap.add_argument("--compare", action="store_true", help="checklist viejo vs checks nuevos")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"No existe la BD: {args.db}")
        return 1

    # Solo lectura, sin excepciones: este script audita, no toca el historial del usuario.
    con = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [
        r
        for r in con.execute("SELECT * FROM benchmark_results")
        if not (r["error"] or "") and (r["raw_output"] or "").strip()
    ]
    prompts = {p.id: p for p in load_prompts()}
    columnas = {c[1] for c in con.execute("PRAGMA table_info(benchmark_results)")}
    print(f"BD: {args.db}   respuestas utilizables: {len(rows)}\n")

    # Re-puntuar filas de OTRA versión del prompt no mide nada: son respuestas a otra
    # pregunta. Yo mismo me lo comí diseñando esto (filas de `chat` que contestaban
    # "recomiéndame 3 libros" salían con 49 fallos de "names Mercury"). Las filas anteriores
    # al registro de versión (prompt_version NULL) se cuentan aparte, no se mezclan.
    def version_de(r) -> int | None:
        return r["prompt_version"] if "prompt_version" in columnas else None

    vigentes, viejas = [], 0
    for r in rows:
        p = prompts.get(r["prompt_id"])
        if not p:
            continue
        v = version_de(r)
        if v is None or v != p.version:
            viejas += 1
            continue
        vigentes.append((p, r))

    if viejas:
        print(
            f"⚠ {viejas} filas descartadas: son de otra versión del prompt (o anteriores a\n"
            f"  que se registrara la versión). Comparar sus notas con las de ahora no mide\n"
            f"  nada: respondían a otro enunciado o con otro baremo.\n"
        )

    por_prompt: dict[str, list[float]] = defaultdict(list)
    for p, r in vigentes:
        if p.checks:
            por_prompt[p.id].append(_quality_checks(r["raw_output"], p.checks))
        elif p.keywords:
            por_prompt[p.id].append(_quality_keywords(r["raw_output"], p.keywords))

    if not por_prompt:
        print("Todavía no hay resultados de la batería vigente: lanza un benchmark y vuelve.")
        return 0

    print("--- Poder discriminativo por prompt (re-puntuando el historial) ---")
    print(
        f"{'prompt':<22}{'dif':<8}{'n':>5}{'niveles':>9}{'media':>8}{'std':>8}{'techo':>8}{'suelo':>8}"
    )
    for pid, notas in sorted(por_prompt.items()):
        if not notas:
            continue
        dif = prompts[pid].difficulty
        std = statistics.stdev(notas) if len(notas) > 1 else 0.0
        techo = 100 * sum(1 for q in notas if q >= 99.9) / len(notas)
        suelo = 100 * sum(1 for q in notas if q <= 0.01) / len(notas)
        print(
            f"{pid:<22}{dif:<8}{len(notas):>5}{len(set(notas)):>9}"
            f"{statistics.mean(notas):>8.1f}{std:>8.1f}{techo:>7.0f}%{suelo:>7.0f}%"
        )

    sin_datos = [p.id for p in prompts.values() if p.id not in por_prompt]
    if sin_datos:
        print(f"\nSin histórico todavía (prompts nuevos): {', '.join(sin_datos)}")

    if args.compare:
        print("\n--- Checklist viejo vs comprobaciones nuevas (mismas respuestas) ---")
        for pid, p in sorted(prompts.items()):
            if not (p.checks and p.keywords):
                continue
            pares = [
                (
                    _quality_keywords(r["raw_output"], p.keywords),
                    _quality_checks(r["raw_output"], p.checks),
                )
                for q, r in vigentes
                if q.id == pid
            ]
            if not pares:
                continue
            perfectos_antes = sum(1 for a, _ in pares if a >= 99.9)
            siguen = sum(1 for a, b in pares if a >= 99.9 and b >= 99.9)
            print(
                f"{pid:<22} n={len(pares):<4} 100 con el checklist viejo: {perfectos_antes:<4}"
                f"→ siguen siendo 100: {siguen}  (falsos positivos cazados: "
                f"{perfectos_antes - siguen})"
            )

        print("\n--- Comprobaciones que más fallan (dónde se rompen los modelos) ---")
        conteo: dict[tuple[str, str], int] = defaultdict(int)
        for p, r in vigentes:
            if p.checks:
                for etiqueta in _failed_checks(r["raw_output"], p.checks):
                    conteo[(p.id, etiqueta)] += 1
        for (pid, etiqueta), n in sorted(conteo.items(), key=lambda kv: -kv[1])[:12]:
            print(f"   {n:>4}×  {pid}: {etiqueta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
