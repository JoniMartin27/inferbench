---
title: Cómo saber qué LLM te entra en tu GPU (y a cuántos tok/s) sin adivinar
published: false
tags: llm, localai, opensource, python
cover_image: https://raw.githubusercontent.com/JoniMartin27/inferbench/master/assets/inferbench-demo.gif
---

> TL;DR: monté **[InferBench](https://github.com/JoniMartin27/inferbench)**, una app de escritorio open source que, con un click, descarga el motor, baja el modelo, lo arranca con la config óptima para tu hardware y **mide de verdad** TTFT, tok/s, VRAM y calidad. Sin Docker, sin CLI, 100% local.

## El problema: demasiadas variables

Correr un LLM en local suena fácil hasta que te enfrentas a la matriz real:

- **Qué modelo** (Llama, Qwen, Gemma, Mistral, Phi…).
- **Qué cuantización** (Q4_K_M, Q5_K_M, Q8_0, IQ2…). Cada una pesa distinto y degrada distinto.
- **Qué motor** (llama.cpp, Ollama, vLLM, SGLang, TGI). Cada uno con sus flags.
- **Tu hardware** (¿cuánta VRAM libre tienes de verdad? ¿la GPU también pinta la pantalla?).

La pregunta que importa —**"¿esto me entra y a cuántos tok/s va a ir?"**— normalmente se responde a base de prueba y error, descargas de varios GB y OOMs.

## Cómo se calcula de verdad (no a ojo)

La clave es la **KV-cache**, que crece con el contexto y a menudo es lo que te saca de la VRAM. InferBench la calcula **exacta** desde la metadata del propio GGUF:

```
kv_per_token = 2 · n_layer · n_head_kv · head_dim · 2 bytes (f16)
```

Eso captura GQA/MQA correctamente (usar `n_head` en vez de `n_head_kv` infla la cuenta varias veces). Con la KV exacta + el tamaño del modelo al quant real, sabe qué contexto máximo te cabe y elige la mejor cuantización que entra.

## Por qué medir gana a estimar

Los números inventados no sirven. InferBench corre la inferencia real y:

- Descarta **una pasada de warmup** y mide **N muestras** (mediana + desviación), no una sola.
- Toma el tok/s de los **timings internos del motor** (`predicted_per_second`), no del reloj del cliente.
- Evalúa **calidad con scorers verificables**: para el prompt de código, **ejecuta** lo que genera el modelo en un sandbox y cuenta cuántos tests pasan.

Un dato real de mi equipo, medido con la propia app:

| Hardware | Modelo | tok/s | TTFT | VRAM | Calidad |
|----------|--------|-------|------|------|---------|
| RTX 3070 8GB | Qwen2.5 7B Q4_K_M | **75** | 284 ms | 7.96 GB | 100/100 |

## Del click al benchmark

![demo](https://raw.githubusercontent.com/JoniMartin27/inferbench/master/assets/inferbench-demo.gif)

1. Eliges modelo y cuantizaciones.
2. InferBench descarga el binario del motor (release oficial de llama.cpp, con verificación SHA-256) y el GGUF de Hugging Face.
3. Arranca el motor con la config óptima para tu hardware.
4. Corre la suite de prompts midiendo TTFT, tok/s, VRAM y calidad.
5. Guarda los resultados y te deja compararlos lado a lado.

llama.cpp corre **nativo, sin Docker**; Ollama / vLLM / SGLang / TGI van por Docker; y también puedes medir APIs cloud (OpenAI, Anthropic, OpenRouter, NVIDIA) con el mismo interfaz.

## Local-first de verdad

Tus datos no salen del equipo y la inferencia local cuesta $0. InferBench es parte de un stack local-first junto a un orquestador de agentes y una herramienta de observabilidad — todo sin nube.

- **Repo:** https://github.com/JoniMartin27/inferbench
- **Descarga (Win/macOS/Linux):** https://github.com/JoniMartin27/inferbench/releases/latest

Es open source (MIT). Si lo pruebas, me encantaría feedback honesto: qué motor o modelo te falta y qué se rompe.
