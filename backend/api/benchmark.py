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

# Estado en memoria de runs activas. Cap explícito: si un cliente postea runs sin
# conectarse al stream SSE, los runners quedan huérfanos. Purgamos los más viejos
# cuando se supera el límite para evitar fuga de memoria.
_RUNNERS: dict[str, BenchmarkRunner] = {}
_MAX_RUNNERS = 100

# Un solo motor/puerto físico por engine_id (un llama-server en :8080, un contenedor
# inferbench-<engine>, etc.). Si dos runs del MISMO motor corren a la vez se pisan el
# arranque y las métricas se atribuyen al modelo equivocado (rompe la regla "no datos
# inventados"). Serializamos por engine_id con un lock; runs de motores DISTINTOS sí van
# en paralelo. Los sweeps ya eran secuenciales, así que el lock no los bloquea entre sí.
_ENGINE_LOCKS: dict[str, asyncio.Lock] = {}


def _engine_lock(engine: str) -> asyncio.Lock:
    lock = _ENGINE_LOCKS.get(engine)
    if lock is None:
        lock = asyncio.Lock()
        _ENGINE_LOCKS[engine] = lock
    return lock


def _prune_runners() -> None:
    while len(_RUNNERS) > _MAX_RUNNERS:
        _RUNNERS.pop(next(iter(_RUNNERS)), None)


@router.post("/run")
async def start_run(req: BenchmarkRequest) -> dict[str, str]:
    runner = BenchmarkRunner(req)
    _RUNNERS[runner.run_id] = runner
    _prune_runners()

    # Persistir registro de la run
    with get_session() as s:
        s.add(
            BenchmarkRun(
                id=runner.run_id,
                ts=int(time.time()),
                engine=req.engine,
                hw_json=detect_hardware().model_dump_json(),
                opts_json=req.model_dump_json(exclude={"api_key"}),
                notes=req.notes,
                status="running",
            )
        )
        s.commit()

    asyncio.create_task(_run_and_persist(runner))
    return {"run_id": runner.run_id}


async def _run_and_persist(runner: BenchmarkRunner) -> None:
    lock = _engine_lock(runner.req.engine)
    if lock.locked():
        runner.queue.put_nowait(
            {"type": "log", "level": "info",
             "text": f"Motor {runner.req.engine} ocupado por otra run; esperando turno…"}
        )
    async with lock:
        started = time.time()
        await runner.run()
        ended = time.time()
    with get_session() as s:
        run = s.get(BenchmarkRun, runner.run_id)
        if run:
            run.status = "done"
            s.add(run)
        for r in runner.results:
            s.add(BenchmarkResult(run_id=runner.run_id, **r.model_dump()))
        s.commit()

    # Observabilidad opt-in: exporta el run como trace a lookspan (best-effort, no rompe nada)
    from core import lookspan

    await lookspan.export_run(
        runner.run_id, runner.req.engine, runner.req.model, runner.req.quant,
        runner.results, started, ended, runner.req.engine_opts,
    )


class SweepRequest(BaseModel):
    """Lanza el mismo modelo+motor con N cuantizaciones distintas (sequencialmente)."""
    base: BenchmarkRequest
    quants: list[str] = Field(min_length=1)


_SWEEPS: dict[str, dict] = {}  # sweep_id → state
_MAX_SWEEPS = 50


@router.post("/sweep")
async def start_sweep(req: SweepRequest) -> dict:
    import uuid

    sweep_id = uuid.uuid4().hex[:10]
    state = {"id": sweep_id, "queue": list(req.quants), "runs": [], "current": None,
             "cancelled": False, "completed": False}
    _SWEEPS[sweep_id] = state
    # Purgar sweeps completados más viejos si se supera el cap
    if len(_SWEEPS) > _MAX_SWEEPS:
        done = [k for k, v in _SWEEPS.items() if v.get("completed") or v.get("cancelled")]
        for k in done[:len(_SWEEPS) - _MAX_SWEEPS]:
            _SWEEPS.pop(k, None)

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
                    opts_json=sub_req.model_dump_json(exclude={"api_key"}),
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
                try:
                    evt = await asyncio.wait_for(runner.queue.get(), timeout=600.0)
                except asyncio.TimeoutError:
                    yield {"event": "error", "data": json.dumps({"error": "stream timeout"})}
                    return
                if evt.get("type") == "_eof":
                    yield {"event": "done", "data": json.dumps({"run_id": run_id})}
                    return
                yield {"event": evt.get("type", "message"), "data": json.dumps(evt)}
        finally:
            _RUNNERS.pop(run_id, None)

    return EventSourceResponse(event_gen())
