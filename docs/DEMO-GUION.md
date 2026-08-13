# Guion de la demo (`assets/inferbench-demo.gif`)

Guion de la grabación de la app real. Se escribe **antes** de grabar: el recorder
(`scripts/record-demo.mjs`) es la traducción literal de este documento, y la verificación
posterior comprueba escena por escena los criterios de aceptación de aquí.

> Regla del proyecto que manda sobre todo lo demás: **nada simulado**. El hardware es el de
> la máquina, los runs del historial son benchmarks reales ya ejecutados, el benchmark de la
> escena 3 corre de verdad contra `llama-server`, y la imagen de la escena 5 la genera
> sd.cpp en ese momento. Si algo no se puede enseñar de verdad, se quita del guion — no se
> maquilla.

Última regrabación: **2026-08-13** (la anterior era del 2026-06-08, con el tema viejo
indigo/slate, sin vista Guide, sin nav agrupada y sin la tabla de motores por modelo).

---

## 1. Ficha técnica

| Parámetro | Valor | Por qué |
|---|---|---|
| Resolución de captura | 1280×800, `deviceScaleFactor: 1` | Es la ventana típica de la app de escritorio; todo entra sin scroll horizontal. |
| Idioma de la UI | **inglés** (`inferbench:lang = en`) | Es el idioma por defecto de la app y el GIF también se usa en los materiales de lanzamiento en inglés. El recorder acepta `IB_LANG=es` para sacar un corte en castellano sin tocar código. |
| Duración | **40,9 s** (medida) | Por encima de ~45 s nadie lo mira entero. |
| Ancho del GIF | **800 px** | El `README.md` lo pinta con `width="800"`: exportarlo a 900 solo añadía peso invisible. |
| fps del GIF | **8** | MEDIDO: a 12 fps el GIF pesaba 8,4 MB y a 10 fps 6,0 MB pero con solo 32 colores (banding en los degradados del tema). A 8 fps caben 48 colores y el texto queda limpio; el contenido es texto y scroll, no vídeo. |
| Colores | **48** | Ver arriba. Con 64 se va a 8,4 MB; con 32 se nota el ruido de dithering en la barra lateral. |
| Peso | **7,0 MB** (tope 8 MB) | El de junio pesaba 8,1 MB a 900 px. |
| Tema | Fervon (carbon/ember), el de la app | Sin CSS inyectado para maquillar nada. |

**Prohibido en esta grabación:** ocultar banners con CSS (la versión de junio tapaba el aviso
de "Docker no disponible"; ahora Docker está arrancado de verdad y el chip dice su versión),
tocar el DOM para cambiar cifras, y grabar con datos sembrados que no vengan de una ejecución
real.

## 2. Precondiciones (se comprueban antes de darle a grabar)

1. **Backend de `master` reiniciado** en `:7777` (`uvicorn main:app --port 7777` desde
   `backend/`), para que la grabación enseñe el código de hoy y no el de la sesión anterior.
2. **Docker Desktop arrancado** → el chip de la barra lateral dice `Docker 29.5.3` y el
   Dashboard cuenta `10/10` motores. Sin Docker la demo sale con un aviso degradado.
