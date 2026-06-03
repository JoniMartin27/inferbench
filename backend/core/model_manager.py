"""Descarga y caché de modelos GGUF desde Hugging Face."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from loguru import logger

from .models_catalog import Model

MODELS_ROOT = (
    Path(os.environ["APPDATA"]) / "InferBench" / "models"
    if os.name == "nt" and "APPDATA" in os.environ
    else Path.home() / ".inferbench" / "models"
)

# Caché de existencia de recursos remotos. Clave: (namespace, resource).
# Valor: (existe: bool, expira: datetime). TTL de 20 minutos.
_exists_cache: dict[tuple[str, str], tuple[bool, datetime]] = {}
_EXISTS_CACHE_TTL = timedelta(minutes=20)

# Descargas resilientes: reintentos con backoff exponencial. Las descargas de
# GGUF pueden ser de decenas de GB; un corte de red no debe tirar todo el trabajo.
_MAX_DL_RETRIES = 4
_DL_BACKOFF_BASE = 1.5  # segundos → 1.5, 3, 6 entre reintentos
_NET_SEMAPHORE: asyncio.Semaphore | None = None  # inicializado lazy (necesita loop)


def _net_sem() -> asyncio.Semaphore:
    global _NET_SEMAPHORE
    if _NET_SEMAPHORE is None:
        _NET_SEMAPHORE = asyncio.Semaphore(6)  # máx 6 requests en paralelo
    return _NET_SEMAPHORE


def _cache_get(key: tuple[str, str]) -> bool | None:
    entry = _exists_cache.get(key)
    if entry and datetime.now() < entry[1]:
        return entry[0]
    return None


def _cache_set(key: tuple[str, str], exists: bool) -> None:
    _exists_cache[key] = (exists, datetime.now() + _EXISTS_CACHE_TTL)


async def hf_file_exists(repo: str, filename: str) -> bool:
    """HEAD check contra HuggingFace para un archivo concreto (ej. .gguf).

    Cachea 20 min. En error de red devuelve True para no bloquear al usuario.
    HF devuelve 401/403 (no 404) para archivos inexistentes en repos públicos.
    """
    key = ("hf_file", f"{repo}/{filename}")
    cached = _cache_get(key)
    if cached is not None:
        return cached

    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
    async with _net_sem():
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True
            ) as client:
                resp = await client.head(url)
                exists = resp.status_code not in (401, 403, 404)
        except Exception:
            logger.debug(f"hf_file_exists timeout/error: {url}")
            return True  # en error de red, asumir que existe

    _cache_set(key, exists)
    logger.debug(f"HF HEAD {url} → exists={exists}")
    return exists


async def hf_repo_exists(repo: str) -> bool:
    """Verifica si un repo de HuggingFace existe (para vLLM / SGLang / TGI).

    Todos los repos HF válidos tienen README.md; lo usamos como sonda.
    """
    return await hf_file_exists(repo, "README.md")


async def ollama_model_exists(tag: str) -> bool:
    """Verifica si un tag de Ollama existe en el registro público (registry.ollama.ai).

    Sigue el protocolo OCI de manifests. Cachea 20 min.
    Devuelve True en caso de error de red para no bloquear al usuario.
    """
    key = ("ollama", tag)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    model_name, _, version = tag.partition(":")
    version = version or "latest"
    url = f"https://registry.ollama.ai/v2/library/{model_name}/manifests/{version}"
    headers = {"Accept": "application/vnd.oci.image.manifest.v1+json"}

    async with _net_sem():
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True
            ) as client:
                resp = await client.head(url, headers=headers)
                exists = resp.status_code not in (401, 403, 404)
        except Exception:
            logger.debug(f"ollama_model_exists timeout/error: {tag}")
            return True

    _cache_set(key, exists)
    logger.debug(f"Ollama registry {tag} → exists={exists}")
    return exists

ProgressCb = Callable[[dict], Awaitable[None]] | None


def _model_file(model: Model, quant: str) -> Path:
    if not model.hf_gguf:
        raise RuntimeError(f"Modelo {model.id} no tiene fuente HF GGUF configurada")
    repo = model.hf_gguf.repo
    filename = model.hf_gguf.file_template.format(quant=quant)
    return MODELS_ROOT / repo.replace("/", "__") / filename


def gguf_path(model: Model, quant: str) -> Path:
    return _model_file(model, quant)


def gguf_installed(model: Model, quant: str) -> bool:
    return _model_file(model, quant).exists()


async def ensure_gguf(
    model: Model,
    quant: str,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
) -> Path:
    """Descarga el GGUF si no existe localmente. Devuelve la ruta absoluta.

    Resiliencia: reintenta hasta `_MAX_DL_RETRIES` veces con backoff exponencial y
    reanuda desde el `.part` parcial vía cabecera Range si el servidor lo soporta.
    Si se pasa `cancel_event` y se setea durante la descarga, se aborta con
    asyncio.CancelledError y el `.part` se conserva (permite reanudar). Si se agotan
    los reintentos, el `.part` se elimina para no dejar basura en disco.
    """
    if not model.hf_gguf:
        raise RuntimeError(
            f"Modelo {model.id} no tiene fuente HF GGUF configurada en el catálogo"
        )

    target = _model_file(model, quant)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    repo = model.hf_gguf.repo
    filename = target.name
    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"

    logger.info(f"Descargando GGUF: {url}")
    if progress:
        await progress({"phase": "model.lookup", "model": model.id, "quant": quant, "url": url})

    tmp = target.with_suffix(target.suffix + ".part")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(None, connect=30.0), follow_redirects=True
    ) as client:
        # HEAD para tamaño y validar 200
        head = await client.head(url)
        # HF devuelve 401/403 (no 404) para archivos inexistentes en repos públicos.
        # 404 también puede ocurrir si el repo entero no existe. Son errores
        # permanentes → no se reintentan.
        if head.status_code in (401, 403, 404):
            raise RuntimeError(
                f"Cuantización {quant} no disponible para {model.id} en {repo}. "
                f"Bartowski no publica {quant} para este modelo. "
                f"Prueba con Q4_K_M o usa Modelos → Locales para apuntar a un GGUF tuyo."
            )
        head.raise_for_status()
        total = int(head.headers.get("content-length", 0))
        accept_ranges = head.headers.get("accept-ranges", "").lower() == "bytes"

        if progress:
            await progress({
                "phase": "model.download",
                "model": model.id,
                "name": filename,
                "size": total,
                "downloaded": 0,
                "pct": 0,
            })

        last_err: Exception | None = None
        for attempt in range(_MAX_DL_RETRIES):
            # Reanudar desde el .part parcial si el servidor soporta Range.
            resume_from = tmp.stat().st_size if (accept_ranges and tmp.exists()) else 0
            if total and resume_from >= total:
                resume_from = 0  # .part corrupto/sobredimensionado → reempezar
            headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
            mode = "ab" if resume_from else "wb"
            downloaded = resume_from
            try:
                async with client.stream("GET", url, headers=headers) as resp:
                    # Si pedimos Range pero el servidor responde 200, ignoró la
                    # reanudación → reempezamos sobreescribiendo el .part.
                    if resume_from and resp.status_code == 200:
                        mode, downloaded = "wb", 0
                    resp.raise_for_status()
                    last_pct = -1.0
                    with open(tmp, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            if cancel_event is not None and cancel_event.is_set():
                                raise asyncio.CancelledError(
                                    f"Descarga de {filename} cancelada por el usuario"
                                )
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress and total:
                                pct = round(downloaded / total * 100, 1)
                                if pct - last_pct >= 0.5:
                                    await progress({
                                        "phase": "model.download",
                                        "model": model.id,
                                        "downloaded": downloaded,
                                        "size": total,
                                        "pct": pct,
                                    })
                                    last_pct = pct
                # Validar que la descarga está completa antes del rename atómico.
                if total and tmp.stat().st_size < total:
                    raise httpx.RemoteProtocolError(
                        f"descarga incompleta: {tmp.stat().st_size}/{total} bytes"
                    )
                tmp.rename(target)
                if progress:
                    await progress({"phase": "model.ready", "path": str(target)})
                return target
            except asyncio.CancelledError:
                raise  # cancelación del usuario: conservar .part para reanudar
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code < 500 and code != 429:  # 4xx (salvo 429) son permanentes
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Descarga de {filename} falló con HTTP {code}"
                    ) from e
                last_err = e
            except httpx.TransportError as e:
                last_err = e

            if attempt < _MAX_DL_RETRIES - 1:
                delay = _DL_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    f"Descarga de {filename} falló (intento {attempt + 1}/{_MAX_DL_RETRIES}): "
                    f"{last_err}. Reintento en {delay:.0f}s"
                )
                if progress:
                    await progress({
                        "phase": "model.retry",
                        "model": model.id,
                        "attempt": attempt + 1,
                        "max": _MAX_DL_RETRIES,
                        "delay": delay,
                    })
                await asyncio.sleep(delay)

        # Agotados los reintentos: limpiar el .part parcial y abortar con error claro.
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"No se pudo descargar {filename} tras {_MAX_DL_RETRIES} intentos: {last_err}"
        )
