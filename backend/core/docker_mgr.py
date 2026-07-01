"""Wrapper sobre Docker SDK: start, stop, status, logs de contenedores de motores."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel

try:
    import docker
    from docker.errors import APIError, NotFound
except ImportError:  # docker SDK no instalado
    docker = None  # type: ignore
    NotFound = Exception  # type: ignore
    APIError = Exception  # type: ignore


CONTAINER_PREFIX = "inferbench-"


class DockerUnavailableError(RuntimeError):
    """Docker daemon no accesible o SDK no instalado."""


class ContainerStatus(BaseModel):
    name: str
    state: str  # running, exited, created, paused, restarting, dead, missing
    image: str | None = None
    ports: dict[str, Any] = {}
    container_id: str | None = None
    gpu: bool | None = None  # True/False si se conoce (start()); None si no aplica (status/stop)


def _client():
    if docker is None:
        raise DockerUnavailableError("docker SDK no instalado")
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        raise DockerUnavailableError(f"Docker daemon no accesible: {e}") from e


def _docker_cli_installed() -> bool:
    import shutil

    return shutil.which("docker") is not None


def availability() -> dict:
    """Devuelve el estado de Docker en el sistema (sin lanzar excepciones)."""
    if docker is None:
        return {
            "available": False,
            "installed": False,
            "reason": "Docker SDK no instalado en el backend",
            "hint": "pip install docker",
        }
    cli_installed = _docker_cli_installed()
    try:
        client = docker.from_env()
        client.ping()
        info = client.version()
        return {
            "available": True,
            "installed": True,
            "version": info.get("Version"),
            "api_version": info.get("ApiVersion"),
            "platform": (info.get("Platform") or {}).get("Name"),
        }
    except Exception as e:
        msg = str(e).split("\n")[0][:200]
        return {
            "available": False,
            "installed": cli_installed,
            "reason": msg,
            "hint": ("Arranca Docker Desktop" if cli_installed else "Instalar Docker Desktop"),
        }


def container_name(engine_id: str) -> str:
    return f"{CONTAINER_PREFIX}{engine_id}"


def status(engine_id: str) -> ContainerStatus:
    name = container_name(engine_id)
    try:
        c = _client()
    except DockerUnavailableError:
        return ContainerStatus(name=name, state="docker-unavailable")
    try:
        cnt = c.containers.get(name)
    except NotFound:
        return ContainerStatus(name=name, state="missing")
    cnt.reload()
    return ContainerStatus(
        name=name,
        state=cnt.status,
        image=cnt.image.tags[0] if cnt.image and cnt.image.tags else None,
        ports=cnt.attrs.get("NetworkSettings", {}).get("Ports") or {},
        container_id=cnt.short_id,
    )


def start(
    engine_id: str,
    image: str,
    *,
    command: list[str] | None = None,
    ports: dict[str, int] | None = None,
    environment: dict[str, str] | None = None,
    volumes: dict[str, dict[str, str]] | None = None,
    gpu: bool = True,
    pull_if_missing: bool = True,
) -> ContainerStatus:
    """Arranca un contenedor (eliminando uno previo con el mismo nombre).

    `ports`: mapping container_port -> host_port  ej. {"8080/tcp": 8080}
    `volumes`: docker SDK style {"/host/path": {"bind": "/cont/path", "mode": "ro"}}
    """
    c = _client()
    name = container_name(engine_id)

    # Limpiar previo
    try:
        existing = c.containers.get(name)
        logger.info(f"Removiendo contenedor previo {name} ({existing.status})")
        existing.remove(force=True)
    except NotFound:
        pass

    # Pull si falta la imagen
    if pull_if_missing:
        try:
            c.images.get(image)
        except NotFound:
            logger.info(f"Pulling image {image}…")
            c.images.pull(image)

    device_requests = None
    if gpu:
        # Petición GPU NVIDIA — si no hay runtime nvidia, Docker fallará con APIError
        device_requests = [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]

    run_kwargs = dict(
        image=image,
        command=command,
        name=name,
        detach=True,
        ports=ports or {},
        environment=environment or {},
        volumes=volumes or {},
        restart_policy={"Name": "no"},
    )
    got_gpu = gpu
    try:
        cnt = c.containers.run(device_requests=device_requests, **run_kwargs)
    except APIError as e:
        # Si falla por GPU, reintentar sin GPU. El motor construyó su comando/flags
        # asumiendo GPU (ver engines/*): el caller debe poder distinguir este caso vía
        # el campo `gpu` de la respuesta, no solo por el log.
        if gpu and "could not select device driver" in str(e).lower():
            logger.warning(
                f"GPU runtime no disponible para {name}, arrancando en CPU "
                f"(el motor podría no funcionar bien sin flags de CPU dedicados)"
            )
            got_gpu = False
            cnt = c.containers.run(**run_kwargs)
        else:
            raise
    cnt.reload()
    return ContainerStatus(
        name=name,
        state=cnt.status,
        image=image,
        ports=cnt.attrs.get("NetworkSettings", {}).get("Ports") or {},
        container_id=cnt.short_id,
        gpu=got_gpu,
    )


def stop(engine_id: str, *, remove: bool = True, timeout: int = 10) -> ContainerStatus:
    name = container_name(engine_id)
    c = _client()
    try:
        cnt = c.containers.get(name)
    except NotFound:
        return ContainerStatus(name=name, state="missing")
    try:
        cnt.stop(timeout=timeout)
    except APIError as e:
        logger.warning(f"stop falló: {e}")
    if remove:
        try:
            cnt.remove(force=True)
        except APIError:
            pass
        return ContainerStatus(name=name, state="missing")
    cnt.reload()
    return ContainerStatus(name=name, state=cnt.status, container_id=cnt.short_id)


def logs(engine_id: str, *, tail: int = 200) -> str:
    name = container_name(engine_id)
    c = _client()
    try:
        cnt = c.containers.get(name)
    except NotFound:
        return ""
    out = cnt.logs(tail=tail, stdout=True, stderr=True)
    return out.decode("utf-8", errors="replace") if isinstance(out, bytes) else str(out)
