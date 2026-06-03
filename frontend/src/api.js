// Cliente HTTP del backend FastAPI en localhost:7777.
// El frontend (Vite/Electron) se comunica solo a través de este módulo.

export const API_BASE = "http://localhost:7777";

async function request(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${path}: ${text}`);
  }
  return res.json();
}

// Convierte un error de `request()` (o un fallo de red) en un mensaje accionable
// para el usuario, en vez de mostrar "HTTP 500 /api/..." crudo.
export function humanizeError(err, fallback = "Algo salió mal") {
  const msg = err?.message || String(err || "");
  if (/failed to fetch|networkerror|load failed/i.test(msg)) {
    return "No se pudo conectar con el backend (localhost:7777). ¿Está arrancado?";
  }
  const m = msg.match(/^HTTP (\d+)[^:]*:\s*([\s\S]*)$/);
  if (m) {
    const [, code, rawBody] = m;
    let detail = (rawBody || "").trim();
    try {
      const j = JSON.parse(detail); // FastAPI suele devolver {"detail": "..."}
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* cuerpo en texto plano */
    }
    detail = detail.slice(0, 240);
    if (code[0] === "5") return detail || "Error interno del backend. Revisa sus logs.";
    return detail || `Petición rechazada (HTTP ${code}).`;
  }
  return msg || fallback;
}

export const api = {
  health: () => request("/api/health"),

  // Hardware
  hardware: () => request("/api/hardware"),

  // Engines
  listEngines: () => request("/api/engines"),
  getEngine: (id) => request(`/api/engines/${id}`),
  startEngine: (id, body) =>
    request(`/api/engines/${id}/start`, { method: "POST", body: JSON.stringify(body) }),
  stopEngine: (id) => request(`/api/engines/${id}/stop`, { method: "POST" }),
  engineLogs: (id, tail = 200) => request(`/api/engines/${id}/logs?tail=${tail}`),
  engineInstallStreamUrl: (id) => `${API_BASE}/api/engines/${id}/install`,

  // Models
  listModels: () => request("/api/models"),
  listLocalModels: () => request("/api/models/local"),
  listSearchDirs: () => request("/api/models/local/dirs"),
  saveSearchDirs: (dirs) =>
    request("/api/models/local/dirs", { method: "POST", body: JSON.stringify({ dirs }) }),
  modelCompat: ({ engine, quant = "Q4_K_M", kvCache = "f16", contextLen = 4096, moeOffload }) => {
    const params = new URLSearchParams({ engine, quant, kv_cache: kvCache, context_len: contextLen });
    if (moeOffload != null) params.set("moe_offload", moeOffload);
    return request(`/api/models/compat/all?${params}`);
  },

  // Optimizer
  optimize: (engine, modelId) =>
    request("/api/optimize", { method: "POST", body: JSON.stringify({ engine, model_id: modelId }) }),
  getRecommendations: (top = 15) => request(`/api/optimize/recommendations?top=${top}`),
  getQuants: (engine, modelId, kvCache = "f16", contextLen = 4096) =>
    request(`/api/optimize/quants?engine=${engine}&model_id=${encodeURIComponent(modelId)}&kv_cache=${kvCache}&context_len=${contextLen}`),
  getModelEngines: (modelId) =>
    request(`/api/optimize/model-engines?model_id=${encodeURIComponent(modelId)}`),
  getByCompression: (engine = "llamacpp", contextLen = 8192) =>
    request(`/api/optimize/by-compression?engine=${engine}&context_len=${contextLen}`),

  // Benchmark + history
  startBenchmark: (body) =>
    request("/api/benchmark/run", { method: "POST", body: JSON.stringify(body) }),
  stopBenchmark: (runId) =>
    request(`/api/benchmark/${runId}/stop`, { method: "POST" }),
  benchmarkStreamUrl: (runId) => `${API_BASE}/api/benchmark/${runId}/stream`,

  listHistory: () => request("/api/history"),
  getHistory: (runId) => request(`/api/history/${runId}`),
  deleteHistory: (runId) => request(`/api/history/${runId}`, { method: "DELETE" }),
  compareHistory: (ids) => request(`/api/history/compare/runs?ids=${ids.join(",")}`),

  // API keys de cloud — guardadas en el keyring del SO. listKeys() solo devuelve presencia.
  listKeys: () => request("/api/keys"),
  saveKey: (provider, key) =>
    request("/api/keys", { method: "POST", body: JSON.stringify({ provider, key }) }),
  deleteKey: (provider) => request(`/api/keys/${provider}`, { method: "DELETE" }),

  startSweep: (base, quants) =>
    request("/api/benchmark/sweep", {
      method: "POST",
      body: JSON.stringify({ base, quants }),
    }),
  sweepStatus: (sweepId) => request(`/api/benchmark/sweep/${sweepId}`),
  stopSweep: (sweepId) =>
    request(`/api/benchmark/sweep/${sweepId}/stop`, { method: "POST" }),
};

// Suscripción SSE a un run de benchmark.
// onEvent({type, ...data}) recibe cada evento parseado.
export function subscribeBenchmark(runId, onEvent) {
  const es = new EventSource(api.benchmarkStreamUrl(runId));
  let finished = false;
  const handle = (e) => {
    let evt;
    try {
      evt = JSON.parse(e.data);
    } catch {
      evt = { type: e.type, raw: e.data };
    }
    if (evt.type === "done") finished = true;
    onEvent(evt);
  };
  [
    "start",
    "phase",
    "tokens",
    "result",
    "log",
    "done",
    "engine.install",
    "model.download",
    "engine.start",
    "engine.ready",
  ].forEach((t) => es.addEventListener(t, handle));
  es.onerror = () => {
    // Si el stream cae ANTES del "done" (backend caído, red, timeout) avisamos al consumidor
    // para que limpie el estado "running"; si no, la UI se quedaría colgada para siempre.
    if (!finished) {
      finished = true;
      onEvent({ type: "stream_error", error: "Se perdió la conexión con el backend" });
    }
    es.close();
  };
  return () => es.close();
}

// Suscripción a la instalación de binarios nativos.
// Nota: el navegador EventSource solo soporta GET, así que arrancamos la instalación con fetch
// y consumimos manualmente el stream SSE.
export async function installEngine(engineId, onEvent) {
  const res = await fetch(`${API_BASE}/api/engines/${engineId}/install`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const dataLine = block.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(6)));
      } catch {
        /* ignore */
      }
    }
  }
}
