import { useEffect, useRef, useState } from "react";
import { Play, Square, Image as ImageIcon } from "lucide-react";
import { api, humanizeError } from "../api";
import { PageHeader, Card, Field, Select, Input, Button, Badge, Stat } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { useT } from "../i18n/index.jsx";

const ALL_PROMPTS = [
  { id: "reasoning", labelKey: "benchmark.prompts.reasoning" },
  { id: "code", labelKey: "benchmark.prompts.code" },
  { id: "summary", labelKey: "benchmark.prompts.summary" },
  { id: "chat", labelKey: "benchmark.prompts.chat" },
  { id: "long-context", labelKey: "benchmark.prompts.longContext" },
  { id: "vision-scene", labelKey: "benchmark.prompts.visionScene", vision: true },
  { id: "vision-count", labelKey: "benchmark.prompts.visionCount", vision: true },
];
const VISION_PROMPT_IDS = ALL_PROMPTS.filter((p) => p.vision).map((p) => p.id);

// Mapea kv_cache del optimizador → preset de compresión del frontend
const KV_TO_COMPRESSION = { f16: "quality", q8_0: "balanced", q5_0: "compressed", q4_0: "aggressive" };

// Claves i18n para el status de compatibilidad de cada cuantización
const STATUS_LABEL = {
  ok: "benchmark.quantStatus.ok",
  moe: "benchmark.quantStatus.moe",
  partial: "benchmark.quantStatus.partial",
  cpu: "benchmark.quantStatus.cpu",
  disk: "benchmark.quantStatus.disk",
  fail: "benchmark.quantStatus.fail",
  nofile: "benchmark.quantStatus.nofile",
};
const statusLabelKey = (s) => STATUS_LABEL[s] || s;
const isQuantDisabled = (s) => s === "disk" || s === "fail" || s === "nofile";

