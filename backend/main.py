"""Entry point del backend FastAPI de InferBench."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from api.hardware import router as hardware_router
from api.engines import router as engines_router
from api.models import router as models_router
from api.benchmark import router as benchmark_router
from api.history import router as history_router
from api.optimize import router as optimize_router
from db import init_db

app = FastAPI(title="InferBench Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "app://."],  # Vite dev + Electron
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


app.include_router(hardware_router)
app.include_router(engines_router)
app.include_router(models_router)
app.include_router(benchmark_router)
app.include_router(history_router)
app.include_router(optimize_router)


@app.on_event("startup")
async def _startup() -> None:
    init_db()

# TODO M3: models router
# TODO M4: benchmark + history routers


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting InferBench backend on http://localhost:7777")
    uvicorn.run("main:app", host="127.0.0.1", port=7777, reload=True)
