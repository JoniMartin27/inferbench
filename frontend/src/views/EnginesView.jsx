import { useEffect, useState } from "react";
import { Play, Square, RefreshCw } from "lucide-react";
import { api } from "../api";
import { PageHeader, Card, Button, Badge, Field, Input, Spinner } from "../components/ui.jsx";

export default function EnginesView() {
  const [engines, setEngines] = useState([]);
  const [busy, setBusy] = useState({});
  const [error, setError] = useState(null);
  const [forms, setForms] = useState({}); // engineId → {model_path, contextLen, kvCache, ...}

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

  const setForm = (id, patch) =>
    setForms((s) => ({ ...s, [id]: { ...s[id], ...patch } }));

  return (
    <>
      <PageHeader
        title="Motores"
        subtitle="Arranca o detén los contenedores de inferencia"
        actions={
          <Button variant="ghost" onClick={refresh}>
            <RefreshCw size={14} /> Refrescar
          </Button>
        }
      />
      <div className="space-y-4 p-8">
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
              busy={!!busy[e.meta.id]}
            />
          ))}
        </div>
      </div>
    </>
  );
}

function EngineCard({ engine, form, onForm, onStart, onStop, busy }) {
  const { meta, status } = engine;
  const isApi = meta.type === "api";
  const state = isApi ? "api" : status?.state || "missing";
  const isRunning = state === "running";

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

      {!isApi && (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Field label="Ruta del modelo (host)">
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
          <div className="flex items-end gap-3">
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

      <div className="mt-4 flex items-center justify-between border-t border-slate-800 pt-4">
        <div className="text-xs text-slate-500">
          {meta.default_port ? `Puerto :${meta.default_port}` : "Sin puerto local"}
          {meta.image && (
            <span className="ml-2 truncate text-slate-600">{meta.image}</span>
          )}
        </div>
        {!isApi && (
          <div className="flex gap-2">
            {!isRunning ? (
              <Button onClick={onStart} disabled={busy}>
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
