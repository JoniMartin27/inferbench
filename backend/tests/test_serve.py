"""Tests del modo Serve / MCP (sin motor real).

Cubren el CONTRATO HTTP de /api/serve y la serialización del estado del slot, además
del manejo de errores del server MCP cuando el backend no está accesible. NO arrancan
ningún subprocess de llama.cpp: validan request, fases y forma de la respuesta.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core import serve as serve_core
from main import app

client = TestClient(app)

# Claves obligatorias del estado del slot según el contrato.
_STATUS_KEYS = {
    "served",
    "model_id",
    "engine",
    "quant",
    "context",
    "modality",
    "endpoint",
    "phase",
    "progress",
    "message",
}


@pytest.fixture(autouse=True)
def _reset_manager():
    """Cada test arranca con un slot limpio (idle) y lo deja limpio al salir."""
    mgr = serve_core.get_manager()
    mgr.model_id = None
    mgr.engine = None
    mgr.quant = None
    mgr.context = None
    mgr.modality = "text"
    mgr.phase = "idle"
    mgr.progress = None
    mgr.message = "Sin modelo servido."
    mgr._task = None
    yield
    mgr.phase = "idle"
    mgr.modality = "text"
    mgr.model_id = None
    mgr.engine = None


def test_status_idle_at_start():
    r = client.get("/api/serve/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == _STATUS_KEYS
    assert body["served"] is False
    assert body["phase"] == "idle"
    assert body["model_id"] is None
    assert body["engine"] is None
    assert body["endpoint"] is None


def test_status_serializes_full_contract():
    """Todos los campos del contrato tienen el tipo correcto cuando hay un modelo cargado."""
    mgr = serve_core.get_manager()
    mgr.model_id = "qwen2.5-7b"
    mgr.engine = "llamacpp"
    mgr.quant = "Q4_K_M"
    mgr.context = 8192
    mgr.phase = "ready"
    mgr.progress = 100.0
    mgr.message = "ok"
    # status_dict comprueba que el proceso está vivo; sin motor real → degrada a 'error'.
    body = mgr.status_dict()
    assert set(body) == _STATUS_KEYS
    # El motor no corre de verdad → la fase ready se degrada a error (honesto, no finge).
    assert body["phase"] == "error"
    assert body["served"] is False
    assert body["model_id"] == "qwen2.5-7b"
    assert body["engine"] == "llamacpp"
    assert body["quant"] == "Q4_K_M"
    assert body["context"] == 8192


def test_load_rejects_unknown_model():
    r = client.post("/api/serve/load", json={"model_id": "no-existe-xyz"})
    assert r.status_code == 404
    assert (
        "no-existe-xyz" in r.json()["detail"].lower() or "desconocido" in r.json()["detail"].lower()
    )


def test_load_rejects_unsupported_engine():
    r = client.post("/api/serve/load", json={"model_id": "whatever", "engine": "vllm"})
    assert r.status_code == 400
    assert "vllm" in r.json()["detail"].lower()


def test_chat_without_model_returns_409():
    r = client.post("/api/serve/chat", json={"prompt": "hola"})
    assert r.status_code == 409
    assert "modelo" in r.json()["detail"].lower()


def test_chat_prompt_shortcut_and_messages_required():
    # Sin prompt ni messages → 400 (request inválido), distinto del 409 de "sin modelo".
    r = client.post("/api/serve/chat", json={})
    assert r.status_code == 400


def test_unload_is_idempotent_and_returns_idle():
    r = client.post("/api/serve/unload")
    assert r.status_code == 200
    body = r.json()
    assert body["served"] is False
    assert body["phase"] == "idle"
    assert "message" in body


@pytest.mark.anyio
async def test_chat_raises_serve_error_when_not_ready():
    mgr = serve_core.get_manager()
    with pytest.raises(serve_core.ServeError) as exc:
        await mgr.chat([{"role": "user", "content": "hi"}])
    assert exc.value.status_code == 409


def test_engine_endpoint_helper():
    assert serve_core.engine_endpoint("llamacpp") == "http://127.0.0.1:8080"
    # endpoint del slot es None mientras está idle
    assert serve_core.get_manager().endpoint is None


def test_load_validates_model_without_gguf_source(monkeypatch):
    """Un modelo del catálogo sin fuente GGUF no es auto-descargable → 400 claro."""
    from core.models_catalog import Model

    fake = Model(
        id="fake-no-gguf",
        name="Fake",
        family="fake",
        params_b=1.0,
        active_b=1.0,
        is_moe=False,
        size_base_gb=2.0,
        max_ctx=4096,
        hf_gguf=None,
    )
    monkeypatch.setattr(
        serve_core, "get_model", lambda mid: fake if mid == "fake-no-gguf" else None
    )
    r = client.post("/api/serve/load", json={"model_id": "fake-no-gguf"})
    assert r.status_code == 400
    assert "gguf" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_load_cancels_orphaned_pending_task():
    """Regresión: una load() mientras otra sigue 'downloading' no debe dejar la tarea
    anterior huérfana corriendo en background (issue real: sustituía self._task sin
    cancelar la previa, que podía arrancar su motor DESPUÉS de la nueva)."""
    import asyncio

    mgr = serve_core.get_manager()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _never_finishes():
        try:
            started.set()
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    mgr.phase = "downloading"
    mgr._task = asyncio.create_task(_never_finishes())
    await asyncio.wait_for(started.wait(), timeout=5)
    assert not mgr._task.done()

    await mgr._cancel_pending_task()

    await asyncio.wait_for(cancelled.wait(), timeout=5)
    assert mgr._task.done()
    assert mgr._task.cancelled()


@pytest.mark.anyio
async def test_load_does_not_reuse_when_context_differs(monkeypatch):
    """Regresión: si el modelo/engine/quant ya están 'ready' pero el caller pide un
    `context` explícito distinto del servido, load() NO debe reusar el motor viejo en
    silencio — debe relanzar la carga para honrar el nuevo context."""
    import asyncio

    mgr = serve_core.get_manager()
    mgr.model_id = "smollm2-360m"
    mgr.engine = "llamacpp"
    mgr.quant = "Q4_K_M"
    mgr.context = 4096
    mgr.phase = "ready"
    monkeypatch.setattr(mgr, "_engine_running", lambda: True)

    # Evita tocar de verdad binarios/red: _run_load se sustituye por un no-op que no
    # completa (basta con comprobar que load() intentó relanzar, no que termine).
    async def _fake_run_load(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(mgr, "_run_load", _fake_run_load)

    # Mismo quant explícito, pero context distinto del ya servido (4096) → no reusa.
    result = await mgr.load("smollm2-360m", engine="llamacpp", quant="Q4_K_M", context=8192)

    assert result["phase"] == "downloading"
    assert mgr.context == 8192
    # Limpieza: cancela la tarea en background para no dejarla huérfana entre tests.
    await mgr._cancel_pending_task()


@pytest.mark.anyio
async def test_load_reuses_when_context_matches_or_unset(monkeypatch):
    """Mismo escenario pero sin pedir context (o pidiendo el mismo ya servido): sigue
    reusando el motor sin relanzar, como antes."""
    mgr = serve_core.get_manager()
    mgr.model_id = "smollm2-360m"
    mgr.engine = "llamacpp"
    mgr.quant = "Q4_K_M"
    mgr.context = 4096
    mgr.phase = "ready"
    monkeypatch.setattr(mgr, "_engine_running", lambda: True)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("_run_load no debería llamarse cuando se reusa el motor")

    monkeypatch.setattr(mgr, "_run_load", _fail_if_called)

    result = await mgr.load("smollm2-360m", engine="llamacpp", quant="Q4_K_M")
    assert result["phase"] == "ready"

    result2 = await mgr.load("smollm2-360m", engine="llamacpp", quant="Q4_K_M", context=4096)
    assert result2["phase"] == "ready"
