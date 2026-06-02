#!/usr/bin/env python
"""Driver para arrancar y CONDUCIR el backend de InferBench (FastAPI :7777).

Es el handle programatico del backend + orquestacion de motores: gestiona el
ciclo de vida de uvicorn, hace smoke de los endpoints clave y (con --benchmark)
conduce un benchmark REAL por HTTP+SSE — el mismo camino que usa el frontend
Electron — exigiendo tokens reales (sin falsos positivos).

Uso (desde inferbench/, con el venv del backend ya creado):
    python .claude/skills/run-inferbench-backend/driver.py            # smoke
    python .claude/skills/run-inferbench-backend/driver.py --benchmark llamacpp:smollm2-360m
    python .claude/skills/run-inferbench-backend/driver.py --no-spawn  # backend ya corriendo

Salidas: 0 = OK, !=0 = fallo. Solo ASCII en stdout (consola Windows cp1252).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

PORT = 7777
BASE = f"http://127.0.0.1:{PORT}"
HERE = Path(__file__).resolve().parent
# inferbench/.claude/skills/run-inferbench-backend/driver.py -> inferbench/backend
BACKEND = HERE.parents[2] / "backend"


def _venv_python() -> Path:
    win = BACKEND / ".venv" / "Scripts" / "python.exe"
    nix = BACKEND / ".venv" / "bin" / "python"
    if win.exists():
        return win
    if nix.exists():
        return nix
    raise SystemExit(
        f"No hay venv en {BACKEND/'.venv'}. Crea: cd backend && uv venv --python 3.11 "
        f"&& uv pip install -e ."
    )


def _is_up() -> bool:
    try:
        return httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200
    except Exception:
        return False


def spawn_backend() -> subprocess.Popen:
    py = _venv_python()
    print(f"[spawn] {py} -m uvicorn main:app --port {PORT}  (cwd={BACKEND})")
    log = open(BACKEND / "_driver_uvicorn.log", "wb", buffering=0)
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "main:app", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=str(BACKEND),
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc


def wait_health(timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_up():
            print("[health] backend listo")
            return
        time.sleep(1)
    raise SystemExit(f"[health] backend no respondio en {timeout}s (ver _driver_uvicorn.log)")


def smoke() -> None:
    with httpx.Client(base_url=BASE, timeout=20) as c:
        h = c.get("/api/health").json()
        print(f"[health] {h}")
        hw = c.get("/api/hardware").json()
        cpu = (hw.get("cpu") or {}).get("name", "?")
        gpu = (hw.get("gpus") or [{}])[0].get("name", "—")
        print(f"[hardware] CPU={cpu} RAM={hw.get('ram_gb')}GB GPU={gpu}")
        engines = c.get("/api/engines").json()
        local = [e["meta"]["id"] for e in engines if e["meta"].get("type") == "local"]
        api = [e["meta"]["id"] for e in engines if e["meta"].get("type") == "api"]
        print(f"[engines] local={local}  api={api}")
        assert len(engines) >= 5, f"esperaba >=5 motores, hay {len(engines)}"
        models = c.get("/api/models").json()
        print(f"[models] catalogo={len(models)} modelos")
        assert len(models) > 50, "catalogo sospechosamente pequeno"
    print("[smoke] OK")


def run_benchmark(engine: str, model: str, quant: str = "Q4_K_M") -> None:
    body = {
        "engine": engine,
        "model": model,
        "quant": quant,
        "prompts": ["chat"],
        "auto": True,
        "keep_alive": False,
    }
    print(f"[bench] POST /api/benchmark/run  {engine}:{model}")
    with httpx.Client(base_url=BASE, timeout=30) as c:
        run_id = c.post("/api/benchmark/run", json=body).json()["run_id"]
    print(f"[bench] run_id={run_id}  conectando al stream SSE...")

    result = None
    fatal = None
    # El bootstrap puede tardar (descarga binario/modelo, arranque motor)
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(900)) as c:
        with c.stream("GET", f"/api/benchmark/{run_id}/stream") as resp:
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    continue
                t = evt.get("type")
                if t == "log" and evt.get("level") in ("error", "warn"):
                    print(f"   [{evt['level']}] {evt.get('text','')[:140]}")
                elif t == "result":
                    result = evt["result"]
                elif t == "done":
                    if evt.get("error"):
                        fatal = evt["error"]
                    break

    if fatal:
        raise SystemExit(f"[bench] FALLO: {fatal}")
    if not result:
        raise SystemExit("[bench] FALLO: no se recibio ningun resultado")
    out = (result.get("raw_output") or "").strip()
    tps = result.get("tps", 0)
    print(f"[bench] tps={tps} ttft_ms={result.get('ttft_ms')} "
          f"vram_gb={result.get('vram_gb')} quality={result.get('quality')}")
    print(f"[bench] output[:80]={out[:80]!r}")
    if not (tps > 0 and out and not result.get("error")):
        raise SystemExit("[bench] FALLO: resultado sin inferencia real (falso positivo)")
    print("[bench] OK (inferencia real verificada)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", metavar="ENGINE:MODEL",
                    help="corre un benchmark real, p.ej. llamacpp:smollm2-360m")
    ap.add_argument("--quant", default="Q4_K_M")
    ap.add_argument("--no-spawn", action="store_true",
                    help="asume backend ya corriendo en :7777")
    args = ap.parse_args()

    proc = None
    try:
        if _is_up():
            print(f"[init] backend ya corriendo en :{PORT}, reusando")
        elif args.no_spawn:
            raise SystemExit(f"[init] --no-spawn pero nada responde en :{PORT}")
        else:
            proc = spawn_backend()
            wait_health()

        smoke()
        if args.benchmark:
            eng, _, mdl = args.benchmark.partition(":")
            if not mdl:
                raise SystemExit("formato --benchmark ENGINE:MODEL")
            run_benchmark(eng, mdl, args.quant)
        print("\n=== DRIVER OK ===")
    finally:
        if proc is not None:
            print("[shutdown] parando backend")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
