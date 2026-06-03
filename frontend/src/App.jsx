import { Suspense, lazy, useEffect, useState } from "react";
import {
  LayoutDashboard,
  Cpu,
  Boxes,
  PlayCircle,
  History as HistoryIcon,
  Settings,
  Compass,
  Activity,
} from "lucide-react";
import { api } from "./api";
import { useBenchmarkRun } from "./useBenchmarkRun";
import { ToastProvider } from "./components/toast.jsx";
import { Spinner } from "./components/ui.jsx";

// Vistas cargadas bajo demanda (code-splitting): el chunk pesado de recharts (gráficos de
// Historial/Benchmark) ya no entra en el bundle inicial → arranque más rápido de la app.
const GuideView = lazy(() => import("./views/GuideView.jsx"));
const Dashboard = lazy(() => import("./views/Dashboard.jsx"));
const EnginesView = lazy(() => import("./views/EnginesView.jsx"));
const ModelsView = lazy(() => import("./views/ModelsView.jsx"));
const BenchmarkView = lazy(() => import("./views/BenchmarkView.jsx"));
const HistoryView = lazy(() => import("./views/HistoryView.jsx"));
const SettingsView = lazy(() => import("./views/SettingsView.jsx"));

const NAV_GROUPS = [
  {
    label: "Empezar",
    items: [{ id: "guide", label: "Guía", icon: Compass, View: GuideView }],
  },
  {
    label: "Workflow",
    items: [
      { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, View: Dashboard },
      { id: "models", label: "Modelos", icon: Boxes, View: ModelsView },
      { id: "engines", label: "Motores", icon: Cpu, View: EnginesView },
      { id: "benchmark", label: "Benchmark", icon: PlayCircle, View: BenchmarkView },
    ],
  },
  {
    label: "Datos",
    items: [
      { id: "history", label: "Historial", icon: HistoryIcon, View: HistoryView },
      { id: "settings", label: "Ajustes", icon: Settings, View: SettingsView },
    ],
  },
];

const ALL_NAV = NAV_GROUPS.flatMap((g) => g.items);

export default function App() {
  const [active, setActive] = useState(() => {
    return localStorage.getItem("inferbench:lastView") || "guide";
  });
  const [navPayload, setNavPayload] = useState(null);
  const [health, setHealth] = useState({ status: "checking" });
  const [counts, setCounts] = useState({ history: 0, models: 0, engines: 0 });
  // Estado del benchmark a nivel App: sobrevive al cambio de pestaña
  const benchmark = useBenchmarkRun();

  useEffect(() => {
    localStorage.setItem("inferbench:lastView", active);
  }, [active]);

  const navigate = (view, payload = null) => {
    setActive(view);
    setNavPayload(payload);
  };

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [h, hist, models, engines] = await Promise.all([
          api.health().catch(() => ({ status: "offline" })),
          api.listHistory().catch(() => []),
          api.listModels().catch(() => []),
          api.listEngines().catch(() => []),
        ]);
        if (cancelled) return;
        setHealth(h);
        setCounts({ history: hist.length, models: models.length, engines: engines.length });
      } catch {
        if (!cancelled) setHealth({ status: "offline" });
      }
    };
    tick();
    const id = setInterval(tick, 6000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const Current = ALL_NAV.find((n) => n.id === active)?.View || Dashboard;
  const dockerDown = health.status === "ok" && health.docker && health.docker.available === false;

  return (
    <ToastProvider>
    <div className="flex h-full flex-col bg-slate-950">
      {dockerDown && (
        <div className="flex items-center justify-between gap-4 border-b border-slate-800 bg-gradient-to-r from-slate-900/80 to-slate-900/50 px-6 py-1.5 text-xs text-slate-400">
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            <span>
              <strong className="text-slate-300">Docker no disponible</strong> — llama.cpp y
              Ollama (nativo) funcionan sin Docker
            </span>
          </span>
          <a
            href="https://docs.docker.com/get-docker/"
            target="_blank"
            rel="noreferrer"
            className="rounded border border-slate-700/80 px-2 py-0.5 hover:border-slate-500 hover:text-slate-200"
          >
            Instalar Docker
          </a>
        </div>
      )}
      <div className="flex flex-1 overflow-hidden">
        <aside className="flex w-60 flex-col border-r border-slate-800 bg-gradient-to-b from-slate-950 to-slate-950/80">
          <div className="border-b border-slate-800 px-5 py-5">
            <div className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-purple-500 text-white shadow-lg shadow-indigo-900/40">
                <Activity size={14} />
              </div>
              Infer<span className="text-indigo-400">Bench</span>
            </div>
            <div className="mt-2 flex items-center gap-2 text-[10px] uppercase tracking-wider">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  health.status === "ok"
                    ? "bg-emerald-400 shadow shadow-emerald-500/50"
                    : health.status === "checking"
                    ? "bg-amber-400"
                    : "bg-rose-500"
                }`}
              />
              <span className="text-slate-500">
                backend {health.status === "ok" ? `v${health.version}` : health.status}
              </span>
            </div>
          </div>

          <nav className="flex-1 overflow-y-auto p-2">
            {NAV_GROUPS.map((group) => (
              <div key={group.label} className="mb-3">
                <div className="px-3 pb-1 pt-2 text-[9px] font-semibold uppercase tracking-[0.2em] text-slate-600">
                  {group.label}
                </div>
                {group.items.map(({ id, label, icon: Icon }) => {
                  const isActive = active === id;
                  const isRunning = id === "benchmark" && !!benchmark.running;
                  const badge =
                    id === "history" && counts.history > 0
                      ? counts.history
                      : id === "models" && counts.models > 0
                      ? counts.models
                      : null;
                  return (
                    <button
                      key={id}
                      onClick={() => navigate(id)}
                      className={`group relative flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                        isActive
                          ? "bg-gradient-to-r from-indigo-500/15 to-transparent text-indigo-200"
                          : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-100"
                      }`}
                    >
                      {isActive && (
                        <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-indigo-400" />
                      )}
                      <Icon size={15} className={isActive ? "text-indigo-300" : ""} />
                      <span className="flex-1 text-left">{label}</span>
                      {isRunning && (
                        <span
                          className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400 shadow shadow-emerald-500/50"
                          title="Benchmark en curso"
                        />
                      )}
                      {badge != null && (
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${
                            isActive
                              ? "bg-indigo-500/20 text-indigo-200"
                              : "bg-slate-800/60 text-slate-500"
                          }`}
                        >
                          {badge}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="border-t border-slate-800 px-4 py-3 text-[10px] text-slate-600">
            <div className="font-mono">localhost:7777</div>
            <div className="mt-0.5 truncate">
              {health.docker?.available ? `Docker ${health.docker.version}` : "sin Docker"}
            </div>
          </div>
        </aside>

        <main className="flex-1 overflow-y-auto bg-slate-950 text-slate-100">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-slate-500">
                <Spinner className="text-indigo-400" />
              </div>
            }
          >
            <Current
              dockerDown={dockerDown}
              onNavigate={navigate}
              navPayload={navPayload}
              benchmark={benchmark}
            />
          </Suspense>
        </main>
      </div>
    </div>
    </ToastProvider>
  );
}
