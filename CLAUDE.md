# Instrucciones para Claude Code en este proyecto

## Antes de tocar nada
- Lee `PROJECT_BRIEF.md` para la visión, fórmulas de compatibilidad y schemas de optimización por motor.
- `README.md` tiene el inventario actual: motores soportados, endpoints, layout de cachés y estado real de cada feature.
- Los hitos M1–M9 están todos implementados (ver tabla en README). Esto es mantenimiento y extensión, no greenfield.

## Lo que NO debes hacer (load-bearing)

### Schemas de optimización son por motor, no uniformes
Cada motor tiene su propio set de flags. `llama.cpp` usa `-ctk`, `-ctv`, `--n-cpu-moe`, `-fa`, `--n-gpu-layers`. vLLM usa otros. APIs cloud (OpenAI, Anthropic, OpenRouter, NVIDIA) sólo admiten parámetros de sampling — no optimización local. Está en `PROJECT_BRIEF.md`, sección "Schema de optimizaciones POR MOTOR". No intentes unificar.

### No simules motores
El prototipo del artefacto inicial usaba datos fake. **El proyecto local NO debe simular**: si un motor no está disponible o falla, devuelve error claro al frontend. No inventes TTFT, tok/s, ni VRAM. Único mock aceptable: tests unitarios.

### No bloquees el event loop
FastAPI es async. Las descargas (binarios GitHub, GGUF de HF), spawn de subprocesos y operaciones Docker se hacen sin bloquear — patrón ya establecido en `core/binary_manager.py`, `core/model_manager.py`, `core/native_runtime.py`. Replica ese patrón.

### Secretos
API keys de cloud (OpenAI/Anthropic/etc.) van por `keyring` (ya es dependencia). No las metas a SQLite ni a archivos de config en plano.

### No satures la GPU del display (load-bearing)
vLLM/SGLang/TGI pre-asignan `fracción · VRAM_total`. En un equipo de UNA GPU que también pinta la pantalla, pedir demasiado **ahoga al compositor → cortes de vídeo y cuelgues** (pasó de verdad). Por eso:
- `hardware.safe_gpu_fraction()` calcula el tope desde la VRAM **libre** menos una **reserva de display** (`gpu_display_reserve_gb`, por defecto `max(2GB, 25%)`, ajustable con env `INFERBENCH_GPU_RESERVE_GB`).
- **Cada motor Docker aplica este tope SIEMPRE** en su `build_command`/`build_environment` (vLLM `--gpu-memory-utilization`, SGLang `--mem-fraction-static`, TGI `CUDA_MEMORY_FRACTION`), con `min(lo_pedido, lo_seguro)`. NO dejes que usen su default (~0.9). NO quites el cap.
- `base._start_docker` tiene un **guard**: si no cabe nada de forma segura, lanza error claro en vez de arrancar. Nunca lo bypasees arrancando contenedores GPU a mano sin pasar por el motor.

## Convenciones

### Python (`backend/`)
- Python 3.11+, `uv` para venv y deps (no pip/poetry directos).
- `ruff` + `black`, línea 100 (configurado en `pyproject.toml`).
- Type hints en funciones públicas. Pydantic models para entradas/salidas de la API (no dicts sueltos).
- `loguru` para logging, nunca `print()`.
- Pytest + pytest-asyncio instalados. Hay **42 tests** en `backend/tests/` (cubren `compat`, `optimizer`, `quality`, `gguf_reader`, `multimodal` y `security`); corre `pytest` antes de tocar `core/`. Al añadir features amplía la cobertura de `core/compat.py` y `core/optimizer.py`.

### Frontend (`frontend/`)
- JSX, no TypeScript (decisión deliberada del MVP — no migres sin hablarlo).
- Componentes funcionales con hooks, Tailwind para estilos (no CSS modules).
- Cliente HTTP centralizado en `src/api.js`, incluye helper de suscripción SSE — úsalo, no hagas `fetch` directo desde vistas.
- No hay ESLint/Prettier configurados en este momento; mantente consistente con el estilo existente.

