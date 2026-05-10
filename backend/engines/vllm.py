"""Adaptador para vLLM (Docker only, requiere GPU NVIDIA)."""
from __future__ import annotations

from .base import Engine, EngineMeta, StartRequest


class VllmEngine(Engine):
    def __init__(self) -> None:
        super().__init__(
            EngineMeta(
                id="vllm",
                name="vLLM",
                type="local",
                default_port=8000,
                image="vllm/vllm-openai:latest",
                optimizable=True,
                description="Servidor vLLM con prefix caching y speculative decoding. Solo Docker + GPU NVIDIA.",
                runtimes=["docker"],
                default_runtime="docker",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        opts = req.engine_opts or {}
        cmd: list[str] = []

        hf_id = opts.get("hf_model_id") or opts.get("model")
        if hf_id:
            cmd += ["--model", hf_id]

        cmd += ["--port", str(req.port or self.meta.default_port)]
        cmd += ["--host", "0.0.0.0"]

        if opts.get("contextLen"):
            cmd += ["--max-model-len", str(int(opts["contextLen"]))]

        quant = opts.get("quant") or opts.get("quantization")
        if quant and quant.lower() not in ("none", "f16", "fp16"):
            cmd += ["--quantization", quant.lower()]

        kv = opts.get("kvCache")
        if kv and kv != "auto":
            cmd += ["--kv-cache-dtype", kv]

        if opts.get("gpuMemUtil"):
            cmd += ["--gpu-memory-utilization", str(opts["gpuMemUtil"])]

        if opts.get("enforceEager"):
            cmd += ["--enforce-eager"]

        if opts.get("prefixCaching"):
            cmd += ["--enable-prefix-caching"]

        return cmd
