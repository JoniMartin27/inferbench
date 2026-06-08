# Serve / MCP — guía completa

InferBench tiene dos modos que comparten la misma tubería (detección de hardware,
optimizador, descarga de GGUF, arranque de motor):

- **Benchmark** — el flujo de siempre: descarga, arranca y mide motores.
- **Serve / MCP** — sirve **un** modelo cuantizado de forma **residente** y lo expone a
  cualquier app por **MCP** (Model Context Protocol). InferBench actúa de intermediario:
  elige la cuantización óptima para tu hardware, descarga el GGUF, arranca el motor y
  enruta la inferencia.

Esta página documenta el servidor MCP: las tools que expone, los dos transportes
(stdio y HTTP), los snippets de configuración para Claude Desktop / Cursor y un apartado de
troubleshooting.

> El modo Serve v1 soporta el motor **`llamacpp`** (nativo, siempre disponible). La API es
> agnóstica de motor; otros motores llegarán después. Se sirve **un solo modelo a la vez**
> (slot único, igual que el resto de la app).

---

## ¿Qué es MCP aquí?

[MCP](https://modelcontextprotocol.io/) es un protocolo estándar para que un cliente (Claude
Desktop, Cursor, etc.) descubra y llame **tools** expuestas por un servidor. InferBench
expone un servidor MCP llamado **`inferbench`** cuyas tools dejan que el cliente:

1. consulte el catálogo y pida recomendaciones para el hardware actual,
2. mande a InferBench **servir** un modelo (con el quant óptimo elegido automáticamente),
3. **chatear** contra un modelo de texto, o **generar imágenes** contra un modelo de imagen, y
4. **parar** el modelo y liberar VRAM.

Todas las tools son **finas**: llaman al backend REST de InferBench (`:7777`) por HTTP. Hay
**una sola implementación** y **un único proceso** —el backend— que gestiona el motor. Esto
vale para los **dos transportes**, así que el cliente stdio **no** arranca su propio motor:
solo hace de proxy al backend.

---

## Tools del servidor MCP

Server: **`inferbench`**. Tools disponibles:

| Tool | Backend que invoca | Qué hace |
|------|--------------------|----------|
| `list_models()` | `GET /api/models` | Lista resumida del catálogo (id, name, params_b, family). |
| `recommend_models(limit=5)` | `GET /api/optimize/recommendations` | Top modelos **ejecutables** en tu hardware (los más potentes que entran). |
| `get_hardware()` | `GET /api/hardware` | CPU, RAM y GPUs detectadas. |
| `serve_model(model_id, quant=None, engine="llamacpp")` | `POST /api/serve/load` + poll `GET /api/serve/status` | Empieza a servir un modelo de forma residente; espera (poll cada ~2 s, timeout ~300 s) hasta `ready`/`error`. Devuelve el estado final con `endpoint` y el `quant` elegido. Con `quant=None` el optimizador elige la cuantización óptima. |
| `serve_status()` | `GET /api/serve/status` | Estado del slot servido (fase, modelo, quant, contexto, endpoint, progreso). |
| `chat(prompt, max_tokens=512, temperature=0.7)` | `POST /api/serve/chat` | Manda un prompt al modelo servido (texto) y devuelve el texto. Falla con error claro si no hay modelo en fase `ready`. |
| `generate_image(prompt, steps=20, width=512, height=512, seed=-1, negative_prompt="")` | `POST /api/serve/generate` | Genera una imagen con el modelo de **imagen** servido. **Devuelve la imagen** (como `ImageContent` del SDK MCP, para que el cliente la **muestre**) + una línea con seed y tiempo. Falla con error claro si no hay un modelo de imagen en fase `ready` (HTTP 409). |
| `stop_model()` | `POST /api/serve/unload` | Para el motor servido y libera la VRAM. |

> `recommend_models`, `list_models` y `get_hardware` **reusan endpoints existentes** del
> backend (los mismos del modo Benchmark): no hay endpoint nuevo para ellos.

