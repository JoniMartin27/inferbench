# Changelog

Todos los cambios notables de InferBench. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/).

## [Unreleased]

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

## [0.1.0]
- Primera versión pública: auto-bootstrap (binario + modelo + motor + benchmark), modo
  nativo sin Docker para llama.cpp, detección de hardware, optimizador, sweep multi-quant,
  comparación de runs, SSE en vivo y persistencia SQLite.
