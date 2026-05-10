"""Endpoints /api/engines."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core import binary_manager, docker_mgr, native_runtime, ollama_manager
from engines import registry
from engines.base import EngineMeta, StartRequest

router = APIRouter(prefix="/api/engines", tags=["engines"])


class RuntimeAvailability(BaseModel):
    runtime: str
    ready: bool
    detail: str = ""
    install_url: str | None = None


class EngineSummary(BaseModel):
    meta: EngineMeta
    status: native_runtime.ProcessStatus | docker_mgr.ContainerStatus | None = None
    runtimes: list[RuntimeAvailability] = []


def _runtime_avail(meta: EngineMeta) -> list[RuntimeAvailability]:
    out: list[RuntimeAvailability] = []
    for rt in meta.runtimes:
        if rt == "native":
            if meta.id == "llamacpp":
                fully = binary_manager.llamacpp_fully_installed()
                exe_only = binary_manager.llamacpp_installed()
                if fully:
                    detail = "Binario + CUDA listos"
                elif exe_only:
                    detail = "Binario sin DLLs CUDA — descarga pendiente"
                else:
                    detail = "Listo para descargar"
                out.append(
                    RuntimeAvailability(runtime="native", ready=fully, detail=detail)
                )
            elif meta.id == "ollama":
                if ollama_manager.is_installed():
                    out.append(
                        RuntimeAvailability(
                            runtime="native",
                            ready=True,
                            detail=f"Instalado en {ollama_manager.find_ollama_exe()}",
                        )
                    )
                else:
                    out.append(
                        RuntimeAvailability(
                            runtime="native",
                            ready=False,
                            detail="No instalado",
                            install_url=ollama_manager.installer_url() or "https://ollama.com/download",
                        )
                    )
            else:
                out.append(RuntimeAvailability(runtime="native", ready=False, detail="No implementado"))
        elif rt == "docker":
            d = docker_mgr.availability()
            out.append(
                RuntimeAvailability(
                    runtime="docker",
                    ready=d.get("available", False),
                    detail=d.get("hint") or d.get("reason", ""),
                )
            )
    return out


def _engine_status(engine):
    if engine.is_api:
        return None
    try:
        return engine.status()
    except docker_mgr.DockerUnavailableError:
        return native_runtime.status(engine.meta.id)


@router.get("", response_model=list[EngineSummary])
async def list_engines() -> list[EngineSummary]:
    out: list[EngineSummary] = []
    for engine in registry.list_engines():
        out.append(
            EngineSummary(
                meta=engine.meta,
                status=_engine_status(engine),
                runtimes=_runtime_avail(engine.meta),
            )
        )
    return out


@router.get("/{engine_id}", response_model=EngineSummary)
async def get_engine(engine_id: str) -> EngineSummary:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    return EngineSummary(
        meta=engine.meta,
        status=_engine_status(engine),
        runtimes=_runtime_avail(engine.meta),
    )


@router.post("/{engine_id}/start")
async def start_engine(engine_id: str, req: StartRequest):
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    if engine.is_api:
        raise HTTPException(400, f"Motor {engine_id} es API, no se arranca")
    try:
        return await engine.start(req)
    except docker_mgr.DockerUnavailableError as e:
        raise HTTPException(503, str(e)) from e
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("start engine failed")
        raise HTTPException(500, str(e)) from e


@router.post("/{engine_id}/stop")
async def stop_engine(engine_id: str):
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    if engine.is_api:
        raise HTTPException(400, f"Motor {engine_id} es API")
    try:
        return engine.stop()
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.post("/{engine_id}/install")
async def install_engine(engine_id: str) -> EventSourceResponse:
    """Instala (descarga) el binario nativo del motor con progreso SSE."""
    if engine_id != "llamacpp":
        raise HTTPException(400, f"Sin instalador nativo para {engine_id}")

    queue: asyncio.Queue = asyncio.Queue()

    async def progress(evt: dict):
        await queue.put(evt)

    async def runner():
        try:
            path = await binary_manager.install_llamacpp(progress=progress)
            await queue.put({"phase": "ready", "path": str(path)})
        except Exception as e:
            logger.exception("install failed")
            await queue.put({"phase": "error", "message": str(e)})
        finally:
            await queue.put({"phase": "_eof"})

    asyncio.create_task(runner())

    async def event_gen() -> AsyncIterator[dict]:
        while True:
            evt = await queue.get()
            if evt.get("phase") == "_eof":
                yield {"event": "done", "data": json.dumps({"engine": engine_id})}
                return
            yield {"event": evt.get("phase", "progress"), "data": json.dumps(evt)}

    return EventSourceResponse(event_gen())


@router.get("/{engine_id}/logs")
async def engine_logs(engine_id: str, tail: int = 200) -> dict:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    # Probar logs nativos primero, luego Docker
    text = native_runtime.logs(engine_id, tail=tail)
    if not text:
        try:
            text = docker_mgr.logs(engine_id, tail=tail)
        except docker_mgr.DockerUnavailableError:
            pass
    return {"engine": engine_id, "tail": tail, "logs": text}
