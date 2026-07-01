"""Endpoints /api/keys — gestión de API keys de cloud (vía keyring del SO).

Por seguridad NUNCA se devuelven los valores de las keys: solo si cada proveedor tiene
una guardada. El benchmark las recupera del keyring cuando el request no trae api_key.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import secrets

router = APIRouter(prefix="/api/keys", tags=["keys"])


class KeyIn(BaseModel):
    provider: str
    key: str


@router.get("")
async def list_keys() -> dict[str, bool]:
    """{proveedor: ¿hay key guardada?}. No expone los valores."""
    return secrets.has_keys()


@router.post("")
async def save_key(body: KeyIn) -> dict[str, str]:
    if body.provider not in secrets.PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {body.provider}")
    if not body.key.strip():
        raise HTTPException(400, "The API key is empty")
    try:
        secrets.set_key(body.provider, body.key.strip())
    except secrets.KeyringUnavailableError as e:
        raise HTTPException(503, str(e)) from e
    return {"saved": body.provider}


@router.delete("/{provider}")
async def delete_key(provider: str) -> dict[str, str]:
    if provider not in secrets.PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")
    secrets.delete_key(provider)
    return {"deleted": provider}
