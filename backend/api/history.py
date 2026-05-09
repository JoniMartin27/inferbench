"""Endpoints /api/history — listar/leer/borrar runs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from db import BenchmarkResult, BenchmarkRun, get_session

router = APIRouter(prefix="/api/history", tags=["history"])


class RunDetail(BaseModel):
    run: BenchmarkRun
    results: list[BenchmarkResult]


@router.get("", response_model=list[BenchmarkRun])
async def list_runs() -> list[BenchmarkRun]:
    with get_session() as s:
        return list(s.exec(select(BenchmarkRun).order_by(BenchmarkRun.ts.desc())).all())


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str) -> RunDetail:
    with get_session() as s:
        run = s.get(BenchmarkRun, run_id)
        if not run:
            raise HTTPException(404, f"run desconocida: {run_id}")
        results = list(s.exec(select(BenchmarkResult).where(BenchmarkResult.run_id == run_id)).all())
        return RunDetail(run=run, results=results)


@router.delete("/{run_id}")
async def delete_run(run_id: str) -> dict[str, str]:
    with get_session() as s:
        run = s.get(BenchmarkRun, run_id)
        if not run:
            raise HTTPException(404, f"run desconocida: {run_id}")
        results = list(s.exec(select(BenchmarkResult).where(BenchmarkResult.run_id == run_id)).all())
        for r in results:
            s.delete(r)
        s.delete(run)
        s.commit()
    return {"deleted": run_id}
