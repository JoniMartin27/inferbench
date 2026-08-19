"""SQLite + SQLModel: persistencia de runs y resultados de benchmark."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from loguru import logger
from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel, create_engine

# Variable de entorno que MANDA sobre cualquier otra ruta. Existe para que el arnés de
# pruebas pueda apuntar a una base de datos desechable ANTES de que se importe este módulo:
# `DB_PATH` y `_engine` se calculan al importar, así que parchearlos después siempre llega
# tarde para lo que corra en un lifespan. Ver `tests/conftest.py`.
_ENV_DB_PATH = "INFERBENCH_DB_PATH"


def _db_path() -> Path:
    """Dónde vive el SQLite de runs y resultados.

    **Congelado por PyInstaller (el sidecar de la app instalada): en los datos del
    usuario.** Con `Path(__file__).parent` a secas, en un onefile la ruta caía dentro de
    `%TEMP%\\_MEI<aleatorio>\\`, que PyInstaller crea NUEVO EN CADA ARRANQUE y borra al
    salir. Resultado medido en la app instalada: historial vacío en cada apertura, todos
    los benchmarks perdidos al cerrar, y un `.sqlite` huérfano por lanzamiento tirado en
    el temporal. La pestaña Historial —comparar runs, exportar CSV/JSON— era inservible
    en el build empaquetado, y solo parecía funcionar cuando la app reutilizaba un
    backend de desarrollo.

    Se usa la MISMA carpeta que el resto de cachés del proyecto (`%APPDATA%\\InferBench`
    en Windows, `~/.inferbench` fuera), donde ya viven binarios, modelos y logs.

    Ejecutando desde el código sigue en `backend/data/`, para no mezclar la base de datos
    de desarrollo con la del usuario.

    `INFERBENCH_DB_PATH` gana a todo lo demás (lo usa el arnés de pruebas para no poder
    tocar la base de datos real ni por accidente).
    """
    forzada = os.environ.get(_ENV_DB_PATH)
    if forzada:
        ruta = Path(forzada).expanduser()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        return ruta
    if getattr(sys, "frozen", False):
        base = (
            Path(os.environ["APPDATA"]) / "InferBench"
            if os.name == "nt" and "APPDATA" in os.environ
            else Path.home() / ".inferbench"
        )
        base.mkdir(parents=True, exist_ok=True)
        return base / "inferbench.sqlite"
    return Path(__file__).resolve().parent / "data" / "inferbench.sqlite"


DB_PATH = _db_path()
_engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


class BenchmarkRun(SQLModel, table=True):
    __tablename__ = "benchmark_runs"
    id: str = Field(primary_key=True)
    ts: int
    engine: str
    hw_json: str
    opts_json: str
    notes: str = ""
    status: str = "running"  # running | done | error


class BenchmarkResult(SQLModel, table=True):
    __tablename__ = "benchmark_results"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, foreign_key="benchmark_runs.id")
    model_id: str
    prompt_id: str
    tps: float | None = None
    ttft_ms: int | None = None
    vram_gb: float | None = None
    ram_gb: float | None = None
    quality: float | None = None
    cost: float | None = None
    ctx_used: int | None = None
    raw_output: str = ""
    error: str = ""
    # Rigor estadístico: cada métrica es la MEDIANA de N muestras (tras descartar un warmup).
    prefill_tps: float | None = (
        None  # tok/s de procesamiento de prompt (prefill), separado del decode
    )
    tps_std: float | None = None  # desviación estándar del decode tok/s entre muestras
    ttft_std: float | None = None  # desviación estándar del TTFT (ms) entre muestras
    n_samples: int | None = None  # nº de muestras medidas que respaldan estas cifras
    # Versión del prompt y del scorer con los que se obtuvo esta nota. Sin esto, comparar
    # notas de runs distintas es inválido en cuanto la batería cambia: MEDIDO sobre el
    # historial real, filas del prompt `chat` guardaban respuestas a "recomiéndame 3 libros"
    # y a "lista los ocho planetas" con la misma etiqueta, indistinguibles.
    prompt_version: int | None = None
    scorer: str = ""  # checks | checklist | code-exec | heuristic | llm:self | llm:api


# Columnas añadidas tras la v0 de la tabla. create_all no altera tablas existentes, así que
# las añadimos a mano (idempotente). (columna, tipo SQL).
_RESULT_MIGRATIONS = [
    ("prefill_tps", "FLOAT"),
    ("tps_std", "FLOAT"),
    ("ttft_std", "FLOAT"),
    ("n_samples", "INTEGER"),
    ("prompt_version", "INTEGER"),
    ("scorer", "VARCHAR"),
]


def _migrate() -> None:
    """Migración aditiva no destructiva: añade columnas nuevas a benchmark_results si faltan."""
    with _engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(benchmark_results)"))}
        for col, sqltype in _RESULT_MIGRATIONS:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE benchmark_results ADD COLUMN {col} {sqltype}"))


def _runs_con_resultados_completos(conn, estado: str) -> list[str]:
    """ids de runs en `estado` que tienen resultados para TODOS sus prompts declarados.

    Una fila así NO se quedó a medias: terminó y solo le faltó el último UPDATE de estado.
    El criterio es deliberadamente conservador —exige cubrir todos los prompts de
    `opts_json`— porque el error caro es al revés: dar por buena una run que no acabó.

    Nota: el gating de visión puede OMITIR prompts (un modelo sin `mmproj` no los corre),
    así que una run completa puede tener menos resultados que prompts declarados y aquí
    contará como incompleta. Se prefiere quedarse corto: dejarla `interrupted` es honesto.
    """
    filas = conn.execute(
        text("SELECT id, opts_json FROM benchmark_runs WHERE status = :estado"),
        {"estado": estado},
    ).fetchall()
    if not filas:
        return []
    por_run = dict(
        conn.execute(
            text("SELECT run_id, count(*) FROM benchmark_results GROUP BY run_id")
        ).fetchall()
    )
    completas = []
    for run_id, opts_json in filas:
        try:
            prompts = (json.loads(opts_json or "{}") or {}).get("prompts") or []
        except (json.JSONDecodeError, TypeError, ValueError):
            continue  # opts ilegible: no presuponemos nada
        if prompts and por_run.get(run_id, 0) >= len(prompts):
            completas.append(run_id)
    return completas


def reconcile_orphan_runs() -> int:
    """Cierra las runs que quedaron marcadas `running` de una ejecución anterior.

    El estado `running` de una fila lo cierra el propio flujo del runner al terminar. Si el
    proceso muere antes —cierras la app, se cae el backend, alguien lo mata— la fila se
    queda en `running` PARA SIEMPRE: el Historial la enseña "en curso", no hay forma de
    pararla (el `/stop` daba 404 porque el runner ya no existe en memoria) y encima las
    nuevas runs se quedaban esperando turno detrás de un fantasma.

    Al arrancar, cualquier fila en `running` es por definición imposible: el proceso que la
    ejecutaba ya no existe. Pero **`interrupted` no es la verdad para todas**: una fila con
    resultados para todos sus prompts SÍ terminó, solo le faltó el último UPDATE. Marcarla
    "interrumpida" borra trabajo bueno del Historial, que es justo el daño que hay que
    evitar. Esas se recuperan como `done`; el resto sí se marcan `interrupted`.

    Devuelve cuántas filas han dejado de estar en `running`.
    """
    with _engine.begin() as conn:
        recuperadas = _runs_con_resultados_completos(conn, "running")
        if recuperadas:
            conn.execute(
                text("UPDATE benchmark_runs SET status = 'done' WHERE id = :id"),
                [{"id": run_id} for run_id in recuperadas],
            )
        resultado = conn.execute(
            text("UPDATE benchmark_runs SET status = 'interrupted' WHERE status = 'running'")
        )
        interrumpidas = resultado.rowcount or 0
    if recuperadas:
        logger.info(
            f"{len(recuperadas)} run(s) colgadas tenían todos sus resultados: "
            "estaban terminadas y se han marcado como completadas, no interrumpidas."
        )
    return len(recuperadas) + interrumpidas


def repair_misflagged_interrupted_runs() -> int:
    """Devuelve a `done` las runs marcadas `interrupted` que tienen todos sus resultados.

    Reparación de un incidente real (2026-08-13): un `UPDATE` de reconciliación llegó a
    correr contra la base de datos del usuario y dejó 135 de 137 filas en `interrupted`;
    98 de ellas tenían resultados para todos sus prompts, o sea habían terminado bien. El
    Historial pasó de verde a ámbar casi entero y las runs buenas parecían basura.

    Que una fila `interrupted` tenga TODOS sus resultados es imposible por el camino normal:
    `api/benchmark.py` escribe `done` y los resultados en la MISMA transacción, y `/stop`
    solo toca filas en `running`. Así que si se da, es una fila mal marcada — se corrige.

    Idempotente: en cuanto no quedan filas así, no hace nada. Corre en cada arranque para
    que otras máquinas/instalaciones afectadas se reparen solas.

    Devuelve cuántas ha recuperado.
    """
    with _engine.begin() as conn:
        recuperadas = _runs_con_resultados_completos(conn, "interrupted")
        if recuperadas:
            conn.execute(
                text("UPDATE benchmark_runs SET status = 'done' WHERE id = :id"),
                [{"id": run_id} for run_id in recuperadas],
            )
    if recuperadas:
        logger.warning(
            f"{len(recuperadas)} run(s) estaban marcadas como interrumpidas pero tenían todos "
            "sus resultados; las devuelvo a completadas (reparación idempotente)."
        )
    return len(recuperadas)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_engine)
    _migrate()
    repair_misflagged_interrupted_runs()


def get_session() -> Session:
    return Session(_engine)
