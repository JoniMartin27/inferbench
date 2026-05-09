"""Adaptador para llama.cpp — soporta runtime nativo (subprocess) y Docker."""
from __future__ import annotations

from pathlib import Path

from core import binary_manager

from .base import Engine, EngineMeta, ProgressCb, StartRequest


class LlamaCppEngine(Engine):
    def __init__(self) -> None:
        super().__init__(
            EngineMeta(
                id="llamacpp",
                name="llama.cpp",
                type="local",
                default_port=8080,
                image="ghcr.io/ggerganov/llama.cpp:server-cuda",
                optimizable=True,
                description="Servidor llama.cpp con soporte GGUF y MoE offload (--n-cpu-moe). Modo nativo: descarga binario oficial.",
                runtimes=["native", "docker"],
                default_runtime="native",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        """Comando para Docker (modelo en /models)."""
        return self._common_args(req, model_path=self.container_model_path(req))

    def native_args(self, req: StartRequest) -> list[str]:
        """Args para subprocess nativo (modelo en ruta del host)."""
        return self._common_args(req, model_path=self.native_model_path(req))

    def _common_args(self, req: StartRequest, *, model_path: str | None) -> list[str]:
        opts = req.engine_opts or {}
        cmd: list[str] = ["--host", "0.0.0.0", "--port", str(req.port or self.meta.default_port)]

        if model_path:
            cmd += ["-m", model_path]

        ctx = opts.get("contextLen") or opts.get("context_len")
        if ctx:
            cmd += ["-c", str(int(ctx))]

        ngl = opts.get("ngl", 99 if req.gpu else 0)
        cmd += ["-ngl", str(int(ngl))]

        kv = opts.get("kvCache") or opts.get("kv_cache")
        if kv:
            cmd += ["-ctk", str(kv), "-ctv", str(kv)]

        n_cpu_moe = opts.get("moeOffload") or opts.get("n_cpu_moe")
        if isinstance(n_cpu_moe, bool):
            n_cpu_moe = None
        if n_cpu_moe:
            cmd += ["--n-cpu-moe", str(int(n_cpu_moe))]

        if opts.get("noMmap") or opts.get("no_mmap"):
            cmd += ["--no-mmap"]
        if opts.get("mlock"):
            cmd += ["--mlock"]
        if opts.get("flashAttn") or opts.get("flash_attn"):
            cmd += ["-fa", "on"]

        threads = opts.get("threads")
        if threads:
            cmd += ["-t", str(int(threads))]

        return cmd

    def native_exe(self):
        async def _ensure(progress: ProgressCb = None) -> Path:
            return await binary_manager.install_llamacpp(progress=progress)

        return _ensure