## Arquitectura (resumen)

```
Electron (React + Vite + Tailwind)
  └─ HTTP REST + SSE ─→ FastAPI :7777
                          ├─ core/hardware.py        detección CPU/RAM/GPU
                          ├─ core/binary_manager.py  descarga releases GitHub
                          ├─ core/model_manager.py   descarga GGUF de HF
                          ├─ core/native_runtime.py  subprocess wrapper
                          ├─ core/docker_mgr.py      Docker SDK wrapper
                          ├─ core/compat.py          ¿cabe X en mi hardware?
                          ├─ core/optimizer.py       config óptima por hw+modelo+motor
                          ├─ core/benchmark.py       runner + SSE events
                          └─ engines/                Engine ABC + impls (llamacpp ✅, resto stub)
                              │
                              └─→ llama-server (nativo) o contenedor Docker
                                     │
                                     └─→ GGUF cache en %APPDATA%\InferBench\models\
```

El flujo estrella es **auto-bootstrap**: 1 click en la UI dispara descarga de binario + descarga de GGUF + arranque del motor + benchmark + persistencia. Cada paso emite eventos SSE; el frontend los pinta en `RunningPanel`.

### Cachés (no se redescargan; respeta sus rutas)
- Binarios: `%APPDATA%\InferBench\binaries\<engine>\`
- Modelos GGUF: `%APPDATA%\InferBench\models\<repo>\<file>.gguf`
- SQLite: `backend/data/inferbench.sqlite`
- Logs de motores nativos: `%APPDATA%\InferBench\logs\<engine>.log`

## Comandos

### Backend (desde `backend/`, PowerShell en Windows)
```powershell
uv venv --python 3.11
.venv\Scripts\activate
uv pip install -e ".[dev]"
uvicorn main:app --reload --port 7777
```

Lint / formato / tests (cuando existan):
```powershell
ruff check .
ruff format .            # o: black .
pytest                   # suite completa
pytest path\to\test_file.py::test_name   # un test concreto
```

### Frontend (desde `frontend/`)
```powershell
npm install
npm run electron:dev     # Vite + Electron en paralelo (recomendado)
npm run dev              # sólo Vite en :5173 (debug del navegador)
```

### Todo junto (desde la raíz)
```powershell
npm run dev              # backend + frontend con concurrently
```

### Empaquetado
```powershell
scripts\build-sidecar.ps1     # PyInstaller del backend → frontend/electron/sidecar/
cd frontend && npm run electron:build
```
Salida en `frontend/release/`.

## Endpoints clave
Ver `README.md` para la tabla completa. Los SSE viven en `/api/engines/{id}/install`, `/api/benchmark/{run_id}/stream`. El runner devuelve `run_id` síncronamente; el stream va aparte.

## Ya implementado (no son pendientes)
- **Catálogo de 124+ modelos** verificados contra HF. Para ampliarlo usa `backend/scripts/verify_models.py` + `merge_models.py` (verifican repo GGUF, derivan `file_template` real y validan contra el schema). NO añadas modelos a mano sin verificar.
- **Cuenta de parámetros** de GGUFs locales se lee de la metadata (`core/gguf_reader.py::estimate_param_count`), no del tamaño de archivo.
- **KV-cache exacta** (`core/compat.py::kv_per_token_mb_f16`): `2·n_layer·n_head_kv·head_dim·2B`, captura GQA/MQA. El catálogo trae `n_head_kv`/`head_dim` (poblados por `scripts/enrich_arch.py` leyendo el header GGUF vía Range). Si faltan dims, cae a la heurística `0.5·(params/7)^0.7`. NO reintroduzcas la heurística en `optimizer.py`: usa `compat.kv_per_token_mb_f16`.
- **Plan de arranque por run** (`optimizer.plan_llamacpp_run`): el ctx y `ngl` se calculan para el quant REAL que se ejecuta y la KV efectiva (kvCacheK/V + `nkvo`=KV en RAM), NO para el quant que el optimizer elegiría. NO uses `optimal.context_len`/`optimal.flags['ngl']` directamente en el arranque (causaba OOM al correr un quant ≠ óptimo). La KV cuantizada (`-ctk/-ctv` ≠ f16) **fuerza `-fa on`** (llama.cpp lo exige). Los flags del arranque se construyen una sola vez (base optimizer + overrides de engine_opts, sin duplicar).
- **`detect_hardware()` cacheado** (`lru_cache`) — no lo "des-cachees"; el listado de compat depende de que sea instantáneo.
- **Evaluación de calidad** en 3 modos (`core/benchmark.py`): scorer offline basado en referencia (default, sin GPU/API), LLM-judge `self` y `api`. El default DEBE seguir funcionando en cualquier ordenador.
- **Visión multimodal real** (`llamacpp` nativo): los modelos con tag `vision` declaran su `mmproj` en `hf_gguf.mmproj`; `model_manager.ensure_mmproj` lo descarga, el bootstrap arranca llama-server con `--mmproj` y los prompts `vision-scene`/`vision-count` mandan imágenes reales (`data/vision_*.png`, generadas por `scripts/make_vision_test.py`) por la API OpenAI-vision. El gating de `run()` omite prompts con imagen en modelos no-visión. NO mandes imágenes sin mmproj cargado.
- **Scorers verificables (política: TODO prompt lleva uno)** en `core/benchmark.py`. Hay un test que lo exige (`test_every_prompt_has_a_verifiable_scorer`). No añadas prompts puntuados solo por F1 de tokens.
  - `_quality_keywords`: `Prompt.keywords` = grupos de sinónimos (ground-truth). Nota = fracción presente. Casa por `\b`+prefijo (acepta morfología, pero "500" no cuenta dentro de "1500"). Sin acentos, ES/EN. Scorer de visión, `reasoning`, `summary`, `chat`.
  - `_quality_code` (async): `Prompt.code_tests` = aserciones que se EJECUTAN contra el código del modelo en subproceso aislado (`python -I`, cwd temporal, timeout). Nota = % de casos que pasan. Desactivable con env `INFERBENCH_NO_CODE_EXEC=1`. Scorer de `code`.
  - El LLM-judge solo aplica a prompts SIN scorer verificable (no ve la imagen ni ejecuta el código).
  - `Prompt.context_file`: antepone un texto largo de `data/` al prompt (test de contexto largo / needle-in-haystack). `_prompt_user_text` lo resuelve para ambos formatos de body.
- **APIs cloud**: OpenAI/OpenRouter/NVIDIA van por `/v1/chat/completions` (`_stream_openai_chat`, auth `Bearer`). **Anthropic NO es OpenAI-compatible**: usa `_stream_anthropic_chat` (`/v1/messages`, `x-api-key` + `anthropic-version`, `system` como campo aparte, eventos SSE `content_block_delta`). El dispatch está en `_run_one` por `self.req.engine`. Verificados E2E: llamacpp (nativo), ollama (daemon), vllm (Docker+GPU); sglang/tgi comparten el bootstrap Docker de vllm.
- **Speculative decoding (DFLASH/EAGLE)** en vLLM/SGLang: engine_opts `specMethod`+`specDraftModel`(+`specNumTokens`) → en vLLM `--speculative-config` (JSON) + `--attention-backend flash_attn` si es dflash; en SGLang `--speculative-algorithm/--speculative-draft-model-path/--speculative-num-draft-tokens`. NO es un motor — es una opción de aceleración. Sintaxis de los docs oficiales; NO E2E-testeado (los modelos DFLASH son 27B+ y no caben en 8GB; vLLM necesita una build con soporte, SGLang es la ruta oficial). Los motores Docker montan un caché HF persistente (`base.build_volumes`) para no re-descargar el modelo cada run.

## Pendientes documentados
La sección "Pendientes / siguientes pasos" del README es la fuente — incluye API keys vía `keyring`, flags extra de tuning de llama.cpp (`cache-reuse`, `--prio-batch`), soporte MoE multi-parte para auto-descarga, y extender la visión a motores Docker / API (hoy corre en `llamacpp` nativo).
