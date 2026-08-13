// EnginesView namespace. English is the source of truth; es mirrors the original Spanish.
export const engines = {
  en: {
    header: {
      title: "Engines",
      subtitle: "Hit Start and the app installs whatever is missing automatically",
      refresh: "Refresh",
    },
    banner: {
      title: "One-click install.",
      bodyBefore: "Hit ",
      bodyStart: "Start",
      bodyMid: " on any engine: if the native binary (llama.cpp) or the Docker image is missing, it downloads automatically. For end-to-end benchmarks (binary + model + run in a single click), use the ",
      bodyBenchmark: "Benchmark",
      bodyAfter: " tab.",
    },
    badge: {
      optimizable: "optimizable",
    },
    // El backend manda `meta.description` en inglés; aquí se traduce por el id del motor
    // y solo se cae al texto del backend si aparece un motor que la UI no conoce.
    description: {
      llamacpp:
        "llama.cpp server with GGUF support and MoE offload (--n-cpu-moe). Native mode: downloads the official binary.",
      ollama:
        "Ollama daemon: models from its own registry (llama3.2:1b, qwen2.5:7b…). OpenAI-compatible API.",
      vllm: "vLLM server with prefix caching and speculative decoding (DFLASH/EAGLE). Docker + NVIDIA GPU only.",
      sglang:
        "SGLang server with chunked prefill + speculative decoding (EAGLE3/DFLASH). Docker + NVIDIA GPU only.",
      tgi: "HuggingFace text-generation-inference. Docker + NVIDIA GPU only.",
      stablediffusion:
        "stable-diffusion.cpp server for local image generation (GGUF/safetensors). Supports single-file SD1.x/SDXL and multi-file FLUX. Video (Wan2.1/LTX): coming soon.",
      openai: "Cloud API — sampling only.",
      anthropic: "Cloud API — sampling only.",
      openrouter: "API aggregator — sampling only.",
      nvidia: "Cloud API — sampling only.",
    },
    // Chips de disponibilidad. El backend manda `detail_key` + `detail_params`; el texto
    // en inglés que trae en `detail` es solo el fallback para claves desconocidas.
    runtime: {
      binaryCudaReady: "Binary + CUDA ready",
      binaryNoCuda: "Binary without CUDA DLLs — download pending",
      readyToDownload: "Ready to download",
      installed: "Installed",
      installedExe: "Installed ({exe})",
      notInstalled: "Not installed",
      notImplemented: "Not implemented",
      dockerVersion: "Docker {version}",
      dockerAvailable: "Available",
      sdkMissing: "pip install docker",
      startDockerDesktop: "Start Docker Desktop",
      installDockerDesktop: "Install Docker Desktop",
    },
    port: {
      with: "Port :{port}",
      none: "No local port",
    },
    field: {
      runtime: "Runtime",
      modelPath: "Model path",
      context: "Context",
      kvCache: "KV cache",
      flashAttn: "flash-attn",
      mlock: "mlock",
    },
    placeholder: {
      modelPath: "C:/models/qwen.Q4_K_M.gguf",
      context: "4096",
      kvCache: "f16 / q8_0 / q4_0",
    },
    actions: {
      start: "Start",
      installAndStart: "Install and start",
      stop: "Stop",
      dockerUnavailable: "Docker unavailable",
    },
    install: {
      lookup: "Looking up latest release…",
      download: "Downloading {name}",
      extract: "Extracting…",
      ready: "Ready",
      done: "Installation complete",
      error: "Error: {message}",
      starting: "Starting…",
    },
    // "missing" (el estado que manda el backend) significa que el proceso/contenedor no
    // existe todavía, NO que falte nada por instalar — con el binario listo y el motor
    // parado se leía como un error. De ahí "not started".
    state: {
      running: "running",
      missing: "not started",
      dockerOff: "docker off",
      exited: "exited",
      api: "API",
      created: "created",
    },
    toast: {
      listError: "Could not load the list of engines",
    },
    errors: {
      notInstalled: "{name} is not installed.",
      installFrom: " Install it from {url}",
    },
    empty: {
      title: "No engines available",
      body: "No inference engines were found. Check that the backend is running.",
    },
  },
  es: {
    header: {
      title: "Motores",
      subtitle: "Pulsa Arrancar y la app instala lo que falte automáticamente",
      refresh: "Refrescar",
    },
    banner: {
      title: "Instalación al primer click.",
      bodyBefore: "Pulsa ",
      bodyStart: "Arrancar",
      bodyMid: " en cualquier motor: si falta el binario nativo (llama.cpp) o la imagen Docker, se descargará automáticamente. Para benchmarks end-to-end (binario + modelo + ejecución en un solo click), usa la pestaña ",
      bodyBenchmark: "Benchmark",
      bodyAfter: ".",
    },
    badge: {
      optimizable: "optimizable",
    },
    description: {
      llamacpp:
        "Servidor llama.cpp con soporte GGUF y MoE offload (--n-cpu-moe). Modo nativo: descarga el binario oficial.",
      ollama:
        "Daemon Ollama: modelos vía su registro propio (llama3.2:1b, qwen2.5:7b…). API compatible con OpenAI.",
      vllm: "Servidor vLLM con prefix caching y speculative decoding (DFLASH/EAGLE). Solo Docker + GPU NVIDIA.",
      sglang:
        "Servidor SGLang con chunked prefill + speculative decoding (EAGLE3/DFLASH). Solo Docker + GPU NVIDIA.",
      tgi: "HuggingFace text-generation-inference. Solo Docker + GPU NVIDIA.",
      stablediffusion:
        "Servidor stable-diffusion.cpp para generación de imagen local (GGUF/safetensors). Soporta SD1.x/SDXL en un solo archivo y FLUX multi-archivo. Vídeo (Wan2.1/LTX): próximamente.",
      openai: "API cloud — solo sampling.",
      anthropic: "API cloud — solo sampling.",
      openrouter: "Agregador de APIs — solo sampling.",
      nvidia: "API cloud — solo sampling.",
    },
    runtime: {
      binaryCudaReady: "Binario + CUDA listos",
      binaryNoCuda: "Binario sin DLLs CUDA — descarga pendiente",
      readyToDownload: "Listo para descargar",
      installed: "Instalado",
      installedExe: "Instalado ({exe})",
      notInstalled: "No instalado",
      notImplemented: "No implementado",
      dockerVersion: "Docker {version}",
      dockerAvailable: "Disponible",
      sdkMissing: "pip install docker",
      startDockerDesktop: "Arranca Docker Desktop",
      installDockerDesktop: "Instala Docker Desktop",
    },
    port: {
      with: "Puerto :{port}",
      none: "Sin puerto local",
    },
    field: {
      runtime: "Runtime",
      modelPath: "Ruta del modelo",
      context: "Contexto",
      kvCache: "KV cache",
      flashAttn: "flash-attn",
      mlock: "mlock",
    },
    placeholder: {
      modelPath: "C:/modelos/qwen.Q4_K_M.gguf",
      context: "4096",
      kvCache: "f16 / q8_0 / q4_0",
    },
    actions: {
      start: "Arrancar",
      installAndStart: "Instalar y arrancar",
      stop: "Detener",
      dockerUnavailable: "Docker no disponible",
    },
    install: {
      lookup: "Buscando última release…",
      download: "Descargando {name}",
      extract: "Extrayendo…",
      ready: "Listo",
      done: "Instalación completada",
      error: "Error: {message}",
      starting: "Iniciando…",
    },
    // Estaban SIN TRADUCIR (copiadas tal cual del bloque inglés): en una UI que dice
    // "Motores", "Arrancar" y "Puerto", el estado ponía "missing" / "exited" / "created".
    state: {
      running: "en marcha",
      missing: "sin arrancar",
      dockerOff: "docker apagado",
      exited: "terminado",
      api: "API",
      created: "creado",
    },
    toast: {
      listError: "No se pudo cargar la lista de motores",
    },
    errors: {
      notInstalled: "{name} no está instalado.",
      installFrom: " Instálalo desde {url}",
    },
    empty: {
      title: "No hay motores disponibles",
      body: "No se encontraron motores de inferencia. Comprueba que el backend esté arrancado.",
    },
  },
};
