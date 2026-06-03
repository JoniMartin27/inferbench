import { useEffect, useState } from "react";
import { api, humanizeError } from "../api";
import { PageHeader, Card, Stat, Badge, Button, Input } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";

export default function SettingsView() {
  const [hw, setHw] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.hardware().then(setHw).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeader title="Ajustes" subtitle="Hardware detectado y endpoint del backend" />
      <div className="grid gap-6 p-8 md:grid-cols-2">
        <Card title="Backend">
          <dl className="text-sm">
            <Row k="API base" v="http://localhost:7777" />
            <Row k="DB" v="backend/data/inferbench.sqlite" />
            <Row k="Frontend dev" v="http://localhost:5173" />
          </dl>
        </Card>

        <Card title="Hardware">
          {error && <p className="text-rose-300">{error}</p>}
          {hw && (
            <div className="grid grid-cols-2 gap-4">
              <Stat label="CPU" value={hw.cpu.name} />
              <Stat label="RAM" value={`${hw.ram_gb} GB`} hint={`${hw.ram_available_gb} GB libres`} />
              <Stat
                label="GPU"
                value={hw.gpus[0]?.name || "—"}
                hint={hw.gpus[0] ? `${hw.gpus[0].vram_gb} GB VRAM` : "CPU-only"}
                tone="accent"
              />
              <Stat
                label="OS"
                value={hw.os}
                hint={hw.os_version}
              />
            </div>
          )}
        </Card>

        <Card title="GPUs detectadas" className="md:col-span-2">
          {!hw?.gpus?.length && <p className="text-slate-500">Ninguna GPU detectada. Modo CPU-only.</p>}
          <ul className="space-y-2">
            {hw?.gpus?.map((g, i) => (
              <li
                key={i}
                className="flex items-center justify-between rounded border border-slate-800 px-3 py-2"
              >
                <div>
                  <div className="font-medium">{g.name}</div>
                  <div className="text-xs text-slate-500">
                    {g.vendor} · driver {g.driver || "?"}
                  </div>
                </div>
                <Badge tone="indigo">{g.vram_gb} GB</Badge>
              </li>
            ))}
          </ul>
        </Card>

        <ApiKeysCard />
      </div>
    </>
  );
}

const PROVIDERS = [
  { id: "openai", label: "OpenAI", ph: "sk-…" },
  { id: "anthropic", label: "Anthropic", ph: "sk-ant-…" },
  { id: "openrouter", label: "OpenRouter", ph: "sk-or-…" },
  { id: "nvidia", label: "NVIDIA NIM", ph: "nvapi-…" },
];

function ApiKeysCard() {
  const toast = useToast();
  const [saved, setSaved] = useState({});
  const [inputs, setInputs] = useState({});

  const refresh = () => api.listKeys().then(setSaved).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const save = async (id) => {
    const key = (inputs[id] || "").trim();
    if (!key) return;
    try {
      await api.saveKey(id, key);
      setInputs((s) => ({ ...s, [id]: "" }));
      await refresh();
      toast.success(`Key de ${id} guardada`);
    } catch (e) {
      toast.error(humanizeError(e, "No se pudo guardar la key"));
    }
  };

  const clear = async (id) => {
    try {
      await api.deleteKey(id);
      await refresh();
      toast.success(`Key de ${id} borrada`);
    } catch (e) {
      toast.error(humanizeError(e, "No se pudo borrar la key"));
    }
  };

  return (
    <Card title="API keys (cloud)" className="md:col-span-2">
      <p className="mb-3 text-xs text-slate-500">
        Se guardan en el gestor de credenciales del sistema (no en disco ni en la base de
        datos). Una vez guardada, el benchmark la usa automáticamente para ese proveedor.
      </p>
      <div className="space-y-2">
        {PROVIDERS.map((p) => (
          <div key={p.id} className="flex items-center gap-2">
            <div className="w-28 shrink-0 text-sm text-slate-300">{p.label}</div>
            <Input
              type="password"
              autoComplete="off"
              placeholder={saved[p.id] ? "•••••••••• (guardada)" : p.ph}
              value={inputs[p.id] || ""}
              onChange={(e) => setInputs((s) => ({ ...s, [p.id]: e.target.value }))}
            />
            <Button size="sm" onClick={() => save(p.id)} disabled={!(inputs[p.id] || "").trim()}>
              Guardar
            </Button>
            {saved[p.id] ? (
              <>
                <Badge tone="emerald">guardada</Badge>
                <Button size="sm" variant="ghost" onClick={() => clear(p.id)}>
                  Borrar
                </Button>
              </>
            ) : (
              <Badge tone="slate">sin key</Badge>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Row({ k, v }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-2 py-1">
      <dt className="text-slate-500">{k}</dt>
      <dd className="truncate font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}