// Presets de compresión. Los campos de texto guardan CLAVES i18n; el llamador hace t(...).
const COMPRESSION_PRESETS = [
  {
    id: "quality", labelKey: "benchmark.compression.quality.label", kvK: "f16", kvV: "f16", nkvo: false, swaFull: false, factor: 1.0,
    descKey: "benchmark.compression.quality.desc",
    whatKey: "benchmark.compression.quality.what",
    affectsKey: "benchmark.compression.quality.affects",
    allowsKey: "benchmark.compression.quality.allows",
  },
  {
    id: "balanced", labelKey: "benchmark.compression.balanced.label", kvK: "q8_0", kvV: "q8_0", nkvo: false, swaFull: false, factor: 0.5,
    descKey: "benchmark.compression.balanced.desc",
    whatKey: "benchmark.compression.balanced.what",
    affectsKey: "benchmark.compression.balanced.affects",
    allowsKey: "benchmark.compression.balanced.allows",
  },
  {
    id: "compressed", labelKey: "benchmark.compression.compressed.label", kvK: "q8_0", kvV: "iq4_nl", nkvo: false, swaFull: false, factor: 0.38,
    descKey: "benchmark.compression.compressed.desc",
    whatKey: "benchmark.compression.compressed.what",
    affectsKey: "benchmark.compression.compressed.affects",
    allowsKey: "benchmark.compression.compressed.allows",
  },
  {
    id: "aggressive", labelKey: "benchmark.compression.aggressive.label", kvK: "q4_0", kvV: "q4_0", nkvo: false, swaFull: false, factor: 0.25,
    descKey: "benchmark.compression.aggressive.desc",
    whatKey: "benchmark.compression.aggressive.what",
    affectsKey: "benchmark.compression.aggressive.affects",
    allowsKey: "benchmark.compression.aggressive.allows",
  },
  {
    id: "extreme", labelKey: "benchmark.compression.extreme.label", kvK: "q4_0", kvV: "q4_0", nkvo: true, swaFull: false, factor: 0.25,
    descKey: "benchmark.compression.extreme.desc",
    whatKey: "benchmark.compression.extreme.what",
    affectsKey: "benchmark.compression.extreme.affects",
    allowsKey: "benchmark.compression.extreme.allows",
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
  const t = useT();

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
  const [prompts, setPrompts] = useState(ALL_PROMPTS.filter((p) => !p.vision).map((p) => p.id));
  const [keepAlive, setKeepAlive] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [judgeMode, setJudgeMode] = useState("heuristic"); // heuristic | self | api
  const [judgeApi, setJudgeApi] = useState({ engine: "openai", model: "gpt-4o-mini", base_url: "", api_key: "" });
  // Speculative decoding (DFLASH) — solo vLLM/SGLang
  const [dflash, setDflash] = useState(false);
  const [dflashDraft, setDflashDraft] = useState("");
  const [dflashTokens, setDflashTokens] = useState(16);

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
  const isVisionModel = !!selectedModel?.tags?.includes("vision");
  // Cuantizaciones válidas para el motor elegido (GGUF en llama.cpp, awq/gptq/fp8 en los
  // Docker, vacío en ollama/API). Las publica el backend en la metadata del motor.
  const engineQuants = selectedEngine?.meta?.quants ?? [];
  // DFLASH (speculative decoding) solo aplica a vLLM/SGLang
  const supportsSpec = engine === "vllm" || engine === "sglang";
  const apiNeedsKey = engineIsApi && !apiKey;
  // Determinar si el motor está listo para arrancar
  const engineNativeReady = selectedEngine?.runtimes?.some(
    (r) => r.runtime === "native" && r.ready
  );
  const engineDockerReady = selectedEngine?.runtimes?.some(
    (r) => r.runtime === "docker" && r.ready
  );
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
      if (dflash && dflashDraft.trim()) {
        engineOpts.specMethod = "dflash";
        engineOpts.specDraftModel = dflashDraft.trim();
        engineOpts.specNumTokens = Number(dflashTokens) || 16;
      }
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
          ? t("benchmark.notes.local", { filename: localModel.filename, compression })
          : t("benchmark.notes.compression", { compression }),
      });
    } catch (e) {
      // El hook ya logueó el evento, sólo dejamos un fallback por si la API falla antes
      console.error("startBench failed:", e);
      toast.error(humanizeError(e, t("benchmark.toast.launchFailed")));
    }
  };

  const stop = async () => {
    try {
      await stopBench();
    } catch (e) {
      console.warn("stopBench:", e);
    }
  };

  // Cancela el polling del sweep si el usuario navega fuera (desmonta la vista): sin esto,
  // el while(true) seguiría vivo en segundo plano abriendo EventSources nuevos.
  const sweepCancelRef = useRef(false);
  useEffect(() => () => {
    sweepCancelRef.current = true;
  }, []);

  const startSweep = async () => {
    if (!sweepQuants.length) return;
    bClear();
    bLog("info", t("benchmark.sweep.starting", { quants: sweepQuants.join(", ") }));
    try {
      const base = {
        engine,
        model,
        prompts,
        auto: !engineIsApi,
        keep_alive: false,
        api_key: apiKey || null,
        notes: t("benchmark.notes.sweep", { quants: sweepQuants.join("+") }),
      };
      const { sweep_id } = await api.startSweep(base, sweepQuants);
      bLog("info", t("benchmark.sweep.started", { id: sweep_id }));
      sweepCancelRef.current = false; // re-armar para esta corrida
      pollSweep(sweep_id);
    } catch (e) {
      bLog("error", e.message);
      toast.error(humanizeError(e, t("benchmark.toast.sweepFailed")));
    }
  };

  const pollSweep = async (sweepId) => {
    let lastRunId = null;
    while (true) {
      if (sweepCancelRef.current) return; // vista desmontada: detener el polling
      try {
        const status = await api.sweepStatus(sweepId);
        if (status.current && status.current !== lastRunId) {
          lastRunId = status.current;
          bLog("info", `→ run ${lastRunId}`);
          subscribe(lastRunId); // re-suscribe a la nueva sub-corrida; setea running
        }
        if (status.completed || status.cancelled) {
          bLog("success", t("benchmark.sweep.finished", { count: status.runs.length }));
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

  // El prompt de visión solo aplica a modelos multimodales: deselecciónalo al cambiar
  // a un modelo sin visión para no enviarlo (el backend igual lo gatea, esto evita ruido).
  useEffect(() => {
    // Mantén los prompts de visión solo si el modelo es de visión o el motor es una API
    // multimodal; si no, deselecciónalos.
    if (!isVisionModel && !engineIsApi) {
      setPrompts((p) => p.filter((id) => !VISION_PROMPT_IDS.includes(id)));
    }
  }, [isVisionModel, engineIsApi]);

  // Al cambiar de motor, si el quant actual no es válido para él, salta al primero válido
  // y limpia del sweep los quants que ese motor no admite.
  useEffect(() => {
    if (!engineQuants.length) return;
    if (!engineQuants.includes(quant)) setQuant(engineQuants[0]);
    setSweepQuants((s) => s.filter((q) => engineQuants.includes(q)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine, engineQuants.join("|")]);

  return (
    <>
      <PageHeader
        title={t("benchmark.header.title")}
        subtitle={t("benchmark.header.subtitle")}
      />
      <div className="grid gap-6 p-8 lg:grid-cols-2">
        <Card title={t("benchmark.config.title")}>
          <div className="grid gap-4">
            <Field label={t("benchmark.fields.engine")}>
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
                      {e.meta.name} ({e.meta.type}){!runtimeReady ? ` · ${t("benchmark.options.notInstalled")}` : ""}
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
              <Field label={t("benchmark.fields.localGguf")}>
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
                      {t("benchmark.localGguf.change")}
                    </button>
                  </div>
                </div>
              </Field>
            ) : (
              <Field label={t("benchmark.fields.model")}>
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
                        {m.name}{!compatible ? ` · ${t("benchmark.options.incompatible")}` : ""}
                      </option>
                    );
                  })}
                </Select>
                {!engineIsApi && !modelHasGguf && engine === "llamacpp" && (
                  <p className="mt-1 text-xs text-amber-300">
                    {t("benchmark.model.noGguf")}
                  </p>
                )}
              </Field>
            )}
            {!engineIsApi && !localModel && engineQuants.length > 0 && (
              <>
                <Field
                  label={t("benchmark.fields.quant")}
                  hint={loadingQuants ? t("benchmark.quant.checking") : t("benchmark.quant.singleRun")}
                >
                  <Select value={quant} onChange={(e) => setQuant(e.target.value)} disabled={!!running}>
                    {engineQuants.map((q) => {
                      const st = feasibleQuants[q];
                      const disabled = isQuantDisabled(st);
                      return (
                        <option key={q} value={q} disabled={disabled}>
                          {q}{st ? ` · ${t(statusLabelKey(st))}` : ""}
                        </option>
                      );
                    })}
                  </Select>
                </Field>
                <Field label={t("benchmark.fields.sweep")} hint={t("benchmark.sweep.hint")}>
                  <div className="flex flex-wrap gap-2">
                    {engineQuants.map((q) => {
                      const st = feasibleQuants[q];
                      const infeasible = isQuantDisabled(st);
                      const selected = sweepQuants.includes(q);
                      return (
                        <button
                          key={q}
                          type="button"
                          onClick={() => !infeasible && toggleSweepQuant(q)}
                          disabled={!!running || infeasible}
                          title={st ? t(statusLabelKey(st)) : undefined}
                          aria-pressed={selected}
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
            {!engineIsApi && !supportsSpec && (
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
            {supportsSpec && (
              <Field
                label={t("benchmark.dflash.label")}
                hint={t("benchmark.dflash.hint")}
              >
                <label className="mb-2 flex items-center gap-2 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={dflash}
                    onChange={(e) => setDflash(e.target.checked)}
                    disabled={!!running}
                    className="accent-indigo-500"
                  />
                  {t("benchmark.dflash.enable")}
                </label>
                {dflash && (
                  <div className="space-y-2">
                    <Input
                      placeholder={t("benchmark.dflash.draftPlaceholder")}
                      value={dflashDraft}
                      onChange={(e) => setDflashDraft(e.target.value)}
                      disabled={!!running}
                    />
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                      <span>{t("benchmark.dflash.specTokens")}</span>
                      <Input
                        type="number"
                        min="1"
                        value={dflashTokens}
                        onChange={(e) => setDflashTokens(e.target.value)}
                        disabled={!!running}
                        className="w-20"
                      />
                    </div>
                    <p className="text-[11px] text-slate-500">
                      {t("benchmark.dflash.note")}
                    </p>
                  </div>
                )}
              </Field>
            )}
            {engineIsApi && (
              <Field label={t("benchmark.fields.apiKey")} hint={t("benchmark.apiKey.hint")}>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  disabled={!!running}
                  placeholder="••••••••"
                />
              </Field>
            )}
            <Field
              label={t("benchmark.fields.prompts")}
              hint={
                isVisionModel
                  ? t("benchmark.prompts.visionHint")
                  : engineIsApi
                  ? t("benchmark.prompts.apiHint")
                  : undefined
              }
            >
              <div className="flex flex-wrap gap-2">
                {ALL_PROMPTS.map((p) => {
                  const blocked = p.vision && !isVisionModel && !engineIsApi;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => togglePrompt(p.id)}
                      disabled={!!running || blocked}
                      title={blocked ? t("benchmark.prompts.blocked") : undefined}
                      aria-pressed={prompts.includes(p.id)}
                      className={`inline-flex items-center gap-1 rounded-md border px-3 py-1 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${
                        prompts.includes(p.id)
                          ? "border-indigo-500 bg-indigo-500/10 text-indigo-200"
                          : "border-slate-700 text-slate-400"
                      }`}
                    >
                      {p.vision && <ImageIcon size={11} />}
                      {t(p.labelKey)}
                    </button>
                  );
                })}
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
                {t("benchmark.keepAlive")}
              </label>
            )}
            <div className="flex flex-wrap gap-2 pt-2">
              {!running ? (
                <>
                  <Button onClick={start} disabled={!model || !prompts.length || !canRun}>
                    <Play size={14} /> {t("benchmark.actions.launch")}
                  </Button>
                  {sweepQuants.length > 0 && !engineIsApi && (
                    <Button onClick={startSweep} variant="success" disabled={!model || !canRun}>
                      <Play size={14} /> {t("benchmark.actions.sweep", { count: sweepQuants.length })}
                    </Button>
                  )}
                </>
              ) : (
                <Button variant="danger" onClick={stop}>
                  <Square size={14} /> {t("benchmark.actions.stop")}
                </Button>
              )}
              {running && (
                <span className="self-center text-xs text-slate-500">{t("benchmark.runLabel", { id: running })}</span>
              )}
            </div>
            {!engineIsApi && !running && (
              <EngineHint engine={engine} selectedEngine={selectedEngine} selectedModel={selectedModel} />
            )}
          </div>
        </Card>

        <RunningPanel events={events} progress={progress} running={!!running} />

        {results.length > 0 && (
          <Card title={t("benchmark.results.title")} className="lg:col-span-2">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                  <tr className="border-b border-slate-800">
                    <th className="py-2 pr-3">{t("benchmark.results.colPrompt")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colTtft")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colDecode")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colPrefill")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colVramPeak")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colRamPeak")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colQuality")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colTokens")}</th>
                    <th className="py-2 pr-3">{t("benchmark.results.colStatus")}</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={i} className="border-b border-slate-900">
                      <td className="py-2 pr-3 font-medium">{r.prompt_id}</td>
                      <td className="py-2 pr-3 tabular-nums">
                        {r.ttft_ms} ms
                        {r.ttft_std ? <span className="text-slate-500"> ±{r.ttft_std}</span> : null}
                        {r.n_samples > 1 ? (
                          <span className="ml-1 text-[10px] text-slate-600">n={r.n_samples}</span>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3 tabular-nums">
                        {r.tps}
                        {r.tps_std ? <span className="text-slate-500"> ±{r.tps_std}</span> : null}
                      </td>
                      <td className="py-2 pr-3 tabular-nums">{r.prefill_tps || "—"}</td>
                      <td className="py-2 pr-3 tabular-nums">{r.vram_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums">{r.ram_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums">{r.quality}</td>
                      <td className="py-2 pr-3 tabular-nums">{r.ctx_used}</td>
                      <td className="py-2 pr-3">
                        {r.error ? <Badge tone="rose">{t("benchmark.results.statusError")}</Badge> : <Badge tone="emerald">{t("benchmark.results.statusOk")}</Badge>}
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
  const t = useT();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // Variable renombrada (no "t") para no sombrear el t() de i18n del componente —
    // confundía la lectura y era frágil ante futuros cambios dentro del efecto.
    const debounceId = setTimeout(() => {
      api
        .getByCompression(engine, contextLen)
        .then((r) => !cancelled && setRows(r))
        .catch(() => !cancelled && setRows([]))
        .finally(() => !cancelled && setLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(debounceId);
    };
  }, [engine, contextLen]);

  return (
    <Card title={t("benchmark.power.title")} className="lg:col-span-2">
      <p className="mb-3 text-xs text-slate-400">
        {t("benchmark.power.intro.before")}{" "}
        <span className="font-mono text-slate-300">{contextLen.toLocaleString()}</span>{" "}
        {t("benchmark.power.intro.after")}
      </p>
      {loading && rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("benchmark.power.calculating")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-3">{t("benchmark.power.colCompression")}</th>
                <th className="py-2 pr-3">{t("benchmark.power.colKv")}</th>
                <th className="py-2 pr-3">{t("benchmark.power.colTopFullGpu")}</th>
                <th className="py-2 pr-3">{t("benchmark.power.colKvCache")}</th>
                <th className="py-2 pr-3">{t("benchmark.power.colLargestRunnable")}</th>
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
  const t = useT();
  const MODES = [
    { id: "heuristic", labelKey: "benchmark.judge.heuristic.label", hintKey: "benchmark.judge.heuristic.hint" },
    { id: "self", labelKey: "benchmark.judge.self.label", hintKey: "benchmark.judge.self.hint" },
    { id: "api", labelKey: "benchmark.judge.api.label", hintKey: "benchmark.judge.api.hint" },
  ];
  const cur = MODES.find((m) => m.id === mode) || MODES[0];
  return (
    <Field label={t("benchmark.judge.fieldLabel")} hint={t(cur.hintKey)}>
      <Select value={mode} onChange={(e) => onMode(e.target.value)} disabled={running}>
        {MODES.map((m) => (
          <option key={m.id} value={m.id}>
            {t(m.labelKey)}
          </option>
        ))}
      </Select>
      {mode === "api" && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Input
            placeholder={t("benchmark.judge.baseUrlPlaceholder")}
            value={api.base_url}
            onChange={(e) => onApi({ ...api, base_url: e.target.value })}
            disabled={running}
          />
          <Input
            placeholder={t("benchmark.judge.modelPlaceholder")}
            value={api.model}
            onChange={(e) => onApi({ ...api, model: e.target.value })}
            disabled={running}
          />
          <Input
            type="password"
            placeholder={t("benchmark.judge.apiKeyPlaceholder")}
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
  const t = useT();
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
        label={t("benchmark.compression.fieldLabel")}
        hint={preset ? t(preset.descKey) : undefined}
      >
        <div className="grid grid-cols-5 gap-1 rounded-md border border-slate-700 bg-slate-900/40 p-1">
          {COMPRESSION_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onChange(p.id)}
              disabled={running}
              title={`${t(p.labelKey)} — ${t(p.descKey)}`}
              aria-pressed={value === p.id}
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
              {t(p.labelKey)}
            </button>
          ))}
        </div>
      </Field>

      <details className="rounded-md border border-slate-800 bg-slate-900/30 px-3 py-2">
        <summary className="cursor-pointer text-[11px] font-medium uppercase tracking-wider text-slate-400 hover:text-slate-200">
          {t("benchmark.compression.detailsSummary")}
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
                <span className="font-semibold text-slate-200">{t(p.labelKey)}</span>
                <Badge tone="slate">K={p.kvK} · V={p.kvV}{p.nkvo ? " · RAM" : ""}</Badge>
              </div>
              <dl className="grid grid-cols-[88px_1fr] gap-x-2 gap-y-0.5 text-slate-400">
                <dt className="text-slate-500">{t("benchmark.compression.dtWhat")}</dt><dd className="text-slate-300">{t(p.whatKey)}</dd>
                <dt className="text-slate-500">{t("benchmark.compression.dtAffects")}</dt><dd>{t(p.affectsKey)}</dd>
                <dt className="text-slate-500">{t("benchmark.compression.dtAllows")}</dt><dd className="text-emerald-300/90">{t(p.allowsKey)}</dd>
              </dl>
            </div>
          ))}
        </div>
      </details>

      <div className="grid grid-cols-2 gap-3">
        <Field
          label={t("benchmark.context.label")}
          hint={t("benchmark.context.hint")}
        >
          <Input
            type="number"
            placeholder={t("benchmark.context.placeholder")}
            value={customCtx}
            onChange={(e) => onCustomCtx(e.target.value)}
            disabled={running}
          />
        </Field>
        <div className="flex flex-col justify-end rounded-md border border-slate-800 bg-slate-900/40 p-2 text-xs">
          <div className="text-slate-500">{t("benchmark.context.kvAt", { tokens: ctx.toLocaleString() })}</div>
          <div className="mt-0.5 font-mono text-sm text-slate-200">
            ≈ {kvAtCtxMb < 1024 ? `${kvAtCtxMb.toFixed(0)} MB` : `${(kvAtCtxMb / 1024).toFixed(2)} GB`}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            K={preset?.kvK} · V={preset?.kvV}{preset?.nkvo ? ` · ${t("benchmark.context.inRam")}` : ""}
          </div>
        </div>
      </div>
    </div>
  );
}

function EngineHint({ engine, selectedEngine, selectedModel }) {
  const t = useT();
  const nativeRt = selectedEngine?.runtimes?.find((r) => r.runtime === "native");
  const dockerRt = selectedEngine?.runtimes?.find((r) => r.runtime === "docker");

  if (engine === "llamacpp") {
    return (
      <p className="text-xs text-slate-500">
        {t("benchmark.engineHint.llamacpp.before")} <code>%APPDATA%\InferBench\</code>{t("benchmark.engineHint.llamacpp.after")}
      </p>
    );
  }
  if (engine === "ollama") {
    if (nativeRt && !nativeRt.ready) {
      return (
        <div className="rounded border border-amber-700/40 bg-amber-950/30 p-3 text-xs text-amber-100">
          <p className="font-semibold">{t("benchmark.engineHint.ollama.notInstalledTitle")}</p>
          <p className="mt-1 opacity-80">
            {t("benchmark.engineHint.ollama.notInstalledBody")}
          </p>
          {nativeRt.install_url && (
            <a
              href={nativeRt.install_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block rounded border border-amber-600/60 px-2 py-0.5 hover:bg-amber-900/40"
            >
              {t("benchmark.engineHint.ollama.downloadCta")}
            </a>
          )}
        </div>
      );
    }
    return (
      <p className="text-xs text-slate-500">
        {t("benchmark.engineHint.ollama.readyBefore")}{" "}
        <code className="text-slate-300">{selectedModel?.ollama_tag || t("benchmark.engineHint.ollama.theModel")}</code>{" "}
        {t("benchmark.engineHint.ollama.readyAfter")}
      </p>
    );
  }
  if (["vllm", "sglang", "tgi"].includes(engine)) {
    if (dockerRt && !dockerRt.ready) {
      return (
        <div className="rounded border border-amber-700/40 bg-amber-950/30 p-3 text-xs text-amber-100">
          <p className="font-semibold">{t("benchmark.engineHint.docker.requiredTitle", { engine })}</p>
          <p className="mt-1 opacity-80">
            {t("benchmark.engineHint.docker.requiredBody", { engine })}
          </p>
        </div>
      );
    }
    return (
      <p className="text-xs text-slate-500">
        {t("benchmark.engineHint.docker.firstRun")}
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
  const t = useT();
  if (loading && recs.length === 0) {
    return (
      <div className="rounded border border-slate-800 bg-slate-900/30 p-2 text-center text-xs text-slate-500">
        {t("benchmark.engineMatrix.checking")}
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
          {t("benchmark.engineMatrix.title")}
        </span>
        {loading && <span className="text-[10px] text-slate-600">{t("benchmark.engineMatrix.updating")}</span>}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-800/60 text-left text-[10px] uppercase tracking-wider text-slate-600">
            <th className="px-3 py-1.5">{t("benchmark.engineMatrix.colEngine")}</th>
            <th className="px-2 py-1.5">{t("benchmark.engineMatrix.colBestQuant")}</th>
            <th className="px-2 py-1.5">{t("benchmark.engineMatrix.colSource")}</th>
            <th className="px-2 py-1.5">{t("benchmark.engineMatrix.colRuntime")}</th>
            <th className="px-3 py-1.5">{t("benchmark.engineMatrix.colScore")}</th>
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
                onKeyDown={(e) => {
                  if (clickable && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    onSelect(r.engine_id);
                  }
                }}
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                aria-pressed={clickable ? isSelected : undefined}
                title={
                  !r.model_available
                    ? t("benchmark.engineMatrix.titleModelUnavailable")
                    : !r.runtime_ready
                    ? t("benchmark.engineMatrix.titleRuntimeMissing")
                    : !r.feasible
                    ? t("benchmark.engineMatrix.titleWontFit")
                    : t("benchmark.engineMatrix.titleClickSelect")
                }
                className={`border-b border-slate-800/40 transition-colors last:border-0 ${
                  isSelected
                    ? "bg-indigo-900/20"
                    : clickable
                    ? "cursor-pointer hover:bg-slate-800/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-400"
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
                    <span className="text-indigo-400">{t("benchmark.engineMatrix.cloud")}</span>
                  ) : r.runtime_ready ? (
                    <span className="text-emerald-400">{t("benchmark.engineMatrix.ready")}</span>
                  ) : (
                    <span className="text-amber-500">{t("benchmark.engineMatrix.notInstalled")}</span>
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
  const t = useT();
  const logRef = useRef(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events]);

  return (
    <Card title={t("benchmark.running.title")}>
      <BootstrapProgress progress={progress} />
      <TokensProgress progress={progress} />

      <div
        ref={logRef}
        className="mt-4 h-72 overflow-y-auto rounded border border-slate-800 bg-black/60 p-3 font-mono text-[11px] leading-relaxed"
      >
        {events.length === 0 && (
          <p className="text-slate-600">
            {running ? t("benchmark.running.waiting") : t("benchmark.running.idle")}
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
  const t = useT();
  if (progress.kind === "engine.install") {
    return (
      <PhasePanel label={t("benchmark.bootstrap.downloadingBinary")} progress={progress} color="indigo" />
    );
  }
  if (progress.kind === "model.download") {
    return (
      <PhasePanel label={t("benchmark.bootstrap.downloadingModel", { name: progress.name || "GGUF" })} progress={progress} color="purple" />
    );
  }
  if (progress.kind === "engine.ready") {
    return (
      <div className="rounded border border-emerald-700/40 bg-emerald-950/30 p-3 text-sm text-emerald-200">
        {t("benchmark.bootstrap.engineReady")}
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
  const t = useT();
  if (progress.kind !== "tokens") return null;
  const pct = progress.target ? Math.min(100, (progress.current / progress.target) * 100) : 0;
  return (
    <div>
      <div className="grid grid-cols-3 gap-4 pb-3">
        <Stat label={t("benchmark.tokens.ttft")} value={progress.ttft != null ? `${progress.ttft} ms` : "—"} tone="accent" />
        <Stat label={t("benchmark.tokens.tps")} value={progress.tps || "—"} tone="success" />
        <Stat
          label={t("benchmark.tokens.progress")}
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
    // Show only the binary basename (e.g. "llama-server.exe"), never the full
    // absolute path — it would leak the OS username (PII) in the live log.
    const bin = evt.binary ? String(evt.binary).split(/[\\/]/).pop() : "";
    return <div className="text-cyan-300">[engine] start {bin}</div>;
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
