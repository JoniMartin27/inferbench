"""Tests del servidor MCP "inferbench" (sin red real ni motor).

Verifican que el server expone las tools del contrato, que las tools hacen proxy al
backend REST, y que un backend caído produce un error CLARO (no un crash).
"""

from __future__ import annotations

import httpx
import pytest

import mcp_server


def bloques_de(resultado):
    """Bloques de contenido de un `call_tool`, sea cual sea la versión del SDK.

    mcp 1.x devuelve la tupla `(content_blocks, structured)`; mcp 2.x devuelve un
    `CallToolResult` con el contenido en `.content`. Los tests miran el CONTRATO (qué
    bloques salen), no la forma del envoltorio, así que normalizamos aquí.
    """
    contenido = getattr(resultado, "content", None)
    if contenido is not None:
        return list(contenido)
    if isinstance(resultado, tuple):
        return list(resultado[0])
    return list(resultado)


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
    text = "".join(getattr(b, "text", "") for b in bloques_de(result))
    assert "respuesta del modelo" in text


def test_backend_url_env(monkeypatch):
    monkeypatch.delenv("INFERBENCH_BACKEND_URL", raising=False)
    assert mcp_server.backend_url() == "http://127.0.0.1:7777"
    monkeypatch.setenv("INFERBENCH_BACKEND_URL", "http://localhost:9999/")
    assert mcp_server.backend_url() == "http://localhost:9999"


def test_el_handshake_anuncia_la_version_de_inferbench_no_la_del_sdk():
    """Lo que ve el usuario en Claude Desktop / Cursor es este número.

    Sin fijarlo, FastMCP (mcp 1.x) deja el server interno con `version=None` y el SDK
    responde SU propia versión: comprobado contra el exe empaquetado, `initialize`
    devolvía `serverInfo: inferbench v1.27.2` — la versión del paquete `mcp`, no la de la
    app.
    """
    from importlib.metadata import version as _pkg_version

    esperada = _pkg_version("inferbench-backend")
    server = mcp_server.get_server()

    # mcp 1.x expone el server de bajo nivel; 2.x lo lleva en el propio objeto.
    interno = getattr(server, "_mcp_server", server)
    anunciada = getattr(interno, "version", None)

    assert anunciada == esperada, (
        f"el handshake MCP anuncia {anunciada!r} en vez de la versión de InferBench "
        f"({esperada!r}); el usuario lo ve en su cliente MCP"
    )
    assert not str(anunciada).startswith("1."), "eso es la versión del SDK de mcp"
