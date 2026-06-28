"""Interfaz abstracta de motor de inferencia (Docker o nativo)."""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from core import docker_mgr, hardware, native_runtime

EngineType = Literal["local", "api"]
RuntimeKind = Literal["native", "docker"]

ProgressCb = Callable[[dict], Awaitable[None]] | None


class EngineMeta(BaseModel):
    id: str
    name: str
    type: EngineType
    default_port: int | None = None
    image: str | None = None
    optimizable: bool = True
    description: str = ""
    runtimes: list[RuntimeKind] = []  # qué runtimes soporta
    default_runtime: RuntimeKind = "docker"
    quants: list[str] = []  # cuantizaciones válidas para ESTE motor (vacío = no aplica)


class StartRequest(BaseModel):
    model_path: str | None = None
    port: int | None = None
    gpu: bool = True
    runtime: RuntimeKind | None = None  # None = usar default
    engine_opts: dict[str, Any] = Field(default_factory=dict)
    extra_env: dict[str, str] = Field(default_factory=dict)


def _docker_hf_cache() -> Path:
    """Directorio host del caché HF que comparten los contenedores (persistente)."""
    base = (
        Path(os.environ["APPDATA"]) / "InferBench"
        if os.name == "nt" and os.environ.get("APPDATA")
        else Path.home() / ".inferbench"
    )
    d = base / "docker-hf-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Engine(ABC):
    meta: EngineMeta

    def __init__(self, meta: EngineMeta) -> None:
        self.meta = meta

    @property
    def is_api(self) -> bool:
        return self.meta.type == "api"

    @abstractmethod
    def build_command(self, req: StartRequest) -> list[str]:
        """Args CLI a pasar al contenedor o al binario nativo."""

    def build_environment(self, req: StartRequest) -> dict[str, str]:
        return dict(req.extra_env)

    def build_volumes(self, req: StartRequest) -> dict[str, dict[str, str]]:
        vols: dict[str, dict[str, str]] = {}
        if req.model_path:
            host_dir = os.path.dirname(os.path.abspath(req.model_path))
            vols[host_dir] = {"bind": "/models", "mode": "ro"}
        # Caché HF persistente: vLLM/SGLang/TGI descargan el modelo dentro del contenedor;
        # sin este volumen lo re-descargarían en CADA run (lento y puede agotar el timeout).
        vols[str(_docker_hf_cache())] = {"bind": "/root/.cache/huggingface", "mode": "rw"}
        return vols

    def container_model_path(self, req: StartRequest) -> str | None:
        if not req.model_path:
            return None
        import os

        return f"/models/{os.path.basename(req.model_path)}"

    def native_model_path(self, req: StartRequest) -> str | None:
        return req.model_path

    def native_args(self, req: StartRequest) -> list[str]:
        """Args para el binario nativo. Por defecto usa build_command,
        pero los motores pueden sobrescribir si la sintaxis difiere de Docker."""
        return self.build_command(req)

    def native_exe(self) -> Any:  # Path | Awaitable[Path]
        raise NotImplementedError(f"{self.meta.id} no tiene runtime nativo")

    def resolve_runtime(self, req: StartRequest) -> RuntimeKind:
        wanted = req.runtime or self.meta.default_runtime
        if wanted not in self.meta.runtimes:
            raise ValueError(
                f"Motor {self.meta.id} no soporta runtime '{wanted}' "
                f"(soportados: {self.meta.runtimes})"
            )
        return wanted

    async def start(self, req: StartRequest, progress: ProgressCb = None):
        if self.is_api:
            raise ValueError(f"Motor {self.meta.id} es API, no se arranca")
        runtime = self.resolve_runtime(req)
        if runtime == "docker":
            # _start_docker es bloqueante (Docker SDK síncrono: images.pull de varios GB
            # puede tardar minutos). En un hilo para no congelar el event loop de FastAPI.
            return await asyncio.to_thread(self._start_docker, req)
        return await self._start_native(req, progress)

    def _start_docker(self, req: StartRequest):
        if not self.meta.image:
            raise ValueError(f"Motor {self.meta.id} no tiene imagen Docker")
        port = req.port or self.meta.default_port
        if port is None:
            raise ValueError(f"Motor {self.meta.id} requiere puerto")
        # GUARD de seguridad: no arrancar si no queda VRAM suficiente tras reservar el
        # margen del display → evita saturar la GPU y congelar la pantalla. Surfacea error.
        if req.gpu:
            safe = hardware.safe_gpu_fraction()
            if safe < 0.15:
                free, total = hardware.gpu_memory_gb()
                raise RuntimeError(
                    f"VRAM insuficiente para arrancar {self.meta.id} sin saturar la pantalla "
                    f"(libre {free:.1f} de {total:.1f} GB; se reserva margen para el display). "
                    f"Cierra apps que usen la GPU, elige un modelo más pequeño/cuantizado, o "
                    f"baja INFERBENCH_GPU_RESERVE_GB si esta GPU no pinta tu monitor."
                )
        # El contenedor escucha en `port` (build_command usa req.port or default_port);
        # publicar host:port → container:port. Clavarlo a default_port dejaba el motor
        # inalcanzable si el llamador pasaba un req.port distinto.
        ports = {f"{port}/tcp": port}
        # Un comando vacío ([]) significa "usa el CMD por defecto de la imagen" (p.ej. el
        # contenedor de Ollama arranca su daemon solo). Pasar [] a docker-py SOBREESCRIBE el
        # CMD con nada → contenedor inútil. Lo convertimos a None para respetar el default.
        command = self.build_command(req) or None
        st = docker_mgr.start(
            self.meta.id,
            image=self.meta.image,
            command=command,
            ports=ports,
            environment=self.build_environment(req),
            volumes=self.build_volumes(req),
            gpu=req.gpu,
        )
        return st

    async def _start_native(self, req: StartRequest, progress: ProgressCb):
        exe = self.native_exe()
        if hasattr(exe, "__await__"):
            exe = await exe  # type: ignore
        elif callable(exe):
            exe = exe(progress)
            if hasattr(exe, "__await__"):
                exe = await exe
        port = req.port or self.meta.default_port
        return native_runtime.start(
            self.meta.id,
            exe=exe,
            args=self.native_args(req),
            env=self.build_environment(req),
            port=port,
        )

    def stop(self):
        # Probar ambos runtimes — el que esté activo
        try:
            n = native_runtime.status(self.meta.id)
            if n.state == "running":
                return native_runtime.stop(self.meta.id)
        except Exception:
            pass
        try:
            return docker_mgr.stop(self.meta.id)
        except docker_mgr.DockerUnavailableError:
            return native_runtime.stop(self.meta.id)

    def status(self):
        # Si hay proceso nativo activo, ese gana
        n = native_runtime.status(self.meta.id)
        if n.state == "running":
            return n
        try:
            d = docker_mgr.status(self.meta.id)
            if d.state in ("running", "exited", "created", "paused", "restarting", "dead"):
                return d
            # Docker apagado: para un motor solo-Docker el nativo informará "missing";
            # propaga "docker-unavailable" para que la UI muestre el badge correcto.
            if d.state == "docker-unavailable" and n.state in ("missing", "stopped"):
                return d
        except Exception:
            pass
        return n
