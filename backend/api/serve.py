"""Endpoints /api/serve — modo Serve / MCP.

Sirve un modelo cuantizado de forma residente (slot único) y lo expone por la API
OpenAI del motor. La carga NO bloquea: /load arranca en background y responde con el
estado inicial; el frontend (o el server MCP) hace polling de /status hasta 'ready'.

Toda la lógica vive en core/serve.py::ServeManager — este router es fino.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from core import serve as serve_core

router = APIRouter(prefix="/api/serve", tags=["serve"])


class LoadRequest(BaseModel):
    model_id: str
    engine: str = "llamacpp"
    quant: str | None = None
    context: int | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    max_tokens: int = 512
    temperature: float = 0.7
    # Atajo: { "prompt": "..." } → [{role:"user", content:prompt}]
    prompt: str | None = None


@router.post("/load")
async def load(req: LoadRequest):
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
async def status():
    """Estado actual del slot servido."""
    return serve_core.get_manager().status_dict()


@router.post("/chat")
async def chat(req: ChatRequest):
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


@router.post("/unload")
async def unload():
    """Para el motor servido y libera VRAM."""
    try:
        return await serve_core.get_manager().unload()
    except Exception as e:  # noqa: BLE001
        logger.exception("serve unload failed")
        raise HTTPException(500, str(e)) from e
