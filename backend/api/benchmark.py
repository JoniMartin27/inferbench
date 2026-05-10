"""Endpoints /api/benchmark — POST /run, GET /stream/{run_id} (SSE), POST /stop/{run_id}."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from pydantic import BaseModel, Field

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


class SweepRequest(BaseModel):
    """Lanza el mismo modelo+motor con N cuantizaciones distintas (sequencialmente)."""
    base: BenchmarkRequest
    quants: list[str] = Field(min_length=1)


_SWEEPS: dict[str, dict] = {}  # sweep_id → state


@router.post("/sweep")
async def start_sweep(req: SweepRequest) -> dict:
    import uuid

    sweep_id = uuid.uuid4().hex[:10]
    state = {"id": sweep_id, "queue": list(req.quants), "runs": [], "current": None,
             "cancelled": False, "completed": False}
    _SWEEPS[sweep_id] = state

    async def runner_loop():
        for quant in req.quants:
            if state["cancelled"]:
                break
            sub_req = req.base.model_copy(update={"quant": quant})
            runner = BenchmarkRunner(sub_req)
            _RUNNERS[runner.run_id] = runner
            state["current"] = runner.run_id
            state["runs"].append({"run_id": runner.run_id, "quant": quant})
            with get_session() as s:
                s.add(BenchmarkRun(
                    id=runner.run_id, ts=int(time.time()), engine=sub_req.engine,
                    hw_json=detect_hardware().model_dump_json(),
                    opts_json=sub_req.model_dump_json(),
                    notes=f"[sweep {sweep_id}] {sub_req.notes}".strip(),
                    status="running",
                ))
                s.commit()
            await _run_and_persist(runner)
        state["current"] = None
        state["completed"] = True

    asyncio.create_task(runner_loop())
    return {"sweep_id": sweep_id, "runs_planned": len(req.quants)}


@router.get("/sweep/{sweep_id}")
async def sweep_status(sweep_id: str) -> dict:
    s = _SWEEPS.get(sweep_id)
    if not s:
        raise HTTPException(404, f"sweep desconocido: {sweep_id}")
    return s


@router.post("/sweep/{sweep_id}/stop")
async def sweep_stop(sweep_id: str) -> dict:
    s = _SWEEPS.get(sweep_id)
    if not s:
        raise HTTPException(404, f"sweep desconocido: {sweep_id}")
    s["cancelled"] = True
    if s.get("current"):
        runner = _RUNNERS.get(s["current"])
        if runner:
            runner.cancel()
    return s


@router.post("/{run_id}/stop")
async def stop_run(run_id: str) -> dict:
    runner = _RUNNERS.get(run_id)
    if not runner:
        raise HTTPException(404, f"run_id desconocido o ya finalizado: {run_id}")
    runner.cancel()
    return {"run_id": run_id, "cancelled": True}


@router.get("/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    runner = _RUNNERS.get(run_id)
    if not runner:
        raise HTTPException(404, f"run_id desconocido: {run_id}")

    async def event_gen() -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                evt = await runner.queue.get()
                if evt.get("type") == "_eof":
                    yield {"event": "done", "data": json.dumps({"run_id": run_id})}
                    return
                yield {"event": evt.get("type", "message"), "data": json.dumps(evt)}
        finally:
            _RUNNERS.pop(run_id, None)

    return EventSourceResponse(event_gen())
