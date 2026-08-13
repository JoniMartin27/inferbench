"""Endpoints /api/engines."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core import binary_manager, docker_mgr, native_runtime, ollama_manager
from engines import registry
from engines.base import Engine, EngineMeta, StartRequest

router = APIRouter(prefix="/api/engines", tags=["engines"])


class RuntimeAvailability(BaseModel):
    """Disponibilidad de un runtime, lista para pintar en cualquier idioma.

    `detail` es el texto en INGLÉS (fallback y documentación de la API). La UI, que
    habla ES y EN, traduce por `detail_key` (`engines.runtime.<key>`) interpolando
    `detail_params`, y solo cae a `detail` cuando no hay clave — el caso del error
    crudo del SDK de Docker, que no es enumerable y por tanto no es traducible.
    """

    runtime: str
    ready: bool
    detail: str = ""
    detail_key: str | None = None
    detail_params: dict[str, str] = {}
    install_url: str | None = None


class EngineSummary(BaseModel):
    meta: EngineMeta
    status: native_runtime.ProcessStatus | docker_mgr.ContainerStatus | None = None
    runtimes: list[RuntimeAvailability] = []


def _binary_avail(ready_full: bool, exe_only: bool) -> RuntimeAvailability:
    """Estado de un binario nativo auto-descargable (llama.cpp, sd.cpp)."""
    if ready_full:
        key, detail = "binaryCudaReady", "Binary + CUDA ready"
    elif exe_only:
        key, detail = "binaryNoCuda", "Binary without CUDA DLLs — download pending"
    else:
        key, detail = "readyToDownload", "Ready to download"
    return RuntimeAvailability(runtime="native", ready=ready_full, detail=detail, detail_key=key)


def _runtime_avail(meta: EngineMeta) -> list[RuntimeAvailability]:
    out: list[RuntimeAvailability] = []
    for rt in meta.runtimes:
        if rt == "native":
            if meta.id == "llamacpp":
                out.append(
                    _binary_avail(
                        binary_manager.llamacpp_fully_installed(),
                        binary_manager.llamacpp_installed(),
                    )
                )
            elif meta.id == "ollama":
                if ollama_manager.is_installed():
                    # Solo el nombre del ejecutable: no filtrar la ruta absoluta del usuario.
                    exe = ollama_manager.find_ollama_exe()
                    out.append(
                        RuntimeAvailability(
                            runtime="native",
                            ready=True,
                            detail=f"Installed ({exe.name})" if exe else "Installed",
                            detail_key="installedExe" if exe else "installed",
                            detail_params={"exe": exe.name} if exe else {},
                        )
                    )
                else:
                    out.append(
                        RuntimeAvailability(
                            runtime="native",
                            ready=False,
                            detail="Not installed",
                            detail_key="notInstalled",
                            install_url=ollama_manager.installer_url()
                            or "https://ollama.com/download",
                        )
                    )
            elif meta.id == "stablediffusion":
                # `binary_manager` ya sabía responder por sd.cpp (`stablediffusion_installed`
                # / `_fully_installed`, calcados de los de llama.cpp), pero nadie los
                # llamaba: el motor caía en el `else` de abajo y la UI anunciaba
                # "No implementado" para una funcionalidad que SÍ está implementada y que
                # se auto-descarga al primer arranque, igual que llama.cpp. Resultado: la
                # generación de imagen parecía muerta y nadie la pulsaba.
                out.append(
                    _binary_avail(
                        binary_manager.stablediffusion_fully_installed(),
                        binary_manager.stablediffusion_installed(),
                    )
                )
            else:
                out.append(
                    RuntimeAvailability(
                        runtime="native",
                        ready=False,
                        detail="Not implemented",
                        detail_key="notImplemented",
                    )
                )
        elif rt == "docker":
            d = docker_mgr.availability()
            params: dict[str, str] = {}
            if d.get("available"):
                # `hint`/`reason` solo existen cuando Docker NO está disponible, así que en
                # el camino feliz el detalle salía VACÍO y la UI pintaba el chip como
                # "docker:" seguido de nada — parecía roto justo cuando todo iba bien.
                version = d.get("version")
                if version:
                    detail, key = f"Docker {version}", "dockerVersion"
                    params = {"version": str(version)}
                else:
                    detail, key = "Available", "dockerAvailable"
            else:
                # `hint` trae su `hint_key` traducible; `reason` es el mensaje crudo del SDK
                # y se pinta tal cual (sin clave) porque no es un estado enumerable.
                hint, hint_key = d.get("hint"), d.get("hint_key")
                if hint:
                    detail, key = hint, hint_key or None
                else:
                    detail, key = d.get("reason") or "Not available", None
            out.append(
                RuntimeAvailability(
                    runtime="docker",
                    ready=bool(d.get("available")),
                    detail=detail,
                    detail_key=key,
                    detail_params=params,
                )
            )
    return out


def _engine_status(
    engine: Engine,
) -> native_runtime.ProcessStatus | docker_mgr.ContainerStatus | None:
    if engine.is_api:
        return None
    try:
        return engine.status()
    except docker_mgr.DockerUnavailableError:
        return native_runtime.status(engine.meta.id)


def _summarize(engine) -> EngineSummary:
    # `_engine_status`/`_runtime_avail` hacen I/O de Docker BLOQUEANTE (from_env+ping+version).
    # Se llaman desde handlers async y EnginesView pollea cada 4s: hay que sacarlo del event loop.
    return EngineSummary(
        meta=engine.meta,
        status=_engine_status(engine),
        runtimes=_runtime_avail(engine.meta),
    )


@router.get("", response_model=list[EngineSummary])
async def list_engines() -> list[EngineSummary]:
    engines = registry.list_engines()
    return await asyncio.to_thread(lambda: [_summarize(e) for e in engines])


@router.get("/{engine_id}", response_model=EngineSummary)
async def get_engine(engine_id: str) -> EngineSummary:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError as e:
        raise HTTPException(404, f"Unknown engine: {engine_id}") from e
    return await asyncio.to_thread(_summarize, engine)


@router.post("/{engine_id}/start")
async def start_engine(
    engine_id: str, req: StartRequest
) -> native_runtime.ProcessStatus | docker_mgr.ContainerStatus:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError as e:
        raise HTTPException(404, f"Unknown engine: {engine_id}") from e
    if engine.is_api:
        raise HTTPException(400, f"Engine {engine_id} is an API, it can't be started")
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
async def stop_engine(
    engine_id: str,
) -> native_runtime.ProcessStatus | docker_mgr.ContainerStatus:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError as e:
        raise HTTPException(404, f"Unknown engine: {engine_id}") from e
    if engine.is_api:
        raise HTTPException(400, f"Engine {engine_id} is an API")
    try:
        # stop() Docker es bloqueante (hasta ~10s); en un hilo para no congelar el event loop.
        return await asyncio.to_thread(engine.stop)
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.post("/{engine_id}/install")
async def install_engine(engine_id: str) -> EventSourceResponse:
    """Instala (descarga) el binario nativo del motor con progreso SSE."""
    if engine_id != "llamacpp":
        raise HTTPException(400, f"No native installer for {engine_id}")

    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress(evt: dict) -> None:
        await queue.put(evt)

    async def runner() -> None:
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


class EngineLogs(BaseModel):
    engine: str
    tail: int
    logs: str


@router.get("/{engine_id}/logs", response_model=EngineLogs)
async def engine_logs(engine_id: str, tail: int = Query(200, ge=1, le=5_000)) -> EngineLogs:
    try:
        registry.get_engine(engine_id)  # valida que el motor existe
    except KeyError as e:
        raise HTTPException(404, f"Unknown engine: {engine_id}") from e
    # Probar logs nativos primero, luego Docker
    text = native_runtime.logs(engine_id, tail=tail)
    if not text:
        try:
            text = docker_mgr.logs(engine_id, tail=tail)
        except docker_mgr.DockerUnavailableError as e:
            # No es fatal: puede ser un motor nativo sin contenedor, o Docker apagado.
            # No rompemos la respuesta, pero dejamos rastro en vez de tragarlo en silencio.
            logger.debug(f"logs de {engine_id}: Docker no disponible ({e})")
    return EngineLogs(engine=engine_id, tail=tail, logs=text)
