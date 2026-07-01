"""Adaptador para vLLM (Docker only, requiere GPU NVIDIA)."""

from __future__ import annotations

import json

from core.hardware import capped_gpu_fraction

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
                description="Servidor vLLM con prefix caching y speculative decoding (DFLASH/EAGLE). Solo Docker + GPU NVIDIA.",
                runtimes=["docker"],
                default_runtime="docker",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        opts = req.engine_opts or {}
        cmd: list[str] = []

        hf_id = opts.get("hf_model_id") or opts.get("model")
        if hf_id:
            cmd += ["--model", str(hf_id)]

        cmd += ["--port", str(req.port or self.meta.default_port)]
        cmd += ["--host", "0.0.0.0"]

        if opts.get("contextLen"):
            cmd += ["--max-model-len", str(int(opts["contextLen"]))]

        quant = opts.get("quant") or opts.get("quantization")
        if quant and str(quant).lower() not in ("none", "f16", "fp16"):
            cmd += ["--quantization", str(quant).lower()]

        kv = opts.get("kvCache")
        if kv and kv != "auto":
            cmd += ["--kv-cache-dtype", str(kv)]

        # Tope de VRAM SIEMPRE aplicado (default de vLLM 0.9) para no ahogar el display.
        cmd += ["--gpu-memory-utilization", str(capped_gpu_fraction(opts.get("gpuMemUtil")))]

        if opts.get("enforceEager"):
            cmd += ["--enforce-eager"]  # sin CUDA graphs → ahorra VRAM (clave en GPUs chicas)

        if opts.get("maxNumSeqs"):
            cmd += ["--max-num-seqs", str(int(opts["maxNumSeqs"]))]

        if opts.get("prefixCaching"):
            cmd += ["--enable-prefix-caching"]

        # Speculative decoding (DFLASH, EAGLE, …): acelera con un modelo draft. vLLM lo
        # configura con --speculative-config (JSON). DFLASH además exige flash_attn.
        spec_method = opts.get("specMethod")
        spec_draft = opts.get("specDraftModel")
        if spec_method and spec_draft:
            cmd += [
                "--speculative-config",
                json.dumps(
                    {
                        "method": str(spec_method).lower(),
                        "model": spec_draft,
                        "num_speculative_tokens": int(opts.get("specNumTokens") or 5),
                    }
                ),
            ]
            if str(spec_method).lower() == "dflash":
                cmd += ["--attention-backend", "flash_attn"]

        return cmd
