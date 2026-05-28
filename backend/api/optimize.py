"""Endpoint /api/optimize."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core import binary_manager, compat as _compat, docker_mgr, ollama_manager
from core.hardware import detect_hardware
from core.model_manager import (
    gguf_installed,
    hf_file_exists,
    hf_repo_exists,
    ollama_model_exists,
)
from core.models_catalog import Model, get_model, load_models
from core.optimizer import (
    ENGINE_QUANTS,
    OptimalConfig,
    OptimizeRequest,
    benefits_summary,
    get_optimal_config,
)
from engines import registry

router = APIRouter(prefix="/api", tags=["optimize"])

_STATUS_RANK: dict[str, int] = {"ok": 0, "moe": 1, "partial": 2, "cpu": 3, "disk": 4}
_STATUS_SCORE: dict[str, float] = {
    "ok": 1.0, "moe": 0.9, "partial": 0.7, "cpu": 0.3,
    "disk": 0.0, "fail": 0.0, "api": 0.8, "nofile": 0.0,
}


class OptimizeResponse(BaseModel):
    config: OptimalConfig
    techniques: list[str]


class RecommendationRow(BaseModel):
    model: Model
    config: OptimalConfig
    techniques: list[str]
    engine_note: str | None = None


class QuantOption(BaseModel):
    quant: str
    status: _compat.CompatStatus
    size_gb: float


class EngineRec(BaseModel):
    engine_id: str
    engine_name: str
    type: str
    feasible: bool
    status: _compat.CompatStatus
    best_quant: str | None = None
    context_len: int = 0
    runtime_ready: bool
    model_source: str   # "gguf" | "ollama" | "hf_repo" | "api" | "none"
    model_available: bool
    score: float        # 0–1, mayor = más recomendado


def _runtime_ready(eng_id: str, eng) -> bool:
    """Comprueba si el runtime del motor está instalado y listo sin lanzar el proceso."""
    if eng.meta.type == "api":
        return True
    for rt in eng.meta.runtimes:
        if rt == "native":
            if eng_id == "llamacpp" and binary_manager.llamacpp_fully_installed():
                return True
            if eng_id == "ollama" and ollama_manager.is_installed():
                return True
        elif rt == "docker":
            if docker_mgr.availability().get("available", False):
                return True
    return False


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


@router.get("/optimize/quants", response_model=list[QuantOption])
async def quants_for_model(
    engine: str = Query(..., description="ID del motor"),
    model_id: str = Query(..., description="ID del modelo"),
    kv_cache: str = Query("f16"),
    context_len: int = Query(4096),
) -> list[QuantOption]:
    """Para un (motor, modelo), devuelve cada cuantización con su status real:
    primero comprueba compatibilidad de hardware y después verifica que el archivo
    o modelo realmente existe en HuggingFace / registro de Ollama.
    """
    model = get_model(model_id)
    if model is None:
        raise HTTPException(404, f"Modelo desconocido: {model_id}")
    try:
        eng = registry.get_engine(engine)
    except KeyError as e:
        raise HTTPException(404, f"Motor desconocido: {engine}") from e

    quants = ENGINE_QUANTS.get(engine, [])
    if eng.meta.type == "api":
        return [QuantOption(quant="none", status="api", size_gb=0.0)]

    hw_info = detect_hardware()
    snap = _compat.HardwareSnapshot(vram_gb=hw_info.primary_vram_gb, ram_gb=hw_info.ram_gb)

    # 1ª pasada: compatibilidad de hardware (VRAM / RAM)
    rows: list[QuantOption] = []
    for q in quants:
        opts = _compat.EngineOpts(quant=q, kv_cache=kv_cache, context_len=context_len)
        status = _compat.check_compat(model, snap, opts, engine_id=engine, is_api=False)
        size = _compat.get_model_size_gb(model, q)
        rows.append(QuantOption(quant=q, status=status, size_gb=round(size, 2)))

    # 2ª pasada: verificar que el archivo/modelo realmente existe en el origen remoto.
    # Solo se comprueban las quants que el hardware admitiría (evita HEAD innecesarios).
    # Los requests van en paralelo con asyncio.gather y se cachean 20 min.

    if engine == "llamacpp" and model.hf_gguf:
        # Llamacpp: comprobación por archivo individual (.gguf)
        async def _check_gguf(row: QuantOption) -> QuantOption:
            if row.status in ("disk", "fail", "api"):
                return row
            if gguf_installed(model, row.quant):
                return row  # ya en caché local → existe
            filename = model.hf_gguf.file_template.format(quant=row.quant)
            exists = await hf_file_exists(model.hf_gguf.repo, filename)
            if not exists:
                return QuantOption(quant=row.quant, status="nofile", size_gb=row.size_gb)
            return row

        rows = list(await asyncio.gather(*[_check_gguf(r) for r in rows]))

    elif engine == "ollama" and model.ollama_tag:
        # Ollama: una sola comprobación del tag base; si no existe, todas las quants = nofile
        base_exists = await ollama_model_exists(model.ollama_tag)
        if not base_exists:
            rows = [
                QuantOption(quant=r.quant, status="nofile", size_gb=r.size_gb)
                if r.status not in ("disk", "fail")
                else r
                for r in rows
            ]

    elif engine in ("vllm", "sglang", "tgi") and model.hf_repo:
        # Docker engines: comprobación del repo HF (README.md como sonda)
        repo_exists = await hf_repo_exists(model.hf_repo)
        if not repo_exists:
            rows = [
                QuantOption(quant=r.quant, status="nofile", size_gb=r.size_gb)
                if r.status not in ("disk", "fail")
                else r
                for r in rows
            ]

    return rows


@router.get("/optimize/model-engines", response_model=list[EngineRec])
async def model_engines(
    model_id: str = Query(..., description="ID del modelo"),
) -> list[EngineRec]:
    """Para un modelo concreto, devuelve todos los motores con su compatibilidad,
    mejor cuantización y un score (0–1) que indica cuán bien está optimizado ese
    motor para el modelo en el hardware actual.
    Ordenados de mayor a menor score.
    """
    model = get_model(model_id)
    if model is None:
        raise HTTPException(404, f"Modelo desconocido: {model_id}")

    hw_info = detect_hardware()

    async def _rec(eng_id: str) -> EngineRec:
        eng = registry.get_engine(eng_id)
        is_api = eng.meta.type == "api"

        cfg = get_optimal_config(eng_id, model_id, hw=hw_info)
        runtime_ready = _runtime_ready(eng_id, eng)

        # Fuente del modelo y disponibilidad remota
        if is_api:
            model_source = "api"
            model_available = True
        elif eng_id == "llamacpp":
            model_source = "gguf"
            if model.hf_gguf and cfg.quant:
                if gguf_installed(model, cfg.quant):
                    model_available = True
                else:
                    filename = model.hf_gguf.file_template.format(quant=cfg.quant)
                    model_available = await hf_file_exists(model.hf_gguf.repo, filename)
            else:
                model_available = bool(model.hf_gguf)  # sin hf_gguf → no auto-descargable
        elif eng_id == "ollama":
            model_source = "ollama"
            model_available = bool(model.ollama_tag) and await ollama_model_exists(
                model.ollama_tag  # type: ignore[arg-type]
            )
        elif eng_id in ("vllm", "sglang", "tgi"):
            model_source = "hf_repo"
            model_available = bool(model.hf_repo) and await hf_repo_exists(
                model.hf_repo  # type: ignore[arg-type]
            )
        else:
            model_source = "none"
            model_available = False

        # Score: calidad de compatibilidad × disponibilidad × runtime instalado
        base = _STATUS_SCORE.get(cfg.status, 0.0) if cfg.feasible else 0.0
        score = base * (1.0 if model_available else 0.0) * (1.0 if runtime_ready else 0.55)

        return EngineRec(
            engine_id=eng_id,
            engine_name=eng.meta.name,
            type=eng.meta.type,
            feasible=cfg.feasible and model_available,
            status=cfg.status,
            best_quant=cfg.quant,
            context_len=cfg.context_len,
            runtime_ready=runtime_ready,
            model_source=model_source,
            model_available=model_available,
            score=round(score, 3),
        )

    recs = list(await asyncio.gather(*[_rec(eng_id) for eng_id in registry._REGISTRY]))
    recs.sort(key=lambda r: -r.score)
    return recs
