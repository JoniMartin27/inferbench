"""Entry point del backend FastAPI de InferBench."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.hardware import router as hardware_router
from api.engines import router as engines_router
from api.models import router as models_router
from api.benchmark import router as benchmark_router
from api.history import router as history_router
from api.optimize import router as optimize_router
from db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="InferBench Backend", version="0.1.0", lifespan=lifespan)

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
    if host and _hostname(host) not in _ALLOWED_HOSTS:
        return JSONResponse(
            status_code=403,
            content={"detail": "Host no permitido. La API de InferBench solo acepta loopback."},
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "app://."],  # Vite dev + Electron
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    from core.docker_mgr import availability
    return {"status": "ok", "version": "0.1.0", "docker": availability()}


app.include_router(hardware_router)
app.include_router(engines_router)
app.include_router(models_router)
app.include_router(benchmark_router)
app.include_router(history_router)
app.include_router(optimize_router)


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting InferBench backend on http://localhost:7777")
    uvicorn.run("main:app", host="127.0.0.1", port=7777, reload=True)
