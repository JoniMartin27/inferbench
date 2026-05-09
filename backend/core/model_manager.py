"""Descarga y caché de modelos GGUF desde Hugging Face."""
from __future__ import annotations

import os
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


async def ensure_gguf(model: Model, quant: str, progress: ProgressCb = None) -> Path:
    """Descarga el GGUF si no existe localmente. Devuelve la ruta absoluta."""
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
    downloaded = 0
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(None, connect=30.0), follow_redirects=True
    ) as client:
        # HEAD para tamaño y validar 200
        head = await client.head(url)
        if head.status_code == 404:
            raise RuntimeError(
                f"GGUF no encontrado en HF: {repo}/{filename}. "
                f"¿Cuantización {quant} no disponible?"
            )
        head.raise_for_status()
        total = int(head.headers.get("content-length", 0))

        if progress:
            await progress({
                "phase": "model.download",
                "model": model.id,
                "name": filename,
                "size": total,
                "downloaded": 0,
                "pct": 0,
            })

        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                last_pct = -1
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
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
    tmp.rename(target)
    if progress:
        await progress({"phase": "model.ready", "path": str(target)})
    return target
