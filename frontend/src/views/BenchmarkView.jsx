import { useEffect, useRef, useState } from "react";
import { Play, Square } from "lucide-react";
import { api, humanizeError } from "../api";
import { PageHeader, Card, Field, Select, Input, Button, Badge, Stat } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";

const ALL_PROMPTS = [
  { id: "reasoning", label: "Razonamiento" },
  { id: "code", label: "Código" },
  { id: "summary", label: "Resumen" },
  { id: "chat", label: "Chat" },
];

const QUANTS = [
  "Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS",
  "Q3_K_M", "IQ3_M", "Q2_K", "IQ2_M", "IQ2_XS", "IQ2_XXS", "IQ1_M", "IQ1_S",
];

// Mapea kv_cache del optimizador → preset de compresión del frontend
const KV_TO_COMPRESSION = { f16: "quality", q8_0: "balanced", q5_0: "compressed", q4_0: "aggressive" };

// Etiquetas legibles para el status de compatibilidad de cada cuantización
const STATUS_LABEL = { ok: "ok", moe: "MoE", partial: "~RAM", cpu: "solo CPU", disk: "no cabe", fail: "error", nofile: "sin archivo" };
const statusLabel = (s) => STATUS_LABEL[s] || s;
const isQuantDisabled = (s) => s === "disk" || s === "fail" || s === "nofile";

const COMPRESSION_PRESETS = [
  {
    id: "quality", label: "Calidad", kvK: "f16", kvV: "f16", nkvo: false, swaFull: false, factor: 1.0,
    desc: "Sin compresión KV — máxima precisión.",
    what: "La KV-cache se guarda en 16 bits (f16), sin comprimir.",
    affects: "Ocupa el doble de VRAM que q8_0; en contextos largos llena la VRAM rápido.",
    allows: "La mejor calidad posible. Ideal para modelos pequeños/medianos donde la VRAM sobra.",
  },
  {
    id: "balanced", label: "Equilibrado", kvK: "q8_0", kvV: "q8_0", nkvo: false, swaFull: false, factor: 0.5,
    desc: "KV q8_0 — 50% menos memoria, calidad casi idéntica.",
    what: "K y V cuantizados a 8 bits (q8_0).",
    affects: "Mitad de memoria de KV-cache con pérdida de calidad imperceptible.",
    allows: "El punto dulce por defecto: más contexto o un modelo algo mayor sin notar degradación.",
  },
  {
    id: "compressed", label: "Comprimido", kvK: "q8_0", kvV: "iq4_nl", nkvo: false, swaFull: false, factor: 0.38,
    desc: "K=q8_0 + V=iq4_nl — ~60% menos. Buena para contextos largos.",
    what: "K en 8 bits (preciso) y V en 4 bits i-quant (iq4_nl, moderno).",
    affects: "~60% menos KV; la clave (K) sigue precisa, solo el valor (V) se comprime más.",
    allows: "Contextos largos (16k–32k+) manteniendo buena calidad de respuesta.",
  },
  {
    id: "aggressive", label: "Agresivo", kvK: "q4_0", kvV: "q4_0", nkvo: false, swaFull: false, factor: 0.25,
    desc: "KV q4_0 — 75% menos memoria. Algo de calidad sacrificada.",
    what: "K y V cuantizados a 4 bits (q4_0).",
    affects: "75% menos memoria de KV; se nota algo de pérdida de precisión en contextos muy largos.",
    allows: "Contextos enormes o cargar un modelo bastante más grande en la misma GPU.",
  },
  {
    id: "extreme", label: "Extremo", kvK: "q4_0", kvV: "q4_0", nkvo: true, swaFull: false, factor: 0.25,
    desc: "q4_0 + KV en RAM (no-kv-offload). Libera VRAM al máximo.",
    what: "KV en 4 bits Y movida a RAM del sistema (--no-kv-offload); la VRAM solo guarda los pesos.",
    affects: "Libera toda la VRAM que usaría la KV, pero baja los tok/s (la KV viaja por PCIe).",
    allows: "El modelo más grande posible con los pesos 100% en GPU, delegando la KV a la RAM.",
  },
];

