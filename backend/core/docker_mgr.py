"""Wrapper sobre Docker SDK: start, stop, status, logs de contenedores de motores."""

from __future__ import annotations

import threading
import time
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


_client_cache = None
_client_lock = threading.Lock()


def _client():
    """Cliente Docker reutilizado.

    `from_env()` lee la configuración y abre el named pipe, y `ping()` es otro viaje al
    daemon: hacerlo en CADA operación se notaba, porque `status()` se llama una vez por
    motor y `EnginesView` pollea cada 4 s. El cliente del SDK es reutilizable y seguro
    entre hilos; si el daemon se cae, la siguiente operación lanza y lo descartamos aquí.
    """
    global _client_cache
    if docker is None:
        raise DockerUnavailableError("docker SDK no instalado")
    with _client_lock:
        if _client_cache is not None:
            return _client_cache
        try:
            client = docker.from_env()
            client.ping()
        except Exception as e:
            raise DockerUnavailableError(f"Docker daemon no accesible: {e}") from e
        _client_cache = client
        return client


def _drop_client() -> None:
    """Tira el cliente cacheado (el daemon se ha caído o reiniciado)."""
    global _client_cache
    with _client_lock:
        cliente, _client_cache = _client_cache, None
    if cliente is not None:
        try:
            cliente.close()
        except Exception:  # noqa: BLE001
            pass


def _docker_cli_installed() -> bool:
    import shutil

    return shutil.which("docker") is not None


# Caché del sondeo de Docker.
#
# MEDIDO: `availability()` crea un cliente (`from_env()`, que lee la config y abre el named
# pipe) y hace `ping()` + `version()` — 200-600 ms por llamada con Docker Desktop arrancado.
# Y `api/engines.py::_runtime_avail` la llama UNA VEZ POR MOTOR: cinco motores declaran
# runtime docker, así que un solo `GET /api/engines` disparaba cinco sondeos completos.
# Con `EnginesView` polleando cada 4 s y `App.jsx` cada 6 s, el resultado era que la app iba
# MÁS LENTA con Docker funcionando que con Docker apagado: `/api/engines` pasaba de 63 ms a
# 0,85-1,8 s y `/api/health` de 9 ms a 700 ms.
#
# Que Docker esté o no arrancado es un hecho de la máquina, no del motor, y cambia como
# mucho cada varios minutos. Un TTL corto lo deja fresco de sobra (la UI pollea cada 4 s)
# y convierte los cinco sondeos por request en cero.
_AVAIL_TTL_S = 10.0
_avail_cache: tuple[float, dict] | None = None
_avail_lock = threading.Lock()


def invalidate_availability() -> None:
    """Olvida el sondeo cacheado. Úsalo tras arrancar/parar Docker desde la app."""
    global _avail_cache
    with _avail_lock:
        _avail_cache = None


def availability(force: bool = False) -> dict:
    """Estado de Docker en el sistema (sin lanzar excepciones), cacheado `_AVAIL_TTL_S`."""
    global _avail_cache
    if not force:
        with _avail_lock:
            if _avail_cache and (time.monotonic() - _avail_cache[0]) < _AVAIL_TTL_S:
                return _avail_cache[1]
    resultado = _probe_availability()
    with _avail_lock:
        _avail_cache = (time.monotonic(), resultado)
    return resultado


def _probe_availability() -> dict:
    """El sondeo de verdad. Caro: no lo llames en bucle, usa `availability()`.

    `hint` viaja hasta la UI (chip de runtime en Motores), así que va en inglés y
    acompañado de `hint_key`: un id estable que el frontend traduce a su idioma
    (`engines.runtime.<hint_key>`). `reason` NO es traducible — es el mensaje crudo del
    SDK de Docker — y por eso no lleva clave.
    """
    if docker is None:
        return {
            "available": False,
            "installed": False,
            "reason": "Docker SDK not installed in the backend",
            "hint": "pip install docker",
            "hint_key": "sdkMissing",
        }
    cli_installed = _docker_cli_installed()
    try:
        client = _client()
        info = client.version()
        return {
            "available": True,
            "installed": True,
            "version": info.get("Version"),
            "api_version": info.get("ApiVersion"),
            "platform": (info.get("Platform") or {}).get("Name"),
        }
    except Exception as e:
        # Si el sondeo falla, el cliente cacheado (si lo había) ya no sirve.
        _drop_client()
        msg = str(e).split("\n")[0][:200]
        return {
            "available": False,
            "installed": cli_installed,
            "reason": msg,
            "hint": ("Start Docker Desktop" if cli_installed else "Install Docker Desktop"),
            "hint_key": ("startDockerDesktop" if cli_installed else "installDockerDesktop"),
        }


def container_name(engine_id: str) -> str:
    return f"{CONTAINER_PREFIX}{engine_id}"


# Instantánea de contenedores nuestros.
#
# `status()` se llama UNA VEZ POR MOTOR, y `GET /api/engines` los recorre todos: eran
# cinco `containers.get()` + `reload()` — dos viajes al daemon cada uno — por request, con
# la UI polleando cada 4 s. Un solo `containers.list(all=True)` los trae todos con sus
# attrs ya rellenos (no hace falta `reload()`). El TTL es muy corto: solo tiene que cubrir
# las llamadas de UNA request, no dar información vieja. Y `start()`/`stop()` lo invalidan
# para que un cambio de estado se vea al instante.
_SNAPSHOT_TTL_S = 1.5
_snapshot_cache: tuple[float, dict[str, Any]] | None = None
_snapshot_lock = threading.Lock()


def invalidate_containers() -> None:
    """Olvida la instantánea de contenedores (tras arrancar o parar uno)."""
    global _snapshot_cache
    with _snapshot_lock:
        _snapshot_cache = None


def _containers_snapshot() -> dict[str, Any]:
    """{nombre: contenedor} de los contenedores de InferBench, cacheado `_SNAPSHOT_TTL_S`."""
    global _snapshot_cache
    with _snapshot_lock:
        if _snapshot_cache and (time.monotonic() - _snapshot_cache[0]) < _SNAPSHOT_TTL_S:
            return _snapshot_cache[1]
    c = _client()  # propaga DockerUnavailableError
    try:
        lista = c.containers.list(all=True, filters={"name": CONTAINER_PREFIX})
    except Exception:
        _drop_client()
        invalidate_availability()
        raise DockerUnavailableError("no pude listar contenedores") from None
    porNombre = {cnt.name: cnt for cnt in lista}
    with _snapshot_lock:
        _snapshot_cache = (time.monotonic(), porNombre)
    return porNombre


def status(engine_id: str) -> ContainerStatus:
    name = container_name(engine_id)
    try:
        cnt = _containers_snapshot().get(name)
    except DockerUnavailableError:
        return ContainerStatus(name=name, state="docker-unavailable")
    if cnt is None:
        return ContainerStatus(name=name, state="missing")
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
    invalidate_containers()  # el estado acaba de cambiar: la instantánea ya no vale
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
    finally:
        invalidate_containers()  # pase lo que pase, el estado cacheado ya no vale
    if remove:
        try:
            cnt.remove(force=True)
        except APIError:
            pass
        invalidate_containers()
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
