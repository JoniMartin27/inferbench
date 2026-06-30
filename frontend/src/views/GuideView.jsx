import { useEffect, useState } from "react";
import {
  Cpu,
  Boxes,
  HardDrive,
  PlayCircle,
  Layers,
  GitCompare,
  CheckCircle2,
  Circle,
  ArrowRight,
  Lightbulb,
  Square,
  Download,
} from "lucide-react";
import { api } from "../api";
import { PageHeader, Card, Button, Badge, Skeleton } from "../components/ui.jsx";
import { useT } from "../i18n/index.jsx";

export default function GuideView({ onNavigate }) {
  const t = useT();
  const [state, setState] = useState({
    hw: null,
    engines: [],
    localModels: [],
    history: [],
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.hardware().catch(() => null),
      api.listEngines().catch(() => []),
      api.listLocalModels().catch(() => []),
      api.listHistory().catch(() => []),
    ]).then(([hw, engines, localModels, history]) => {
      if (!cancelled) setState({ hw, engines, localModels, history, loading: false });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const { hw, engines, localModels, history, loading } = state;

  // Estado por paso
  const hwOk = !!hw;
  const localCount = localModels.length;
  const runs = history.length;
  const sweepRuns = history.filter((r) => r.notes?.includes("[sweep")).length;
  const enginesReady = engines.filter(
    (e) => e.runtimes?.some((r) => r.ready)
  ).length;
  const hasRunForCompare = runs >= 2;

  const steps = [
    {
      id: 1,
      done: hwOk,
      icon: Cpu,
      title: t("guide.steps.hw.title"),
      detail: hwOk
        ? t("guide.steps.hw.detail", {
            cpu: hw.cpu.name.split(" ").slice(0, 4).join(" "),
            ram: hw.ram_gb,
            gpu: hw.gpus[0]?.name || t("guide.steps.hw.noGpu"),
            vram: hw.gpus[0] ? ` (${hw.gpus[0].vram_gb}GB VRAM)` : "",
          })
        : t("guide.steps.hw.detailPending"),
      why: t("guide.steps.hw.why"),
      action: { label: t("guide.steps.hw.action"), view: "dashboard" },
    },
    {
      id: 2,
      done: enginesReady > 0,
      icon: Layers,
      title: t("guide.steps.engines.title"),
      detail:
        enginesReady > 0
          ? t("guide.steps.engines.detail", { count: enginesReady })
          : t("guide.steps.engines.detailPending"),
      why: t("guide.steps.engines.why"),
      action: { label: t("guide.steps.engines.action"), view: "engines" },
    },
    {
      id: 3,
      done: localCount > 0 || runs > 0,
      icon: HardDrive,
      title: t("guide.steps.models.title"),
      detail:
        localCount > 0
          ? t("guide.steps.models.detail", { count: localCount })
          : t("guide.steps.models.detailPending"),
      why: t("guide.steps.models.why"),
      action: { label: t("guide.steps.models.action"), view: "models" },
    },
    {
      id: 4,
      done: runs > 0,
      icon: PlayCircle,
      title: t("guide.steps.firstBench.title"),
      detail: runs > 0
        ? t("guide.steps.firstBench.detail", { count: runs })
        : t("guide.steps.firstBench.detailPending"),
      why: t("guide.steps.firstBench.why"),
      action: { label: t("guide.steps.firstBench.action"), view: "benchmark", primary: true },
    },
    {
      id: 5,
      done: sweepRuns > 0,
      icon: Download,
      title: t("guide.steps.sweep.title"),
      detail:
        sweepRuns > 0
          ? t("guide.steps.sweep.detail", { count: sweepRuns })
          : t("guide.steps.sweep.detailPending"),
      why: t("guide.steps.sweep.why"),
      action: { label: t("guide.steps.sweep.action"), view: "benchmark" },
    },
    {
      id: 6,
      done: hasRunForCompare,
      icon: GitCompare,
      title: t("guide.steps.compare.title"),
      detail: hasRunForCompare
        ? t("guide.steps.compare.detail", { count: runs })
        : t("guide.steps.compare.detailPending"),
      why: t("guide.steps.compare.why"),
      action: { label: t("guide.steps.compare.action"), view: "history", disabled: !hasRunForCompare },
    },
  ];

  const completed = steps.filter((s) => s.done).length;
  const progress = Math.round((completed / steps.length) * 100);

  return (
    <>
      <PageHeader
        title={t("guide.header.title")}
        subtitle={t("guide.header.subtitle")}
      />

      <div className="space-y-6 p-8">
        {/* Progress */}
        <Card>
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-500">{t("guide.progress.label")}</div>
              <div className="mt-1 text-2xl font-semibold">
                {t("guide.progress.completed", { completed, total: steps.length })}
              </div>
            </div>
            <div className="text-right">
              <div className="text-3xl font-semibold text-indigo-300">{progress}%</div>
              <div className="text-xs text-slate-500">{t("guide.progress.ofFlow")}</div>
            </div>
          </div>
          <div
            role="progressbar"
            aria-label={t("guide.progress.label")}
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            className="mt-3 h-2 overflow-hidden rounded bg-slate-800"
          >
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </Card>

        {loading && (
          <div className="space-y-4">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        )}

        {!loading && (
          <div className="space-y-4">
            {steps.map((s) => (
              <StepCard key={s.id} step={s} onNavigate={onNavigate} />
            ))}
          </div>
        )}

        <Tips />
        <Faq />
      </div>
    </>
  );
}

function StepCard({ step, onNavigate }) {
  const t = useT();
  const Icon = step.icon;
  return (
    <div
      className={`flex gap-4 rounded-lg border p-5 ${
        step.done
          ? "border-emerald-700/40 bg-emerald-950/10"
          : "border-slate-800 bg-slate-900/30"
      }`}
    >
      <div className="flex flex-col items-center">
        {step.done ? (
          <CheckCircle2 className="text-emerald-400" size={22} />
        ) : (
          <Circle className="text-slate-600" size={22} />
        )}
        <div className="mt-2 text-xs font-mono text-slate-600">{step.id}</div>
      </div>

      <div className="flex-1">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Icon size={16} className="text-indigo-300" />
              <h3 className="font-semibold">{step.title}</h3>
              {step.done && <Badge tone="emerald">{t("guide.done")}</Badge>}
            </div>
            <p className="mt-1 text-sm text-slate-300">{step.detail}</p>
            <p className="mt-1 text-xs text-slate-500">{step.why}</p>
          </div>
          <Button
            variant={step.action.primary && !step.done ? "primary" : "ghost"}
            onClick={() => onNavigate(step.action.view)}
            disabled={step.action.disabled}
          >
            {step.action.label} <ArrowRight size={12} />
          </Button>
        </div>
      </div>
    </div>
  );
}

function Tips() {
  const t = useT();
  const items = [
    {
      icon: Square,
      title: t("guide.tips.stop.title"),
      body: t("guide.tips.stop.body"),
    },
    {
      icon: Boxes,
      title: t("guide.tips.reuse.title"),
      body: t("guide.tips.reuse.body"),
    },
    {
      icon: Lightbulb,
      title: t("guide.tips.optimize.title"),
      body: t("guide.tips.optimize.body"),
    },
    {
      icon: HardDrive,
      title: t("guide.tips.reuseGguf.title"),
      body: t("guide.tips.reuseGguf.body"),
    },
    {
      icon: Layers,
      title: t("guide.tips.kvCache.title"),
      body: t("guide.tips.kvCache.body"),
    },
    {
      icon: GitCompare,
      title: t("guide.tips.quality.title"),
      body: t("guide.tips.quality.body"),
    },
  ];
  return (
    <Card title={t("guide.tips.heading")}>
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item, i) => {
          const Icon = item.icon;
          return (
            <div key={i} className="flex gap-3 rounded border border-slate-800 p-3">
              <Icon size={16} className="mt-0.5 shrink-0 text-indigo-300" />
              <div>
                <div className="text-sm font-medium">{item.title}</div>
                <div className="mt-0.5 text-xs text-slate-400">{item.body}</div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function Faq() {
  const t = useT();
  const items = [
    {
      q: t("guide.faq.docker.q"),
      a: t("guide.faq.docker.a"),
    },
    {
      q: t("guide.faq.where.q"),
      a: t("guide.faq.where.a"),
    },
    {
      q: t("guide.faq.existing.q"),
      a: t("guide.faq.existing.a"),
    },
    {
      q: t("guide.faq.moe.q"),
      a: t("guide.faq.moe.a"),
    },
    {
      q: t("guide.faq.reliable.q"),
      a: t("guide.faq.reliable.a"),
    },
  ];
  return (
    <Card title={t("guide.faq.heading")}>
      <div className="space-y-3">
        {items.map((it, i) => (
          <details key={i} className="rounded border border-slate-800 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-200">
              {it.q}
            </summary>
            <p className="mt-2 text-sm text-slate-400">{it.a}</p>
          </details>
        ))}
      </div>
    </Card>
  );
}
