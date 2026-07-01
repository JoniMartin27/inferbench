"""Endpoints /api/models."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core import compat, local_models
from core.hardware import detect_hardware
from core.models_catalog import Model, get_model, load_models
from engines import registry

router = APIRouter(prefix="/api/models", tags=["models"])


class CompatRow(BaseModel):
    model: Model
    status: compat.CompatStatus
    model_size_gb: float
    kv_per_token_kb: float
    estimated_total_gb: float
    max_context: int


@router.get("", response_model=list[Model])
async def list_models() -> list[Model]:
    return load_models()


@router.get("/local", response_model=list[local_models.LocalModel])
async def list_local_models(refresh: bool = False) -> list[local_models.LocalModel]:
    """Escanea carpetas conocidas + extras y devuelve todos los GGUFs locales."""
    # discover() hace rglob sobre ~20 carpetas y lee headers GGUF (hasta 16 MB c/u),
    # todo I/O síncrono. Fuera del event loop para no congelar el backend (regla
    # load-bearing del proyecto: no bloquear el loop).
    return await asyncio.to_thread(local_models.discover, read_metadata=True)


class SearchDirs(BaseModel):
    known: list[str]
    extra: list[str]
    extra_dirs_file: str


@router.get("/local/dirs", response_model=SearchDirs)
async def list_search_dirs() -> SearchDirs:
    return SearchDirs(
        known=[str(d) for d in local_models.KNOWN_DIRS],
        extra=[str(d) for d in local_models.get_extra_dirs()],
        extra_dirs_file=str(local_models.get_extra_dirs_file()),
    )


class ExtraDirs(BaseModel):
    dirs: list[str]


class SavedDirs(BaseModel):
    saved: list[str]


@router.post("/local/dirs", response_model=SavedDirs)
async def update_search_dirs(body: ExtraDirs) -> SavedDirs:
    saved = local_models.set_extra_dirs(body.dirs)
    return SavedDirs(saved=[str(d) for d in saved])


@router.get("/{model_id}", response_model=Model)
async def get_one(model_id: str) -> Model:
    m = get_model(model_id)
    if m is None:
        raise HTTPException(404, f"Unknown model: {model_id}")
    return m


@router.get("/compat/all", response_model=list[CompatRow])
async def compat_all(
    engine: str = Query(..., description="ID de motor"),
    quant: str = Query("Q4_K_M"),
    kv_cache: str = Query("f16"),
    context_len: int = Query(4096, ge=1, le=131_072),
    moe_offload: int | None = Query(None, ge=0, le=1_000),
) -> list[CompatRow]:
    try:
        eng = registry.get_engine(engine)
    except KeyError as e:
        raise HTTPException(404, f"Unknown engine: {engine}") from e

    hw_info = detect_hardware()
    hw = compat.HardwareSnapshot(vram_gb=hw_info.primary_vram_gb, ram_gb=hw_info.ram_gb)
    opts = compat.EngineOpts(
        quant=quant, kv_cache=kv_cache, context_len=context_len, moe_offload=moe_offload
    )

    rows: list[CompatRow] = []
    for m in load_models():
        size = compat.get_model_size_gb(m, opts.quant)
        kv_mb = compat.get_kv_per_token_mb(m, opts.kv_cache)
        total = size + opts.context_len * (kv_mb / 1024.0) + 0.6
        status = compat.check_compat(m, hw, opts, engine_id=eng.meta.id, is_api=eng.is_api)
        max_ctx = compat.compute_max_context(m, hw, opts, engine_id=eng.meta.id, is_api=eng.is_api)
        rows.append(
            CompatRow(
                model=m,
                status=status,
                model_size_gb=round(size, 2),
                kv_per_token_kb=round(kv_mb * 1024, 2),
                estimated_total_gb=round(total, 2),
                max_context=max_ctx,
            )
        )
    return rows
