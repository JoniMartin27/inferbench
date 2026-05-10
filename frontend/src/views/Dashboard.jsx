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
import { api } from "../api";
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
  const [hw, setHw] = useState(null);
  const [engines, setEngines] = useState([]);
  const [history, setHistory] = useState([]);
  const [recommended, setRecommended] = useState({ fullGpu: [], moe: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.hardware().catch(() => null),
      api.listEngines().catch(() => []),
      api.listHistory().catch(() => []),
      api
        .modelCompat({ engine: "llamacpp", quant: "Q4_K_M", kvCache: "q8_0", contextLen: 4096, moeOffload: 27 })
        .catch(() => []),
    ])
      .then(([h, e, hist, compat]) => {
        setHw(h);
        setEngines(e);
        setHistory(hist);
        // Top recomendados — separar full-GPU vs MoE-offload
        const fullGpu = compat
          .filter((c) => c.status === "ok")
          .sort((a, b) => b.model.params_b - a.model.params_b)
          .slice(0, 5);
        const moe = compat.filter((c) => c.status === "moe").slice(0, 3);
        setRecommended({ fullGpu, moe });
      })
      .finally(() => setLoading(false));
  }, []);

  const running = engines.filter((e) => e.status?.state === "running").length;
  const operational = engines.filter(
    (e) => e.runtimes?.some((r) => r.ready) || e.meta.type === "api"
  ).length;

  return (
    <>
      <PageHeader
        eyebrow="Resumen"
        title="Dashboard"
        subtitle="Estado de tu entorno y modelos recomendados para tu hardware"
        actions={
          <Button onClick={() => onNavigate?.("benchmark")}>
            <PlayCircle size={14} /> Lanzar benchmark
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
                label="GPU principal"
                value={hw?.gpus?.[0]?.name?.replace("NVIDIA GeForce ", "") || "—"}
                hint={hw?.gpus?.[0] ? `${hw.gpus[0].vram_gb} GB VRAM` : "CPU-only"}
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
                label="RAM"
                value={`${hw?.ram_gb || 0} GB`}
                hint={`${hw?.ram_available_gb || 0} GB libres`}
              />
            )}
          </Card>
          <Card variant="flat">
            {loading ? (
              <Skeleton className="h-14 w-full" />
            ) : (
              <Stat
                icon={Server}
                label="Motores"
                value={`${operational}/${engines.length}`}
                hint={running > 0 ? `${running} corriendo` : "ninguno activo"}
                tone={running > 0 ? "success" : "default"}
              />
            )}
          </Card>
          <Card variant="flat">
            {loading ? (
              <Skeleton className="h-14 w-full" />
            ) : (
              <Stat
                icon={TrendingUp}
                label="Runs"
                value={history.length}
                hint={
                  history[0]
                    ? `última hace ${relativeTime(history[0].ts)}`
                    : "aún sin benchmarks"
                }
                tone="purple"
              />
            )}
          </Card>
        </div>

        {/* Full-GPU */}
        <Card variant="success" title="100% GPU — máxima velocidad" icon={Zap}>
          <p className="mb-3 text-xs text-slate-400">
            Estos modelos caben enteros en tu VRAM. Velocidad máxima (50-200+ tok/s típico).
          </p>
          {loading && (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)}
            </div>
          )}
          {!loading && recommended.fullGpu.length === 0 && (
            <Empty
              icon={Zap}
              title="Tu GPU es muy pequeña para los modelos del catálogo"
              body="Considera modelos más cuantizados o usa MoE offload."
            />
          )}
          {!loading && recommended.fullGpu.length > 0 && (
            <div className="grid gap-2 lg:grid-cols-2">
              {recommended.fullGpu.map((row) => (
                <ModelRecRow key={row.model.id} row={row} onNavigate={onNavigate} accent="emerald" />
              ))}
            </div>
          )}
        </Card>

        {/* MoE offload */}
        {recommended.moe.length > 0 && (
          <Card variant="accent" title="MoE offload — modelos enormes con --n-cpu-moe" icon={Sparkles}>
            <p className="mb-3 text-xs text-slate-400">
              Modelos MoE de hasta 30B+ params totales que caben en tu VRAM gracias a mover las capas
              expert a CPU. Velocidad razonable porque pocos params se activan por token.
            </p>
            <div className="grid gap-2 lg:grid-cols-2">
              {recommended.moe.map((row) => (
                <ModelRecRow key={row.model.id} row={row} onNavigate={onNavigate} accent="purple" />
              ))}
            </div>
          </Card>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Hardware detail */}
          <Card title="Hardware" icon={Activity}>
            {loading && <Skeleton className="h-32 w-full" />}
            {!loading && hw && (
              <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                <Row k="OS" v={`${hw.os} ${hw.os_version}`} />
                <Row k="CPU" v={hw.cpu.name} />
                <Row k="Cores" v={`${hw.cpu.physical_cores}c / ${hw.cpu.logical_cores}t`} />
                <Row k="Frecuencia" v={`${hw.cpu.freq_mhz?.toFixed(0) || "?"} MHz`} />
                <Row k="RAM" v={`${hw.ram_gb} GB total · ${hw.ram_available_gb} GB libres`} />
                <Row
                  k="GPU"
                  v={
                    hw.gpus.length
                      ? hw.gpus.map((g) => `${g.name} · ${g.vram_gb}GB · ${g.vendor}`).join(" / ")
                      : "ninguna"
                  }
                />
              </dl>
            )}
          </Card>

          {/* Última actividad */}
          <Card title="Última actividad" icon={TrendingUp}>
            {loading && <Skeleton className="h-32 w-full" />}
            {!loading && history.length === 0 && (
              <Empty
                icon={PlayCircle}
                title="Sin actividad"
                body="Lanza tu primer benchmark para empezar a coleccionar métricas."
                action={
                  <Button onClick={() => onNavigate?.("benchmark")}>
                    <PlayCircle size={14} /> Ir a Benchmark
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
                      <Badge tone={r.status === "done" ? "emerald" : "amber"}>{r.status}</Badge>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 truncate">
                          <span className="font-medium">{opts.model || r.engine}</span>
                          {opts.quant && <Badge tone="indigo">{opts.quant}</Badge>}
                        </div>
                        <div className="text-xs text-slate-500">
                          {r.engine} · {relativeTime(r.ts)} atrás
                        </div>
                      </div>
                      <button
                        onClick={() => onNavigate?.("history")}
                        className="text-xs text-slate-500 hover:text-indigo-300"
                      >
                        ver →
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        {/* Motores compactos */}
        <Card title={`Motores (${engines.length})`} icon={Server}>
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
                        {meta.type === "api" ? "API" : meta.runtimes?.join(" · ") || "—"}
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
                        ? "API"
                        : running
                        ? "running"
                        : ready
                        ? "listo"
                        : "off"}
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
  const { model, status, model_size_gb, max_context } = row;
  const accents = {
    emerald: "from-emerald-500/20 to-cyan-500/20 text-emerald-300",
    purple: "from-purple-500/20 to-indigo-500/20 text-purple-300",
  };
  return (
    <button
      onClick={() => onNavigate?.("benchmark", { model: model.id })}
      className="group flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-left transition hover:border-indigo-500/60 hover:bg-slate-900/70"
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${accents[accent]}`}>
        {compatIcon(status)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 truncate font-medium">
          <span className="truncate">{model.name}</span>
          {model.tags?.includes("popular") && <Sparkles size={11} className="shrink-0 text-amber-300" />}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
          <Badge tone={compatTone(status)}>{compatLabel(status)}</Badge>
          <Badge tone="slate">{model.params_b}B</Badge>
          <Badge tone="slate">{model_size_gb} GB</Badge>
          {model.is_moe && <Badge tone="purple">MoE</Badge>}
          <span className="text-slate-500">ctx {max_context.toLocaleString()}</span>
        </div>
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
