"""Tests del servidor MCP "inferbench" (sin red real ni motor).

Verifican que el server expone las tools del contrato, que las tools hacen proxy al
backend REST, y que un backend caído produce un error CLARO (no un crash).
"""

from __future__ import annotations

import httpx
import pytest

import mcp_server


@pytest.mark.anyio
async def test_server_exposes_contract_tools():
    server = mcp_server.get_server()
    tools = await server.list_tools()
    names = {t.name for t in tools}
    expected = {
        "list_models",
        "recommend_models",
        "get_hardware",
        "serve_model",
        "serve_status",
        "chat",
        "stop_model",
    }
    assert expected <= names


@pytest.mark.anyio
async def test_get_backend_down_gives_clear_error(monkeypatch):
    """Si el backend no responde (ConnectError), las tools dan un mensaje accionable."""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("connection refused")

        async def post(self, *a, **k):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", _Client)

    with pytest.raises(RuntimeError) as exc:
        await mcp_server._get("/api/models")
    assert "InferBench no está abierto" in str(exc.value)

    with pytest.raises(RuntimeError) as exc2:
        await mcp_server._post("/api/serve/unload")
    assert "InferBench no está abierto" in str(exc2.value)


@pytest.mark.anyio
async def test_chat_tool_proxies_content(monkeypatch):
    async def fake_post(path, body=None):
        assert path == "/api/serve/chat"
        assert body["prompt"] == "hola"
        return {"content": "respuesta del modelo", "model_id": "m", "phase": "ready"}

    monkeypatch.setattr(mcp_server, "_post", fake_post)
    server = mcp_server.get_server()
    result = await server.call_tool("chat", {"prompt": "hola"})
    # call_tool devuelve (content_blocks, structured); el texto está en el bloque de texto.
    text = "".join(getattr(b, "text", "") for b in result[0])
    assert "respuesta del modelo" in text


def test_backend_url_env(monkeypatch):
    monkeypatch.delenv("INFERBENCH_BACKEND_URL", raising=False)
    assert mcp_server.backend_url() == "http://127.0.0.1:7777"
    monkeypatch.setenv("INFERBENCH_BACKEND_URL", "http://localhost:9999/")
    assert mcp_server.backend_url() == "http://localhost:9999"
