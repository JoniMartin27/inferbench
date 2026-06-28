// Benchmark view strings. English is the source of truth; Spanish mirrors the original copy.
export const benchmark = {
  en: {
    "header": {
      "title": "Benchmark",
      "subtitle": "The app downloads the binary + model, starts the engine and runs the suite in a single click"
    },
    "config": {
      "title": "Configuration"
    },
    "fields": {
      "engine": "Engine",
      "localGguf": "Selected local GGUF",
      "model": "Model",
      "quant": "Quantization",
      "sweep": "Sweep",
      "apiKey": "API key",
      "prompts": "Prompts"
    },
    "options": {
      "notInstalled": "not installed",
      "incompatible": "incompatible"
    },
    "localGguf": {
      "change": "change"
    },
    "model": {
      "noGguf": "This model has no GGUF source. Pick another one or use Models → Local."
    },
    "quant": {
      "checking": "Checking compatibility…",
      "singleRun": "For a single run"
    },
    "quantStatus": {
      "ok": "ok",
      "moe": "MoE",
      "partial": "~RAM",
      "cpu": "CPU only",
      "disk": "won't fit",
      "fail": "error",
      "nofile": "no file"
    },
    "sweep": {
      "hint": "Tick several to compare (runs sequentially)",
      "starting": "Sweep: {quants}",
      "started": "Sweep started: {id}",
      "finished": "Sweep finished ({count|run|runs})",
      "cancelled": "Sweep cancelled"
    },
    "notes": {
      "local": "local: {filename} · {compression}",
      "compression": "compression: {compression}",
      "sweep": "sweep {quants}"
    },
    "toast": {
      "launchFailed": "Could not launch the benchmark",
      "sweepFailed": "Could not launch the sweep",
      "sweepCancelFailed": "Could not cancel the sweep"
    },
    "dflash": {
      "label": "Speculative decoding (DFLASH)",
      "hint": "Speeds up with a block-diffusion draft model. Needs the DFLASH model and extra VRAM",
      "enable": "Enable DFLASH",
      "draftPlaceholder": "Draft model, e.g. z-lab/Qwen3.5-35B-A3B-DFlash",
      "specTokens": "Spec tokens:",
      "note": "SGLang is the official DFLASH path; on vLLM it needs a build with support. Speeds up 6-8×, with no quality loss, if it fits in your VRAM."
    },
    "apiKey": {
      "hint": "Empty = uses the one saved in Settings (OS keyring)"
    },
    "prompts": {
      "reasoning": "Reasoning",
      "code": "Code",
      "summary": "Summary",
      "chat": "Knowledge",
      "longContext": "Long context",
      "visionScene": "Vision: scene",
      "visionCount": "Vision: count",
      "visionHint": "Vision model: the image prompt is available",
      "apiHint": "Multimodal API (gpt-4o, claude…): image prompts also work",
      "blocked": "Vision models (mmproj) or multimodal APIs only"
    },
    "judge": {
      "fieldLabel": "Quality evaluation",
      "heuristic": {
        "label": "Reference (offline)",
        "hint": "Coverage of the reference answer (key facts, numbers) + non-degeneration. No GPU/API: works on any PC. Approximate on open-ended tasks (chat)."
      },
      "self": {
        "label": "LLM-judge (local engine)",
        "hint": "The model scores itself. Free, but only reliable with capable models (≥7-8B); small ones (1-3B) collapse to 0. Judge = evaluated model (bias)."
      },
      "api": {
        "label": "LLM-judge (external API)",
        "hint": "An OpenAI-compatible cloud model (e.g. gpt-4o-mini) judges. The most reliable and impartial; requires an API key."
      },
      "baseUrlPlaceholder": "base_url (e.g. https://api.openai.com)",
      "modelPlaceholder": "judge model (e.g. gpt-4o-mini)",
      "apiKeyPlaceholder": "judge API key"
    },
    "keepAlive": "Don't stop the engine when finished (faster if you'll relaunch)",
    "actions": {
      "launch": "Launch benchmark",
      "sweep": "Sweep ({count} quants)",
      "cancelSweep": "Cancel sweep",
      "stop": "Stop"
    },
    "runLabel": "run {id}",
    "results": {
      "title": "Results",
      "colPrompt": "Prompt",
      "colTtft": "TTFT",
      "colDecode": "decode tok/s",
      "colPrefill": "prefill tok/s",
      "colVramPeak": "VRAM peak",
      "colRamPeak": "RAM peak",
      "colQuality": "Quality",
      "colTokens": "Tokens",
      "colStatus": "Status",
      "statusError": "error",
      "statusOk": "ok"
    },
    "compression": {
      "fieldLabel": "KV-cache compression",
      "detailsSummary": "What does each compression do?",
      "dtWhat": "What it does",
      "dtAffects": "What it affects",
      "dtAllows": "What it allows",
      "quality": {
        "label": "Quality",
        "desc": "No KV compression — maximum precision.",
        "what": "The KV-cache is stored in 16 bits (f16), uncompressed.",
        "affects": "Takes twice the VRAM of q8_0; on long contexts it fills VRAM fast.",
        "allows": "The best possible quality. Ideal for small/medium models where VRAM is plentiful."
      },
      "balanced": {
        "label": "Balanced",
        "desc": "KV q8_0 — 50% less memory, near-identical quality.",
        "what": "K and V quantized to 8 bits (q8_0).",
        "affects": "Half the KV-cache memory with imperceptible quality loss.",
        "allows": "The default sweet spot: more context or a slightly larger model with no noticeable degradation."
      },
      "compressed": {
        "label": "Compressed",
        "desc": "K=q8_0 + V=iq4_nl — ~60% less. Good for long contexts.",
        "what": "K in 8 bits (precise) and V in 4-bit i-quant (iq4_nl, modern).",
        "affects": "~60% less KV; the key (K) stays precise, only the value (V) is compressed more.",
        "allows": "Long contexts (16k–32k+) while keeping good answer quality."
      },
      "aggressive": {
        "label": "Aggressive",
        "desc": "KV q4_0 — 75% less memory. Some quality sacrificed.",
        "what": "K and V quantized to 4 bits (q4_0).",
        "affects": "75% less KV memory; some precision loss is noticeable on very long contexts.",
        "allows": "Huge contexts or loading a much larger model on the same GPU."
      },
      "extreme": {
        "label": "Extreme",
        "desc": "q4_0 + KV in RAM (no-kv-offload). Frees VRAM to the max.",
        "what": "KV in 4 bits AND moved to system RAM (--no-kv-offload); VRAM only holds the weights.",
        "affects": "Frees all the VRAM the KV would use, but lowers tok/s (the KV travels over PCIe).",
        "allows": "The largest possible model with weights 100% on GPU, delegating the KV to RAM."
      }
    },
    "context": {
      "label": "Context (override)",
      "hint": "Auto: the optimizer computes the maximum. Enter a number to force it.",
      "placeholder": "auto",
      "kvAt": "KV-cache at {tokens} tokens",
      "inRam": "in RAM"
    },
    "engineHint": {
      "llamacpp": {
        "before": "First time: downloads the llama.cpp binary (~300MB + cudart if NVIDIA) + the model GGUF. Cached in",
        "after": "."
      },
      "ollama": {
        "notInstalledTitle": "Ollama not installed.",
        "notInstalledBody": "Download it (~700MB) and install it, then come back and the app will detect the binary:",
        "downloadCta": "Download Ollama →",
        "readyBefore": "Ollama ready. The app will pull",
        "theModel": "the model",
        "readyAfter": "from the Ollama registry if you don't have it already."
      },
      "docker": {
        "requiredTitle": "Docker required for {engine}.",
        "requiredBody": "Start Docker Desktop. {engine} runs on an NVIDIA GPU inside the container.",
        "firstRun": "First time: pull the Docker image (~6GB for vLLM/SGLang/TGI) + download the HF model inside the container. May take several minutes."
      }
    },
    "engineMatrix": {
      "checking": "Checking engines…",
      "title": "Engines for this model",
      "updating": "updating…",
      "colEngine": "Engine",
      "colBestQuant": "Best quant",
      "colSource": "Source",
      "colRuntime": "Runtime",
      "colScore": "Score",
      "titleModelUnavailable": "Model not available from this source",
      "titleRuntimeMissing": "Runtime not installed",
      "titleWontFit": "Won't fit in the hardware",
      "titleClickSelect": "Click to select this engine",
      "cloud": "cloud",
      "ready": "ready",
      "notInstalled": "not installed"
    },
    "running": {
      "title": "Execution",
      "waiting": "Waiting for events…",
      "idle": "Configure and press Launch benchmark."
    },
    "bootstrap": {
      "downloadingBinary": "Downloading llama.cpp binary",
      "downloadingModel": "Downloading {name}",
      "engineReady": "✓ Engine ready"
    },
    "tokens": {
      "ttft": "TTFT",
      "tps": "current tok/s",
      "progress": "Progress"
    },
    "power": {
      "title": "Most powerful models by compression",
      "intro": {
        "before": "For your hardware and a context of",
        "after": "tokens: compressing the KV-cache frees VRAM and lets you load larger models 100% on the GPU."
      },
      "calculating": "Calculating…",
      "colCompression": "Compression",
      "colKv": "KV",
      "colTopFullGpu": "Most powerful · 100% GPU",
      "colKvCache": "KV-cache",
      "colLargestRunnable": "Largest runnable"
    }
  },
  es: {
    "header": {
      "title": "Benchmark",
      "subtitle": "La app descarga binario + modelo, arranca el motor y ejecuta la suite con un solo click"
    },
    "config": {
      "title": "Configuración"
    },
    "fields": {
      "engine": "Motor",
      "localGguf": "GGUF local seleccionado",
      "model": "Modelo",
      "quant": "Cuantización",
      "sweep": "Sweep",
      "apiKey": "API key",
      "prompts": "Prompts"
    },
    "options": {
      "notInstalled": "no instalado",
      "incompatible": "incompatible"
    },
    "localGguf": {
      "change": "cambiar"
    },
    "model": {
      "noGguf": "Este modelo no tiene fuente GGUF. Elige otro o usa Modelos → Locales."
    },
    "quant": {
      "checking": "Comprobando compatibilidad…",
      "singleRun": "Para una sola corrida"
    },
    "quantStatus": {
      "ok": "ok",
      "moe": "MoE",
      "partial": "~RAM",
      "cpu": "solo CPU",
      "disk": "no cabe",
      "fail": "error",
      "nofile": "sin archivo"
    },
    "sweep": {
      "hint": "Marca varias para comparar (corre secuencial)",
      "starting": "Sweep: {quants}",
      "started": "Sweep arrancado: {id}",
      "finished": "Sweep terminado ({count|run|runs})",
      "cancelled": "Sweep cancelado"
    },
    "notes": {
      "local": "local: {filename} · {compression}",
      "compression": "compresión: {compression}",
      "sweep": "sweep {quants}"
    },
    "toast": {
      "launchFailed": "No se pudo lanzar el benchmark",
      "sweepFailed": "No se pudo lanzar el sweep",
      "sweepCancelFailed": "No se pudo cancelar el sweep"
    },
    "dflash": {
      "label": "Speculative decoding (DFLASH)",
      "hint": "Acelera con un modelo draft block-diffusion. Necesita el modelo DFLASH y VRAM extra",
      "enable": "Activar DFLASH",
      "draftPlaceholder": "Modelo draft, ej. z-lab/Qwen3.5-35B-A3B-DFlash",
      "specTokens": "Tokens spec:",
      "note": "SGLang es la ruta oficial de DFLASH; en vLLM requiere una build con soporte. Acelera 6-8×, sin pérdida de calidad, si cabe en tu VRAM."
    },
    "apiKey": {
      "hint": "Vacío = usa la guardada en Ajustes (keyring del SO)"
    },
    "prompts": {
      "reasoning": "Razonamiento",
      "code": "Código",
      "summary": "Resumen",
      "chat": "Conocimiento",
      "longContext": "Contexto largo",
      "visionScene": "Visión: escena",
      "visionCount": "Visión: conteo",
      "visionHint": "Modelo de visión: el prompt de imagen está disponible",
      "apiHint": "API multimodal (gpt-4o, claude…): los prompts de imagen también valen",
      "blocked": "Solo modelos de visión (mmproj) o APIs multimodales"
    },
    "judge": {
      "fieldLabel": "Evaluación de calidad",
      "heuristic": {
        "label": "Referencia (offline)",
        "hint": "Cobertura de la respuesta de referencia (datos clave, números) + no-degeneración. Sin GPU/API: funciona en cualquier PC. Aproximado en tareas abiertas (chat)."
      },
      "self": {
        "label": "LLM-judge (motor local)",
        "hint": "El propio modelo puntúa. Sin coste, pero solo fiable con modelos capaces (≥7-8B); los pequeños (1-3B) colapsan a 0. Juez = modelo evaluado (sesgo)."
      },
      "api": {
        "label": "LLM-judge (API externa)",
        "hint": "Un modelo cloud OpenAI-compatible (p.ej. gpt-4o-mini) juzga. Lo más fiable e imparcial; requiere API key."
      },
      "baseUrlPlaceholder": "base_url (ej. https://api.openai.com)",
      "modelPlaceholder": "modelo juez (ej. gpt-4o-mini)",
      "apiKeyPlaceholder": "API key del juez"
    },
    "keepAlive": "No detener el motor al terminar (más rápido si vas a relanzar)",
    "actions": {
      "launch": "Lanzar benchmark",
      "sweep": "Sweep ({count} quants)",
      "cancelSweep": "Cancelar sweep",
      "stop": "Detener"
    },
    "runLabel": "run {id}",
    "results": {
      "title": "Resultados",
      "colPrompt": "Prompt",
      "colTtft": "TTFT",
      "colDecode": "decode tok/s",
      "colPrefill": "prefill tok/s",
      "colVramPeak": "VRAM peak",
      "colRamPeak": "RAM peak",
      "colQuality": "Calidad",
      "colTokens": "Tokens",
      "colStatus": "Estado",
      "statusError": "error",
      "statusOk": "ok"
    },
    "compression": {
      "fieldLabel": "Compresión de KV-cache",
      "detailsSummary": "¿Qué hace cada compresión?",
      "dtWhat": "Qué hace",
      "dtAffects": "En qué afecta",
      "dtAllows": "Qué permite",
      "quality": {
        "label": "Calidad",
        "desc": "Sin compresión KV — máxima precisión.",
        "what": "La KV-cache se guarda en 16 bits (f16), sin comprimir.",
        "affects": "Ocupa el doble de VRAM que q8_0; en contextos largos llena la VRAM rápido.",
        "allows": "La mejor calidad posible. Ideal para modelos pequeños/medianos donde la VRAM sobra."
      },
      "balanced": {
        "label": "Equilibrado",
        "desc": "KV q8_0 — 50% menos memoria, calidad casi idéntica.",
        "what": "K y V cuantizados a 8 bits (q8_0).",
        "affects": "Mitad de memoria de KV-cache con pérdida de calidad imperceptible.",
        "allows": "El punto dulce por defecto: más contexto o un modelo algo mayor sin notar degradación."
      },
      "compressed": {
        "label": "Comprimido",
        "desc": "K=q8_0 + V=iq4_nl — ~60% menos. Buena para contextos largos.",
        "what": "K en 8 bits (preciso) y V en 4 bits i-quant (iq4_nl, moderno).",
        "affects": "~60% menos KV; la clave (K) sigue precisa, solo el valor (V) se comprime más.",
        "allows": "Contextos largos (16k–32k+) manteniendo buena calidad de respuesta."
      },
      "aggressive": {
        "label": "Agresivo",
        "desc": "KV q4_0 — 75% menos memoria. Algo de calidad sacrificada.",
        "what": "K y V cuantizados a 4 bits (q4_0).",
        "affects": "75% menos memoria de KV; se nota algo de pérdida de precisión en contextos muy largos.",
        "allows": "Contextos enormes o cargar un modelo bastante más grande en la misma GPU."
      },
      "extreme": {
        "label": "Extremo",
        "desc": "q4_0 + KV en RAM (no-kv-offload). Libera VRAM al máximo.",
        "what": "KV en 4 bits Y movida a RAM del sistema (--no-kv-offload); la VRAM solo guarda los pesos.",
        "affects": "Libera toda la VRAM que usaría la KV, pero baja los tok/s (la KV viaja por PCIe).",
        "allows": "El modelo más grande posible con los pesos 100% en GPU, delegando la KV a la RAM."
      }
    },
    "context": {
      "label": "Contexto (override)",
      "hint": "Auto: el optimizador calcula el máximo. Pon un número para forzar.",
      "placeholder": "auto",
      "kvAt": "KV-cache en {tokens} tokens",
      "inRam": "en RAM"
    },
    "engineHint": {
      "llamacpp": {
        "before": "Si es la primera vez: descarga binario llama.cpp (~300MB + cudart si hay NVIDIA) + el GGUF del modelo. Cacheado en",
        "after": "."
      },
      "ollama": {
        "notInstalledTitle": "Ollama no instalado.",
        "notInstalledBody": "Descárgalo (~700MB) e instálalo, después vuelve y la app detectará el binario:",
        "downloadCta": "Descargar Ollama →",
        "readyBefore": "Ollama listo. La app pulleará",
        "theModel": "el modelo",
        "readyAfter": "desde el registro de Ollama si no lo tienes ya."
      },
      "docker": {
        "requiredTitle": "Docker requerido para {engine}.",
        "requiredBody": "Arranca Docker Desktop. {engine} corre en GPU NVIDIA dentro del contenedor.",
        "firstRun": "Primera vez: pull de la imagen Docker (~6GB para vLLM/SGLang/TGI) + descarga del modelo HF dentro del contenedor. Puede tardar varios minutos."
      }
    },
    "engineMatrix": {
      "checking": "Comprobando motores…",
      "title": "Motores para este modelo",
      "updating": "actualizando…",
      "colEngine": "Motor",
      "colBestQuant": "Mejor quant",
      "colSource": "Fuente",
      "colRuntime": "Runtime",
      "colScore": "Score",
      "titleModelUnavailable": "Modelo no disponible en este origen",
      "titleRuntimeMissing": "Runtime no instalado",
      "titleWontFit": "No cabe en el hardware",
      "titleClickSelect": "Click para seleccionar este motor",
      "cloud": "cloud",
      "ready": "listo",
      "notInstalled": "no instalado"
    },
    "running": {
      "title": "Ejecución",
      "waiting": "Esperando eventos…",
      "idle": "Configura y pulsa Lanzar benchmark."
    },
    "bootstrap": {
      "downloadingBinary": "Descargando binario llama.cpp",
      "downloadingModel": "Descargando {name}",
      "engineReady": "✓ Motor listo"
    },
    "tokens": {
      "ttft": "TTFT",
      "tps": "tok/s actual",
      "progress": "Progreso"
    },
    "power": {
      "title": "Modelos más potentes por compresión",
      "intro": {
        "before": "Para tu hardware y un contexto de",
        "after": "tokens: comprimir la KV-cache libera VRAM y te deja cargar modelos más grandes 100% en la GPU."
      },
      "calculating": "Calculando…",
      "colCompression": "Compresión",
      "colKv": "KV",
      "colTopFullGpu": "Más potente · 100% GPU",
      "colKvCache": "KV-cache",
      "colLargestRunnable": "Más grande ejecutable"
    }
  },
};
