# Instrucciones para Claude Code en este proyecto

## Lectura obligatoria al iniciar
1. Lee `PROJECT_BRIEF.md` completo.
2. Lee este archivo.
3. No empieces a escribir código hasta haber confirmado el plan de hitos con el usuario.

## Filosofía de trabajo

**Construye en hitos pequeños, verificables, ejecutables.** Cada hito debe terminar con algo que el usuario pueda probar (un endpoint, una pantalla, un comando).

**No asumas: pregunta o busca en `PROJECT_BRIEF.md`.** Si una decisión no está documentada, pregunta antes de inventar.

**Schemas por motor:** las optimizaciones NO son uniformes. llama.cpp tiene flags distintas a vLLM. APIs cloud no admiten optimización local. Esto está en `PROJECT_BRIEF.md`, sección "Schema de optimizaciones POR MOTOR".

## Hitos sugeridos (en este orden)

### M1 — Backend: detección de hardware
- `backend/core/hardware.py` con función `detect_hardware()` → CPU, RAM, GPU(s) NVIDIA/AMD/Apple/CPU-only
- `backend/api/hardware.py` con `GET /api/hardware`
- Test manual: `curl localhost:7777/api/hardware` devuelve JSON correcto

### M2 — Backend: gestión de motores Docker
- `backend/core/docker_mgr.py` con métodos `start`, `stop`, `status`, `logs`
- `backend/engines/base.py` clase abstracta `Engine`
- `backend/engines/llamacpp.py` como primera implementación concreta
- `backend/api/engines.py` endpoints
- Test: arrancar/detener llama.cpp via API

### M3 — Backend: catálogo de modelos y compatibilidad
- `backend/data/models.json` con catálogo inicial (10-15 modelos)
- `backend/core/compat.py` con `check_compat()` y `compute_max_context()`
- `backend/api/models.py` endpoints
- Test: `GET /api/models/compat?engine=llamacpp` devuelve compatibilidad realista

### M4 — Backend: benchmark con SSE
- `backend/core/benchmark.py` ejecución real (vía API HTTP de cada motor)
- `backend/api/benchmark.py` con stream SSE
- `backend/db.py` SQLite + persistencia de runs
- `backend/api/history.py`
- Test: `POST /api/benchmark/run` y consumir el stream

### M5 — Frontend: Electron + Vite + React scaffold
- Crear estructura `frontend/`
- Configurar Vite + Tailwind + Electron
- Cliente API en `frontend/src/api.js`
- Test: app abre ventana en blanco con conexión al backend

### M6 — Frontend: portar prototipo
- Copiar componentes del prototipo (Dashboard, Engines, Models, Benchmark, Running, History, Settings)
- Adaptar para que tiren de `api.js` en lugar de datos hardcoded
- Test: navegar por las pantallas con datos reales del backend

### M7 — Integración benchmark live
- Conectar `RunningPanel` al SSE del backend
- Test: lanzar benchmark, ver progreso real

### M8 — Optimizador automático
- `backend/core/optimizer.py` con `get_optimal_config()`
- `POST /api/optimize`
- Botón "Optimizar para mi hardware" funcional

### M9 — Empaquetado
- electron-builder configurado para Windows / macOS / Linux
- Backend Python empaquetado con PyInstaller o como sidecar
- Documentación de instalación

## Convenciones de código

### Python
- Python 3.11+
- `ruff` para lint, `black` para formato (línea 100)
- Type hints obligatorios
- Pydantic models para todas las entradas/salidas de la API
- Logging con `loguru`
- No `print()` en producción

### JavaScript / React
- Sin TypeScript en MVP (acelera iteración). Migrable luego.
- Componentes funcionales con hooks
- Tailwind para estilos, NO CSS modules
- ESLint + Prettier
- Cliente HTTP: `fetch` nativo o `ky` (no axios)

### Git
- Commits pequeños, mensaje en presente: "add hardware detection"
- Una rama por hito: `feat/m1-hardware`, `feat/m2-engines`, etc.
- PR no necesarios en este flujo (trabajo individual)

## Cosas que NO debes hacer

- ❌ No reinventes el schema de optimizaciones por motor — está en `PROJECT_BRIEF.md`
- ❌ No guardes API keys en plano — usa `keyring`
- ❌ No bloquees el event loop con llamadas síncronas pesadas — usa `async`
- ❌ No agrupes varios hitos en un commit gigante
- ❌ No instales librerías "por si acaso" — solo lo que necesite el hito actual
- ❌ No uses TypeScript todavía (decidido para acelerar MVP)
- ❌ No añadas tests E2E hasta el M9 — sí tests unitarios donde tenga sentido

## Comandos útiles del proyecto

```bash
# Backend (desde /backend)
uv venv && source .venv/bin/activate
uv pip install -e .
uvicorn main:app --reload --port 7777

# Frontend (desde /frontend)
npm install
npm run dev          # Vite dev server
npm run electron:dev # Electron + Vite

# Build
npm run build
npm run electron:build
```

## Política sobre simulaciones / mocks

El prototipo en el artefacto usa datos simulados. **El proyecto local NO debe simular**: si un motor no está disponible, devuelve error claro al frontend; no inventes números. Único mock aceptable: tests unitarios.
