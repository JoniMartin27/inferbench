"""Tests de core/compat.py: tamaños, KV, compatibilidad y contexto máximo."""
from core import compat
from core.models_catalog import Model


def _model(**kw) -> Model:
    base = dict(
        id="t", name="T", family="llama", params_b=7.0, active_b=7.0,
        is_moe=False, size_base_gb=14.0, max_ctx=8192,
    )
    base.update(kw)
    return Model(**base)


def test_model_size_scales_with_quant():
    m = _model()
    q8 = compat.get_model_size_gb(m, "Q8_0")
    q4 = compat.get_model_size_gb(m, "Q4_K_M")
    assert q8 > q4 > 0
    # Q4_K_M ~0.55 del FP16 (size_base/2 * 0.55)
    assert abs(q4 - m.size_base_gb / 2 * 0.55) < 1e-6


def test_unknown_quant_falls_back():
    m = _model()
    assert compat.get_model_size_gb(m, "NOPE") == compat.get_model_size_gb(m, "Q4_K_M")


def test_kv_per_token_compresses():
    m = _model()
    assert compat.get_kv_per_token_mb(m, "f16") > compat.get_kv_per_token_mb(m, "q8_0")
    assert compat.get_kv_per_token_mb(m, "q8_0") > compat.get_kv_per_token_mb(m, "q4_0")


def test_kv_exact_from_arch_dims():
    # KV f16 = 2(K+V) · n_layer · n_head_kv · head_dim · 2 bytes / 1MiB
    # Llama-3-8B: 32 capas, 8 KV heads, head_dim 128 → 0.125 MB/token (→ 1 GB @ 8192 ctx)
    m = _model(n_layer=32, n_head_kv=8, head_dim=128)
    expected = 4 * 32 * 8 * 128 / (1024 * 1024)
    assert abs(compat.kv_per_token_mb_f16(m) - expected) < 1e-9
    assert abs(compat.kv_per_token_mb_f16(m) - 0.125) < 1e-6
    # No depende de params_b cuando hay metadata
    assert compat.kv_per_token_mb_f16(_model(params_b=70.0, n_layer=32, n_head_kv=8, head_dim=128)) == \
        compat.kv_per_token_mb_f16(m)


def test_kv_exact_captures_gqa():
    # Misma forma salvo n_head_kv: GQA (8 KV heads) usa 4× menos KV que MHA (32).
    mha = _model(n_layer=32, n_head_kv=32, head_dim=128)
    gqa = _model(n_layer=32, n_head_kv=8, head_dim=128)
    assert compat.kv_per_token_mb_f16(mha) == 4 * compat.kv_per_token_mb_f16(gqa)


def test_kv_falls_back_to_heuristic_without_dims():
    # Sin n_head_kv/head_dim → heurística basada en params (comportamiento previo).
    m = _model(params_b=7.0)  # sin dims de arquitectura
    assert m.n_head_kv is None
    assert abs(compat.kv_per_token_mb_f16(m) - 0.5 * (7.0 / 7.0) ** 0.7) < 1e-9


def test_check_compat_fits_on_big_gpu():
    hw = compat.HardwareSnapshot(vram_gb=24.0, ram_gb=64.0)
    opts = compat.EngineOpts(quant="Q4_K_M", kv_cache="q8_0", context_len=4096)
    st = compat.check_compat(_model(params_b=7.0, size_base_gb=14.0), hw, opts,
                             engine_id="llamacpp", is_api=False)
    assert st == "ok"


def test_check_compat_huge_model_tiny_gpu_not_ok():
    hw = compat.HardwareSnapshot(vram_gb=4.0, ram_gb=8.0)
    opts = compat.EngineOpts(quant="Q4_K_M", kv_cache="q8_0", context_len=4096)
    st = compat.check_compat(_model(params_b=70.0, size_base_gb=140.0), hw, opts,
                             engine_id="llamacpp", is_api=False)
    assert st in {"partial", "cpu", "disk", "fail"}
    assert st != "ok"


def test_api_engine_is_api():
    hw = compat.HardwareSnapshot(vram_gb=0.0, ram_gb=8.0)
    opts = compat.EngineOpts()
    assert compat.check_compat(_model(), hw, opts, engine_id="openai", is_api=True) == "api"


def test_max_context_bounds():
    hw = compat.HardwareSnapshot(vram_gb=24.0, ram_gb=64.0)
    opts = compat.EngineOpts(quant="Q4_K_M", kv_cache="q8_0", context_len=4096)
    m = _model(max_ctx=8192)
    ctx = compat.compute_max_context(m, hw, opts, engine_id="llamacpp", is_api=False)
    assert 2048 <= ctx <= m.max_ctx


def test_preset_kv_factor_order():
    assert compat.preset_kv_factor("quality") == 1.0
    assert compat.preset_kv_factor("balanced") == 0.5
    assert compat.preset_kv_factor("aggressive") == 0.25
    # comprimido (q8_0 + iq4_nl) entre balanced y aggressive
    comp = compat.preset_kv_factor("compressed")
    assert 0.25 < comp < 0.5
