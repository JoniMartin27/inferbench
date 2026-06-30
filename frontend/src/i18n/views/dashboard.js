// Dashboard view strings. English is the source of truth; Spanish mirrors the original copy.
export const dashboard = {
  en: {
    "header": {
      "eyebrow": "Overview",
      "title": "Dashboard",
      "subtitle": "Your environment status and recommended models for your hardware",
      "launchBenchmark": "Launch benchmark"
    },
    "stats": {
      "gpu": {
        "label": "Main GPU",
        "hint": "{vram} GB VRAM",
        "cpuOnly": "CPU-only"
      },
      "ram": {
        "label": "RAM",
        "hint": "{free} GB free"
      },
      "engines": {
        "label": "Engines",
        "running": "{count} running",
        "noneActive": "none active"
      },
      "runs": {
        "label": "Runs",
        "lastAgo": "last {ago} ago",
        "noneYet": "no benchmarks yet"
      }
    },
    "fullGpu": {
      "title": "100% GPU — maximum speed",
      "desc": "They fit entirely in your VRAM at the highest possible quantization. Maximum speed (50-200+ tok/s typical).",
      "empty": {
        "title": "Your GPU is too small for the catalog models with full-GPU status",
        "body": "Check the MoE offload or GPU+CPU section."
      }
    },
    "moe": {
      "title": "MoE offload — huge models with --n-cpu-moe",
      "desc": "MoE models with experts on CPU and attention on GPU. Few active params per token → reasonable speed with huge models."
    },
    "partial": {
      "title": "GPU + CPU — partial layer offload",
      "desc": "They don't fit entirely in VRAM. -ngl is used to put the layers that fit on GPU and the rest on CPU. Lower tok/s but runnable."
    },
    "hardware": {
      "title": "Hardware",
      "os": "OS",
      "cpu": "CPU",
      "cores": "Cores",
      "frequency": "Frequency",
      "ram": "RAM",
      "ramValue": "{total} GB total · {free} GB free",
      "gpu": "GPU",
      "noGpu": "none"
    },
    "activity": {
      "title": "Latest activity",
      "empty": {
        "title": "No activity",
        "body": "Launch your first benchmark to start collecting metrics.",
        "goToBenchmark": "Go to Benchmark"
      },
      "engineAgo": "{engine} · {ago} ago",
      "view": "view →"
    },
    "engines": {
      "title": "Engines ({count})",
      "running": "running",
      "ready": "ready",
      "off": "off",
      "api": "API"
    },
    "rec": {
      "ctx": "ctx {ctx}"
    },
    "toast": {
      "loadError": "Could not load dashboard data"
    }
  },
  es: {
    "header": {
      "eyebrow": "Resumen",
      "title": "Dashboard",
      "subtitle": "Estado de tu entorno y modelos recomendados para tu hardware",
      "launchBenchmark": "Lanzar benchmark"
    },
    "stats": {
      "gpu": {
        "label": "GPU principal",
        "hint": "{vram} GB VRAM",
        "cpuOnly": "CPU-only"
      },
      "ram": {
        "label": "RAM",
        "hint": "{free} GB libres"
      },
      "engines": {
        "label": "Motores",
        "running": "{count} corriendo",
        "noneActive": "ninguno activo"
      },
      "runs": {
        "label": "Runs",
        "lastAgo": "última hace {ago}",
        "noneYet": "aún sin benchmarks"
      }
    },
    "fullGpu": {
      "title": "100% GPU — máxima velocidad",
      "desc": "Caben enteros en tu VRAM con la cuantización más alta posible. Velocidad máxima (50-200+ tok/s típico).",
      "empty": {
        "title": "Tu GPU es muy pequeña para los modelos del catálogo con status full-GPU",
        "body": "Mira la sección MoE offload o GPU+CPU."
      }
    },
    "moe": {
      "title": "MoE offload — modelos enormes con --n-cpu-moe",
      "desc": "Modelos MoE con expertos en CPU y atención en GPU. Pocos parámetros activos por token → velocidad razonable con modelos enormes."
    },
    "partial": {
      "title": "GPU + CPU — offload parcial de capas",
      "desc": "No caben enteros en VRAM. Se usa -ngl para poner las capas que caben en GPU y el resto en CPU. Tok/s más bajos pero ejecutable."
    },
    "hardware": {
      "title": "Hardware",
      "os": "OS",
      "cpu": "CPU",
      "cores": "Cores",
      "frequency": "Frecuencia",
      "ram": "RAM",
      "ramValue": "{total} GB total · {free} GB libres",
      "gpu": "GPU",
      "noGpu": "ninguna"
    },
    "activity": {
      "title": "Última actividad",
      "empty": {
        "title": "Sin actividad",
        "body": "Lanza tu primer benchmark para empezar a coleccionar métricas.",
        "goToBenchmark": "Ir a Benchmark"
      },
      "engineAgo": "{engine} · {ago} atrás",
      "view": "ver →"
    },
    "engines": {
      "title": "Motores ({count})",
      "running": "running",
      "ready": "listo",
      "off": "off",
      "api": "API"
    },
    "rec": {
      "ctx": "ctx {ctx}"
    },
    "toast": {
      "loadError": "No se pudieron cargar los datos del dashboard"
    }
  },
};
