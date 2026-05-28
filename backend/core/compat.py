"""Cálculos de compatibilidad de modelos con hardware.

Implementa las fórmulas del PROJECT_BRIEF:
- size_GB(model, quant) = base * QUANT_FACTOR[quant] / 0.55
- kv_per_token_MB(model, kv) = 0.5 * (params/7)^0.7 * KV_FACTOR[kv]
- check_compat() devuelve "api" | "ok" | "moe" | "partial" | "cpu" | "disk" | "fail" | "nofile"
- compute_max_context() devuelve int (tokens)

Aproximación: en futuro leer n_layer/n_kv_heads/head_dim del config real.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .models_catalog import Model

CompatStatus = Literal["api", "ok", "moe", "partial", "cpu", "disk", "fail", "nofile"]


# Factor relativo a FP16 (size base). Q4_K_M tomado como referencia 0.55.
# Bits/param aproximados → factor = bits/16 (relativo a FP16=16 bits)
QUANT_FACTOR: dict[str, float] = {
    "F16": 2.0, "fp16": 2.0, "BF16": 2.0,
    "Q8_0": 1.0, "q8_0": 1.0,                         # 8.0 bits
    "Q6_K": 0.81, "q6_K": 0.81,                        # 6.5
    "Q5_K_M": 0.67, "q5_K_M": 0.67,                    # 5.4
    "Q5_K_S": 0.65, "q5_K_S": 0.65,
    "Q4_K_M": 0.55, "q4_K_M": 0.55,                    # 4.4
    "Q4_K_S": 0.53, "q4_K_S": 0.53,
    "IQ4_XS": 0.50, "iq4_xs": 0.50,                    # 4.0
    "IQ4_NL": 0.52, "iq4_nl": 0.52,
    "Q3_K_L": 0.46, "q3_K_L": 0.46,
    "Q3_K_M": 0.42, "q3_K_M": 0.42,                    # 3.4
    "Q3_K_S": 0.40, "q3_K_S": 0.40,
    "IQ3_M": 0.40, "iq3_m": 0.40,                      # 3.2
    "IQ3_S": 0.38, "iq3_s": 0.38,
    "IQ3_XXS": 0.35, "iq3_xxs": 0.35,                  # 2.8
    "Q2_K": 0.32, "q2_K": 0.32,                        # 2.6
    "IQ2_M": 0.30, "iq2_m": 0.30,                      # 2.4
    "IQ2_S": 0.28, "iq2_s": 0.28,
    "IQ2_XS": 0.26, "iq2_xs": 0.26,                    # 2.1
    "IQ2_XXS": 0.24, "iq2_xxs": 0.24,                  # 1.9
    "IQ1_M": 0.22, "iq1_m": 0.22,                      # 1.75
    "IQ1_S": 0.19, "iq1_s": 0.19,                      # 1.5 — extremo
    # vLLM/SGLang/TGI estilos
    "awq": 0.55,
    "gptq": 0.55,
    "fp8": 1.0,
    "bitsandbytes": 0.55,
    "eetq": 0.55,
    "none": 2.0,
}


KV_FACTOR: dict[str, float] = {
    # f16 baseline (2 bytes/valor)
    "f16": 1.0, "F16": 1.0, "fp16": 1.0, "auto": 1.0,
    "bf16": 1.0, "BF16": 1.0,
    # 1 byte/valor → 50% del tamaño
    "q8_0": 0.5, "Q8_0": 0.5,
    "fp8": 0.5, "fp8_e5m2": 0.5, "fp8_e4m3": 0.5,
    # 5 bits/valor (~62% en práctica con bloques)
    "q5_0": 0.34, "Q5_0": 0.34, "q5_1": 0.36, "Q5_1": 0.36,
    # 4 bits/valor (~25-28%)
    "q4_0": 0.25, "Q4_0": 0.25, "q4_1": 0.28, "Q4_1": 0.28,
    "iq4_nl": 0.27, "IQ4_NL": 0.27,
    # f32 (control/baseline doble)
    "f32": 2.0, "F32": 2.0,
}


# Niveles de compresión de KV-cache: K y V se cuantizan iguales por simplicidad
COMPRESSION_PRESETS: dict[str, dict] = {
    "quality": {
        "label": "Calidad",
        "kv_k": "f16", "kv_v": "f16",
        "desc": "Sin compresión KV. Máxima precisión, mayor uso de VRAM en contextos largos.",
    },
    "balanced": {
        "label": "Equilibrado",
        "kv_k": "q8_0", "kv_v": "q8_0",
        "desc": "KV q8_0: 50% menos memoria con pérdida de calidad mínima. Default recomendado.",
    },
    "compressed": {
        "label": "Comprimido",
        "kv_k": "q8_0", "kv_v": "iq4_nl",
        "desc": "K en q8_0 + V en iq4_nl (i-quant moderna): ~60% menos. Buena calidad para contextos largos.",
    },
    "aggressive": {
        "label": "Agresivo",
        "kv_k": "q4_0", "kv_v": "q4_0",
        "desc": "KV q4_0: 75% menos memoria. Permite contextos enormes pero penaliza calidad.",
    },
    "extreme": {
        "label": "Extremo (KV en RAM)",
        "kv_k": "q4_0", "kv_v": "q4_0",
        "nkvo": True,
        "desc": "q4_0 + KV completamente en RAM (--no-kv-offload). Libera VRAM al máximo, slow per-token.",
    },
}


# Cuantizaciones de mayor a menor calidad (orden estándar)
QUANT_QUALITY_ORDER = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"]

# Lista extendida incluyendo i-quants extremos para modelos enormes (>=70B)
QUANT_EXTREME_ORDER = [
    "Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS",
    "Q3_K_M", "IQ3_M", "Q2_K", "IQ2_M", "IQ2_XS", "IQ2_XXS",
    "IQ1_M", "IQ1_S",
]


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
    total = model_size + kv_overhead + 0.6

    # Caso especial MoE con --n-cpu-moe
    if (
        model.is_moe
        and opts.moe_offload
        and engine_id == "llamacpp"
        and hw.vram_gb > 0
    ):
        # Para MoE, lo que sí debe caber en VRAM es la "shared+gating" + atención + KV.
        # Estimación: ratio_active * model_size para shared parte + KV
        shared = (model.active_b / model.params_b) * model_size * 0.4 + 1.2
        # 0.4 porque dentro de active_b ~40% son params shared, resto experts activos
        if shared + kv_overhead <= hw.vram_gb:
            if total <= hw.vram_gb + hw.ram_gb * 0.8:
                return "moe"
            # Fits in VRAM (working set) pero modelo necesita disco
            return "disk"

    if total <= hw.vram_gb:
        return "ok"
    if hw.vram_gb > 0 and total <= hw.vram_gb + hw.ram_gb * 0.8:
        return "partial"
    if total <= hw.ram_gb * 0.8:
        return "cpu"
    # Disco fallback: si la "working set" cabe (tipo MoE shared+kv) o el modelo
    # < 4× capacidad combinada, mmap puede pagear desde disco con tps muy bajo.
    combined = hw.vram_gb + hw.ram_gb
    if model.is_moe and engine_id == "llamacpp":
        # Para MoE incluso sin moe_offload explícito, mmap permite usar disco
        shared = (model.active_b / model.params_b) * model_size * 0.4 + 1.2
        if shared + kv_overhead <= hw.vram_gb and model_size < combined * 3:
            return "disk"
    if model_size < combined * 1.5 and total < combined * 2:
        return "disk"
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
