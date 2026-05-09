import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { api } from "../api";
import { PageHeader, Card, Button, Badge, Stat } from "../components/ui.jsx";

export default function HistoryView() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);

  const refresh = () => api.listHistory().then(setRuns).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    api.getHistory(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  const remove = async (id) => {
    await api.deleteHistory(id);
    if (selected === id) setSelected(null);
    refresh();
  };

  return (
    <>
      <PageHeader title="Historial" subtitle="Runs de benchmark guardados en SQLite" />
      <div className="grid gap-6 p-8 lg:grid-cols-[360px_1fr]">
        <Card title={`Runs (${runs.length})`}>
          {runs.length === 0 && (
            <p className="text-sm text-slate-500">Aún no has lanzado ninguna suite.</p>
          )}
          <ul className="divide-y divide-slate-800">
            {runs.map((r) => (
              <li
                key={r.id}
                className={`flex items-start justify-between gap-2 py-2 ${
                  selected === r.id ? "text-indigo-200" : ""
                }`}
              >
                <button
                  onClick={() => setSelected(r.id)}
                  className="flex-1 text-left"
                >
                  <div className="font-medium">{r.engine}</div>
                  <div className="text-xs text-slate-500">
                    {new Date(r.ts * 1000).toLocaleString()} · {r.id}
                  </div>
                </button>
                <Badge tone={r.status === "done" ? "emerald" : r.status === "error" ? "rose" : "amber"}>
                  {r.status}
                </Badge>
                <button
                  onClick={() => remove(r.id)}
                  className="text-slate-500 hover:text-rose-300"
                  title="Eliminar"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-4">
          {!detail && (
            <Card>
              <p className="text-sm text-slate-500">Selecciona un run para ver el detalle.</p>
            </Card>
          )}
          {detail && <RunDetail detail={detail} />}
        </div>
      </div>
    </>
  );
}

function RunDetail({ detail }) {
  const { run, results } = detail;
  const okResults = results.filter((r) => !r.error);
  const avg = (k) =>
    okResults.length ? okResults.reduce((s, r) => s + (r[k] || 0), 0) / okResults.length : 0;

  return (
    <>
      <Card title={`Run ${run.id}`}>
        <div className="grid grid-cols-4 gap-4">
          <Stat label="Motor" value={run.engine} tone="accent" />
          <Stat label="Resultados" value={`${okResults.length}/${results.length}`} />
          <Stat label="TTFT medio" value={`${Math.round(avg("ttft_ms"))} ms`} tone="success" />
          <Stat label="tok/s medio" value={avg("tps").toFixed(1)} tone="success" />
        </div>
      </Card>

      {okResults.length > 0 && (
        <Card title="tok/s por prompt">
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={okResults}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="prompt_id" stroke="#64748b" />
                <YAxis stroke="#64748b" />
                <Tooltip
                  contentStyle={{
                    background: "#0f172a",
                    border: "1px solid #1e293b",
                    borderRadius: 6,
                  }}
                />
                <Bar dataKey="tps" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      <Card title="Resultados detallados">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-3">Modelo</th>
                <th className="py-2 pr-3">Prompt</th>
                <th className="py-2 pr-3">TTFT</th>
                <th className="py-2 pr-3">tok/s</th>
                <th className="py-2 pr-3">Quality</th>
                <th className="py-2 pr-3">Tokens</th>
                <th className="py-2 pr-3">Error</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id} className="border-b border-slate-900">
                  <td className="py-2 pr-3">{r.model_id}</td>
                  <td className="py-2 pr-3">{r.prompt_id}</td>
                  <td className="py-2 pr-3 tabular-nums">{r.ttft_ms} ms</td>
                  <td className="py-2 pr-3 tabular-nums">{r.tps}</td>
                  <td className="py-2 pr-3 tabular-nums">{r.quality}</td>
                  <td className="py-2 pr-3 tabular-nums">{r.ctx_used}</td>
                  <td className="py-2 pr-3 text-xs text-rose-300">{r.error || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