> **Imagen vs. texto.** `chat` aplica al modelo servido cuando es un **LLM de texto**;
> `generate_image` cuando es un modelo de **imagen** (vía stable-diffusion.cpp). El slot es
> **único**: se sirve un modelo a la vez, sea de texto o de imagen. `serve_model` arranca el
> que toque según la **modalidad** del modelo del catálogo. Detalles de generación de imagen
> en **[docs/IMAGE.md](IMAGE.md)**.

### Ciclo de vida típico desde un cliente MCP

```
get_hardware()                      → ¿qué GPU/RAM tengo?
recommend_models(limit=5)           → ¿qué modelos me entran?
serve_model("qwen2.5-7b-instruct")  → descarga + arranca + espera a "ready"
chat("Explícame los transformers")  → inferencia contra el modelo residente
stop_model()                        → libera VRAM
```

`serve_model` con `quant=None` (por defecto) deja que InferBench elija la cuantización
óptima para tu hardware vía `core/optimizer.py`. Si pasas un `quant` explícito (p.ej.
`"Q4_K_M"`), se respeta.

### Ciclo para un modelo de imagen

```
serve_model("sd-turbo")                        → arranca sd-server (modelo de imagen)
generate_image("a red fox in a snowy forest")  → devuelve el PNG (Claude lo muestra) + seed/tiempo
stop_model()                                    → libera VRAM
```

`serve_model` arranca el binario correcto según la **modalidad** del modelo del catálogo
(stable-diffusion.cpp para imagen, llama.cpp para texto). Con un modelo de imagen servido,
usa `generate_image` (no `chat`). Más en **[docs/IMAGE.md](IMAGE.md)**.

---

## Los dos transportes

La **definición de las tools es la misma** para ambos transportes; solo cambia cómo se
conecta el cliente.

### 1. stdio — para Claude Desktop / Cursor

El cliente lanza el ejecutable del backend con el flag `--mcp`. En vez de arrancar uvicorn,
el backend ejecuta el servidor MCP por stdio (`mcp.run(transport="stdio")`).

