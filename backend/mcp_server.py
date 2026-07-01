"""Servidor MCP "inferbench" (SDK oficial `mcp` / FastMCP).

Todas las tools son FINAS: hacen proxy vía httpx al backend REST de InferBench
(INFERBENCH_BACKEND_URL, default http://127.0.0.1:7777). Así hay UNA sola
implementación y un único proceso —el backend FastAPI— gestiona el motor.

Dos transportes comparten esta misma definición de tools:
  - HTTP: main.py monta `streamable_http_app()` bajo /mcp.
  - stdio: `inferbench-backend.exe --mcp` ejecuta `run_stdio()` (Claude Desktop / Cursor).
    El stdio NO arranca su propio motor: solo hace proxy al backend, que debe estar abierto.

El SDK `mcp` se importa de forma PEREZOSA dentro de _build_server() para que importar
este módulo (y main.py) no falle si la dependencia aún no está instalada.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

SERVER_NAME = "inferbench"
DEFAULT_TIMEOUT = httpx.Timeout(360.0, connect=10.0)

# Mensaje claro cuando el backend no está accesible (stdio lanzado sin la app abierta).
_BACKEND_DOWN = (
    "InferBench no está abierto: arranca la app InferBench y reintenta "
    "(el servidor MCP solo hace de proxy hacia el backend en :7777)."
)


def backend_url() -> str:
    return os.environ.get("INFERBENCH_BACKEND_URL", "http://127.0.0.1:7777").rstrip("/")


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{backend_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError as e:
        raise RuntimeError(_BACKEND_DOWN) from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"InferBench devolvió HTTP {e.response.status_code}: {e.response.text[:300]}"
        ) from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"Error contactando InferBench: {e}") from e


async def _post(path: str, body: dict[str, Any] | None = None) -> Any:
    url = f"{backend_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.post(url, json=body or {})
            # 409/4xx llevan un mensaje útil del backend → propágalo legible.
            if r.status_code >= 400:
                detail = ""
                try:
                    payload = r.json()
                    detail = payload.get("detail") or payload.get("message") or ""
                except Exception:  # noqa: BLE001
                    detail = r.text[:300]
                raise RuntimeError(f"InferBench HTTP {r.status_code}: {detail}")
            return r.json()
    except httpx.ConnectError as e:
        raise RuntimeError(_BACKEND_DOWN) from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"Error contactando InferBench: {e}") from e


def _build_server():
    """Construye el FastMCP con todas las tools. Importa `mcp` de forma perezosa."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    # El transporte HTTP de MCP trae su PROPIA defensa anti-DNS-rebinding (igual que el
    # middleware del backend): solo acepta Host/Origin loopback. Añadimos el origen
    # `app://` de Electron para que el handshake desde la app empaquetada no se bloquee.
    # Con streamable_http_path="/" el sub-app se monta limpio bajo /mcp en main.py.
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "127.0.0.1", "localhost"],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "app://.",
            "app://*",
        ],
    )
    mcp = FastMCP(
        SERVER_NAME,
        streamable_http_path="/",
        transport_security=transport_security,
    )

    @mcp.tool()
    async def list_models() -> list[dict[str, Any]]:
        """Lista el catálogo de modelos de InferBench (resumen: id, name, params_b, family)."""
        models = await _get("/api/models")
        return [
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "params_b": m.get("params_b"),
                "family": m.get("family"),
            }
            for m in models
        ]

    @mcp.tool()
    async def recommend_models(limit: int = 5) -> list[dict[str, Any]]:
        """Top modelos ejecutables en el hardware actual (ordenados por compatibilidad)."""
        rows = await _get("/api/optimize/recommendations", params={"top": limit})
        out = []
        for r in rows[:limit]:
            model = r.get("model", {})
            cfg = r.get("config", {})
            out.append(
                {
                    "id": model.get("id"),
                    "name": model.get("name"),
                    "params_b": model.get("params_b"),
                    "best_quant": cfg.get("quant"),
                    "status": cfg.get("status"),
                    "context_len": cfg.get("context_len"),
                    "engine": cfg.get("engine"),
                }
            )
        return out

    @mcp.tool()
    async def get_hardware() -> dict[str, Any]:
        """Hardware detectado (CPU/RAM/GPU/VRAM) para elegir modelo y cuantización."""
        return await _get("/api/hardware")

    @mcp.tool()
    async def serve_model(
        model_id: str, quant: str | None = None, engine: str = "llamacpp"
    ) -> dict[str, Any]:
        """Empieza a servir un modelo de forma residente y ESPERA hasta que esté listo.

        Lanza /api/serve/load y hace polling de /api/serve/status cada ~2s hasta phase
        'ready'/'error' o timeout (~300s). Devuelve el estado final (incluye endpoint
        OpenAI y el quant elegido). InferBench elige el quant óptimo si `quant` es None.
        """
        await _post(
            "/api/serve/load",
            {"model_id": model_id, "engine": engine, "quant": quant},
        )
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 300.0
        last: dict[str, Any] = {}
        while loop.time() < deadline:
            last = await _get("/api/serve/status")
            if last.get("phase") in ("ready", "error", "idle"):
                return last
            await asyncio.sleep(2.0)
        return {**last, "message": "Timeout esperando a que el modelo quede listo (300s)."}

    @mcp.tool()
    async def serve_status() -> dict[str, Any]:
        """Estado del modelo actualmente servido (phase, endpoint, quant, context)."""
        return await _get("/api/serve/status")

    @mcp.tool()
    async def chat(prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        """Envía un prompt al modelo servido y devuelve el texto generado.

        Requiere un modelo en phase 'ready' (usa serve_model primero).
        """
        data = await _post(
            "/api/serve/chat",
            {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature},
        )
        return data.get("content", "")

    @mcp.tool()
    async def generate_image(
        prompt: str,
        steps: int = 20,
        width: int = 512,
        height: int = 512,
        seed: int = -1,
        negative_prompt: str = "",
    ):
        """Genera una imagen con el modelo de IMAGEN servido (stable-diffusion.cpp).

        Requiere un modelo modality='image' en phase 'ready' (sírvelo antes con serve_model,
        ej. 'sd-turbo' o 'flux.1-schnell-q4'). Devuelve la imagen para que el cliente la
        MUESTRE, más una línea de texto con seed y tiempo de generación.
        """
        from mcp.types import ImageContent, TextContent

        data = await _post(
            "/api/serve/generate",
            {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "steps": steps,
                "width": width,
                "height": height,
                "seed": seed,
            },
        )
        # El backend devuelve un data URL ("data:image/png;base64,<...>"); ImageContent
        # del SDK MCP quiere el base64 PELADO + mimeType aparte.
        image_b64 = data.get("image_b64", "") or ""
        if image_b64.startswith("data:"):
            header, _, payload = image_b64.partition(",")
            mime = "image/png"
            if ";" in header and ":" in header:
                mime = header.split(":", 1)[1].split(";", 1)[0] or "image/png"
            image_b64 = payload
        else:
            mime = "image/png"
        elapsed = data.get("elapsed_s")
        used_seed = data.get("seed")
        info = (
            f"Imagen generada con {data.get('model_id', '?')} "
            f"({data.get('width')}x{data.get('height')}, {data.get('steps')} steps, "
            f"seed {used_seed}, {elapsed}s)."
        )
        return [
            ImageContent(type="image", data=image_b64, mimeType=mime),
            TextContent(type="text", text=info),
        ]

    @mcp.tool()
    async def stop_model() -> dict[str, Any]:
        """Para el motor servido y libera la VRAM."""
        return await _post("/api/serve/unload")

    return mcp


# FastMCP se construye una sola vez (las tools son stateless: proxy puro al backend).
_SERVER = None


def get_server():
    """Devuelve (construyendo si hace falta) el FastMCP "inferbench"."""
    global _SERVER
    if _SERVER is None:
        _SERVER = _build_server()
    return _SERVER


def http_app():
    """ASGI app del transporte streamable-http (para montar bajo /mcp en FastAPI).

    OJO: este sub-app trae su propio lifespan (arranca el StreamableHTTPSessionManager).
    Starlette NO ejecuta el lifespan de un sub-app montado, así que main.py DEBE encadenar
    `session_manager_lifespan()` en el lifespan de la app FastAPI raíz. Si no, las
    peticiones a /mcp fallan con "Task group is not initialized".
    """
    return get_server().streamable_http_app()


def session_manager_lifespan():
    """Context manager async que arranca/para el gestor de sesiones HTTP de MCP.

    Pensado para encadenarse en el lifespan de la app FastAPI raíz:
        async with mcp_server.session_manager_lifespan():
            yield
    Llama primero a http_app() (crea el session manager de forma perezosa).
    """
    http_app()  # asegura que el session manager existe
    return get_server().session_manager.run()


def run_stdio() -> None:
    """Arranca el server MCP por stdio (Claude Desktop / Cursor lanzan el exe con --mcp)."""
    get_server().run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
