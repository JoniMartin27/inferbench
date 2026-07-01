"""Descarga y caché de modelos GGUF desde Hugging Face."""

from __future__ import annotations

import asyncio
import os
import re
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


def _repo_dir(model: Model) -> Path:
    return MODELS_ROOT / model.hf_gguf.repo.replace("/", "__")


def _model_file(model: Model, quant: str) -> Path:
    if not model.hf_gguf:
        raise RuntimeError(f"Modelo {model.id} no tiene fuente HF GGUF configurada")
    return _repo_dir(model) / model.hf_gguf.file_template.format(quant=quant)


# ---- GGUF multi-parte (modelos enormes partidos en shards -00001-of-000NN.gguf) ----
def _shard_base(model: Model, quant: str) -> str:
    """Nombre base sin .gguf del fichero de un quant, p.ej. 'Model-Q4_K_M'."""
    name = model.hf_gguf.file_template.format(quant=quant)
    return name[:-5] if name.endswith(".gguf") else name


def _cached_shard1(model: Model, quant: str) -> Path | None:
    """Shard 1 ya cacheada de un quant multi-parte (puede estar en subdir), o None."""
    repo_dir = _repo_dir(model)
    if not repo_dir.exists():
        return None
    matches = sorted(repo_dir.glob(f"**/{_shard_base(model, quant)}-00001-of-*.gguf"))
    return matches[0] if matches else None


def _multipart_installed(model: Model, quant: str) -> bool:
    """¿Están TODOS los shards del quant ya en disco? (el total va en el nombre -of-000NN)."""
    s1 = _cached_shard1(model, quant)
    if not s1:
        return False
    m = re.search(r"-00001-of-(\d{5})\.gguf$", s1.name)
    if not m:
        return False
    total = int(m.group(1))
    return all(
        (s1.parent / re.sub(r"-00001-of-", f"-{i:05d}-of-", s1.name)).exists()
        for i in range(1, total + 1)
    )


def _filter_shards(rfilenames: list[str], base: str) -> list[str]:
    """De una lista de rfilenames, los shards `<base>-NNNNN-of-NNNNN.gguf`, ordenados.

    Ancla también el inicio del nombre de fichero (tras el último '/'): sin esto, un
    `base` que sea sufijo de otro modelo del mismo repo (ej. 'Model-Q4_K_M' dentro de
    'Big-Model-Q4_K_M-00001-of-00002.gguf') colaría shards de un modelo distinto.
    """
    pat = re.compile(r"(?:^|/)" + re.escape(base) + r"-\d{5}-of-\d{5}\.gguf$")
    return sorted(f for f in rfilenames if pat.search(f))


async def _fetch_shard_files(repo: str, base: str) -> list[str]:
    """rfilenames de los shards de `base` en el repo (vía HF API), ordenados. [] si no hay."""
    url = f"https://huggingface.co/api/models/{repo}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "inferbench"})
        resp.raise_for_status()
        data = resp.json()
    return _filter_shards([s.get("rfilename", "") for s in data.get("siblings", [])], base)


def _quants_from_filenames(file_template: str, filenames: list[str]) -> list[str]:
    """Deriva las cuantizaciones de una lista de nombres de fichero que casan el
    `file_template` (con {quant}). Ordenadas por calidad descendente. Pura (sin red)."""
    if "{quant}" not in file_template:
        return []
    pat = re.compile(
        "^" + re.escape(file_template).replace(re.escape("{quant}"), r"([A-Za-z0-9_.]+)") + "$"
    )
    found: set[str] = set()
    for f in filenames:
        name = (f or "").rsplit("/", 1)[-1]
        m = pat.match(name)
        if m:
            found.add(m.group(1))
    # Orden aproximado por calidad descendente (Q8 mejor que Q4 mejor que IQ2…).
    order = {
        "Q8_0": 0,
        "Q6_K": 1,
        "Q5_K_M": 2,
        "Q5_K_S": 3,
        "Q4_K_M": 4,
        "Q4_K_S": 5,
        "IQ4_XS": 6,
        "Q3_K_M": 7,
        "IQ3_M": 8,
        "Q2_K": 9,
        "IQ2_M": 10,
        "IQ2_XS": 11,
        "IQ2_XXS": 12,
        "IQ1_M": 13,
        "IQ1_S": 14,
    }
    return sorted(found, key=lambda q: order.get(q, 99))


