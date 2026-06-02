---
name: run-inferbench-backend
description: Build, launch, smoke-test and drive the InferBench FastAPI backend (:7777) and its inference-engine orchestration. Use when asked to run, start, launch, boot, smoke-test, benchmark, or drive the inferbench backend / API / engines (llama.cpp, ollama, vLLM, SGLang, TGI), or to verify an engine actually starts and runs a model.
---

# Run InferBench backend + engines

InferBench's backend is a Python 3.11 **FastAPI** app on `:7777` that orchestrates
local inference engines (downloads binaries/GGUFs, starts engines natively or via
Docker, benchmarks them, persists to SQLite). The Electron frontend is just a REST/SSE
client of it. This skill drives the backend **programmatically** via
[`driver.py`](driver.py), which manages the uvicorn lifecycle, smoke-tests the key
endpoints, and runs a **real benchmark over the production HTTP+SSE path** — asserting
real tokens, no false positives.

All paths below are relative to the `inferbench/` project root. Environment verified:
**Windows 11**, Docker Desktop 29.4.2, NVIDIA RTX 3070.

## Prerequisites

The backend needs its uv venv (Python 3.11). If `backend/.venv/` is missing:

```bash
cd backend && uv venv --python 3.11 && uv pip install -e ".[dev]"
```

The driver imports `httpx`, so it **must run with the backend venv's Python**
(`backend/.venv/Scripts/python.exe` on Windows). Engines also need, on demand:
Docker Desktop running + an NVIDIA GPU for `vllm`/`sglang`/`tgi`; nothing extra for
`llamacpp` (downloads the official binary) or `ollama` (needs Ollama installed).

## Run (agent path) — this is the primary path

Smoke test (spawns uvicorn, checks health/hardware/engines/models, shuts down):

```bash
backend/.venv/Scripts/python.exe ".claude/skills/run-inferbench-backend/driver.py"
```

Full drive — smoke **plus** a real end-to-end benchmark through `POST /api/benchmark/run`
+ the SSE stream (auto-bootstrap → engine start → inference → result). `llamacpp` +
the smallest catalog model is the fastest honest check (~370 tps on the RTX 3070):

```bash
backend/.venv/Scripts/python.exe ".claude/skills/run-inferbench-backend/driver.py" --benchmark llamacpp:smollm2-360m
```

Other verified engines (each starts a real container/daemon and runs a model — slower,
need Docker+GPU / Ollama): `vllm:qwen2.5-0.5b`, `sglang:qwen2.5-0.5b`, `tgi:qwen2.5-0.5b`,
`ollama:smollm2-360m`.

If a backend is already listening on `:7777`, the driver **reuses it** (and does not
shut it down). To attach to an already-running backend without spawning: add `--no-spawn`.

Expected tail of a successful full run:

```
[engines] local=['llamacpp', 'ollama', 'vllm', 'sglang', 'tgi']  api=['openai', 'anthropic', 'openrouter', 'nvidia']
[bench] tps=370.21 ttft_ms=455 vram_gb=3.12 quality=70.0
[bench] OK (inferencia real verificada)
=== DRIVER OK ===
```

## Direct invocation (no HTTP) — for PRs touching engine internals

Most engine work changes `core/benchmark.py` (the runner) or `engines/*.py` (adapters).
Drive the runner in-process, bypassing FastAPI — exercises the exact bootstrap/start/
infer/stop path and asserts real tokens:

```bash
cd backend && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import asyncio
from core.benchmark import BenchmarkRequest, BenchmarkRunner
async def main():
    r = BenchmarkRunner(BenchmarkRequest(engine='llamacpp', model='smollm2-360m',
        prompts=['chat'], auto=True, keep_alive=False))
    t = asyncio.create_task(r.run())
    res, fatal = [], None
    while True:
        e = await r.queue.get()
        if e.get('type') == '_eof': break
        if e.get('type') == 'result': res.append(e['result'])
        if e.get('type') == 'done' and e.get('error'): fatal = e['error']
    await t
    assert not fatal and res and res[0]['tps'] > 0 and res[0]['raw_output'].strip(), fatal
    print('OK tps=', res[0]['tps'])
asyncio.run(main())
"
```

A single Docker engine adapter can also be driven directly via the registry
(`registry.get_engine('vllm').start(StartRequest(...))` → poll `/v1/models` → stop);
the runner path above is preferred because it also covers model resolution + scoring.

## Run (human path)

`npm run dev` (from root) launches backend + Electron frontend via concurrently; backend
alone is `cd backend && uvicorn main:app --reload --port 7777`. Useless for headless
verification — no programmatic handle. Use the driver instead.

## Gotchas (verified this session)

- **Wrong interpreter = instant failure.** There is **no** `.venv` at the project root —
  only `backend/.venv`. Running the driver with `python` or a root venv fails (`No such
  file` / missing `httpx`). Always use `backend/.venv/Scripts/python.exe`.
- **`PYTHONIOENCODING=utf-8` on Windows.** Model output is non-ASCII; without it the
  Windows console (cp1252) can raise `UnicodeEncodeError`. The driver prints `repr()[:80]`
  to stay safe, but set the env var for any extension.
- **API JSON shape is nested.** `GET /api/engines` returns `{meta:{id,type,...},status:{...}}`
  — engine id/type live under `["meta"]`. Hardware CPU is under `hw["cpu"]["name"]`,
  GPUs under `hw["gpus"]`. Relevant if you extend the driver.
- **vLLM/SGLang refuse to start on a non-empty GPU by default.** They pre-allocate ~0.9
  of *total* VRAM; the runner now derives the fraction from *free* VRAM and clamps any
  user/optimizer value down to fit (`core/benchmark.py::_gpu_mem_fraction`). On an 8 GB
  card with ~1 GB in use this is why a run succeeds where a raw `vllm serve` would OOM.
- **First benchmark per engine is slow.** It downloads the binary/GGUF (llamacpp) or pulls
  the Docker image / HF model (others) into `%APPDATA%\InferBench\`. Cached after.
- **The driver only stops backends it spawned.** A pre-existing `:7777` (e.g. from
  `npm run dev`, which uses `--reload`) is reused and left running.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No hay venv en .../backend/.venv` | `cd backend && uv venv --python 3.11 && uv pip install -e ".[dev]"` |
| `[health] backend no respondio en 60s` | Read `backend/_driver_uvicorn.log` — usually an import error or port in use. |
| `[bench] FALLO: ... no se recibio ningun resultado` / falso positivo | Engine couldn't produce tokens — check `GET /api/engines/{id}/logs` and Docker/GPU availability. |
| Docker engine hangs on "Esperando motor listo" | Docker Desktop down, or the HF model download inside the container is large. `vllm`/`tgi`/`sglang` need Docker + NVIDIA GPU. |
