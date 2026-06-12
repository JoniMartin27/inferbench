# Roadmap orientado a la comunidad — investigación 2026-06-12

Investigación multi-agente sobre qué piden los usuarios de LLMs locales que InferBench podría cubrir.
Método: 6 ángulos en paralelo (r/LocalLLaMA, Hacker News, issues de GitHub de proyectos adyacentes,
análisis de competidores, compradores de hardware, evaluación de calidad) → 61 hallazgos con fuentes →
síntesis deduplicada contra el inventario de features actual → verificación contra el código del repo.

Las mejoras 1-6 están verificadas archivo a archivo contra el repo; las 7-12 están contrastadas contra
el inventario de features (ninguna existe hoy) pero sin verificación profunda de código.

## Resumen

| # | Mejora | Prioridad | Esfuerzo | ¿Existe ya? |
|---|--------|-----------|----------|-------------|
| 1 | Leaderboard comunitario de resultados (subida opt-in) | Alta | M | No |
| 2 | Curva TTFT/prefill/decode por profundidad de contexto 0→128K | Alta | M | Parcial (bloques sueltos) |
| 3 | Informe de degradación por quant + KL-divergence | Alta | L (solo informe: S-M) | Parcial (sweep+scorers) |
| 4 | Soporte multi-GPU (split, VRAM agregada, topología) | Alta | M | Parcial (solo detección) |
| 5 | Avisos de ejecución degradada + APUs + ruta Vulkan | Alta | M | Parcial |
| 6 | Benchmark de endpoints remotos OpenAI-compat + Ollama vivo + CLI headless | Alta | M | Parcial (runner genérico) |
| 7 | Suites de prompts personalizadas (benchmark privado del usuario) | Media | M | No |
| 8 | Calculadora web "¿me cabe este modelo?" en la landing | Media | S-M | No |
| 9 | Métricas de energía: tok/W, Wh/run, idle draw | Media | S-M | No |
| 10 | Comparación multi-motor en un click (engine sweep) | Media | S-M | No (manual vía Historial) |
| 11 | Curva de offload MoE (sweep sobre `--n-cpu-moe`) | Media | M | No (optimizer planifica 1 punto) |
| 12 | Transparencia de la nota de calidad + tarjeta compartible | Media | S | Parcial |

---

## 1. Base de datos pública de resultados + leaderboard filtrable por hardware

**Qué:** botón "Compartir resultado" opt-in en HistoryView que sube el run anonimizado (GPU/CPU/RAM,
modelo, quant, motor+versión, flags, contexto, KV-quant, TTFT/pp/tg con mediana+std) a una base pública
consultable desde el website (Astro ya desplegado en Pages). Filtrable por GPU × modelo × quant × motor.
**Requisito de la comunidad:** pp, tg y TTFT SIEMPRE como métricas separadas, nunca score único condensado
(crítica principal a LocalScore). Bonus: "tu resultado vs la mediana de usuarios con tu GPU".

**Demanda:** la más repetida de toda la investigación (5 de 6 ángulos). Las preguntas "how fast is X on Y"
son el género más recurrente de r/LocalLLaMA; el Show HN de LocalScore pidió leaderboards por hardware y
compartición federada anónima; llama.cpp issue #14791 pide `--upload` para un leaderboard descentralizado;
el recurso de referencia (repo GPU-Benchmarks, 1.9k★) está congelado desde 2024.

**Estado en el repo:** toda la metadata ya se persiste (`backend/db.py`: hw_json/opts_json, medianas+std).
Falta: anonimización del payload (¡hw_json puede contener PII!), endpoint/almacén de subida,
`website/src/pages/leaderboard.astro`. Esfuerzo M.

