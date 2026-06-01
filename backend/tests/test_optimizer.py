"""Tests de core/optimizer.py: config óptima y modelos por compresión (hardware sintético)."""
from core import optimizer
from core.hardware import CPUInfo, GPUInfo, HardwareInfo


def _hw(vram_gb: float, ram_gb: float = 32.0) -> HardwareInfo:
    return HardwareInfo(
        os="Test", os_version="0", ram_gb=ram_gb, ram_available_gb=ram_gb * 0.8,
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
    small = optimizer.most_powerful_per_compression(hw=_hw(8.0), context_len=4096)[0]["top_full_gpu"]
    big = optimizer.most_powerful_per_compression(hw=_hw(8.0), context_len=32768)[0]["top_full_gpu"]
    if small and big:
        assert big["params_b"] <= small["params_b"]
