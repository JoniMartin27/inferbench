"""Entry point del backend FastAPI de InferBench."""

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.hardware import router as hardware_router
from api.engines import router as engines_router
from api.models import router as models_router
from api.benchmark import router as benchmark_router
from api.history import router as history_router
from api.keys import router as keys_router
from api.optimize import router as optimize_router
from api.serve import router as serve_router
from db import init_db


@asynccontextmanager
async def lifespan(app_: FastAPI):
    init_db()
    # El transporte HTTP de MCP (montado bajo /mcp) necesita que su gestor de sesiones
    # corra durante la vida de la app. Starlette no ejecuta el lifespan de sub-apps
    # montadas, así que lo encadenamos aquí. Si `mcp` no está instalado, seguimos sin MCP
    # HTTP (el resto del backend funciona igual; el stdio se lanza por --mcp aparte).
    try:
        import mcp_server

        async with mcp_server.session_manager_lifespan():
            yield
        return
    except ModuleNotFoundError:
        logger.warning("Paquete 'mcp' no instalado: /mcp (HTTP) deshabilitado.")
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo arrancar el transporte MCP HTTP; sigo sin él.")
    yield


try:
    __version__ = _pkg_version("inferbench-backend")
except PackageNotFoundError:  # ejecutado sin instalar el paquete (raro)
    __version__ = "0.0.0+dev"

app = FastAPI(title="InferBench Backend", version=__version__, lifespan=lifespan)

# Hosts loopback permitidos. La API local puede descargar y ejecutar binarios, así que
# la protegemos contra DNS-rebinding: un sitio malicioso que rebinde su dominio a
# 127.0.0.1 enviaría su propio dominio en la cabecera Host; solo aceptamos loopback.
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def _hostname(host_header: str) -> str:
    h = host_header.lower().strip()
    if h.startswith("["):  # IPv6 con corchetes, ej. [::1]:7777
        return h[1:].split("]", 1)[0]
    return h.split(":", 1)[0]


@app.middleware("http")
async def _block_dns_rebinding(request: Request, call_next):
    host = request.headers.get("host")
    if not host or _hostname(host) not in _ALLOWED_HOSTS:
        return JSONResponse(
            status_code=403,
            content={"detail": "Host no permitido. La API de InferBench solo acepta loopback."},
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "app://.",
    ],  # Vite dev + Electron
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    from core.docker_mgr import availability

    return {"status": "ok", "version": __version__, "docker": availability()}


app.include_router(hardware_router)
app.include_router(engines_router)
app.include_router(models_router)
app.include_router(benchmark_router)
app.include_router(history_router)
app.include_router(keys_router)
app.include_router(optimize_router)
app.include_router(serve_router)


# Servidor MCP por HTTP (streamable). Cualquier cliente MCP (Claude Desktop/Cursor) puede
# hablar con InferBench en http://localhost:7777/mcp. Las tools del server hacen proxy a
# estos mismos endpoints REST. El gestor de sesiones se arranca en el lifespan de arriba.
# Si `mcp` no está instalado, omitimos el mount (el resto del backend no se ve afectado).
try:
    import mcp_server

    app.mount("/mcp", mcp_server.http_app())
except ModuleNotFoundError:
    logger.warning("Paquete 'mcp' no instalado: no se monta /mcp.")
except Exception:  # noqa: BLE001
    logger.exception("No se pudo montar el transporte MCP HTTP.")


if __name__ == "__main__":
    import os
    import sys

    # Modo MCP stdio: `inferbench-backend.exe --mcp`. Claude Desktop / Cursor lanzan el
    # exe con esta flag y hablan MCP por stdin/stdout. El server MCP NO arranca su propio
    # motor: solo hace de proxy hacia el backend HTTP (que debe estar abierto). Por eso
    # NO levantamos uvicorn aquí — solo el bucle MCP por stdio.
    if "--mcp" in sys.argv:
        import mcp_server

        logger.info("Starting InferBench MCP server (stdio transport)")
        mcp_server.run_stdio()
        sys.exit(0)

    import uvicorn

    # Congelado por PyInstaller (sidecar de Electron): SIN reload. El reloader de uvicorn
    # re-ejecutaría el exe en bucle infinito (fork-bomb) y nunca llegaría a servir.
    frozen = getattr(sys, "frozen", False)
    port = int(os.environ.get("INFERBENCH_PORT", "7777"))
    logger.info(f"Starting InferBench backend on http://127.0.0.1:{port} (frozen={frozen})")
    if frozen:
        uvicorn.run(app, host="127.0.0.1", port=port)
    else:
        uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True)
