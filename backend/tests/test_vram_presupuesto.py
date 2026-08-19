"""El plan de llama.cpp nativo se dimensiona con la VRAM LIBRE, no con la total.

Regresión MEDIDA el 2026-08-19 en una RTX 3070 de 8 GB con el escritorio de Windows
ocupando 2,4 GB (5,7 GB libres): el plan de `llama-3.1-8b` Q4_K_M salió ctx 23552 con las
33 capas en GPU — 4,4 GB de pesos + 2,9 GB de KV = 7,3 GB — y `llama-server` murió con
`CUDA error: out of memory`. El benchmark entero se perdió. Los motores Docker ya se
planificaban contra la VRAM libre; el nativo, no.
"""

from __future__ import annotations

import asyncio

import pytest
from core import benchmark, compat, hardware, native_runtime, optimizer
from core.models_catalog import get_model

# La tarjeta del incidente: 8 GB en total, 5,7 GB realmente libres.
_TARJETA = compat.HardwareSnapshot(vram_gb=8.0, ram_gb=32.0)
_LIBRE_REAL = 5.7


def _huella_gpu(model, quant: str, ctx: int, kv: str) -> float:
    """GB de VRAM que ocupa el plan si TODAS las capas van a GPU (pesos + KV + overhead)."""
    return (
        compat.get_model_size_gb(model, quant) + ctx * compat.get_kv_per_token_gb(model, kv) + 0.6
    )


# --- native_vram_budget_gb ------------------------------------------------------------


def test_presupuesto_parte_de_la_libre_menos_un_margen(monkeypatch):
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (5.7, 8.0))
    monkeypatch.delenv("INFERBENCH_NATIVE_VRAM_MARGIN_GB", raising=False)
    assert hardware.native_vram_budget_gb() == pytest.approx(4.9, abs=0.01)


def test_presupuesto_no_resta_dos_veces_la_reserva_de_display(monkeypatch):
    """`free` ya descuenta lo que gasta el escritorio: restarle además la reserva de
    display (2 GB en esta tarjeta) dejaría 2,9 GB y ni los pesos cabrían."""
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (5.7, 8.0))
    monkeypatch.delenv("INFERBENCH_NATIVE_VRAM_MARGIN_GB", raising=False)
    assert hardware.native_vram_budget_gb() > 5.7 - hardware.gpu_display_reserve_gb(8.0)


def test_presupuesto_configurable_por_env(monkeypatch):
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (5.7, 8.0))
    monkeypatch.setenv("INFERBENCH_NATIVE_VRAM_MARGIN_GB", "2")
    assert hardware.native_vram_budget_gb() == pytest.approx(3.7, abs=0.01)


def test_presupuesto_cero_sin_gpu_detectable(monkeypatch):
    """Sin NVML no hay medida: 0.0 significa "planifica como siempre", no "no cabe nada"."""
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (0.0, 0.0))
    assert hardware.native_vram_budget_gb() == 0.0


def test_presupuesto_nunca_negativo(monkeypatch):
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (0.2, 8.0))
    monkeypatch.delenv("INFERBENCH_NATIVE_VRAM_MARGIN_GB", raising=False)
    assert hardware.native_vram_budget_gb() == 0.0


# --- el plan respeta el presupuesto ---------------------------------------------------


def test_el_plan_de_siempre_se_pasaba_de_la_vram_libre():
    """Ata la regresión: sin presupuesto, el plan del incidente NO cabe en lo libre."""
    m = get_model("llama-3.1-8b")
    ctx, ngl, mode = optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M")
    assert mode == "all" and ngl == 999
    assert _huella_gpu(m, "Q4_K_M", ctx, "f16") > _LIBRE_REAL


def test_con_presupuesto_el_plan_cabe_en_lo_libre():
    m = get_model("llama-3.1-8b")
    presupuesto = 4.9  # 5,7 libres - 0,8 de margen
    ctx, ngl, mode = optimizer.plan_llamacpp_run(
        m, _TARJETA, quant="Q4_K_M", vram_budget_gb=presupuesto
    )
    if mode == "all":
        assert _huella_gpu(m, "Q4_K_M", ctx, "f16") <= presupuesto
    else:
        # Offload parcial: solo una parte de las capas va a GPU, así que el plan ya no
        # promete meter el modelo entero en una VRAM que no lo admite.
        assert ngl < (m.n_layer or 32)


