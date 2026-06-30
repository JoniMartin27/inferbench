import { useEffect, useRef, useState } from "react";
import {
  Server,
  Play,
  Square,
  Send,
  Copy,
  Check,
  Sparkles,
  Plug,
  Loader2,
  CircleAlert,
  Image as ImageIcon,
  Dices,
  Download,
} from "lucide-react";
import { api, humanizeError, API_BASE } from "../api";
import {
  PageHeader,
  Card,
  Field,
  Select,
  Input,
  Badge,
  Button,
  Spinner,
  Empty,
} from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { useT } from "../i18n/index.jsx";

const QUANTS = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"];
const POLL_MS = 2000;
// Ruta esperada del binario empaquetado por PyInstaller (sidecar de Electron).
const STDIO_COMMAND = "inferbench-backend.exe";

// Presets de tamaño para generación de imagen (cuadrados; sd.cpp acepta cualquier múltiplo de 64).
const IMAGE_SIZES = [512, 768, 1024];

// La modalidad llega del catálogo del backend (campo `modality`); por defecto "text".
function modelModality(m) {
  return m?.modality || "text";
}
function isImageModel(m) {
  return modelModality(m) === "image";
}

const PHASE_TONE = {
  idle: "slate",
  downloading: "indigo",
  starting: "amber",
  ready: "emerald",
  error: "rose",
};

function phaseLabelKey(phase) {
  return `serve.status.phase.${phase || "idle"}`;
}

