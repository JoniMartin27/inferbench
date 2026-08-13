export const quality = {
  en: {
    eyebrow: "Measured",
    title: "Quantization damage",
    subtitle: "What each quantization actually costs, measured on your machine",
    explain: {
      title: "Why not just the benchmark score?",
      body:
        "A task score says whether the model got the answer right, and that saturates long before quality degrades: the same model scores the same at Q8_0 and Q4_K_M. This compares the output distribution against the same model at higher precision — the standard way to measure quantization damage. “Matches the reference” is how often it picks the very same word; it moves much earlier than perplexity does.",
    },
    empty: {
      title: "Nothing to compare yet",
      body: "Download at least two quantizations of the same model. Damage is relative — it needs a higher-precision reference of the same model.",
    },
    measure: "Measure",
    remeasure: "Measure again",
    cancel: "Stop",
    quants: "{n} quantizations",
    reference: "reference: {q}",
    refBadge: "reference",
    measuring: "measuring {quant} — chunk {chunk}",
    notMeasured: "Not measured yet.",
    col: {
      quant: "Quantization",
      ppl: "Perplexity",
      vsRef: "vs reference",
      kld: "KL divergence",
      sameTop: "Matches the reference",
    },
    footnote: "Measured over {corpus} at ctx {ctx}, on CPU so it doesn't compete with your display for VRAM.",
    toast: {
      loadError: "Could not load measurements",
      measureError: "The measurement failed",
      streamLost: "Lost the connection to the backend",
      done: "Measurement finished",
    },
  },
  es: {
    eyebrow: "Medido",
    title: "Daño por cuantización",
    subtitle: "Lo que cuesta de verdad cada cuantización, medido en tu máquina",
    explain: {
      title: "¿Por qué no vale la nota del benchmark?",
      body:
        "Una nota de tarea dice si el modelo acierta, y eso satura mucho antes de que se note la degradación: el mismo modelo puntúa igual a Q8_0 que a Q4_K_M. Aquí se compara la distribución de salida contra el mismo modelo a más precisión, que es la forma estándar de medir el daño de cuantizar. «Coincide con la referencia» es cuántas veces elige exactamente la misma palabra; se mueve mucho antes que la perplejidad.",
    },
    empty: {
      title: "Todavía no hay nada que comparar",
      body: "Descarga al menos dos cuantizaciones del mismo modelo. El daño es relativo: necesita una referencia del mismo modelo a más precisión.",
    },
    measure: "Medir",
    remeasure: "Volver a medir",
    cancel: "Parar",
    quants: "{n} cuantizaciones",
    reference: "referencia: {q}",
    refBadge: "referencia",
    measuring: "midiendo {quant} — fragmento {chunk}",
    notMeasured: "Sin medir todavía.",
    col: {
      quant: "Cuantización",
      ppl: "Perplejidad",
      vsRef: "vs referencia",
      kld: "Divergencia KL",
      sameTop: "Coincide con la referencia",
    },
    footnote: "Medido sobre {corpus} a ctx {ctx}, en CPU para no competir por la VRAM con tu pantalla.",
    toast: {
      loadError: "No se pudieron cargar las medidas",
      measureError: "La medida falló",
      streamLost: "Se perdió la conexión con el backend",
      done: "Medida terminada",
    },
  },
};
