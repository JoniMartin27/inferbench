# InferBench — Briefing del proyecto

## Visión

Aplicación local multiplataforma (Windows / macOS / Linux) que permite:

1. **Conectar motores de inferencia** locales (vía Docker) y APIs cloud
2. **Detectar hardware** del sistema automáticamente (CPU, RAM, GPU)
3. **Calcular compatibilidad** de modelos LLM con el hardware disponible
4. **Ejecutar benchmarks automatizados** comparando modelos × motores × prompts
5. **Aplicar optimizaciones específicas por motor** (TurboQuant, MoE offload, MTP, speculative decoding, etc.)
6. **Maximizar el contexto** automáticamente: dado modelo + hardware + opts, calcular el contexto máximo que cabe
7. **Cambiar de motor con un clic** desde la UI
8. **Guardar historial** persistente de benchmarks para comparar runs

## Filosofía clave

- **Por defecto, todo automático**: el usuario pulsa "Optimizar" y la app elige la mejor cuantización + KV-cache + flags + contexto máximo para su hardware.
- **Manual disponible**: cada parámetro se puede sobrescribir.
- **Cero optimización en APIs cloud**: cuando el motor activo es OpenAI/Anthropic/etc., solo se exponen parámetros de sampling (`temperature`, `top_p`, `max_tokens`). No tiene sentido cuantizar lo que no controlas.
- **Las optimizaciones son por motor**: las flags de llama.cpp NO son las mismas que vLLM. Cada motor tiene su propio schema.

## Stack técnico

| Capa | Tecnología | Por qué |
|------|------------|---------|
| App de escritorio | **Electron** | Multiplataforma real, fácil de empaquetar |
| Frontend | **React + Vite + TailwindCSS** | Ya tenemos prototipo de UI funcional |
| Gráficas | **Recharts** | Ya integrado en el prototipo |
| Iconos | **lucide-react** | Ya integrado |
| Backend local | **FastAPI** (Python) | Mejor ecosistema para Docker SDK, GPU, ML |
| Comunicación | **HTTP REST en `localhost:7777`** | Simple y depurable. Considerar SSE/WebSocket para benchmarks live |
| Detección hardware | `psutil` + `pynvml` (NVIDIA) + plataforma-específico (AMD/Apple) | |
| Orquestación motores | **Docker SDK for Python** (`docker` package) | Lanzar/detener contenedores |
| Persistencia | **SQLite** vía `sqlite3` o `sqlmodel` | Sin servidor, embebido |
| Empaquetado | **electron-builder** | Genera .exe / .dmg / .AppImage |

## Arquitectura

```
┌─────────────────────────────────────────────────┐
│  Electron app (frontend React)                  │
│  - UI: dashboard, motores, modelos, benchmark   │
│  - Llama a HTTP localhost:7777                  │
└──────────────────┬──────────────────────────────┘
                   │  HTTP / SSE
┌──────────────────▼──────────────────────────────┐
│  Backend FastAPI (Python, localhost:7777)       │
│  ├─ /api/hardware       → detect hw             │
│  ├─ /api/engines/*      → start/stop/status     │
│  ├─ /api/models/*       → catalog + compat      │
│  ├─ /api/benchmark      → run + SSE progress    │
│  └─ /api/history/*      → CRUD historial        │
└──────────────────┬──────────────────────────────┘
                   │  Docker SDK
┌──────────────────▼──────────────────────────────┐
│  Docker containers (motores)                    │
│  llama.cpp · Ollama · vLLM · SGLang · TGI       │
└─────────────────────────────────────────────────┘
```

## Estructura del repositorio

```
inferbench/
├── PROJECT_BRIEF.md       # este documento
├── CLAUDE.md              # instrucciones para Claude Code
├── README.md
├── package.json           # workspace raíz (electron-builder, scripts)
├── .gitignore
│
├── backend/               # FastAPI
│   ├── pyproject.toml
│   ├── main.py            # entrypoint, registra rutas
│   ├── api/
│   │   ├── hardware.py    # GET /api/hardware
│   │   ├── engines.py     # /api/engines/*
│   │   ├── models.py      # /api/models/*
│   │   ├── benchmark.py   # /api/benchmark (con SSE)
│   │   └── history.py     # /api/history/*
│   ├── core/
│   │   ├── hardware.py    # detección CPU/RAM/GPU
│   │   ├── docker_mgr.py  # wrapper sobre Docker SDK
│   │   ├── compat.py      # cálculos de compatibilidad y ctx máx
│   │   ├── optimizer.py   # lógica "Optimizar para mi hardware"
│   │   └── benchmark.py   # ejecución de suite + medición real
│   ├── engines/           # adaptadores por motor
│   │   ├── base.py        # interfaz común (start, stop, infer, build_command)
│   │   ├── llamacpp.py
│   │   ├── ollama.py
│   │   ├── vllm.py
│   │   ├── sglang.py
│   │   ├── tgi.py
│   │   ├── openai.py
│   │   ├── anthropic.py
│   │   ├── openrouter.py
│   │   └── nvidia.py
│   ├── data/
│   │   ├── models.json    # catálogo de modelos (poblar al inicio)
│   │   └── prompts.json   # suite de prompts de benchmark
│   └── db.py              # SQLite (historial)
│
├── frontend/              # Electron + React
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── electron/
│   │   ├── main.js        # proceso main de Electron
│   │   └── preload.js
│   └── src/
│       ├── App.jsx        # ← portar el prototipo del artefacto aquí
│       ├── api.js         # cliente HTTP a localhost:7777
│       ├── components/
│       └── views/
│
├── docker/
│   └── docker-compose.yml # imágenes pre-tageadas de los motores
│
└── scripts/
    ├── install.sh         # Linux/macOS
    └── install.ps1        # Windows
```

