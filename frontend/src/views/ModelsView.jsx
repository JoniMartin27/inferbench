import { useEffect, useState } from "react";
import { Zap, RefreshCw, FolderOpen, HardDrive, Cloud, Play, Filter, Sparkles } from "lucide-react";
import { api, humanizeError } from "../api";
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
import { useToast } from "../components/toast.jsx";
import { useT } from "../i18n/index.jsx";

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
  const [filterMode, setFilterMode] = useState("compat"); // all | compat | full_gpu
  const [familyFilter, setFamilyFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const toast = useToast();
  const t = useT();

  const refreshLocal = async () => {
    setLocalLoading(true);
    try {
      const [m, d] = await Promise.all([api.listLocalModels(), api.listSearchDirs()]);
      setLocalModels(m);
      setSearchDirs(d);
      setExtraInput((d.extra || []).join("\n"));
    } catch (e) {
      toast.error(humanizeError(e, t("models.toast.scanLocalError")));
    } finally {
      setLocalLoading(false);
    }
  };

  const saveDirs = async () => {
    const dirs = extraInput.split("\n").map((s) => s.trim()).filter(Boolean);
    try {
      await api.saveSearchDirs(dirs);
      await refreshLocal();
      toast.success(t("models.toast.dirsSaved"));
    } catch (e) {
      toast.error(humanizeError(e, t("models.toast.dirsSaveError")));
    }
  };

  useEffect(() => {
    api.listEngines().then(setEngines).catch(() => {});
    refreshLocal();
  }, []);

  useEffect(() => {
    setLoading(true);
    // Debounce: al teclear en contexto/MoE (inputs numéricos) no disparamos una
    // petición por pulsación; esperamos 250ms a que el usuario pare.
    const t = setTimeout(() => {
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
    }, 250);
    return () => clearTimeout(t);
  }, [engine, quant, kvCache, contextLen, moeOffload]);

  const isApi = engines.find((e) => e.meta.id === engine)?.meta.type === "api";
  const [optimal, setOptimal] = useState(null); // { modelId, config } | null
  const [optimizing, setOptimizing] = useState(null);

  const [optimizeError, setOptimizeError] = useState(null);

  const optimize = async (modelId) => {
    setOptimizing(modelId);
    setOptimal(null);
    setOptimizeError(null);
    try {
      const res = await api.optimize(engine, modelId);
      // Backend nuevo devuelve {config, techniques}; viejo devolvía OptimalConfig directo
      const cfg = res.config || res;
      const techniques = res.techniques || [];
      setOptimal({ modelId, config: cfg, techniques });
    } catch (e) {
      setOptimizeError(t("models.optimize.error", { model: modelId, reason: humanizeError(e) }));
    } finally {
      setOptimizing(null);
    }
  };

  return (
    <>
      <PageHeader
        title={t("models.header.title")}
        subtitle={t("models.header.subtitle")}
        actions={
          <Button variant="ghost" onClick={refreshLocal}>
            <RefreshCw size={14} /> {t("models.header.rescan")}
          </Button>
        }
      />

      <div className="flex gap-2 px-8 pt-4">
        <TabButton active={tab === "catalog"} onClick={() => setTab("catalog")} icon={Cloud}>
          {t("models.tabs.catalog", { count: rows.length })}
        </TabButton>
        <TabButton active={tab === "local"} onClick={() => setTab("local")} icon={HardDrive}>
          {t("models.tabs.local", { count: localModels.length })}
        </TabButton>
      </div>

      {tab === "local" && (
        <div className="space-y-6 p-8">
          <Card
            title={t("models.local.cardTitle", { count: localModels.length })}
            actions={
              <button
                onClick={() => setShowDirs((s) => !s)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200"
              >
                <FolderOpen size={12} /> {t("models.local.scannedDirs")}
              </button>
            }
          >
            {showDirs && (
              <div className="mb-4 space-y-3 border-b border-slate-800 pb-4">
                <div>
                  <div className="mb-1 text-xs uppercase text-slate-500">{t("models.local.knownDirs")}</div>
                  <ul className="space-y-0.5 font-mono text-xs text-slate-400">
                    {searchDirs.known.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="mb-1 text-xs uppercase text-slate-500">{t("models.local.extraDirs")}</div>
                  <textarea
                    rows={4}
                    value={extraInput}
                    onChange={(e) => setExtraInput(e.target.value)}
                    placeholder="C:/MisModelos&#10;D:/llm-cache"
                    className="w-full rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 font-mono text-xs text-slate-200 outline-none focus:border-indigo-400"
                  />
                  <div className="mt-2 flex gap-2">
                    <Button onClick={saveDirs}>{t("models.local.save")}</Button>
                    <span className="self-center text-xs text-slate-500">
                      {t("models.local.savedTo", { file: searchDirs.extra_dirs_file })}
                    </span>
                  </div>
                </div>
              </div>
            )}
            {localLoading && <p className="text-sm text-slate-500">{t("models.local.scanning")}</p>}
            {!localLoading && localModels.length === 0 && (
              <p className="text-sm text-slate-500">
                {t("models.local.empty")}
              </p>
            )}
            {localModels.length > 0 && (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                    <tr className="border-b border-slate-800">
                      <th className="py-2 pr-3">{t("models.local.col.name")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.arch")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.quant")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.params")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.size")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.layers")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.ctx")}</th>
                      <th className="py-2 pr-3">{t("models.local.col.origin")}</th>
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
                            title={t("models.local.benchmarkTitle")}
                          >
                            <Play size={12} /> {t("models.local.benchmark")}
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
        <Card title={t("models.config.title")}>
          <div className="grid gap-4 md:grid-cols-5">
            <Field label={t("models.config.engine")}>
              <Select value={engine} onChange={(e) => setEngine(e.target.value)}>
                {engines.map((e) => (
                  <option key={e.meta.id} value={e.meta.id}>
                    {e.meta.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("models.config.quant")}>
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
            <Field label={t("models.config.kvCache")}>
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
            <Field label={t("models.config.context")}>
              <Input
                type="number"
                value={contextLen}
                onChange={(e) => setContextLen(Number(e.target.value) || 0)}
                disabled={isApi}
              />
            </Field>
            <Field label={t("models.config.moeOffload")} hint={t("models.config.moeOffloadHint")}>
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

        {optimizeError && (
          <div className="mb-4 rounded-lg border border-red-700/50 bg-red-950/30 px-4 py-3 text-sm text-red-200">
            {optimizeError}
          </div>
        )}

        {optimal && (
          <Card
            title={t("models.optimal.title", { model: optimal.modelId })}
            actions={
              <div className="flex items-center gap-3">
                {optimal.config.feasible && (
                  <button
                    onClick={() => onNavigate?.("benchmark", { config: optimal.config })}
                    className="inline-flex items-center gap-1 rounded border border-indigo-500/60 px-2 py-1 text-xs font-medium text-indigo-200 hover:border-indigo-400 hover:bg-indigo-500/10"
                    title={t("models.optimal.benchmarkTitle")}
                  >
                    <Zap size={12} /> {t("models.optimal.benchmark")}
                  </button>
                )}
                <button
                  onClick={() => setOptimal(null)}
                  className="text-xs text-slate-500 hover:text-slate-300"
                >
                  {t("models.optimal.close")}
                </button>
              </div>
            }
          >
            <OptimalDetail cfg={optimal.config} techniques={optimal.techniques} />
          </Card>
        )}

        <CatalogTable
          rows={rows}
          loading={loading}
          filterMode={filterMode}
          setFilterMode={setFilterMode}
          familyFilter={familyFilter}
          setFamilyFilter={setFamilyFilter}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          optimize={optimize}
          optimizing={optimizing}
        />
        {false && (
        <Card title={t("models.catalog.titleLegacy", { count: rows.length })}>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="py-2 pr-3">{t("models.catalog.col.model")}</th>
                  <th className="py-2 pr-3">{t("models.catalog.col.type")}</th>
                  <th className="py-2 pr-3">{t("models.catalog.col.params")}</th>
                  <th className="py-2 pr-3">{t("models.catalog.col.size")}</th>
                  <th className="py-2 pr-3">{t("models.catalog.col.total")}</th>
                  <th className="py-2 pr-3">{t("models.catalog.col.maxCtx")}</th>
                  <th className="py-2 pr-3">{t("models.catalog.col.compat")}</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-slate-500">
                      {t("models.catalog.calculating")}
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
                          <Badge tone="purple">{t("models.catalog.moeActive", { active: model.active_b })}</Badge>
                        ) : (
                          <Badge>{t("models.catalog.dense")}</Badge>
                        )}
                      </td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{model.params_b}B</td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{model_size_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{estimated_total_gb} GB</td>
                      <td className="py-2 pr-3 tabular-nums text-slate-300">{max_context.toLocaleString()}</td>
                      <td className="py-2 pr-3">
                        <Badge tone={compatTone(status)}>{t(compatLabel(status))}</Badge>
                      </td>
                      <td className="py-2 pr-3">
                        <button
                          onClick={() => optimize(model.id)}
                          className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-indigo-400 hover:text-indigo-200"
                          title={t("models.catalog.optimizeTitle")}
                        >
                          {optimizing === model.id ? <Spinner /> : <Zap size={12} />} {t("models.catalog.optimize")}
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
        )}
      </div>
      )}
    </>
  );
}

function CatalogTable({ rows, loading, filterMode, setFilterMode, familyFilter, setFamilyFilter, searchQuery, setSearchQuery, optimize, optimizing }) {
  const t = useT();
  const STATUS_RANK = { ok: 0, moe: 1, partial: 2, cpu: 3, fail: 4, api: 5 };
  const families = Array.from(new Set(rows.map((r) => r.model.family))).sort();

  const filtered = rows
    .filter((r) => {
      if (filterMode === "full_gpu" && r.status !== "ok") return false;
      if (filterMode === "compat" && r.status === "fail") return false;
      if (familyFilter !== "all" && r.model.family !== familyFilter) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return (
          r.model.name.toLowerCase().includes(q) ||
          r.model.id.toLowerCase().includes(q) ||
          r.model.tags.some((t) => t.toLowerCase().includes(q))
        );
      }
      return true;
    })
    .sort((a, b) => {
      const ra = STATUS_RANK[a.status] ?? 99;
      const rb = STATUS_RANK[b.status] ?? 99;
      if (ra !== rb) return ra - rb;
      return a.model.params_b - b.model.params_b;
    });

  const stats = rows.reduce(
    (acc, r) => {
      acc[r.status] = (acc[r.status] || 0) + 1;
      return acc;
    },
    {}
  );

  return (
    <Card
      title={t("models.catalog.title", { shown: filtered.length, total: rows.length })}
      actions={
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <Badge tone="emerald">{t("models.catalog.statGpu", { count: stats.ok || 0 })}</Badge>
          <Badge tone="purple">{t("models.catalog.statMoe", { count: stats.moe || 0 })}</Badge>
          <Badge tone="amber">{t("models.catalog.statMixed", { count: stats.partial || 0 })}</Badge>
          <Badge tone="rose">{t("models.catalog.statFail", { count: stats.fail || 0 })}</Badge>
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-3 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-1 rounded border border-slate-700 bg-slate-900/40 p-0.5 text-xs">
          {[
            { id: "full_gpu", label: t("models.catalog.filter.fullGpu"), title: t("models.catalog.filter.fullGpuTitle") },
            { id: "compat", label: t("models.catalog.filter.compat"), title: t("models.catalog.filter.compatTitle") },
            { id: "all", label: t("models.catalog.filter.all"), title: t("models.catalog.filter.allTitle") },
          ].map((m) => (
            <button
              key={m.id}
              onClick={() => setFilterMode(m.id)}
              title={m.title}
              className={`rounded px-2 py-1 transition ${
                filterMode === m.id
                  ? "bg-indigo-500 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <select
          value={familyFilter}
          onChange={(e) => setFamilyFilter(e.target.value)}
          className="rounded border border-slate-700 bg-slate-900/40 px-2 py-1 text-xs"
        >
          <option value="all">{t("models.catalog.allFamilies")}</option>
          {families.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder={t("models.catalog.searchPlaceholder")}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 min-w-[200px] rounded border border-slate-700 bg-slate-900/40 px-3 py-1 text-xs"
        />
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-slate-500">
            <tr className="border-b border-slate-800">
              <th className="py-2 pr-3">{t("models.catalog.col.model")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.family")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.type")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.params")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.size")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.total")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.maxCtx")}</th>
              <th className="py-2 pr-3">{t("models.catalog.col.compat")}</th>
              <th className="py-2 pr-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={9} className="py-6 text-center text-slate-500">
                  {t("models.catalog.calculating")}
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="py-6 text-center text-slate-500">
                  {t("models.catalog.noResults")}
                </td>
              </tr>
            )}
            {!loading &&
              filtered.map(({ model, status, model_size_gb, estimated_total_gb, max_context }) => (
                <tr key={model.id} className="border-b border-slate-900 hover:bg-slate-900/40">
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{model.name}</span>
                      {model.tags.includes("popular") && (
                        <Sparkles size={12} className="text-amber-300" title={t("models.catalog.popular")} />
                      )}
                    </div>
                    <div className="text-xs text-slate-500">{model.id}</div>
                    {model.tags.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {model.tags.filter((t) => t !== "popular").map((t) => (
                          <span key={t} className="rounded bg-slate-800/60 px-1.5 py-0.5 text-[10px] text-slate-400">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-300 capitalize">{model.family}</td>
                  <td className="py-2 pr-3">
                    {model.is_moe ? (
                      <Badge tone="purple">{t("models.catalog.moeActive", { active: model.active_b })}</Badge>
                    ) : (
                      <Badge>{t("models.catalog.dense")}</Badge>
                    )}
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-slate-300">{model.params_b}B</td>
                  <td className="py-2 pr-3 tabular-nums text-slate-300">{model_size_gb} GB</td>
                  <td className="py-2 pr-3 tabular-nums text-slate-300">{estimated_total_gb} GB</td>
                  <td className="py-2 pr-3 tabular-nums text-slate-300">{max_context.toLocaleString()}</td>
                  <td className="py-2 pr-3">
                    <Badge tone={compatTone(status)}>{t(compatLabel(status))}</Badge>
                  </td>
                  <td className="py-2 pr-3">
                    <button
                      onClick={() => optimize(model.id)}
                      className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-indigo-400 hover:text-indigo-200"
                      title={t("models.catalog.optimizeTitle")}
                    >
                      {optimizing === model.id ? <Spinner /> : <Zap size={12} />} {t("models.catalog.optimize")}
                    </button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Card>
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

function OptimalDetail({ cfg, techniques = [] }) {
  const t = useT();
  if (!cfg.feasible) {
    return (
      <div>
        <Badge tone="rose">{t("models.optimal.notFeasible")}</Badge>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-400">
          {cfg.rationale.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Kv k={t("models.optimal.kv.status")} v={<Badge tone={compatTone(cfg.status)}>{t(compatLabel(cfg.status))}</Badge>} />
          <Kv k={t("models.optimal.kv.quant")} v={cfg.quant || "—"} />
          <Kv k={t("models.optimal.kv.kvCache")} v={cfg.kv_cache || "—"} />
          <Kv k={t("models.optimal.kv.context")} v={cfg.context_len?.toLocaleString() || "—"} />
          {cfg.moe_offload != null && <Kv k={t("models.optimal.kv.moeOffload")} v={`--n-cpu-moe ${cfg.moe_offload}`} />}
          {cfg.flags?.ngl != null && cfg.flags.ngl !== 999 && (
            <Kv k={t("models.optimal.kv.gpuLayers")} v={t("models.optimal.kv.gpuLayersValue", { ngl: cfg.flags.ngl })} />
          )}
          <Kv k={t("models.optimal.kv.totalEstimated")} v={`${cfg.estimated_total_gb} GB`} />
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500">{t("models.optimal.activeFlags")}</div>
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(cfg.flags || {})
              .filter(([k, v]) => v !== false && v != null && k !== "ngl_mode")
              .map(([k, v]) => (
                <Badge key={k} tone="indigo">
                  {k}
                  {typeof v !== "boolean" ? `=${v}` : ""}
                </Badge>
              ))}
          </div>
        </div>
      </div>

      {techniques.length > 0 && (
        <div className="rounded-lg border border-emerald-700/40 bg-emerald-950/20 p-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
            {t("models.optimal.techniques", { count: techniques.length })}
          </div>
          <ul className="space-y-1.5 text-sm text-slate-200">
            {techniques.map((t, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                <span>{t}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="rounded border border-slate-800 p-3 text-sm">
        <summary className="cursor-pointer text-xs uppercase tracking-wider text-slate-500">
          {t("models.optimal.rationale")}
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-400">
          {cfg.rationale.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </details>
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
