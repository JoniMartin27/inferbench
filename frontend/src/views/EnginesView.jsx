import { useEffect, useState } from "react";
import { Play, Square, RefreshCw, Download } from "lucide-react";
import { api, installEngine } from "../api";
import { PageHeader, Card, Button, Badge, Field, Input, Spinner } from "../components/ui.jsx";

export default function EnginesView({ dockerDown }) {
  const [engines, setEngines] = useState([]);
  const [busy, setBusy] = useState({});
  const [error, setError] = useState(null);
  const [forms, setForms] = useState({});
  const [installing, setInstalling] = useState({}); // id → progress

  const refresh = () => api.listEngines().then(setEngines).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, []);

  const start = async (id) => {
    setBusy((b) => ({ ...b, [id]: true }));
    setError(null);
    try {
      const f = forms[id] || {};
      const body = {
        model_path: f.model_path || null,
        runtime: f.runtime || null,
        engine_opts: {
          contextLen: Number(f.contextLen) || 4096,
          kvCache: f.kvCache || "f16",
          flashAttn: !!f.flashAttn,
          mlock: !!f.mlock,
        },
        gpu: true,
      };
      await api.startEngine(id, body);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  };

  const stop = async (id) => {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      await api.stopEngine(id);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  };

  const install = async (id) => {
    setInstalling((s) => ({ ...s, [id]: { phase: "starting" } }));
    setError(null);
    try {
      await installEngine(id, (evt) => {
        setInstalling((s) => ({ ...s, [id]: evt }));
      });
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setTimeout(() => setInstalling((s) => ({ ...s, [id]: null })), 1500);
    }
  };

  const setForm = (id, patch) =>
    setForms((s) => ({ ...s, [id]: { ...s[id], ...patch } }));

  const anyNativeReady = engines.some((e) =>
    e.runtimes?.some((r) => r.runtime === "native" && r.ready)
  );
  const anyNativeAvailable = engines.some((e) =>
    e.runtimes?.some((r) => r.runtime === "native")
  );

  return (
    <>
      <PageHeader
        title="Motores"
        subtitle="Arranca o detén motores en modo nativo (sin Docker) o vía contenedor"
        actions={
          <Button variant="ghost" onClick={refresh}>
            <RefreshCw size={14} /> Refrescar
          </Button>
        }
      />
      <div className="space-y-4 p-8">
        {dockerDown && anyNativeAvailable && (
          <div className="rounded border border-emerald-700/40 bg-emerald-950/30 p-4 text-sm text-emerald-100">
            <p className="font-semibold">Modo nativo disponible.</p>
            <p className="mt-1 opacity-80">
              No tienes Docker, pero puedes arrancar <strong>llama.cpp</strong> directamente como
              proceso nativo. Pulsa <em>Instalar binario</em> en la tarjeta de llama.cpp y la app
              descargará la release oficial de GitHub (~50–200 MB según variante CUDA/CPU).
              {!anyNativeReady && " Aún no hay binarios descargados."}
            </p>
          </div>
        )}
        {dockerDown && !anyNativeAvailable && (
          <div className="rounded border border-amber-700/40 bg-amber-950/30 p-4 text-sm text-amber-100">
            <p className="font-semibold">Docker no está corriendo.</p>
            <p className="mt-1 opacity-80">
              Los motores que solo tienen runtime Docker (Ollama, vLLM, SGLang, TGI) requieren Docker.
              Las APIs cloud funcionan sin Docker desde la pestaña Benchmark.
            </p>
          </div>
        )}
        {error && (
          <div className="rounded border border-rose-700/40 bg-rose-950/40 p-3 text-sm text-rose-200">
            {error}
          </div>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          {engines.map((e) => (
            <EngineCard
              key={e.meta.id}
              engine={e}
              form={forms[e.meta.id] || {}}
              onForm={(patch) => setForm(e.meta.id, patch)}
              onStart={() => start(e.meta.id)}
              onStop={() => stop(e.meta.id)}
              onInstall={() => install(e.meta.id)}
              busy={!!busy[e.meta.id]}
              installProgress={installing[e.meta.id]}
            />
          ))}
        </div>
      </div>
    </>
  );
}

function EngineCard({ engine, form, onForm, onStart, onStop, onInstall, busy, installProgress }) {
  const { meta, status, runtimes = [] } = engine;
  const isApi = meta.type === "api";
  const state = isApi ? "api" : status?.state || "missing";
  const isRunning = state === "running";

  const native = runtimes.find((r) => r.runtime === "native");
  const docker = runtimes.find((r) => r.runtime === "docker");
  const wantedRuntime = form.runtime || meta.default_runtime;
  const nativeNeedsInstall = wantedRuntime === "native" && native && !native.ready;
  const dockerUnready = wantedRuntime === "docker" && docker && !docker.ready;

  return (
    <Card
      title={meta.name}
      actions={
        <div className="flex items-center gap-2">
          <StateBadge state={state} />
          {meta.optimizable && <Badge tone="indigo">optimizable</Badge>}
        </div>
      }
    >
      <p className="text-sm text-slate-400">{meta.description}</p>

      {!isApi && runtimes.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          {runtimes.map((r) => (
            <Badge key={r.runtime} tone={r.ready ? "emerald" : "slate"}>
              {r.runtime}: {r.detail}
            </Badge>
          ))}
        </div>
      )}

      {!isApi && (
        <div className="mt-4 grid grid-cols-2 gap-3">
          {meta.runtimes.length > 1 && (
            <Field label="Runtime">
              <select
                value={wantedRuntime}
                onChange={(e) => onForm({ runtime: e.target.value })}
                disabled={isRunning}
                className="w-full rounded-md border border-slate-700 bg-slate-900/40 px-3 py-1.5 text-sm text-slate-100"
              >
                {meta.runtimes.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Ruta del modelo">
            <Input
              placeholder="C:/modelos/qwen.Q4_K_M.gguf"
              value={form.model_path || ""}
              onChange={(e) => onForm({ model_path: e.target.value })}
              disabled={isRunning}
            />
          </Field>
          <Field label="Contexto">
            <Input
              type="number"
              placeholder="4096"
              value={form.contextLen || ""}
              onChange={(e) => onForm({ contextLen: e.target.value })}
              disabled={isRunning}
            />
          </Field>
          <Field label="KV cache">
            <Input
              placeholder="f16 / q8_0 / q4_0"
              value={form.kvCache || ""}
              onChange={(e) => onForm({ kvCache: e.target.value })}
              disabled={isRunning}
            />
          </Field>
          <div className="col-span-2 flex items-end gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={!!form.flashAttn}
                onChange={(e) => onForm({ flashAttn: e.target.checked })}
                disabled={isRunning}
              />
              flash-attn
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={!!form.mlock}
                onChange={(e) => onForm({ mlock: e.target.checked })}
                disabled={isRunning}
              />
              mlock
            </label>
          </div>
        </div>
      )}

      {installProgress && <InstallProgress evt={installProgress} />}

      <div className="mt-4 flex items-center justify-between border-t border-slate-800 pt-4">
        <div className="text-xs text-slate-500">
          {meta.default_port ? `Puerto :${meta.default_port}` : "Sin puerto local"}
        </div>
        {!isApi && (
          <div className="flex gap-2">
            {nativeNeedsInstall && (
              <Button variant="ghost" onClick={onInstall} disabled={!!installProgress}>
                {installProgress ? <Spinner /> : <Download size={14} />} Instalar binario
              </Button>
            )}
            {!isRunning ? (
              <Button
                onClick={onStart}
                disabled={busy || nativeNeedsInstall || dockerUnready}
                title={
                  nativeNeedsInstall
                    ? "Instala el binario nativo primero"
                    : dockerUnready
                    ? "Docker no disponible"
                    : ""
                }
              >
                {busy ? <Spinner /> : <Play size={14} />} Arrancar
              </Button>
            ) : (
              <Button variant="danger" onClick={onStop} disabled={busy}>
                {busy ? <Spinner /> : <Square size={14} />} Detener
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function InstallProgress({ evt }) {
  if (!evt) return null;
  const phase = evt.phase || "…";
  const pct = evt.pct;
  return (
    <div className="mt-4 rounded border border-indigo-700/40 bg-indigo-950/20 p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-indigo-200">
          {phase === "lookup" && "Buscando última release…"}
          {phase === "download" && `Descargando ${evt.name || ""}`}
          {phase === "extract" && "Extrayendo…"}
          {phase === "ready" && "Listo"}
          {phase === "done" && "Instalación completada"}
          {phase === "error" && `Error: ${evt.message}`}
          {phase === "starting" && "Iniciando…"}
        </span>
        {pct != null && <span className="text-xs text-slate-400">{pct}%</span>}
      </div>
      {pct != null && (
        <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
          <div className="h-full bg-indigo-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

function StateBadge({ state }) {
  const map = {
    running: ["emerald", "running"],
    missing: ["slate", "missing"],
    "docker-unavailable": ["amber", "docker off"],
    exited: ["rose", "exited"],
    api: ["indigo", "API"],
    created: ["slate", "created"],
  };
  const [tone, label] = map[state] || ["slate", state];
  return <Badge tone={tone}>{label}</Badge>;
}
