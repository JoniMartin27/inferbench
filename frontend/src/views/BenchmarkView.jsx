import { useEffect, useRef, useState } from "react";
import { Play, Square } from "lucide-react";
import { api, subscribeBenchmark } from "../api";
import { PageHeader, Card, Field, Select, Input, Button, Badge, Stat } from "../components/ui.jsx";

const ALL_PROMPTS = [
  { id: "reasoning", label: "Razonamiento" },
  { id: "code", label: "Código" },
  { id: "summary", label: "Resumen" },
  { id: "chat", label: "Chat" },
];

const QUANTS = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"];

export default function BenchmarkView({ dockerDown, navPayload }) {
  const [engines, setEngines] = useState([]);
  const [models, setModels] = useState([]);
  const [engine, setEngine] = useState("llamacpp");
  const [model, setModel] = useState("");
  const [quant, setQuant] = useState("Q4_K_M");
  const [sweepQuants, setSweepQuants] = useState([]);
  const [localModel, setLocalModel] = useState(null);

  // Si llegamos con un GGUF local seleccionado, lo aplicamos
  useEffect(() => {
    if (navPayload?.localModel) {
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
  const [prompts, setPrompts] = useState(ALL_PROMPTS.map((p) => p.id));
  const [keepAlive, setKeepAlive] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [running, setRunning] = useState(null);
  const [events, setEvents] = useState([]);
  const [results, setResults] = useState([]);
  const [progress, setProgress] = useState({});
  const unsubRef = useRef(null);

  useEffect(() => {
    api.listEngines().then(setEngines).catch(() => {});
    api.listModels().then((m) => {
      setModels(m);
      if (!model && m[0]) setModel(m[0].id);
    });
    return () => unsubRef.current?.();
  }, []);

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
    setEvents([]);
    setResults([]);
    setProgress({});
    try {
      const { run_id } = await api.startBenchmark({
        engine,
        model: localModel ? (localModel.architecture || "local") + "-local" : model,
        quant,
        prompts,
        auto: !engineIsApi,
        keep_alive: keepAlive,
        api_key: apiKey || null,
        local_path: localModel ? localModel.path : null,
        notes: localModel ? `local: ${localModel.filename}` : "",
      });
      setRunning(run_id);
      unsubRef.current = subscribeBenchmark(run_id, (evt) => {
        setEvents((arr) => [...arr.slice(-300), evt]);

        // Progreso del bootstrap
        if (evt.type === "engine.install") {
          setProgress({ kind: "engine.install", ...evt });
        }
        if (evt.type === "model.download") {
          setProgress({ kind: "model.download", ...evt });
        }
        if (evt.type === "engine.ready") {
          setProgress({ kind: "engine.ready" });
        }

        // Progreso por prompt
        if (evt.type === "tokens") {
          setProgress({
            kind: "tokens",
            current: evt.current,
            target: evt.target,
            tps: evt.tps_current,
          });
        }
        if (evt.phase === "ttft") {
          setProgress((p) => ({ ...p, kind: "tokens", ttft: evt.ttft_ms }));
        }
        if (evt.type === "result") setResults((r) => [...r, evt.result]);
        if (evt.type === "done") {
          setRunning(null);
          unsubRef.current?.();
          unsubRef.current = null;
        }
      });
    } catch (e) {
      setEvents((arr) => [...arr, { type: "log", level: "error", text: e.message }]);
    }
  };

  const stop = async () => {
    if (!running) return;
    try {
      await api.stopBenchmark(running);
    } catch (e) {
      setEvents((arr) => [...arr, { type: "log", level: "warn", text: `Stop: ${e.message}` }]);
    }
  };

  const startSweep = async () => {
    if (!sweepQuants.length) return;
    setEvents([{ type: "log", level: "info", text: `Sweep: ${sweepQuants.join(", ")}` }]);
    setResults([]);
    setProgress({});
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
      setEvents((arr) => [...arr, { type: "log", level: "info", text: `Sweep arrancado: ${sweep_id}` }]);
      pollSweep(sweep_id);
    } catch (e) {
      setEvents((arr) => [...arr, { type: "log", level: "error", text: e.message }]);
    }
  };

  const pollSweep = async (sweepId) => {
    let lastRunId = null;
    while (true) {
      try {
        const status = await api.sweepStatus(sweepId);
        if (status.current && status.current !== lastRunId) {
          lastRunId = status.current;
          setEvents((arr) => [
            ...arr,
            { type: "log", level: "info", text: `→ run ${lastRunId}` },
          ]);
          setRunning(lastRunId);
          unsubRef.current?.();
          unsubRef.current = subscribeBenchmark(lastRunId, (evt) => {
            setEvents((arr) => [...arr.slice(-400), evt]);
            if (evt.type === "result") setResults((r) => [...r, evt.result]);
            if (evt.type === "tokens")
              setProgress({ kind: "tokens", current: evt.current, target: evt.target, tps: evt.tps_current });
          });
        }
        if (status.completed || status.cancelled) {
          setRunning(null);
          unsubRef.current?.();
          unsubRef.current = null;
          setEvents((arr) => [
            ...arr,
            { type: "log", level: "success", text: `Sweep terminado (${status.runs.length} runs)` },
          ]);
          return;
        }
      } catch (e) {
        setEvents((arr) => [...arr, { type: "log", level: "warn", text: `poll: ${e.message}` }]);
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
                {engines.map((e) => (
                  <option key={e.meta.id} value={e.meta.id}>
                    {e.meta.name} ({e.meta.type})
                  </option>
                ))}
              </Select>
            </Field>
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
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {!m.hf_gguf ? " · sin auto-descarga" : ""}
                    </option>
                  ))}
                </Select>
                {!engineIsApi && !modelHasGguf && (
                  <p className="mt-1 text-xs text-amber-300">
                    Este modelo no tiene fuente GGUF auto-descargable. Elige otro o usa Modelos → Locales.
                  </p>
                )}
              </Field>
            )}
            {!engineIsApi && !localModel && (
              <>
                <Field label="Cuantización" hint="Para una sola corrida">
                  <Select value={quant} onChange={(e) => setQuant(e.target.value)} disabled={!!running}>
                    {QUANTS.map((q) => (
                      <option key={q}>{q}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Sweep" hint="Marca varias para comparar (corre secuencial)">
                  <div className="flex flex-wrap gap-2">
                    {QUANTS.map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => toggleSweepQuant(q)}
                        disabled={!!running}
                        className={`rounded-md border px-2 py-1 text-xs ${
                          sweepQuants.includes(q)
                            ? "border-purple-500 bg-purple-500/10 text-purple-200"
                            : "border-slate-700 text-slate-400"
                        }`}
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </Field>
              </>
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
      </div>
    </>
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
