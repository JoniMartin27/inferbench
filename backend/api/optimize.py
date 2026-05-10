"""Endpoint /api/optimize."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core import compat as _compat
from core.hardware import detect_hardware
from core.models_catalog import Model, get_model, load_models
from core.optimizer import (
    OptimalConfig,
    OptimizeRequest,
    benefits_summary,
    get_optimal_config,
)
from engines import registry

router = APIRouter(prefix="/api", tags=["optimize"])

_STATUS_RANK: dict[str, int] = {"ok": 0, "moe": 1, "partial": 2, "cpu": 3, "disk": 4}


class OptimizeResponse(BaseModel):
    config: OptimalConfig
    techniques: list[str]


class RecommendationRow(BaseModel):
    model: Model
    config: OptimalConfig
    techniques: list[str]
    engine_note: str | None = None


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


@router.get("/optimize/recommendations", response_model=list[RecommendationRow])
async def recommendations(top: int = Query(15, ge=1, le=53)) -> list[RecommendationRow]:
    """Para cada modelo del catálogo, encuentra el mejor motor+cuantización+KV que cabe en el hardware
    actual. Devuelve los top N modelos más potentes y ejecutables, ordenados por calidad de status
    y luego por número de parámetros.
    """
    hw_info = detect_hardware()
    snap = _compat.HardwareSnapshot(vram_gb=hw_info.primary_vram_gb, ram_gb=hw_info.ram_gb)
    local_engine_ids = ("llamacpp", "ollama")

    rows: list[RecommendationRow] = []

    for model in load_models():
        best_per_engine: dict[str, OptimalConfig] = {}
        for eng_id in local_engine_ids:
            cfg = get_optimal_config(eng_id, model.id, hw=hw_info)
            if cfg.feasible:
                best_per_engine[eng_id] = cfg

        if not best_per_engine:
            continue

        # Mejor motor: menor STATUS_RANK; en empate preferir llamacpp (más técnicas disponibles)
        winner_id = min(
            best_per_engine,
            key=lambda e: (_STATUS_RANK.get(best_per_engine[e].status, 9), 0 if e == "llamacpp" else 1),
        )
        winner = best_per_engine[winner_id]
        techniques = benefits_summary(winner, model, snap)

        engine_note: str | None = None
        if "llamacpp" in best_per_engine and "ollama" in best_per_engine:
            ll_rank = _STATUS_RANK.get(best_per_engine["llamacpp"].status, 9)
            ol_rank = _STATUS_RANK.get(best_per_engine["ollama"].status, 9)
            if ol_rank < ll_rank:
                engine_note = f"Ollama tiene mejor status ({best_per_engine['ollama'].status}) que llama.cpp"
            elif model.ollama_tag and ol_rank == ll_rank and winner_id == "llamacpp":
                engine_note = f"También disponible en Ollama ({model.ollama_tag})"
        elif winner_id == "ollama":
            engine_note = "Ollama recomendado (llama.cpp no compatible con este modelo)"

        rows.append(RecommendationRow(
            model=model,
            config=winner,
            techniques=techniques,
            engine_note=engine_note,
        ))

    # Ordenar: status (ok > moe > partial > cpu > disk), luego params_b desc
    rows.sort(key=lambda r: (_STATUS_RANK.get(r.config.status, 9), -r.model.params_b))
    return rows[:top]
