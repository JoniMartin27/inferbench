"""Endpoint /api/quality — cuánto cuesta cada cuantización, medido.

Los resultados se guardan en un JSON en el directorio de la app, NO en la base de datos:
son medidas de disco (modelo+corpus+ctx), no runs de benchmark, y meterlas en
`benchmark_runs` obligaría a migrar un esquema pensado para otra cosa.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from core import local_models, perplexity as ppl

router = APIRouter(prefix="/api/quality", tags=["quality"])

# Trabajos en curso: id -> cola de eventos. Igual que el runner de benchmark, el POST
# devuelve el id al momento y el stream va aparte.
_TRABAJOS: dict[str, asyncio.Queue] = {}
_TAREAS: dict[str, asyncio.Task] = {}


def _fichero_resultados() -> Path:
    base = (
        Path(os.environ["APPDATA"]) / "InferBench"
        if os.name == "nt" and "APPDATA" in os.environ
        else Path.home() / ".inferbench"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base / "quant_damage.json"


def cargar_resultados() -> list[dict]:
    f = _fichero_resultados()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # Un fichero corrupto no puede tumbar la vista: se avisa y se sigue con lista vacía.
        logger.warning(f"quant_damage.json ilegible: {e}")
        return []


def guardar_resultado(comp: dict) -> None:
    datos = [c for c in cargar_resultados() if c.get("modelo") != comp.get("modelo")]
    datos.append(comp)
    _fichero_resultados().write_text(
        json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8"
    )


class Candidato(BaseModel):
    modelo: str
    quants: list[str]
    referencia: str
    tamano_total_gb: float
    medido: bool = False


class PeticionMedida(BaseModel):
    modelo: str
    # 0 = el corpus entero. Bajarlo acorta la medida a costa de más error.
    chunks: int = 0
    ctx: int = ppl.CTX_POR_DEFECTO
    # Capas a GPU. 0 = todo en CPU, que es lo seguro cuando la VRAM está ocupada por
    # el escritorio; medir NO debería competir con la pantalla del usuario.
    ngl: int = 0


def _agrupar_por_modelo() -> dict[str, dict[str, local_models.LocalModel]]:
    """GGUFs de disco agrupados por modelo base. Solo interesan los que tienen ≥2 quants."""
    grupos: dict[str, dict[str, local_models.LocalModel]] = {}
    for m in local_models.discover(read_metadata=False):
        if m.is_projector or not m.quant:
            continue
        base = ppl._modelo_del_nombre(Path(m.filename))
        grupos.setdefault(base, {})[m.quant.upper()] = m
    return grupos


@router.get("/candidates", response_model=list[Candidato])
async def candidatos() -> list[Candidato]:
    """Modelos con al menos dos cuantizaciones en disco: los únicos comparables.

    Con una sola cuantización no hay nada que medir — el daño es *relativo* a una
    referencia, y la referencia tiene que ser el MISMO modelo a más precisión.
    """
    medidos = {c.get("modelo") for c in cargar_resultados()}
    salida: list[Candidato] = []
    for base, porquant in _agrupar_por_modelo().items():
        if len(porquant) < 2:
            continue
        ref = ppl.elegir_referencia(list(porquant))
        salida.append(
            Candidato(
                modelo=base,
                quants=sorted(porquant, key=ppl.rango_calidad),
                referencia=ref or "",
                tamano_total_gb=round(sum(m.size_gb for m in porquant.values()), 2),
                medido=base in medidos,
            )
        )
    return sorted(salida, key=lambda c: -len(c.quants))


@router.get("/results")
async def resultados(modelo: str | None = Query(None)) -> list[dict]:
    datos = cargar_resultados()
    return [c for c in datos if c.get("modelo") == modelo] if modelo else datos


@router.post("/measure")
async def medir(req: PeticionMedida) -> dict:
    if not ppl.instalado():
        raise HTTPException(
            status_code=400,
            detail="llama-perplexity is not installed. Install the llama.cpp engine first.",
        )
    grupos = _agrupar_por_modelo()
    porquant = grupos.get(req.modelo)
    if not porquant or len(porquant) < 2:
        raise HTTPException(
            status_code=404,
            detail=f"'{req.modelo}' needs at least two local quantizations to compare.",
        )

    job = uuid.uuid4().hex[:10]
    cola: asyncio.Queue = asyncio.Queue()
    _TRABAJOS[job] = cola

    rutas = {q: Path(m.path) for q, m in porquant.items()}

    async def trabajo():
        try:
            comp = await ppl.comparar_quants(
                rutas,
                ctx=req.ctx,
                chunks=req.chunks,
                ngl=req.ngl,
                al_evento=cola.put_nowait,
            )
            guardar_resultado(comp.dict())
        except Exception as e:  # noqa: BLE001 - el fallo tiene que llegar al usuario
            logger.exception("medida de cuantización fallida")
            cola.put_nowait({"type": "error", "detail": str(e)})
        finally:
            cola.put_nowait({"type": "eof"})

    _TAREAS[job] = asyncio.create_task(trabajo())
    return {"job_id": job, "modelo": req.modelo, "quants": len(rutas)}


@router.get("/measure/{job}/stream")
async def stream(job: str) -> StreamingResponse:
    cola = _TRABAJOS.get(job)
    if cola is None:
        raise HTTPException(status_code=404, detail="Unknown job")

    async def eventos():
        while True:
            ev = await cola.get()
            if ev.get("type") == "eof":
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        _TRABAJOS.pop(job, None)
        _TAREAS.pop(job, None)

    return StreamingResponse(eventos(), media_type="text/event-stream")


@router.post("/measure/{job}/cancel")
async def cancelar(job: str) -> dict:
    tarea = _TAREAS.get(job)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    tarea.cancel()
    cola = _TRABAJOS.get(job)
    if cola:
        cola.put_nowait({"type": "cancelled"})
        cola.put_nowait({"type": "eof"})
    return {"cancelled": True}
