"""Adaptador para Ollama — soporta runtime nativo (binario `ollama`) y Docker."""

from __future__ import annotations

from pathlib import Path

from core import ollama_manager

from .base import Engine, EngineMeta, ProgressCb, StartRequest


class OllamaEngine(Engine):
    def __init__(self) -> None:
        super().__init__(
            EngineMeta(
                id="ollama",
                name="Ollama",
                type="local",
                default_port=11434,
                image="ollama/ollama:latest",
                optimizable=True,
                description="Daemon Ollama: modelos vía su registro propio (llama3.2:1b, qwen2.5:7b…). API OpenAI-compatible.",
                runtimes=["native", "docker"],
                default_runtime="native",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        # Para Docker: el contenedor arranca el daemon por defecto
        return []

    def native_args(self, req: StartRequest) -> list[str]:
        return ["serve"]

    def build_environment(self, req: StartRequest) -> dict[str, str]:
        env = super().build_environment(req)
        opts = req.engine_opts or {}
        # Optimizaciones documentadas de Ollama
        if opts.get("flashAttn"):
            env["OLLAMA_FLASH_ATTENTION"] = "1"
        if opts.get("kvCache"):
            env["OLLAMA_KV_CACHE_TYPE"] = str(opts["kvCache"])
        if opts.get("numParallel"):
            env["OLLAMA_NUM_PARALLEL"] = str(int(opts["numParallel"]))
        return env

    def native_exe(self):
        async def _ensure(progress: ProgressCb = None) -> Path:
            exe = ollama_manager.find_ollama_exe()
            if not exe:
                raise RuntimeError(
                    "Ollama no instalado. Instálalo desde https://ollama.com/download "
                    "y vuelve a intentarlo."
                )
            return exe

        return _ensure
