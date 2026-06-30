import { useEffect, useState } from "react";
import {
  Cpu,
  HardDrive,
  Zap,
  Activity,
  TrendingUp,
  PlayCircle,
  ArrowRight,
  Sparkles,
  Server,
} from "lucide-react";
import { api, humanizeError } from "../api";
import { useT } from "../i18n/index.jsx";
import { useToast } from "../components/toast.jsx";
import {
  PageHeader,
  Card,
  Stat,
  Badge,
  Button,
  Empty,
  Skeleton,
  compatTone,
  compatLabel,
  compatIcon,
} from "../components/ui.jsx";

export default function Dashboard({ onNavigate }) {
  const t = useT();
  const toast = useToast();
  const [hw, setHw] = useState(null);
  const [engines, setEngines] = useState([]);
  const [history, setHistory] = useState([]);
  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.hardware().catch(() => null),
      api.listEngines().catch(() => []),
      api.listHistory().catch(() => []),
      api.getRecommendations(15).catch(() => []),
    ])
      .then(([h, e, hist, recRows]) => {
        if (cancelled) return;
        setHw(h);
        setEngines(e);
        setHistory(hist);
        setRecs(recRows);
      })
      .catch((err) => {
        if (cancelled) return;
        toast.error(humanizeError(err, t("dashboard.toast.loadError")));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runningCount = engines.filter((e) => e.status?.state === "running").length;
  const operational = engines.filter(
    (e) => e.runtimes?.some((r) => r.ready) || e.meta.type === "api"
  ).length;

  const fullGpu = recs.filter((r) => r.config.status === "ok");
  const moe = recs.filter((r) => r.config.status === "moe");
  const partial = recs.filter((r) => r.config.status === "partial").slice(0, 4);

  return (
    <>
      <PageHeader
        eyebrow={t("dashboard.header.eyebrow")}
        title={t("dashboard.header.title")}
        subtitle={t("dashboard.header.subtitle")}
        actions={
          <Button onClick={() => onNavigate?.("benchmark")}>
            <PlayCircle size={14} /> {t("dashboard.header.launchBenchmark")}
          </Button>
        }
      />
      <div className="grid gap-6 p-8">
        {/* Stats */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card variant="flat">
            {loading ? (
              <Skeleton className="h-14 w-full" />
            ) : (
              <Stat
                icon={Cpu}
                label={t("dashboard.stats.gpu.label")}
                value={hw?.gpus?.[0]?.name?.replace("NVIDIA GeForce ", "") || "—"}
                hint={hw?.gpus?.[0] ? t("dashboard.stats.gpu.hint", { vram: hw.gpus[0].vram_gb }) : t("dashboard.stats.gpu.cpuOnly")}
                tone="accent"
              />
            )}
          </Card>
          <Card variant="flat">
            {loading ? (
              <Skeleton className="h-14 w-full" />
            ) : (
              <Stat
                icon={HardDrive}
                label={t("dashboard.stats.ram.label")}
                value={`${hw?.ram_gb || 0} GB`}
                hint={t("dashboard.stats.ram.hint", { free: hw?.ram_available_gb || 0 })}
              />
            )}
          </Card>
          <Card variant="flat">
            {loading ? (
              <Skeleton className="h-14 w-full" />
            ) : (
              <Stat
                icon={Server}
                label={t("dashboard.stats.engines.label")}
                value={`${operational}/${engines.length}`}
                hint={runningCount > 0 ? t("dashboard.stats.engines.running", { count: runningCount }) : t("dashboard.stats.engines.noneActive")}
                tone={runningCount > 0 ? "success" : "default"}
              />
            )}
          </Card>
          <Card variant="flat">
            {loading ? (
              <Skeleton className="h-14 w-full" />
            ) : (
              <Stat
                icon={TrendingUp}
                label={t("dashboard.stats.runs.label")}
                value={history.length}
                hint={
                  history[0]
                    ? t("dashboard.stats.runs.lastAgo", { ago: relativeTime(history[0].ts) })
                    : t("dashboard.stats.runs.noneYet")
                }
                tone="purple"
              />
            )}
          </Card>
        </div>

        {/* Full-GPU */}
        <Card variant="success" title={t("dashboard.fullGpu.title")} icon={Zap}>
          <p className="mb-3 text-xs text-slate-400">
            {t("dashboard.fullGpu.desc")}
          </p>
          {loading && (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          )}
          {!loading && fullGpu.length === 0 && (
            <Empty
              icon={Zap}
              title={t("dashboard.fullGpu.empty.title")}
              body={t("dashboard.fullGpu.empty.body")}
            />
          )}
          {!loading && fullGpu.length > 0 && (
            <div className="grid gap-2 lg:grid-cols-2">
              {fullGpu.map((row) => (
                <ModelRecRow key={row.model.id} row={row} onNavigate={onNavigate} accent="emerald" />
              ))}
            </div>
          )}
        </Card>

        {/* MoE offload */}
        {(loading || moe.length > 0) && (
          <Card variant="accent" title={t("dashboard.moe.title")} icon={Sparkles}>
            <p className="mb-3 text-xs text-slate-400">
              {t("dashboard.moe.desc")}
            </p>
            {loading && <Skeleton className="h-16 w-full" />}
            {!loading && (
              <div className="grid gap-2 lg:grid-cols-2">
                {moe.map((row) => (
                  <ModelRecRow key={row.model.id} row={row} onNavigate={onNavigate} accent="purple" />
                ))}
              </div>
            )}
          </Card>
        )}

        {/* GPU + CPU parcial */}
        {(loading || partial.length > 0) && (
          <Card title={t("dashboard.partial.title")} icon={Activity}>
            <p className="mb-3 text-xs text-slate-400">
              {t("dashboard.partial.desc")}
            </p>
            {loading && <Skeleton className="h-16 w-full" />}
            {!loading && (
              <div className="grid gap-2 lg:grid-cols-2">
                {partial.map((row) => (
                  <ModelRecRow key={row.model.id} row={row} onNavigate={onNavigate} accent="amber" />
                ))}
              </div>
            )}
          </Card>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Hardware detail */}
          <Card title={t("dashboard.hardware.title")} icon={Activity}>
            {loading && <Skeleton className="h-32 w-full" />}
            {!loading && hw && (
              <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                <Row k={t("dashboard.hardware.os")} v={`${hw.os} ${hw.os_version}`} />
                <Row k={t("dashboard.hardware.cpu")} v={hw.cpu.name} />
                <Row k={t("dashboard.hardware.cores")} v={`${hw.cpu.physical_cores}c / ${hw.cpu.logical_cores}t`} />
                <Row k={t("dashboard.hardware.frequency")} v={`${hw.cpu.freq_mhz?.toFixed(0) || "?"} MHz`} />
                <Row k={t("dashboard.hardware.ram")} v={t("dashboard.hardware.ramValue", { total: hw.ram_gb, free: hw.ram_available_gb })} />
                <Row
                  k={t("dashboard.hardware.gpu")}
                  v={
                    hw.gpus.length
                      ? hw.gpus.map((g) => `${g.name} · ${g.vram_gb}GB · ${g.vendor}`).join(" / ")
                      : t("dashboard.hardware.noGpu")
                  }
                />
              </dl>
            )}
          </Card>

          {/* Última actividad */}
          <Card title={t("dashboard.activity.title")} icon={TrendingUp}>
            {loading && <Skeleton className="h-32 w-full" />}
            {!loading && history.length === 0 && (
              <Empty
                icon={PlayCircle}
                title={t("dashboard.activity.empty.title")}
                body={t("dashboard.activity.empty.body")}
                action={
                  <Button onClick={() => onNavigate?.("benchmark")}>
                    <PlayCircle size={14} /> {t("dashboard.activity.empty.goToBenchmark")}
                  </Button>
                }
              />
            )}
            {!loading && history.length > 0 && (
              <ul className="space-y-2">
                {history.slice(0, 5).map((r) => {
                  let opts = {};
                  try {
                    opts = JSON.parse(r.opts_json);
                  } catch {}
                  return (
                    <li
                      key={r.id}
                      className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/30 p-2.5 text-sm"
                    >
                      <Badge tone={r.status === "done" ? "emerald" : "amber"}>
                        {t(`history.list.status.${r.status}`)}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 truncate">
                          <span className="font-medium">{opts.model || r.engine}</span>
                          {opts.quant && <Badge tone="indigo">{opts.quant}</Badge>}
                        </div>
                        <div className="text-xs text-slate-500">
                          {t("dashboard.activity.engineAgo", { engine: r.engine, ago: relativeTime(r.ts) })}
                        </div>
                      </div>
                      <button
                        onClick={() => onNavigate?.("history")}
                        className="text-xs text-slate-500 hover:text-indigo-300"
                      >
                        {t("dashboard.activity.view")}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        {/* Motores compactos */}
        <Card title={t("dashboard.engines.title", { count: engines.length })} icon={Server}>
          {loading ? (
            <Skeleton className="h-20 w-full" />
          ) : (
            <ul className="grid gap-2 md:grid-cols-3">
              {engines.map(({ meta, status, runtimes }) => {
                const ready = runtimes?.some((r) => r.ready);
                const running = status?.state === "running";
                return (
                  <li
                    key={meta.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/30 p-2.5 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{meta.name}</div>
                      <div className="text-xs text-slate-500">
                        {meta.type === "api" ? t("dashboard.engines.api") : meta.runtimes?.join(" · ") || "—"}
                      </div>
                    </div>
                    <Badge
                      tone={
                        meta.type === "api"
                          ? "indigo"
                          : running
                          ? "emerald"
                          : ready
                          ? "cyan"
                          : "slate"
                      }
                    >
                      {meta.type === "api"
                        ? t("dashboard.engines.api")
                        : running
                        ? t("dashboard.engines.running")
                        : ready
                        ? t("dashboard.engines.ready")
                        : t("dashboard.engines.off")}
                    </Badge>
                  </li>
                );
              })}
            </ul>
          )}
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

function ModelRecRow({ row, onNavigate, accent }) {
  const t = useT();
  const { model, config, techniques, engine_note } = row;
  const accents = {
    emerald: "from-emerald-500/20 to-cyan-500/20 text-emerald-300",
    purple: "from-purple-500/20 to-indigo-500/20 text-purple-300",
    amber: "from-amber-500/20 to-orange-500/20 text-amber-300",
  };
  // Primera técnica es siempre la de cuantización (la más informativa)
  const topTech = techniques[0];
  return (
    <button
      onClick={() => onNavigate?.("benchmark", { config })}
      className="group flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-left transition hover:border-indigo-500/60 hover:bg-slate-900/70"
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${accents[accent] || accents.emerald}`}>
        {compatIcon(config.status)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 truncate font-medium">
          <span className="truncate">{model.name}</span>
          {model.tags?.includes("popular") && <Sparkles size={11} className="shrink-0 text-amber-300" />}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
          <Badge tone={compatTone(config.status)}>{t(compatLabel(config.status))}</Badge>
          {config.quant && <Badge tone="indigo">{config.quant}</Badge>}
          {config.engine !== "llamacpp" && <Badge tone="amber">{config.engine}</Badge>}
          <Badge tone="slate">{model.params_b}B</Badge>
          {model.is_moe && <Badge tone="purple">MoE</Badge>}
          {config.context_len > 0 && (
            <span className="text-slate-500">{t("dashboard.rec.ctx", { ctx: config.context_len.toLocaleString() })}</span>
          )}
        </div>
        {topTech && (
          <div className="mt-1 truncate text-[10px] text-slate-500">{topTech}</div>
        )}
        {engine_note && (
          <div className="mt-0.5 truncate text-[10px] text-amber-400">{engine_note}</div>
        )}
      </div>
      <ArrowRight size={14} className="shrink-0 text-slate-600 transition group-hover:translate-x-0.5 group-hover:text-indigo-300" />
    </button>
  );
}

function relativeTime(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}min`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}
