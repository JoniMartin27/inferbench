"""Cálculos de compatibilidad de modelos con hardware.

Implementa las fórmulas del PROJECT_BRIEF:
- size_GB(model, quant) = base * QUANT_FACTOR[quant] / 0.55
- kv_per_token_MB(model, kv) = 0.5 * (params/7)^0.7 * KV_FACTOR[kv]
- check_compat() devuelve "api" | "ok" | "moe" | "partial" | "cpu" | "fail"
- compute_max_context() devuelve int (tokens)

Aproximación: en futuro leer n_layer/n_kv_heads/head_dim del config real.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .models_catalog import Model

CompatStatus = Literal["api", "ok", "moe", "partial", "cpu", "fail"]


# Factor relativo a FP16 (size base). Q4_K_M tomado como referencia 0.55.
QUANT_FACTOR: dict[str, float] = {
    "F16": 2.0,
    "fp16": 2.0,
    "Q8_0": 1.0,
    "q8_0": 1.0,
    "Q6_K": 0.81,
    "q6_K": 0.81,
    "Q5_K_M": 0.67,
    "q5_K_M": 0.67,
    "Q4_K_M": 0.55,
    "q4_K_M": 0.55,
    "Q3_K_M": 0.42,
    "q3_K_M": 0.42,
    "Q2_K": 0.32,
    "q2_K": 0.32,
    # vLLM/SGLang/TGI estilos
    "awq": 0.55,      # ~Q4 efectivo
    "gptq": 0.55,
    "fp8": 1.0,
    "bitsandbytes": 0.55,
    "eetq": 0.55,
    "none": 2.0,      # FP16
}


KV_FACTOR: dict[str, float] = {
    "f16": 1.0,
    "F16": 1.0,
    "auto": 1.0,
    "q8_0": 0.5,
    "Q8_0": 0.5,
    "q4_0": 0.25,
    "Q4_0": 0.25,
    "fp8": 0.5,
    "fp8_e5m2": 0.5,
}


# Cuantizaciones de mayor a menor calidad (orden estándar)
QUANT_QUALITY_ORDER = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"]


class HardwareSnapshot(BaseModel):
    """Subconjunto de HardwareInfo necesario para los cálculos."""

    vram_gb: float
    ram_gb: float


class EngineOpts(BaseModel):
    """Opciones de motor relevantes para el cálculo."""

    quant: str = "Q4_K_M"
    kv_cache: str = "f16"
    context_len: int = 4096
    moe_offload: int | bool | None = None  # número de capas en CPU (llama.cpp) o True


def get_model_size_gb(model: Model, quant: str) -> float:
    factor = QUANT_FACTOR.get(quant)
    if factor is None:
        # fallback Q4_K_M
        factor = QUANT_FACTOR["Q4_K_M"]
    return model.size_base_gb * factor / 2.0  # FP16=2 → ratio relativo a FP16


def get_kv_per_token_mb(model: Model, kv_type: str) -> float:
    factor = KV_FACTOR.get(kv_type, 1.0)
    return 0.5 * ((model.params_b / 7.0) ** 0.7) * factor


def get_kv_per_token_gb(model: Model, kv_type: str) -> float:
    return get_kv_per_token_mb(model, kv_type) / 1024.0


def check_compat(
    model: Model,
    hw: HardwareSnapshot,
    opts: EngineOpts,
    *,
    engine_id: str,
    is_api: bool,
) -> CompatStatus:
    if is_api:
        return "api"

    model_size = get_model_size_gb(model, opts.quant)
    kv_per_tok = get_kv_per_token_gb(model, opts.kv_cache)
    kv_overhead = opts.context_len * kv_per_tok
    total = model_size + kv_overhead + 0.6  # overhead fijo

    # Caso especial MoE con --n-cpu-moe (solo llama.cpp)
    if (
        model.is_moe
        and opts.moe_offload
        and engine_id == "llamacpp"
        and hw.vram_gb > 0
    ):
        shared_active = (model.active_b / model.params_b) * model_size + 1.2
        if shared_active <= hw.vram_gb and total <= hw.vram_gb + hw.ram_gb * 0.8:
            return "moe"

    if total <= hw.vram_gb:
        return "ok"
    if hw.vram_gb > 0 and total <= hw.vram_gb + hw.ram_gb * 0.8:
        return "partial"
    if total <= hw.ram_gb * 0.8:
        return "cpu"
    return "fail"


def compute_max_context(
    model: Model,
    hw: HardwareSnapshot,
    opts: EngineOpts,
    *,
    engine_id: str,
    is_api: bool,
) -> int:
    if is_api:
        return model.max_ctx

    model_size = get_model_size_gb(model, opts.quant)
    kv_per_tok = get_kv_per_token_gb(model, opts.kv_cache)

    if model.is_moe and opts.moe_offload and engine_id == "llamacpp":
        avail = hw.vram_gb - ((model.active_b / model.params_b) * model_size + 1.2) - 0.4
    elif model_size <= hw.vram_gb:
        avail = hw.vram_gb - model_size - 0.4
    else:
        avail = (hw.vram_gb + hw.ram_gb * 0.7) - model_size - 0.8

    if avail <= 0.3:
        return 2048
    max_tok = int(avail / kv_per_tok) if kv_per_tok > 0 else model.max_ctx
    rounded = (max_tok // 1024) * 1024
    return max(2048, min(rounded, model.max_ctx))
