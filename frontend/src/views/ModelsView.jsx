import { useEffect, useState } from "react";
import { Zap, RefreshCw, FolderOpen, HardDrive, Cloud, Play } from "lucide-react";
import { api } from "../api";
import {
  PageHeader,
  Card,
  Field,
  Select,
  Input,
  Badge,
  Button,
  Spinner,
  compatTone,
  compatLabel,
} from "../components/ui.jsx";

const QUANTS = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"];
const KV_OPTS = ["f16", "q8_0", "q4_0"];

export default function ModelsView({ onNavigate }) {
  const [engines, setEngines] = useState([]);
  const [engine, setEngine] = useState("llamacpp");
  const [quant, setQuant] = useState("Q4_K_M");
  const [kvCache, setKvCache] = useState("q8_0");
  const [contextLen, setContextLen] = useState(4096);
  const [moeOffload, setMoeOffload] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("catalog"); // catalog | local
  const [localModels, setLocalModels] = useState([]);
  const [localLoading, setLocalLoading] = useState(false);
  const [searchDirs, setSearchDirs] = useState({ known: [], extra: [] });
  const [showDirs, setShowDirs] = useState(false);
  const [extraInput, setExtraInput] = useState("");

  const refreshLocal = async () => {
    setLocalLoading(true);
    try {
      const [m, d] = await Promise.all([api.listLocalModels(), api.listSearchDirs()]);
      setLocalModels(m);
      setSearchDirs(d);
      setExtraInput((d.extra || []).join("\n"));
    } finally {
      setLocalLoading(false);
    }
  };

  const saveDirs = async () => {
    const dirs = extraInput.split("\n").map((s) => s.trim()).filter(Boolean);
    await api.saveSearchDirs(dirs);
    await refreshLocal();
  };

  useEffect(() => {
    api.listEngines().then(setEngines).catch(() => {});
    refreshLocal();
  }, []);

  useEffect(() => {
    setLoading(true);
    api
      .modelCompat({
        engine,
        quant,
        kvCache,
        contextLen,
        moeOffload: moeOffload ? Number(moeOffload) : null,
      })
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [engine, quant, kvCache, contextLen, moeOffload]);

  const isApi = engines.find((e) => e.meta.id === engine)?.meta.type === "api";
  const [optimal, setOptimal] = useState(null); // { modelId, config } | null
  const [optimizing, setOptimizing] = useState(null);

  const optimize = async (modelId) => {
    setOptimizing(modelId);
    setOptimal(null);
    try {
      const cfg = await api.optimize(engine, modelId);
      setOptimal({ modelId, config: cfg });
    } finally {
      setOptimizing(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Modelos"
        subtitle="Catálogo descargable + escaneo de GGUFs locales en tu disco"
        actions={
          <Button variant="ghost" onClick={refreshLocal}>
            <RefreshCw size={14} /> Re-escanear
          </Button>
        }
      />

      <div className="flex gap-2 px-8 pt-4">
        <TabButton active={tab === "catalog"} onClick={() => setTab("catalog")} icon={Cloud}>
          Catálogo ({rows.length})
        </TabButton>
        <TabButton active={tab === "local"} onClick={() => setTab("local")} icon={HardDrive}>
          Locales ({localModels.length})
        </TabButton>
      </div>

      {tab === "local" && (
        <div className="space-y-6 p-8">
          <Card
            title={`Modelos GGUF detectados en disco (${localModels.length})`}
            actions={
              <button
                onClick={() => setShowDirs((s) => !s)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200"
              >
                <FolderOpen size={12} /> Carpetas escaneadas
              </button>
            }
          >
            {showDirs && (
              <div className="mb-4 space-y-3 border-b border-slate-800 pb-4">
                <div>
                  <div className="mb-1 text-xs uppercase text-slate-500">Carpetas conocidas</div>
                  <ul className="space-y-0.5 font-mono text-xs text-slate-400">
                    {searchDirs.known.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="mb-1 text-xs uppercase text-slate-500">Carpetas extra (una por línea)</div>
                  <textarea
                    rows={4}
                    value={extraInput}
                    onChange={(e) => setExtraInput(e.target.value)}
                    placeholder="C:/MisModelos&#10;D:/llm-cache"
                    className="w-full rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 font-mono text-xs text-slate-200 outline-none focus:border-indigo-400"
                  />
                  <div className="mt-2 flex gap-2">
                    <Button onClick={saveDirs}>Guardar</Button>
                    <span className="self-center text-xs text-slate-500">
                      Se guarda en {searchDirs.extra_dirs_file}
                    </span>
                  </div>
                </div>
              </div>
            )}
            {localLoading && <p className="text-sm text-slate-500">Escaneando…</p>}
            {!localLoading && localModels.length === 0 && (
              <p className="text-sm text-slate-500">
                No se encontraron GGUFs en las carpetas conocidas. Añade carpetas extra arriba si tienes modelos en otra ubicación.
              </p>
            )}
            {localModels.length > 0 && (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                    <tr className="border-b border-slate-800">
                      <th className="py-2 pr-3">Nombre</th>
                      <th className="py-2 pr-3">Arch</th>
                      <th className="py-2 pr-3">Quant</th>
                      <th className="py-2 pr-3">Params</th>
                      <th className="py-2 pr-3">Tamaño</th>
                      <th className="py-2 pr-3">Capas</th>
                      <th className="py-2 pr-3">Ctx</th>
                      <th className="py-2 pr-3">Origen</th>
                      <th className="py-2 pr-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {localModels.map((m) => (
                      <tr key={m.path} className="border-b border-slate-900 hover:bg-slate-900/40">
                        <td className="py-2 pr-3">
                          <div className="font-medium">{m.name || m.filename.replace(".gguf", "")}</div>
                          <div className="truncate text-xs text-slate-500" title={m.path}>
                            {m.path}
                          </div>
                        </td>
                        <td className="py-2 pr-3">
                          {m.architecture ? <Badge tone="indigo">{m.architecture}</Badge> : "—"}
                          {m.is_moe && (
                            <Badge tone="purple" className="ml-1">
                              MoE
                            </Badge>
                          )}
                        </td>
                        <td className="py-2 pr-3">
                          {m.quant ? <Badge>{m.quant}</Badge> : <span className="text-slate-500">?</span>}
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-slate-300">
                          {m.params_b ? `${m.params_b}B` : "—"}
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-slate-300">{m.size_gb} GB</td>
                        <td className="py-2 pr-3 tabular-nums text-slate-300">{m.n_layer || "—"}</td>
                        <td className="py-2 pr-3 tabular-nums text-slate-300">
                          {m.context_length ? m.context_length.toLocaleString() : "—"}
                        </td>
                        <td className="py-2 pr-3">
                          <span
                            className="text-xs text-slate-500"
                            title={m.dir}
                          >
                            {shortenPath(m.dir)}
                          </span>
                        </td>
                        <td className="py-2 pr-3">
                          <button
                            onClick={() => onNavigate?.("benchmark", { localModel: m })}
                            className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-emerald-400 hover:text-emerald-200"
                            title="Lanzar benchmark con este GGUF"
                          >
                            <Play size={12} /> Benchmark
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === "catalog" && (
      <div className="space-y-6 p-8">
        <Card title="Configuración">
          <div className="grid gap-4 md:grid-cols-5">
            <Field label="Motor">
              <Select value={engine} onChange={(e) => setEngine(e.target.value)}>
                {engines.map((e) => (
                  <option key={e.meta.id} value={e.meta.id}>
                    {e.meta.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Cuantización">
              <Select
                value={quant}
                onChange={(e) => setQuant(e.target.value)}
                disabled={isApi}
              >
                {QUANTS.map((q) => (
                  <option key={q}>{q}</option>
                ))}
              </Select>
            </Field>
            <Field label="KV cache">
              <Select
                value={kvCache}
                onChange={(e) => setKvCache(e.target.value)}
                disabled={isApi}
              >
                {KV_OPTS.map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </Select>
            </Field>
            <Field label="Contexto">
              <Input
                type="number"
                value={contextLen}
                onChange={(e) => setContextLen(Number(e.target.value) || 0)}
                disabled={isApi}
              />
            </Field>
            <Field label="MoE offload (n capas CPU)" hint="solo llama.cpp + modelos MoE">
              <Input
                type="number"
                value={moeOffload}
                onChange={(e) => setMoeOffload(e.target.value)}
                placeholder="—"
                disabled={isApi || engine !== "llamacpp"}
              />
            </Field>
          </div>
        </Card>

        {optimal && (
          <Card
            title={`Configuración óptima · ${optimal.modelId}`}
            actions={
              <button
                onClick={() => setOptimal(null)}
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                cerrar
              </button>
            }
          >
            <OptimalDetail cfg={optimal.config} />
          </Card>
        )}

        <Card title={`Catálogo (${rows.length} modelos)`}>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="py-2 pr-3">Modelo</th>
                  <th className="py-2 pr-3">Tipo</th>
                  <th className="py-2 pr-3">Params</th>
                  <th className="py-2 pr-3">Tamaño</th>
                  <th className="py-2 pr-3">Total ~</th>
                  <th className="py-2 pr-3">Max ctx</th>
                  <th className="py-2 pr-3">Compat</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-slate-500">
                      Calculando…
                    </td>
                  </tr>
                )}
                {!loading &&
                  rows.map(({ model, status, model_size_gb, estimated_total_gb, max_context }) => (
                    <tr key={model.id} className="border-b border-slate-900 hover:bg-slate-900/40">
                      <td className="py-2 pr-3">
                        <div className="font-medium">{model.name}</div>
                        <div className="text-xs text-slate-500">{model.id}</div>
                      </td>
                      <td className="py-2 pr-3">
                        {model.is_moe ? (
                          <Badge tone="purple">MoE · {model.active_b}B act</Badge>
                        ) : (
                          <Badge>dense</Badge>
                        )}
                      </td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{model.params_b}B</td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{model_size_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{estimated_total_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{max_context.toLocaleString()}</td>
                      <td className="py-2 pr-3">
                        <Badge tone={compatTone(status)}>{compatLabel(status)}</Badge>
                      </td>
                      <td className="py-2 pr-3">
                        <button
                          onClick={() => optimize(model.id)}
                          className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-indigo-400 hover:text-indigo-200"
                          title="Optimizar para mi hardware"
                        >
                          {optimizing === model.id ? <Spinner /> : <Zap size={12} />} Optimizar
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      )}
    </>
  );
}

function TabButton({ active, onClick, icon: Icon, children }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition ${
        active
          ? "border-indigo-500 bg-indigo-500/10 text-indigo-200"
          : "border-slate-700 text-slate-400 hover:border-slate-600"
      }`}
    >
      <Icon size={14} />
      {children}
    </button>
  );
}

function shortenPath(p) {
  if (!p) return "";
  const parts = p.split(/[\\/]+/);
  if (parts.length <= 3) return p;
  return ".../" + parts.slice(-2).join("/");
}

function OptimalDetail({ cfg }) {
  if (!cfg.feasible) {
    return (
      <div>
        <Badge tone="rose">No viable</Badge>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-400">
          {cfg.rationale.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="grid grid-cols-2 gap-3 text-sm">
        <Kv k="Status" v={<Badge tone={compatTone(cfg.status)}>{compatLabel(cfg.status)}</Badge>} />
        <Kv k="Cuantización" v={cfg.quant || "—"} />
        <Kv k="KV cache" v={cfg.kv_cache || "—"} />
        <Kv k="Contexto" v={cfg.context_len?.toLocaleString() || "—"} />
        {cfg.moe_offload != null && <Kv k="MoE offload" v={`--n-cpu-moe ${cfg.moe_offload}`} />}
        <Kv k="Total estimado" v={`${cfg.estimated_total_gb} GB`} />
        <Kv
          k="Flags"
          v={
            <div className="flex flex-wrap gap-1">
              {Object.entries(cfg.flags || {}).map(([k, v]) =>
                v === false ? null : (
                  <Badge key={k} tone="indigo">
                    {k}
                    {typeof v !== "boolean" ? `=${v}` : ""}
                  </Badge>
                )
              )}
            </div>
          }
        />
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500">Razonamiento</div>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
          {cfg.rationale.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Kv({ k, v }) {
  return (
    <>
      <div className="text-slate-500">{k}</div>
      <div className="text-slate-200">{v}</div>
    </>
  );
}
