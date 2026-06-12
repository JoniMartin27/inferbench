// Exporta resultados de benchmark a CSV / JSON desde el frontend, sin tocar el backend.
// El historial ya viene del backend como { run, results }; aquí solo lo aplanamos a una
// tabla tabular (CSV) o lo serializamos tal cual (JSON) y disparamos la descarga en el navegador.
//
// Módulo de funciones puras (sin React) para que sea fácil de razonar y reutilizar tanto
// en el detalle de un run como en una comparación de varios.

// Columnas del CSV en orden. Cada fila = un resultado (prompt) dentro de un run.
// Se incluyen las opciones del run (motor/modelo/quant/kv/ctx) desnormalizadas en cada fila
// para que el CSV sea autocontenido (un análisis en hoja de cálculo no necesita un join).
const CSV_COLUMNS = [
  "run_id",
  "engine",
  "model",
  "quant",
  "kv_cache",
  "context_len",
  "prompt_id",
  "ttft_ms",
  "ttft_std",
  "tps",
  "tps_std",
  "prefill_tps",
  "n_samples",
  "vram_gb",
  "quality",
  "ctx_used",
  "error",
];

function safeParse(s) {
  try {
    return JSON.parse(s) || {};
  } catch {
    return {};
  }
}

// Deriva una etiqueta legible de KV-cache desde engine_opts. El benchmark real guarda
// `kvCacheK`/`kvCacheV` por separado (preset de compresión), no un único `kvCache`; si K=V
// se colapsa a un valor ("q8_0"), si difieren se muestra "K/V" ("q8_0/iq4_nl"). Se mantiene
// el fallback al `kvCache`/`kv_cache` legacy para runs antiguos.
export function kvLabel(opts = {}) {
  const eo = opts.engine_opts || {};
  const k = eo.kvCacheK;
  const v = eo.kvCacheV;
  if (k || v) {
    const kk = k || v;
    const vv = v || k;
    return kk === vv ? kk : `${kk}/${vv}`;
  }
  return eo.kvCache || opts.kv_cache || "";
}

// Escapa un valor para CSV (RFC 4180): entrecomilla si contiene coma, comilla o salto de
// línea, y duplica las comillas internas. null/undefined → cadena vacía.
export function csvEscape(value) {
  if (value == null) return "";
  const s = String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

// Aplana un único run ({ run, results }) a filas planas (objetos con las claves de CSV_COLUMNS).
export function runToRows({ run, results }) {
  const opts = safeParse(run?.opts_json);
  const kv = kvLabel(opts);
  const ctx = opts.engine_opts?.contextLen || opts.context_len || "";
  return (results || []).map((r) => ({
    run_id: run?.id ?? "",
    engine: run?.engine ?? "",
    model: opts.model ?? "",
    quant: opts.quant ?? "",
    kv_cache: kv,
    context_len: ctx,
    prompt_id: r.prompt_id ?? "",
    ttft_ms: r.ttft_ms ?? "",
    ttft_std: r.ttft_std ?? "",
    tps: r.tps ?? "",
    tps_std: r.tps_std ?? "",
    prefill_tps: r.prefill_tps ?? "",
    n_samples: r.n_samples ?? "",
    vram_gb: r.vram_gb ?? "",
    quality: r.quality ?? "",
    ctx_used: r.ctx_used ?? "",
    error: r.error ?? "",
  }));
}

// Construye el texto CSV a partir de uno o varios runs ({ run, results }).
// Acepta un único objeto o un array (comparación de varios runs).
export function buildCsv(runOrRuns) {
  const runs = Array.isArray(runOrRuns) ? runOrRuns : [runOrRuns];
  const rows = runs.flatMap((r) => runToRows(r));
  const header = CSV_COLUMNS.join(",");
  const body = rows
    .map((row) => CSV_COLUMNS.map((c) => csvEscape(row[c])).join(","))
    .join("\n");
  return body ? `${header}\n${body}` : header;
}

// Serializa a JSON "bonito" el run o los runs tal cual los entrega el backend.
export function buildJson(runOrRuns) {
  return JSON.stringify(runOrRuns, null, 2);
}

// Nombre de archivo seguro para una descarga (sin caracteres problemáticos en FS).
export function exportFilename(prefix, ext) {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const safePrefix = String(prefix || "inferbench").replace(/[^\w.-]+/g, "_");
  return `${safePrefix}-${stamp}.${ext}`;
}

// Dispara la descarga de un archivo de texto en el navegador (Electron incluido).
// Aislado para poder mockearlo en tests. Devuelve true si pudo iniciar la descarga.
export function downloadTextFile(filename, text, mime = "text/plain") {
  if (typeof document === "undefined" || typeof URL?.createObjectURL !== "function") {
    return false;
  }
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Liberar el object URL en el siguiente tick (algunos navegadores necesitan que el
  // click se procese antes de revocar).
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return true;
}

// Helpers de alto nivel: construyen el contenido + el nombre y disparan la descarga.
export function exportRunsCsv(runOrRuns, prefix = "inferbench") {
  return downloadTextFile(exportFilename(prefix, "csv"), buildCsv(runOrRuns), "text/csv");
}

export function exportRunsJson(runOrRuns, prefix = "inferbench") {
  return downloadTextFile(
    exportFilename(prefix, "json"),
    buildJson(runOrRuns),
    "application/json",
  );
}
