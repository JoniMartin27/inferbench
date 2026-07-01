"""Tests del estado en memoria de api/benchmark.py (runs/sweeps), sin red ni motores reales.

`_RUNNERS` tiene un cap explícito (`_MAX_RUNNERS`) para no acumular runners huérfanos si un
cliente nunca se conecta al stream SSE. `start_run` lo respeta; `start_sweep` debe respetarlo
también para cada sub-run que encola (bug: el sweep insertaba en `_RUNNERS` sin podar).
"""

from __future__ import annotations

import api.benchmark as bench_api
from core.benchmark import BenchmarkRequest, BenchmarkRunner


async def _noop_run(self) -> None:
    """Sustituye BenchmarkRunner.run(): sin red/motor, solo deja `results` vacío."""
    return None


def _patch_db_session(monkeypatch, tmp_path):
    """Apunta get_session()/BenchmarkRun/BenchmarkResult a un SQLite temporal."""
    import db as dbmod
    from sqlmodel import create_engine

    db_path = tmp_path / "t.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    dbmod.SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(dbmod, "_engine", engine)
    monkeypatch.setattr(bench_api, "get_session", dbmod.get_session)


async def test_start_sweep_prunes_runners_beyond_cap(monkeypatch, tmp_path):
    _patch_db_session(monkeypatch, tmp_path)
    monkeypatch.setattr(BenchmarkRunner, "run", _noop_run)
    monkeypatch.setattr(bench_api, "_MAX_RUNNERS", 2)
    bench_api._RUNNERS.clear()

    req = bench_api.SweepRequest(
        base=BenchmarkRequest(engine="llamacpp", model="m", auto=False, prompts=[]),
        quants=["Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"],
    )
    resp = await bench_api.start_sweep(req)

    # El sweep es secuencial (awaited dentro de la propia request -> create_task corre en
    # el mismo loop antes de que el test termine de await-ear start_sweep solo lanza la
    # tarea); esperamos a que runner_loop (creada como task) procese todas las quants.
    import asyncio

    for _ in range(50):
        state = bench_api._SWEEPS[resp.sweep_id]
        if state.completed:
            break
        await asyncio.sleep(0.01)

    assert bench_api._SWEEPS[resp.sweep_id].completed
    # Nunca debe superar el cap, ni siquiera transitoriamente al final del sweep.
    assert len(bench_api._RUNNERS) <= 2
