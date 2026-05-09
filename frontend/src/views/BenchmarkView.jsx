import { useEffect, useRef, useState } from "react";
import { Play } from "lucide-react";
import { api, subscribeBenchmark } from "../api";
import { PageHeader, Card, Field, Select, Input, Button, Badge, Stat } from "../components/ui.jsx";

const ALL_PROMPTS = [
  { id: "reasoning", label: "Razonamiento" },
  { id: "code", label: "Código" },
  { id: "summary", label: "Resumen" },
  { id: "chat", label: "Chat" },
];

export default function BenchmarkView() {
  const [engines, setEngines] = useState([]);
  const [models, setModels] = useState([]);
  const [engine, setEngine] = useState("llamacpp");
  const [model, setModel] = useState("");
  const [prompts, setPrompts] = useState(ALL_PROMPTS.map((p) => p.id));
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [running, setRunning] = useState(null); // run_id
  const [events, setEvents] = useState([]);
  const [results, setResults] = useState([]);
  const [progress, setProgress] = useState({ current: 0, target: 0, tps: 0, ttft: null });
  const unsubRef = useRef(null);

  useEffect(() => {
    api.listEngines().then(setEngines).catch(() => {});
    api.listModels().then((m) => {
      setModels(m);
      if (m[0]) setModel(m[0].id);
    });
    return () => unsubRef.current?.();
  }, []);

  const start = async () => {
    setEvents([]);
    setResults([]);
    setProgress({ current: 0, target: 0, tps: 0, ttft: null });
    try {
      const { run_id } = await api.startBenchmark({
        engine,
        model,
        prompts,
        base_url: baseUrl || null,
        api_key: apiKey || null,
      });
      setRunning(run_id);
      unsubRef.current = subscribeBenchmark(run_id, (evt) => {
        setEvents((arr) => [...arr.slice(-200), evt]);
        if (evt.type === "tokens") {
          setProgress((p) => ({
            ...p,
            current: evt.current,
            target: evt.target,
            tps: evt.tps_current,
          }));
        }
        if (evt.phase === "ttft") {
          setProgress((p) => ({ ...p, ttft: evt.ttft_ms }));
        }
        if (evt.type === "result") {
          setResults((r) => [...r, evt.result]);
          setProgress({ current: 0, target: 0, tps: 0, ttft: null });
        }
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

  const togglePrompt = (id) =>
    setPrompts((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <>
      <PageHeader
        title="Benchmark"
        subtitle="Ejecuta la suite contra el motor activo y observa el progreso live"
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
            <Field label="Modelo">
              <Select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={!!running}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Base URL (opcional)" hint="auto: usa puerto por defecto del motor local">
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:8080"
                disabled={!!running}
              />
            </Field>
            <Field label="API key (solo motores cloud)">
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={!!running}
              />
            </Field>
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
            <div className="pt-2">
              <Button onClick={start} disabled={!!running || !model || !prompts.length}>
                <Play size={14} /> {running ? `Ejecutando ${running}…` : "Lanzar suite"}
              </Button>
            </div>
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
                        {r.error ? (
                          <Badge tone="rose">error</Badge>
                        ) : (
                          <Badge tone="emerald">ok</Badge>
                        )}
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

function RunningPanel({ events, progress, running }) {
  const logRef = useRef(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events]);

  const pct = progress.target > 0 ? Math.min(100, (progress.current / progress.target) * 100) : 0;

  return (
    <Card title="Ejecución live">
      <div className="grid grid-cols-3 gap-4 pb-4">
        <Stat label="TTFT" value={progress.ttft != null ? `${progress.ttft} ms` : "—"} tone="accent" />
        <Stat label="tok/s actual" value={progress.tps || "—"} tone="success" />
        <Stat
          label="Progreso"
          value={progress.target ? `${progress.current}/${progress.target}` : "—"}
        />
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-slate-800">
        <div
          className="h-full bg-indigo-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>

      <div
        ref={logRef}
        className="mt-4 h-72 overflow-y-auto rounded border border-slate-800 bg-black/60 p-3 font-mono text-[11px] leading-relaxed"
      >
        {events.length === 0 && (
          <p className="text-slate-600">
            {running ? "Esperando eventos…" : "Lanza una suite para ver el log."}
          </p>
        )}
        {events.map((e, i) => (
          <LogLine key={i} evt={e} />
        ))}
      </div>
    </Card>
  );
}

function LogLine({ evt }) {
  if (evt.type === "log") {
    const color =
      evt.level === "error"
        ? "text-rose-400"
        : evt.level === "warn"
        ? "text-amber-300"
        : "text-slate-400";
    return <div className={color}>[log] {evt.text}</div>;
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
