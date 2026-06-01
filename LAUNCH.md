# Plan de lanzamiento — InferBench

Guía para llevar InferBench de "repo público" a "repo con tracción". Orden pensado por impacto.
No es un documento de desarrollo: es marketing. Bórralo o muévelo a un wiki cuando sobre.

---

## Fase 0 — Antes de mover un dedo en redes (bloqueantes)

- [x] Repo público en GitHub.
- [x] LICENSE (MIT) en la raíz.
- [x] README con cabecera orientada a conversión + sección Descargar.
- [ ] **Grabar `assets/demo.gif`** (ver `assets/README.md`). **Esto es lo que más convierte. No lances sin GIF.**
- [ ] **Publicar una Release con binarios** (`.exe` / `.dmg` / `.AppImage`). Sin binario descargable pierdes ~80% de las estrellas potenciales.
  - `scripts\build-sidecar.ps1` → `cd frontend && npm run electron:build` → subir los artefactos de `frontend/release/` a una GitHub Release `v0.1.0`.
- [ ] Comprobar que un usuario nuevo puede: descargar → instalar → benchmarkear un modelo pequeño (Llama 3.2 1B) sin leer nada. Si se atasca, arréglalo antes de lanzar.
- [ ] Añadir 1-2 capturas estáticas al README como fallback del GIF.

## Fase 1 — Pruebas sociales en el propio repo

- [ ] Publicar **un benchmark real tuyo** en el README o en `docs/results.md`: tu GPU + modelo + quant → tok/s, TTFT, VRAM. Ej: "RTX 3060 12GB · Qwen 2.5 7B Q4_K_M · 45 tok/s · TTFT 210 ms". La gente comparte y compara comparativas.
- [ ] Etiquetar 3-5 issues como `good first issue` (adaptadores ollama/vllm, tests de compat.py/optimizer.py).
- [ ] Activar GitHub Discussions (para que la gente pida modelos/motores sin abrir issues).
- [ ] Pin del repo en tu perfil de GitHub.

## Fase 2 — Distribución (de aquí salen las estrellas)

Lanza **un canal por día**, no todos a la vez (así puedes responder comentarios y el algoritmo no te penaliza por crossposting simultáneo).

### r/LocalLLaMA  ← el de mayor ROI para esto
Es EL subreddit del tema. Le encantan las herramientas locales y las comparativas.
- Título sugerido: **"Built a desktop app that downloads, runs and benchmarks local LLM engines in one click (no Docker, no CLI) — open source"**
- Cuerpo: el problema (¿qué quant me entra? ¿a cuántos tok/s?), el GIF, "mide de verdad, no inventa números", link al repo y a la release. Pide feedback explícito, NO estrellas.
- Flair: `Resources` o `Tutorial | Guide`.
- Horario: mañana entre semana (hora US Este).

### Hacker News — Show HN
- Título: **"Show HN: InferBench – Benchmark local LLM engines with one click"**
- Primer comentario (tuyo): qué te llevó a construirlo, stack (Electron + FastAPI), qué hace distinto (mide real, multiplataforma, sin Docker), y qué falta (adaptadores vllm/sglang). La honestidad sobre limitaciones puntúa en HN.

### Otros canales (uno por día)
- [ ] **r/LocalLLM** (variante más pequeña, mismo público).
- [ ] **Discord de llama.cpp / comunidades GGUF** — canal de "show your projects".
- [ ] **X/Twitter**: hilo con el GIF + 3 frases. Etiqueta cuentas de la comunidad LLM local.
- [ ] **dev.to / Hashnode**: post "Cómo saber qué LLM te entra en tu GPU (y a cuántos tok/s) sin adivinar".
- [ ] **Awesome lists** vía PR: `awesome-local-llms`, listas de herramientas llama.cpp, `awesome-electron`.

## Fase 3 — Mantener el momentum

- [ ] Responder TODOS los comentarios/issues las primeras 48h (la velocidad de respuesta decide si un proyecto "cuaja").
- [ ] Cada feature nueva = una Release con changelog (GitHub notifica a watchers).
- [ ] Cuando cierres un adaptador real (ollama/vllm), es excusa para un nuevo post "InferBench ahora soporta X".

---

## Activo único a explotar: el ecosistema local-first

InferBench no va solo. Forma trío con **AGENT-OS** (orquestación de agentes) y **Lookspan** (observabilidad local). Casi nadie tiene un stack de agentes IA 100% local. En el README de InferBench añade una línea "Parte del stack local-first ↗" enlazando los otros dos — el tráfico se reparte entre los tres.

El post de mayor alcance no vende InferBench solo, sino la historia completa:
**"Monté un equipo de agentes IA 100% local: $0 en inferencia, $0 en observabilidad, 0 datos a la nube"** → enlaza los tres repos. Eso pega fuerte en HN/Reddit porque cuenta algo, no vende una herramienta.

---

## Métricas para saber si funciona

- Estrellas en las primeras 72h tras un post en r/LocalLLaMA: 50+ = buen indicio.
- Tráfico en *Insights → Traffic* del repo (referrers te dicen qué canal funciona).
- Descargas de la Release (proxy real de uso, más fiable que las estrellas).
