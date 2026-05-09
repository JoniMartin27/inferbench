"""SQLite + SQLModel: persistencia de runs y resultados de benchmark."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

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


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_engine)


def get_session() -> Session:
    return Session(_engine)
