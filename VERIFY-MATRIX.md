# VERIFY-MATRIX — Porción 15: Matriz de verificación + barrido de huérfanos (inferbench)

> Auditoría SOLO LECTURA del código fuente. No se editó ninguna fuente.
> Fecha: 2026-06-29 · Backend FastAPI :7777 · Frontend React/Vite/Electron.

## Resumen

- **Barrido bidireccional**: todas las funciones de `api.js` salvo **3** se usan en alguna vista;
  todas las rutas backend tienen consumidor salvo **2** (huérfanas intencionales para MCP/CLI/futuro).
- **Contratos**: request/response coinciden en TODAS las llamadas verificadas (serve chat/generate,
  benchmark SSE, history, optimize, models/compat, keys, engines). Sin campos leídos por la UI que
  el backend no devuelva.
- **Botones muertos**: ninguno. Hay un bloque de tabla legacy en `ModelsView` bajo `{false && …}`
  (código muerto, nunca renderiza — no es un botón muerto, pero conviene limpiarlo algún día).
- **Tests**: backend `pytest -q` → **122 passed** (3.2s). Frontend NO tiene vitest configurado;
  el único test disponible (`node --test src/lib/exportResults.test.js`) → **9 passed**.

---

## 1. Barrido bidireccional de huérfanos

### 1a. Rutas backend → ¿quién las consume?

| Método | Ruta | Consumidor (api.js / MCP) | Vista / uso | Estado |
|---|---|---|---|---|
| GET | `/api/health` | `api.health` | App.jsx (polling) | OK |
| GET | `/api/hardware` | `api.hardware` + MCP `get_hardware` | Guide, Dashboard, Settings | OK |
| GET | `/api/engines` | `api.listEngines` | App, Guide, Dashboard, Engines, Models, Benchmark | OK |
| GET | `/api/engines/{id}` | `api.getEngine` | **NINGUNA** | **HUÉRFANA (cliente muerto, ver 1b)** |
| POST | `/api/engines/{id}/start` | `api.startEngine` | EnginesView | OK |
| POST | `/api/engines/{id}/stop` | `api.stopEngine` | EnginesView | OK |
| POST | `/api/engines/{id}/install` (SSE) | `installEngine` / `engineInstallStreamUrl` | EnginesView | OK |
| GET | `/api/engines/{id}/logs` | `api.engineLogs` | **NINGUNA** | **HUÉRFANA (cliente muerto, ver 1b)** |
| GET | `/api/models` | `api.listModels` + MCP `list_models` | App, Benchmark, Serve | OK |
| GET | `/api/models/local` | `api.listLocalModels` | Guide, Models | OK |
| GET | `/api/models/local/dirs` | `api.listSearchDirs` | ModelsView | OK |
| POST | `/api/models/local/dirs` | `api.saveSearchDirs` | ModelsView | OK |
| GET | `/api/models/{id}` | — | **NINGUNA** | **HUÉRFANA (no hay cliente; intencional/CLI)** |
| GET | `/api/models/compat/all` | `api.modelCompat` | ModelsView (catálogo) | OK |
| POST | `/api/optimize` | `api.optimize` | Models, Benchmark (auto-reopt) | OK |
| GET | `/api/optimize/recommendations` | `api.getRecommendations` + MCP `recommend_models` | Dashboard, Serve | OK |
| GET | `/api/optimize/by-compression` | `api.getByCompression` | BenchmarkView (PowerByCompression) | OK |
| GET | `/api/optimize/quants` | `api.getQuants` | BenchmarkView | OK |
| GET | `/api/optimize/model-engines` | `api.getModelEngines` | BenchmarkView (EngineMatrix) | OK |
| POST | `/api/benchmark/run` | `api.startBenchmark` | useBenchmarkRun (Benchmark) | OK |
| GET | `/api/benchmark/{run_id}/stream` (SSE) | `subscribeBenchmark` / `benchmarkStreamUrl` | useBenchmarkRun | OK |
| POST | `/api/benchmark/{run_id}/stop` | `api.stopBenchmark` | useBenchmarkRun | OK |
| POST | `/api/benchmark/sweep` | `api.startSweep` | BenchmarkView | OK |
| GET | `/api/benchmark/sweep/{id}` | `api.sweepStatus` | BenchmarkView (pollSweep) | OK |
| POST | `/api/benchmark/sweep/{id}/stop` | `api.stopSweep` | **NINGUNA** | **HUÉRFANA (cliente muerto, ver 1b)** |
| GET | `/api/history` | `api.listHistory` | App, Guide, Dashboard, History | OK |
| GET | `/api/history/compare/runs` | `api.compareHistory` | HistoryView | OK |
| GET | `/api/history/{run_id}` | `api.getHistory` | HistoryView | OK |
| DELETE | `/api/history/{run_id}` | `api.deleteHistory` | HistoryView | OK |
| GET | `/api/keys` | `api.listKeys` | SettingsView | OK |
| POST | `/api/keys` | `api.saveKey` | SettingsView | OK |
| DELETE | `/api/keys/{provider}` | `api.deleteKey` | SettingsView | OK |
| POST | `/api/serve/load` | `api.serveLoad` + MCP `serve_model` | ServeView | OK |
| GET | `/api/serve/status` | `api.serveStatus` + MCP `serve_status`/`serve_model` | ServeView | OK |
| POST | `/api/serve/chat` | `api.serveChat` + MCP `chat` | ServeView (ChatCard) | OK |
| POST | `/api/serve/generate` | `api.serveGenerate` + MCP `generate_image` | ServeView (GenerateCard) | OK |
| POST | `/api/serve/unload` | `api.serveUnload` + MCP `stop_model` | ServeView | OK |
| (mount) | `/mcp` (streamable HTTP) | servidor MCP externo (Claude Desktop/Cursor) | ServeView muestra la URL | OK (consumo externo) |

