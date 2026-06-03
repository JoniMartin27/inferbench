"""Detección de hardware: CPU, RAM, GPU (NVIDIA / AMD / Apple / CPU-only)."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Literal

import psutil
from loguru import logger
from pydantic import BaseModel

GpuVendor = Literal["nvidia", "amd", "apple", "intel", "unknown"]


class GPUInfo(BaseModel):
    vendor: GpuVendor
    name: str
    vram_gb: float
    driver: str | None = None
    index: int = 0


class CPUInfo(BaseModel):
    name: str
    arch: str
    physical_cores: int
    logical_cores: int
    freq_mhz: float | None = None


class HardwareInfo(BaseModel):
    os: str
    os_version: str
    cpu: CPUInfo
    ram_gb: float
    ram_available_gb: float
    gpus: list[GPUInfo]
    primary_vram_gb: float  # vram de la GPU principal (0 si CPU-only)


def _detect_cpu() -> CPUInfo:
    name = platform.processor() or platform.machine() or "Unknown CPU"
    # En Linux platform.processor() suele estar vacío, intenta /proc/cpuinfo.
    if not name or name == platform.machine():
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
    freq = psutil.cpu_freq()
    return CPUInfo(
        name=name,
        arch=platform.machine(),
        physical_cores=psutil.cpu_count(logical=False) or 0,
        logical_cores=psutil.cpu_count(logical=True) or 0,
        freq_mhz=freq.max if freq else None,
    )


def _detect_nvidia() -> list[GPUInfo]:
    try:
        import pynvml  # type: ignore
    except ImportError:
        return []
    try:
        pynvml.nvmlInit()
    except Exception as e:
        logger.debug(f"pynvml init failed: {e}")
        return []
    gpus: list[GPUInfo] = []
    try:
        count = pynvml.nvmlDeviceGetCount()
        try:
            driver = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(driver, bytes):
                driver = driver.decode()
        except Exception:
            driver = None
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpus.append(
                GPUInfo(
                    vendor="nvidia",
                    name=name,
                    vram_gb=round(mem.total / (1024**3), 2),
                    driver=driver,
                    index=i,
                )
            )
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return gpus


def _detect_amd() -> list[GPUInfo]:
    """AMD via rocm-smi (Linux/Windows con ROCm). Best-effort."""
    if not shutil.which("rocm-smi"):
        return []
    try:
        out = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return []
        import json

        data = json.loads(out.stdout)
        gpus: list[GPUInfo] = []
        for idx, (_card, info) in enumerate(data.items()):
            name = info.get("Card series") or info.get("Card model") or "AMD GPU"
            vram_bytes = int(info.get("VRAM Total Memory (B)", 0) or 0)
            gpus.append(
                GPUInfo(
                    vendor="amd",
                    name=name,
                    vram_gb=round(vram_bytes / (1024**3), 2),
                    index=idx,
                )
            )
        return gpus
    except Exception as e:
        logger.debug(f"rocm-smi probe failed: {e}")
        return []


def _detect_apple() -> list[GPUInfo]:
    """Apple Silicon: GPU comparte memoria con la RAM (unified memory)."""
    if platform.system() != "Darwin":
        return []
    try:
        out = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return []
        text = out.stdout
        # Nombre del chip
        name_match = re.search(r"Chipset Model:\s*(.+)", text)
        name = name_match.group(1).strip() if name_match else "Apple GPU"
        # En Apple Silicon la VRAM efectiva = RAM unificada (con overhead).
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
        return [GPUInfo(vendor="apple", name=name, vram_gb=ram_gb, index=0)]
    except Exception as e:
        logger.debug(f"system_profiler probe failed: {e}")
        return []


@lru_cache(maxsize=1)
def _detect_static() -> tuple[CPUInfo, tuple[GPUInfo, ...]]:
    """Detección cara (subprocesos nvidia-smi/wmi/system_profiler) cacheada.

    CPU y GPUs no cambian durante la sesión; sondearlas en cada request añadía
    ~30ms a /models/compat/all, /optimize/recommendations, dashboard, etc.
    La RAM disponible SÍ es dinámica y se recalcula aparte (psutil, ~0ms).
    """
    cpu = _detect_cpu()
    gpus: list[GPUInfo] = []
    gpus.extend(_detect_nvidia())
    gpus.extend(_detect_amd())
    gpus.extend(_detect_apple())
    return cpu, tuple(gpus)


def detect_hardware() -> HardwareInfo:
    """Detecta CPU, RAM y todas las GPUs disponibles (CPU/GPU cacheados)."""
    cpu, gpus_t = _detect_static()
    gpus = list(gpus_t)
    vm = psutil.virtual_memory()
    ram_gb = round(vm.total / (1024**3), 2)
    ram_avail = round(vm.available / (1024**3), 2)

    primary_vram = gpus[0].vram_gb if gpus else 0.0

    return HardwareInfo(
        os=platform.system(),
        os_version=platform.version(),
        cpu=cpu,
        ram_gb=ram_gb,
        ram_available_gb=ram_avail,
        gpus=gpus,
        primary_vram_gb=primary_vram,
    )


# ---- Seguridad de VRAM para motores Docker (vLLM/SGLang/TGI) ----
# vLLM/SGLang pre-asignan `fraccion * VRAM_total`. En un equipo de una sola GPU que TAMBIÉN
# pinta la pantalla, pedir demasiado ahoga al compositor → cortes de vídeo y cuelgues. Por
# eso reservamos SIEMPRE un margen para el display y acotamos la fracción a lo realmente libre.


def gpu_memory_gb() -> tuple[float, float]:
    """(libre, total) de la GPU 0 en GiB, en vivo. (0, 0) si no hay NVIDIA/pynvml."""
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0))
            return round(mem.free / (1024**3), 2), round(mem.total / (1024**3), 2)
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return 0.0, 0.0


def gpu_display_reserve_gb(total_gb: float) -> float:
    """VRAM a reservar SIEMPRE para el display/escritorio (evita cortes de vídeo).

    Configurable con env `INFERBENCH_GPU_RESERVE_GB`. Por defecto generoso (2 GB o el 25%
    del total) porque en un solo-GPU la tarjeta pinta la pantalla; quien tenga una GPU
    dedicada solo a inferencia puede bajarlo (incluso a 0)."""
    env = os.environ.get("INFERBENCH_GPU_RESERVE_GB")
    if env is not None:
        try:
            return max(0.0, float(env))
        except ValueError:
            pass
    return round(max(2.0, total_gb * 0.25), 1)


def safe_gpu_fraction() -> float:
    """Fracción MÁXIMA de VRAM total que un motor Docker puede pedir sin saturar la pantalla.

    Calculada desde la VRAM LIBRE actual menos la reserva de display. Devuelve 0.0 si no
    cabe nada de forma segura (la GPU está demasiado ocupada o es demasiado pequeña) → en
    ese caso NO se debe arrancar el motor. Sin GPU NVIDIA detectable, devuelve 0.85 (no
    aplica el tope; el motor fallará por su cuenta si no hay GPU)."""
    free, total = gpu_memory_gb()
    if total <= 0:
        return 0.85
    usable = min(free, total) - gpu_display_reserve_gb(total)
    if usable <= 0.5:
        return 0.0
    return round(max(0.1, min(0.85, usable / total)), 2)
