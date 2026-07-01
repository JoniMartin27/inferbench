"""Descarga y caché de binarios nativos de motores (alternativa a Docker).

Por ahora soporta llama.cpp: descarga el zip pre-built de la release oficial de GitHub,
lo extrae a `%APPDATA%/InferBench/binaries/llamacpp/` (o ~/.inferbench/ en Linux/Mac)
y devuelve la ruta a `llama-server[.exe]`.
"""

from __future__ import annotations

import asyncio
import hashlib
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


def _parse_sha256_digest(digest: str | None) -> str | None:
    """Normaliza el campo `digest` de la API de GitHub a un hex sha256 en minúsculas.

    GitHub lo entrega como "sha256:<64 hex>". Devolvemos None si falta o no es sha256
    (no verificamos contra un algoritmo que no calculamos).
    """
    if not digest or not digest.lower().startswith("sha256:"):
        return None
    hexpart = digest.split(":", 1)[1].strip().lower()
    return hexpart if re.fullmatch(r"[0-9a-f]{64}", hexpart) else None


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extrae un zip rechazando nombres con path traversal (zip-slip).

    `zipfile.extractall` no valida rutas: un zip malicioso puede escribir fuera de
    `dest` usando `../../`. Iteramos los miembros y verificamos que cada ruta resuelta
    esté dentro de `dest` antes de extraer.
    """
    dest_resolved = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if not str(target).startswith(str(dest_resolved) + os.sep) and target != dest_resolved:
            raise RuntimeError(f"Path traversal detectado en zip: {member!r}")
        zf.extract(member, dest)


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
        except Exception as e:
            logger.debug(f"detect_hardware() falló, asumiendo sin NVIDIA: {e}")
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


def _flatten_nested_dir(found: Path, target: Path) -> None:
    """Si el binario quedó anidado (ej. `bin/`) tras extraer, sube sus hermanos (DLLs
    incluidas) al directorio raíz del motor. No pisa archivos ya presentes en `target`.
    """
    if found.parent == target:
        return
    for item in found.parent.iterdir():
        dest = target / item.name
        if dest.exists():
            continue
        item.rename(dest)


async def _download_zip(
    client: httpx.AsyncClient,
    asset: dict,
    dest_dir: Path,
    progress: ProgressCb,
    label: str,
    cancel_event: asyncio.Event | None = None,
) -> None:
    """Descarga un asset zip y lo extrae en `dest_dir`. Borra el zip al terminar.

    Si `cancel_event` se setea durante la descarga, aborta con CancelledError y
    elimina el zip parcial para no dejar basura.
    """
    url = asset["browser_download_url"]
    if not _is_trusted_dl_host(url):
        raise RuntimeError(f"URL de descarga no confiable (host fuera de GitHub): {url}")
    size = asset.get("size", 0)
    name = asset["name"]
    # Digest esperado que publica la API de GitHub (formato "sha256:abc…"). Viaja por
    # TLS desde un host confiable (api.github.com), así que sirve de ancla de integridad
    # de cadena de suministro: verificamos que los bytes descargados casan con él.
    expected_digest = _parse_sha256_digest(asset.get("digest"))
    logger.info(f"Descargando {label}: {name} ({size / 1e6:.1f} MB)")
    if progress:
        await progress(
            {"phase": "download", "name": name, "size": size, "downloaded": 0, "label": label}
        )

    zip_path = dest_dir / name
    downloaded = 0
    last_pct = -1
    hasher = hashlib.sha256()
    try:
        with open(zip_path, "wb") as f:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                # Tras seguir redirects, el host final también debe ser de GitHub.
                if not _is_trusted_dl_host(str(resp.url)):
                    raise RuntimeError(f"Redirect de descarga a host no confiable: {resp.url}")
                async for chunk in resp.aiter_bytes(chunk_size=131072):
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError(f"Descarga de {name} cancelada por el usuario")
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress and size:
                        pct = round(downloaded / size * 100, 1)
                        if pct - last_pct >= 0.5:
                            await progress(
                                {
                                    "phase": "download",
                                    "label": label,
                                    "name": name,
                                    "downloaded": downloaded,
                                    "size": size,
                                    "pct": pct,
                                }
                            )
                            last_pct = pct
    except BaseException:
        # Limpiar zip parcial para no dejar basura ni interferir con un retry, sea la
        # descarga cancelada por el usuario o cortada por cualquier otro error (red,
        # host no confiable, HTTP no-2xx).
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    # Verificación de integridad: si GitHub publicó el digest, debe casar. Un mismatch
    # significa corrupción de descarga o un asset manipulado → borramos y abortamos.
    actual_digest = hasher.hexdigest()
    if expected_digest:
        if actual_digest != expected_digest:
            zip_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Checksum SHA-256 no coincide para {name}: "
                f"esperado {expected_digest}, obtenido {actual_digest}. Descarga abortada."
            )
        logger.info(f"Checksum verificado para {name}: sha256:{actual_digest}")
    else:
        # La release no expone digest (assets antiguos): no podemos verificar, pero
        # dejamos el hash en el log para auditoría/reproducibilidad.
        logger.warning(
            f"{name} sin digest en la API de GitHub; no se pudo verificar. "
            f"sha256 calculado: {actual_digest}"
        )

    if progress:
        await progress({"phase": "extract", "label": label, "name": name})
    with zipfile.ZipFile(zip_path) as zf:
        _safe_extractall(zf, dest_dir)
    zip_path.unlink()


async def install_llamacpp(
    progress: ProgressCb = None, cancel_event: asyncio.Event | None = None
) -> Path:
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

    logger.info(
        f"Buscando llama.cpp release: terms={terms} need_main={need_main} need_cudart={need_cudart}"
    )
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
            ref_name = (
                main_asset["name"]
                if main_asset
                else (
                    next(
                        (
                            a["name"]
                            for a in assets
                            if all(t in a["name"].lower() for t in terms)
                            and "cudart" not in a["name"].lower()
                        ),
                        "",
                    )
                )
            )
            cudart_asset = _match_cudart_asset(assets, ref_name)
            if not cudart_asset:
                logger.warning("No se encontró asset cudart; CUDA podría no inicializarse")

        if main_asset:
            await _download_zip(
                client, main_asset, target, progress, "main", cancel_event=cancel_event
            )
        if cudart_asset:
            await _download_zip(
                client, cudart_asset, target, progress, "cudart", cancel_event=cancel_event
            )

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
            f"{_exe_name()} no encontrado tras extraer. Contenido: {contents or '(vacío)'}"
        )

    if found.name != _exe_name():
        renamed = found.with_name(_exe_name())
        found.rename(renamed)
        found = renamed

    _flatten_nested_dir(found, target)
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


# ---------------------------------------------------------------------------
# stable-diffusion.cpp (generación de imagen)
#
# Mismo patrón que llama.cpp: zip de binarios precompilados de las releases de GitHub +
# zip cudart aparte con las DLLs del runtime CUDA. La diferencia está en cómo se nombran
# los assets: sd.cpp usa "sd-master-<hash>-bin-win-cuda12-x64.zip" para CUDA y
# "sd-master-<hash>-bin-win-avx2-x64.zip" (avx/avx2/avx512/noavx) para CPU — NO hay un
# asset "win-x64" liso como en llama.cpp.
# ---------------------------------------------------------------------------

SD_REPO = "leejet/stable-diffusion.cpp"
# Builds alternativas que nunca queremos (aceleradores que no soportamos aquí).
_SD_EXCLUDE_TERMS = ["vulkan", "rocm", "hip", "sycl", "kompute"]


def _sd_server_exe_name() -> str:
    return "sd-server.exe" if os.name == "nt" else "sd-server"


def _stablediffusion_dir() -> Path:
    return BIN_ROOT / "stablediffusion"


def stablediffusion_binary_path() -> Path:
    """Dónde estaría el binario `sd-server`, exista o no."""
    return _stablediffusion_dir() / _sd_server_exe_name()


def stablediffusion_installed() -> bool:
    return stablediffusion_binary_path().exists()


def stablediffusion_fully_installed() -> bool:
    """True si el binario + (cudart si es build CUDA) están presentes."""
    if not stablediffusion_binary_path().exists():
        return False
    terms = _stablediffusion_variant_terms()
    if any("cuda" in t for t in terms) and not _has_cudart_dlls(_stablediffusion_dir()):
        return False
    return True


def _stablediffusion_variant_terms() -> list[str]:
    """Términos requeridos en el nombre del asset de sd.cpp para esta máquina.

    Windows + NVIDIA → build CUDA12. Windows sin NVIDIA → build CPU AVX2 (lo más común en
    x86-64 moderno). Linux/macOS quedan a la build estándar de su plataforma.
    """
    sysname = platform.system()
    machine = platform.machine().lower()

    if sysname == "Windows":
        try:
            from .hardware import detect_hardware

            has_nvidia = any(g.vendor == "nvidia" for g in detect_hardware().gpus)
        except Exception as e:
            logger.debug(f"detect_hardware() falló, asumiendo sin NVIDIA: {e}")
            has_nvidia = False
        if has_nvidia:
            return ["win", "cuda12", "x64"]
        return ["win", "avx2", "x64"]
    if sysname == "Darwin":
        return ["darwin", "arm64" if ("arm" in machine or machine == "aarch64") else "x64"]
    if sysname == "Linux":
        return ["linux", "x86_64" if ("x86" in machine or machine == "x86_64") else "x64"]
    raise RuntimeError(f"OS no soportado para stable-diffusion.cpp: {sysname}")


def _match_sd_asset(assets: list[dict], terms: list[str]) -> dict | None:
    """Asset principal de sd.cpp: incluye todos los términos, excluye builds alternativas
    y el paquete cudart-only (sin binarios). Si la build CUDA no aparece, cae a CPU AVX2.
    """
    excludes = _SD_EXCLUDE_TERMS + ["cudart"]
    for a in assets:
        n = a["name"].lower()
        if not n.endswith(".zip") or any(ex in n for ex in excludes):
            continue
        if all(t in n for t in terms):
            return a
    # Fallback: si pedíamos CUDA y no hay, intenta la build CPU AVX2 en la misma máquina.
    if any("cuda" in t for t in terms):
        cpu_terms = (
            ["win", "avx2", "x64"] if "win" in terms else [t for t in terms if "cuda" not in t]
        )
        if cpu_terms != terms:
            return _match_sd_asset(assets, cpu_terms)
    return None


async def install_stablediffusion(
    progress: ProgressCb = None, cancel_event: asyncio.Event | None = None
) -> Path:
    """Descarga y extrae stable-diffusion.cpp si no existe. Devuelve ruta a `sd-server`.

    Para builds CUDA descarga ADEMÁS el zip cudart con las DLLs del runtime CUDA (igual
    que llama.cpp). Reutiliza `_download_zip` (SHA-256, anti zip-slip, progreso, reanudación).
    """
    target = _stablediffusion_dir()
    exe = target / _sd_server_exe_name()
    target.mkdir(parents=True, exist_ok=True)
    terms = _stablediffusion_variant_terms()
    is_cuda = any("cuda" in t for t in terms)

    need_main = not exe.exists()
    need_cudart = is_cuda and not _has_cudart_dlls(target)
    if not need_main and not need_cudart:
        return exe

    logger.info(
        f"Buscando stable-diffusion.cpp release: terms={terms} "
        f"need_main={need_main} need_cudart={need_cudart}"
    )
    if progress:
        await progress({"phase": "lookup", "message": "Buscando última release de sd.cpp…"})

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
        r = await client.get(
            f"https://api.github.com/repos/{SD_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        release = r.json()
        tag = release.get("tag_name", "?")
        assets = release.get("assets", [])

        main_asset = _match_sd_asset(assets, terms) if need_main else None
        if need_main and not main_asset:
            raise RuntimeError(
                f"No se encontró asset de sd.cpp compatible en release {tag}. Términos: {terms}"
            )

        cudart_asset = None
        if need_cudart:
            ref_name = main_asset["name"] if main_asset else ""
            cudart_asset = _match_cudart_asset(assets, ref_name)
            if not cudart_asset:
                logger.warning("No se encontró cudart de sd.cpp; CUDA podría no inicializarse")

        if main_asset:
            await _download_zip(
                client, main_asset, target, progress, "sd-main", cancel_event=cancel_event
            )
        if cudart_asset:
            await _download_zip(
                client, cudart_asset, target, progress, "sd-cudart", cancel_event=cancel_event
            )

    # Localizar el binario del server (puede quedar anidado en bin/ tras extraer).
    found = next(target.rglob(_sd_server_exe_name()), None)
    if not found:
        contents = sorted(p.name for p in target.rglob("*") if p.is_file())[:30]
        raise RuntimeError(
            f"{_sd_server_exe_name()} no encontrado tras extraer sd.cpp. "
            f"Contenido: {contents or '(vacío)'}"
        )

    # Aplanar: mover el binario y sus DLLs hermanas al directorio raíz del motor.
    _flatten_nested_dir(found, target)

    if progress:
        await progress({"phase": "done", "path": str(exe)})
    return exe


def stablediffusion_status() -> dict:
    """Estado del binario stable-diffusion.cpp."""
    exe = stablediffusion_binary_path()
    return {
        "installed": exe.exists(),
        "path": str(exe),
        "dir": str(_stablediffusion_dir()),
    }
