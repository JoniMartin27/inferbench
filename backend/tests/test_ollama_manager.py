"""Tests de core/ollama_manager.py."""

import httpx
import pytest

from core import ollama_manager


async def test_has_model_does_not_match_different_tag_same_base(monkeypatch):
    # Regresión: solo `llama3.2:1b` está descargado. Pedir `llama3.2:8b` (mismo nombre
    # base, tag distinto) NO debe contar como "ya lo tengo" — son pulls distintos y
    # confundirlos hacía que se saltara la descarga del tag correcto.
    async def fake_list_local_models():
        return [{"name": "llama3.2:1b"}]

    monkeypatch.setattr(ollama_manager, "list_local_models", fake_list_local_models)

    assert await ollama_manager.has_model("llama3.2:8b") is False
    assert await ollama_manager.has_model("llama3.2:1b") is True


async def test_has_model_defaults_to_latest_tag(monkeypatch):
    async def fake_list_local_models():
        return [{"name": "llama3.2:latest"}]

    monkeypatch.setattr(ollama_manager, "list_local_models", fake_list_local_models)

    assert await ollama_manager.has_model("llama3.2") is True
    assert await ollama_manager.has_model("llama3.2:1b") is False


async def test_pull_model_raises_on_inline_error_event(monkeypatch):
    # Regresión: Ollama reporta un pull fallido (tag inexistente) como una línea
    # {"error": "..."} dentro de un stream HTTP 200, no como un status code de error.
    # Sin comprobarlo, pull_model() volvía silenciosamente como si hubiera ido bien.
    body = (
        b'{"status": "pulling manifest"}\n{"error": "pull model manifest: file does not exist"}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(ollama_manager.httpx, "AsyncClient", fake_client)

    with pytest.raises(RuntimeError, match="does not exist"):
        await ollama_manager.pull_model("nonexistent-model:latest")