3. **GGUFs ya en caché** (`%APPDATA%\InferBench\models\`): `Llama-3.2-1B-Instruct` en `Q4_K_M`
   y `Q8_0`, y `stabilityai__sd-turbo`. Si falta alguno, la escena esperaría a una descarga.
4. **Runs sembrados** para la escena 4: `scripts/seed_demo_runs.py` lanza dos benchmarks
   reales del mismo modelo con distinto quant (`Q8_0` vs `Q4_K_M`) y los etiqueta
   `demo · Q8_0` / `demo · Q4_K_M`.
5. **GPU libre al empezar** (`nvidia-smi`): ningún motor residente ni contenedor comiendo
   VRAM. `sd-turbo` **no** se pre-carga antes de grabar, se carga **al empezar la escena 4**
   (el propio recorder llama a `POST /api/serve/load`): tarda 5-10 s, que es justo lo que
   dura la escena de comparación, y así llega listo a la escena 5.
   **MEDIDO, y por eso el orden importa:** con `sd-turbo` residente el benchmark de la
   escena 3 pasa de **9,2 s a 18,6 s** y de **~250 a ~154 tok/s**, porque sd.cpp se lleva
   ~3,9 GB de los 8 de la 3070. Pre-cargarlo antes de grabar arruinaba la escena principal.
6. **Dos arreglos de UI que la demo destapó** (hechos antes de grabar, no son maquillaje):
   - `core/optimizer.py::benefits_summary` devolvía las técnicas aplicadas **en castellano**,
     y se pintan en el Dashboard y en el panel de optimización: con la UI en inglés salía
     "Cuantización Q8_0: modelo de 2.4GB → 1.2GB (50% menos)". Pasadas a inglés, como el
     resto de mensajes que la API manda a la UI.
   - `HistoryView` desbordaba en horizontal al abrir el detalle de un run (1141 px de
     contenido en 1040 px de columna): los botones de exportar CSV/JSON y la última columna
     de la tabla se salían de la pantalla. Faltaba `min-w-0` en la columna derecha del grid.

## 3. Escaleta

Duraciones **medidas en el GIF publicado** (40,9 s en total).

| # | Escena | Vista | Dur. | Tramo del GIF | Tramo de la toma |
|---|---|---|---|---|---|
| 0 | El flujo, de un vistazo | Guide | 2,1 s | 0,0 – 2,1 | 2,0 – 4,1 |
| 1 | Tu máquina, tus modelos | Dashboard | 3,6 s | 2,1 – 5,7 | 4,2 – 7,8 |
| 2 | La config óptima para TU equipo | Models | 6,4 s | 5,7 – 12,1 | 7,9 – 14,3 |
| 3a | Medir, no adivinar (config + run en vivo) | Benchmark | 9,5 s | 12,1 – 21,6 | 18,3 – 27,8 |
| 3b | La fila de resultados | Benchmark | 3,6 s | 21,6 – 25,2 | 30,5 – 34,1 |
| 4 | Compara y decide | History | 5,8 s | 25,2 – 31,0 | 34,4 – 40,2 |
| 5a | Y luego, sírvelo por MCP | Serve / MCP | 4,3 s | 31,0 – 35,3 | 41,0 – 45,3 |
| 5b | La imagen + Connect over MCP | Serve / MCP | 5,6 s | 35,3 – 40,9 | 47,6 – 53,2 |

La última columna es la **lista de cortes**: la toma cruda dura 53,6 s y el montaje quita
lo que no aporta (la carga inicial de la página, el bucle que insiste con el quant, y el
tramo largo de "Generating…" — del que se dejan ~4 s para que no parezca instantáneo; el
tiempo real de generación sale escrito en la propia imagen). No se acelera nada: los
tramos que quedan van a velocidad real.

> Vuelta 1 de pulido (2026-08-13): la escena 2 se quedaba en 4,5 s y el panel de
> configuración óptima —el segundo mejor gancho del producto— solo salía 1,3 s. Se le dio
> el tiempo que faltaba quitándoselo al tramo estático de configuración del benchmark.

La escena 3 se lleva un tercio del metraje a propósito: es el producto. El resto son el
antes (qué elijo, con qué config) y el después (comparar, servir).

---

### Escena 0 — El flujo, de un vistazo · `Guide` · 2,5 s

**Acción:** la app abre ya en Guide, sin clicks. Frame quieto.

**Qué se ve:** `6 / 6 steps completed`, y los pasos con su estado real —
`Check your hardware · done` con "Intel64 · 31.88GB RAM · NVIDIA GeForce RTX 3070 (8GB VRAM)",
`Your engine is ready · done` con "6 runtimes operational",
`Available models · done` con "30 GGUF(s) detected on your disk".

**Qué vende:** en los dos primeros segundos ya se sabe que esto lee tu máquina de verdad, y
que hay un camino guiado en vez de un panel de mandos que hay que adivinar.

**Aceptación:** ningún paso en estado "checking"; el hardware real visible; barra de progreso
pintada.

### Escena 1 — Tu máquina, tus modelos · `Dashboard` · 4,0 s

**Acción:** click en `Dashboard`, medio segundo quieto, scroll suave hacia abajo por la
sección `100% GPU — MAXIMUM SPEED` y vuelta arriba.

**Qué se ve:** las cuatro tarjetas de cabecera (`RTX 3070 · 8 GB VRAM`, `31.88 GB` de RAM,
`10/10` motores, `127` runs) y la rejilla de recomendaciones: modelos de **32B–35B** marcados
`100% GPU` en una tarjeta de 8 GB, cada uno con el quant elegido y una línea que explica el
porqué ("Quantization IQ1_S: model from 70.0GB → 6.7GB (90% less)").

**Qué vende:** el gancho. "Un 35B en una 3070" llama la atención, y justo debajo está la
cuenta que lo justifica — no es marketing, es el optimizador.

**Aceptación:** las notas de cada tarjeta **en inglés**; badges `100% GPU` en verde; nada a
medio cargar.

### Escena 2 — La config óptima para TU equipo · `Models` · 6,0 s

**Acción:** click en `Models`; se ven las pestañas `Catalog (126)` y `Local (30)`; se teclea
`llama-3.2` en el buscador (letra a letra, se ve filtrar); click en `Optimize` de
**Llama 3.2 1B Instruct**.

**Qué se ve:** el panel `OPTIMAL CONFIGURATION · LLAMA-3.2-1B` con `Status 100% GPU`,
`Quantization Q8_0`, `KV cache f16`, `Context 131.072`, `Estimated total 5.8 GB`, los chips de
flags activos (`flashAttn`, `mlock`, `noMmap`, `cacheReuse=256`, `ngl=999`) y el bloque
`OPTIMIZATION TECHNIQUES APPLIED (5)`.

**Qué vende:** la parte que nadie más hace. No es "elige un modelo": es "para tu GPU, este
quant, este contexto, estos flags, y este es el ahorro de cada técnica".

**Aceptación:** el bloque de técnicas **en inglés** y legible; `Estimated total` coherente con
los 8 GB de la tarjeta; el catálogo filtrado a 2 filas detrás del panel.

### Escena 3 — Medir, no adivinar · `Benchmark` · 12,0 s

**Acción:** click en `Benchmark`; se deja ver la tabla `ENGINES FOR THIS MODEL`; se elige
**Llama 3.2 1B** en `MODEL` y **Q4_K_M** en `QUANTIZATION`; se dejan activos solo los prompts
`Knowledge` y `Summary` (para que el run entre en la escena); click en `Launch benchmark`. La
página se mantiene anclada arriba mientras el panel `EXECUTION` se llena, y al terminar se
baja a la fila de resultados.

> **Por qué el quant va a mano y no se deja el que propone el optimizador:** MEDIDO, el
> optimizador elige `Q8_0` para este modelo y con él se lleva `ctx = 131.072`; en esta
> máquina la KV no cabe en VRAM, se va a RAM y el run se desploma a **4,6 tok/s y 246 s**
> (frente a **9,2 s y ~250 tok/s** con `Q4_K_M`). No cabe en una escena de 12 s. Además es
> exactamente la pregunta que contesta la escena 4 con datos, así que encaja: aquí se mide
> Q4, y allí se ve por qué.

**Qué se ve:**
- La tabla de motores para ese modelo: `llama.cpp / Ollama / vLLM / SGLang / HF TGI / OpenAI`
  con su mejor quant, de dónde sale el modelo (`GGUF`, `HF repo`, `API`), si está listo y una
  puntuación.
- El panel `EXECUTION` llenándose en vivo por SSE: fases (`engine.start` → `engine.ready`),
  el log negro acumulando líneas, y `TTFT` / `tok/s` moviéndose.
- Al final, la fila de `RESULTS` con las métricas por prompt.

**Qué vende:** el corazón del producto y la promesa del README: un click descarga lo que
falte, arranca el motor con la config óptima y **mide** TTFT, tok/s, VRAM y calidad. Y se ve
que está pasando de verdad, no que aparece un número.

**Aceptación:** al menos un `result` real con `tok/s > 0` y `quality > 0`; el log con líneas
reales; ningún `0` sospechoso ni error rojo en pantalla.

### Escena 4 — Compara y decide · `History` · 5,0 s

**Acción:** click en `History`; se marcan las casillas de los dos runs sembrados
(`demo · Q8_0` y `demo · Q4_K_M`, mismos prompts, mismo modelo); click en `Compare (2)`;
scroll para enseñar las gráficas.

**Qué se ve:** la tabla comparativa (engine, model, quant, KV, ctx, tok/s medio, TTFT medio,
calidad media, VRAM pico) y las gráficas por prompt: `TOK/S`, `TTFT`, `QUALITY PER PROMPT` y
`VRAM PEAK (GB) PER PROMPT`, con las dos series una al lado de la otra.

**Qué vende:** contesta la pregunta con la que vive cualquiera que corre modelos en local:
*¿me compensa Q8 sobre Q4 en mi máquina?* — con tus números, no con los de un blog.

**Aceptación:** **sin recorte horizontal** (los botones CSV/JSON completos y la última columna
de la tabla dentro de la pantalla); dos series en cada gráfica; ninguna barra de calidad a 0.

### Escena 5 — Y luego, sírvelo por MCP · `Serve / MCP` · 5,5 s

**Acción:** click en `Serve / MCP` (con `sd-turbo` ya servido); se escribe el prompt
`a cozy reading nook by a rainy window, warm lamp light, watercolor` y se pulsa `Generate`;
cuando aparece el PNG, scroll hasta `CONNECT OVER MCP`.

**Qué se ve:** el estado del modelo servido, la imagen **generada en ese momento** por
stable-diffusion.cpp (~2 s en caliente), y el bloque de conexión MCP con las tools que expone.

**Qué vende:** que inferbench no se acaba en el benchmark — el mismo motor que has medido se
queda residente y cualquier app (Claude Desktop, Cursor…) lo usa por MCP. Y que la API es
agnóstica de modalidad: aquí hay imagen, no solo texto.

**Aceptación:** la imagen aparece dentro de la escena (no un spinner colgado); el snippet de
MCP legible; sin errores en consola.

---

## 4. Post-proceso

1. Playwright deja un `.webm` en `C:/tmp/ib-rec`.
2. GIF de cabecera (paleta de dos pasadas, que es lo que salva los degradados del tema):
   ```bash
   ffmpeg -y -i rec.webm -vf "fps=12,scale=800:-1:flags=lanczos,palettegen=stats_mode=diff" palette.png
   ffmpeg -y -i rec.webm -i palette.png \
     -lavfi "fps=12,scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" \
     assets/inferbench-demo.gif
   ```
3. Derivados (los timestamps se ajustan a la escaleta de arriba):
   - `assets/screenshot-dashboard.png` ← escena 1
   - `assets/screenshot-models.png` ← escena 2 (panel de configuración óptima abierto)
   - `assets/inferbench-run.gif` ← recorte de la escena 3 (el panel de ejecución en vivo)

## 5. Verificación

No vale con que el fichero exista. Se extraen fotogramas a PNG **y se miran**, uno por escena
como mínimo, comprobando el criterio de aceptación de cada una. Además:

- [ ] Peso ≤ 6 MB y ancho 800 px.
- [ ] Duración entre 32 y 38 s.
- [ ] Ni una cadena en castellano en la UI (la grabación es en inglés).
- [ ] Ni un recorte horizontal en ninguna escena.
- [ ] Las cifras del GIF cuadran con las que devolvió la API durante la grabación.
- [ ] `assets/README.md` actualizado con las medidas reales del fichero nuevo.