async def available_quants(model: Model) -> list[str]:
    """Cuantizaciones realmente publicadas en el repo HF del modelo, derivadas de los
    ficheros que casan su `file_template`. Devuelve [] si no hay repo o falla la red
    (best-effort: solo se usa para enriquecer mensajes de error, nunca en el happy path)."""
    if not model.hf_gguf or "{quant}" not in model.hf_gguf.file_template:
        return []
    url = f"https://huggingface.co/api/models/{model.hf_gguf.repo}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "inferbench"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []
    names = [s.get("rfilename") or "" for s in data.get("siblings", [])]
    return _quants_from_filenames(model.hf_gguf.file_template, names)


def gguf_path(model: Model, quant: str) -> Path:
    if model.hf_gguf and model.hf_gguf.multipart:
        s1 = _cached_shard1(model, quant)
        if s1:
            return s1  # llama.cpp carga el resto de shards del mismo dir
    return _model_file(model, quant)


def gguf_installed(model: Model, quant: str) -> bool:
    if model.hf_gguf and model.hf_gguf.multipart:
        return _multipart_installed(model, quant)
    return _model_file(model, quant).exists()


async def _download_resilient(
    url: str,
    target: Path,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
    *,
    label: str,
    progress_meta: dict | None = None,
    not_found_msg: str | None = None,
) -> Path:
    """Descarga `url` → `target` con reintentos+backoff y reanudación vía Range.

    Núcleo compartido por `ensure_gguf` y `ensure_mmproj`. Idempotente (si `target`
    existe, no hace nada). Conserva el `.part` al cancelar (permite reanudar) y lo
    elimina al agotar reintentos. `progress_meta` se mezcla en los eventos (p.ej. el
    id del modelo); `not_found_msg` personaliza el error de 401/403/404.
    """
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    meta = progress_meta or {}
    filename = target.name

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(None, connect=30.0), follow_redirects=True
    ) as client:
        # HEAD para tamaño y validar 200. 401/403/404 = archivo inexistente en HF
        # (errores permanentes → no se reintentan).
        head = await client.head(url)
        if head.status_code in (401, 403, 404):
            raise RuntimeError(
                not_found_msg or f"{label} no disponible (HTTP {head.status_code}) en {url}"
            )
        head.raise_for_status()
        total = int(head.headers.get("content-length", 0))
        accept_ranges = head.headers.get("accept-ranges", "").lower() == "bytes"

        if progress:
            await progress(
                {
                    "phase": "model.download",
                    "name": filename,
                    "size": total,
                    "downloaded": 0,
                    "pct": 0,
                    **meta,
                }
            )

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
                                    await progress(
                                        {
                                            "phase": "model.download",
                                            "downloaded": downloaded,
                                            "size": total,
                                            "pct": pct,
                                            **meta,
                                        }
                                    )
                                    last_pct = pct
                # Validar que la descarga está completa antes del rename atómico.
                if total and tmp.stat().st_size < total:
                    raise httpx.RemoteProtocolError(
                        f"descarga incompleta: {tmp.stat().st_size}/{total} bytes"
                    )
                tmp.rename(target)
                if progress:
                    await progress({"phase": "model.ready", "path": str(target), **meta})
                return target
            except asyncio.CancelledError:
                raise  # cancelación del usuario: conservar .part para reanudar
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code < 500 and code != 429:  # 4xx (salvo 429) son permanentes
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(f"Descarga de {filename} falló con HTTP {code}") from e
                last_err = e
            except httpx.TransportError as e:
                last_err = e

            if attempt < _MAX_DL_RETRIES - 1:
                delay = _DL_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    f"Descarga de {filename} falló (intento {attempt + 1}/{_MAX_DL_RETRIES}): "
                    f"{last_err}. Reintento en {delay:.0f}s"
                )
                if progress:
                    await progress(
                        {
                            "phase": "model.retry",
                            "attempt": attempt + 1,
                            "max": _MAX_DL_RETRIES,
                            "delay": delay,
                            **meta,
                        }
                    )
                await asyncio.sleep(delay)

        # Agotados los reintentos: limpiar el .part parcial y abortar con error claro.
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"No se pudo descargar {label} tras {_MAX_DL_RETRIES} intentos: {last_err}"
        )


