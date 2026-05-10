import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Cpu,
  Boxes,
  PlayCircle,
  History as HistoryIcon,
  Settings,
  Compass,
} from "lucide-react";
import { api } from "./api";
import GuideView from "./views/GuideView.jsx";
import Dashboard from "./views/Dashboard.jsx";
import EnginesView from "./views/EnginesView.jsx";
import ModelsView from "./views/ModelsView.jsx";
import BenchmarkView from "./views/BenchmarkView.jsx";
import HistoryView from "./views/HistoryView.jsx";
import SettingsView from "./views/SettingsView.jsx";

const NAV = [
  { id: "guide", label: "Guía", icon: Compass, View: GuideView },
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, View: Dashboard },
  { id: "engines", label: "Motores", icon: Cpu, View: EnginesView },
  { id: "models", label: "Modelos", icon: Boxes, View: ModelsView },
  { id: "benchmark", label: "Benchmark", icon: PlayCircle, View: BenchmarkView },
  { id: "history", label: "Historial", icon: HistoryIcon, View: HistoryView },
  { id: "settings", label: "Ajustes", icon: Settings, View: SettingsView },
];

export default function App() {
  // El usuario nuevo arranca en la Guía. Si ya ha visitado la app, retoma donde lo dejó.
  const [active, setActive] = useState(() => {
    return localStorage.getItem("inferbench:lastView") || "guide";
  });
  const [health, setHealth] = useState({ status: "checking" });

  useEffect(() => {
    localStorage.setItem("inferbench:lastView", active);
  }, [active]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const h = await api.health();
        if (!cancelled) setHealth(h);
      } catch {
        if (!cancelled) setHealth({ status: "offline" });
      }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const Current = NAV.find((n) => n.id === active)?.View || Dashboard;

  const dockerDown =
    health.status === "ok" && health.docker && health.docker.available === false;

  return (
    <div className="flex h-full flex-col">
      {dockerDown && (
        <div className="flex items-center justify-between gap-4 border-b border-slate-800 bg-slate-900/60 px-6 py-2 text-xs text-slate-400">
          <span>
            <span className="font-medium text-slate-300">Docker no disponible</span> ·
            llama.cpp puede arrancarse en modo nativo desde la pestaña Motores. Otros motores
            locales (Ollama, vLLM, SGLang, TGI) requieren Docker.
          </span>
          <a
            href="https://docs.docker.com/get-docker/"
            target="_blank"
            rel="noreferrer"
            className="rounded border border-slate-700 px-2 py-0.5 hover:border-slate-500"
          >
            Instalar Docker
          </a>
        </div>
      )}
      <div className="flex flex-1 overflow-hidden">
      <aside className="flex w-56 flex-col border-r border-slate-800 bg-slate-950/80">
        <div className="border-b border-slate-800 px-5 py-5">
          <div className="text-xl font-semibold tracking-tight">
            Infer<span className="text-indigo-400">Bench</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health.status === "ok"
                  ? "bg-emerald-400"
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
        <nav className="flex-1 p-2">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActive(id)}
              className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                active === id
                  ? "bg-indigo-500/15 text-indigo-200"
                  : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
              }`}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>
        <div className="px-4 py-3 text-[10px] text-slate-600">localhost:7777</div>
      </aside>

      <main className="flex-1 overflow-y-auto bg-slate-950 text-slate-100">
        <Current dockerDown={dockerDown} onNavigate={setActive} />
      </main>
      </div>
    </div>
  );
}