> **Importante:** el proceso stdio **no** arranca el motor; hace de proxy al backend HTTP en
> `:7777`. Por tanto **InferBench (la app) debe estar abierta** para que las tools funcionen.
> Si no lo está, las tools devuelven un error claro en vez de crashear (ver
> [Troubleshooting](#troubleshooting)).

El ejecutable es el **sidecar** que ya empaqueta InferBench con PyInstaller
(`inferbench-backend.exe` en Windows; el binario equivalente en macOS/Linux).

### 2. HTTP (streamable) — para clientes que hablan MCP sobre HTTP

El backend monta la app MCP HTTP bajo **`/mcp`** dentro del propio FastAPI
(`mcp.streamable_http_app()`). La URL es:

```
http://localhost:7777/mcp
```

Aquí no hace falta lanzar nada aparte: si InferBench está abierto, el endpoint `/mcp` ya está
servido por el backend en `:7777`.

> El backend mantiene su middleware anti-DNS-rebinding (valida la cabecera `Host`, solo
> loopback) y el CORS para `localhost:5173` y `app://`. La ruta `/mcp` respeta ese
> middleware.

---

## Configuración del cliente

### Claude Desktop (stdio)

Edita el archivo de configuración de Claude Desktop:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Añade el server `inferbench` apuntando al ejecutable del backend con `--mcp`:

```json
{
  "mcpServers": {
    "inferbench": {
      "command": "C:\\Users\\<tu-usuario>\\AppData\\Local\\Programs\\InferBench\\resources\\sidecar\\inferbench-backend.exe",
      "args": ["--mcp"]
    }
  }
}
```

> Ajusta `command` a la ruta real del sidecar `inferbench-backend.exe` en tu instalación
> (en macOS/Linux, al binario equivalente, sin extensión `.exe`). La forma más cómoda de
> obtener el snippet exacto es desde la app: **Serve / MCP → Conectar por MCP**, que muestra
> el JSON listo para copiar con la ruta ya rellenada.

Reinicia Claude Desktop. El server `inferbench` y sus tools aparecerán disponibles.

### Cursor (stdio)

Cursor usa el mismo formato `mcpServers`. Añádelo a la config MCP de Cursor (Settings → MCP)
con el mismo bloque que para Claude Desktop.

### Clientes HTTP

Para clientes que soportan MCP sobre HTTP, apunta a:

```
http://localhost:7777/mcp
```

No requiere `command`/`args`: basta con que InferBench esté abierto.

---

## Variables de entorno

| Variable | Default | Para qué |
|----------|---------|----------|
| `INFERBENCH_BACKEND_URL` | `http://127.0.0.1:7777` | URL del backend REST que las tools MCP llaman. Cámbiala solo si corres el backend en otro host/puerto. |

---

## Activar / desactivar el modo

InferBench es **una sola app unificada** con dos modos que se activan/desactivan desde
**Ajustes → Modos / Features**:

- **Benchmark** — vistas Dashboard, Motores, Modelos, Benchmark, Historial.
- **Serve / MCP** — vista Serve.

Ambos están **ON** por defecto. Al desactivar un modo, sus ítems desaparecen de la barra
lateral (la preferencia se guarda en `localStorage`, clave `inferbench:modes`). **No se
pueden desactivar los dos a la vez**: siempre queda al menos uno activo.

> Desactivar el modo Serve solo oculta su vista en la UI; no afecta a si el servidor MCP
> responde. Para servir un modelo por MCP necesitas el backend abierto (la app InferBench).

---

## Troubleshooting

### "InferBench no está abierto: arranca la app InferBench y reintenta."

El transporte **stdio** no arranca ningún motor: hace de proxy al backend HTTP en
`:7777`. Si lanzas el server MCP (Claude Desktop / Cursor) **sin la app InferBench abierta**,
las tools no encuentran el backend y devuelven este error.

**Solución:** abre la app InferBench (que arranca el backend en `:7777`) y reintenta la tool.

### Las tools no aparecen en Claude Desktop / Cursor

- Verifica que la ruta de `command` apunta al `inferbench-backend.exe` real (cópiala desde
  **Serve / MCP → Conectar por MCP** en la app).
- Reinicia el cliente tras editar el JSON de configuración.
- Comprueba que el JSON es válido (sin comas colgando).

### `chat` devuelve un error 409 / "no hay modelo servido"

No hay ningún modelo en fase `ready`. Llama antes a `serve_model(...)` y espera a que el
estado sea `ready` (la propia tool `serve_model` hace el poll por ti). Comprueba el estado
con `serve_status()`.

### `generate_image` devuelve un error 409 / "no hay modelo de imagen servido"

`generate_image` necesita un modelo de **imagen** en fase `ready`. Si no has servido ninguno,
o el modelo servido es de **texto**, devuelve 409. Sirve un modelo de modalidad imagen con
`serve_model(...)` (p.ej. SD1.5) y reintenta. Recuerda que el slot es único: servir un modelo
de imagen reemplaza al de texto que hubiera. Ver [docs/IMAGE.md](IMAGE.md).

### El modelo tarda mucho en quedar `ready`

`serve_model` cubre **descarga + arranque**. Un GGUF grande puede tardar (depende de tu red).
La tool hace poll hasta ~300 s; si tu modelo es muy grande, sírvelo primero desde la app
(que muestra el progreso de descarga) y luego úsalo por MCP.

### El endpoint `/mcp` no responde por HTTP

- Asegúrate de que InferBench está abierto (el backend escucha en `:7777`).
- Usa exactamente `http://localhost:7777/mcp` (loopback): el backend rechaza hosts que no
  sean loopback por su defensa anti-DNS-rebinding.

---

## Ver también

- [README — sección Serve / MCP](../README.md#serve--mcp)
- [docs/IMAGE.md](IMAGE.md) — generación de imagen (modelos, VRAM, FLUX, troubleshooting)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [CLAUDE.md](../CLAUDE.md) — convenciones de desarrollo