## Catálogo inicial de motores

| ID | Nombre | Tipo | Puerto | Imagen Docker | Optimizable |
|----|--------|------|--------|---------------|-------------|
| `llamacpp` | llama.cpp | local | 8080 | `ghcr.io/ggerganov/llama.cpp:server-cuda` | ✅ |
| `ollama` | Ollama | local | 11434 | `ollama/ollama:latest` | ✅ |
| `vllm` | vLLM | local | 8000 | `vllm/vllm-openai:latest` | ✅ |
| `sglang` | SGLang | local | 30000 | `lmsysorg/sglang:latest` | ✅ |
| `tgi` | HF TGI | local | 8088 | `ghcr.io/huggingface/text-generation-inference` | ✅ |
| `openai` | OpenAI | api | — | — | ❌ (solo sampling) |
| `anthropic` | Anthropic | api | — | — | ❌ (solo sampling) |
| `openrouter` | OpenRouter | api | — | — | ❌ (solo sampling) |
| `nvidia` | NVIDIA NIM | api | — | — | ❌ (solo sampling) |

## Schema de optimizaciones POR MOTOR (crítico)

> ⚠️ **Cada motor expone flags distintas. NO se aplican las mismas optimizaciones a todos.**

### `llamacpp` (referencia: vídeo de Codacus, Qwen 3.6 35B en 6GB VRAM)

- `quant`: GGUF level — `Q2_K`, `Q3_K_M`, `Q4_K_M`, `Q5_K_M`, `Q6_K`, `Q8_0`, `F16`
- `kvCache`: `f16` | `q8_0` | `q4_0` (flags: `-ctk` `-ctv`)
- `moeOffload` (solo MoE): activa `--n-cpu-moe N`
- `noMmap`: `--no-mmap`
- `mlock`: `--mlock`
- `flashAttn`: `-fa`
- `turboQuant`: KV-cache compression avanzada
- `contextLen`: `-c N` (auto-calculado por defecto)

Comando ejemplo:
```
llama-server -m models/qwen3.6-35b-a3b.Q4_K_M.gguf -c 8192 --n-cpu-moe 27 -ngl 99 --no-mmap --mlock -fa -ctk q8_0 -ctv q8_0
```

### `ollama`

- `quant`: `q2_K`, `q3_K_M`, `q4_K_M`, `q5_K_M`, `q6_K`, `q8_0`, `fp16`
- `kvCache`: env `OLLAMA_KV_CACHE_TYPE=q8_0`
- `flashAttn`: env `OLLAMA_FLASH_ATTENTION=1`
- `numThread`: `num_thread` en Modelfile
- `contextLen`: `num_ctx`

### `vllm`

- `quant`: `none`, `awq`, `gptq`, `fp8`, `bitsandbytes` (flag: `--quantization`)
- `kvCache`: `auto`, `fp8`, `fp8_e5m2` (flag: `--kv-cache-dtype`)
- `gpuMemUtil`: `--gpu-memory-utilization 0.5..0.98`
- `enforceEager`: `--enforce-eager`
- `prefixCaching`: `--enable-prefix-caching`
- `specDecode`: `--speculative-model "[ngram]" --num-speculative-tokens 5`
- `contextLen`: `--max-model-len`

### `sglang`

- `quant`: `none`, `awq`, `gptq`, `fp8` (flag: `--quantization`)
- `kvCache`: `auto`, `fp8_e5m2`
- `memFraction`: `--mem-fraction-static 0.5..0.95`
- `specDecode`: `--speculative-algorithm EAGLE3 --speculative-num-steps 5`
- `chunkedPrefill`: `--chunked-prefill-size 8192`
- `torchCompile`: `--enable-torch-compile`
- `contextLen`: `--context-length`

