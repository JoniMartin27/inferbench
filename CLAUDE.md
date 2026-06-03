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
- **`detect_hardware()` cacheado** (`lru_cache`) — no lo "des-cachees"; el listado de compat depende de que sea instantáneo.
- **Evaluación de calidad** en 3 modos (`core/benchmark.py`): scorer offline basado en referencia (default, sin GPU/API), LLM-judge `self` y `api`. El default DEBE seguir funcionando en cualquier ordenador.
- **Visión multimodal real** (`llamacpp` nativo): los modelos con tag `vision` declaran su `mmproj` en `hf_gguf.mmproj`; `model_manager.ensure_mmproj` lo descarga, el bootstrap arranca llama-server con `--mmproj` y los prompts `vision-scene`/`vision-count` mandan imágenes reales (`data/vision_*.png`, generadas por `scripts/make_vision_test.py`) por la API OpenAI-vision. El gating de `run()` omite prompts con imagen en modelos no-visión. NO mandes imágenes sin mmproj cargado.
- **Calidad por checklist** (`core/benchmark.py::_quality_keywords`): si un `Prompt` define `keywords` (lista de grupos de sinónimos = el ground-truth), la nota es la fracción de grupos presentes en la respuesta (normalizado sin acentos, ES/EN). Es el scorer de los prompts de visión — mide corrección real, no F1 de tokens. El LLM-judge NO lo sustituye (no ve la imagen). Para tareas con hechos verificables, prefiere `keywords` sobre `reference`.

## Pendientes documentados
La sección "Pendientes / siguientes pasos" del README es la fuente — incluye API keys vía `keyring`, flags extra de tuning de llama.cpp (`cache-reuse`, `--prio-batch`), soporte MoE multi-parte para auto-descarga, y extender la visión a motores Docker / API (hoy corre en `llamacpp` nativo).