async def _ensure_gguf_multipart(
    model: Model, quant: str, progress: ProgressCb, cancel_event: asyncio.Event | None
) -> Path:
    """Descarga TODOS los shards de un GGUF multi-parte y devuelve el path de la shard 1
    (llama.cpp carga las hermanas del mismo directorio automáticamente)."""
    if _multipart_installed(model, quant):
        return _cached_shard1(model, quant)  # type: ignore[return-value]
    repo = model.hf_gguf.repo
    base = _shard_base(model, quant)
    if progress:
        await progress(
            {"phase": "model.lookup", "model": model.id, "quant": quant, "multipart": True}
        )
    shards = await _fetch_shard_files(repo, base)
    if not shards:
        raise RuntimeError(
            f"No se encontraron shards de {quant} para {model.id} en {repo}. "
            f"Prueba otro quant o revisa el catálogo."
        )
    repo_dir = _repo_dir(model)
    logger.info(f"Descargando {len(shards)} shards de {model.id} {quant}")
    for idx, rf in enumerate(shards, 1):
        await _download_resilient(
            f"https://huggingface.co/{repo}/resolve/main/{rf}",
            repo_dir / rf,  # preserva el subdir → los shards quedan juntos
            progress,
            cancel_event,
            label=f"shard {idx}/{len(shards)} de {model.id} {quant}",
            progress_meta={"model": model.id, "shard": idx, "shards": len(shards)},
        )
    return repo_dir / shards[0]


async def ensure_gguf(
    model: Model,
    quant: str,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
) -> Path:
    """Descarga el GGUF si no existe localmente. Devuelve la ruta absoluta.

    Resiliente: reintentos con backoff y reanudación vía Range (ver `_download_resilient`).
    Si el modelo es multi-parte (`hf_gguf.multipart`), descarga todos los shards.
    """
    if not model.hf_gguf:
        raise RuntimeError(f"Modelo {model.id} no tiene fuente HF GGUF configurada en el catálogo")
    if model.hf_gguf.multipart:
        return await _ensure_gguf_multipart(model, quant, progress, cancel_event)
    target = _model_file(model, quant)
    if target.exists():
        return target
    repo = model.hf_gguf.repo
    url = f"https://huggingface.co/{repo}/resolve/main/{target.name}"
    logger.info(f"Descargando GGUF: {url}")
    if progress:
        await progress({"phase": "model.lookup", "model": model.id, "quant": quant, "url": url})
    not_found = f"Cuantización {quant} no disponible para {model.id} en {repo}."
    try:
        return await _download_resilient(
            url,
            target,
            progress,
            cancel_event,
            label=f"GGUF {quant} de {model.id}",
            progress_meta={"model": model.id},
            not_found_msg=not_found,
        )
    except RuntimeError as e:
        # Solo el caso "no existe ese quant" (no errores de red/disco): enriquece el
        # mensaje listando las cuantizaciones REALES del repo en vez de adivinar.
        if not_found not in str(e):
            raise
        quants = await available_quants(model)
        if quants:
            alts = ", ".join(q for q in quants if q != quant) or "ninguna distinta"
            hint = f" Cuantizaciones disponibles en el repo: {alts}."
        else:
            hint = " Usa Modelos → Locales para apuntar a un GGUF tuyo."
        raise RuntimeError(not_found + hint) from e


# ---------------------------------------------------------------------------
# Modelos single-file (imagen: SD1.x/SDXL/SD-Turbo) y archivos auxiliares (FLUX:
# diffusion-model + vae + clip_l/clip_g + t5xxl). Mismo patrón que ensure_mmproj:
# un archivo extra que vive junto al modelo en el mismo repo HF.
# ---------------------------------------------------------------------------


def single_file_path(model: Model) -> Path | None:
    """Ruta local del checkpoint único (`hf_gguf.file`), o None si no aplica.

    Para modelos de imagen single-file (SD-Turbo, SD1.5) el catálogo trae `file` con el
    nombre exacto (sin {quant}); model_manager lo descarga tal cual.
    """
    if not (model.hf_gguf and model.hf_gguf.file):
        return None
    return _repo_dir(model) / model.hf_gguf.file


def single_file_installed(model: Model) -> bool:
    p = single_file_path(model)
    return bool(p and p.exists())


