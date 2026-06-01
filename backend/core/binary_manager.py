"""Descarga y caché de binarios nativos de motores (alternativa a Docker).

Por ahora soporta llama.cpp: descarga el zip pre-built de la release oficial de GitHub,
lo extrae a `%APPDATA%/InferBench/binaries/llamacpp/` (o ~/.inferbench/ en Linux/Mac)
y devuelve la ruta a `llama-server[.exe]`.
"""
from __future__ import annotations

import asyncio
import os
import platform
import re
import zipfile
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx
from loguru import logger

# Hosts de los que aceptamos descargar binarios ejecutables. Defensa de cadena de
# suministro: si un redirect (follow_redirects=True) apuntara fuera de GitHub, se aborta.
_TRUSTED_DL_HOSTS = ("github.com", "githubusercontent.com")


def _is_trusted_dl_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _TRUSTED_DL_HOSTS)


EXCLUDE_TERMS_NEED = ["vulkan", "hip", "sycl", "kompute"]  # NUNCA queremos estos

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


def llamacpp_fully_installed() -> bool:
    """True si binario + (cudart si CUDA variant) están presentes."""
    if not llamacpp_binary_path().exists():
        return False
    terms = _llamacpp_variant_terms()
    if "cuda" in terms and not _has_cudart_dlls(_llamacpp_dir()):
        return False
    return True


def _match_asset(assets: list[dict], terms: list[str]) -> dict | None:
    """Asset principal con binarios: incluye todos los términos, excluye builds alternativas
    y el paquete cudart-only (sin binarios).
    """
    excludes = EXCLUDE_TERMS_NEED + ["cudart"]
    for a in assets:
        n = a["name"].lower()
        if not n.endswith(".zip") or any(ex in n for ex in excludes):
            continue
        if all(t in n for t in terms):
            return a
    if "cuda" in terms:
        return _match_asset(assets, [t for t in terms if t != "cuda"])
    return None


def _cuda_version(asset_name: str) -> str | None:
    """Extrae la versión CUDA del nombre del asset (ej. 'cu12.4' o 'cuda-12.4')."""
    m = re.search(r"cu(?:da)?[-_]?(\d{1,2}\.\d)", asset_name.lower())
    return m.group(1) if m else None


def _match_cudart_asset(assets: list[dict], main_name: str) -> dict | None:
    """Asset cudart compatible con la versión CUDA del binario principal."""
    cu_ver = _cuda_version(main_name)
    candidates = []
    for a in assets:
        n = a["name"].lower()
        if not n.endswith(".zip") or "cudart" not in n or "win" not in n:
            continue
        candidates.append(a)
    if cu_ver:
        for a in candidates:
            if cu_ver in a["name"].lower():
                return a
    return candidates[0] if candidates else None


def _has_cudart_dlls(directory: Path) -> bool:
    return any(directory.glob("cudart64_*.dll")) or any(directory.glob("cublas64_*.dll"))


async def _download_zip(client: httpx.AsyncClient, asset: dict, dest_dir: Path,
                        progress: ProgressCb, label: str,
                        cancel_event: asyncio.Event | None = None) -> None:
    """Descarga un asset zip y lo extrae en `dest_dir`. Borra el zip al terminar.

    Si `cancel_event` se setea durante la descarga, aborta con CancelledError y
    elimina el zip parcial para no dejar basura.
    """
    url = asset["browser_download_url"]
    if not _is_trusted_dl_host(url):
        raise RuntimeError(f"URL de descarga no confiable (host fuera de GitHub): {url}")
    size = asset.get("size", 0)
    name = asset["name"]
    logger.info(f"Descargando {label}: {name} ({size / 1e6:.1f} MB)")
    if progress:
        await progress({"phase": "download", "name": name, "size": size, "downloaded": 0,
                        "label": label})

    zip_path = dest_dir / name
    downloaded = 0
    last_pct = -1
    try:
        with open(zip_path, "wb") as f:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                # Tras seguir redirects, el host final también debe ser de GitHub.
                if not _is_trusted_dl_host(str(resp.url)):
                    raise RuntimeError(
                        f"Redirect de descarga a host no confiable: {resp.url}"
                    )
                async for chunk in resp.aiter_bytes(chunk_size=131072):
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError(
                            f"Descarga de {name} cancelada por el usuario"
                        )
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress and size:
                        pct = round(downloaded / size * 100, 1)
                        if pct - last_pct >= 0.5:
                            await progress({
                                "phase": "download", "label": label, "name": name,
                                "downloaded": downloaded, "size": size, "pct": pct,
                            })
                            last_pct = pct
    except asyncio.CancelledError:
        # Limpiar zip parcial para no dejar basura ni interferir con un retry
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    if progress:
        await progress({"phase": "extract", "label": label, "name": name})
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    zip_path.unlink()


async def install_llamacpp(progress: ProgressCb = None,
                           cancel_event: asyncio.Event | None = None) -> Path:
    """Descarga y extrae llama.cpp si no existe. Devuelve ruta al binario.

    Para builds CUDA, descarga ADEMÁS el zip cudart con las DLLs del runtime CUDA.
    Sin esas DLLs, ggml-cuda.dll falla al cargar y el motor cae a CPU silenciosamente.
    """
    target = _llamacpp_dir()
    exe = target / _exe_name()
    target.mkdir(parents=True, exist_ok=True)
    terms = _llamacpp_variant_terms()
    is_cuda = "cuda" in terms

    # ¿Necesitamos algo?
    need_main = not exe.exists()
    need_cudart = is_cuda and not _has_cudart_dlls(target)
    if not need_main and not need_cudart:
        return exe

    logger.info(f"Buscando llama.cpp release: terms={terms} need_main={need_main} need_cudart={need_cudart}")
    if progress:
        await progress({"phase": "lookup", "message": "Buscando última release…"})

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
        r = await client.get(
            f"https://api.github.com/repos/{LLAMACPP_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        release = r.json()
        tag = release.get("tag_name", "?")
        assets = release.get("assets", [])

        main_asset = _match_asset(assets, terms) if need_main else None
        if need_main and not main_asset:
            raise RuntimeError(
                f"No se encontró asset compatible en release {tag}. Términos: {terms}"
            )

        cudart_asset = None
        if need_cudart:
            ref_name = main_asset["name"] if main_asset else (
                next((a["name"] for a in assets if all(t in a["name"].lower() for t in terms)
                      and "cudart" not in a["name"].lower()), "")
            )
            cudart_asset = _match_cudart_asset(assets, ref_name)
            if not cudart_asset:
                logger.warning("No se encontró asset cudart; CUDA podría no inicializarse")

        if main_asset:
            await _download_zip(client, main_asset, target, progress, "main",
                                cancel_event=cancel_event)
        if cudart_asset:
            await _download_zip(client, cudart_asset, target, progress, "cudart",
                                cancel_event=cancel_event)

    # Localizar el binario (algunos releases lo nombran "server.exe")
    candidates = [_exe_name(), "server.exe" if os.name == "nt" else "server"]
    found = None
    for cand in candidates:
        found = next(target.rglob(cand), None)
        if found:
            break

    if not found:
        contents = sorted(p.name for p in target.rglob("*") if p.is_file())[:30]
        raise RuntimeError(
            f"{_exe_name()} no encontrado tras extraer. "
            f"Contenido: {contents or '(vacío)'}"
        )

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
