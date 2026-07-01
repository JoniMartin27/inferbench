"""Endpoints /api/serve — modo Serve / MCP.

Sirve un modelo cuantizado de forma residente (slot único) y lo expone por la API
OpenAI del motor. La carga NO bloquea: /load arranca en background y responde con el
estado inicial; el frontend (o el server MCP) hace polling de /status hasta 'ready'.

Toda la lógica vive en core/serve.py::ServeManager — este router es fino.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from core import serve as serve_core

router = APIRouter(prefix="/api/serve", tags=["serve"])


class LoadRequest(BaseModel):
    model_id: str
    engine: str = "llamacpp"
    quant: str | None = None
    # None → ctx óptimo calculado por el planner; si se fija, debe ser positivo (un valor
    # <=0 llegaría tal cual a `-c` de llama-server).
    context: int | None = Field(default=None, gt=0)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    max_tokens: int = Field(default=512, ge=1, le=32768)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # Atajo: { "prompt": "..." } → [{role:"user", content:prompt}]
    prompt: str | None = None


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    # Cotas defensivas en el borde de la API: sin esto, steps/width/height fuera de rango
    # llegan tal cual al subproceso sd.cpp (cuelgues largos o fallos opacos del binario).
    steps: int = Field(default=20, ge=1, le=150)
    width: int = Field(default=512, ge=64, le=2048)
    height: int = Field(default=512, ge=64, le=2048)
    seed: int = -1
    cfg_scale: float = Field(default=7.0, ge=0.0, le=30.0)
    sampler: str | None = None


@router.post("/load")
async def load(req: LoadRequest) -> dict[str, Any]:
    """Empieza a servir un modelo de forma residente (no bloquea)."""
    try:
        return await serve_core.get_manager().load(
            model_id=req.model_id,
            engine=req.engine,
            quant=req.quant,
            context=req.context,
        )
    except serve_core.ServeError as e:
        raise HTTPException(e.status_code, e.message) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("serve load failed")
        raise HTTPException(500, str(e)) from e


@router.get("/status")
async def status() -> dict[str, Any]:
    """Estado actual del slot servido."""
    return serve_core.get_manager().status_dict()


@router.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    """Proxy de chat (no-stream) al modelo servido. 409 si no hay modelo ready."""
    messages = [m.model_dump() for m in req.messages]
    if req.prompt is not None and not messages:
        messages = [{"role": "user", "content": req.prompt}]
    if not messages:
        raise HTTPException(400, "Faltan 'messages' o 'prompt'.")
    try:
        return await serve_core.get_manager().chat(
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
    except serve_core.ServeError as e:
        raise HTTPException(e.status_code, e.message) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("serve chat failed")
        raise HTTPException(500, str(e)) from e


@router.post("/generate")
async def generate(req: GenerateRequest) -> dict[str, Any]:
    """Genera una imagen con el modelo de imagen servido. 409 si no hay uno ready.

    Devuelve la imagen como data URL PNG base64 (`image_b64`) + metadata (seed, tamaño,
    steps, tiempo). Proxy a stable-diffusion.cpp vía core/serve.py.
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(400, "Falta 'prompt'.")
    try:
        return await serve_core.get_manager().generate(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            steps=req.steps,
            width=req.width,
            height=req.height,
            seed=req.seed,
            cfg_scale=req.cfg_scale,
            sampler=req.sampler,
        )
    except serve_core.ServeError as e:
        raise HTTPException(e.status_code, e.message) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("serve generate failed")
        raise HTTPException(500, str(e)) from e


@router.post("/unload")
async def unload() -> dict[str, Any]:
    """Para el motor servido y libera VRAM."""
    try:
        return await serve_core.get_manager().unload()
    except Exception as e:  # noqa: BLE001
        logger.exception("serve unload failed")
        raise HTTPException(500, str(e)) from e
