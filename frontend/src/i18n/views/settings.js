export const settings = {
  en: {
    header: {
      title: "Settings",
      subtitle: "Detected hardware and backend endpoint",
    },
    appearance: {
      title: "Appearance",
    },
    modes: {
      title: "Modes / Features",
      description:
        "InferBench is one unified app. Turn modes on or off to show only the views you need. At least one mode must stay on.",
      benchmark: "Benchmark",
      benchmarkHint: "Download, launch and benchmark local inference engines.",
      serve: "Serve / MCP",
      serveHint: "Serve a model residently and expose it to any app over MCP.",
      atLeastOne: "At least one mode must stay enabled.",
    },
    language: {
      label: "Language",
      hint: "English by default; Spanish if your system is set to Spanish.",
    },
    backend: {
      title: "Backend",
      apiBase: "API base",
      db: "DB",
      frontendDev: "Frontend dev",
    },
    hardware: {
      title: "Hardware",
      cpu: "CPU",
      ram: "RAM",
      ramFree: "{gb} GB free",
      gpu: "GPU",
      vram: "{gb} GB VRAM",
      cpuOnly: "CPU-only",
      os: "OS",
      loadError: "Could not detect hardware",
    },
    gpus: {
      title: "Detected GPUs",
      none: "No GPU detected. CPU-only mode.",
      driver: "{vendor} · driver {driver}",
    },
    apiKeys: {
      title: "API keys (cloud)",
      description:
        "They are stored in the system credential manager (not on disk or in the database). Once saved, the benchmark uses it automatically for that provider.",
      placeholderSaved: "•••••••••• (saved)",
      save: "Save",
      delete: "Delete",
      badgeSaved: "saved",
      badgeNone: "no key",
      saved: "{provider} key saved",
      deleted: "{provider} key deleted",
      saveError: "Could not save the key",
      deleteError: "Could not delete the key",
      inputLabel: "{provider} API key",
    },
  },
  es: {
    header: {
      title: "Ajustes",
      subtitle: "Hardware detectado y endpoint del backend",
    },
    appearance: {
      title: "Apariencia",
    },
    modes: {
      title: "Modos / Features",
      description:
        "InferBench es una sola app unificada. Activa o desactiva modos para mostrar solo las vistas que necesitas. Al menos un modo debe quedar activo.",
      benchmark: "Benchmark",
      benchmarkHint: "Descarga, arranca y benchmarkea motores de inferencia locales.",
      serve: "Serve / MCP",
      serveHint: "Sirve un modelo de forma residente y expónlo a cualquier app por MCP.",
      atLeastOne: "Al menos un modo debe quedar activo.",
    },
    language: {
      label: "Idioma",
      hint: "Inglés por defecto; español si tu sistema está en español.",
    },
    backend: {
      title: "Backend",
      apiBase: "API base",
      db: "DB",
      frontendDev: "Frontend dev",
    },
    hardware: {
      title: "Hardware",
      cpu: "CPU",
      ram: "RAM",
      ramFree: "{gb} GB libres",
      gpu: "GPU",
      vram: "{gb} GB VRAM",
      cpuOnly: "CPU-only",
      os: "OS",
      loadError: "No se pudo detectar el hardware",
    },
    gpus: {
      title: "GPUs detectadas",
      none: "Ninguna GPU detectada. Modo CPU-only.",
      driver: "{vendor} · driver {driver}",
    },
    apiKeys: {
      title: "API keys (cloud)",
      description:
        "Se guardan en el gestor de credenciales del sistema (no en disco ni en la base de datos). Una vez guardada, el benchmark la usa automáticamente para ese proveedor.",
      placeholderSaved: "•••••••••• (guardada)",
      save: "Guardar",
      delete: "Borrar",
      badgeSaved: "guardada",
      badgeNone: "sin key",
      saved: "Key de {provider} guardada",
      deleted: "Key de {provider} borrada",
      saveError: "No se pudo guardar la key",
      deleteError: "No se pudo borrar la key",
      inputLabel: "API key de {provider}",
    },
  },
};
