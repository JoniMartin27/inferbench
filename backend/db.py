"""SQLite + SQLModel: persistencia de runs y resultados de benchmark."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel, create_engine


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
    """
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


# Columnas añadidas tras la v0 de la tabla. create_all no altera tablas existentes, así que
# las añadimos a mano (idempotente). (columna, tipo SQL).
_RESULT_MIGRATIONS = [
    ("prefill_tps", "FLOAT"),
    ("tps_std", "FLOAT"),
    ("ttft_std", "FLOAT"),
    ("n_samples", "INTEGER"),
]


def _migrate() -> None:
    """Migración aditiva no destructiva: añade columnas nuevas a benchmark_results si faltan."""
    with _engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(benchmark_results)"))}
        for col, sqltype in _RESULT_MIGRATIONS:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE benchmark_results ADD COLUMN {col} {sqltype}"))


def reconcile_orphan_runs() -> int:
    """Cierra las runs que quedaron marcadas `running` de una ejecución anterior.

    El estado `running` de una fila lo cierra el propio flujo del runner al terminar. Si el
    proceso muere antes —cierras la app, se cae el backend, alguien lo mata— la fila se
    queda en `running` PARA SIEMPRE: el Historial la enseña "en curso", no hay forma de
    pararla (el `/stop` daba 404 porque el runner ya no existe en memoria) y encima las
    nuevas runs se quedaban esperando turno detrás de un fantasma.

    Al arrancar, cualquier fila en `running` es por definición imposible: el proceso que la
    ejecutaba ya no existe. Se marcan `interrupted`, que es la verdad.

    Devuelve cuántas ha cerrado.
    """
    with _engine.begin() as conn:
        resultado = conn.execute(
            text("UPDATE benchmark_runs SET status = 'interrupted' WHERE status = 'running'")
        )
        return resultado.rowcount or 0


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_engine)
    _migrate()


def get_session() -> Session:
    return Session(_engine)
