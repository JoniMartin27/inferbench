<h1 align="center">InferBench</h1>

<p align="center">
  <b>Descarga, arranca y benchmarkea motores de inferencia LLM locales con un solo click.</b><br>
  Sin Docker obligatorio. Sin tocar la línea de comandos. Tus datos nunca salen de tu máquina.
</p>

<p align="center">
  <img alt="Plataformas" src="https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-2b2b2b">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue">
  <a href="https://github.com/JoniMartin27/inferbench/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/JoniMartin27/inferbench/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Electron" src="https://img.shields.io/badge/Electron-33-47848F?logo=electron&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-Python%203.11-009688?logo=fastapi&logoColor=white">
  <a href="https://github.com/JoniMartin27/inferbench/releases"><img alt="Releases" src="https://img.shields.io/github/v/release/JoniMartin27/inferbench?label=descargar"></a>
</p>

<p align="center">
  <!-- Graba este GIF y déjalo en assets/demo.gif (ver assets/README.md). Es la pieza clave de conversión. -->
  <img src="assets/demo.gif" alt="InferBench en acción: elegir modelo, optimizar, benchmark en vivo y comparar runs" width="800">
</p>

---

¿Quieres correr LLMs en local pero no sabes **qué cuantización te entra en tu GPU**, ni **a cuántos tok/s va a ir**, ni **qué motor es más rápido para tu hardware**? InferBench lo responde por ti, midiendo de verdad — sin números inventados.

```
Eliges modelo + cuantizaciones → InferBench:
  ① descarga el binario del motor (release oficial GitHub)
  ② descarga los GGUF que falten desde Hugging Face
  ③ arranca el motor con la config óptima para tu hardware
  ④ ejecuta la suite de prompts midiendo TTFT, tok/s, VRAM, calidad
  ⑤ guarda los resultados y te deja compararlos lado a lado
```

## Descargar

