// Primitivas de UI compartidas — consistencia visual entre vistas.
import { Loader2 } from "lucide-react";

export function PageHeader({ title, subtitle, actions, eyebrow }) {
  return (
    <header className="sticky top-0 z-10 border-b border-slate-800/80 bg-slate-950/80 px-8 py-5 backdrop-blur">
      <div className="flex items-end justify-between gap-4">
        <div>
          {eyebrow && (
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-400">
              {eyebrow}
            </div>
          )}
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function Card({ title, children, className = "", actions, variant = "default", icon: Icon }) {
  const variants = {
    default: "border-slate-800 bg-slate-900/30",
    accent: "border-indigo-700/40 bg-gradient-to-br from-indigo-950/40 to-slate-900/30",
    success: "border-emerald-700/40 bg-gradient-to-br from-emerald-950/30 to-slate-900/30",
    warn: "border-amber-700/40 bg-gradient-to-br from-amber-950/30 to-slate-900/30",
    flat: "border-slate-800/60 bg-slate-900/20",
  };
  return (
    <section
      className={`rounded-xl border shadow-sm shadow-black/20 transition ${variants[variant]} ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-800/60 px-5 py-3">
          {title && (
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              {Icon && <Icon size={13} className="text-indigo-300" />}
              {title}
            </h2>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = "default", icon: Icon }) {
  const tones = {
    default: "text-slate-100",
    accent: "text-indigo-300",
    success: "text-emerald-300",
    warn: "text-amber-300",
    danger: "text-rose-300",
    purple: "text-purple-300",
  };
  const iconBg = {
    default: "bg-slate-800/60 text-slate-300",
    accent: "bg-indigo-500/15 text-indigo-300",
    success: "bg-emerald-500/15 text-emerald-300",
    warn: "bg-amber-500/15 text-amber-300",
    danger: "bg-rose-500/15 text-rose-300",
    purple: "bg-purple-500/15 text-purple-300",
  };
  return (
    <div className="flex items-start gap-3">
      {Icon && (
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${iconBg[tone]}`}>
          <Icon size={16} />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
          {label}
        </div>
        <div className={`mt-0.5 truncate text-2xl font-semibold ${tones[tone]}`}>{value}</div>
        {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
      </div>
    </div>
  );
}

export function Button({ children, variant = "primary", size = "md", className = "", ...rest }) {
  const styles = {
    primary:
      "bg-indigo-500 hover:bg-indigo-400 text-white shadow-sm shadow-indigo-900/40 active:scale-[0.98]",
    ghost:
      "bg-transparent border border-slate-700 hover:border-slate-500 text-slate-200 active:scale-[0.98]",
    danger: "bg-rose-600 hover:bg-rose-500 text-white active:scale-[0.98]",
    success: "bg-emerald-600 hover:bg-emerald-500 text-white active:scale-[0.98]",
    soft: "bg-slate-800/60 hover:bg-slate-700/60 text-slate-200 border border-slate-700/40",
  };
  const sizes = {
    sm: "px-2.5 py-1 text-xs",
    md: "px-3 py-1.5 text-sm",
    lg: "px-4 py-2 text-sm",
  };
  return (
    <button
      className={`inline-flex items-center gap-1.5 rounded-md font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${sizes[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Badge({ children, tone = "slate", className = "" }) {
  const tones = {
    slate: "bg-slate-800/60 text-slate-300 border-slate-700/60",
    indigo: "bg-indigo-500/10 text-indigo-300 border-indigo-700/40",
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-700/40",
    amber: "bg-amber-500/10 text-amber-300 border-amber-700/40",
    rose: "bg-rose-500/10 text-rose-300 border-rose-700/40",
    purple: "bg-purple-500/10 text-purple-300 border-purple-700/40",
    cyan: "bg-cyan-500/10 text-cyan-300 border-cyan-700/40",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Field({ label, hint, children, error }) {
  return (
    <label className="block">
      <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </span>
      <div className="mt-1.5">{children}</div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1 text-xs text-rose-400">{error}</p>}
    </label>
  );
}

export function Input(props) {
  return (
    <input
      {...props}
      className={`w-full rounded-md border border-slate-700 bg-slate-950/50 px-3 py-1.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-indigo-400 focus:bg-slate-900/60 ${
        props.className || ""
      }`}
    />
  );
}

export function Select({ children, ...props }) {
  return (
    <select
      {...props}
      className={`w-full cursor-pointer rounded-md border border-slate-700 bg-slate-950/50 px-3 py-1.5 text-sm text-slate-100 outline-none transition focus:border-indigo-400 ${
        props.className || ""
      }`}
    >
      {children}
    </select>
  );
}

export function Spinner({ className = "" }) {
  return <Loader2 size={14} className={`animate-spin ${className}`} />;
}

export function Skeleton({ className = "" }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-gradient-to-r from-slate-800/50 via-slate-800/30 to-slate-800/50 ${className}`}
    />
  );
}

export function Empty({ icon: Icon, title, body, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {Icon && (
        <div className="rounded-full border border-slate-800 bg-slate-900/40 p-3 text-slate-500">
          <Icon size={22} />
        </div>
      )}
      <div className="mt-1 text-sm font-medium text-slate-200">{title}</div>
      {body && <p className="max-w-md text-xs text-slate-500">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Divider({ className = "" }) {
  return <div className={`h-px w-full bg-slate-800/60 ${className}`} />;
}

export function compatTone(status) {
  return (
    {
      ok: "emerald",
      moe: "purple",
      partial: "amber",
      cpu: "amber",
      fail: "rose",
      api: "indigo",
    }[status] || "slate"
  );
}

export function compatLabel(status) {
  return (
    {
      ok: "100% GPU",
      moe: "MoE offload",
      partial: "GPU + CPU",
      cpu: "Solo CPU",
      fail: "No cabe",
      api: "API",
    }[status] || status
  );
}

export function compatDescription(status) {
  return (
    {
      ok: "Modelo entero en VRAM. Velocidad máxima.",
      moe: "Capas expert en CPU, gating+atención en GPU. Tps decente porque solo activos pocos params/token.",
      partial: "Algunas capas en GPU, resto en CPU. Funciona pero lento (1-10 tok/s típico).",
      cpu: "Todo en CPU. Muy lento, solo si no hay GPU.",
      fail: "No cabe ni con la cuantización más agresiva.",
      api: "Cloud — depende del proveedor.",
    }[status] || ""
  );
}

export function compatIcon(status) {
  // dot-style indicator
  const colors = {
    ok: "bg-emerald-400",
    moe: "bg-purple-400",
    partial: "bg-amber-400",
    cpu: "bg-amber-400",
    fail: "bg-rose-400",
    api: "bg-indigo-400",
  };
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${colors[status] || "bg-slate-500"}`} />;
}