**Rutas huérfanas (sin ningún consumidor real):**
- `GET /api/engines/{id}` — definida en `api.js` como `getEngine` pero **NUNCA llamada** → cliente muerto.
- `GET /api/engines/{id}/logs` — definida como `api.engineLogs` pero **NUNCA llamada** → cliente muerto.
  (No hay panel de logs de motor en la UI; los logs se ven dentro del RunningPanel del benchmark vía SSE.)
- `POST /api/benchmark/sweep/{id}/stop` — definida como `api.stopSweep` pero **NUNCA llamada**: el
  sweep se cancela en cliente con `sweepCancelRef` (deja de pollear) pero no se aborta la corrida en
  curso en el backend. *Funcionalmente no es un bug bloqueante* (la corrida actual termina y el loop
  no sigue), pero el botón de cancelar sweep no existe en la UI → el endpoint queda sin uso.
- `GET /api/models/{id}` — sin función en `api.js`; útil para CLI/MCP futuro. Dejar.

> NOTA (no borrar a ciegas): `getEngine`, `engineLogs`, `stopSweep` y `/api/models/{id}` pueden ser
> deliberados para MCP/CLI/depuración. Son SEGUROS de mantener; documentados aquí para que el dueño
> decida. Candidato más claro a cablear de verdad: un botón "Cancelar sweep" → `api.stopSweep`.

### 1b. Funciones de api.js → ¿qué vista las llama? (funciones muertas)

