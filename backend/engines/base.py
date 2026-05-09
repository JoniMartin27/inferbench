"""Interfaz abstracta de motor de inferencia."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from core import docker_mgr

EngineType = Literal["local", "api"]


class EngineMeta(BaseModel):
    id: str
    name: str
    type: EngineType
    default_port: int | None = None
    image: str | None = None
    optimizable: bool = True
    description: str = ""


class StartRequest(BaseModel):
    """Opciones genéricas + específicas del motor.

    `model_path` es una ruta absoluta en el host (montada en /models en el contenedor).
    `engine_opts` son las flags propias de cada motor (ver PROJECT_BRIEF).
    """

    model_path: str | None = None
    port: int | None = None
    gpu: bool = True
    engine_opts: dict[str, Any] = Field(default_factory=dict)
    extra_env: dict[str, str] = Field(default_factory=dict)


class Engine(ABC):
    meta: EngineMeta

    def __init__(self, meta: EngineMeta) -> None:
        self.meta = meta

    @property
    def is_api(self) -> bool:
        return self.meta.type == "api"

    @abstractmethod
    def build_command(self, req: StartRequest) -> list[str]:
        """Construye el comando CLI a pasar al contenedor."""

    def build_environment(self, req: StartRequest) -> dict[str, str]:
        return dict(req.extra_env)

    def build_volumes(self, req: StartRequest) -> dict[str, dict[str, str]]:
        vols: dict[str, dict[str, str]] = {}
        if req.model_path:
            import os

            host_dir = os.path.dirname(os.path.abspath(req.model_path))
            vols[host_dir] = {"bind": "/models", "mode": "ro"}
        return vols

    def container_model_path(self, req: StartRequest) -> str | None:
        if not req.model_path:
            return None
        import os

        return f"/models/{os.path.basename(req.model_path)}"

    def start(self, req: StartRequest) -> docker_mgr.ContainerStatus:
        if self.is_api:
            raise ValueError(f"Motor {self.meta.id} es API, no se arranca por Docker")
        if not self.meta.image:
            raise ValueError(f"Motor {self.meta.id} no tiene imagen Docker")
        port = req.port or self.meta.default_port
        if port is None:
            raise ValueError(f"Motor {self.meta.id} requiere puerto")
        ports = {f"{self.meta.default_port}/tcp": port}
        return docker_mgr.start(
            self.meta.id,
            image=self.meta.image,
            command=self.build_command(req),
            ports=ports,
            environment=self.build_environment(req),
            volumes=self.build_volumes(req),
            gpu=req.gpu,
        )

    def stop(self) -> docker_mgr.ContainerStatus:
        return docker_mgr.stop(self.meta.id)

    def status(self) -> docker_mgr.ContainerStatus:
        return docker_mgr.status(self.meta.id)