Coge el instalador para tu sistema desde la [**página de Releases**](https://github.com/JoniMartin27/inferbench/releases) — no necesitas Python ni Node instalados, el backend va embebido como sidecar:

| Sistema | Archivo |
|---|---|
| Windows | `InferBench Setup *.exe` (NSIS) |
| macOS | `InferBench-*.dmg` |
| Linux | `InferBench-*.AppImage` |

> ¿Prefieres compilarlo tú? Salta a [Instalación (desarrollo)](#instalación-desarrollo).

---

## Features

- **Auto-bootstrap end-to-end**: 1 click → binario + modelo + arranque + benchmark + cleanup
- **Modo nativo (sin Docker)** para llama.cpp: descarga release pre-compilada de GitHub (auto-detecta CUDA, descarga también las DLLs del runtime)
- **Modo Docker** disponible para cualquier motor que lo requiera
- **Detección automática de hardware**: CPU, RAM, GPU (NVIDIA via NVML, AMD via rocm-smi, Apple Silicon via system_profiler). Cacheada para que el listado de compatibilidad sea instantáneo (~4 ms para 124 modelos)
- **Catálogo de 124+ modelos** con auto-descarga GGUF desde HF, todos verificados contra HuggingFace (incluye visión, código, reasoning y MoE). Ver [Catálogo](#catálogo-de-modelos-con-auto-descarga)
- **Escaneo de GGUFs locales**: detecta modelos de LM Studio, Ollama, HF cache, etc., con cuenta de parámetros real leída de la metadata GGUF (independiente del quant)
- **Optimizador**: dado tu hardware + modelo + motor, calcula la mejor cuantización, KV-cache, contexto máximo, MoE offload, flags
- **Compresión de KV-cache explicada**: 5 presets (Calidad→Extremo) con qué hace / en qué afecta / qué permite, + tabla de los **modelos más potentes que caben con cada compresión** para tu hardware
- **Evaluación de calidad en 3 modos**: scorer offline basado en referencia (sin GPU/API, corre en cualquier PC), LLM-judge con el motor local, o LLM-judge por API externa. Ver [Calidad](#evaluación-de-calidad)
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

`backend/data/models.json` lista **124+ modelos**. Los que tienen `hf_gguf` configurado se auto-descargan desde Hugging Face. Cubre, entre otros:

- **Llama** 3 / 3.1 / 3.2 / 3.3 (1B → 70B), Nemotron, Hermes, Tulu, Dolphin
- **Qwen** 2.5 / 3 (0.5B → 72B), Coder, Math, **QwQ 32B** (reasoning), MoE 30B-A3B
- **Gemma** 2 y **Gemma 3** (1B → 27B)
- **Mistral** 7B, Nemo, Small 3/3.1 24B, Ministral, Codestral, **Mixtral** (MoE)
- **Phi** 2 / 3 / 3.5 / 4 (+ mini, + MoE)
- **DeepSeek** R1 distills, Coder, Coder-V2-Lite (MoE)
- **Visión**: Qwen2-VL, Qwen2.5-VL, MiniCPM-V
- **Código**: Code Llama, CodeGemma, StarCoder2, Yi-Coder, OpenCoder, Stable Code
- **Más**: Granite (IBM), Falcon3, GLM-4, EXAONE, InternLM, OLMo, Aya/Command-R (Cohere), SmolLM2, SOLAR, Zephyr…

> **Sin datos inventados.** Cada entrada se verifica contra HuggingFace antes de añadirse: el repo GGUF existe, el `file_template` se deriva de los archivos reales publicados y se comprueba que el `Q4_K_M` resuelve. La herramienta está en `backend/scripts/` (`verify_models.py` + `merge_models.py`); ejecútala para ampliar el catálogo de forma segura. Los modelos huge multi-parte (Llama 4, DeepSeek-V3) se excluyen a propósito porque la descarga es de archivo único.

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
│   │   ├── hardware.py        # detección CPU/RAM/GPU (cacheada)
│   │   ├── docker_mgr.py      # Docker SDK wrapper
│   │   ├── native_runtime.py  # subprocess wrapper
│   │   ├── binary_manager.py  # descarga binarios desde GitHub
│   │   ├── model_manager.py   # descarga GGUF desde HF
│   │   ├── local_models.py    # escaneo de GGUFs locales
│   │   ├── gguf_reader.py     # lee metadata GGUF (arch, params reales…)
│   │   ├── compat.py          # cálculos de compatibilidad
│   │   ├── optimizer.py       # config óptima + recomendaciones + by-compression
│   │   ├── benchmark.py       # runner + SSE + scorer de calidad + LLM-judge
│   │   └── models_catalog.py
│   ├── scripts/
│   │   ├── verify_models.py   # verifica repos GGUF contra HF y deriva metadata
│   │   └── merge_models.py    # valida y fusiona modelos nuevos en el catálogo
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
- **Calidad** (0-100): ver [Evaluación de calidad](#evaluación-de-calidad)
- **Coste**: solo APIs cloud (calculado de tokens × precio)

---

## Evaluación de calidad

La nota de calidad (0-100) tiene 3 modos, seleccionables en **Benchmark → Evaluación de calidad** (TTFT y tok/s siempre son medidas reales del motor):

| Modo | Cómo funciona | Cuándo usarlo |
|------|---------------|---------------|
| **Referencia (offline)** · *default* | Compara la respuesta con la de referencia: F1 de tokens *recall-weighted* + recall exacto de números + stemming por prefijo + penalización de texto degenerado. Python puro, **sin GPU/modelo/red** | Funciona en **cualquier ordenador**. Bueno en tareas con respuesta esperada (razonamiento, código, resumen); aproximado en tareas abiertas (chat) |
| **LLM-judge (motor local)** | El propio motor puntúa sus respuestas (rúbrica 0-100) | Fiable solo con modelos capaces (**≥7-8B**); los pequeños (1-3B) colapsan a 0. Juez = modelo evaluado (sesgo) |
| **LLM-judge (API externa)** | Un modelo cloud OpenAI-compatible (p.ej. `gpt-4o-mini`) juzga | Lo **más fiable e imparcial**; requiere API key |

El default es offline a propósito para que funcione en máquinas sin GPU ni API. El LLM-judge es la mejora opcional para juicio fiable de tareas abiertas.

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
| GET | `/api/models/local` | GGUFs locales en disco (con params reales de metadata) |
| GET | `/api/models/compat/all?engine=X` | Compat por modelo |
| POST | `/api/optimize` | Config óptima |
| GET | `/api/optimize/recommendations?top=N` | Modelos más potentes ejecutables en tu hardware |
| GET | `/api/optimize/by-compression?context_len=N` | Modelo más potente que cabe con cada preset de compresión KV |
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
| **Bonus** | **Catálogo de 124+ modelos** verificados contra HF + tooling de ampliación | ✅ |
| **Bonus** | **Params reales** de GGUFs locales desde metadata (independiente del quant) | ✅ |
| **Bonus** | **Compresión KV explicada** + tabla de modelos más potentes por compresión | ✅ |
| **Bonus** | **Calidad offline basada en referencia** + **LLM-judge** (local / API) | ✅ |

---

## Pendientes / siguientes pasos

- Adaptadores reales para `ollama`, `vllm`, `sglang`, `tgi` (M2 sólo cubrió `llamacpp`)
- KV-cache exacta para el cálculo de compat usando `n_kv_heads`/`head_dim` de la metadata (la cuenta de **parámetros** ya se lee de la metadata GGUF; el contexto máximo sigue siendo heurístico)
- API keys persistidas vía `keyring` del SO (el LLM-judge por API ya acepta key por request)
- Tests unitarios en `compat.py` y `optimizer.py`
- Implementar `cache-reuse`, `--prio-batch` y resto de flags de tuning de llama.cpp
- Adapter de Ollama nativo (Ollama tiene installer Windows propio)
- Soporte de modelos MoE multi-parte para auto-descarga (split GGUF, manejo de varios shards)
- Soporte multimodal real (los modelos de visión se benchmarkean como texto; falta descargar el `mmproj` y prompts con imagen)

---

## Documentación complementaria

- [PROJECT_BRIEF.md](PROJECT_BRIEF.md) — visión, arquitectura, schemas de optimización por motor, fórmulas de compatibilidad
- [CLAUDE.md](CLAUDE.md) — convenciones de desarrollo y plan de hitos M1–M9

---

## Contribuir

Las PRs son bienvenidas — lee [**CONTRIBUTING.md**](CONTRIBUTING.md) para el setup, cómo correr lint/tests y las convenciones. Buenos primeros aportes: los adaptadores reales para `ollama`/`vllm`/`sglang`/`tgi` y más tests de `compat.py`/`optimizer.py`. Abre un issue antes de un cambio grande para acordar el enfoque.

El proyecto sigue un [Código de conducta](CODE_OF_CONDUCT.md).

## Seguridad

¿Encontraste una vulnerabilidad? **No abras un issue público** — sigue [SECURITY.md](SECURITY.md). El proyecto ha pasado una [auditoría de seguridad](SECURITY-AUDIT.md) (postura buena; los hallazgos están remediados).

## Licencia

[MIT](LICENSE) © 2026 Jonathan Martin.