async def ensure_single_file(
    model: Model,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
) -> Path | None:
    """Descarga el checkpoint único (`hf_gguf.file`) del repo. None si no aplica."""
    target = single_file_path(model)
    if target is None:
        return None
    if target.exists():
        return target
    repo = model.hf_gguf.repo
    fn = model.hf_gguf.file
    url = f"https://huggingface.co/{repo}/resolve/main/{fn}"
    logger.info(f"Descargando checkpoint de imagen: {url}")
    if progress:
        await progress({"phase": "model.lookup", "model": model.id, "file": fn, "url": url})
    return await _download_resilient(
        url,
        target,
        progress,
        cancel_event,
        label=f"checkpoint de {model.id}",
        progress_meta={"model": model.id, "kind": "checkpoint"},
        not_found_msg=f"Checkpoint {fn} no disponible para {model.id} en {repo}.",
    )


def aux_path(model: Model, kind: str) -> Path | None:
    """Ruta local de un archivo auxiliar (vae/clip_l/clip_g/t5xxl/diffusion_model), o None.

    Análogo a mmproj_path: el auxiliar vive en el mismo repo HF que el modelo de difusión.
    `kind` es la clave del aux declarado en hf_gguf (ver HfGguf.aux_files).
    """
    if not model.hf_gguf:
        return None
    fn = model.hf_gguf.aux_files.get(kind)
    if not fn:
        return None
    return _repo_dir(model) / fn


def aux_installed(model: Model, kind: str) -> bool:
    p = aux_path(model, kind)
    return bool(p and p.exists())


async def ensure_aux(
    model: Model,
    kind: str,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
) -> Path | None:
    """Descarga un archivo auxiliar de difusión del mismo repo HF. None si no está declarado.

    Generaliza ensure_mmproj a los auxiliares de sd.cpp (FLUX): diffusion-model, VAE y
    encoders (clip_l/clip_g/t5xxl) viven junto al modelo y se cargan con sus flags.
    """
    target = aux_path(model, kind)
    if target is None:
        return None
    if target.exists():
        return target
    repo = model.hf_gguf.repo
    fn = model.hf_gguf.aux_files[kind]
    url = f"https://huggingface.co/{repo}/resolve/main/{fn}"
    logger.info(f"Descargando auxiliar {kind}: {url}")
    if progress:
        await progress({"phase": "model.lookup", "model": model.id, "aux": kind, "url": url})
    return await _download_resilient(
        url,
        target,
        progress,
        cancel_event,
        label=f"{kind} de {model.id}",
        progress_meta={"model": model.id, "kind": kind},
        not_found_msg=f"Auxiliar {fn} ({kind}) no disponible para {model.id} en {repo}.",
    )


async def ensure_all_aux(
    model: Model,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
) -> dict[str, Path]:
    """Descarga TODOS los auxiliares declarados del modelo. Devuelve kind→ruta local."""
    out: dict[str, Path] = {}
    if not model.hf_gguf:
        return out
    for kind in model.hf_gguf.aux_files:
        p = await ensure_aux(model, kind, progress, cancel_event)
        if p:
            out[kind] = p
    return out


def mmproj_path(model: Model) -> Path | None:
    """Ruta local del projector multimodal (mmproj), o None si el modelo no es de visión."""
    if not (model.hf_gguf and model.hf_gguf.mmproj):
        return None
    return _repo_dir(model) / model.hf_gguf.mmproj


def mmproj_installed(model: Model) -> bool:
    p = mmproj_path(model)
    return bool(p and p.exists())


async def ensure_mmproj(
    model: Model,
    progress: ProgressCb = None,
    cancel_event: asyncio.Event | None = None,
) -> Path | None:
    """Descarga el mmproj (projector de visión) del mismo repo GGUF. None si no aplica.

    El mmproj es un GGUF aparte (encoder de imagen) que llama-server carga con
    `--mmproj` para habilitar entrada multimodal. Vive junto al modelo en el repo.
    """
    target = mmproj_path(model)
    if target is None:
        return None
    if target.exists():
        return target
    repo = model.hf_gguf.repo
    fn = model.hf_gguf.mmproj
    url = f"https://huggingface.co/{repo}/resolve/main/{fn}"
    logger.info(f"Descargando mmproj: {url}")
    if progress:
        await progress({"phase": "model.lookup", "model": model.id, "mmproj": fn, "url": url})
    return await _download_resilient(
        url,
        target,
        progress,
        cancel_event,
        label=f"mmproj de {model.id}",
        progress_meta={"model": model.id, "kind": "mmproj"},
    )
