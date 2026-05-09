"""Endpoints /api/engines."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from core import docker_mgr
from engines import registry
from engines.base import EngineMeta, StartRequest

router = APIRouter(prefix="/api/engines", tags=["engines"])


class EngineSummary(BaseModel):
    meta: EngineMeta
    status: docker_mgr.ContainerStatus | None = None


@router.get("", response_model=list[EngineSummary])
async def list_engines() -> list[EngineSummary]:
    out: list[EngineSummary] = []
    for engine in registry.list_engines():
        st = None
        if not engine.is_api:
            try:
                st = engine.status()
            except docker_mgr.DockerUnavailableError:
                st = docker_mgr.ContainerStatus(
                    name=docker_mgr.container_name(engine.meta.id),
                    state="docker-unavailable",
                )
        out.append(EngineSummary(meta=engine.meta, status=st))
    return out


@router.get("/{engine_id}", response_model=EngineSummary)
async def get_engine(engine_id: str) -> EngineSummary:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    st = None
    if not engine.is_api:
        try:
            st = engine.status()
        except docker_mgr.DockerUnavailableError:
            st = docker_mgr.ContainerStatus(
                name=docker_mgr.container_name(engine.meta.id),
                state="docker-unavailable",
            )
    return EngineSummary(meta=engine.meta, status=st)


@router.post("/{engine_id}/start", response_model=docker_mgr.ContainerStatus)
async def start_engine(engine_id: str, req: StartRequest) -> docker_mgr.ContainerStatus:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    if engine.is_api:
        raise HTTPException(400, f"Motor {engine_id} es API, no se arranca")
    try:
        return engine.start(req)
    except docker_mgr.DockerUnavailableError as e:
        raise HTTPException(503, str(e)) from e
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("start engine failed")
        raise HTTPException(500, str(e)) from e


@router.post("/{engine_id}/stop", response_model=docker_mgr.ContainerStatus)
async def stop_engine(engine_id: str) -> docker_mgr.ContainerStatus:
    try:
        engine = registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    if engine.is_api:
        raise HTTPException(400, f"Motor {engine_id} es API")
    try:
        return engine.stop()
    except docker_mgr.DockerUnavailableError as e:
        raise HTTPException(503, str(e)) from e


@router.get("/{engine_id}/logs")
async def engine_logs(engine_id: str, tail: int = 200) -> dict:
    try:
        registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")
    try:
        text = docker_mgr.logs(engine_id, tail=tail)
    except docker_mgr.DockerUnavailableError as e:
        raise HTTPException(503, str(e)) from e
    return {"engine": engine_id, "tail": tail, "logs": text}


@router.get("/{engine_id}/logs/stream")
async def engine_logs_stream(engine_id: str):
    try:
        registry.get_engine(engine_id)
    except KeyError:
        raise HTTPException(404, f"Motor desconocido: {engine_id}")

    def gen():
        try:
            for chunk in docker_mgr.stream_logs(engine_id):
                yield chunk
        except docker_mgr.DockerUnavailableError as e:
            yield f"[error] {e}\n"
        except Exception as e:
            yield f"[error] {e}\n"

    return StreamingResponse(gen(), media_type="text/plain")
