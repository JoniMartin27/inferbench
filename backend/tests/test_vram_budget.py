"""Tests del rechazo temprano por VRAM al arrancar un motor Docker.

El fallo que fijan: el guard de `engines/base.py::_start_docker` es un SUELO ABSOLUTO
(`safe_gpu_fraction() < 0.15`) — pregunta "¿queda algo de VRAM?", no "¿cabe ESTE modelo?".
Medido en real sobre una RTX 3070 con el escritorio ocupando 4,1 GB: la fracción segura
daba 0.22 (1,76 GB), el suelo dejaba pasar, el contenedor de vLLM arrancaba y el runner
**esperaba 600 s** antes de rendirse con "Engine not ready". Diez minutos para un fallo
que se conocía desde el segundo cero.
"""

import pytest

from core import benchmark as bm
from core.models_catalog import get_model


@pytest.fixture
def gpu(monkeypatch):
    """Permite fijar (libre, total) y la fracción segura para el test."""

    def _set(libre_gb, total_gb, fraccion):
        monkeypatch.setattr(bm, "gpu_memory_gb", lambda: (libre_gb, total_gb))
        monkeypatch.setattr(bm, "safe_gpu_fraction", lambda: fraccion)

    return _set


@pytest.fixture
def modelo():
    m = get_model("qwen2.5-0.5b")
    assert m is not None, "el catálogo debe traer qwen2.5-0.5b"
    return m


def test_rechaza_el_caso_real_que_esperaba_600s(gpu, modelo):
    """1,76 GB de presupuesto para un modelo de 1,0 GB de pesos: no cabe con el overhead."""
    gpu(3.6, 8.0, 0.22)
    with pytest.raises(RuntimeError) as e:
        bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")
    msg = str(e.value)
    assert "does not fit" in msg
    assert "vllm" in msg, "el mensaje debe decir qué motor"
    assert "usable" in msg, "hay que decir cuánta VRAM hay disponible"


def test_deja_pasar_cuando_de_verdad_cabe(gpu, modelo):
    """Con la GPU libre, el mismo modelo debe arrancar sin estorbo."""
    gpu(7.5, 8.0, 0.68)  # 5,4 GB de presupuesto para 1,0 GB de pesos + 1,0 de margen
    bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")


def test_el_suelo_viejo_no_habria_bastado(gpu, modelo):
    """La fracción del caso real (0.22) supera el suelo de 0.15: por eso hacía falta esto."""
    assert 0.22 > 0.15
    gpu(3.6, 8.0, 0.22)
    with pytest.raises(RuntimeError):
        bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")


def test_cuenta_el_margen_de_contexto_cuda_no_solo_los_pesos(gpu, modelo, monkeypatch):
    """Un presupuesto que cubre los pesos justos pero no el contexto debe rechazarse.

    Es exactamente el caso medido: 1,0 GB de pesos con 1,6-1,8 GB de presupuesto se
    quedaba colgado hasta el timeout.
    """
    monkeypatch.delenv("INFERBENCH_DOCKER_VRAM_OVERHEAD_GB", raising=False)
    gpu(8.0, 8.0, 0.15)  # 1,2 GB: cubre el peso (1,0) pero no el margen
    with pytest.raises(RuntimeError):
        bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")


def test_el_margen_es_configurable(gpu, modelo, monkeypatch):
    gpu(8.0, 8.0, 0.15)  # 1,2 GB de presupuesto
    monkeypatch.setenv("INFERBENCH_DOCKER_VRAM_OVERHEAD_GB", "0.1")
    bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")  # 1,0 + 0,1 = 1,1 <= 1,2


def test_un_margen_ilegible_cae_al_valor_por_defecto(gpu, modelo, monkeypatch):
    gpu(8.0, 8.0, 0.15)
    monkeypatch.setenv("INFERBENCH_DOCKER_VRAM_OVERHEAD_GB", "no-es-un-numero")
    with pytest.raises(RuntimeError):
        bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")


def test_sin_gpu_nvidia_no_se_bloquea_nada(gpu, modelo):
    """Sin GPU detectable no imponemos tope: que falle el motor por su cuenta."""
    gpu(0.0, 0.0, 0.85)
    bm._check_docker_vram_budget(modelo, "Q4_K_M", "vllm")


def test_un_quant_que_el_motor_entiende_reduce_lo_que_pide(gpu, monkeypatch):
    """awq/gptq sí los sirve el motor cuantizados; los GGUF (Q4_K_M) no cuentan."""
    m = get_model("qwen2.5-7b")
    if m is None:
        pytest.skip("qwen2.5-7b no está en el catálogo")
    monkeypatch.delenv("INFERBENCH_DOCKER_VRAM_OVERHEAD_GB", raising=False)
    from core import compat

    fp16 = compat.get_model_size_gb(m, "F16")
    awq = compat.get_model_size_gb(m, "awq") if "awq" in compat.QUANT_FACTOR else None
    if awq is None or awq >= fp16:
        pytest.skip("el catálogo no modela awq más pequeño que fp16")
    gpu(8.0, 8.0, (awq + 1.0 + 0.1) / 8.0)
    bm._check_docker_vram_budget(m, "awq", "vllm")  # cuantizado sí cabe
    with pytest.raises(RuntimeError):
        bm._check_docker_vram_budget(m, "Q4_K_M", "vllm")  # GGUF -> se sirve en fp16
