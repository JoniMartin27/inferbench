# Generación de imagen — guía completa

InferBench orquesta también **modelos de imagen** locales, reutilizando **exactamente el
mismo patrón** que con los LLM de texto. Donde para texto usa el binario nativo de
**llama.cpp** + pesos GGUF, para imagen usa su hermano de difusión,
**[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)** (de `leejet`): un
binario CUDA precompilado descargable de los releases de GitHub + pesos GGUF/safetensors de
Hugging Face + su **server HTTP**. InferBench sigue siendo el **intermediario que orquesta**:
elige los pesos, descarga lo que falte, arranca el motor de forma residente y enruta la
generación.

> **Alcance de esta entrega:** solo **imagen** (txt2img). El **vídeo** llega en una **fase 2**
> (stable-diffusion.cpp ya soporta Wan2.1/Wan2.2 y LTX, pero InferBench **aún no** lo
> implementa). Esta fase es **generar + servir por MCP**; no toca el pipeline de benchmark ni
> añade métricas de generación.

---

## El mismo patrón que llama.cpp

| Pieza | Texto (LLM) | Imagen |
|-------|-------------|--------|
| Motor | `llamacpp` | `stablediffusion` |
| Binario | release de `ggml-org/llama.cpp` | release de `leejet/stable-diffusion.cpp` |
| Server residente | `llama-server` (`:8080`) | `sd-server` (`:7861`) |
| Pesos | GGUF de Hugging Face | GGUF / safetensors de Hugging Face |
| Auxiliares | `mmproj` (visión) | `t5xxl` + `clip_l` + `vae` (FLUX) |
| API del server | OpenAI `/v1/chat/completions` | AUTOMATIC1111 `/sdapi/v1/txt2img` (JSON, `images: [base64]`) |
| Slot | único (un modelo a la vez) | único (comparte slot — un binario = un slot de GPU) |

El motor de imagen vive bajo el **mismo modo Serve** y el **mismo slot único**: como una sola
GPU pinta también la pantalla, InferBench sirve **un modelo a la vez** (texto **o** imagen).
Servir un modelo de imagen libera el de texto que hubiera, y viceversa.

---

## Servir un modelo de imagen y generar

Desde la **vista Serve** de la app:

1. En el selector de modelo, elige uno de **modalidad imagen** (aparecen agrupados/filtrados
   por modalidad junto a los de texto).
2. Pulsa **Servir**: InferBench descarga (si hace falta) el binario de stable-diffusion.cpp,
   los pesos (y los **archivos auxiliares** si el modelo los requiere, p.ej. FLUX) y arranca
   `sd-server` en `:7861`, mostrando la **fase** y el **progreso** hasta `ready`.
3. Cuando el modelo servido es de imagen, la app muestra un **GenerateCard** en vez del
   mini-chat: textarea de **prompt**, **negative prompt** opcional, **steps** (slider, 20 por
   defecto), **tamaño** con presets (512×512 / 768×768 / 1024×1024), **seed** (input + botón
   de seed aleatorio) y un botón **Generar**. La imagen generada se previsualiza en línea con
   un badge del tiempo (`elapsed_s`).
4. **Parar** libera la VRAM.

### Por API REST

`POST /api/serve/generate` (requiere un modelo de imagen en fase `ready`; si no, **HTTP 409**):

```jsonc
// Request
{
  "prompt": "a red fox in a snowy forest, golden hour",
  "negative_prompt": "",
  "steps": 20,
  "width": 512,
  "height": 512,
  "seed": -1,        // -1 = aleatoria
  "cfg_scale": 7.0,
  "sampler": null     // null = el default del server
}
```

```jsonc
// Response
{
  "image_b64": "data:image/png;base64,iVBORw0KGgo…",
  "model_id": "sd-turbo",
  "seed": 428173,
  "width": 512,
  "height": 512,
  "steps": 20,
  "elapsed_s": 3.8,
  "phase": "ready",
  "message": "ok"
}
```

El endpoint hace de **proxy** al server de stable-diffusion.cpp (API AUTOMATIC1111-compatible
`/sdapi/v1/txt2img`, que acepta `negative_prompt`/`steps`/`cfg_scale`/`seed`/`sampler` en JSON
y responde con `images: [PNG base64]`). InferBench **no inventa** nada: el tiempo es el real de
la generación. La **seed** también es real y reproducible: si pides `seed: -1`, InferBench
resuelve una semilla concreta antes de generar y te la devuelve en la respuesta (el endpoint de
sd.cpp no reporta la semilla efectiva por sí mismo, así que la fija InferBench para que puedas
repetir el resultado).

### Por MCP

La tool **`generate_image`** del servidor MCP `inferbench` genera contra el modelo de imagen
servido y **devuelve la imagen** (como `ImageContent` del SDK MCP, para que Claude Desktop la
**muestre**) más una línea con la seed y el tiempo. Ver **[docs/MCP.md](MCP.md)**.

---

## Modelos de imagen soportados

El catálogo (`backend/data/models.json`) marca cada modelo con un campo `modality`
(`"text"` por defecto, `"image"` para los de difusión). De fábrica incluye dos modelos de
imagen:

| Modelo (id) | Tipo | Archivos | VRAM aprox. (8 GB) | Notas |
|--------|------|----------|--------------------|-------|
| **SD-Turbo** (`sd-turbo`) | single-file | 1 (safetensors) | ~2–4 GB | Default garantizado. Rápido, entra holgado. 512×512 nativo, 1–4 steps. |
| **FLUX.1-schnell Q4** (`flux.1-schnell-q4`) | multi-archivo | 4 (diffusion + t5xxl + clip_l + vae) | ~7–8 GB al límite | Showcase. Calidad alta con pocos steps; en 8 GB va justo. |

