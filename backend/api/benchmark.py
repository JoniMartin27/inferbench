"""Endpoints /api/benchmark — POST /run + GET /stream/{run_id} (SSE)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from core.benchmark import BenchmarkRequest, BenchmarkRunner
from core.hardware import detect_hardware
from db import BenchmarkResult, BenchmarkRun, get_session

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

# Estado en memoria de runs activas
_RUNNERS: dict[str, BenchmarkRunner] = {}


@router.post("/run")
async def start_run(req: BenchmarkRequest) -> dict[str, str]:
    runner = BenchmarkRunner(req)
    _RUNNERS[runner.run_id] = runner

    # Persistir registro de la run
    with get_session() as s:
        s.add(
            BenchmarkRun(
                id=runner.run_id,
                ts=int(time.time()),
                engine=req.engine,
                hw_json=detect_hardware().model_dump_json(),
                opts_json=req.model_dump_json(),
                notes=req.notes,
                status="running",
            )
        )
        s.commit()

    asyncio.create_task(_run_and_persist(runner))
    return {"run_id": runner.run_id}


async def _run_and_persist(runner: BenchmarkRunner) -> None:
    await runner.run()
    with get_session() as s:
        run = s.get(BenchmarkRun, runner.run_id)
        if run:
            run.status = "done"
            s.add(run)
        for r in runner.results:
            s.add(BenchmarkResult(run_id=runner.run_id, **r.model_dump()))
        s.commit()


@router.get("/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    runner = _RUNNERS.get(run_id)
    if not runner:
        raise HTTPException(404, f"run_id desconocido: {run_id}")

    async def event_gen() -> AsyncIterator[dict[str, Any]]:
        while True:
            evt = await runner.queue.get()
            if evt.get("type") == "_eof":
                yield {"event": "done", "data": json.dumps({"run_id": run_id})}
                _RUNNERS.pop(run_id, None)
                return
            yield {"event": evt.get("type", "message"), "data": json.dumps(evt)}

    return EventSourceResponse(event_gen())
