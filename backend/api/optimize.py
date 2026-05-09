"""Endpoint /api/optimize."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.optimizer import OptimalConfig, OptimizeRequest, get_optimal_config
from engines import registry

router = APIRouter(prefix="/api", tags=["optimize"])


@router.post("/optimize", response_model=OptimalConfig)
async def optimize(req: OptimizeRequest) -> OptimalConfig:
    try:
        registry.get_engine(req.engine)
    except KeyError as e:
        raise HTTPException(404, f"Motor desconocido: {req.engine}") from e
    return get_optimal_config(req.engine, req.model_id)
