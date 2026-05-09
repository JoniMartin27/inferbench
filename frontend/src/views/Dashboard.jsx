import { useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader, Card, Stat, Badge } from "../components/ui.jsx";

export default function Dashboard() {
  const [hw, setHw] = useState(null);
  const [engines, setEngines] = useState([]);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    Promise.all([api.hardware(), api.listEngines(), api.listHistory()])
      .then(([h, e, hist]) => {
        setHw(h);
        setEngines(e);
        setHistory(hist);
      })
      .catch(() => {});
  }, []);

  const running = engines.filter((e) => e.status?.state === "running").length;
  const localOk = engines.filter(
    (e) => e.meta.type === "local" && e.status?.state !== "docker-unavailable"
  ).length;

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Estado general de tu entorno de benchmarking local"
      />
      <div className="grid gap-6 p-8 md:grid-cols-4">
        <Card>
          <Stat
            label="GPU principal"
            value={hw?.gpus?.[0]?.name || "—"}
            hint={hw?.gpus?.[0] ? `${hw.gpus[0].vram_gb} GB VRAM` : "CPU-only"}
            tone="accent"
          />
        </Card>
        <Card>
          <Stat label="RAM" value={`${hw?.ram_gb || 0} GB`} hint={`${hw?.ram_available_gb || 0} GB libres`} />
        </Card>
        <Card>
          <Stat
            label="Motores activos"
            value={running}
            hint={`${localOk} locales operativos`}
            tone={running > 0 ? "success" : "default"}
          />
        </Card>
        <Card>
          <Stat
            label="Runs históricas"
            value={history.length}
            hint={
              history[0]
                ? `última hace ${relativeTime(history[0].ts)}`
                : "aún sin benchmarks"
            }
          />
        </Card>

        <Card title="Hardware" className="md:col-span-2">
          {!hw ? (
            <p className="text-slate-400">Cargando…</p>
          ) : (
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <Row k="OS" v={`${hw.os} ${hw.os_version}`} />
              <Row k="CPU" v={hw.cpu.name} />
              <Row
                k="Cores"
                v={`${hw.cpu.physical_cores} físicos / ${hw.cpu.logical_cores} lógicos`}
              />
              <Row k="Frecuencia" v={`${hw.cpu.freq_mhz?.toFixed(0) || "?"} MHz`} />
              <Row k="RAM total" v={`${hw.ram_gb} GB`} />
              <Row
                k="GPUs"
                v={
                  hw.gpus.length
                    ? hw.gpus
                        .map((g) => `${g.name} (${g.vendor}, ${g.vram_gb}GB)`)
                        .join(", ")
                    : "ninguna"
                }
              />
            </dl>
          )}
        </Card>

        <Card title="Motores" className="md:col-span-2">
          <ul className="grid grid-cols-2 gap-2">
            {engines.map(({ meta, status }) => (
              <li
                key={meta.id}
                className="flex items-center justify-between rounded border border-slate-800 px-3 py-2 text-sm"
              >
                <div>
                  <div className="font-medium">{meta.name}</div>
                  <div className="text-xs text-slate-500">{meta.type}</div>
                </div>
                <EngineBadge meta={meta} status={status} />
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
    <>
      <dt className="text-slate-500">{k}</dt>
      <dd className="truncate text-slate-200">{v ?? "—"}</dd>
    </>
  );
}

function EngineBadge({ meta, status }) {
  if (meta.type === "api") return <Badge tone="indigo">API</Badge>;
  const state = status?.state;
  if (state === "running") return <Badge tone="emerald">running</Badge>;
  if (state === "docker-unavailable") return <Badge tone="amber">docker off</Badge>;
  return <Badge tone="slate">{state || "missing"}</Badge>;
}

function relativeTime(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}min`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}