| Función api.js | Vista(s) que la usan | Estado |
|---|---|---|
| `health` | App.jsx | viva |
| `hardware` | Guide, Dashboard, Settings | viva |
| `listEngines` | App, Guide, Dashboard, Engines, Models, Benchmark | viva |
| `getEngine` | — | **MUERTA** |
| `startEngine` | EnginesView | viva |
| `stopEngine` | EnginesView | viva |
| `engineLogs` | — | **MUERTA** |
| `engineInstallStreamUrl` | (usado por `installEngine` internamente) | viva (indirecta) |
| `installEngine` (export) | EnginesView | viva |
| `listModels` | App, Benchmark, Serve | viva |
| `listLocalModels` | Guide, Models | viva |
| `listSearchDirs` | ModelsView | viva |
| `saveSearchDirs` | ModelsView | viva |
| `modelCompat` | ModelsView | viva |
| `optimize` | Models, Benchmark | viva |
| `getRecommendations` | Dashboard, Serve | viva |
| `getQuants` | BenchmarkView | viva |
| `getModelEngines` | BenchmarkView | viva |
| `getByCompression` | BenchmarkView | viva |
| `startBenchmark` | useBenchmarkRun | viva |
| `stopBenchmark` | useBenchmarkRun | viva |
| `benchmarkStreamUrl` | subscribeBenchmark | viva (indirecta) |
| `subscribeBenchmark` (export) | useBenchmarkRun | viva |
| `listHistory` | App, Guide, Dashboard, History | viva |
| `getHistory` | HistoryView | viva |
| `deleteHistory` | HistoryView | viva |
| `compareHistory` | HistoryView | viva |
| `listKeys` / `saveKey` / `deleteKey` | SettingsView | vivas |
| `startSweep` | BenchmarkView | viva |
| `sweepStatus` | BenchmarkView | viva |
| `stopSweep` | — | **MUERTA** |
| `serveLoad` / `serveStatus` / `serveChat` / `serveGenerate` / `serveUnload` | ServeView | vivas |
| `humanizeError` (export) | Models, History, Settings, Serve, Benchmark | viva |

**Funciones muertas confirmadas:** `getEngine`, `engineLogs`, `stopSweep` (3).

### 1c. Botones / acciones por vista → ¿disparan llamada real?

| Vista | Control | Llamada real | OK |
|---|---|---|---|
| Guide | Botones "ir a paso X" | navegación interna (`onNavigate`) — sin red por diseño | OK |
| Dashboard | "Lanzar benchmark" / filas recomendadas / "ver" | navegación a Benchmark/History con payload | OK |
| Models | tabs catalog/local, filtros, búsqueda | cliente (recálculo local) | OK |
| Models | cambio engine/quant/kv/ctx/moe | `modelCompat` (debounced 250ms) | OK |
| Models | "Optimizar" (fila) | `optimize` | OK |
| Models | "Rescan" / "Guardar dirs" | `listLocalModels`+`listSearchDirs` / `saveSearchDirs` | OK |
| Models | "Benchmark" (fila local / óptimo) | navegación con payload localModel/config | OK |
| Engines | "Refrescar" | `listEngines` | OK |
| Engines | "Iniciar" / "Instalar+iniciar" | `installEngine` (si nativo) + `startEngine` | OK |
| Engines | "Parar" | `stopEngine` | OK |
| Benchmark | "Lanzar" | `startBenchmark` (via hook) → SSE | OK |
| Benchmark | "Sweep N" | `startSweep` + `sweepStatus` polling | OK |
| Benchmark | "Parar" | `stopBenchmark` | OK |
| Benchmark | EngineMatrix (clic fila) | set engine local (datos de `getModelEngines`) | OK |
| Benchmark | toggles prompts/compresión/dflash/judge | estado local; entran en el body de `startBenchmark` | OK |
| Serve | "Servir" | `serveLoad` + `serveStatus` polling | OK |
| Serve | "Parar" | `serveUnload` | OK |
| Serve | Chat "Enviar" | `serveChat` | OK |
| Serve | Generar imagen | `serveGenerate` + descarga cliente | OK |
| Serve | "Copiar" (endpoint / MCP snippets) | clipboard (sin red) | OK |
| History | seleccionar run | `getHistory` | OK |
| History | "Comparar" (≥2) | `compareHistory` | OK |
| History | "Borrar" (papelera) | `deleteHistory` (optimista + revert) | OK |
| History | "CSV"/"JSON" export | descarga cliente (`exportResults.js`) — sin red | OK |
| Settings | idioma / modos | localStorage + evento (sin red) | OK |
| Settings | API keys guardar/borrar | `saveKey` / `deleteKey` / `listKeys` | OK |

