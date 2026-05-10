"""Endpoint /api/optimize."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import compat as _compat
from core.hardware import detect_hardware
from core.models_catalog import get_model
from core.optimizer import (
    OptimalConfig,
    OptimizeRequest,
    benefits_summary,
    get_optimal_config,
)
from engines import registry

router = APIRouter(prefix="/api", tags=["optimize"])


class OptimizeResponse(BaseModel):
    config: OptimalConfig
    techniques: list[str]


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest) -> OptimizeResponse:
    try:
        registry.get_engine(req.engine)
    except KeyError as e:
        raise HTTPException(404, f"Motor desconocido: {req.engine}") from e
    cfg = get_optimal_config(req.engine, req.model_id)
    model = get_model(req.model_id)
    hw_info = detect_hardware()
    snap = _compat.HardwareSnapshot(vram_gb=hw_info.primary_vram_gb, ram_gb=hw_info.ram_gb)
    techniques = benefits_summary(cfg, model, snap) if model else []
    return OptimizeResponse(config=cfg, techniques=techniques)
