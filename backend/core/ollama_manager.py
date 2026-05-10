"""Gestión del runtime nativo de Ollama: detección, daemon, pull, listado."""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from loguru import logger

OLLAMA_PORT = 11434
OLLAMA_BASE_URL = f"http://localhost:{OLLAMA_PORT}"
OLLAMA_INSTALLER_URL_WIN = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_INSTALLER_URL_MAC = "https://ollama.com/download/Ollama-darwin.zip"

ProgressCb = Callable[[dict], Awaitable[None]] | None


def find_ollama_exe() -> Path | None:
    """Busca el binario `ollama` en PATH o en ubicaciones típicas."""
    in_path = shutil.which("ollama")
    if in_path:
        return Path(in_path)

    candidates: list[Path] = []
    if os.name == "nt":
        for env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Ollama" / "ollama.exe")
                candidates.append(Path(base) / "Programs" / "Ollama" / "ollama.exe")
    elif platform.system() == "Darwin":
        candidates += [
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            Path.home() / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama",
        ]
    else:  # Linux
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]

    for c in candidates:
        if c.exists():
            return c
    return None


def is_installed() -> bool:
    return find_ollama_exe() is not None


async def is_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/version")
            return r.status_code == 200
    except Exception:
        return False


async def version() -> dict:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/version")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e)}


async def list_local_models() -> list[dict]:
    """Modelos ya descargados por Ollama (vía /api/tags)."""
    if not await is_running():
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            return r.json().get("models", [])
    except Exception as e:
        logger.warning(f"Ollama list failed: {e}")
        return []


async def pull_model(tag: str, progress: ProgressCb = None) -> None:
    """Pull con stream de progreso."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": tag, "stream": True},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # evt típico: {"status": "downloading", "digest":..., "total":..., "completed":...}
                if progress:
                    pct = None
                    total = evt.get("total")
                    completed = evt.get("completed")
                    if total and completed:
                        pct = round(completed / total * 100, 1)
                    await progress(
                        {
                            "phase": evt.get("status", "pull"),
                            "name": tag,
                            "downloaded": completed or 0,
                            "size": total or 0,
                            "pct": pct or 0,
                        }
                    )


async def has_model(tag: str) -> bool:
    models = await list_local_models()
    target = tag.split(":")[0]
    target_full = tag if ":" in tag else f"{tag}:latest"
    return any(
        m.get("name") == target_full or m.get("name", "").split(":")[0] == target
        for m in models
    )


def start_daemon() -> int:
    """Arranca `ollama serve` en background. Devuelve PID."""
    import subprocess

    exe = find_ollama_exe()
    if not exe:
        raise RuntimeError("Ollama no instalado")

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000  # CREATE_NO_WINDOW
        )

    proc = subprocess.Popen(
        [str(exe), "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return proc.pid


async def ensure_running(timeout: float = 30.0) -> None:
    """Si Ollama no responde, intenta arrancar el daemon y esperar."""
    if await is_running():
        return
    if not is_installed():
        raise RuntimeError(
            "Ollama no instalado. Descárgalo desde https://ollama.com/download"
        )
    logger.info("Arrancando Ollama daemon…")
    start_daemon()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await is_running():
            return
        await asyncio.sleep(1)
    raise RuntimeError(f"Ollama no respondió tras {timeout}s")


def installer_url() -> str | None:
    if os.name == "nt":
        return OLLAMA_INSTALLER_URL_WIN
    if platform.system() == "Darwin":
        return OLLAMA_INSTALLER_URL_MAC
    return None  # Linux: usar curl install script