export default function BenchmarkView({ dockerDown, navPayload, benchmark }) {
  const [engines, setEngines] = useState([]);
  const [models, setModels] = useState([]);
  const [engine, setEngine] = useState("llamacpp");
  const [model, setModel] = useState("");
  const [quant, setQuant] = useState("Q4_K_M");
  const [sweepQuants, setSweepQuants] = useState([]);
  const [localModel, setLocalModel] = useState(null);
  const [compression, setCompression] = useState("balanced");
  const [feasibleQuants, setFeasibleQuants] = useState({}); // { Q4_K_M: 'ok', IQ1_S: 'disk', ... }
  const [loadingQuants, setLoadingQuants] = useState(false);
  const [engineRecs, setEngineRecs] = useState([]); // lista de EngineRec para el modelo actual
  const [loadingRecs, setLoadingRecs] = useState(false);
  const [customCtx, setCustomCtx] = useState(""); // override de contexto

  // Estado del benchmark vive en App (vía useBenchmarkRun) para sobrevivir
  // al desmontaje de esta vista al cambiar de pestaña.
  const { running, events, results, progress, start: startBench, stop: stopBench, subscribe, log: bLog, clear: bClear } = benchmark;
  const toast = useToast();

  // Aplicar config de navegación (desde Dashboard u otras vistas)
  useEffect(() => {
    if (navPayload?.config) {
      // Viene con la config completa del optimizador
      const cfg = navPayload.config;
      setLocalModel(null);
      setModel(cfg.model_id);
      setEngine(cfg.engine || "llamacpp");
      if (cfg.quant) setQuant(cfg.quant);
      // kv_cache q4_0 + nkvo=true → "extreme"; q4_0 sin nkvo → "aggressive"
      const compression =
        cfg.kv_cache === "q4_0" && cfg.flags?.nkvo
          ? "extreme"
          : KV_TO_COMPRESSION[cfg.kv_cache] || "balanced";
      setCompression(compression);
      // No tocamos customCtx — debe seguir como override manual del usuario ("auto" por defecto)
    } else if (navPayload?.localModel) {
      const m = navPayload.localModel;
      setLocalModel(m);
      if (m.quant) setQuant(m.quant);
      setEngine("llamacpp");
    } else if (navPayload?.model) {
      setLocalModel(null);
      setModel(navPayload.model);
      setEngine("llamacpp");
    }
  }, [navPayload]);

  // Re-optimizar automáticamente cuando cambia modelo o motor: evita combinaciones
  // imposibles (ej. TinyLlama 1.1B con quant IQ1_M heredado de un modelo grande, que
  // bartowski no publica en HF y produce 401). Sólo actualiza quant y compresión —
  // el contexto (customCtx) sigue siendo override manual del usuario.
  useEffect(() => {
    if (!model || localModel) return;
    let cancelled = false;
    api
      .optimize(engine, model)
      .then((res) => {
        if (cancelled || !res?.config?.feasible) return;
        const cfg = res.config;
        if (cfg.quant) setQuant(cfg.quant);
        const comp =
          cfg.kv_cache === "q4_0" && cfg.flags?.nkvo
            ? "extreme"
            : KV_TO_COMPRESSION[cfg.kv_cache] || "balanced";
        setCompression(comp);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [model, engine, localModel]);
  const [prompts, setPrompts] = useState(ALL_PROMPTS.map((p) => p.id));
  const [keepAlive, setKeepAlive] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [judgeMode, setJudgeMode] = useState("heuristic"); // heuristic | self | api
  const [judgeApi, setJudgeApi] = useState({ engine: "openai", model: "gpt-4o-mini", base_url: "", api_key: "" });

  useEffect(() => {
    api.listEngines().then(setEngines).catch(() => {});
    api.listModels().then((m) => {
      setModels(m);
      // Funcional para leer el valor actual de model, no el del closure (que es "" al
      // montar). Sin esto, si navPayload ya seteó el modelo, lo pisamos con m[0].
      if (m[0]) setModel((prev) => prev || m[0].id);
    });
  }, []);

  // Cargar status real de cada cuantización cuando cambia modelo o motor
  useEffect(() => {
    const selEng = engines.find((e) => e.meta.id === engine);
    const isApi = selEng?.meta.type === "api";
    if (!model || localModel || isApi || !engines.length) {
      setFeasibleQuants({});
      return;
    }
    let cancelled = false;
    setLoadingQuants(true);
    api
      .getQuants(engine, model)
      .then((rows) => {
        if (cancelled) return;
        const map = {};
        for (const row of rows) map[row.quant] = row.status;
        setFeasibleQuants(map);
        // Si la quant actual es inviable, auto-cambiar a la mejor disponible
        setQuant((prev) => {
          if (isQuantDisabled(map[prev])) {
            const best = rows.find((r) => !isQuantDisabled(r.status));
            return best ? best.quant : prev;
          }
          return prev;
        });
        // Sacar del sweep las quants inviables
        setSweepQuants((prev) => prev.filter((q) => !isQuantDisabled(map[q])));
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingQuants(false); });
    return () => { cancelled = true; };
  }, [model, engine, localModel, engines]);

  // Cargar recomendaciones de motor para el modelo seleccionado
  useEffect(() => {
    if (!model || localModel) {
      setEngineRecs([]);
      return;
    }
    let cancelled = false;
    setLoadingRecs(true);
    api
      .getModelEngines(model)
      .then((recs) => { if (!cancelled) setEngineRecs(recs); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingRecs(false); });
    return () => { cancelled = true; };
  }, [model, localModel]);

  const selectedEngine = engines.find((e) => e.meta.id === engine);
  const engineIsApi = selectedEngine?.meta.type === "api";
  const selectedModel = models.find((m) => m.id === model);
  const modelHasGguf = !!selectedModel?.hf_gguf;
  const apiNeedsKey = engineIsApi && !apiKey;
  // Determinar si el motor está listo para arrancar
  const engineNativeReady = selectedEngine?.runtimes?.some(
    (r) => r.runtime === "native" && r.ready
  );
  const engineDockerReady = selectedEngine?.runtimes?.some(
    (r) => r.runtime === "docker" && r.ready
  );
  const engineSomeReady = engineNativeReady || engineDockerReady;
  const canRun = engineIsApi
    ? !apiNeedsKey
    : engine === "llamacpp"
    ? !!localModel || modelHasGguf
    : engine === "ollama"
    ? engineNativeReady && !!selectedModel?.ollama_tag
    : ["vllm", "sglang", "tgi"].includes(engine)
    ? engineDockerReady && !!selectedModel?.hf_repo
    : selectedEngine?.status?.state === "running";

  const start = async () => {
    try {
      const preset = COMPRESSION_PRESETS.find((p) => p.id === compression);
      const engineOpts = {
        kvCacheK: preset?.kvK || "q8_0",
        kvCacheV: preset?.kvV || "q8_0",
        nkvo: !!preset?.nkvo,
        swaFull: !!preset?.swaFull,
      };
      if (customCtx) engineOpts.contextLen = Number(customCtx);
      await startBench({
        engine,
        model: localModel ? (localModel.architecture || "local") + "-local" : model,
        quant,
        prompts,
        auto: !engineIsApi,
        keep_alive: keepAlive,
        api_key: apiKey || null,
        local_path: localModel ? localModel.path : null,
        engine_opts: engineOpts,
        judge:
          judgeMode === "api"
            ? {
                mode: "api",
                engine: judgeApi.engine,
                model: judgeApi.model,
                base_url: judgeApi.base_url || null,
                api_key: judgeApi.api_key || null,
              }
            : { mode: judgeMode },
        notes: localModel
          ? `local: ${localModel.filename} · ${compression}`
          : `compresión: ${compression}`,
      });
    } catch (e) {
      // El hook ya logueó el evento, sólo dejamos un fallback por si la API falla antes
      console.error("startBench failed:", e);
      toast.error(humanizeError(e, "No se pudo lanzar el benchmark"));
    }
  };

  const stop = async () => {
    try {
      await stopBench();
    } catch (e) {
      console.warn("stopBench:", e);
    }
  };

  const startSweep = async () => {
    if (!sweepQuants.length) return;
    bClear();
    bLog("info", `Sweep: ${sweepQuants.join(", ")}`);
    try {
      const base = {
        engine,
        model,
        prompts,
        auto: !engineIsApi,
        keep_alive: false,
        api_key: apiKey || null,
        notes: `sweep ${sweepQuants.join("+")}`,
      };
      const { sweep_id } = await api.startSweep(base, sweepQuants);
      bLog("info", `Sweep arrancado: ${sweep_id}`);
      pollSweep(sweep_id);
    } catch (e) {
      bLog("error", e.message);
      toast.error(humanizeError(e, "No se pudo lanzar el sweep"));
    }
  };

  const pollSweep = async (sweepId) => {
    let lastRunId = null;
    while (true) {
      try {
        const status = await api.sweepStatus(sweepId);
        if (status.current && status.current !== lastRunId) {
          lastRunId = status.current;
          bLog("info", `→ run ${lastRunId}`);
          subscribe(lastRunId); // re-suscribe a la nueva sub-corrida; setea running
        }
        if (status.completed || status.cancelled) {
          bLog("success", `Sweep terminado (${status.runs.length} runs)`);
          return;
        }
      } catch (e) {
        bLog("warn", `poll: ${e.message}`);
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  };

  const toggleSweepQuant = (q) =>
    setSweepQuants((s) => (s.includes(q) ? s.filter((x) => x !== q) : [...s, q]));

  const togglePrompt = (id) =>
    setPrompts((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <>
      <PageHeader
        title="Benchmark"
        subtitle="La app descarga binario + modelo, arranca el motor y ejecuta la suite con un solo click"
      />
      <div className="grid gap-6 p-8 lg:grid-cols-2">
        <Card title="Configuración">
          <div className="grid gap-4">
            <Field label="Motor">
              <Select
                value={engine}
                onChange={(e) => setEngine(e.target.value)}
                disabled={!!running}
              >
                {engines.map((e) => {
                  const isApi = e.meta.type === "api";
                  const runtimeReady = isApi || e.runtimes?.some((r) => r.ready);
                  return (
                    <option key={e.meta.id} value={e.meta.id} disabled={!runtimeReady}>
                      {e.meta.name} ({e.meta.type}){!runtimeReady ? " · no instalado" : ""}
                    </option>
                  );
                })}
              </Select>
            </Field>
            {engineRecs.length > 0 && !localModel && (
              <EngineMatrix
                recs={engineRecs}
                loading={loadingRecs}
                selectedEngine={engine}
                onSelect={(id) => !running && setEngine(id)}
              />
            )}
            {localModel ? (
              <Field label="GGUF local seleccionado">
                <div className="rounded border border-emerald-700/40 bg-emerald-950/20 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-emerald-200">
                        {localModel.name || localModel.filename}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-slate-400" title={localModel.path}>
                        {localModel.path}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
                        {localModel.architecture && <Badge tone="indigo">{localModel.architecture}</Badge>}
                        {localModel.quant && <Badge>{localModel.quant}</Badge>}
                        <Badge tone="slate">{localModel.size_gb} GB</Badge>
                        {localModel.params_b && <Badge tone="slate">{localModel.params_b}B</Badge>}
                        {localModel.is_moe && <Badge tone="purple">MoE</Badge>}
                      </div>
                    </div>
                    <button
                      onClick={() => setLocalModel(null)}
                      className="text-xs text-slate-500 hover:text-rose-300"
                      disabled={!!running}
                    >
                      cambiar
                    </button>
                  </div>
                </div>
              </Field>
            ) : (
              <Field label="Modelo">
                <Select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  disabled={!!running}
                >
                  {models.map((m) => {
                    const compatible = engineIsApi
                      ? true
                      : engine === "llamacpp"
                      ? !!m.hf_gguf
                      : engine === "ollama"
                      ? !!m.ollama_tag
                      : ["vllm", "sglang", "tgi"].includes(engine)
                      ? !!m.hf_repo
                      : true;
                    return (
                      <option key={m.id} value={m.id} disabled={!compatible}>
                        {m.name}{!compatible ? " · incompatible" : ""}
                      </option>
                    );
                  })}
                </Select>
                {!engineIsApi && !modelHasGguf && engine === "llamacpp" && (
                  <p className="mt-1 text-xs text-amber-300">
                    Este modelo no tiene fuente GGUF. Elige otro o usa Modelos → Locales.
                  </p>
                )}
              </Field>
            )}
            {!engineIsApi && !localModel && (
              <>
                <Field
                  label="Cuantización"
                  hint={loadingQuants ? "Comprobando compatibilidad…" : "Para una sola corrida"}
                >
                  <Select value={quant} onChange={(e) => setQuant(e.target.value)} disabled={!!running}>
                    {QUANTS.map((q) => {
                      const st = feasibleQuants[q];
                      const disabled = isQuantDisabled(st);
                      return (
                        <option key={q} value={q} disabled={disabled}>
                          {q}{st ? ` · ${statusLabel(st)}` : ""}
                        </option>
                      );
                    })}
                  </Select>
                </Field>
                <Field label="Sweep" hint="Marca varias para comparar (corre secuencial)">
                  <div className="flex flex-wrap gap-2">
                    {QUANTS.map((q) => {
                      const st = feasibleQuants[q];
                      const infeasible = isQuantDisabled(st);
                      const selected = sweepQuants.includes(q);
                      return (
                        <button
                          key={q}
                          type="button"
                          onClick={() => !infeasible && toggleSweepQuant(q)}
                          disabled={!!running || infeasible}
                          title={st ? statusLabel(st) : undefined}
                          className={`rounded-md border px-2 py-1 text-xs transition-opacity ${
                            infeasible
                              ? "cursor-not-allowed border-slate-800 text-slate-600 opacity-40"
                              : selected
                              ? "border-purple-500 bg-purple-500/10 text-purple-200"
                              : st === "cpu"
                              ? "border-amber-800/60 text-amber-600 hover:text-amber-400"
                              : st === "partial"
                              ? "border-yellow-700/60 text-yellow-600 hover:text-yellow-400"
                              : "border-slate-700 text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          {q}
                        </button>
                      );
                    })}
                  </div>
                </Field>
              </>
            )}
            {!engineIsApi && (
              <CompressionField
                value={compression}
                onChange={setCompression}
                running={!!running}
                model={selectedModel}
                localModel={localModel}
                customCtx={customCtx}
                onCustomCtx={setCustomCtx}
              />
            )}
            {engineIsApi && (
              <Field label="API key">
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  disabled={!!running}
                />
              </Field>
            )}
            <Field label="Prompts">
              <div className="flex flex-wrap gap-2">
                {ALL_PROMPTS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => togglePrompt(p.id)}
                    disabled={!!running}
                    className={`rounded-md border px-3 py-1 text-xs ${
                      prompts.includes(p.id)
                        ? "border-indigo-500 bg-indigo-500/10 text-indigo-200"
                        : "border-slate-700 text-slate-400"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </Field>
            <JudgeField
              mode={judgeMode}
              onMode={setJudgeMode}
              api={judgeApi}
              onApi={setJudgeApi}
              running={!!running}
            />
            {!engineIsApi && (
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={keepAlive}
                  onChange={(e) => setKeepAlive(e.target.checked)}
                  disabled={!!running}
                />
                No detener el motor al terminar (más rápido si vas a relanzar)
              </label>
            )}
            <div className="flex flex-wrap gap-2 pt-2">
              {!running ? (
                <>
                  <Button onClick={start} disabled={!model || !prompts.length || !canRun}>
                    <Play size={14} /> Lanzar benchmark
                  </Button>
                  {sweepQuants.length > 0 && !engineIsApi && (
                    <Button onClick={startSweep} variant="success" disabled={!model || !canRun}>
                      <Play size={14} /> Sweep ({sweepQuants.length} quants)
                    </Button>
                  )}
                </>
              ) : (
                <Button variant="danger" onClick={stop}>
                  <Square size={14} /> Detener
                </Button>
              )}
              {running && (
                <span className="self-center text-xs text-slate-500">run {running}</span>
              )}
            </div>
            {!engineIsApi && !running && (
              <EngineHint engine={engine} selectedEngine={selectedEngine} selectedModel={selectedModel} />
            )}
          </div>
        </Card>

        <RunningPanel events={events} progress={progress} running={!!running} />

        {results.length > 0 && (
          <Card title="Resultados" className="lg:col-span-2">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                  <tr className="border-b border-slate-800">
                    <th className="py-2 pr-3">Prompt</th>
                    <th className="py-2 pr-3">TTFT</th>
                    <th className="py-2 pr-3">tok/s</th>
                    <th className="py-2 pr-3">VRAM peak</th>
                    <th className="py-2 pr-3">RAM peak</th>
                    <th className="py-2 pr-3">Calidad</th>
                    <th className="py-2 pr-3">Tokens</th>
                    <th className="py-2 pr-3">Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={i} className="border-b border-slate-900">
                      <td className="py-2 pr-3 font-medium">{r.prompt_id}</td>
                      <td className="py-2 pr-3 tabular-nums">{r.ttft_ms} ms</td>
                      <td className="py-2 pr-3 tabular-nums">{r.tps}</td>
                      <td className="py-2 pr-3 tabular-nums">{r.vram_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums">{r.ram_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums">{r.quality}</td>
                      <td className="py-2 pr-3 tabular-nums">{r.ctx_used}</td>
                      <td className="py-2 pr-3">
                        {r.error ? <Badge tone="rose">error</Badge> : <Badge tone="emerald">ok</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {!engineIsApi && (
          <PowerByCompression
            engine={engine}
            contextLen={Number(customCtx) || 8192}
            selected={compression}
          />
        )}
      </div>
    </>
  );
}

function PowerByCompression({ engine, contextLen, selected }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(() => {
      api
        .getByCompression(engine, contextLen)
        .then((r) => !cancelled && setRows(r))
        .catch(() => !cancelled && setRows([]))
        .finally(() => !cancelled && setLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [engine, contextLen]);

  return (
    <Card title="Modelos más potentes por compresión" className="lg:col-span-2">
      <p className="mb-3 text-xs text-slate-400">
        Para tu hardware y un contexto de{" "}
        <span className="font-mono text-slate-300">{contextLen.toLocaleString()}</span> tokens:
        comprimir la KV-cache libera VRAM y te deja cargar modelos más grandes 100% en la GPU.
      </p>
      {loading && rows.length === 0 ? (
        <p className="text-sm text-slate-500">Calculando…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-3">Compresión</th>
                <th className="py-2 pr-3">KV</th>
                <th className="py-2 pr-3">Más potente · 100% GPU</th>
                <th className="py-2 pr-3">KV-cache</th>
                <th className="py-2 pr-3">Más grande ejecutable</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const ok = p.top_full_gpu;
                const run = p.top_runnable;
                return (
                  <tr
                    key={p.preset}
                    className={`border-b border-slate-900 ${
                      selected === p.preset ? "bg-indigo-950/20" : ""
                    }`}
                  >
                    <td className="py-2 pr-3 font-medium text-slate-200">{p.label}</td>
                    <td className="py-2 pr-3">
                      <Badge tone="slate">
                        {p.kv_k}/{p.kv_v}
                        {p.kv_in_ram ? "·RAM" : ""}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">
                      {ok ? (
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="font-medium text-emerald-200">{ok.name}</span>
                          <Badge tone="indigo">{ok.quant}</Badge>
                          <span className="text-xs text-slate-500">{ok.params_b}B</span>
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-slate-400">
                      {ok ? `${ok.kv_gb} GB` : "—"}
                    </td>
                    <td className="py-2 pr-3">
                      {run ? (
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="text-slate-300">{run.name}</span>
                          <span className="text-xs text-slate-500">{run.params_b}B</span>
                          {run.status !== "ok" && <Badge tone="amber">{run.status}</Badge>}
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function JudgeField({ mode, onMode, api, onApi, running }) {
  const MODES = [
    { id: "heuristic", label: "Referencia (offline)", hint: "Cobertura de la respuesta de referencia (datos clave, números) + no-degeneración. Sin GPU/API: funciona en cualquier PC. Aproximado en tareas abiertas (chat)." },
    { id: "self", label: "LLM-judge (motor local)", hint: "El propio modelo puntúa. Sin coste, pero solo fiable con modelos capaces (≥7-8B); los pequeños (1-3B) colapsan a 0. Juez = modelo evaluado (sesgo)." },
    { id: "api", label: "LLM-judge (API externa)", hint: "Un modelo cloud OpenAI-compatible (p.ej. gpt-4o-mini) juzga. Lo más fiable e imparcial; requiere API key." },
  ];
  const cur = MODES.find((m) => m.id === mode) || MODES[0];
  return (
    <Field label="Evaluación de calidad" hint={cur.hint}>
      <Select value={mode} onChange={(e) => onMode(e.target.value)} disabled={running}>
        {MODES.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </Select>
      {mode === "api" && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Input
            placeholder="base_url (ej. https://api.openai.com)"
            value={api.base_url}
            onChange={(e) => onApi({ ...api, base_url: e.target.value })}
            disabled={running}
          />
          <Input
            placeholder="modelo juez (ej. gpt-4o-mini)"
            value={api.model}
            onChange={(e) => onApi({ ...api, model: e.target.value })}
            disabled={running}
          />
          <Input
            type="password"
            placeholder="API key del juez"
            value={api.api_key}
            onChange={(e) => onApi({ ...api, api_key: e.target.value })}
            disabled={running}
            className="col-span-2"
          />
        </div>
      )}
    </Field>
  );
}

function CompressionField({ value, onChange, running, model, localModel, customCtx, onCustomCtx }) {
  const preset = COMPRESSION_PRESETS.find((p) => p.id === value);
  // Estimación de bytes/token de KV cache en función del modelo seleccionado
  // Heurística: kv_per_token_MB(f16) ≈ 0.5 * (params/7)^0.7
  const params = model?.params_b || localModel?.params_b || 0;
  const kvF16Mb = params > 0 ? 0.5 * Math.pow(params / 7, 0.7) : 0;
  const kvActualKb = kvF16Mb * (preset?.factor || 0.5) * 1024;
  const ctx = Number(customCtx) || 4096;
  const kvAtCtxMb = (kvActualKb * ctx) / 1024;

  return (
    <div className="space-y-2">
      <Field
        label="Compresión de KV-cache"
        hint={preset?.desc}
      >
        <div className="grid grid-cols-5 gap-1 rounded-md border border-slate-700 bg-slate-900/40 p-1">
          {COMPRESSION_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onChange(p.id)}
              disabled={running}
              title={`${p.label} — ${p.desc}`}
              className={`rounded px-2 py-1.5 text-[11px] font-medium transition ${
                value === p.id
                  ? p.id === "quality"
                    ? "bg-emerald-500 text-white"
                    : p.id === "balanced"
                    ? "bg-indigo-500 text-white"
                    : p.id === "compressed"
                    ? "bg-cyan-500 text-white"
                    : p.id === "aggressive"
                    ? "bg-amber-500 text-white"
                    : "bg-rose-500 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </Field>

      <details className="rounded-md border border-slate-800 bg-slate-900/30 px-3 py-2">
        <summary className="cursor-pointer text-[11px] font-medium uppercase tracking-wider text-slate-400 hover:text-slate-200">
          ¿Qué hace cada compresión?
        </summary>
        <div className="mt-3 space-y-2.5">
          {COMPRESSION_PRESETS.map((p) => (
            <div
              key={p.id}
              className={`rounded border p-2.5 text-xs ${
                value === p.id ? "border-indigo-600/50 bg-indigo-950/20" : "border-slate-800 bg-slate-900/20"
              }`}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className="font-semibold text-slate-200">{p.label}</span>
                <Badge tone="slate">K={p.kvK} · V={p.kvV}{p.nkvo ? " · RAM" : ""}</Badge>
              </div>
              <dl className="grid grid-cols-[88px_1fr] gap-x-2 gap-y-0.5 text-slate-400">
                <dt className="text-slate-500">Qué hace</dt><dd className="text-slate-300">{p.what}</dd>
                <dt className="text-slate-500">En qué afecta</dt><dd>{p.affects}</dd>
                <dt className="text-slate-500">Qué permite</dt><dd className="text-emerald-300/90">{p.allows}</dd>
              </dl>
            </div>
          ))}
        </div>
      </details>

      <div className="grid grid-cols-2 gap-3">
        <Field
          label="Contexto (override)"
          hint={`Auto: el optimizador calcula el máximo. Pon un número para forzar.`}
        >
          <Input
            type="number"
            placeholder="auto"
            value={customCtx}
            onChange={(e) => onCustomCtx(e.target.value)}
            disabled={running}
          />
        </Field>
        <div className="flex flex-col justify-end rounded-md border border-slate-800 bg-slate-900/40 p-2 text-xs">
          <div className="text-slate-500">KV-cache en {ctx.toLocaleString()} tokens</div>
          <div className="mt-0.5 font-mono text-sm text-slate-200">
            ≈ {kvAtCtxMb < 1024 ? `${kvAtCtxMb.toFixed(0)} MB` : `${(kvAtCtxMb / 1024).toFixed(2)} GB`}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            K={preset?.kvK} · V={preset?.kvV}{preset?.nkvo ? " · en RAM" : ""}
          </div>
        </div>
      </div>
    </div>
  );
}

function EngineHint({ engine, selectedEngine, selectedModel }) {
  const nativeRt = selectedEngine?.runtimes?.find((r) => r.runtime === "native");
  const dockerRt = selectedEngine?.runtimes?.find((r) => r.runtime === "docker");

  if (engine === "llamacpp") {
    return (
      <p className="text-xs text-slate-500">
        Si es la primera vez: descarga binario llama.cpp (~300MB + cudart si hay NVIDIA) + el GGUF
        del modelo. Cacheado en <code>%APPDATA%\InferBench\</code>.
      </p>
    );
  }
  if (engine === "ollama") {
    if (nativeRt && !nativeRt.ready) {
      return (
        <div className="rounded border border-amber-700/40 bg-amber-950/30 p-3 text-xs text-amber-100">
          <p className="font-semibold">Ollama no instalado.</p>
          <p className="mt-1 opacity-80">
            Descárgalo (~700MB) e instálalo, después vuelve y la app detectará el binario:
          </p>
          {nativeRt.install_url && (
            <a
              href={nativeRt.install_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block rounded border border-amber-600/60 px-2 py-0.5 hover:bg-amber-900/40"
            >
              Descargar Ollama →
            </a>
          )}
        </div>
      );
    }
    return (
      <p className="text-xs text-slate-500">
        Ollama listo. La app pulleará{" "}
        <code className="text-slate-300">{selectedModel?.ollama_tag || "el modelo"}</code> desde el
        registro de Ollama si no lo tienes ya.
      </p>
    );
  }
  if (["vllm", "sglang", "tgi"].includes(engine)) {
    if (dockerRt && !dockerRt.ready) {
      return (
        <div className="rounded border border-amber-700/40 bg-amber-950/30 p-3 text-xs text-amber-100">
          <p className="font-semibold">Docker requerido para {engine}.</p>
          <p className="mt-1 opacity-80">
            Arranca Docker Desktop. {engine} corre en GPU NVIDIA dentro del contenedor.
          </p>
        </div>
      );
    }
    return (
      <p className="text-xs text-slate-500">
        Primera vez: pull de la imagen Docker (~6GB para vLLM/SGLang/TGI) + descarga del modelo HF
        dentro del contenedor. Puede tardar varios minutos.
      </p>
    );
  }
  return null;
}

const ENGINE_SOURCE_LABEL = { gguf: "GGUF", ollama: "Ollama", hf_repo: "HF repo", api: "API", none: "—" };
const ENGINE_STATUS_COLOR = {
  ok: "text-emerald-400",
  moe: "text-yellow-400",
  partial: "text-amber-400",
  cpu: "text-slate-400",
  disk: "text-rose-400",
  fail: "text-rose-400",
  api: "text-indigo-400",
  nofile: "text-rose-400",
};
const SCORE_BAR_COLOR = (score) =>
  score >= 0.8 ? "bg-emerald-500" : score >= 0.5 ? "bg-amber-500" : score > 0 ? "bg-slate-500" : "bg-rose-900";

function EngineMatrix({ recs, loading, selectedEngine, onSelect }) {
  if (loading && recs.length === 0) {
    return (
      <div className="rounded border border-slate-800 bg-slate-900/30 p-2 text-center text-xs text-slate-500">
        Comprobando motores…
      </div>
    );
  }
  // Mostrar solo motores locales + mejor API si hay alguna; no mostrar los cloud todos
  const local = recs.filter((r) => r.type !== "api");
  const bestApi = recs.filter((r) => r.type === "api" && r.score > 0)[0];
  const visible = bestApi ? [...local, bestApi] : local;

  return (
    <div className="overflow-hidden rounded border border-slate-800 bg-slate-900/30">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-1.5">
        <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
          Motores para este modelo
        </span>
        {loading && <span className="text-[10px] text-slate-600">actualizando…</span>}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-800/60 text-left text-[10px] uppercase tracking-wider text-slate-600">
            <th className="px-3 py-1.5">Motor</th>
            <th className="px-2 py-1.5">Mejor quant</th>
            <th className="px-2 py-1.5">Fuente</th>
            <th className="px-2 py-1.5">Runtime</th>
            <th className="px-3 py-1.5">Score</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => {
            const isSelected = r.engine_id === selectedEngine;
            const clickable = r.feasible && r.runtime_ready;
            return (
              <tr
                key={r.engine_id}
                onClick={() => clickable && onSelect(r.engine_id)}
                title={
                  !r.model_available
                    ? "Modelo no disponible en este origen"
                    : !r.runtime_ready
                    ? "Runtime no instalado"
                    : !r.feasible
                    ? "No cabe en el hardware"
                    : "Click para seleccionar este motor"
                }
                className={`border-b border-slate-800/40 transition-colors last:border-0 ${
                  isSelected
                    ? "bg-indigo-900/20"
                    : clickable
                    ? "cursor-pointer hover:bg-slate-800/40"
                    : "cursor-default opacity-50"
                }`}
              >
                <td className="px-3 py-1.5 font-medium">
                  {isSelected && <span className="mr-1 text-indigo-400">▶</span>}
                  {r.engine_name}
                </td>
                <td className={`px-2 py-1.5 font-mono ${ENGINE_STATUS_COLOR[r.status] || "text-slate-400"}`}>
                  {r.best_quant || "—"}
                  {r.status !== "ok" && r.status !== "api" && (
                    <span className="ml-1 text-[10px] opacity-70">({r.status})</span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-slate-400">
                  {ENGINE_SOURCE_LABEL[r.model_source] || r.model_source}
                  {!r.model_available && <span className="ml-1 text-rose-400">✗</span>}
                </td>
                <td className="px-2 py-1.5">
                  {r.type === "api" ? (
                    <span className="text-indigo-400">cloud</span>
                  ) : r.runtime_ready ? (
                    <span className="text-emerald-400">listo</span>
                  ) : (
                    <span className="text-amber-500">no instalado</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded bg-slate-800">
                      <div
                        className={`h-full transition-all ${SCORE_BAR_COLOR(r.score)}`}
                        style={{ width: `${r.score * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] tabular-nums text-slate-500">
                      {Math.round(r.score * 100)}
                    </span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RunningPanel({ events, progress, running }) {
  const logRef = useRef(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events]);

  return (
    <Card title="Ejecución">
      <BootstrapProgress progress={progress} />
      <TokensProgress progress={progress} />

      <div
        ref={logRef}
        className="mt-4 h-72 overflow-y-auto rounded border border-slate-800 bg-black/60 p-3 font-mono text-[11px] leading-relaxed"
      >
        {events.length === 0 && (
          <p className="text-slate-600">
            {running ? "Esperando eventos…" : "Configura y pulsa Lanzar benchmark."}
          </p>
        )}
        {events.map((e, i) => (
          <LogLine key={i} evt={e} />
        ))}
      </div>
    </Card>
  );
}

function BootstrapProgress({ progress }) {
  if (progress.kind === "engine.install") {
    return (
      <PhasePanel label="Descargando binario llama.cpp" progress={progress} color="indigo" />
    );
  }
  if (progress.kind === "model.download") {
    return (
      <PhasePanel label={`Descargando ${progress.name || "GGUF"}`} progress={progress} color="purple" />
    );
  }
  if (progress.kind === "engine.ready") {
    return (
      <div className="rounded border border-emerald-700/40 bg-emerald-950/30 p-3 text-sm text-emerald-200">
        ✓ Motor listo
      </div>
    );
  }
  return null;
}

function PhasePanel({ label, progress, color }) {
  const pct = progress.pct || 0;
  const dl = progress.downloaded || 0;
  const sz = progress.size || 0;
  const colors = {
    indigo: "border-indigo-700/40 bg-indigo-950/20 text-indigo-200",
    purple: "border-purple-700/40 bg-purple-950/20 text-purple-200",
  };
  return (
    <div className={`rounded border p-3 text-sm ${colors[color]}`}>
      <div className="flex items-center justify-between">
        <span>{label}</span>
        <span className="text-xs opacity-70">
          {fmtBytes(dl)}
          {sz ? ` / ${fmtBytes(sz)}` : ""} · {pct}%
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
        <div
          className={`h-full transition-all ${color === "purple" ? "bg-purple-500" : "bg-indigo-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function TokensProgress({ progress }) {
  if (progress.kind !== "tokens") return null;
  const pct = progress.target ? Math.min(100, (progress.current / progress.target) * 100) : 0;
  return (
    <div>
      <div className="grid grid-cols-3 gap-4 pb-3">
        <Stat label="TTFT" value={progress.ttft != null ? `${progress.ttft} ms` : "—"} tone="accent" />
        <Stat label="tok/s actual" value={progress.tps || "—"} tone="success" />
        <Stat
          label="Progreso"
          value={progress.target ? `${progress.current}/${progress.target}` : "—"}
        />
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-slate-800">
        <div className="h-full bg-indigo-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function fmtBytes(n) {
  if (!n) return "0";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function LogLine({ evt }) {
  if (evt.type === "log") {
    const color =
      evt.level === "error"
        ? "text-rose-400"
        : evt.level === "warn"
        ? "text-amber-300"
        : evt.level === "success"
        ? "text-emerald-300"
        : "text-slate-400";
    return <div className={color}>[log] {evt.text}</div>;
  }
  if (evt.type === "engine.install") {
    return (
      <div className="text-indigo-300">
        [bin] {evt.phase} {evt.pct != null ? `${evt.pct}%` : ""} {evt.name || ""}
      </div>
    );
  }
  if (evt.type === "model.download") {
    return (
      <div className="text-purple-300">
        [model] {evt.phase} {evt.pct != null ? `${evt.pct}%` : ""} {evt.name || ""}
      </div>
    );
  }
  if (evt.type === "engine.start") {
    return <div className="text-cyan-300">[engine] start {evt.binary}</div>;
  }
  if (evt.type === "engine.ready") {
    return <div className="text-emerald-300">[engine] ready · {evt.base_url}</div>;
  }
  if (evt.type === "phase") {
    return (
      <div className="text-indigo-300">
        [phase] {evt.phase}
        {evt.model ? ` · ${evt.model}` : ""}
        {evt.prompt ? ` · ${evt.prompt}` : ""}
        {evt.ttft_ms ? ` · ${evt.ttft_ms}ms` : ""}
        {evt.score != null ? ` · score=${evt.score}` : ""}
        {evt.method ? ` (${evt.method})` : ""}
      </div>
    );
  }
  if (evt.type === "tokens") {
    return (
      <div className="text-emerald-300">
        [tok] {evt.current}/{evt.target} · {evt.tps_current} tok/s
      </div>
    );
  }
  if (evt.type === "result") {
    return (
      <div className="text-purple-300">
        [result] {evt.result.prompt_id} · ttft={evt.result.ttft_ms}ms · tps={evt.result.tps}
      </div>
    );
  }
  if (evt.type === "start") {
    return <div className="text-slate-300">[start] run={evt.run_id} total={evt.total}</div>;
  }
  if (evt.type === "done") {
    return <div className="text-slate-300">[done] run={evt.run_id}</div>;
  }
  return <div className="text-slate-500">{JSON.stringify(evt)}</div>;
}
