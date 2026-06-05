# Changelog

Todos los cambios notables de InferBench. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/).

## [Unreleased]

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
