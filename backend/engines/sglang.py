"""Adaptador para SGLang (Docker only, requiere GPU NVIDIA)."""
from __future__ import annotations

from core.hardware import capped_gpu_fraction

from .base import Engine, EngineMeta, StartRequest


class SglangEngine(Engine):
    def __init__(self) -> None:
        super().__init__(
            EngineMeta(
                id="sglang",
                name="SGLang",
                type="local",
                default_port=30000,
                image="lmsysorg/sglang:latest",
                optimizable=True,
                description="SGLang server con chunked prefill + speculative decoding (EAGLE3/DFLASH). Solo Docker + GPU NVIDIA.",
                runtimes=["docker"],
                default_runtime="docker",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        opts = req.engine_opts or {}
        cmd: list[str] = ["python3", "-m", "sglang.launch_server"]

        hf_id = opts.get("hf_model_id") or opts.get("model")
        if hf_id:
            cmd += ["--model-path", hf_id]

        cmd += ["--host", "0.0.0.0", "--port", str(req.port or self.meta.default_port)]

        if opts.get("contextLen"):
            cmd += ["--context-length", str(int(opts["contextLen"]))]

        quant = opts.get("quant") or opts.get("quantization")
        if quant and quant.lower() not in ("none", "f16", "fp16"):
            cmd += ["--quantization", quant.lower()]

        # Tope de VRAM SIEMPRE aplicado (default de SGLang ~0.88) para no ahogar el display.
        cmd += ["--mem-fraction-static", str(capped_gpu_fraction(opts.get("memFraction")))]

        if opts.get("chunkedPrefill"):
            cmd += ["--chunked-prefill-size", str(int(opts["chunkedPrefill"]))]

        if opts.get("torchCompile"):
            cmd += ["--enable-torch-compile"]

        # Speculative decoding (DFLASH, EAGLE3, …): SGLang es la ruta oficial de DFLASH.
        spec_method = opts.get("specMethod")
        spec_draft = opts.get("specDraftModel")
        if spec_method and spec_draft:
            cmd += [
                "--speculative-algorithm", str(spec_method).upper(),
                "--speculative-draft-model-path", spec_draft,
                "--speculative-num-draft-tokens", str(int(opts.get("specNumTokens") or 16)),
            ]

        return cmd
