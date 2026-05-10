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
import { PageHeader, Card, Button, Badge } from "../components/ui.jsx";

export default function GuideView({ onNavigate }) {
  const [state, setState] = useState({
    hw: null,
    engines: [],
    localModels: [],
    history: [],
    loading: true,
  });

  useEffect(() => {
    Promise.all([
      api.hardware().catch(() => null),
      api.listEngines().catch(() => []),
      api.listLocalModels().catch(() => []),
      api.listHistory().catch(() => []),
    ]).then(([hw, engines, localModels, history]) => {
      setState({ hw, engines, localModels, history, loading: false });
    });
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
      title: "Verifica tu hardware",
      detail: hwOk
        ? `Detectado: ${hw.cpu.name.split(" ").slice(0, 4).join(" ")} · ${hw.ram_gb}GB RAM · ${
            hw.gpus[0]?.name || "sin GPU"
          }${hw.gpus[0] ? ` (${hw.gpus[0].vram_gb}GB VRAM)` : ""}`
        : "InferBench va a usar tu CPU/GPU/RAM para elegir la mejor configuración",
      why: "El optimizador y el cálculo de compatibilidad dependen de saber qué máquina tienes.",
      action: { label: "Ver dashboard", view: "dashboard" },
    },
    {
      id: 2,
      done: enginesReady > 0,
      icon: Layers,
      title: "Tu motor está listo",
      detail:
        enginesReady > 0
          ? `${enginesReady} runtime(s) operativo(s)`
          : "El primer benchmark descarga llama.cpp automáticamente (~300MB binario + ~390MB cudart si tienes NVIDIA)",
      why: "llama.cpp corre como proceso nativo, sin Docker. Otros motores (Ollama/vLLM/SGLang/TGI) usan Docker si lo tienes.",
      action: { label: "Ver motores", view: "engines" },
    },
    {
      id: 3,
      done: localCount > 0 || runs > 0,
      icon: HardDrive,
      title: "Modelos disponibles",
      detail:
        localCount > 0
          ? `${localCount} GGUF(s) detectados en tu disco — InferBench escanea LM Studio, HF cache, llama.cpp y más`
          : "Aún no tienes GGUFs en disco. El primer benchmark descargará uno desde Hugging Face.",
      why: "Puedes usar cualquier GGUF que ya tengas o descargar del catálogo. Compatibilidad calculada en tiempo real con tu hardware.",
      action: { label: "Ver catálogo + locales", view: "models" },
    },
    {
      id: 4,
      done: runs > 0,
      icon: PlayCircle,
      title: "Lanza tu primer benchmark",
      detail: runs > 0
        ? `${runs} run(s) ejecutadas`
        : "Recomendado para empezar: Llama 3.2 1B Q4_K_M (~760MB, completa en ~1 minuto en RTX 3070)",
      why: "Con 1 click la app baja binario + modelo, arranca el motor con la config óptima y mide TTFT, tok/s, VRAM y calidad para 4 prompts.",
      action: { label: "Ir a benchmark", view: "benchmark", primary: true },
    },
    {
      id: 5,
      done: sweepRuns > 0,
      icon: Download,
      title: "Compara cuantizaciones (sweep)",
      detail:
        sweepRuns > 0
          ? `${sweepRuns} run(s) de sweep`
          : "Marca varias cuantizaciones (p.ej. Q4_K_M, Q5_K_M, Q6_K) y pulsa Sweep — corre todas en cola",
      why: "Q4 suele ser el sweet spot velocidad/calidad, pero depende del modelo. Sweep responde 'cuál es realmente la mejor para mí'.",
      action: { label: "Ir a benchmark", view: "benchmark" },
    },
    {
      id: 6,
      done: hasRunForCompare,
      icon: GitCompare,
      title: "Compara resultados",
      detail: hasRunForCompare
        ? `${runs} runs guardadas, listas para comparar`
        : "Cuando tengas 2+ runs, podrás compararlas lado a lado",
      why: "Tabla resumen + 4 gráficos (tok/s, TTFT, calidad, VRAM peak) por prompt. Te dice qué config rinde mejor para cada tarea.",
      action: { label: "Ver historial", view: "history", disabled: !hasRunForCompare },
    },
  ];

  const completed = steps.filter((s) => s.done).length;
  const progress = Math.round((completed / steps.length) * 100);

  return (
    <>
      <PageHeader
        title="Guía"
        subtitle="Sigue el flujo recomendado — cada paso muestra su estado actual"
      />

      <div className="space-y-6 p-8">
        {/* Progress */}
        <Card>
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-500">Progreso</div>
              <div className="mt-1 text-2xl font-semibold">
                {completed} / {steps.length} pasos completados
              </div>
            </div>
            <div className="text-right">
              <div className="text-3xl font-semibold text-indigo-300">{progress}%</div>
              <div className="text-xs text-slate-500">del flujo recomendado</div>
            </div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded bg-slate-800">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </Card>

        {loading && <p className="text-slate-500">Cargando estado…</p>}

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
              {step.done && <Badge tone="emerald">hecho</Badge>}
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
  const items = [
    {
      icon: Square,
      title: "Detener en cualquier momento",
      body: "Durante una corrida verás un botón rojo Detener en Benchmark. Cancela bootstrap, descarga o ejecución sin dejar el motor zombi.",
    },
    {
      icon: Boxes,
      title: "Reuso de motor",
      body: "Si vas a lanzar varias veces el mismo modelo+cuantización, marca 'No detener motor al terminar' para evitar la carga del modelo en cada run (saltas ~5-10s).",
    },
    {
      icon: Lightbulb,
      title: "⚡ Optimizar para tu hardware",
      body: "En la pestaña Modelos, click en ⚡ junto a cualquier modelo: la app calcula la mejor cuantización + KV cache + contexto + flags para tu GPU automáticamente.",
    },
    {
      icon: HardDrive,
      title: "Reusa GGUFs que ya tengas",
      body: "InferBench detecta modelos de LM Studio, llama.cpp, HuggingFace cache, GPT4All... Si tienes un GGUF en otra carpeta, añádela en Modelos → 'Carpetas escaneadas'.",
    },
  ];
  return (
    <Card title="Tips">
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((t, i) => (
          <div key={i} className="flex gap-3 rounded border border-slate-800 p-3">
            <t.icon size={16} className="mt-0.5 shrink-0 text-indigo-300" />
            <div>
              <div className="text-sm font-medium">{t.title}</div>
              <div className="mt-0.5 text-xs text-slate-400">{t.body}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Faq() {
  const items = [
    {
      q: "¿Necesito Docker?",
      a: "No para llama.cpp — corre nativo. Sí lo necesitas para Ollama, vLLM, SGLang y TGI (en implementación). APIs cloud (OpenAI, Anthropic, OpenRouter, NVIDIA NIM) tampoco requieren Docker.",
    },
    {
      q: "¿Dónde se guardan los modelos descargados?",
      a: "%APPDATA%\\InferBench\\models\\ en Windows o ~/.inferbench/models/ en Linux/Mac. Una vez descargado, se reusa para futuros benchmarks.",
    },
    {
      q: "¿Puedo usar mis GGUFs existentes?",
      a: "Sí. La pestaña Modelos → Locales escanea LM Studio, llama.cpp, HuggingFace cache, GPT4All, Jan.ai y muestra todos con su metadata (arquitectura, capas, contexto, params). Añade carpetas extras desde 'Carpetas escaneadas'.",
    },
    {
      q: "¿Y los modelos MoE como Qwen 3 30B-A3B o Mixtral?",
      a: "Compatibilidad calculada con --n-cpu-moe (offload de capas MoE a CPU). El optimizador elige automáticamente cuántas capas descargar según tu VRAM. Auto-descarga GGUF para MoE aún pendiente.",
    },
    {
      q: "¿Cómo de fiable es la calidad medida?",
      a: "MVP: heurística por longitud + overlap con respuesta de referencia. Para juicio fiable, sustituir por LLM-judge (pendiente). TTFT y tok/s sí son medidas reales del motor.",
    },
  ];
  return (
    <Card title="FAQ">
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
