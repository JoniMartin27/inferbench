"""Almacenamiento seguro de API keys de cloud vía el keyring del SO.

Las keys NUNCA se guardan en SQLite ni en archivos de config en plano (regla del proyecto):
van al gestor de credenciales del sistema (Windows Credential Manager, macOS Keychain,
Secret Service en Linux). Este módulo es la única puerta de entrada/salida.
"""
from __future__ import annotations

import keyring
from keyring.errors import KeyringError
from loguru import logger

_SERVICE = "InferBench"
PROVIDERS = ("openai", "anthropic", "openrouter", "nvidia")


def set_key(provider: str, key: str) -> None:
    """Guarda (o reemplaza) la API key de un proveedor en el keyring del SO."""
    keyring.set_password(_SERVICE, provider, key)


def get_key(provider: str) -> str | None:
    """Devuelve la API key guardada de un proveedor, o None si no hay / falla el keyring."""
    try:
        return keyring.get_password(_SERVICE, provider)
    except KeyringError as e:  # backend de keyring no disponible
        logger.warning(f"keyring get '{provider}': {e}")
        return None


def delete_key(provider: str) -> None:
    try:
        keyring.delete_password(_SERVICE, provider)
    except KeyringError:
        pass  # no existía o backend no disponible


def has_keys() -> dict[str, bool]:
    """Mapa {proveedor: ¿hay key?}. NO expone los valores — solo presencia."""
    return {p: bool(get_key(p)) for p in PROVIDERS}
