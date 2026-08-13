import { useCallback, useEffect, useRef, useState } from "react";
import { Ruler, Play, Square, Loader2, CircleAlert } from "lucide-react";
import { api, humanizeError } from "../api";
import { PageHeader, Card, Button, Badge, Empty, Spinner } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { useT } from "../i18n/index.jsx";

// Umbrales para colorear "coincide con el original". No son un veredicto de calidad
// —eso lo decide el número— sino una ayuda de lectura: por debajo del 90% el modelo elige
// otra palabra una de cada diez veces, que ya no es "la misma configuración un poco peor".
const SAME_TOP_BIEN = 95;
const SAME_TOP_REGULAR = 90;

function toneSameTop(pct) {
  if (pct == null) return "slate";
  if (pct >= SAME_TOP_BIEN) return "emerald";
  if (pct >= SAME_TOP_REGULAR) return "amber";
  return "rose";
}

function num(v, dec = 2, sufijo = "") {
  return v == null ? "—" : `${v.toFixed(dec)}${sufijo}`;
}

export default function QualityView() {
  const t = useT();
  const toast = useToast();
  const [candidatos, setCandidatos] = useState(null);
  const [resultados, setResultados] = useState([]);
  const [job, setJob] = useState(null);
  const [progreso, setProgreso] = useState(null);
  const esRef = useRef(null);

  const cargar = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([api.qualityCandidates(), api.qualityResults()]);
      setCandidatos(c);
      setResultados(r);
    } catch (e) {
      setCandidatos([]);
      toast.error(humanizeError(e, t("quality.toast.loadError")));
    }
  }, [toast, t]);

  useEffect(() => {
    cargar();
    // Cerrar el stream al desmontar: si no, sigue recibiendo eventos de un componente
    // que ya no existe y React avisa de un setState sobre algo desmontado.
    return () => esRef.current?.close();
  }, [cargar]);

  async function medir(modelo) {
    try {
      const { job_id } = await api.qualityMeasure({ modelo, ngl: 0 });
      setJob({ id: job_id, modelo });
      setProgreso({ quant: null, chunk: 0, medidas: [] });

      const es = new EventSource(api.qualityStreamUrl(job_id));
      esRef.current = es;
      es.onmessage = (ev) => {
        const e = JSON.parse(ev.data);
        if (e.type === "measuring") setProgreso((p) => ({ ...p, quant: e.quant, chunk: 0 }));
        else if (e.type === "progress") setProgreso((p) => ({ ...p, chunk: e.chunk }));
        else if (e.type === "measured")
          setProgreso((p) => ({ ...p, medidas: [...(p?.medidas || []), e] }));
        else if (e.type === "error") toast.error(e.detail || t("quality.toast.measureError"));
        else if (e.type === "done") {
          es.close();
          setJob(null);
          setProgreso(null);
          cargar();
          toast.success(t("quality.toast.done"));
        }
      };
      es.onerror = () => {
        es.close();
        setJob(null);
        setProgreso(null);
        toast.error(t("quality.toast.streamLost"));
      };
    } catch (e) {
      toast.error(humanizeError(e, t("quality.toast.measureError")));
    }
  }

  async function cancelar() {
    if (!job) return;
    try {
      await api.qualityCancel(job.id);
    } catch {
      /* si ya terminó, el stream lo cierra igual */
    }
    esRef.current?.close();
    setJob(null);
    setProgreso(null);
  }

  const porModelo = Object.fromEntries(resultados.map((r) => [r.modelo, r]));

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("quality.eyebrow")}
        title={t("quality.title")}
        subtitle={t("quality.subtitle")}
      />

      <Card variant="flat" icon={Ruler} title={t("quality.explain.title")}>
        <p className="text-sm text-slate-400">{t("quality.explain.body")}</p>
      </Card>

      {candidatos === null && <Spinner />}

      {candidatos?.length === 0 && (
        <Empty
          icon={Ruler}
          title={t("quality.empty.title")}
          body={t("quality.empty.body")}
        />
      )}

      {candidatos?.map((c) => {
        const res = porModelo[c.modelo];
        const midiendoEste = job?.modelo === c.modelo;
        return (
          <Card
            key={c.modelo}
            title={c.modelo}
            actions={
              midiendoEste ? (
                <Button variant="ghost" size="sm" onClick={cancelar}>
                  <Square size={13} /> {t("quality.cancel")}
                </Button>
              ) : (
                <Button size="sm" onClick={() => medir(c.modelo)} disabled={!!job}>
                  <Play size={13} /> {res ? t("quality.remeasure") : t("quality.measure")}
                </Button>
              )
            }
          >
            <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[11px]">
              <Badge tone="slate">{t("quality.quants", { n: c.quants.length })}</Badge>
              <Badge tone="indigo">{t("quality.reference", { q: c.referencia })}</Badge>
              <Badge tone="slate">{c.tamano_total_gb} GB</Badge>
            </div>

            {midiendoEste && (
              <div className="mb-3 flex items-center gap-2 text-sm text-amber-300">
                <Loader2 size={14} className="animate-spin" />
                {t("quality.measuring", {
                  quant: progreso?.quant || "…",
                  chunk: progreso?.chunk || 0,
                })}
              </div>
            )}

            {res ? (
              <TablaDanio res={res} t={t} />
            ) : (
              !midiendoEste && (
                <p className="text-sm text-slate-500">{t("quality.notMeasured")}</p>
              )
            )}
          </Card>
        );
      })}
    </div>
  );
}

function TablaDanio({ res, t }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="pb-2 pr-3">{t("quality.col.quant")}</th>
            <th className="pb-2 pr-3">{t("quality.col.ppl")}</th>
            <th className="pb-2 pr-3">{t("quality.col.vsRef")}</th>
            <th className="pb-2 pr-3">{t("quality.col.kld")}</th>
            <th className="pb-2 pr-3">{t("quality.col.sameTop")}</th>
          </tr>
        </thead>
        <tbody>
          {res.medidas.map((m) => (
            <tr key={m.quant} className="border-t border-slate-800/70">
              <td className="py-2 pr-3">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium">{m.quant}</span>
                  {m.es_referencia && (
                    <Badge tone="indigo">{t("quality.refBadge")}</Badge>
                  )}
                </div>
              </td>
              <td className="py-2 pr-3 tabular-nums">{num(m.ppl, 3)}</td>
              <td className="py-2 pr-3 tabular-nums">
                {/* La referencia no se compara consigo misma: un 1,00 haría creer que está
                    medido. Se deja en blanco a propósito. */}
                {m.es_referencia
                  ? "—"
                  : m.ppl_ratio == null
                    ? "—"
                    : `+${((m.ppl_ratio - 1) * 100).toFixed(2)} %`}
              </td>
              <td className="py-2 pr-3 tabular-nums">{num(m.kld_media, 4)}</td>
              <td className="py-2 pr-3">
                {m.es_referencia ? (
                  "—"
                ) : (
                  <Badge tone={toneSameTop(m.same_top_pct)}>
                    {num(m.same_top_pct, 2, " %")}
                  </Badge>
                )}
              </td>
            </tr>
          ))}
          {res.medidas.some((m) => m.error) && (
            <tr>
              <td colSpan={5} className="pt-3 text-xs text-rose-300">
                <CircleAlert size={12} className="mr-1 inline" />
                {res.medidas.find((m) => m.error)?.error}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="mt-3 text-[11px] text-slate-500">
        {t("quality.footnote", { corpus: res.corpus, ctx: res.ctx })}
      </p>
    </div>
  );
}