def test_el_presupuesto_recorta_el_contexto():
    m = get_model("llama-3.1-8b")
    ctx_total, _, _ = optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M")
    ctx_real, _, _ = optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M", vram_budget_gb=4.9)
    assert ctx_real < ctx_total


def test_presupuesto_ausente_no_cambia_nada():
    """Quien no tenga NVML debe seguir viendo EXACTAMENTE el plan de antes."""
    m = get_model("llama-3.1-8b")
    base = optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M")
    for sin_medida in (None, 0.0):
        assert (
            optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M", vram_budget_gb=sin_medida)
            == base
        )


def test_presupuesto_mayor_que_la_tarjeta_no_infla_el_plan():
    """Un presupuesto absurdo (GPU vacía y NVML mintiendo) nunca supera la VRAM real."""
    m = get_model("llama-3.1-8b")
    base = optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M")
    assert optimizer.plan_llamacpp_run(m, _TARJETA, quant="Q4_K_M", vram_budget_gb=999.0) == base


def test_compute_optimal_ngl_reparte_capas_con_el_presupuesto():
    m = get_model("llama-3.1-8b")
    ngl_total, modo_total = optimizer.compute_optimal_ngl(m, _TARJETA, "Q4_K_M", "f16", 8192)
    ngl_real, modo_real = optimizer.compute_optimal_ngl(
        m, _TARJETA, "Q4_K_M", "f16", 8192, vram_budget_gb=3.0
    )
    assert modo_total == "all"
    assert modo_real == "partial" and ngl_real < (m.n_layer or 32)


# --- el arranque no espera 120 s a un motor que ya está muerto ------------------------


class _Estado:
    def __init__(self, state: str) -> None:
        self.state = state


def test_arranque_aborta_cuando_el_motor_ha_muerto(monkeypatch):
    monkeypatch.setattr(native_runtime, "status", lambda _e: _Estado("exited"))
    monkeypatch.setattr(
        native_runtime,
        "logs",
        lambda _e, tail=200: (
            "llama_kv_cache: CUDA0 KV buffer size = 2944.00 MiB\n"
            "CUDA error: out of memory\n"
            "  current device: 0, in function ggml_backend_cuda_buffer_clear\n"
        ),
    )
    with pytest.raises(RuntimeError) as e:
        asyncio.run(
            benchmark._wait_engine_ready("http://127.0.0.1:9", timeout=30.0, engine_id="llamacpp")
        )
    # El mensaje tiene que llevar la CAUSA, no "All connection attempts failed".
    assert "out of memory" in str(e.value).lower()
    assert "died while starting up" in str(e.value)


def test_arranque_no_aborta_mientras_el_motor_siga_vivo(monkeypatch):
    """Si el proceso vive, se espera al timeout como siempre (arranque lento ≠ muerto)."""
    monkeypatch.setattr(native_runtime, "status", lambda _e: _Estado("running"))
    with pytest.raises(RuntimeError) as e:
        asyncio.run(
            benchmark._wait_engine_ready("http://127.0.0.1:9", timeout=1.5, engine_id="llamacpp")
        )
    assert "Engine not ready after" in str(e.value)


def test_sin_engine_id_no_se_mira_el_proceso(monkeypatch):
    """El camino de Docker no pasa por native_runtime: no debe consultarlo siquiera."""

    def _explota(_e):  # pragma: no cover - debe no llamarse
        raise AssertionError("no se debe consultar native_runtime sin engine_id")

    monkeypatch.setattr(native_runtime, "status", _explota)
    with pytest.raises(RuntimeError, match="Engine not ready after"):
        asyncio.run(benchmark._wait_engine_ready("http://127.0.0.1:9", timeout=1.5))


def test_causa_de_muerte_ignora_el_ruido_del_log(monkeypatch):
    monkeypatch.setattr(
        native_runtime,
        "logs",
        lambda _e, tail=200: "load_tensors: offloaded 33/33 layers to GPU\nllama_context: n_ctx = 23552\n",
    )
    assert benchmark._causa_de_muerte("llamacpp") == ""


def test_causa_de_muerte_aguanta_un_log_ilegible(monkeypatch):
    def _revienta(_e, tail=200):
        raise OSError("log bloqueado por otro proceso")

    monkeypatch.setattr(native_runtime, "logs", _revienta)
    assert benchmark._causa_de_muerte("llamacpp") == ""