export default function ServeView() {
  const t = useT();
  const toast = useToast();

  // Selección de modelo
  const [source, setSource] = useState("catalog"); // catalog | recommend
  const [models, setModels] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [recLoading, setRecLoading] = useState(false);
  const [modelId, setModelId] = useState("");
  const [quant, setQuant] = useState(""); // "" → Auto (óptimo)
  const [context, setContext] = useState(""); // "" → Auto

  // Estado del slot servido (poll de /api/serve/status)
  const [status, setStatus] = useState({ served: false, phase: "idle" });
  const [loading, setLoading] = useState(false); // serveLoad en curso
  const [stopping, setStopping] = useState(false);
  const pollRef = useRef(null);
  const mountedRef = useRef(true);

  // Carga inicial del catálogo + estado actual
  useEffect(() => {
    mountedRef.current = true;
    api
      .listModels()
      .then((m) => {
        if (mountedRef.current) setModels(m);
      })
      .catch((e) => {
        if (mountedRef.current) toast.error(humanizeError(e, t("serve.config.modelsError")));
      });
    // Recoge el estado por si ya había un modelo servido al entrar en la vista.
    refreshStatus();
    return () => {
      mountedRef.current = false;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const refreshStatus = async () => {
    try {
      const s = await api.serveStatus();
      // El componente puede haberse desmontado (cambio de vista) mientras la petición
      // estaba en vuelo: evita setState fuera de ciclo de vida y, sobre todo, evita
      // re-arrancar el polling después de que el cleanup ya lo hubiera parado.
      if (!mountedRef.current) return null;
      setStatus(s);
      // Si el backend dice que ya está en fase terminal, dejamos de pollear.
      if (s.phase === "ready" || s.phase === "error" || s.phase === "idle") {
        stopPolling();
      } else if (!pollRef.current) {
        startPolling();
      }
      return s;
    } catch {
      // Backend caído: no spameamos toasts en el poll; mostramos estado offline.
      return null;
    }
  };

  const startPolling = () => {
    if (pollRef.current) return;
    pollRef.current = setInterval(refreshStatus, POLL_MS);
  };

  const loadRecommendations = async () => {
    setRecLoading(true);
    try {
      const rows = await api.getRecommendations(8);
      if (!mountedRef.current) return;
      setRecommendations(rows);
    } catch (e) {
      if (mountedRef.current) toast.error(humanizeError(e, t("serve.config.recommendError")));
    } finally {
      if (mountedRef.current) setRecLoading(false);
    }
  };

  const onSourceChange = (next) => {
    setSource(next);
    setModelId("");
    if (next === "recommend" && recommendations.length === 0) loadRecommendations();
  };

  // Modelo seleccionado (objeto completo del catálogo) → decide motor y tipo de card.
  const selectedModel = models.find((m) => m.id === modelId);
  const selectedIsImage = isImageModel(selectedModel);

  const serve = async () => {
    if (!modelId) {
      toast.error(t("serve.config.pickFirst"));
      return;
    }
    setLoading(true);
    try {
      const body = {
        model_id: modelId,
        // El motor se deriva de la modalidad: difusión vs LLM de texto.
        engine: selectedIsImage ? "stablediffusion" : "llamacpp",
        quant: quant || null,
        context: context ? Number(context) : null,
      };
      const s = await api.serveLoad(body);
      if (!mountedRef.current) return;
      setStatus(s);
      toast.info(t("serve.status.loadStarted"));
      startPolling();
    } catch (e) {
      if (mountedRef.current) toast.error(humanizeError(e, t("serve.status.loadError")));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  const stop = async () => {
    setStopping(true);
    try {
      const s = await api.serveUnload();
      stopPolling();
      if (!mountedRef.current) return;
      setStatus(s || { served: false, phase: "idle" });
      toast.success(t("serve.status.stopped"));
    } catch (e) {
      if (mountedRef.current) toast.error(humanizeError(e, t("serve.status.stopError")));
    } finally {
      if (mountedRef.current) setStopping(false);
    }
  };

  const phase = status?.phase || "idle";
  const isBusy = phase === "downloading" || phase === "starting";
  const isReady = phase === "ready";

  // Qué card mostrar: el backend reporta `modality` en el status; mientras carga el slot
  // (aún sin status definitivo) caemos a la modalidad del modelo elegido para el mismo id.
  const servedIsImage =
    status?.modality === "image" ||
    (status?.served &&
      status?.model_id &&
      status.model_id === modelId &&
      selectedIsImage);

  return (
    <>
      <PageHeader
        eyebrow={t("serve.header.eyebrow")}
        title={t("serve.header.title")}
        subtitle={t("serve.header.subtitle")}
        actions={
          (status?.served || isBusy || isReady) && (
            <Button variant="danger" onClick={stop} disabled={stopping}>
              {stopping ? <Spinner /> : <Square size={14} />} {t("serve.status.stop")}
            </Button>
          )
        }
      />

      <div className="grid gap-6 p-8 lg:grid-cols-2">
        {/* === Selección de modelo === */}
        <Card title={t("serve.config.title")} icon={Server} className="lg:col-span-2">
          <div className="space-y-4">
            <div className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/40 p-0.5 text-xs">
              {[
                { id: "catalog", label: t("serve.config.sourceCatalog") },
                { id: "recommend", label: t("serve.config.sourceRecommend") },
              ].map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onSourceChange(s.id)}
                  aria-pressed={source === s.id}
                  className={`rounded px-3 py-1.5 transition ${
                    source === s.id
                      ? "bg-indigo-500 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {s.id === "recommend" && <Sparkles size={11} className="-mt-0.5 mr-1 inline" />}
                  {s.label}
                </button>
              ))}
            </div>

            <div className="grid gap-4 md:grid-cols-4">
              <div className="md:col-span-2">
                <Field label={t("serve.config.model")}>
                  {source === "catalog" ? (
                    <Select value={modelId} onChange={(e) => setModelId(e.target.value)}>
                      <option value="">{t("serve.config.modelPlaceholder")}</option>
                      {/* Agrupados por modalidad: el selector único cubre LLMs de texto e imagen. */}
                      <optgroup label={t("serve.config.groupText")}>
                        {models
                          .filter((m) => !isImageModel(m))
                          .map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                              {m.params_b ? ` · ${m.params_b}B` : ""}
                            </option>
                          ))}
                      </optgroup>
                      {models.some(isImageModel) && (
                        <optgroup label={t("serve.config.groupImage")}>
                          {models.filter(isImageModel).map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </Select>
                  ) : recLoading ? (
                    <div className="flex items-center gap-2 py-2 text-sm text-slate-400">
                      <Spinner className="text-indigo-400" /> {t("serve.config.recommendLoading")}
                    </div>
                  ) : recommendations.length === 0 ? (
                    <p className="py-2 text-sm text-slate-500">{t("serve.config.recommendEmpty")}</p>
                  ) : (
                    <Select value={modelId} onChange={(e) => setModelId(e.target.value)}>
                      <option value="">{t("serve.config.modelPlaceholder")}</option>
                      {recommendations.map((r) => (
                        <option key={r.model.id} value={r.model.id}>
                          {r.model.name} · {r.config.quant || "?"} · {r.config.status}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              </div>

              {/* Quant/contexto solo aplican a LLMs de texto; los modelos de imagen
                  resuelven sus pesos y no usan KV-cache, así que se ocultan. */}
              {!selectedIsImage && (
                <>
                  <Field label={t("serve.config.quant")} hint={t("serve.config.quantHint")}>
                    <Select value={quant} onChange={(e) => setQuant(e.target.value)}>
                      <option value="">{t("serve.config.quantAuto")}</option>
                      {QUANTS.map((q) => (
                        <option key={q}>{q}</option>
                      ))}
                    </Select>
                  </Field>

                  <Field label={t("serve.config.context")} hint={t("serve.config.contextHint")}>
                    <Input
                      type="number"
                      value={context}
                      placeholder={t("serve.config.contextAuto")}
                      onChange={(e) => setContext(e.target.value)}
                    />
                  </Field>
                </>
              )}
            </div>

            <div>
              <Button onClick={serve} disabled={loading || isBusy || !modelId}>
                {loading || isBusy ? <Spinner /> : <Play size={14} />}{" "}
                {loading || isBusy ? t("serve.config.serving") : t("serve.config.serve")}
              </Button>
            </div>
          </div>
        </Card>

        {/* === Estado del slot === */}
        <StatusCard status={status} t={t} toast={toast} />

        {/* === Interacción: chat (texto) o generación (imagen) según la modalidad servida === */}
        {servedIsImage ? (
          <GenerateCard ready={isReady} t={t} toast={toast} />
        ) : (
          <ChatCard ready={isReady} t={t} toast={toast} />
        )}

        {/* === Conectar por MCP === */}
        <McpCard t={t} toast={toast} className="lg:col-span-2" />
      </div>
    </>
  );
}

function StatusCard({ status, t, toast }) {
  const phase = status?.phase || "idle";
  const idle = phase === "idle" || (!status?.served && phase !== "error");

  const copyEndpoint = async () => {
    try {
      await navigator.clipboard.writeText(status.endpoint || "");
      toast.success(t("serve.status.copied"));
    } catch {
      toast.error(t("serve.status.stopError"));
    }
  };

  return (
    <Card title={t("serve.status.title")} icon={Server}>
      {idle ? (
        <Empty icon={Server} title={t("serve.status.idle")} body={t("serve.status.idleHint")} />
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Badge tone={PHASE_TONE[phase] || "slate"}>
              {phase !== "ready" && phase !== "error" && phase !== "idle" && (
                <Loader2 size={11} className="animate-spin" />
              )}
              {phase === "error" && <CircleAlert size={11} />}
              {t(phaseLabelKey(phase))}
            </Badge>
            {status.progress != null && phase === "downloading" && (
              <span className="text-xs tabular-nums text-slate-400">
                {Math.min(100, Math.round(status.progress))}%
              </span>
            )}
          </div>

          {status.progress != null && phase === "downloading" && (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all"
                style={{ width: `${Math.min(100, Math.round(status.progress))}%` }}
              />
            </div>
          )}

          {status.message && (
            <p className={`text-sm ${phase === "error" ? "text-rose-300" : "text-slate-400"}`}>
              {status.message}
            </p>
          )}

          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Kv k={t("serve.status.model")} v={status.model_id || "—"} />
            <Kv k={t("serve.status.engine")} v={status.engine || "—"} />
            {/* Para imagen, quant/contexto no aplican: se muestran "—" honestamente. */}
            <Kv k={t("serve.status.quant")} v={status.quant || "—"} />
            <Kv
              k={t("serve.status.context")}
              v={status.context ? status.context.toLocaleString() : "—"}
            />
          </dl>

          {phase === "ready" && (
            <div className="rounded-lg border border-emerald-700/40 bg-emerald-950/20 p-3">
              <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
                <Check size={13} /> {t("serve.status.ready")}
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded bg-slate-950/60 px-2 py-1 font-mono text-xs text-slate-200">
                  {status.endpoint}
                </code>
                <Button size="sm" variant="ghost" onClick={copyEndpoint}>
                  <Copy size={12} /> {t("serve.status.copyEndpoint")}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function ChatCard({ ready, t, toast }) {
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState([]); // {role, content, tps?}
  const [sending, setSending] = useState(false);
  const scrollRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  // Evita setState tras desmontar (p.ej. si la respuesta llega después de cambiar de vista
  // o de que el slot servido pase a modalidad imagen y esta card se desmonte).
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const send = async () => {
    const text = prompt.trim();
    if (!text || sending) return;
    // id estable por mensaje — el índice del array no sirve de key porque "Clear" reinicia
    // la lista y un mensaje en vuelo podría llegar después, desalineando índices.
    setMessages((m) => [...m, { id: `u-${Date.now()}-${m.length}`, role: "user", content: text }]);
    setPrompt("");
    setSending(true);
    try {
      const res = await api.serveChat({ prompt: text, max_tokens: 512, temperature: 0.7 });
      if (!mountedRef.current) return;
      setMessages((m) => [
        ...m,
        { id: `a-${Date.now()}-${m.length}`, role: "assistant", content: res.content || "", tps: res.tps },
      ]);
    } catch (e) {
      if (mountedRef.current) toast.error(humanizeError(e, t("serve.chat.error")));
    } finally {
      if (mountedRef.current) setSending(false);
    }
  };

  return (
    <Card
      title={t("serve.chat.title")}
      icon={Send}
      actions={
        messages.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setMessages([])}>
            {t("serve.chat.clear")}
          </Button>
        )
      }
    >
      {!ready ? (
        <Empty icon={Send} title={t("serve.chat.empty")} body={t("serve.chat.notReady")} />
      ) : (
        <div className="flex h-80 flex-col">
          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
            {messages.length === 0 && (
              <p className="py-4 text-center text-sm text-slate-500">{t("serve.chat.placeholder")}</p>
            )}
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}
              >
                <div className="mb-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                  {m.role === "user" ? t("serve.chat.you") : t("serve.chat.model")}
                  {m.tps != null && (
                    <span className="ml-1 text-emerald-400">
                      {t("serve.chat.tps", { tps: Math.round(m.tps * 10) / 10 })}
                    </span>
                  )}
                </div>
                <div
                  className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                    m.role === "user"
                      ? "bg-indigo-500/15 text-indigo-100"
                      : "bg-slate-800/60 text-slate-200"
                  }`}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Spinner className="text-indigo-400" /> {t("serve.chat.sending")}
              </div>
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <Input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={t("serve.chat.placeholder")}
              disabled={sending}
            />
            <Button onClick={send} disabled={sending || !prompt.trim()}>
              {sending ? <Spinner /> : <Send size={14} />} {t("serve.chat.send")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function GenerateCard({ ready, t, toast }) {
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [steps, setSteps] = useState(20);
  const [size, setSize] = useState(512);
  const [seed, setSeed] = useState("-1");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null); // { image_b64, seed, elapsed_s, width, height }
  const mountedRef = useRef(true);

  // Evita setState tras desmontar (p.ej. si el slot servido vuelve a modalidad texto
  // mientras una generación de imagen sigue en curso).
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const randomizeSeed = () => {
    // Semilla aleatoria en cliente (32-bit) para poder reproducir un resultado concreto.
    setSeed(String(Math.floor(Math.random() * 2 ** 31)));
  };

  const generate = async () => {
    const text = prompt.trim();
    if (!text || generating) return;
    setGenerating(true);
    try {
      const parsedSeed = Number.parseInt(seed, 10);
      const res = await api.serveGenerate({
        prompt: text,
        negative_prompt: negative.trim(),
        steps: Number(steps),
        width: size,
        height: size,
        seed: Number.isFinite(parsedSeed) ? parsedSeed : -1,
      });
      if (!mountedRef.current) return;
      setResult(res);
      // El backend resuelve la semilla efectiva cuando se pidió -1; la reflejamos en el input.
      if (res?.seed != null) setSeed(String(res.seed));
    } catch (e) {
      if (mountedRef.current) toast.error(humanizeError(e, t("serve.generate.error")));
    } finally {
      if (mountedRef.current) setGenerating(false);
    }
  };

  const download = () => {
    if (!result?.image_b64) return;
    const a = document.createElement("a");
    a.href = result.image_b64;
    a.download = `inferbench-${result.seed ?? "image"}.png`;
    // Algunos navegadores solo disparan el click si el <a> está en el DOM.
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <Card
      title={t("serve.generate.title")}
      icon={ImageIcon}
      actions={
        result && (
          <Button size="sm" variant="ghost" onClick={download}>
            <Download size={12} /> {t("serve.generate.download")}
          </Button>
        )
      }
    >
      {!ready ? (
        <Empty
          icon={ImageIcon}
          title={t("serve.generate.empty")}
          body={t("serve.generate.notReady")}
        />
      ) : (
        <div className="space-y-4">
          <Field label={t("serve.generate.prompt")}>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  generate();
                }
              }}
              placeholder={t("serve.generate.promptPlaceholder")}
              rows={3}
              disabled={generating}
              className="w-full resize-none rounded-md border border-slate-700 bg-slate-950/50 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-indigo-400 focus:bg-slate-900/60"
            />
          </Field>

          <Field label={t("serve.generate.negative")}>
            <Input
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              placeholder={t("serve.generate.negativePlaceholder")}
              disabled={generating}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={`${t("serve.generate.steps")} · ${steps}`}>
              <input
                type="range"
                min={1}
                max={50}
                value={steps}
                onChange={(e) => setSteps(Number(e.target.value))}
                disabled={generating}
                className="w-full accent-indigo-500"
              />
            </Field>

            <Field label={t("serve.generate.size")}>
              <div className="flex gap-1 rounded-md border border-slate-700 bg-slate-900/40 p-0.5 text-xs">
                {IMAGE_SIZES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSize(s)}
                    disabled={generating}
                    aria-pressed={size === s}
                    className={`flex-1 rounded px-2 py-1.5 transition disabled:opacity-50 ${
                      size === s
                        ? "bg-indigo-500 text-white"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {s}²
                  </button>
                ))}
              </div>
            </Field>
          </div>

          <Field label={t("serve.generate.seed")}>
            <div className="flex gap-2">
              <Input
                type="number"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder={t("serve.generate.seedPlaceholder")}
                disabled={generating}
              />
              <Button
                variant="ghost"
                onClick={randomizeSeed}
                disabled={generating}
                title={t("serve.generate.seedRandom")}
                aria-label={t("serve.generate.seedRandom")}
              >
                <Dices size={14} />
              </Button>
            </div>
          </Field>

          <Button onClick={generate} disabled={generating || !prompt.trim()}>
            {generating ? <Spinner /> : <Sparkles size={14} />}{" "}
            {generating ? t("serve.generate.generating") : t("serve.generate.generate")}
          </Button>

          {/* Preview de la imagen generada (o placeholder mientras no hay resultado). */}
          <div className="relative flex min-h-[16rem] items-center justify-center overflow-hidden rounded-lg border border-slate-800 bg-slate-950/40">
            {generating ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Spinner className="text-indigo-400" /> {t("serve.generate.generating")}
              </div>
            ) : result?.image_b64 ? (
              <>
                <img
                  src={result.image_b64}
                  alt={prompt}
                  className="max-h-[28rem] w-full object-contain"
                />
                <div className="absolute bottom-2 right-2 flex gap-1">
                  {result.elapsed_s != null && (
                    <Badge tone="emerald">
                      {t("serve.generate.elapsed", {
                        s: Math.round(result.elapsed_s * 10) / 10,
                      })}
                    </Badge>
                  )}
                  {result.seed != null && (
                    <Badge tone="slate">
                      {t("serve.generate.seedTag", { seed: result.seed })}
                    </Badge>
                  )}
                </div>
              </>
            ) : (
              <p className="px-6 py-10 text-center text-xs text-slate-500">
                {t("serve.generate.placeholder")}
              </p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function McpCard({ t, toast, className = "" }) {
  const httpUrl = `${API_BASE}/mcp`;
  const stdioSnippet = JSON.stringify(
    {
      mcpServers: {
        inferbench: {
          command: STDIO_COMMAND,
          args: ["--mcp"],
        },
      },
    },
    null,
    2
  );

  return (
    <Card title={t("serve.mcp.title")} icon={Plug} className={className}>
      <p className="mb-4 text-xs text-slate-500">{t("serve.mcp.description")}</p>
      <div className="grid gap-4 md:grid-cols-2">
        <Snippet
          title={t("serve.mcp.stdioTitle")}
          hint={t("serve.mcp.stdioHint")}
          value={stdioSnippet}
          t={t}
          toast={toast}
        />
        <Snippet
          title={t("serve.mcp.httpTitle")}
          hint={t("serve.mcp.httpHint")}
          value={httpUrl}
          t={t}
          toast={toast}
        />
      </div>

      {/* Tools que el servidor MCP expone (incluye generate_image para modelos de imagen). */}
      <div className="mt-4">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {t("serve.mcp.toolsTitle")}
        </span>
        <ul className="mt-2 space-y-1.5">
          {[
            { id: "chat", icon: Send, label: t("serve.mcp.toolChat") },
            { id: "generate_image", icon: ImageIcon, label: t("serve.mcp.toolGenerateImage") },
            { id: "serve_status", icon: Server, label: t("serve.mcp.toolStatus") },
          ].map(({ id, icon: Icon, label }) => (
            <li key={id} className="flex items-center gap-2 text-[11px] text-slate-400">
              <Icon size={12} className="shrink-0 text-indigo-300" />
              <code className="font-mono">{label}</code>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function Snippet({ title, hint, value, t, toast }) {
  const [copied, setCopied] = useState(false);
  const resetRef = useRef(null);

  useEffect(() => () => clearTimeout(resetRef.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(t("serve.mcp.copied"));
      clearTimeout(resetRef.current);
      resetRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(t("serve.mcp.copyError"));
    }
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</span>
        <Button size="sm" variant="ghost" onClick={copy}>
          {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}{" "}
          {t("serve.mcp.copy")}
        </Button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-slate-950/60 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-300">
        {value}
      </pre>
      <p className="mt-2 text-[11px] text-slate-500">{hint}</p>
    </div>
  );
}

function Kv({ k, v }) {
  return (
    <>
      <div className="text-slate-500">{k}</div>
      <div className="truncate font-mono text-xs text-slate-200" title={v}>
        {v}
      </div>
    </>
  );
}
