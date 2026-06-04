"""Adaptador para HuggingFace TGI (text-generation-inference)."""
from __future__ import annotations

from core.hardware import capped_gpu_fraction

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
            # max-total-tokens = input + output, y debe caber en la ventana (contextLen).
            # Antes input=contextLen + total=contextLen+512 dejaba la salida capada a 512
            # y total fuera de ventana. Reservamos presupuesto de salida DENTRO de la
            # ventana: input = contextLen − out_budget, total = contextLen.
            ctx = int(opts["contextLen"])
            out_budget = min(1024, max(256, ctx // 4))
            cmd += ["--max-input-tokens", str(max(256, ctx - out_budget))]
            cmd += ["--max-total-tokens", str(ctx)]

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
        env["CUDA_MEMORY_FRACTION"] = str(capped_gpu_fraction(env.get("CUDA_MEMORY_FRACTION")))
        return env
