# Borradores de posts — lanzamiento InferBench

Textos listos para copiar-pegar. **No publicados.** Revísalos y ajústalos antes de enviar.
Lanza **un canal por día** (ver `LAUNCH.md`). Sustituye el benchmark de ejemplo por uno tuyo real.

Links:
- Repo: https://github.com/JoniMartin27/inferbench
- Release: https://github.com/JoniMartin27/inferbench/releases/latest

---

## 1. r/LocalLLaMA  (mayor ROI — empezar por aquí)

**Título:**
> Built a desktop app that downloads, runs and benchmarks local LLM engines in one click — no Docker, no CLI, open source

**Cuerpo:**
```
Me cansé de adivinar qué cuantización me entra en la GPU y a cuántos tok/s va a ir, así
que construí InferBench: una app de escritorio que, con un click, descarga el binario del
motor (release oficial de llama.cpp), baja el GGUF de Hugging Face, arranca el motor con la
config óptima para tu hardware y corre una suite de benchmarks midiendo TTFT, tok/s, VRAM y
calidad. Mide de verdad — no inventa números.

- 126 modelos verificados en el catálogo (con compatibilidad calculada para TU hardware).
- llama.cpp en modo nativo (sin Docker); Ollama / vLLM / SGLang / TGI vía Docker; + APIs cloud.
- Rigor: descarta una pasada de warmup y reporta la mediana de N muestras + desviación.
- Calidad evaluada con scorers verificables (ejecuta el código que genera el modelo, etc.).
- 100% local. Tus datos no salen del equipo. MIT.

[GIF]

Ejemplo (mi equipo, medido con la propia app): RTX 3070 8GB · Qwen2.5 7B Q4_K_M ·
75 tok/s · TTFT 284 ms · 7.96 GB VRAM · calidad 100/100.

Es v0.1.1, binarios para Windows/macOS/Linux en la release. Busco feedback honesto: qué
motor/modelo os falta, qué se rompe. Repo y descarga en los comentarios.
```
- **Flair:** `Resources`
- **Horario:** mañana entre semana (hora US Este).
- Pega los links en un comentario propio, no en el cuerpo (mejor alcance).

---

## 2. Hacker News — Show HN

**Título:**
> Show HN: InferBench – Benchmark local LLM engines with one click

**URL:** https://github.com/JoniMartin27/inferbench

**Primer comentario (tuyo, nada más publicar):**
```
Autor aquí. Lo monté porque cada vez que quería correr un modelo en local perdía media hora
adivinando qué quant cabía en mi GPU y a cuántos tok/s iría. InferBench lo mide por ti:
un click descarga el binario del motor, baja el GGUF, arranca con la config óptima para tu
hardware y corre los benchmarks de verdad (TTFT, tok/s desde los timings internos del motor,
VRAM, y calidad con scorers que ejecutan el código generado).

Stack: Electron + React en el frontend, FastAPI + Python para el backend (empaquetado como
sidecar PyInstaller). llama.cpp corre nativo sin Docker; los motores Docker (vLLM/SGLang/TGI)
aplican siempre un tope de VRAM para no ahogar al compositor de pantalla en equipos de una
sola GPU (me pasó de verdad).

Qué falta y soy honesto: visión solo en llama.cpp nativo por ahora, los adaptadores Docker
de vLLM/SGLang aún no E2E-testeados en GPUs pequeñas. Feedback bienvenido.

Es parte de un stack local-first junto a un orquestador de agentes y una herramienta de
observabilidad, todo $0 y sin nube.
```
> En HN la honestidad sobre limitaciones puntúa. No pidas estrellas.

---

## 3. X / Twitter (hilo)

```
1/ ¿Quieres correr LLMs en local pero no sabes qué cuantización te entra en la GPU ni a
cuántos tok/s va a ir? Hice una app de escritorio que lo mide por ti con un click. Open
source, sin Docker, sin CLI. 🧵

[GIF]

2/ Eliges modelo → InferBench descarga el binario del motor, baja el GGUF, arranca con la
config óptima para tu hardware y corre los benchmarks midiendo TTFT, tok/s, VRAM y calidad.
Mide de verdad, no inventa números.

3/ 126 modelos verificados. llama.cpp nativo (sin Docker) + Ollama/vLLM/SGLang/TGI + APIs
cloud. 100% local: tus datos no salen del equipo. Ej. real en mi RTX 3070: Qwen2.5 7B
Q4_K_M a 75 tok/s, TTFT 284 ms.

4/ Windows / macOS / Linux. MIT. Descarga y repo 👇
github.com/JoniMartin27/inferbench
```
- Etiqueta cuentas de la comunidad LLM local.

---

## 4. dev.to / Hashnode (artículo)

**Título:** Cómo saber qué LLM te entra en tu GPU (y a cuántos tok/s) sin adivinar

**Esqueleto:**
1. El problema: la matriz modelo × quant × motor × hardware es un infierno de prueba y error.
2. Cómo se calcula de verdad: KV-cache exacta (GQA/MQA) desde la metadata GGUF, no heurística.
3. Por qué medir > estimar: warmup + mediana de N muestras, tok/s desde los timings del motor.
4. Demo: del click al benchmark (GIF).
5. Local-first: $0 de inferencia, $0 de nube. Link al repo.

---

## 5. Canales secundarios (uno por día)

- **r/LocalLLM** — misma audiencia, más pequeña. Reusa el post de r/LocalLLaMA.
- **Discord llama.cpp / comunidades GGUF** — canal "show your projects", versión corta + GIF.
- **Awesome lists vía PR:** `awesome-local-llms`, listas de herramientas llama.cpp, `awesome-electron`.

---

## Post de mayor alcance (el del ecosistema, para cuando tengas tracción)

**"Monté un equipo de agentes IA 100% local: $0 en inferencia, $0 en observabilidad, 0 datos a la nube"**
→ enlaza los tres repos (Regenta/AGENT-OS + InferBench + Lookspan). Cuenta una historia, no
vende una herramienta — por eso pega fuerte en HN/Reddit.
