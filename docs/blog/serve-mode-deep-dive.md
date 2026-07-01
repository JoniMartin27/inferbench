---
title: "Turning a local LLM benchmarking tool into an MCP server: inferbench's Serve mode"
published: false
description: "inferbench already downloads, launches and benchmarks local LLM engines. Serve mode reuses that exact pipeline to serve one quantized model resident and expose it to Claude Desktop, Cursor or any MCP client — text and images — with the optimal quant picked for your hardware automatically."
tags: llm, localai, mcp, llamacpp
canonical_url: https://jonimartin27.github.io/inferbench
cover_image: https://raw.githubusercontent.com/JoniMartin27/inferbench/master/assets/inferbench-demo.gif
---

# Turning a local LLM benchmark into an MCP server

[inferbench](https://jonimartin27.github.io/inferbench) started as one thing: a desktop app that downloads, launches and **benchmarks** local LLM inference engines (llama.cpp and friends) and reports *real* tokens/sec on *your* hardware — no invented numbers, no cloud.

But once you've built the machinery to (1) detect hardware, (2) pick the optimal quantization, (3) download the right GGUF, and (4) boot an engine — you're one short step away from a different, very useful product: a **local model server that any MCP client can drive**.

That's **Serve mode**. This post is a deep dive into how it works and why it's built the way it is.

## The insight: same pipeline, different exit

Benchmark mode and Serve mode share the **exact same pipeline**:

```
hardware detection → optimizer (best quant for your GPU) → GGUF download → engine boot
```

Benchmark mode runs that, fires a measured workload at the model, and tears it down. Serve mode runs the same thing and then **keeps the model resident** in a single slot, routing inference to it — and exposes the whole thing over the **Model Context Protocol (MCP)**.

So inferbench becomes a broker: you ask for a model by id, it chooses the optimal quant for *your* hardware, fetches it, boots the engine, and hands you a live endpoint. No manual `-ngl` math, no "which quant fits in 8 GB of VRAM" guesswork.

## What the MCP server exposes

The server is named `inferbench` and exposes a handful of deliberately **thin** tools. Every tool is just an HTTP call to inferbench's local REST backend on `:7777` — one implementation, one process managing the engine:

| Tool | What it does |
|------|--------------|
| `get_hardware()` | CPU, RAM and detected GPUs |
| `list_models()` | Catalog summary (id, name, params, family) |
| `recommend_models(limit=5)` | The most capable models that actually *fit* your hardware |
| `serve_model(model_id, quant=None)` | Start serving a model resident; polls until `ready`. `quant=None` → optimizer picks the optimal quant |
| `serve_status()` | Phase, model, quant, context, endpoint, progress |
| `chat(prompt, ...)` | Run a prompt against the served **text** model |
| `generate_image(prompt, ...)` | Generate a PNG against the served **image** model (returns the image as MCP `ImageContent` so the client renders it) |
| `stop_model()` | Stop the engine and free VRAM |

A typical session from inside Claude Desktop or Cursor reads like a conversation with your own GPU:

```
get_hardware()                      → what GPU/RAM do I have?
recommend_models(limit=5)           → what fits?
serve_model("qwen2.5-7b-instruct")  → download + boot + wait for "ready"
chat("Explain transformers")        → inference against the resident model
stop_model()                        → free VRAM
```

`serve_model` covers **download *and* boot**, polling (~every 2s, ~300s timeout) until the slot is `ready` or `error`, then returns the final status with the chosen `quant` and `endpoint`. With `quant=None` the optimizer (`core/optimizer.py`) picks the optimal quantization for your hardware; pass an explicit `"Q4_K_M"` and it's respected.

## Text *and* images, one slot

The slot is single — one model at a time — but it isn't text-only. `serve_model` boots the **right binary based on the model's modality** in the catalog: `llama.cpp` for text, `stable-diffusion.cpp` for image models.

```
serve_model("sd-turbo")                        → boots the image engine
generate_image("a red fox in a snowy forest")  → returns the PNG (Claude shows it) + seed/time
stop_model()                                   → free VRAM
```

`generate_image` returns the image as MCP `ImageContent`, so a client like Claude Desktop **renders it inline**. Ask for `chat` on an image model (or vice versa) and you get a clean **HTTP 409** with a clear message — not a crash.

## Two transports, one definition

The tool definitions are identical across both transports; only the connection differs.

**stdio** — for Claude Desktop / Cursor. The client launches inferbench's PyInstaller sidecar (`inferbench-backend.exe`) with a `--mcp` flag. Crucially, **this process does not boot an engine** — it proxies to the HTTP backend on `:7777`. So the inferbench app must be open; if it isn't, tools return a clear error instead of crashing.

```json
{
  "mcpServers": {
    "inferbench": {
      "command": "C:\\...\\InferBench\\resources\\sidecar\\inferbench-backend.exe",
      "args": ["--mcp"]
    }
  }
}
```

(The app generates this snippet with the real path under **Serve / MCP → Connect via MCP**.)

**HTTP (streamable)** — for clients that speak MCP over HTTP. The backend mounts the MCP app under `/mcp` inside FastAPI itself:

```
http://localhost:7777/mcp
```

Nothing extra to launch — if inferbench is open, the endpoint is live. It still respects the backend's anti-DNS-rebinding middleware (loopback-only `Host` validation), so use `localhost`, not a hostname.

## Why "thin tools proxying one backend" matters

It would have been tempting to give the stdio server its own engine. We deliberately didn't. There is **one** process that owns the engine, GPU memory and the model slot — the backend. Both transports proxy to it. That means:

- No two paths fighting over the same single GPU.
- The same VRAM-safety guard everywhere (inferbench caps GPU fraction so it never starves the display compositor — a real failure mode on single-GPU machines).
- One place to reason about state: `serve_status()` is the truth for every client.

## The design rule underneath all of it: no fake numbers

inferbench has a hard rule — **no simulated data outside unit tests**. If an engine isn't available or fails, it surfaces an error rather than inventing TTFT, tok/s or VRAM. Serve mode inherits that honesty: `serve_model` reports the *actual* quant it ran and the *actual* endpoint; `chat`/`generate_image` fail loudly when there's no `ready` model instead of returning plausible-looking nothing.

## Try it

- **Site:** https://jonimartin27.github.io/inferbench
- **Source:** https://github.com/JoniMartin27/inferbench
- **Full Serve/MCP guide:** [docs/MCP.md](https://github.com/JoniMartin27/inferbench/blob/master/docs/MCP.md)

Open inferbench, flip on Serve mode, point Claude Desktop or Cursor at it, and you've got your own hardware-aware local model broker — text and images — in a few lines of JSON.