Otros modelos single-file de difusión (p.ej. **SD 1.5** o **SDXL**) encajan en el mismo patrón
single-file y se pueden añadir al catálogo declarando su repo/`file` y `modality: "image"`.

> Cifras **honestas y aproximadas**: dependen de la resolución, el sampler y de cuánto reserve
> el compositor de tu escritorio. En una sola GPU que también pinta la pantalla, deja margen.

### Cuantización (GGUF) para imagen

Igual que en texto, el quant baja la VRAM a cambio de calidad:

- **Q8** ≈ casi sin pérdida · **Q6** muy cerca · **Q4** es el **piso práctico** (detalles
  finos más blandos, texto algo menos preciso) · Q2/Q3 solo para experimentar.
- En **8 GB**, FLUX.1-schnell entra en **Q4**; SD1.5/SDXL caben sin cuantizar.

---

## Archivos auxiliares de FLUX

Los modelos SD1.x / SD-Turbo / SDXL suelen ser **un único archivo**. **FLUX**, en cambio,
necesita **archivos auxiliares** además del modelo de difusión (mismo patrón generalizado que
el `mmproj` de los modelos de visión):

El modelo `flux.1-schnell-q4` del catálogo toma **los cuatro archivos del MISMO repo**
(`second-state/FLUX.1-schnell-GGUF`, no-gated), declarados en `hf_gguf`:

| Archivo (campo) | Qué es | Filename en el repo |
|---------|--------|-----------------|
| `diffusion_model` | el transformer de difusión (los pesos FLUX) | `flux1-schnell-Q4_0.gguf` |
| `t5xxl` | text encoder T5-XXL (entiende el prompt largo) | `t5xxl-Q4_K.gguf` |
| `clip_l` | text encoder CLIP-L | `clip_l.safetensors` |
| `vae` | autoencoder (decodifica el latente a píxeles) | `ae.safetensors` |

InferBench descarga estos auxiliares junto al modelo (igual que descarga el `mmproj` de un
modelo de visión, vía `model_manager.ensure_all_aux`) y le pasa cada uno a `sd-server` por su
flag correspondiente (`--diffusion-model` / `--t5xxl` / `--clip_l` / `--vae`). Si falta alguno,
el modelo no puede arrancar y la app lo reporta con un error claro (sin números inventados).

---

## Requisitos y rendimiento (8 GB, honesto)

- **SD 1.5 / SD-Turbo** — la opción **segura**: entra holgado, genera 512×512 en pocos
  segundos. SD-Turbo además funciona con **muy pocos steps** (1–4).
- **SDXL** — entra en 8 GB pero **ajustado**, sobre todo a 1024×1024; si la VRAM aprieta, baja
  la resolución o activa el offload del server.
- **FLUX.1-schnell Q4** — el **showcase** de calidad; en 8 GB va **al límite** (modelo + T5 +
  CLIP + VAE). Schnell está pensado para **pocos steps** (típicamente 1–4), lo que ayuda.

> Como en el resto de InferBench: si algo **no cabe** o el motor falla, la app devuelve un
> **error claro**, nunca métricas inventadas.

---

## Troubleshooting

### `POST /api/serve/generate` devuelve **409**

No hay ningún modelo de imagen en fase `ready`. Sirve primero un modelo **de modalidad
imagen** desde la vista Serve (o por MCP con `serve_model`) y espera a `ready`. Recuerda que el
slot es **único**: si tenías servido un LLM de texto, sírvelo de imagen y se reemplaza.

### `generate_image` (MCP) falla con "InferBench no está abierto"

La tool MCP hace de **proxy** al backend en `:7777`. Abre la app InferBench y reintenta (mismo
comportamiento que el resto de tools — ver [docs/MCP.md](MCP.md)).

### Se queda sin VRAM / la pantalla parpadea al generar

Una sola GPU que también pinta el escritorio tiene margen limitado. Baja la **resolución**
(usa 512×512), reduce **steps**, elige un quant **menor** (Q4) o sirve un modelo **más
ligero** (SD1.5 en vez de SDXL/FLUX). No fuerces resoluciones que no caben.

### FLUX no arranca (faltan auxiliares)

FLUX necesita los 4 archivos (diffusion + t5xxl + clip_l + vae). Si la descarga de alguno
falló, el modelo no puede servirse. Reintenta la carga (las descargas son resilientes con
reanudación) o empieza por un modelo single-file (SD1.5) para validar el flujo.

### La imagen sale borrosa o el texto es ilegible

Es esperable con quants agresivos (Q2/Q3) o **pocos steps** en modelos que no son "turbo".
Sube el quant (Q4→Q6→Q8), sube los **steps**, o usa un `cfg_scale` distinto. SD-Turbo y
FLUX-schnell sí están diseñados para pocos steps.

---

## Próximamente (fase 2)

- **Vídeo** — stable-diffusion.cpp ya soporta modelos de vídeo (**Wan2.1/Wan2.2**, **LTX**);
  InferBench lo integrará en una fase posterior con su propia tool y vista.
- **Métricas de generación** en el modo Benchmark (hoy el benchmark mide solo LLM de texto).

---

## Ver también

- [README — sección Generación de imagen](../README.md#generación-de-imagen)
- [docs/MCP.md](MCP.md) — tools del servidor MCP, incluida `generate_image`
- [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) — el motor de difusión
- [CLAUDE.md](../CLAUDE.md) — convenciones de desarrollo