Fuentes: [r/LocalLLaMA LocalScore](https://www.reddit.com/r/LocalLLaMA/comments/1jqn570/localscore_local_llm_benchmark/) · [Show HN LocalScore](https://news.ycombinator.com/item?id=43572134) · [llama.cpp #14791](https://github.com/ggml-org/llama.cpp/issues/14791) · [GPU-Benchmarks (congelado)](https://github.com/XiongjieDai/GPU-Benchmarks-on-LLM-Inference) · [llama.cpp disc. #4167](https://github.com/ggml-org/llama.cpp/discussions/4167)

## 2. Benchmark por profundidad de contexto: curva 0→128K

**Qué:** rellenar el contexto a profundidades configurables (0/4K/16K/32K/64K/128K, capadas al ctx máximo
que la KV-cache exacta permite) y medir TTFT, prefill y decode tok/s en cada punto. LineChart
velocidad-vs-profundidad en resultados y comparación. Opcional: cruzar con KV-quant como sweep 2D, con
aislamiento de fallos por celda (un OOM a 128K no tira el run).

**Demanda:** 5 ángulos. "Token generation tanks at long context: 30/s → 2/s" (HN, 283 pts); el propio
maintainer de llama.cpp abrió #13408 pidiendo métricas por profundidad; los defaults pp512/tg128 de
llama-bench se consideran irreales para la era de agentes a 32-128K.

**Estado en el repo:** todos los bloques existen (TTFT/prefill con mediana, needle-in-haystack fijo a ~4-5k,
KV-cache exacta, presets KV-quant, sweep secuencial, Recharts, migración aditiva). Falta el barrido.
Truco de implementación: arrancar el motor UNA vez con el ctx máximo viable y variar solo la longitud
del prompt. Esfuerzo M (el 2D completo: L).

Fuentes: [r/LocalLLaMA pp speed](https://www.reddit.com/r/LocalLLaMA/comments/1kmf2w9/is_there_a_benchmark_that_shows_prompt_processing/) · [HN](https://news.ycombinator.com/item?id=48146369) · [llama.cpp #13408](https://github.com/ggml-org/llama.cpp/issues/13408) · [llm-tracker cheat-sheet](https://llm-tracker.info/howto/LLM-Inference-Benchmarking-Cheat%E2%80%91Sheet-for-Hardware-Reviewers)

## 3. Informe de degradación por cuantización (quant × velocidad × calidad + KL-divergence)

**Qué:** sobre el sweep de quants existente, informe automático: delta de calidad por quant vs el quant más
alto usando los scorers verificables, + KL-divergence y top-token flip-rate vía `llama-perplexity
--kl-divergence` (el binario ya se descarga con la release de llama.cpp). Salida: "qué pierdes y qué ganas
en TU hardware por cada quant" + recomendación del quant óptimo por calidad medida (hoy es estática por
tamaño). Extensión: comparar el mismo modelo de distintos proveedores de quants (Unsloth/Bartowski/Ollama).

**Demanda:** 4 ángulos. Posts de comparación de quants arrasan en r/LocalLLaMA (268 pts); llama.cpp
disc. #4110: "perplexity is inaccurate — KL divergence seems better"; paper 2026: quants con la misma PPL
difieren ~9 puntos en GSM8K; la gente decide por folclore ("below Q4 isn't worth it").

**Estado en el repo:** sweep + scorers verificables + comparación manual existen. Cero KLD/logits/flip-rate.
models.json solo tiene UN proveedor GGUF por modelo. Esfuerzo: solo informe S-M; con KLD M; multi-proveedor M;
todo junto L.

Fuentes: [Unsloth Dynamic v2 KLD](https://www.reddit.com/r/LocalLLaMA/comments/1k71mab/unsloth_dynamic_v20_ggufs_llama_4_bug_fixes_kl/) · [llama.cpp disc. #4110](https://github.com/ggml-org/llama.cpp/discussions/4110) · [paper "Which Quantization Should I Use?"](https://arxiv.org/html/2601.14277v1)

## 4. Soporte multi-GPU

**Qué:** VRAM agregada en compat, flags de split en el optimizador (`--tensor-split`, `--split-mode` en
llama.cpp; `--tensor-parallel-size` en vLLM; `--tp-size` en SGLang), topología en la metadata del run
(modelo por GPU, PCIe gen/lanes, NVLink), VRAM pico por GPU. Prerequisito para que el leaderboard (1)
cubra al segmento entusiasta 2×3090/4090.

**Demanda:** 3 ángulos. LocalScore #31 ("I have to select one GPU"); MLPerf Client #17; guías 2026 enteras
solo sobre escalado multi-GPU (PCIe x4 penaliza 35-40%, NVLink +50% en TP) cuyos datos solo existen en
blogs personales.

**Estado en el repo:** la detección ya enumera N GPUs y se persiste la lista completa en hw_json; Docker ya
pasa todas las GPUs; TGI ya expone numShard. Pero TODO el pipeline compat/optimizer usa `gpus[0].vram_gb`,
no hay flags de split, y la medición de VRAM en vivo es solo GPU 0. Ojo: el cap de seguridad de display
(safe_gpu_fraction, load-bearing) también es GPU-0-only. Sin hardware multi-GPU para validar E2E (tests
mockeados). Esfuerzo M.

Fuentes: [LocalScore #31](https://github.com/cjpais/LocalScore/issues/31) · [guía multi-GPU](https://insiderllm.com/guides/multi-gpu-local-ai/) · [4×3090 vLLM bench](http://himeshp.blogspot.com/2025/03/vllm-performance-benchmarks-4x-rtx-3090.html)

## 5. Avisos de ejecución degradada + APUs con memoria unificada + ruta Vulkan

**Qué:** (a) banner imposible de ignorar cuando el run corre CPU-only o con menos capas en GPU de las
planificadas — parsear "offloaded X/Y layers" del log de llama-server + NVML en warmup, comparar plan vs
real, marcar el run como "degradado" en DB/historial/export; (b) detectar APUs con memoria unificada
(Strix Halo, Ryzen AI) que hoy quedan como `vram=0` → CPU-only; (c) ofrecer la build Vulkan oficial de
llama.cpp cuando no hay CUDA/ROCm (en Strix Halo, Vulkan triplica a HIP: 884 vs 348 pp tok/s).

**Demanda:** la mayor fuente de quejas contra los competidores. LocalScore "happily get you benchmarking
your CPU" (resultados 4× más lentos sin avisar); el grueso de sus issues son detección rota; hilo
Vulkan/Ollama con 217 pts y 228 comentarios de usuarios de iGPU ignorados. En esta categoría gana el que
"simplemente funciona" y avisa cuando no.

**Estado en el repo:** los logs ya se capturan pero nadie los parsea; el plan de offload (ngl) ya existe pero
no se compara con lo real; el fallback silencioso a CPU está reconocido solo como medida preventiva
(descarga de cudart). Vulkan está activamente EXCLUIDO en binary_manager (`EXCLUDE_TERMS_NEED`). Detección:
solo NVIDIA/AMD-dedicada/Apple. Esfuerzo M (~2-3 días las 3 piezas; pieza 1 sola ~1 día). Sin hardware APU
para validar E2E.

Fuentes: [Show HN LocalScore (crítica CPU)](https://news.ycombinator.com/item?id=43572134) · [issues LocalScore](https://github.com/cjpais/LocalScore/issues) · [hilo Vulkan/Ollama](https://hn.algolia.com/api/v1/items/42886680)

## 6. Endpoints remotos OpenAI-compatible + Ollama vivo + modo headless CLI

**Qué:** adaptador "custom-openai" (base URL + api key opcional + modelo) para correr la suite contra
cualquier servidor OpenAI-compatible en la misma máquina o en la LAN, sin que InferBench arranque nada.
Picker de modelos de una instancia Ollama viva (:11434). CLI headless (`inferbench bench --url ... --json`)
para servidores sin GUI. Documentar que sin timings internos el tok/s viene de cronometraje cliente.

**Demanda:** 3 ángulos. Show HN de LocalScore: "remote headless server... OpenAI-like API would be great" y
"Ollama integration would be nice" (su issue #25 sigue abierto); vLLM #28325 (benchmarkear sin imágenes
multi-GB) quedó stale; Jan #5474 entre los más votados.

**Estado en el repo:** el runner YA es OpenAI-compatible genérico (auto=false + base_url + api_key, con
fallback a cronometraje cliente documentado) y ollama_manager ya reutiliza el daemon vivo y salta el pull.
Falta: el allowlist anti-SSRF bloquea hosts LAN (relajarlo requiere opt-in explícito + tests de
test_security.py — es decisión de seguridad deliberada), engine id "custom-openai" + UI, picker de tags
vivos, y el CLI (la API REST ya es invocable sin GUI; sería un wrapper fino). Esfuerzo M.

Fuentes: [Show HN LocalScore](https://news.ycombinator.com/item?id=43572134) · [vLLM #28325](https://github.com/vllm-project/vllm/issues/28325) · [LocalScore #25](https://github.com/cjpais/LocalScore/issues/25)

---

## 7. Suites de prompts personalizadas (benchmark privado del usuario)

Editor/importador JSON-YAML de suites propias reutilizando los scorers existentes (referencia offline,
checklist, tests de código en sandbox, LLM-judge); persistidas en SQLite, seleccionables en benchmark/sweep,
exportables. Posicionamiento: "tu benchmark privado con TUS problemas, que ningún modelo pudo memorizar" —
el antídoto a la contaminación de benchmarks y la forma sistemática del vibe check. Demanda transversal del
ángulo calidad-eval (HN: "create your own eval harness... instead of purely vibes or contaminated public
benchmarks"). Esfuerzo estimado M.
Fuentes: [HN](https://news.ycombinator.com/item?id=47910388) · [blog evals Sanseviero](https://osanseviero.github.io/hackerllama/blog/posts/llm_evals/)

## 8. Calculadora web "¿me cabe este modelo?" en la landing

Página estática en website/ que carga models.json + metadata de arquitectura: eliges GPU/VRAM/RAM y
contexto, y devuelve modelos+quants compatibles portando la fórmula exacta de KV-cache a JS (los datos ya
están en el catálogo). CTA hacia descargar la app "para medir los tok/s de verdad". Tres comentaristas del
Show HN de whichllm pidieron exactamente esto; existen 10+ calculadoras de VRAM independientes, todas con
fórmulas aproximadas — la señal de demanda más clara del espacio. Es el embudo de adquisición. Esfuerzo S-M.
Fuentes: [Show HN whichllm](https://news.ycombinator.com/item?id=48146369) · [apxml VRAM calc](https://apxml.com/tools/vram-calculator) · [selfhostllm.org](https://selfhostllm.org/)

## 9. Métricas de energía: tok/W, Wh por run, idle draw

Muestrear potencia durante el benchmark sin hardware externo: `nvmlDeviceGetPowerUsage` (pynvml ya está en
el stack), powermetrics en macOS, rocm-smi en AMD. Métricas nuevas: potencia media/pico, tok/s por vatio,
Wh por 1M tokens, idle (antes del warmup). Al historial, exports, comparación y leaderboard (1). MLPerf
Client v1.5 lanzó eficiencia energética como feature estrella pero con medidores físicos; nadie lo da con
un click. En mercados caros (Irlanda 0,62$/kWh) el idle decide la compra. Esfuerzo S-M.
Fuentes: [MLPerf Client 1.5](https://mlcommons.org/2025/11/mlperf-client-1-5-release/) · [DGX Spark vs Mac Studio Wh/Mtok](https://skorppio.com/blog/dgx-spark-vs-mac-studio-efficiency-benchmark) · [XDA idle draw](https://www.xda-developers.com/run-local-llms-one-worlds-priciest-energy-markets/)

## 10. Comparación multi-motor en un click (engine sweep)

Extender el patrón del sweep de quants: mismo modelo, N motores instalados (llama.cpp nativo vs Ollama vs
vLLM vs SGLang), runs idénticos encolados y reporte comparativo (TTFT/pp/tg/VRAM/calidad por motor), con
normalización documentada (mismo GGUF/quant donde aplique, aviso si vLLM/TGI usan otro formato). Los
usuarios miden a mano diferencias enormes (Ollama #14579 "much slower than LlamaCPP"; #12037 "prompt eval
9x slower"). InferBench, orquestando ya 6 motores locales, es de las pocas posicionadas. Esfuerzo S-M.
Fuentes: [ollama #14579](https://github.com/ollama/ollama/issues/14579) · [ollama #12037](https://github.com/ollama/ollama/issues/12037) · [LM Studio #1772](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1772)

## 11. Curva de offload MoE: sweep sobre `--n-cpu-moe`

Iterar valores de `--n-cpu-moe` (y opcionalmente `--ngl`) para el MoE elegido: curva tok/s vs expertos en
CPU, con VRAM/RAM por punto y recomendación del óptimo. El optimizador ya planifica MoE offload para UN
punto; falta el barrido medido. Responde la pregunta de compra de la era MoE: "¿qué tok/s da un 80B-A3B con
16GB de VRAM + DDR5?". llama.cpp #19480 documenta estimaciones falladas por 3-4×; hay una guía entera de HF
solo para tunear esto a mano. Esfuerzo M.
Fuentes: [llama.cpp #19480](https://github.com/ggml-org/llama.cpp/issues/19480) · [guía MoE offload HF](https://huggingface.co/blog/Doctor-Shotgun/llamacpp-moe-offload-guide)

## 12. Transparencia de la nota de calidad + tarjeta de resultado compartible

(1) Desglosar la nota separando la parte verificable (código ejecutado, ground truth, needle) del LLM-judge,
con badge del modo y aviso del sesgo juez=evaluado; página de metodología en el website. (2) Botón
"compartir resultado": tarjeta markdown/imagen con tabla de métricas + metadata completa de reproducibilidad
(motor+versión, driver, flags, contexto, KV-quant) lista para pegar en Reddit/HN. La credibilidad es el
campo de batalla: HN desconfía del LLM-judge, Reddit exige comandos exactos y versión del motor en cada post
"I benchmarked...". InferBench ya tiene el rigor; falta hacerlo visible. Esfuerzo S.
Fuentes: [HN LLM-judge unreliable](https://hn.algolia.com/api/v1/search?query=%22LLM%20as%20a%20judge%22%20unreliable&tags=comment&hitsPerPage=20) · [comparativa herramientas 2026](https://runaihome.com/blog/how-to-find-best-local-llm-your-hardware-benchmark-tools-2026/)

---

## Sinergias

La mejora 1 (leaderboard) multiplica el valor de casi todas las demás: contexto (2), multi-GPU (4),
energía (9) y MoE (11) generan exactamente los datos que la comunidad quiere consultar antes de comprar
hardware. La 8 (calculadora web) y la 12 (tarjeta compartible) son los canales de adquisición que llevan
tráfico al leaderboard y a la app. La 5 (avisos de degradación) protege la calidad de los datos del
leaderboard (sin runs CPU-only camuflados, la queja nº1 contra LocalScore).
