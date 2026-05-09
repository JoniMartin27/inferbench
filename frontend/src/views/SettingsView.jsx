import { useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader, Card, Stat, Badge } from "../components/ui.jsx";

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
      </div>
    </>
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
