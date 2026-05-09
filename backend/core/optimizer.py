"""Optimizador: dado un (motor, modelo, hardware), elige la mejor cuantización + KV-cache + flags + contexto máximo.

Algoritmo del PROJECT_BRIEF:
1. Recorrer cuantizaciones de mayor a menor calidad
2. La primera que quepa con un contexto mínimo de 4096 → ganadora
3. Calcular contexto máximo automático con esa cuantización
4. Activar todas las flags compatibles (flashAttn, mlock, MoE offload si aplica)
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from . import compat
from .hardware import HardwareInfo, detect_hardware
from .models_catalog import Model, get_model

# Cuantizaciones por motor (de mayor a menor calidad)
ENGINE_QUANTS: dict[str, list[str]] = {
    "llamacpp": ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"],
    "ollama": ["q8_0", "q6_K", "q5_K_M", "q4_K_M", "q3_K_M", "q2_K"],
    "vllm": ["fp8", "awq", "gptq", "bitsandbytes"],
    "sglang": ["fp8", "awq", "gptq"],
    "tgi": ["fp8", "awq", "gptq", "bitsandbytes", "eetq"],
}

# KV-cache preferida por motor (mejor calidad → mayor compresión)
ENGINE_KV_PREFERENCE: dict[str, list[str]] = {
    "llamacpp": ["f16", "q8_0", "q4_0"],
    "ollama": ["f16", "q8_0"],
    "vllm": ["auto", "fp8"],
    "sglang": ["auto", "fp8_e5m2"],
    "tgi": ["auto", "fp8"],
}

MIN_CONTEXT = 4096


class OptimizeRequest(BaseModel):
    engine: str
    model_id: str


class OptimalConfig(BaseModel):
    engine: str
    model_id: str
    feasible: bool
    status: compat.CompatStatus
    quant: str | None = None
    kv_cache: str | None = None
    context_len: int = 0
    moe_offload: int | None = None
    flags: dict[str, Any] = {}
    rationale: list[str] = []
    estimated_total_gb: float = 0.0


def _is_api(engine_id: str) -> bool:
    return engine_id in {"openai", "anthropic", "openrouter", "nvidia"}


def get_optimal_config(engine_id: str, model_id: str, hw: HardwareInfo | None = None) -> OptimalConfig:
    model = get_model(model_id)
    if model is None:
        return OptimalConfig(
            engine=engine_id, model_id=model_id, feasible=False, status="fail",
            rationale=[f"Modelo desconocido: {model_id}"],
        )

    if _is_api(engine_id):
        return OptimalConfig(
            engine=engine_id, model_id=model_id, feasible=True, status="api",
            context_len=model.max_ctx,
            rationale=["Motor cloud: solo sampling. Usa max_ctx del modelo."],
        )

    hw = hw or detect_hardware()
    snap = compat.HardwareSnapshot(vram_gb=hw.primary_vram_gb, ram_gb=hw.ram_gb)
    quants = ENGINE_QUANTS.get(engine_id, ENGINE_QUANTS["llamacpp"])
    kv_pref = ENGINE_KV_PREFERENCE.get(engine_id, ["f16"])

    rationale: list[str] = [
        f"Hardware: {hw.primary_vram_gb}GB VRAM + {hw.ram_gb}GB RAM"
    ]

    # MoE offload candidato (solo llama.cpp)
    moe_candidate = _estimate_moe_offload(model, snap) if (model.is_moe and engine_id == "llamacpp") else None
    if moe_candidate:
        rationale.append(f"Modelo MoE detectado: probando --n-cpu-moe={moe_candidate}")

    best: OptimalConfig | None = None
    for kv in kv_pref:
        for quant in quants:
            opts = compat.EngineOpts(
                quant=quant, kv_cache=kv, context_len=MIN_CONTEXT, moe_offload=moe_candidate
            )
            status = compat.check_compat(model, snap, opts, engine_id=engine_id, is_api=False)
            if status in {"ok", "moe", "partial"}:
                max_ctx = compat.compute_max_context(
                    model, snap, opts, engine_id=engine_id, is_api=False
                )
                total = (
                    compat.get_model_size_gb(model, quant)
                    + max_ctx * compat.get_kv_per_token_gb(model, kv)
                    + 0.6
                )
                cfg = OptimalConfig(
                    engine=engine_id,
                    model_id=model_id,
                    feasible=True,
                    status=status,
                    quant=quant,
                    kv_cache=kv,
                    context_len=max_ctx,
                    moe_offload=moe_candidate if status == "moe" else None,
                    flags=_default_flags(engine_id, model, status),
                    rationale=rationale + [
                        f"Elegida cuantización {quant} con KV {kv}: status={status}",
                        f"Contexto máximo automático: {max_ctx} tokens",
                        f"Memoria estimada total: {round(total, 2)} GB",
                    ],
                    estimated_total_gb=round(total, 2),
                )
                # Preferimos status='ok' o 'moe' sobre 'partial'
                if status in {"ok", "moe"} or best is None:
                    best = cfg
                if status in {"ok", "moe"}:
                    return best

    if best:
        return best

    # No cabe ni en CPU
    return OptimalConfig(
        engine=engine_id,
        model_id=model_id,
        feasible=False,
        status="fail",
        rationale=rationale + [
            "Ninguna combinación cabe en este hardware. Considera un modelo más pequeño."
        ],
    )


def _estimate_moe_offload(model: Model, hw: compat.HardwareSnapshot) -> int | None:
    """Estima un valor sensato de --n-cpu-moe.

    Heurística: para que la parte densa quepa en VRAM, descargamos N capas MoE a CPU.
    Asumimos 32 capas medias y proporcional al ratio params/active.
    """
    if hw.vram_gb <= 0 or model.params_b <= 0:
        return None
    # Fracción a descargar = 1 - (vram disponible / tamaño modelo Q4)
    base_size = compat.get_model_size_gb(model, "Q4_K_M")
    if base_size <= hw.vram_gb:
        return None
    excess_ratio = max(0.0, (base_size - hw.vram_gb * 0.85) / base_size)
    n_layers = 32  # aproximación; modelos reales 24-80
    n_offload = int(excess_ratio * n_layers)
    return max(1, min(n_layers - 1, n_offload))


def _default_flags(engine_id: str, model: Model, status: str) -> dict[str, Any]:
    if engine_id == "llamacpp":
        return {
            "flashAttn": True,
            "mlock": status == "ok",  # mlock solo si todo cabe en VRAM
            "noMmap": status == "ok",
        }
    if engine_id == "ollama":
        return {"flashAttn": True}
    if engine_id == "vllm":
        return {"prefixCaching": True, "gpuMemUtil": 0.9}
    if engine_id == "sglang":
        return {"chunkedPrefill": 8192, "torchCompile": False}
    if engine_id == "tgi":
        return {}
    return {}
