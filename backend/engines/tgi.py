"""Adaptador para HuggingFace TGI (text-generation-inference)."""
from __future__ import annotations

from core.hardware import safe_gpu_fraction

from .base import Engine, EngineMeta, StartRequest


class TgiEngine(Engine):
    def __init__(self) -> None:
        super().__init__(
            EngineMeta(
                id="tgi",
                name="HF TGI",
                type="local",
                default_port=8088,
                image="ghcr.io/huggingface/text-generation-inference:latest",
                optimizable=True,
                description="HuggingFace text-generation-inference. Solo Docker + GPU NVIDIA.",
                runtimes=["docker"],
                default_runtime="docker",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        opts = req.engine_opts or {}
        cmd: list[str] = []

        hf_id = opts.get("hf_model_id") or opts.get("model")
        if hf_id:
            cmd += ["--model-id", hf_id]

        cmd += ["--port", str(req.port or self.meta.default_port), "--hostname", "0.0.0.0"]

        if opts.get("contextLen"):
            cmd += ["--max-input-tokens", str(int(opts["contextLen"]))]
            cmd += ["--max-total-tokens", str(int(opts["contextLen"]) + 512)]

        quant = opts.get("quant") or opts.get("quantization")
        if quant and quant.lower() not in ("none", "f16", "fp16"):
            cmd += ["--quantize", quant.lower()]

        if opts.get("numShard"):
            cmd += ["--num-shard", str(int(opts["numShard"]))]

        if opts.get("maxBatchPrefill"):
            cmd += ["--max-batch-prefill-tokens", str(int(opts["maxBatchPrefill"]))]

        return cmd

    def build_environment(self, req: StartRequest) -> dict[str, str]:
        # TGI reserva VRAM vía CUDA_MEMORY_FRACTION (no flag). Tope SIEMPRE seguro.
        env = super().build_environment(req)
        safe = safe_gpu_fraction()
        cur = env.get("CUDA_MEMORY_FRACTION")
        try:
            frac = min(float(cur), safe) if cur else safe
        except ValueError:
            frac = safe
        env["CUDA_MEMORY_FRACTION"] = str(round(max(0.1, frac), 2))
        return env
