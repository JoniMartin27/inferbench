// Guide view i18n. English = source of truth; Spanish mirrors the original copy.
export const guide = {
  en: {
    header: {
      title: "Guide",
      subtitle: "Follow the recommended flow — each step shows its current status",
    },
    progress: {
      label: "Progress",
      completed: "{completed} / {total} steps completed",
      ofFlow: "of the recommended flow",
    },
    done: "done",
    steps: {
      hw: {
        title: "Check your hardware",
        detail: "Detected: {cpu} · {ram}GB RAM · {gpu}{vram}",
        detailPending: "InferBench will use your CPU/GPU/RAM to pick the best configuration",
        noGpu: "no GPU",
        why: "The optimizer and the compatibility calculation depend on knowing what machine you have.",
        action: "View dashboard",
      },
      engines: {
        title: "Your engine is ready",
        detail: "{count|runtime operational|runtimes operational}",
        detailPending:
          "The first benchmark downloads llama.cpp automatically (~300MB binary + ~390MB cudart if you have NVIDIA)",
        why: "llama.cpp runs as a native process, no Docker. Other engines (Ollama/vLLM/SGLang/TGI) use Docker if you have it.",
        action: "View engines",
      },
      models: {
        title: "Available models",
        detail:
          "{count} GGUF(s) detected on your disk — InferBench scans LM Studio, HF cache, llama.cpp and more",
        detailPending:
          "Catalog of 124+ verified models (Llama, Qwen, Gemma 3, DeepSeek, vision, code…) ready to auto-download from Hugging Face.",
        why: "Use any GGUF you already have or download from the catalog. Compatibility is computed in real time with your hardware (including MoE offload and GPU+CPU).",
        action: "View catalog + local",
      },
      firstBench: {
        title: "Launch your first benchmark",
        detail: "{count|run executed|runs executed}",
        detailPending:
          "Recommended to start: Llama 3.2 1B Q4_K_M (~760MB, completes in ~1 minute on RTX 3070)",
        why: "With 1 click the app downloads binary + model, starts the engine with the optimal config and measures TTFT, tok/s, VRAM and quality for 4 prompts.",
        action: "Go to benchmark",
      },
      sweep: {
        title: "Compare quantizations (sweep)",
        detail: "{count|sweep run|sweep runs}",
        detailPending:
          "Pick several quantizations (e.g. Q4_K_M, Q5_K_M, Q6_K) and hit Sweep — it runs them all in a queue",
        why: "Q4 is usually the speed/quality sweet spot, but it depends on the model. Sweep answers 'which one is really best for me'.",
        action: "Go to benchmark",
      },
      compare: {
        title: "Compare results",
        detail: "{count} runs saved, ready to compare",
        detailPending: "Once you have 2+ runs, you'll be able to compare them side by side",
        why: "Summary table + 4 charts (tok/s, TTFT, quality, peak VRAM) per prompt. It tells you which config performs best for each task.",
        action: "View history",
      },
    },
    tips: {
      heading: "Tips",
      stop: {
        title: "Stop at any time",
        body: "During a run you'll see a red Stop button in Benchmark. It cancels bootstrap, download or execution without leaving a zombie engine.",
      },
      reuse: {
        title: "Engine reuse",
        body: "If you're going to launch the same model+quantization several times, check 'Don't stop engine when done' to avoid loading the model on each run (you skip ~5-10s).",
      },
      optimize: {
        title: "⚡ Optimize for your hardware",
        body: "In the Models tab, click on ⚡ next to any model: the app calculates the best quantization + KV cache + context + flags for your GPU automatically.",
      },
      reuseGguf: {
        title: "Reuse GGUFs you already have",
        body: "InferBench detects models from LM Studio, llama.cpp, HuggingFace cache, GPT4All... If you have a GGUF in another folder, add it in Models → 'Scanned folders'.",
      },
      kvCache: {
        title: "KV-cache compression",
        body: "In Benchmark, expand 'What does each compression do?' to understand each preset (Quality→Extreme), and look at the 'Most powerful models per compression' table: compressing the KV frees VRAM to load larger models.",
      },
      quality: {
        title: "Reliable quality evaluation",
        body: "Quality by default is measured offline against the reference (any PC, no GPU). For reliable judgment of open-ended tasks, switch to LLM-judge (local engine ≥7B or external API) in Benchmark → Quality evaluation.",
      },
    },
    faq: {
      heading: "FAQ",
      docker: {
        q: "Do I need Docker?",
        a: "Not for llama.cpp — it runs native. You do need it for Ollama, vLLM, SGLang and TGI (in progress). Cloud APIs (OpenAI, Anthropic, OpenRouter, NVIDIA NIM) don't require Docker either.",
      },
      where: {
        q: "Where are downloaded models stored?",
        a: "%APPDATA%\\InferBench\\models\\ on Windows or ~/.inferbench/models/ on Linux/Mac. Once downloaded, it's reused for future benchmarks.",
      },
      existing: {
        q: "Can I use my existing GGUFs?",
        a: "Yes. The Models tab → Local scans LM Studio, llama.cpp, HuggingFace cache, GPT4All, Jan.ai and shows them all with their metadata (architecture, layers, context, params). Add extra folders from 'Scanned folders'.",
      },
      moe: {
        q: "What about MoE models like Qwen 3 30B-A3B or Mixtral?",
        a: "Compatibility computed with --n-cpu-moe (offload of MoE layers to CPU). The optimizer automatically picks how many layers to offload based on your VRAM. Auto-download of GGUF for MoE still pending.",
      },
      reliable: {
        q: "How reliable is the measured quality?",
        a: "There are three modes (in Benchmark → Quality evaluation). By default: offline comparison with the reference answer (coverage of key facts and numbers + penalty for degenerate text), which works on any computer without GPU or API and is good for tasks with an expected answer (reasoning, code, summary); on open-ended tasks (chat) it's approximate. For reliable judgment of open-ended tasks: local LLM-judge (the engine itself scores, reliable only with models ≥7-8B) or LLM-judge via external API (impartial cloud model, the most reliable). TTFT and tok/s are always real measurements from the engine.",
      },
    },
  },
  es: {
    header: {
      title: "Guía",
      subtitle: "Sigue el flujo recomendado — cada paso muestra su estado actual",
    },
    progress: {
      label: "Progreso",
      completed: "{completed} / {total} pasos completados",
      ofFlow: "del flujo recomendado",
    },
    done: "hecho",
    steps: {
      hw: {
        title: "Verifica tu hardware",
        detail: "Detectado: {cpu} · {ram}GB RAM · {gpu}{vram}",
        detailPending: "InferBench va a usar tu CPU/GPU/RAM para elegir la mejor configuración",
        noGpu: "sin GPU",
        why: "El optimizador y el cálculo de compatibilidad dependen de saber qué máquina tienes.",
        action: "Ver dashboard",
      },
      engines: {
        title: "Tu motor está listo",
        detail: "{count|runtime operativo|runtimes operativos}",
        detailPending:
          "El primer benchmark descarga llama.cpp automáticamente (~300MB binario + ~390MB cudart si tienes NVIDIA)",
        why: "llama.cpp corre como proceso nativo, sin Docker. Otros motores (Ollama/vLLM/SGLang/TGI) usan Docker si lo tienes.",
        action: "Ver motores",
      },
      models: {
        title: "Modelos disponibles",
        detail:
          "{count} GGUF(s) detectados en tu disco — InferBench escanea LM Studio, HF cache, llama.cpp y más",
        detailPending:
          "Catálogo de 124+ modelos verificados (Llama, Qwen, Gemma 3, DeepSeek, visión, código…) listos para auto-descargar desde Hugging Face.",
        why: "Usa cualquier GGUF que ya tengas o descarga del catálogo. La compatibilidad se calcula en tiempo real con tu hardware (incluido offload MoE y GPU+CPU).",
        action: "Ver catálogo + locales",
      },
      firstBench: {
        title: "Lanza tu primer benchmark",
        detail: "{count|run ejecutada|runs ejecutadas}",
        detailPending:
          "Recomendado para empezar: Llama 3.2 1B Q4_K_M (~760MB, completa en ~1 minuto en RTX 3070)",
        why: "Con 1 click la app baja binario + modelo, arranca el motor con la config óptima y mide TTFT, tok/s, VRAM y calidad para 4 prompts.",
        action: "Ir a benchmark",
      },
      sweep: {
        title: "Compara cuantizaciones (sweep)",
        detail: "{count|run de sweep|runs de sweep}",
        detailPending:
          "Marca varias cuantizaciones (p.ej. Q4_K_M, Q5_K_M, Q6_K) y pulsa Sweep — corre todas en cola",
        why: "Q4 suele ser el sweet spot velocidad/calidad, pero depende del modelo. Sweep responde 'cuál es realmente la mejor para mí'.",
        action: "Ir a benchmark",
      },
      compare: {
        title: "Compara resultados",
        detail: "{count} runs guardadas, listas para comparar",
        detailPending: "Cuando tengas 2+ runs, podrás compararlas lado a lado",
        why: "Tabla resumen + 4 gráficos (tok/s, TTFT, calidad, VRAM peak) por prompt. Te dice qué config rinde mejor para cada tarea.",
        action: "Ver historial",
      },
    },
    tips: {
      heading: "Tips",
      stop: {
        title: "Detener en cualquier momento",
        body: "Durante una corrida verás un botón rojo Detener en Benchmark. Cancela bootstrap, descarga o ejecución sin dejar el motor zombi.",
      },
      reuse: {
        title: "Reuso de motor",
        body: "Si vas a lanzar varias veces el mismo modelo+cuantización, marca 'No detener motor al terminar' para evitar la carga del modelo en cada run (saltas ~5-10s).",
      },
      optimize: {
        title: "⚡ Optimizar para tu hardware",
        body: "En la pestaña Modelos, click en ⚡ junto a cualquier modelo: la app calcula la mejor cuantización + KV cache + contexto + flags para tu GPU automáticamente.",
      },
      reuseGguf: {
        title: "Reusa GGUFs que ya tengas",
        body: "InferBench detecta modelos de LM Studio, llama.cpp, HuggingFace cache, GPT4All... Si tienes un GGUF en otra carpeta, añádela en Modelos → 'Carpetas escaneadas'.",
      },
      kvCache: {
        title: "Compresión de KV-cache",
        body: "En Benchmark, despliega '¿Qué hace cada compresión?' para entender cada preset (Calidad→Extremo), y mira la tabla 'Modelos más potentes por compresión': comprimir la KV libera VRAM para cargar modelos más grandes.",
      },
      quality: {
        title: "Evaluación de calidad fiable",
        body: "La calidad por defecto se mide offline contra la referencia (cualquier PC, sin GPU). Para juicio fiable de tareas abiertas, cambia a LLM-judge (motor local ≥7B o API externa) en Benchmark → Evaluación de calidad.",
      },
    },
    faq: {
      heading: "FAQ",
      docker: {
        q: "¿Necesito Docker?",
        a: "No para llama.cpp — corre nativo. Sí lo necesitas para Ollama, vLLM, SGLang y TGI (en implementación). APIs cloud (OpenAI, Anthropic, OpenRouter, NVIDIA NIM) tampoco requieren Docker.",
      },
      where: {
        q: "¿Dónde se guardan los modelos descargados?",
        a: "%APPDATA%\\InferBench\\models\\ en Windows o ~/.inferbench/models/ en Linux/Mac. Una vez descargado, se reusa para futuros benchmarks.",
      },
      existing: {
        q: "¿Puedo usar mis GGUFs existentes?",
        a: "Sí. La pestaña Modelos → Locales escanea LM Studio, llama.cpp, HuggingFace cache, GPT4All, Jan.ai y muestra todos con su metadata (arquitectura, capas, contexto, params). Añade carpetas extras desde 'Carpetas escaneadas'.",
      },
      moe: {
        q: "¿Y los modelos MoE como Qwen 3 30B-A3B o Mixtral?",
        a: "Compatibilidad calculada con --n-cpu-moe (offload de capas MoE a CPU). El optimizador elige automáticamente cuántas capas descargar según tu VRAM. Auto-descarga GGUF para MoE aún pendiente.",
      },
      reliable: {
        q: "¿Cómo de fiable es la calidad medida?",
        a: "Hay tres modos (en Benchmark → Evaluación de calidad). Por defecto: comparación offline con la respuesta de referencia (cobertura de datos clave y números + penalización de texto degenerado), que funciona en cualquier ordenador sin GPU ni API y es buena para tareas con respuesta esperada (razonamiento, código, resumen); en tareas abiertas (chat) es aproximada. Para juicio fiable de tareas abiertas: LLM-judge local (el propio motor puntúa, fiable solo con modelos ≥7-8B) o LLM-judge por API externa (modelo cloud imparcial, lo más fiable). TTFT y tok/s siempre son medidas reales del motor.",
      },
    },
  },
};
