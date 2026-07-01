"""Runtime nativo: arranca motores como subprocess en lugar de contenedores Docker."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import IO, Optional

from loguru import logger
from pydantic import BaseModel


# Reutilizamos el mismo schema de ContainerStatus para uniformidad con docker_mgr
class ProcessStatus(BaseModel):
    name: str
    state: str  # running | exited | missing
    image: Optional[str] = None  # ruta del binario
    ports: dict = {}
    container_id: Optional[str] = None  # reusamos como pid (string)
    pid: Optional[int] = None


_PROCS: dict[str, subprocess.Popen] = {}
_LOG_FILES: dict[str, Path] = {}
_LOG_FDS: dict[str, "IO"] = {}  # file handles abiertos — cerrados en stop() para evitar fugas
_LOADED: dict[str, dict] = {}  # engine_id → {model, quant, ...} actualmente servido


def set_loaded(engine_id: str, info: dict | None) -> None:
    if info is None:
        _LOADED.pop(engine_id, None)
    else:
        _LOADED[engine_id] = info


def get_loaded(engine_id: str) -> dict | None:
    return _LOADED.get(engine_id)


def _log_dir() -> Path:
    base = (
        Path(os.environ["APPDATA"]) / "InferBench" / "logs"
        if os.name == "nt" and "APPDATA" in os.environ
        else Path.home() / ".inferbench" / "logs"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def status(engine_id: str) -> ProcessStatus:
    proc = _PROCS.get(engine_id)
    name = f"native-{engine_id}"
    if proc is None:
        return ProcessStatus(name=name, state="missing")
    rc = proc.poll()
    if rc is None:
        return ProcessStatus(name=name, state="running", pid=proc.pid, container_id=str(proc.pid))
    # Proceso murió por su cuenta (crash/OOM-kill), no vía stop(): limpiar también
    # _LOADED para que get_loaded() no reporte un modelo "cargado" que ya no corre.
    _PROCS.pop(engine_id, None)
    _LOADED.pop(engine_id, None)
    return ProcessStatus(name=name, state="exited", pid=proc.pid)


def start(
    engine_id: str,
    *,
    exe: Path,
    args: list[str],
    env: dict[str, str] | None = None,
    port: int | None = None,
) -> ProcessStatus:
    stop(engine_id)
    full_env = {**os.environ, **(env or {})}
    log_path = _log_dir() / f"{engine_id}.log"
    _LOG_FILES[engine_id] = log_path
    log_fd = open(log_path, "ab", buffering=0)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    logger.info(f"native start [{engine_id}]: {exe} {' '.join(str(a) for a in args)}")
    try:
        proc = subprocess.Popen(
            [str(exe), *args],
            env=full_env,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            cwd=str(exe.parent),
        )
    except Exception:
        # Popen falló: no dejar el fd abierto ni una entrada de _LOG_FILES apuntando a
        # un intento que nunca llegó a tener proceso (_PROCS/_LOG_FDS nunca se poblaron).
        log_fd.close()
        _LOG_FILES.pop(engine_id, None)
        raise
    _LOG_FDS[engine_id] = log_fd
    _PROCS[engine_id] = proc
    st = status(engine_id)
    st.image = str(exe)
    if port:
        st.ports = {f"{port}/tcp": [{"HostPort": str(port)}]}
    return st


def stop(engine_id: str) -> ProcessStatus:
    proc = _PROCS.pop(engine_id, None)
    _LOADED.pop(engine_id, None)
    # Cerrar el descriptor del log para no acumular handles en reinicios repetidos
    fd = _LOG_FDS.pop(engine_id, None)
    if fd is not None:
        try:
            fd.close()
        except Exception:
            pass
    if proc and proc.poll() is None:
        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
    return ProcessStatus(name=f"native-{engine_id}", state="missing")


def logs(engine_id: str, tail: int = 200) -> str:
    path = _LOG_FILES.get(engine_id)
    if not path or not path.exists():
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 65536)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return "\n".join(lines[-tail:])
    except OSError:
        return ""
