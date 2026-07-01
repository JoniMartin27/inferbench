"""Tests de core/optimizer.py: config óptima y modelos por compresión (hardware sintético)."""

from core import compat, optimizer
from core.hardware import CPUInfo, GPUInfo, HardwareInfo
from core.models_catalog import get_model


def _hw(vram_gb: float, ram_gb: float = 32.0) -> HardwareInfo:
    return HardwareInfo(
        os="Test",
        os_version="0",
        ram_gb=ram_gb,
        ram_available_gb=ram_gb * 0.8,
        cpu=CPUInfo(name="Test CPU", arch="x86_64", physical_cores=8, logical_cores=16),
        gpus=[GPUInfo(vendor="nvidia", name="Test GPU", vram_gb=vram_gb)] if vram_gb else [],
        primary_vram_gb=vram_gb,
    )


def test_optimal_config_feasible_small_model_big_gpu():
    cfg = optimizer.get_optimal_config("llamacpp", "llama-3.2-1b", hw=_hw(24.0))
    assert cfg.feasible
    assert cfg.status in {"ok", "moe", "partial", "cpu", "disk"}
    assert cfg.quant
    assert cfg.kv_cache
    assert cfg.context_len >= 2048


def test_optimal_config_unknown_model():
    cfg = optimizer.get_optimal_config("llamacpp", "no-existe", hw=_hw(24.0))
    assert not cfg.feasible
    assert cfg.status == "fail"


def test_optimal_config_api_engine():
    cfg = optimizer.get_optimal_config("openai", "llama-3.2-1b", hw=_hw(0.0))
    assert cfg.feasible
    assert cfg.status == "api"


def test_optimal_config_moe_offload_scales_with_chosen_quant():
    # Regresión: --n-cpu-moe se estimaba UNA vez con el quant por defecto (Q4_K_M) y
    # se reusaba para todos los quants probados en el bucle (Q8_0, Q6_K, ...). Un
    # Q8_0 ocupa ~2x un Q4_K_M y necesita más capas offloaded a CPU; reusar el valor
    # de Q4_K_M para un Q8_0 subestima el offload necesario -> riesgo de OOM real.
    m = get_model("qwen3-30b-a3b")
    assert m is not None and m.is_moe
    hw = _hw(8.0)
    snap = compat.HardwareSnapshot(vram_gb=hw.primary_vram_gb, ram_gb=hw.ram_gb)

    off_q4 = optimizer._estimate_moe_offload(m, snap, "Q4_K_M")
    off_q8 = optimizer._estimate_moe_offload(m, snap, "Q8_0")
    assert off_q8 > off_q4  # Q8_0 exige offloadear más capas que Q4_K_M

    # Con 8GB de VRAM el optimizer elige Q8_0 (mayor calidad que cabe) -> el offload
    # usado DEBE ser el estimado para Q8_0, no el de Q4_K_M reusado del cálculo previo.
    cfg = optimizer.get_optimal_config("llamacpp", "qwen3-30b-a3b", hw=hw)
    assert cfg.feasible
    assert cfg.quant == "Q8_0"
    assert cfg.moe_offload == off_q8
    assert cfg.moe_offload != off_q4


def test_by_compression_structure_and_monotonicity():
    rows = optimizer.most_powerful_per_compression(hw=_hw(8.0), context_len=8192)
    assert len(rows) == 5
    presets = [r["preset"] for r in rows]
    assert presets == ["quality", "balanced", "compressed", "aggressive", "extreme"]
    for r in rows:
        assert {"label", "kv_factor", "top_full_gpu", "top_runnable"} <= set(r)
    # Comprimir libera VRAM: el modelo 100% GPU del modo agresivo no es más pequeño
    # que el del modo calidad (a igualdad de contexto).
    q = rows[0]["top_full_gpu"]
    aggr = rows[3]["top_full_gpu"]
    if q and aggr:
        assert aggr["params_b"] >= q["params_b"]


def test_by_compression_more_context_shrinks_or_equal_top():
    """A más contexto, el top 100% GPU del modo Calidad (KV f16) no crece."""
    small = optimizer.most_powerful_per_compression(hw=_hw(8.0), context_len=4096)[0][
        "top_full_gpu"
    ]
    big = optimizer.most_powerful_per_compression(hw=_hw(8.0), context_len=32768)[0]["top_full_gpu"]
    if small and big:
        assert big["params_b"] <= small["params_b"]


# ---- plan_llamacpp_run: ctx/ngl para los parámetros REALES del run ----

_SNAP = compat.HardwareSnapshot(vram_gb=8.0, ram_gb=32.0)


def test_plan_dimensiona_para_el_quant_real():
    # Un quant más grande (Q8_0) deja MENOS capas en GPU que uno pequeño (Q4_K_M).
    m = get_model("llama-3-8b")
    _, ngl_q4, _ = optimizer.plan_llamacpp_run(m, _SNAP, quant="Q4_K_M", kv_k="q8_0", kv_v="q8_0")
    _, ngl_q8, _ = optimizer.plan_llamacpp_run(m, _SNAP, quant="Q8_0", kv_k="q8_0", kv_v="q8_0")
    assert ngl_q8 <= ngl_q4


def test_plan_compresion_kv_da_mas_contexto():
    # Comprimir la KV (q4_0 vs f16) permite MÁS contexto a igualdad de quant.
    m = get_model("llama-3-8b")
    ctx_f16, _, _ = optimizer.plan_llamacpp_run(m, _SNAP, quant="Q4_K_M", kv_k="f16", kv_v="f16")
    ctx_q4, _, _ = optimizer.plan_llamacpp_run(m, _SNAP, quant="Q4_K_M", kv_k="q4_0", kv_v="q4_0")
    assert ctx_q4 >= ctx_f16


def test_plan_kv_en_ram_da_mas_contexto():
    # --no-kv-offload mueve la KV a RAM → libera VRAM → más contexto que con KV en VRAM.
    m = get_model("llama-3-8b")
    ctx_vram, _, _ = optimizer.plan_llamacpp_run(m, _SNAP, quant="Q6_K", kv_k="q4_0", kv_v="q4_0")
    ctx_ram, _, _ = optimizer.plan_llamacpp_run(
        m, _SNAP, quant="Q6_K", kv_k="q4_0", kv_v="q4_0", kv_in_ram=True
    )
    assert ctx_ram >= ctx_vram


def test_plan_contexto_dentro_de_limites():
    m = get_model("llama-3.2-1b")
    ctx, ngl, mode = optimizer.plan_llamacpp_run(m, _SNAP, quant="Q4_K_M", kv_k="f16", kv_v="f16")
    assert ctx >= 2048 and ctx <= m.max_ctx
    assert ngl >= 0 and mode in {"all", "partial", "moe"}
