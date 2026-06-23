import { Component, Suspense, lazy, useEffect, useState } from "react";
import {
  LayoutDashboard,
  Cpu,
  Boxes,
  PlayCircle,
  History as HistoryIcon,
  Settings,
  Compass,
  Activity,
  Server,
} from "lucide-react";
import { api } from "./api";
import { useBenchmarkRun } from "./useBenchmarkRun";
import { ToastProvider } from "./components/toast.jsx";
import { Spinner } from "./components/ui.jsx";
import { useT } from "./i18n/index.jsx";

// Vistas cargadas bajo demanda (code-splitting): el chunk pesado de recharts (gráficos de
// Historial/Benchmark) ya no entra en el bundle inicial → arranque más rápido de la app.
const GuideView = lazy(() => import("./views/GuideView.jsx"));
const Dashboard = lazy(() => import("./views/Dashboard.jsx"));
const EnginesView = lazy(() => import("./views/EnginesView.jsx"));
const ModelsView = lazy(() => import("./views/ModelsView.jsx"));
const BenchmarkView = lazy(() => import("./views/BenchmarkView.jsx"));
const ServeView = lazy(() => import("./views/ServeView.jsx"));
const HistoryView = lazy(() => import("./views/HistoryView.jsx"));
const SettingsView = lazy(() => import("./views/SettingsView.jsx"));

// Boundary para los chunks lazy: si un import() de vista falla (chunk no carga tras un
// deploy, throw en el módulo) mostramos un fallback en vez de tumbar toda la app a pantalla
// en blanco. key={active} en el uso lo resetea al cambiar de vista (reintenta la siguiente).
class ViewErrorBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("Failed to load view:", error, info);
  }
  render() {
    if (this.state.error) {
      const t = this.props.t;
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-slate-400">
          <p className="text-sm">{t("app.viewLoadError")}</p>
          <button
            onClick={() => this.setState({ error: null })}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
          >
            {t("common.retry")}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const NAV_GROUPS = [
  {
    labelKey: "app.nav.start",
    items: [{ id: "guide", labelKey: "app.nav.guide", icon: Compass, View: GuideView }],
  },
  {
    labelKey: "app.nav.workflow",
    items: [
      { id: "dashboard", labelKey: "app.nav.dashboard", icon: LayoutDashboard, View: Dashboard, mode: "benchmark" },
      { id: "models", labelKey: "app.nav.models", icon: Boxes, View: ModelsView, mode: "benchmark" },
      { id: "engines", labelKey: "app.nav.engines", icon: Cpu, View: EnginesView, mode: "benchmark" },
      { id: "benchmark", labelKey: "app.nav.benchmark", icon: PlayCircle, View: BenchmarkView, mode: "benchmark" },
      { id: "serve", labelKey: "app.nav.serve", icon: Server, View: ServeView, mode: "serve" },
    ],
  },
  {
    labelKey: "app.nav.data",
    items: [
      { id: "history", labelKey: "app.nav.history", icon: HistoryIcon, View: HistoryView, mode: "benchmark" },
      { id: "settings", labelKey: "app.nav.settings", icon: Settings, View: SettingsView },
    ],
  },
];

const ALL_NAV = NAV_GROUPS.flatMap((g) => g.items);

// Modos / Features unificados. Cada ítem de nav declara su `mode`; los que no lo tengan
// (p.ej. settings) están SIEMPRE visibles. Persistido en localStorage por SettingsView.
// Default: ambos modos ON. Invariante: nunca ambos OFF (se fuerza en getModes/SettingsView).
const MODES_KEY = "inferbench:modes";

export function getModes() {
  try {
    const raw = JSON.parse(localStorage.getItem(MODES_KEY) || "{}");
    const benchmark = raw.benchmark !== false; // default ON
    let serve = raw.serve !== false; // default ON
    // Invariante: al menos un modo activo. Si ambos quedaron OFF, reactiva benchmark.
    if (!benchmark && !serve) return { benchmark: true, serve: false };
    return { benchmark, serve };
  } catch {
    return { benchmark: true, serve: true };
  }
}

export default function App() {
  const t = useT();
  const [active, setActive] = useState(() => {
    return localStorage.getItem("inferbench:lastView") || "guide";
  });
  const [navPayload, setNavPayload] = useState(null);
  const [health, setHealth] = useState({ status: "checking" });
  const [counts, setCounts] = useState({ history: 0, models: 0, engines: 0 });
  const [modes, setModes] = useState(getModes);
  // Estado del benchmark a nivel App: sobrevive al cambio de pestaña
  const benchmark = useBenchmarkRun();

  // Re-lee los modos cuando SettingsView los cambia (evento propio, misma pestaña) o
  // cuando se editan en otra ventana (storage event).
  useEffect(() => {
    const sync = () => setModes(getModes());
    window.addEventListener("inferbench:modes-changed", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("inferbench:modes-changed", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  // Nav visible según los modos activos. Los ítems sin `mode` (settings) siempre se ven.
  const navGroups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((it) => !it.mode || modes[it.mode]),
  })).filter((g) => g.items.length > 0);
  const visibleIds = navGroups.flatMap((g) => g.items.map((it) => it.id));

  // Si la vista activa pertenece a un modo desactivado, salta a la primera visible.
  useEffect(() => {
    if (!visibleIds.includes(active)) {
      setActive(visibleIds[0] || "settings");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modes]);

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
              <strong className="text-slate-300">{t("app.dockerUnavailable")}</strong> — {t("app.dockerHint")}
            </span>
          </span>
          <a
            href="https://docs.docker.com/get-docker/"
            target="_blank"
            rel="noreferrer"
            className="rounded border border-slate-700/80 px-2 py-0.5 hover:border-slate-500 hover:text-slate-200"
          >
            {t("app.installDocker")}
          </a>
        </div>
      )}
      <div className="flex flex-1 overflow-hidden">
        <aside className="flex w-60 flex-col border-r border-slate-800 bg-gradient-to-b from-slate-950 to-slate-950/80">
          <div className="border-b border-slate-800 px-5 py-5">
            <div className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-amber-400 to-accent text-[#2A1402] shadow-lg shadow-orange-900/40">
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
                {t("app.backendStatus")} {health.status === "ok" ? `v${health.version}` : health.status}
              </span>
            </div>
          </div>

          <nav className="flex-1 overflow-y-auto p-2">
            {navGroups.map((group) => (
              <div key={group.labelKey} className="mb-3">
                <div className="px-3 pb-1 pt-2 text-[9px] font-semibold uppercase tracking-[0.2em] text-slate-600">
                  {t(group.labelKey)}
                </div>
                {group.items.map(({ id, labelKey, icon: Icon }) => {
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
                      <span className="flex-1 text-left">{t(labelKey)}</span>
                      {isRunning && (
                        <span
                          className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400 shadow shadow-emerald-500/50"
                          title={t("app.benchmarkRunning")}
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
              {health.docker?.available ? t("app.docker", { version: health.docker.version }) : t("app.noDocker")}
            </div>
            <a
              href="https://fervon.dev"
              target="_blank"
              rel="noreferrer"
              className="mt-1.5 inline-block text-slate-500 transition hover:text-accent"
            >
              Forged red-hot · part of Fervon
            </a>
          </div>
        </aside>

        <main className="flex-1 overflow-y-auto bg-slate-950 text-slate-100">
          <ViewErrorBoundary key={active} t={t}>
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
          </ViewErrorBoundary>
        </main>
      </div>
    </div>
    </ToastProvider>
  );
}
