"""Tests del tope de VRAM que protege el display (no saturar la GPU → no congelar pantalla)."""
import pytest

from core import hardware
from engines.base import StartRequest
from engines.vllm import VllmEngine


def test_display_reserve_default_and_env(monkeypatch):
    monkeypatch.delenv("INFERBENCH_GPU_RESERVE_GB", raising=False)
    assert hardware.gpu_display_reserve_gb(8.0) == 2.0  # max(2, 0.25*8)
    assert hardware.gpu_display_reserve_gb(24.0) == 6.0  # 0.25*24
    monkeypatch.setenv("INFERBENCH_GPU_RESERVE_GB", "0.5")
    assert hardware.gpu_display_reserve_gb(8.0) == 0.5


def test_safe_fraction_reserves_display(monkeypatch):
    monkeypatch.delenv("INFERBENCH_GPU_RESERVE_GB", raising=False)
    # 8GB total, 7 libres → usable = 7 - 2 = 5 → 5/8 = 0.62
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (7.0, 8.0))
    assert hardware.safe_gpu_fraction() == 0.62


def test_safe_fraction_zero_when_busy(monkeypatch):
    monkeypatch.delenv("INFERBENCH_GPU_RESERVE_GB", raising=False)
    # 8GB total, 2 libres → usable = 0 → 0.0 (señal de NO arrancar)
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (2.0, 8.0))
    assert hardware.safe_gpu_fraction() == 0.0


def test_safe_fraction_hard_cap(monkeypatch):
    monkeypatch.setenv("INFERBENCH_GPU_RESERVE_GB", "0.5")
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (80.0, 80.0))
    assert hardware.safe_gpu_fraction() == 0.85  # nunca por encima de 0.85


def test_vllm_always_caps_gpu_util(monkeypatch):
    monkeypatch.delenv("INFERBENCH_GPU_RESERVE_GB", raising=False)
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (8.0, 8.0))  # seguro = 0.75
    # Aunque el usuario pida 0.95, se capa a lo seguro
    cmd = VllmEngine().build_command(
        StartRequest(engine_opts={"hf_model_id": "x", "gpuMemUtil": 0.95})
    )
    util = float(cmd[cmd.index("--gpu-memory-utilization") + 1])
    assert util <= 0.75
    # Y aunque NO pida nada, igual se inyecta el tope (vLLM por defecto usaría 0.9)
    cmd2 = VllmEngine().build_command(StartRequest(engine_opts={"hf_model_id": "x"}))
    assert "--gpu-memory-utilization" in cmd2


def test_start_docker_guard_refuses_when_unsafe(monkeypatch):
    monkeypatch.setattr(hardware, "safe_gpu_fraction", lambda: 0.0)
    monkeypatch.setattr(hardware, "gpu_memory_gb", lambda: (1.0, 8.0))
    with pytest.raises(RuntimeError, match="saturar la pantalla"):
        VllmEngine()._start_docker(StartRequest(runtime="docker", gpu=True))
