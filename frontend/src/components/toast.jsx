// Sistema de notificaciones (toasts) global. Provee `useToast()` a todas las vistas.
//
//   const toast = useToast();
//   toast.success("Run eliminada");
//   toast.error("No se pudo conectar con el backend");
//   toast("Mensaje neutro", { title: "Info", ttl: 5000 });
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { CheckCircle2, AlertTriangle, Info, X } from "lucide-react";

const ToastCtx = createContext(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

const TONES = {
  success: { icon: CheckCircle2, border: "border-emerald-700/50", accent: "text-emerald-300" },
  error: { icon: AlertTriangle, border: "border-rose-700/50", accent: "text-rose-300" },
  info: { icon: Info, border: "border-indigo-700/50", accent: "text-indigo-300" },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message, opts = {}) => {
      const id = ++idRef.current;
      const tone = TONES[opts.tone] ? opts.tone : "info";
      const ttl = opts.ttl ?? (tone === "error" ? 6000 : 3500);
      setToasts((prev) => [...prev, { id, message, tone, title: opts.title }]);
      if (ttl > 0) setTimeout(() => dismiss(id), ttl);
      return id;
    },
    [dismiss]
  );

  const toast = useMemo(() => {
    const fn = (message, opts) => push(message, opts);
    fn.success = (message, opts) => push(message, { ...opts, tone: "success" });
    fn.error = (message, opts) => push(message, { ...opts, tone: "error" });
    fn.info = (message, opts) => push(message, { ...opts, tone: "info" });
    return fn;
  }, [push]);

  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => {
          const tone = TONES[t.tone] || TONES.info;
          const Icon = tone.icon;
          return (
            <div
              key={t.id}
              role="status"
              aria-live="polite"
              className={`toast-in pointer-events-auto flex items-start gap-2.5 rounded-lg border ${tone.border} bg-slate-900/95 px-3 py-2.5 shadow-lg shadow-black/40 backdrop-blur`}
            >
              <Icon size={16} className={`mt-0.5 shrink-0 ${tone.accent}`} />
              <div className="min-w-0 flex-1">
                {t.title && (
                  <div className="text-xs font-semibold text-slate-200">{t.title}</div>
                )}
                <div className="break-words text-xs text-slate-400">{t.message}</div>
              </div>
              <button
                onClick={() => dismiss(t.id)}
                aria-label="Cerrar notificación"
                className="shrink-0 rounded text-slate-500 transition hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
              >
                <X size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}
