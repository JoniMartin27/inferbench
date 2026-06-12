import { useEffect, useMemo, useState } from "react";
import { Trash2, GitCompare, X, Inbox, Download } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import { api, humanizeError } from "../api";
import { PageHeader, Card, Button, Badge, Stat, Empty } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { useT } from "../i18n/index.jsx";
import { exportRunsCsv, exportRunsJson, kvLabel } from "../lib/exportResults.js";

const PROMPT_ORDER = ["reasoning", "code", "summary", "chat"];

export default function HistoryView({ onNavigate }) {
  const t = useT();
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [checked, setChecked] = useState(new Set());
  const [comparison, setComparison] = useState(null);
  const toast = useToast();

  const refresh = () =>
    api
      .listHistory()
      .then(setRuns)
      .catch((e) => toast.error(humanizeError(e, t("history.toast.loadError"))))
      .finally(() => setLoading(false));
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
    const prev = runs;
    setRuns((rs) => rs.filter((r) => r.id !== id)); // optimista: quita ya de la lista
    if (selected === id) setSelected(null);
    setChecked((s) => {
      const next = new Set(s);
      next.delete(id);
      return next;
    });
    try {
      await api.deleteHistory(id);
      toast.success(t("history.toast.deleteSuccess"));
    } catch (e) {
      setRuns(prev); // revertir si el backend falla
      toast.error(humanizeError(e, t("history.toast.deleteError")));
    }
  };

  const toggleCheck = (id) => {
    setChecked((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const compare = async () => {
    if (checked.size < 2) return;
    try {
      const data = await api.compareHistory(Array.from(checked));
      setComparison(data);
    } catch (e) {
      toast.error(humanizeError(e, t("history.toast.compareError")));
    }
  };

  return (
    <>
      <PageHeader
        title={t("history.header.title")}
        subtitle={t("history.header.subtitle")}
        actions={
          <Button onClick={compare} disabled={checked.size < 2}>
            <GitCompare size={14} /> {t("history.header.compare", { count: checked.size })}
          </Button>
        }
      />
      <div className="grid gap-6 p-8 lg:grid-cols-[420px_1fr]">
        <Card title={t("history.list.cardTitle", { count: runs.length })}>
          {loading && runs.length === 0 && (
            <p className="py-2 text-sm text-slate-500">{t("history.list.loading")}</p>
          )}
          {!loading && runs.length === 0 && (
            <Empty
              icon={Inbox}
              title={t("history.list.empty.title")}
              body={t("history.list.empty.body")}
              action={
                onNavigate && (
                  <Button onClick={() => onNavigate("benchmark")}>
                    {t("history.list.empty.action")}
                  </Button>
                )
              }
            />
          )}
          <ul className="divide-y divide-slate-800">
            {runs.map((r) => {
              const opts = safeParse(r.opts_json);
              return (
                <li
                  key={r.id}
                  className={`flex items-start gap-2 py-2 ${
                    selected === r.id ? "text-indigo-200" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked.has(r.id)}
                    onChange={() => toggleCheck(r.id)}
                    className="mt-1.5 accent-indigo-500"
                  />
                  <button
                    onClick={() => setSelected(r.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{opts.model || r.engine}</span>
                      {opts.quant && <Badge tone="indigo">{opts.quant}</Badge>}
                    </div>
                    <div className="text-xs text-slate-500">
                      {r.engine} · {new Date(r.ts * 1000).toLocaleString()} ·{" "}
                      <span className="opacity-60">{r.id}</span>
                    </div>
                    {r.notes && (
                      <div className="mt-0.5 truncate text-xs text-slate-600">{r.notes}</div>
                    )}
                  </button>
                  <Badge
                    tone={
                      r.status === "done" ? "emerald" : r.status === "error" ? "rose" : "amber"
                    }
                  >
                    {r.status}
                  </Badge>
                  <button
                    onClick={() => remove(r.id)}
                    className="rounded text-slate-500 transition hover:text-rose-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                    title={t("history.list.deleteTitle")}
                    aria-label={t("history.list.deleteAriaLabel")}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <div className="space-y-4">
          {comparison && (
            <ComparisonPanel data={comparison} onClose={() => setComparison(null)} />
          )}
          {!detail && !comparison && (
            <Card>
              <p className="text-sm text-slate-500">{t("history.detail.placeholder")}</p>
            </Card>
          )}
          {detail && !comparison && <RunDetail detail={detail} />}
        </div>
      </div>
    </>
  );
}

function ComparisonPanel({ data, onClose }) {
  const t = useT();
  const allPrompts = useMemo(() => {
    const set = new Set();
    data.forEach((d) => d.results.forEach((r) => set.add(r.prompt_id)));
    return PROMPT_ORDER.filter((p) => set.has(p)).concat(
      Array.from(set).filter((p) => !PROMPT_ORDER.includes(p))
    );
  }, [data]);

  const chartData = (metric) =>
    allPrompts.map((p) => {
      const row = { prompt: p };
      data.forEach((d) => {
        const opts = safeParse(d.run.opts_json);
        const label = `${opts.model || d.run.engine} ${opts.quant || ""}`.trim();
        const r = d.results.find((x) => x.prompt_id === p);
        row[label] = r ? r[metric] : 0;
      });
      return row;
    });

  const labels = data.map((d) => {
    const o = safeParse(d.run.opts_json);
    return `${o.model || d.run.engine} ${o.quant || ""}`.trim();
  });

  const palette = ["#6366f1", "#10b981", "#a78bfa", "#f59e0b", "#f43f5e", "#06b6d4"];

  return (
    <>
      <Card
        title={t("history.comparison.title", { count: data.length })}
        actions={
          <div className="flex items-center gap-3">
            <ExportButtons data={data} prefix="inferbench-comparison" />
            <button
              onClick={onClose}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
            >
              <X size={12} /> {t("history.comparison.close")}
            </button>
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-3">{t("history.comparison.table.run")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.engine")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.model")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.quant")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.kv")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.ctx")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.avgTps")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.avgTtft")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.avgQuality")}</th>
                <th className="py-2 pr-3">{t("history.comparison.table.vramPeak")}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => {
                const o = safeParse(d.run.opts_json);
                const ok = d.results.filter((r) => !r.error);
                const avg = (k) =>
                  ok.length ? ok.reduce((s, r) => s + (r[k] || 0), 0) / ok.length : 0;
                const peak = (k) =>
                  ok.length ? Math.max(...ok.map((r) => r[k] || 0)) : 0;
                return (
                  <tr key={d.run.id} className="border-b border-slate-900">
                    <td className="py-2 pr-3 font-mono text-xs text-slate-400">{d.run.id}</td>
                    <td className="py-2 pr-3">{d.run.engine}</td>
                    <td className="py-2 pr-3">{o.model || "—"}</td>
                    <td className="py-2 pr-3">
                      <Badge tone="indigo">{o.quant || "—"}</Badge>
                    </td>
                    <td className="py-2 pr-3">{kvLabel(o) || "—"}</td>
                    <td className="py-2 pr-3 tabular-nums">{o.engine_opts?.contextLen || "—"}</td>
                    <td className="py-2 pr-3 tabular-nums text-emerald-300">
                      {avg("tps").toFixed(1)}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{Math.round(avg("ttft_ms"))} ms</td>
                    <td className="py-2 pr-3 tabular-nums">{avg("quality").toFixed(1)}</td>
                    <td className="py-2 pr-3 tabular-nums">{peak("vram_gb").toFixed(2)} GB</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <CompareChart title={t("history.comparison.charts.tps")} data={chartData("tps")} keys={labels} palette={palette} />
        <CompareChart title={t("history.comparison.charts.ttft")} data={chartData("ttft_ms")} keys={labels} palette={palette} />
        <CompareChart title={t("history.comparison.charts.quality")} data={chartData("quality")} keys={labels} palette={palette} />
        <CompareChart title={t("history.comparison.charts.vram")} data={chartData("vram_gb")} keys={labels} palette={palette} />
      </div>
    </>
  );
}

function CompareChart({ title, data, keys, palette }) {
  return (
    <Card title={title}>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="prompt" stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={12} />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: 6,
                fontSize: 12,
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {keys.map((k, i) => (
              <Bar key={k} dataKey={k} fill={palette[i % palette.length]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function RunDetail({ detail }) {
  const t = useT();
  const { run, results } = detail;
  const opts = safeParse(run.opts_json);
  const ok = results.filter((r) => !r.error);
  const avg = (k) => (ok.length ? ok.reduce((s, r) => s + (r[k] || 0), 0) / ok.length : 0);

  return (
    <>
      <Card
        title={t("history.detail.cardTitle", { id: run.id })}
        actions={<ExportButtons data={detail} prefix={`inferbench-${run.id}`} />}
      >
        <div className="grid grid-cols-4 gap-4">
          <Stat label={t("history.detail.stats.engine")} value={run.engine} tone="accent" />
          <Stat label={t("history.detail.stats.model")} value={opts.model || "—"} />
          <Stat label={t("history.detail.stats.quant")} value={opts.quant || "—"} tone="accent" />
          <Stat label={t("history.detail.stats.results")} value={`${ok.length}/${results.length}`} />
          <Stat label={t("history.detail.stats.avgTtft")} value={`${Math.round(avg("ttft_ms"))} ms`} tone="success" />
          <Stat label={t("history.detail.stats.avgTps")} value={avg("tps").toFixed(1)} tone="success" />
          <Stat label={t("history.detail.stats.avgQuality")} value={avg("quality").toFixed(1)} />
          <Stat
            label={t("history.detail.stats.vramPeak")}
            value={`${Math.max(...(ok.map((r) => r.vram_gb || 0).concat([0]))).toFixed(2)} GB`}
          />
        </div>
        {opts.engine_opts && Object.keys(opts.engine_opts).length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1 border-t border-slate-800 pt-3">
            {Object.entries(opts.engine_opts).map(([k, v]) => (
              <Badge key={k} tone="slate">
                {k}={String(v)}
              </Badge>
            ))}
          </div>
        )}
      </Card>

      {ok.length > 0 && (
        <Card title={t("history.detail.tpsChartTitle")}>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={ok}>
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

      <Card title={t("history.detail.resultsTitle")}>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-3">{t("history.detail.table.model")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.prompt")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.ttft")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.decodeTps")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.prefillTps")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.vram")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.quality")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.tokens")}</th>
                <th className="py-2 pr-3">{t("history.detail.table.error")}</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id} className="border-b border-slate-900">
                  <td className="py-2 pr-3">{r.model_id}</td>
                  <td className="py-2 pr-3">{r.prompt_id}</td>
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

// Botones de exportación (CSV / JSON) reutilizables: sirven tanto para un run individual
// ({ run, results }) como para una comparación (array de runs). La descarga se dispara en el
// navegador/Electron sin pasar por el backend.
function ExportButtons({ data, prefix }) {
  const t = useT();
  const toast = useToast();

  const doExport = (fmt) => {
    try {
      const ok =
        fmt === "csv" ? exportRunsCsv(data, prefix) : exportRunsJson(data, prefix);
      if (ok) toast.success(t("history.export.success", { fmt: fmt.toUpperCase() }));
      else toast.error(t("history.export.error"));
    } catch {
      toast.error(t("history.export.error"));
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="soft"
        size="sm"
        onClick={() => doExport("csv")}
        title={t("history.export.csvTitle")}
      >
        <Download size={12} /> {t("history.export.csv")}
      </Button>
      <Button
        variant="soft"
        size="sm"
        onClick={() => doExport("json")}
        title={t("history.export.jsonTitle")}
      >
        <Download size={12} /> {t("history.export.json")}
      </Button>
    </div>
  );
}

function safeParse(s) {
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}
