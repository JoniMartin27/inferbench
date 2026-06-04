"""SQLite + SQLModel: persistencia de runs y resultados de benchmark."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel, create_engine

DB_PATH = Path(__file__).resolve().parent / "data" / "inferbench.sqlite"
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
    id: Optional[int] = Field(default=None, primary_key=True)
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
    prefill_tps: float | None = None   # tok/s de procesamiento de prompt (prefill), separado del decode
    tps_std: float | None = None       # desviación estándar del decode tok/s entre muestras
    ttft_std: float | None = None      # desviación estándar del TTFT (ms) entre muestras
    n_samples: int | None = None       # nº de muestras medidas que respaldan estas cifras


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


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_engine)
    _migrate()


def get_session() -> Session:
    return Session(_engine)