Ningún botón muerto. (`{false && <Card legacy>}` en ModelsView es código muerto inerte, no un control.)

---

## 2. Matriz de verificación VIVA (qué clicar para confirmar el wiring desde el front)

Leyenda peso: **L** = ligero (solo lee datos, sin GPU/descargas) · **P** = pesado
(descarga GGUF/binario o ejecuta motor con GPU; desde el front solo se puede confirmar el *wiring*:
que arranca, emite eventos y surface errores — el resultado numérico exige hardware/red reales).

### Guía
- [ ] **L** Abrir la app: la vista "Guía" carga sin spinner colgado; los 6 pasos muestran detalle
  (hardware detectado, nº motores listos, nº modelos locales, nº runs). → confirma `hardware`,
  `listEngines`, `listLocalModels`, `listHistory`.
- [ ] **L** Barra de progreso refleja pasos hechos; los botones "ir a…" navegan a la vista correcta.

### Dashboard
- [ ] **L** Cards superiores muestran GPU/RAM/Motores/Runs con valores reales (no "—" si hay hw).
- [ ] **L** Secciones "Full-GPU / MoE / Parcial" listan modelos recomendados → confirma
  `getRecommendations`. Clic en una fila → abre Benchmark con la config precargada.
- [ ] **L** "Hardware" detalla CPU/cores/freq/RAM/GPU; "Última actividad" lista hasta 5 runs.

### Modelos
- [ ] **L** Tab "Catálogo": cambiar Engine/Quant/KV/Contexto/MoE recalcula la tabla (status por fila)
  → confirma `modelCompat` (con debounce). Filtros (full_gpu/compat/all), familia y búsqueda funcionan.
- [ ] **L** Botón "Optimizar" de una fila abre la card de config óptima + técnicas → `optimize`.
- [ ] **L** Tab "Local": "Rescan" repuebla la tabla de GGUFs locales; "Carpetas escaneadas" muestra
  conocidas + extra; editar+Guardar persiste → `listLocalModels`, `listSearchDirs`, `saveSearchDirs`.
- [ ] **L** "Benchmark" de un GGUF local navega a Benchmark con `localModel` precargado.

### Motores
- [ ] **L** Lista de motores con badges de runtime (native/docker) y estado; "Refrescar" recarga.
- [ ] **L** (estado) Banner de Docker no disponible aparece si `health.docker.available === false`.
- [ ] **P** "Instalar + iniciar" de **llama.cpp** (nativo): descarga el binario con barra de progreso
  SSE y luego arranca → confirma `installEngine` (stream) + `startEngine`. *Requiere red (descarga).*
- [ ] **P** "Iniciar" de un motor Docker (vLLM/SGLang/TGI): requiere Docker+GPU; desde el front se
  confirma que dispara `startEngine` y surface error claro (503) si Docker está apagado.
- [ ] **L** "Parar" un motor en running → `stopEngine`, el estado vuelve a missing/exited.
- [ ] **L** Ollama no instalado: "Iniciar" muestra error con enlace de instalación (no dispara /install).

### Benchmark
- [ ] **L** Selector de motor deshabilita los no instalados; EngineMatrix puebla scores por motor
  → `getModelEngines`. Selector de quant muestra status real por quant → `getQuants`.
- [ ] **L** Presets de compresión, prompts, judge, dflash (solo vLLM/SGLang) togglean estado local.
- [ ] **L** Tabla "Potencia por compresión" se rellena al cambiar motor/contexto → `getByCompression`.
- [ ] **P** "Lanzar" con llama.cpp: arranca el run, el RunningPanel pinta fases (bootstrap → ttft →
  tokens → result) vía SSE → confirma `startBenchmark` + `subscribeBenchmark`. *Primer run descarga
  binario+GGUF (pesado); ejecución real necesita GPU.* La tabla de resultados aparece al terminar.
- [ ] **P** "Sweep N quants": lanza secuencialmente → `startSweep` + `sweepStatus` polling; el panel
  re-suscribe a cada sub-run.