### `tgi`

- `quant`: `none`, `awq`, `gptq`, `bitsandbytes`, `eetq`, `fp8` (flag: `--quantize`)
- `kvCache`: `auto`, `fp8`
- `numShard`: `--num-shard`
- `maxBatchPrefill`: `--max-batch-prefill-tokens`
- `contextLen`: `--max-input-tokens` y `--max-total-tokens`

### `openai`, `anthropic`, `openrouter`, `nvidia` (APIs cloud)

**Solo sampling** — NO optimización local:

- `temperature`: 0..2
- `topP`: 0..1
- `maxOutTokens`: tokens de salida

## Lógica de cálculo

### Tamaño del modelo cuantizado

```
size_GB(model, quant) = model.size_base * QUANT_FACTOR[quant] / 0.55
```

con `QUANT_FACTOR`: Q2_K=0.32, Q3_K_M=0.42, Q4_K_M=0.55, Q5_K_M=0.67, Q6_K=0.81, Q8_0=1.0, F16=2.0

### Memoria del KV-cache por token

```
kv_per_token_MB(model, kv_type) = 0.5 * (params/7)^0.7 * KV_FACTOR[kv_type]
```

con `KV_FACTOR`: f16=1.0, q8_0=0.5, q4_0=0.25, fp8=0.5, fp8_e5m2=0.5

> ⚠️ Esta es una **aproximación**. En el backend real, leer `n_layer`, `n_kv_heads`, `head_dim` del archivo de config del modelo (`config.json` o metadata GGUF) para precisión exacta.

### Compatibilidad

```python
def check_compat(model, hw, opts, engine):
    if engine.is_api(): return "api"
    model_size = get_model_size(model, opts.quant)
    kv_per_tok = get_kv_per_token(model, opts.kv_cache)
    kv_overhead = opts.context_len * kv_per_tok
    total = model_size + kv_overhead + 0.6  # overhead fijo

    # Caso especial MoE con --n-cpu-moe (solo llama.cpp)
    if model.is_moe and opts.moe_offload and engine == "llamacpp" and hw.vram > 0:
        shared_active = (model.active / model.params) * model_size + 1.2
        if shared_active <= hw.vram and total <= hw.vram + hw.ram * 0.8:
            return "moe"  # MoE offload óptimo

    if total <= hw.vram: return "ok"
    if hw.vram > 0 and total <= hw.vram + hw.ram * 0.8: return "partial"
    if total <= hw.ram * 0.8: return "cpu"
    return "fail"
```

### Contexto máximo automático

```python
def compute_max_context(model, hw, opts, engine):
    if engine.is_api(): return model.max_ctx
    model_size = get_model_size(model, opts.quant)
    kv_per_tok = get_kv_per_token(model, opts.kv_cache)

    if model.is_moe and opts.moe_offload and engine == "llamacpp":
        avail = hw.vram - ((model.active / model.params) * model_size + 1.2) - 0.4
    elif model_size <= hw.vram:
        avail = hw.vram - model_size - 0.4
    else:
        avail = (hw.vram + hw.ram * 0.7) - model_size - 0.8

    if avail <= 0.3: return 2048
    max_tok = int(avail / kv_per_tok)
    return max(2048, min((max_tok // 1024) * 1024, model.max_ctx))
```

### "Optimizar para mi hardware"

Para el motor activo:
1. Recorrer cuantizaciones de mayor a menor calidad: `[Q8_0, Q6_K, Q5_K_M, Q4_K_M, Q3_K_M, Q2_K]`
2. Para cada una, comprobar si cabe el modelo + un contexto mínimo (4096)
3. Elegir la primera que quepa
4. Aplicar contexto máximo automático con esa cuantización
5. Activar todas las flags compatibles (flashAttn, mlock, MoE offload si aplica)

## Suite de prompts de benchmark

| ID | Nombre | Tokens objetivo | Tipo |
|----|--------|-----------------|------|
| `reasoning` | Razonamiento (problema lógico complejo) | 256 | Cadena de razonamiento |
| `code` | Generación de código (función no trivial) | 512 | Programación |
| `summary` | Resumen de texto largo | 384 | Comprensión |
| `chat` | Conversación corta | 128 | Diálogo |

Métricas medidas por run:
- **TTFT**: tiempo al primer token (ms)
- **tok/s**: tokens generados por segundo
- **VRAM peak**: pico de uso (medido con `pynvml.nvmlDeviceGetMemoryInfo` en NVIDIA)
- **RAM peak**: pico de RAM (medido con `psutil.virtual_memory`)
- **Calidad**: score 0-100. Implementado en 3 modos (`core/benchmark.py`): scorer offline basado en la respuesta de referencia (F1 de tokens recall-weighted + recall de números + stemming, sin GPU/API → corre en cualquier PC) por defecto, y LLM-judge opcional (motor local `self` o API externa OpenAI-compatible)
- **Coste**: solo APIs (calculado de tokens × precio publicado)

