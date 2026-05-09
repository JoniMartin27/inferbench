"""Adaptador para llama.cpp server (ghcr.io/ggerganov/llama.cpp:server-cuda)."""
from __future__ import annotations

from .base import Engine, EngineMeta, StartRequest


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
                description="Servidor llama.cpp con soporte GGUF, MoE offload (--n-cpu-moe).",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        opts = req.engine_opts or {}
        cmd: list[str] = ["--host", "0.0.0.0", "--port", str(self.meta.default_port)]

        model_in_container = self.container_model_path(req)
        if model_in_container:
            cmd += ["-m", model_in_container]

        # Contexto
        ctx = opts.get("contextLen") or opts.get("context_len")
        if ctx:
            cmd += ["-c", str(int(ctx))]

        # GPU layers — por defecto todas
        ngl = opts.get("ngl", 99 if req.gpu else 0)
        cmd += ["-ngl", str(int(ngl))]

        # KV cache: -ctk / -ctv (ej. q8_0, q4_0, f16)
        kv = opts.get("kvCache") or opts.get("kv_cache")
        if kv:
            cmd += ["-ctk", str(kv), "-ctv", str(kv)]

        # MoE offload
        n_cpu_moe = opts.get("moeOffload") or opts.get("n_cpu_moe")
        if isinstance(n_cpu_moe, bool):
            # Si solo viene True/False, no podemos elegir N — el frontend debe pasar el número.
            n_cpu_moe = None
        if n_cpu_moe:
            cmd += ["--n-cpu-moe", str(int(n_cpu_moe))]

        if opts.get("noMmap") or opts.get("no_mmap"):
            cmd += ["--no-mmap"]
        if opts.get("mlock"):
            cmd += ["--mlock"]
        if opts.get("flashAttn") or opts.get("flash_attn"):
            cmd += ["-fa"]

        # Threads
        threads = opts.get("threads")
        if threads:
            cmd += ["-t", str(int(threads))]

        return cmd
