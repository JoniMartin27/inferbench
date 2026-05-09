"""Descarga y caché de binarios nativos de motores (alternativa a Docker).

Por ahora soporta llama.cpp: descarga el zip pre-built de la release oficial de GitHub,
lo extrae a `%APPDATA%/InferBench/binaries/llamacpp/` (o ~/.inferbench/ en Linux/Mac)
y devuelve la ruta a `llama-server[.exe]`.
"""
from __future__ import annotations

import os
import platform
import re
import zipfile
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from loguru import logger

BIN_ROOT = (
    Path(os.environ["APPDATA"]) / "InferBench" / "binaries"
    if os.name == "nt" and "APPDATA" in os.environ
    else Path.home() / ".inferbench" / "binaries"
)

LLAMACPP_REPO = "ggerganov/llama.cpp"

ProgressCb = Callable[[dict], Awaitable[None]] | None


def _llamacpp_variant_terms() -> list[str]:
    """Términos requeridos en el nombre del asset para esta máquina."""
    sysname = platform.system()
    machine = platform.machine().lower()

    if sysname == "Windows":
        try:
            from .hardware import detect_hardware

            has_nvidia = any(g.vendor == "nvidia" for g in detect_hardware().gpus)
        except Exception:
            has_nvidia = False
        base = ["win", "x64"]
        return base + (["cuda"] if has_nvidia else [])
    if sysname == "Darwin":
        return ["macos", "arm64" if "arm" in machine or machine == "aarch64" else "x64"]
    if sysname == "Linux":
        return ["ubuntu" if "x86" in machine or machine == "x86_64" else "linux", "x64"]
    raise RuntimeError(f"OS no soportado: {sysname}")


def _exe_name() -> str:
    return "llama-server.exe" if os.name == "nt" else "llama-server"


def _llamacpp_dir() -> Path:
    return BIN_ROOT / "llamacpp"


def llamacpp_binary_path() -> Path:
    """Devuelve dónde estaría el binario, exista o no."""
    return _llamacpp_dir() / _exe_name()


def llamacpp_installed() -> bool:
    return llamacpp_binary_path().exists()


EXCLUDE_TERMS = ["cudart", "vulkan", "hip", "sycl", "kompute"]


def _match_asset(assets: list[dict], terms: list[str]) -> dict | None:
    """Asset zip cuyo nombre contiene todos los términos y NO contiene términos excluidos.

    Excluimos paquetes auxiliares como `cudart` (solo DLLs del runtime, sin binarios)
    o builds alternativas (`vulkan`, `hip`, `sycl`, `kompute`).
    """
    for a in assets:
        n = a["name"].lower()
        if not n.endswith(".zip"):
            continue
        if any(ex in n for ex in EXCLUDE_TERMS):
            continue
        if all(t in n for t in terms):
            return a
    # Relajar si no hay match con cuda — caer a CPU
    if "cuda" in terms:
        return _match_asset(assets, [t for t in terms if t != "cuda"])
    return None


async def install_llamacpp(progress: ProgressCb = None) -> Path:
    """Descarga y extrae llama.cpp si no existe. Devuelve ruta al binario."""
    target = _llamacpp_dir()
    exe = target / _exe_name()
    if exe.exists():
        return exe

    target.mkdir(parents=True, exist_ok=True)
    terms = _llamacpp_variant_terms()
    logger.info(f"Buscando llama.cpp release con términos {terms}")

    if progress:
        await progress({"phase": "lookup", "message": "Buscando última release…"})

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:
        r = await client.get(
            f"https://api.github.com/repos/{LLAMACPP_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        release = r.json()
        tag = release.get("tag_name", "?")
        asset = _match_asset(release.get("assets", []), terms)
        if not asset:
            raise RuntimeError(
                f"No se encontró asset compatible en release {tag}. "
                f"Términos buscados: {terms}"
            )

        url = asset["browser_download_url"]
        size = asset.get("size", 0)
        name = asset["name"]
        logger.info(f"Descargando {name} ({size / 1e6:.1f} MB) desde {url}")
        if progress:
            await progress({"phase": "download", "name": name, "size": size, "downloaded": 0})

        zip_path = target / name
        downloaded = 0
        with open(zip_path, "wb") as f:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=131072):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress and size:
                        await progress({
                            "phase": "download",
                            "downloaded": downloaded,
                            "size": size,
                            "pct": round(downloaded / size * 100, 1),
                        })

    if progress:
        await progress({"phase": "extract"})

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    zip_path.unlink()

    # Localizar el binario (algunos releases lo nombran "server.exe")
    candidates = [_exe_name(), "server.exe" if os.name == "nt" else "server"]
    found = None
    for cand in candidates:
        found = next(target.rglob(cand), None)
        if found:
            break

    if not found:
        # Diagnóstico: listar lo que sí se extrajo
        contents = sorted(p.name for p in target.rglob("*") if p.is_file())[:20]
        raise RuntimeError(
            f"{_exe_name()} no encontrado tras extraer {name}. "
            f"Contenido del zip: {contents or '(vacío)'}"
        )

    # Si encontramos "server.exe" pero esperábamos "llama-server.exe", renombrar
    if found.name != _exe_name():
        renamed = found.with_name(_exe_name())
        found.rename(renamed)
        found = renamed

    # Mover binarios al directorio raíz si están anidados
    if found.parent != target:
        for item in found.parent.iterdir():
            dest = target / item.name
            if dest.exists():
                continue
            item.rename(dest)
    if progress:
        await progress({"phase": "done", "path": str(exe)})
    return exe


def llamacpp_status() -> dict:
    """Estado del binario llama.cpp."""
    exe = llamacpp_binary_path()
    return {
        "installed": exe.exists(),
        "path": str(exe),
        "dir": str(_llamacpp_dir()),
    }
