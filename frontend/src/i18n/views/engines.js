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
    port: {
      with: "Port :{port}",
      none: "No local port",
    },
    field: {
      runtime: "Runtime",
      modelPath: "Model path",
      context: "Context",
      kvCache: "KV cache",
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
    state: {
      running: "running",
      missing: "missing",
      dockerOff: "docker off",
      exited: "exited",
      api: "API",
      created: "created",
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
    port: {
      with: "Puerto :{port}",
      none: "Sin puerto local",
    },
    field: {
      runtime: "Runtime",
      modelPath: "Ruta del modelo",
      context: "Contexto",
      kvCache: "KV cache",
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
    state: {
      running: "running",
      missing: "missing",
      dockerOff: "docker off",
      exited: "exited",
      api: "API",
      created: "created",
    },
  },
};
