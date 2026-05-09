# InferBench

Panel de escritorio multiplataforma para **descargar, arrancar, medir y comparar** motores de inferencia LLM con un solo click. Sin Docker obligatorio, sin tocar la línea de comandos.

```
Eliges modelo + cuantizaciones → InferBench:
  ① descarga el binario del motor (release oficial GitHub)
  ② descarga los GGUF que falten desde Hugging Face
  ③ arranca el motor con la config óptima para tu hardware
  ④ ejecuta la suite de prompts midiendo TTFT, tok/s, VRAM, calidad
  ⑤ guarda los resultados y te deja compararlos lado a lado
```

---

## Features

- **Auto-bootstrap end-to-end**: 1 click → binario + modelo + arranque + benchmark + cleanup
- **Modo nativo (sin Docker)** para llama.cpp: descarga release pre-compilada de GitHub (auto-detecta CUDA, descarga también las DLLs del runtime)
- **Modo Docker** disponible para cualquier motor que lo requiera
- **Detección automática de hardware**: CPU, RAM, GPU (NVIDIA via NVML, AMD via rocm-smi, Apple Silicon via system_profiler)
- **Catálogo de 15 modelos** con auto-descarga GGUF desde HF (bartowski's repos)
- **Optimizador**: dado tu hardware + modelo + motor, calcula la mejor cuantización, KV-cache, contexto máximo, MoE offload, flags
- **Modo sweep**: lanza el mismo modelo con N cuantizaciones distintas en cola
- **Comparación**: selecciona varias runs del historial, ve métricas y gráficos lado a lado
- **SSE en vivo**: progreso de descargas (con %), TTFT, tok/s actual, log estilo terminal
- **Stop en cualquier momento**: cancela bootstrap, descarga o ejecución
- **Persistencia**: SQLite con todos los runs (engine, modelo, quant, flags, métricas por prompt, output bruto)

---

## Stack

| Capa | Tecnología |
|------|------------|
| App de escritorio | Electron 33 |
| Frontend | React 18 + Vite 5 + TailwindCSS + Recharts + lucide-react |
| Backend | FastAPI (Python 3.11) + uvicorn + sse-starlette |
| Persistencia | SQLite vía SQLModel |
| GPU detection | psutil + pynvml + system_profiler / rocm-smi |
| Containers | Docker SDK for Python |
| Native runtime | subprocess.Popen + binarios oficiales de GitHub |
| Empaquetado | electron-builder + PyInstaller |

---

## Motores soportados

| Motor | Tipo | Modo nativo | Modo Docker | Auto-descarga modelo |
|-------|------|-------------|-------------|----------------------|
| `llamacpp` | local | ✅ binarios oficiales | ✅ | ✅ HuggingFace GGUF |
| `ollama` | local | — | ⚠️ stub | — |
| `vllm` | local | — | ⚠️ stub | — |
| `sglang` | local | — | ⚠️ stub | — |
| `tgi` | local | — | ⚠️ stub | — |
| `openai` | API | n/a | n/a | n/a |
| `anthropic` | API | n/a | n/a | n/a |
| `openrouter` | API | n/a | n/a | n/a |
| `nvidia` | API | n/a | n/a | n/a |

> "Stub" = aparece en la lista pero no implementado todavía. Las APIs cloud funcionan con tu API key (sólo parámetros de sampling, sin optimización local).

---

## Optimizaciones aplicadas (llama.cpp)

Por defecto, basadas en `core/optimizer.py`:

- **Cuantización óptima**: itera de mayor a menor calidad (Q8 → Q2) hasta que cabe
- **Contexto máximo automático** según VRAM disponible y KV-cache
- **KV-cache compresión** (`-ctk -ctv`): f16 / q8_0 / q4_0
- **MoE offload** (`--n-cpu-moe N`) para modelos MoE en GPUs pequeñas
- **Flash Attention** (`-fa on`)
- **mlock** + **--no-mmap** cuando el modelo cabe entero en VRAM
- **Threads** = núcleos físicos
- **batch-size 2048** + **ubatch-size 512**
- Override total via `engine_opts` en el request

---

## Catálogo de modelos con auto-descarga

`backend/data/models.json` lista 15 modelos. Los que tienen `hf_gguf` configurado se descargan automáticamente:

- Llama 3.2 1B / 3B
- Llama 3.1 8B
- Qwen 2.5 7B / 14B / 32B / Coder 7B
- Mistral 7B v0.3
- Gemma 2 9B / 27B
- Phi 3.5 Mini
- DeepSeek-R1 Distill Qwen 7B

MoE (Qwen 3 30B-A3B / 235B-A22B, Mixtral 8x7B) están listados pero sin `hf_gguf` (la app sabe calcular su compatibilidad pero la descarga manual queda pendiente).

---

## Instalación (desarrollo)

### Requisitos

- **Node.js 20+**: https://nodejs.org/
- **Python 3.11+**: https://www.python.org/
- **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- *(Opcional)* Docker Desktop si vas a usar motores Docker
- *(Opcional)* Driver NVIDIA si quieres acceleración GPU (la app detecta y descarga la build CUDA)

### Arrancar en dev

```powershell
git clone https://github.com/JoniMartin27/inferbench.git
cd inferbench

# Backend (terminal A)
cd backend
uv venv --python 3.11
.venv\Scripts\activate
uv pip install -e .
uvicorn main:app --reload --port 7777

# Frontend (terminal B)
cd frontend
npm install
npm run electron:dev
```

Se abre la app en una ventana Electron. La sidebar muestra la salud del backend y navega entre vistas.

---

## Empaquetado

El backend Python se empaqueta como ejecutable con PyInstaller y se embebe como **sidecar** en el instalador Electron. La app empaquetada no requiere Python en la máquina destino.

```powershell
# Construir el sidecar
scripts\build-sidecar.ps1     # Windows
bash scripts/build-sidecar.sh # macOS / Linux

# Instalador
cd frontend
npm run electron:build
```

Salida en `frontend/release/`:
- Windows → `InferBench Setup *.exe` (NSIS)
- macOS → `InferBench-*.dmg`
- Linux → `InferBench-*.AppImage`

---

## Arquitectura

```
┌──────────────────────────────────────────────────┐
│  Electron app (React + Tailwind + Recharts)      │
│   Dashboard · Motores · Modelos · Benchmark      │
│   Historial (con comparación) · Ajustes          │
└──────────────────────┬───────────────────────────┘
                       │ HTTP REST + SSE
┌──────────────────────▼───────────────────────────┐
│  FastAPI backend  (localhost:7777)               │
│   /api/health         · /api/hardware            │
│   /api/engines/*      · /api/models/*            │
│   /api/benchmark/*    · /api/history/*           │
│   /api/optimize       · /api/benchmark/sweep     │
└────┬───────────────────────────────────┬─────────┘
     │                                   │
     │ subprocess.Popen                  │ Docker SDK
     ▼                                   ▼
┌──────────────────┐              ┌──────────────────┐
│  Native runtime  │              │  Docker runtime  │
│  llama-server    │              │  ollama/vllm/...  │
│  (GitHub release)│              │  (Docker images)  │
└──────────────────┘              └──────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────┐
│  GGUF cache: %APPDATA%/InferBench/models/        │
│  (auto-descarga desde Hugging Face)              │
└──────────────────────────────────────────────────┘
```

---

## Estructura del repo

```
inferbench/
├── backend/
│   ├── api/             # routers FastAPI
│   ├── core/
│   │   ├── hardware.py        # detección CPU/RAM/GPU
│   │   ├── docker_mgr.py      # Docker SDK wrapper
│   │   ├── native_runtime.py  # subprocess wrapper
│   │   ├── binary_manager.py  # descarga binarios desde GitHub
│   │   ├── model_manager.py   # descarga GGUF desde HF
│   │   ├── compat.py          # cálculos de compatibilidad
│   │   ├── optimizer.py       # config óptima para tu hardware
│   │   ├── benchmark.py       # runner + SSE eventing
│   │   └── models_catalog.py
│   ├── engines/
│   │   ├── base.py            # Engine ABC (native + docker)
│   │   ├── llamacpp.py
│   │   └── registry.py
│   ├── data/
│   │   ├── models.json        # catálogo
│   │   └── prompts.json       # suite benchmark
│   ├── db.py                  # SQLModel
│   ├── main.py
│   └── pyproject.toml
│
├── frontend/
│   ├── electron/
│   │   ├── main.js            # proceso main + sidecar
│   │   └── preload.js
│   └── src/
│       ├── App.jsx            # layout + sidebar
│       ├── api.js             # cliente HTTP + suscripción SSE
│       ├── components/ui.jsx  # primitivas
│       └── views/
│           ├── Dashboard.jsx
│           ├── EnginesView.jsx
│           ├── ModelsView.jsx       # tabla compat + ⚡ optimize
│           ├── BenchmarkView.jsx    # incluye sweep + RunningPanel SSE
│           ├── HistoryView.jsx      # multi-select + comparación
│           └── SettingsView.jsx
│
├── scripts/
│   ├── build-sidecar.ps1
│   └── build-sidecar.sh
└── docker/
    └── docker-compose.yml      # referencia
```

---

## Suite de prompts

`backend/data/prompts.json` define 4 prompts representativos:

| ID | Tipo | Tokens objetivo |
|----|------|-----------------|
| `reasoning` | razonamiento lógico | 256 |
| `code` | generación de código | 512 |
| `summary` | resumen | 384 |
| `chat` | conversación corta | 128 |

Métricas medidas por prompt:
- **TTFT** (ms): tiempo al primer token
- **tok/s**: tokens por segundo en la fase de generación
- **VRAM peak** (GB): pico durante el run, vía `pynvml`
- **RAM peak** (GB): pico vía `psutil`
- **Calidad** (0-100): heurística MVP por longitud + overlap con referencia (sustituible por LLM-judge)
- **Coste**: solo APIs cloud (calculado de tokens × precio)

---

## Endpoints clave

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Status + info Docker |
| GET | `/api/hardware` | CPU, RAM, GPUs |
| GET | `/api/engines` | Lista motores con runtime availability |
| POST | `/api/engines/{id}/install` | SSE: descarga binario nativo |
| POST | `/api/engines/{id}/start` | Arranca motor (auto-instala si falta) |
| POST | `/api/engines/{id}/stop` | Detiene motor |
| GET | `/api/models` | Catálogo |
| GET | `/api/models/compat/all?engine=X` | Compat por modelo |
| POST | `/api/optimize` | Config óptima |
| POST | `/api/benchmark/run` | Lanza run, devuelve `run_id` |
| GET | `/api/benchmark/{run_id}/stream` | SSE de progreso |
| POST | `/api/benchmark/{run_id}/stop` | Cancela run en curso |
| POST | `/api/benchmark/sweep` | Lanza N runs con quants distintas |
| GET | `/api/history` | Lista runs |
| GET | `/api/history/compare/runs?ids=A,B,C` | Detalle multi-run para comparación |

---

## Cachés (no se redescargan)

- Binarios: `%APPDATA%\InferBench\binaries\<engine>\` (Windows) o `~/.inferbench/binaries/` (Linux/Mac)
- Modelos GGUF: `%APPDATA%\InferBench\models\<repo>\<file>.gguf`
- DB: `backend/data/inferbench.sqlite`
- Logs de motores nativos: `%APPDATA%\InferBench\logs\<engine>.log`

---

## Estado de hitos

| | Hito | Estado |
|--|------|--------|
| M1 | Detección hardware (NVIDIA·AMD·Apple·CPU-only) | ✅ |
| M2 | Gestor Docker + abstracción `Engine` + llama.cpp | ✅ |
| M3 | Catálogo modelos + cálculos compat y `max_ctx` | ✅ |
| M4 | Benchmark + SSE + persistencia SQLite | ✅ |
| M5 | Frontend Electron + Vite + Tailwind | ✅ |
| M6 | UI completa (6 vistas) | ✅ |
| M7 | Panel live SSE | ✅ |
| M8 | Optimizador automático + botón ⚡ | ✅ |
| M9 | Empaquetado (config) | ✅ |
| **Bonus** | **Auto-bootstrap end-to-end** (descarga + arranque + bench) | ✅ |
| **Bonus** | **Modo nativo sin Docker** + descarga de DLLs CUDA | ✅ |
| **Bonus** | **Auto-descarga GGUF desde HuggingFace** | ✅ |
| **Bonus** | **Sweep multi-quant** + **comparación side-by-side** | ✅ |
| **Bonus** | **Stop mid-run** | ✅ |

---

## Pendientes / siguientes pasos

- Adaptadores reales para `ollama`, `vllm`, `sglang`, `tgi` (M2 sólo cubrió `llamacpp`)
- KV-cache exacta leyendo metadata GGUF (`n_layer`, `n_kv_heads`, `head_dim`) en lugar de la heurística
- API keys persistidas vía `keyring` del SO
- Quality scoring con LLM-judge (BLEU/ROUGE o juez externo) en lugar de heurística por longitud
- Tests unitarios en `compat.py` y `optimizer.py`
- Implementar `cache-reuse`, `--prio-batch` y resto de flags de tuning de llama.cpp
- Adapter de Ollama nativo (Ollama tiene installer Windows propio)
- Soporte de modelos MoE para auto-descarga (split GGUF, manejo de varios shards)

---

## Documentación complementaria

- [PROJECT_BRIEF.md](PROJECT_BRIEF.md) — visión, arquitectura, schemas de optimización por motor, fórmulas de compatibilidad
- [CLAUDE.md](CLAUDE.md) — convenciones de desarrollo y plan de hitos M1–M9

---

## Licencia

MIT (pendiente de añadir LICENSE).
