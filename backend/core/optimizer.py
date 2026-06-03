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
from .models_catalog import Model, get_model, load_models

# Cuantizaciones por motor (de mayor a menor calidad)
ENGINE_QUANTS: dict[str, list[str]] = {
    "llamacpp": [
        "Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS",
        "Q3_K_M", "IQ3_M", "Q2_K", "IQ2_M", "IQ2_XS", "IQ2_XXS",
        "IQ1_M", "IQ1_S",
    ],
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
            if status in {"ok", "moe", "partial", "cpu", "disk"}:
                max_ctx = compat.compute_max_context(
                    model, snap, opts, engine_id=engine_id, is_api=False
                )
                total = (
                    compat.get_model_size_gb(model, quant)
                    + max_ctx * compat.get_kv_per_token_gb(model, kv)
                    + 0.6
                )
                # Calcular ngl óptimo para llama.cpp
                flags = _default_flags(engine_id, model, status, snap)
                if engine_id in ("llamacpp",):
                    ngl, mode = compute_optimal_ngl(
                        model, snap, quant, kv, max_ctx,
                        moe_offload=moe_candidate if status == "moe" else None,
                    )
                    flags["ngl"] = ngl
                    flags["ngl_mode"] = mode

                # MoE offload aplica también en "disk" (huge MoE paginan desde disco)
                moe_used = moe_candidate if status in {"moe", "disk"} and model.is_moe else None
                cfg = OptimalConfig(
                    engine=engine_id,
                    model_id=model_id,
                    feasible=True,
                    status=status,
                    quant=quant,
                    kv_cache=kv,
                    context_len=max_ctx,
                    moe_offload=moe_used,
                    flags=flags,
                    rationale=rationale + [
                        f"Elegida cuantización {quant} con KV {kv}: status={status}",
                        f"Contexto máximo automático: {max_ctx} tokens",
                        f"Memoria estimada total: {round(total, 2)} GB"
                        + (
                            f" (de los cuales ~{round(total - snap.vram_gb - snap.ram_gb, 1)}GB "
                            f"se paginarán desde disco)"
                            if status == "disk" and total > snap.vram_gb + snap.ram_gb
                            else ""
                        ),
                    ],
                    estimated_total_gb=round(total, 2),
                )
                # Preferimos status='ok' o 'moe' sobre 'partial' sobre 'cpu' sobre 'disk'
                STATUS_RANK = {"ok": 0, "moe": 1, "partial": 2, "cpu": 3, "disk": 4}
                if best is None or STATUS_RANK.get(status, 9) < STATUS_RANK.get(best.status, 9):
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


def _fit_status_kv(
    model: Model,
    hw: compat.HardwareSnapshot,
    quant: str,
    context_len: int,
    kv_factor: float,
    kv_in_ram: bool,
    engine_id: str,
) -> compat.CompatStatus:
    """Como compat.check_compat pero con un factor KV explícito (presets de compresión)
    y la opción kv_in_ram (--no-kv-offload): la KV va a RAM, no a VRAM.
    """
    model_size = compat.get_model_size_gb(model, quant)
    # KV exacta desde arquitectura si hay metadata; si no, heurística. × factor del preset.
    kv_per_tok_gb = compat.kv_per_token_mb_f16(model) * kv_factor / 1024.0
    kv_overhead = context_len * kv_per_tok_gb

    if kv_in_ram:
        vram_need = model_size + 0.6
        ram_extra = kv_overhead
    else:
        vram_need = model_size + kv_overhead + 0.6
        ram_extra = 0.0

    # MoE con offload: solo shared+gating+atención+KV deben caber en VRAM
    if model.is_moe and engine_id == "llamacpp" and hw.vram_gb > 0:
        shared = (model.active_b / model.params_b) * model_size * 0.4 + 1.2
        if shared + (0.0 if kv_in_ram else kv_overhead) <= hw.vram_gb:
            return "moe"

    if vram_need <= hw.vram_gb and ram_extra <= hw.ram_gb * 0.8:
        return "ok"
    if hw.vram_gb > 0 and vram_need <= hw.vram_gb + hw.ram_gb * 0.8 and ram_extra <= hw.ram_gb * 0.8:
        return "partial"
    if vram_need + ram_extra <= hw.ram_gb * 0.8:
        return "cpu"
    return "fail"


def most_powerful_per_compression(
    hw: HardwareInfo | None = None,
    engine_id: str = "llamacpp",
    context_len: int = 8192,
) -> list[dict[str, Any]]:
    """Para cada preset de compresión KV, el modelo descargable más potente (más params)
    que corre 100% en GPU a `context_len`, con la mejor cuantización posible.

    Muestra el beneficio real de comprimir: liberar VRAM permite cargar modelos más grandes.
    """
    hw = hw or detect_hardware()
    snap = compat.HardwareSnapshot(vram_gb=hw.primary_vram_gb, ram_gb=hw.ram_gb)
    # Piso de calidad: comparamos "el más grande que cabe a calidad usable" (≥Q4_K_M).
    # Sin piso, el más potente sería siempre un modelo enorme a IQ1_S (1.5-bit, inservible).
    quants = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M"]
    # Solo modelos con fuente GGUF descargable (lo que llama.cpp arranca de un click)
    models = sorted(
        (m for m in load_models() if m.hf_gguf),
        key=lambda m: m.params_b,
        reverse=True,
    )

    out: list[dict[str, Any]] = []
    for pid, preset in compat.COMPRESSION_PRESETS.items():
        kv_f = compat.preset_kv_factor(pid)
        in_ram = bool(preset.get("nkvo"))
        top_ok = None       # más potente 100% en VRAM (rápido)
        top_runnable = None  # más potente ejecutable (incluye MoE offload / GPU+CPU)
        for m in models:  # de más a menos potente
            for q in quants:  # de mayor a menor calidad
                st = _fit_status_kv(m, snap, q, context_len, kv_f, in_ram, engine_id)
                if st in ("ok", "moe", "partial"):
                    if top_runnable is None:
                        top_runnable = _rec_entry(m, q, st, kv_f, context_len, snap, in_ram)
                    if st == "ok" and top_ok is None:
                        top_ok = _rec_entry(m, q, "ok", kv_f, context_len, snap, in_ram)
                    break
            if top_ok and top_runnable:
                break
        out.append({
            "preset": pid,
            "label": preset["label"],
            "kv_k": preset["kv_k"],
            "kv_v": preset["kv_v"],
            "kv_in_ram": in_ram,
            "kv_factor": round(kv_f, 3),
            "desc": preset["desc"],
            "top_full_gpu": top_ok,
            "top_runnable": top_runnable,
        })
    return out


def _rec_entry(model, quant, status, kv_f, context_len, snap, in_ram) -> dict[str, Any]:
    size = compat.get_model_size_gb(model, quant)
    kv_per_tok_gb = compat.kv_per_token_mb_f16(model) * kv_f / 1024.0
    kv_gb = context_len * kv_per_tok_gb
    return {
        "id": model.id,
        "name": model.name,
        "params_b": model.params_b,
        "is_moe": model.is_moe,
        "quant": quant,
        "status": status,
        "model_size_gb": round(size, 2),
        "kv_gb": round(kv_gb, 2),
        "context_len": context_len,
    }


def _estimate_moe_offload(model: Model, hw: compat.HardwareSnapshot) -> int | None:
    """Estima un valor sensato de --n-cpu-moe.

    Heurística: descargamos a CPU las suficientes capas MoE para que las partes
    "shared" + KV quepan en VRAM. Usa model.n_layer real cuando está disponible.
    """
    if hw.vram_gb <= 0 or model.params_b <= 0:
        return None
    n_layers = model.n_layer or 32
    base_size = compat.get_model_size_gb(model, "Q4_K_M")
    if base_size <= hw.vram_gb:
        return None
    # Cuántas capas MoE deben ir a CPU para que el resto quepa
    excess_ratio = max(0.0, (base_size - hw.vram_gb * 0.85) / base_size)
    n_offload = int(excess_ratio * n_layers)
    # Al menos 1, máximo n_layer (todos los expertos a CPU)
    return max(1, min(n_layers, n_offload))


def _gpu_mem_fraction(vram_total_gb: float, headroom_gb: float = 1.0) -> float:
    """Fracción de VRAM a reservar dejando margen. vLLM/SGLang pre-asignan
    `fraccion * total` y fallan si la GPU no está vacía; planificar con 0.9
    asume GPU vacía. Reservamos `headroom_gb` (el runtime afina luego con la
    VRAM libre real). 0.9 de respaldo si no se detecta VRAM."""
    if vram_total_gb <= 0:
        return 0.9
    return round(max(0.30, min(0.92, (vram_total_gb - headroom_gb) / vram_total_gb)), 2)


def _default_flags(
    engine_id: str, model: Model, status: str, snap: "compat.HardwareSnapshot | None" = None
) -> dict[str, Any]:
    vram = snap.vram_gb if snap else 0.0
    if engine_id == "llamacpp":
        return {
            "flashAttn": True,
            "mlock": status == "ok",
            "noMmap": status == "ok",
            "cacheReuse": 256,
        }
    if engine_id == "ollama":
        return {"flashAttn": True}
    if engine_id == "vllm":
        return {"prefixCaching": True, "gpuMemUtil": _gpu_mem_fraction(vram)}
    if engine_id == "sglang":
        return {
            "chunkedPrefill": 8192,
            "torchCompile": False,
            "memFraction": _gpu_mem_fraction(vram),
        }
    if engine_id == "tgi":
        return {}
    return {}


def compute_optimal_ngl(
    model: Model,
    hw: compat.HardwareSnapshot,
    quant: str,
    kv_cache: str,
    context_len: int,
    moe_offload: int | None = None,
) -> tuple[int, str]:
    """Calcula cuántas capas (de las n_layer del modelo) ofrecer a GPU.

    Devuelve (ngl, mode) donde mode ∈ {"all", "partial", "moe"}.
    Para "all": modelo completo en VRAM → ngl=999.
    Para "partial": modelo no cabe; calculamos cuántas capas caben.
    Para "moe": el offload por --n-cpu-moe ya manejará reparto, ngl=999.
    """
    n_layer = model.n_layer or 32  # fallback razonable
    model_size = compat.get_model_size_gb(model, quant)
    kv_overhead = context_len * compat.get_kv_per_token_gb(model, kv_cache)
    overhead = 0.6  # context, scratch, etc.

    # MoE con --n-cpu-moe: la GPU lleva gating + atención (poca cosa), el offload manejará el resto
    if model.is_moe and moe_offload and moe_offload > 0:
        return 999, "moe"

    # ¿Cabe entero?
    total = model_size + kv_overhead + overhead
    if total <= hw.vram_gb:
        return 999, "all"

    # Partial: cuántas capas caben en VRAM disponible (tras KV + overhead)
    # KV cache se reparte por capas igual que los pesos → ambos escalan con ngl
    # Aproximación: avail_for_layers = vram - overhead, size_per_layer_with_kv = (model_size + kv_overhead) / n_layer
    avail = hw.vram_gb - overhead - 0.3  # 0.3 GB para CUDA context, kernels
    if avail <= 0.5:
        return 0, "partial"  # nada cabe en GPU
    size_per_layer = (model_size + kv_overhead) / n_layer
    if size_per_layer <= 0:
        return 999, "all"
    ngl = int(avail / size_per_layer)
    ngl = max(0, min(ngl, n_layer - 1))  # nunca todas (eso sería "all")
    return ngl, "partial"


def plan_llamacpp_run(
    model: Model,
    hw: compat.HardwareSnapshot,
    *,
    quant: str,
    kv_k: str = "f16",
    kv_v: str = "f16",
    kv_in_ram: bool = False,
    moe_offload: int | None = None,
) -> tuple[int, int, str]:
    """Plan de arranque para los parámetros EXACTOS que se van a correr.

    Devuelve (context_len, ngl, ngl_mode) calculados para el `quant` real y la KV
    efectiva (K y V pueden diferir → factor medio), incluyendo `--no-kv-offload`
    (`kv_in_ram`: la KV va a RAM, así que la limita la RAM y libera VRAM). Corrige el
    bug de dimensionar el contexto/ngl para el quant que el optimizer *habría* elegido
    en vez del que el usuario ejecuta (causaba OOM y desaprovechaba la compresión).
    """
    model_size = compat.get_model_size_gb(model, quant)
    kv_factor = (compat.KV_FACTOR.get(kv_k, 1.0) + compat.KV_FACTOR.get(kv_v, 1.0)) / 2.0
    kv_per_tok_gb = compat.kv_per_token_mb_f16(model) * kv_factor / 1024.0
    overhead = 0.6

    # VRAM que ocupan los pesos en GPU (con MoE offload solo va shared+gating+atención)
    if model.is_moe and moe_offload and moe_offload > 0:
        weights_vram = (model.active_b / model.params_b) * model_size + 1.2
    else:
        weights_vram = model_size

    if kv_in_ram:
        # --no-kv-offload: la KV vive en RAM → el contexto lo limita la RAM, no la VRAM.
        avail_for_kv = hw.ram_gb * 0.6
    elif weights_vram <= hw.vram_gb:
        avail_for_kv = hw.vram_gb - weights_vram - overhead
    else:
        # Los pesos no caben enteros: offload parcial; la KV comparte lo que quede.
        avail_for_kv = max(0.0, (hw.vram_gb + hw.ram_gb * 0.7) - model_size - overhead - 0.2)

    if avail_for_kv <= 0.3 or kv_per_tok_gb <= 0:
        max_ctx = 2048
    else:
        max_ctx = max(2048, min((int(avail_for_kv / kv_per_tok_gb) // 1024) * 1024, model.max_ctx))

    # ngl para ESTE quant. Con KV en RAM, la KV no cuenta en VRAM (ctx=0 para el cálculo).
    ngl_ctx = 0 if kv_in_ram else max_ctx
    ngl, mode = compute_optimal_ngl(model, hw, quant, kv_k, ngl_ctx, moe_offload=moe_offload)
    return max_ctx, ngl, mode


def benefits_summary(cfg: "OptimalConfig", model: Model, hw: compat.HardwareSnapshot) -> list[str]:
    """Lista de las técnicas de optimización aplicadas con su beneficio cuantificado."""
    out: list[str] = []
    base_fp16 = model.size_base_gb
    if cfg.quant:
        size_q = compat.get_model_size_gb(model, cfg.quant)
        saved = base_fp16 - size_q
        pct = saved / base_fp16 * 100 if base_fp16 else 0
        out.append(
            f"Cuantización {cfg.quant}: modelo de {base_fp16:.1f}GB → {size_q:.1f}GB "
            f"({pct:.0f}% menos)"
        )
    if cfg.kv_cache and cfg.kv_cache != "f16":
        kv_factor = {"q8_0": 0.5, "q4_0": 0.25, "fp8": 0.5, "fp8_e5m2": 0.5}.get(cfg.kv_cache, 1.0)
        out.append(
            f"KV-cache {cfg.kv_cache}: {(1 - kv_factor) * 100:.0f}% menos memoria de contexto"
        )
    if cfg.moe_offload:
        n_layer = model.n_layer or 32
        out.append(
            f"MoE offload --n-cpu-moe={cfg.moe_offload}: {cfg.moe_offload}/{n_layer} capas expert "
            f"a CPU. Solo el gating + atención usan GPU. Permite correr {model.params_b}B totales "
            f"con menos VRAM (técnica del video Codacus)"
        )
    if cfg.flags.get("flashAttn"):
        out.append("Flash Attention (-fa on): atención con kernels fusionados, ~30% menos memoria")
    ngl = cfg.flags.get("ngl")
    if ngl is not None and ngl != 999:
        n_layer = model.n_layer or 32
        out.append(
            f"Layer offload parcial (-ngl {ngl}): {ngl}/{n_layer} capas en GPU, "
            f"resto en CPU. Tps bajos pero hace posible correr el modelo"
        )
    if cfg.flags.get("mlock"):
        out.append("--mlock: evita que el SO mueva el modelo a swap")
    if cfg.flags.get("noMmap"):
        out.append("--no-mmap: carga directa a memoria, evita doble copia mapeada")
    if cfg.flags.get("cacheReuse"):
        out.append(f"--cache-reuse {cfg.flags['cacheReuse']}: reusa KV de prompts similares")
    if cfg.flags.get("prefixCaching"):
        out.append("Prefix caching: vLLM reusa el prompt entre requests")
    if cfg.flags.get("chunkedPrefill"):
        out.append(f"Chunked prefill ({cfg.flags['chunkedPrefill']}): SGLang procesa el prompt en chunks")
    return out
