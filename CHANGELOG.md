# Changelog

Todos los cambios notables de InferBench. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/).

## [Unreleased]

## [0.2.0] - 2026-08-16

Segunda versión pública. Suma dos capacidades nuevas —**servir** un modelo por **MCP** y
**generar imágenes** en local— y una forma de medir que antes no existía: **cuánta calidad
cuesta de verdad cada cuantización** (perplejidad + divergencia KL contra la referencia).
Además arregla fallos que **solo aparecían en la app empaquetada**, incluido uno que dejaba
InferBench inservible en **macOS**.

### Añadido
- **Vista Calidad — el daño real de cuantizar, medido**: `llama-perplexity --kl-divergence`
  compara cada cuantización en disco contra la mejor disponible y reporta **perplejidad,
  KL y % de tokens en los que el modelo elige la misma palabra** que la referencia. Corpus
  fijo bilingüe EN+ES (dominio público) para que las medidas sean comparables entre runs; se
  mide en CPU por defecto para no competir por la VRAM. Primera medida real sobre
  Llama-3.2-1B: a Q6_K la perplejidad sube un **0,54 %** y aun así el modelo cambia de token
  **1 de cada 13 veces** — la perplejidad tapa el daño, la KL no.
- **Piso de calidad en las recomendaciones** (`≥Q4_K_M` por defecto, `quality_floor=false`
  para ver la lista completa) y **bits/peso publicados** en cada tarjeta, en ámbar por debajo
  de 4. El Dashboard recomendaba modelos enormes a 1,5 bits sin ningún aviso, contradiciendo
  el piso que el propio optimizador ya aplicaba en la tabla de Benchmark.
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
- **Exportar el historial** a **CSV y JSON** desde la vista Historial.
- **Arranque de un solo click** desde el escritorio: instalador one-click por usuario (sin
  UAC), instancia única, reuso de un backend sano en el `:7777` y cierre que se lleva el
  árbol entero del sidecar. Log del sidecar en `%APPDATA%\InferBench\logs\backend.log`.
- **Identidad de marca Fervon** (tema forja) en la app y en la landing.
- **Export a lookspan**: cada run manda también el **texto** del prompt, no solo su id.
- **[Roadmap de comunidad](docs/COMMUNITY-ROADMAP.md)** con las mejoras priorizadas.

### Cambiado
- **El binario que se distribuye se construye desde `uv.lock`** y con Python 3.11 fijo, igual
  que CI. Antes el release resolvía dependencias libres: CI validaba unas versiones y el
  instalador se empaquetaba con otras que nadie había probado. El release **corre la suite
  antes de empaquetar**, así que ya no se puede publicar una rama rota.
- **CI en los tres sistemas** (Linux, macOS, Windows). Se distribuía para tres y se probaba
  en uno; ahí estaba escondido el fallo de macOS.
- **Soporte del SDK `mcp` 2.x** (se retira el techo `mcp<2`), compatible con 1.x.
- **Docker deja de penalizar el arranque**: la disponibilidad del daemon se cachea y el
  estado de todos los motores sale de una sola llamada. `/api/health` **703 → 2,8 ms** y
  `/api/engines` **1815 → 35 ms** con Docker levantado.
- **Escaneo de GGUFs locales de 6,8 s a 30 ms** cacheando la metadata leída del fichero.

### Corregido
- **InferBench no arrancaba ningún benchmark en macOS**: `psutil.cpu_freq` no existe como
  atributo en macOS y tumbaba la detección de hardware entera — y con ella el benchmark, el
  dashboard y el listado de compatibilidad. Llevaba ahí desde siempre.
- **La app empaquetada perdía TODO el historial al cerrarse**: la base de datos caía en el
  directorio temporal que PyInstaller crea y borra en cada arranque. Ahora vive en
  `%APPDATA%\InferBench\`.
- **Al instalador le faltaban ficheros de datos**: las dos imágenes de visión y el texto de
  contexto largo no se empaquetaban, así que **3 de los prompts estaban rotos** en la app
  instalada.
- **Si el backend se caía, la app se quedaba "offline" para siempre**: ahora lo relanza con
  backoff y avisa con un diálogo claro si se agota.
- **Runs fantasma**: un benchmark interrumpido se quedaba "en curso" en el Historial sin
  forma de pararlo. Se reconcilian al arrancar (estado nuevo `interrupted`) y `/stop` cierra
  la fila colgada en vez de devolver 404.
- **Los GGUF de visión de disco no se podían lanzar y fallaban en silencio**: el motor
  arrancaba con `--mmproj` mientras el gate descartaba el prompt de imagen, y el run
  terminaba sin resultados ni error. Además, los ficheros `mmproj-*.gguf` salían en el
  listado como si fueran modelos ejecutables.
- **El handshake MCP anunciaba la versión del SDK** (`v1.27.2`) como si fuera la de
  InferBench, que es el número que se ve en el cliente.
- **La UI mentía sobre el estado de los motores**: `stablediffusion` se anunciaba como "no
  implementado" pese a estar instalado y funcionando, el chip de Docker salía vacío y las
  etiquetas de estado no estaban traducidas.
- **Un motor Docker que no cabe se rechaza en 5 s en vez de esperar 600**, comparando la VRAM
  que pide el modelo en fp16 contra la realmente disponible.
- El **LLM-judge** troceaba un número fuera de rango y lo convertía en una nota falsa.
- **KV cache vacío** en el export CSV y en la comparación de runs.
- Los mensajes del backend que ve el usuario están **todos en inglés** (contrato verificado
  por test sobre el AST, sin excepciones pendientes).
- Revisión exhaustiva de **UI** y **backend** con jueces adversariales: fuga del intervalo de
  polling en Serve, estado `disk` que faltaba en el icono de compatibilidad, RAM pico ausente
  en Historial, fuga del tope de runners en los sweeps, offload MoE recalculado con el quant
  equivocado (riesgo de OOM real), errores que desaparecían del panel en vivo, y confusión
  entre tags distintos del mismo modelo base en Ollama.

### Seguridad
- El detalle de Ollama **ya no filtra la ruta absoluta** del usuario.
- Landing: `astro` 6.4.4 → 6.4.8, que cierra un SSRF y un XSS.

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