- [ ] **L** "Parar" durante un run → `stopBenchmark`; la UI se desbloquea (estado running→null).
- [ ] **L** (errores) Matar el backend a mitad de stream → el panel muestra "Se perdió la conexión"
  (rama `stream_error`) y desbloquea la UI.

### Serve
- [ ] **L** Selector de modelo (catálogo agrupado texto/imagen) y fuente "recomendados"
  → `listModels`, `getRecommendations`.
- [ ] **P** "Servir" un LLM texto pequeño: StatusCard pasa downloading→starting→ready, muestra el
  endpoint OpenAI → `serveLoad` + `serveStatus` polling. *Pesado: descarga+GPU.*
- [ ] **P** Chat "Enviar" cuando ready: respuesta del modelo + tok/s → `serveChat`
  (lee `content`/`tps`, ambos presentes en el backend).
- [ ] **P** Servir un modelo de imagen (sd-turbo/flux) y "Generar": muestra la imagen + seed/tiempo
  → `serveGenerate` (lee `image_b64`/`seed`/`elapsed_s`, todos presentes). "Descargar" guarda el PNG.
- [ ] **L** "Parar" libera el slot → `serveUnload`. Snippets MCP (stdio/HTTP) se copian al portapapeles.

### Historial
- [ ] **L** Lista de runs; seleccionar uno muestra detalle (stats + gráfico tok/s + tabla de prompts)
  → `getHistory`. Campos `prefill_tps/tps_std/ttft_std/n_samples/ctx_used/vram_gb/quality` presentes.
- [ ] **L** Marcar ≥2 + "Comparar" → tabla + 4 gráficos (tps/ttft/quality/vram) → `compareHistory`.
- [ ] **L** "Borrar" (papelera): la fila desaparece al instante y se confirma con toast → `deleteHistory`
  (optimista con revert si falla).
- [ ] **L** "CSV"/"JSON" descargan el run/comparación (sin pasar por backend).

### Settings
- [ ] **L** Cambiar idioma (ES/EN) reescribe la UI; toggles de modos (Benchmark/Serve) ocultan/muestran
  ítems del sidebar (no se puede apagar el último).
- [ ] **L** Hardware/GPUs se muestran → `hardware`.
- [ ] **L** API keys: guardar una key muestra badge "guardada" (sin exponer el valor); borrar la quita
  → `saveKey`/`deleteKey`/`listKeys`. Si keyring no está disponible, error 503 humanizado.

---

## 3. Suite completa backend

Comando: `cd backend && pytest -q` (vía `.venv\Scripts\python.exe -m pytest -q`)

```
122 passed, 1 warning in 3.19s
```

- 17 ficheros de test (api, benchmark_rigor, compat, gguf_reader, gpu_safety, image_serve, keys,
  lookspan, mcp, multimodal, multipart, optimizer, quality, security, serve, speculative).
- Único warning: `StarletteDeprecationWarning` (httpx + TestClient) — informativo, no afecta.

## 4. Tests frontend

- **No hay vitest** configurado (`vitest` ausente de package.json; no existe binario en node_modules).
  `npx vitest run` no aplica en este proyecto.
- El proyecto usa `node --test` para una suite de utilidades de export:
  `node --test src/lib/exportResults.test.js` → **9 passed** (script `test:unit`).

---

## Conclusión

El enlazado front⇄back está **sano**: contratos coherentes en todas las llamadas vivas, SSE con
nombres de evento idénticos entre `core/benchmark.py` y `subscribeBenchmark`, y sin botones muertos.
Los únicos hallazgos accionables son **3 funciones de cliente muertas** (`getEngine`, `engineLogs`,
`stopSweep`) y **1 ruta sin cliente** (`/api/models/{id}`), todas no destructivas. La oportunidad más
útil sería cablear un botón "Cancelar sweep" a `api.stopSweep` (hoy el sweep solo se cancela en cliente
sin abortar la corrida backend en curso). Lo demás solo se valida del todo con GPU/descargas (marcado
**P** arriba) — desde el front se confirma el wiring (dispara, emite eventos, surface errores).