## Modelo de datos (SQLite)

```sql
CREATE TABLE benchmark_runs (
  id TEXT PRIMARY KEY,
  ts INTEGER NOT NULL,
  engine TEXT NOT NULL,
  hw_json TEXT NOT NULL,
  opts_json TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE benchmark_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_id TEXT NOT NULL,
  tps REAL,
  ttft_ms INTEGER,
  vram_gb REAL,
  ram_gb REAL,
  quality REAL,
  cost REAL,
  ctx_used INTEGER,
  raw_output TEXT,
  FOREIGN KEY(run_id) REFERENCES benchmark_runs(id) ON DELETE CASCADE
);

CREATE TABLE engine_configs (
  engine TEXT PRIMARY KEY,
  config_json TEXT NOT NULL,
  api_key_encrypted TEXT,
  updated_at INTEGER
);
```

> ⚠️ **API keys**: NUNCA en plano. Usar `keyring` (Python) en producción para guardarlas en el almacén nativo del SO (Keychain / Credential Manager / Secret Service).

## API REST del backend

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Healthcheck del backend |
| GET | `/api/hardware` | Detecta CPU, RAM, GPU(s) |
| GET | `/api/engines` | Lista motores con su estado |
| POST | `/api/engines/{id}/start` | Arranca contenedor (body: opts) |
| POST | `/api/engines/{id}/stop` | Detiene contenedor |
| GET | `/api/engines/{id}/logs` | Stream de logs (SSE) |
| GET | `/api/models` | Catálogo de modelos |
| GET | `/api/models/compat?engine=X` | Compatibilidad de cada modelo con hw + motor |
| POST | `/api/benchmark/run` | Lanza suite (body: engine, models, prompts, opts). Devuelve run_id |
| GET | `/api/benchmark/{run_id}/stream` | SSE con eventos de progreso live |
| GET | `/api/history` | Lista runs |
| GET | `/api/history/{run_id}` | Detalle |
| DELETE | `/api/history/{run_id}` | Eliminar |
| POST | `/api/optimize` | Body: engine, model_id. Devuelve config óptima sugerida |

## Eventos SSE durante benchmark

```json
{"type": "start", "run_id": "...", "total": 8}
{"type": "phase", "model": "Qwen 3.6 35B", "prompt": "code", "phase": "load"}
{"type": "phase", "phase": "warmup"}
{"type": "phase", "phase": "ttft", "ttft_ms": 213}
{"type": "phase", "phase": "generate"}
{"type": "tokens", "current": 145, "target": 512, "tps_current": 14.2}
{"type": "phase", "phase": "quality", "score": 87.3}
{"type": "result", "result": { ... }}
{"type": "log", "level": "info|success|warn|error", "text": "..."}
{"type": "done", "run_id": "..."}
```

## Decisiones tomadas (NO revisar sin acuerdo)

- ✅ **Multiplataforma** → Electron + Python backend
- ✅ **Por defecto NVIDIA** pero el sistema debe detectar y soportar AMD ROCm, Apple Metal, y CPU-only
- ✅ **Docker es obligatorio** para motores locales (instalación documentada en README)
- ✅ **Contexto en automático** por defecto (manual disponible)
- ✅ **APIs cloud → solo sampling** (sin cuantización ni offload)
- ✅ **Optimizaciones SON por motor** — schema separado por cada uno
- ✅ **Las API keys se guardan con `keyring`**, nunca en SQLite plano

## Referencia visual: prototipo

El prototipo de UI ya está construido en una sesión anterior de Claude (artefacto React).
Está en `frontend/src/App.jsx` (deberá portarse desde el artefacto).

Componentes/vistas:
- `Dashboard` — resumen
- `EnginesView` — gestionar motores con tarjetas
- `ModelsView` — tabla de modelos con compatibilidad
- `BenchmarkView` — config de suite + ejecución
- `RunningPanel` — panel live con métricas + log estilo terminal durante benchmark
- `HistoryView` — historial con gráficos
- `SettingsView` — hardware (presets + manual)

Paleta: fondo `slate-950`, acentos `indigo-500`, éxito `emerald-400`, MoE `purple`, alerta `amber/rose`.

## Referencias técnicas externas

- llama.cpp `--n-cpu-moe` y MoE offload (vídeo Codacus): https://www.youtube.com/watch?v=8F_5pdcD3HY
- vLLM docs: https://docs.vllm.ai
- SGLang docs: https://docs.sglang.ai
- HF TGI: https://huggingface.co/docs/text-generation-inference
- Ollama: https://github.com/ollama/ollama
