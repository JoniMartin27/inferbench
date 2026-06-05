# Changelog

Todos los cambios notables de InferBench. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Añadido
- **Generación de imagen** (local): InferBench orquesta también **modelos de imagen** vía
  **[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)**, reutilizando
  **el mismo patrón** que con llama.cpp (binario CUDA precompilado de los releases de GitHub +
  pesos GGUF/safetensors de HuggingFace + server HTTP residente). Vive **dentro del modo
  Serve** y comparte el **slot único** (una GPU = un modelo a la vez, texto **o** imagen).
- **Motor `stablediffusion`** (nativo, `sd-server` en el puerto `7861`): se registra como
  motor local de **imagen**; el `ServeManager` discrimina por **modalidad** del modelo qué
  binario/instalador/args usar.
- **Catálogo con modalidad**: el schema `Model` gana el campo `modality`
  (`"text"` por defecto, `"image"` para difusión) + campos de imagen (`default_steps`,
  `default_size`) y soporte de **archivos auxiliares** (t5xxl/clip_l/vae para FLUX,
  generalizando el patrón del `mmproj` de visión). Se añaden al catálogo un modelo single-file
  garantizado (**SD-Turbo**, `sd-turbo`) como default y **FLUX.1-schnell Q4**
  (`flux.1-schnell-q4`, multi-archivo) como showcase.
- **Endpoint REST `POST /api/serve/generate`**: genera una imagen con el modelo de imagen
  servido (proxy a la API AUTOMATIC1111-compatible `/sdapi/v1/txt2img`); devuelve el PNG como
  data URL + seed, tamaño, steps y `elapsed_s`. **HTTP 409** si no hay un modelo de imagen en
  fase `ready`.
- **Tool MCP `generate_image`**: genera contra el modelo de imagen servido y **devuelve la
  imagen** (como `ImageContent` del SDK MCP, para que Claude Desktop la **muestre**) + una
  línea con seed y tiempo.
- **GenerateCard** en la vista Serve: cuando el modelo servido es de imagen, en vez del
  mini-chat aparece un panel de generación (prompt, negative prompt, steps, presets de tamaño,
  seed con botón aleatorio, **preview** de la imagen y badge de tiempo). El selector de modelo
  agrupa por modalidad y el panel MCP lista también `generate_image`. Documentado en
  [docs/IMAGE.md](docs/IMAGE.md).
- **Modo Serve / MCP**: además de benchmarkear, InferBench puede **servir** un modelo
  cuantizado de forma **residente** y exponerlo a cualquier app por **MCP** (Model Context
  Protocol). Reusa la tubería existente (hardware → optimizador → descarga GGUF → arranque del
  motor): elige la cuantización óptima para tu hardware, arranca el motor y enruta la
  inferencia. v1 soporta el motor `llamacpp` (nativo) y un solo modelo a la vez.
- **Vista Serve** en la app: elige modelo (o "recomendar para mi hardware") con cuantización
  **Auto (óptimo)**, sírvelo viendo fase/progreso hasta `ready`, pruébalo en un mini-chat y
  copia el snippet de **Conectar por MCP** para Claude Desktop / Cursor.
- **Endpoints REST `/api/serve/*`**: `load` (arranca el motor en background, no bloquea),
  `status`, `chat` (proxy de chat) y `unload` (libera VRAM).
- **Servidor MCP `inferbench`** con dos transportes que comparten una sola definición de
  tools: **HTTP** montado bajo `/mcp` en el backend (`http://localhost:7777/mcp`) y **stdio**
  vía el flag `--mcp` del sidecar (`inferbench-backend.exe --mcp`) para Claude Desktop /
  Cursor. Tools: `list_models`, `recommend_models`, `get_hardware`, `serve_model`,
  `serve_status`, `chat`, `stop_model`. Documentado en [docs/MCP.md](docs/MCP.md).
- **Modos / Features** en Ajustes: toggles para **Benchmark** y **Serve / MCP** (ambos ON por
  defecto, persistidos en `localStorage`); el sidebar oculta los ítems del modo desactivado.
  Es una sola app unificada — nunca se pueden desactivar los dos a la vez.

## [0.1.1] - 2026-06-05

### Añadido
- **UI bilingüe ES/EN** con autodetección de idioma y selector manual.
- **Screenshots estáticos** en el README como fallback del GIF de demo.

### Seguridad
- **Verificación de checksum SHA-256** de los binarios descargados: se compara contra el
  `digest` que publica la API de GitHub (un mismatch borra el fichero y aborta; si la
  release no expone digest, se registra el hash calculado). Cierra el item de checksum del
  roadmap de hardening.

### Corregido
- `/api/keys` devuelve **503** con mensaje claro si el keyring del SO no está disponible
  (antes era un 500 opaco en un arranque en frío de Windows).
- El fallo de Docker al pedir logs se registra en vez de tragarse en silencio.

## [0.1.0] - 2026-06-03

### Añadido
- **Catálogo de 124 modelos** (antes 15), todos verificados contra HuggingFace: visión
  (Qwen2-VL, Qwen2.5-VL, MiniCPM-V), código (Code Llama, CodeGemma, StarCoder2, Yi-Coder…),
  reasoning (QwQ, DeepScaleR, Sky-T1…), MoE y muchas familias más.
- **Tooling de catálogo** en `backend/scripts/` (`verify_models.py`, `merge_models.py`):
  verifica el repo GGUF, deriva el `file_template` real y valida contra el schema.
- **Compresión de KV-cache explicada**: 5 presets con qué hace / en qué afecta / qué
  permite, y tabla de los **modelos más potentes que caben con cada compresión**
  (`GET /api/optimize/by-compression`).
- **Evaluación de calidad en 3 modos**: scorer offline basado en referencia (default, sin
  GPU/API), LLM-judge con el motor local, y LLM-judge por API externa.
- `GET /api/optimize/recommendations` — modelos más potentes ejecutables en tu hardware.
- Suite de tests `pytest` (compat, optimizer, lector GGUF, scorer, seguridad) y CI en
  GitHub Actions (lint + tests backend, build frontend).

### Cambiado
- **Rendimiento**: `detect_hardware()` cacheado → el listado de compatibilidad pasó de
  ~87 ms a ~4 ms para 124 modelos.
- La cuenta de **parámetros** de GGUFs locales se calcula desde la metadata real
  (independiente del quant), no estimando por tamaño de archivo.

### Seguridad
- Defensa contra **DNS-rebinding**: la API local valida la cabecera `Host` (solo loopback).
- Descarga de binarios restringida a **hosts de GitHub** (anti redirect malicioso).

### Corregido
- Los badges de estado del Historial ya no se desbordan sobre el panel de comparación.

Primera versión pública: auto-bootstrap (binario + modelo + motor + benchmark), modo
nativo sin Docker para llama.cpp, detección de hardware, optimizador, sweep multi-quant,
comparación de runs, SSE en vivo y persistencia SQLite.
