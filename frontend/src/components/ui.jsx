// Primitivas de UI compartidas — consistencia visual entre vistas.

export function PageHeader({ title, subtitle, actions }) {
  return (
    <header className="flex items-end justify-between border-b border-slate-800 px-8 py-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, className = "", actions }) {
  return (
    <section
      className={`rounded-lg border border-slate-800 bg-slate-900/30 ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          {title && (
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              {title}
            </h2>
          )}
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = "default" }) {
  const tones = {
    default: "text-slate-100",
    accent: "text-indigo-300",
    success: "text-emerald-300",
    warn: "text-amber-300",
    danger: "text-rose-300",
  };
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Button({ children, variant = "primary", className = "", ...rest }) {
  const styles = {
    primary:
      "bg-indigo-500 hover:bg-indigo-400 text-white shadow-sm shadow-indigo-900/40",
    ghost:
      "bg-transparent border border-slate-700 hover:border-slate-500 text-slate-200",
    danger: "bg-rose-600 hover:bg-rose-500 text-white",
    success: "bg-emerald-600 hover:bg-emerald-500 text-white",
  };
  return (
    <button
      className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Badge({ children, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-800/60 text-slate-300 border-slate-700",
    indigo: "bg-indigo-900/40 text-indigo-300 border-indigo-700/40",
    emerald: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
    amber: "bg-amber-900/40 text-amber-300 border-amber-700/40",
    rose: "bg-rose-900/40 text-rose-300 border-rose-700/40",
    purple: "bg-purple-900/40 text-purple-300 border-purple-700/40",
  };
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="block text-xs uppercase tracking-wider text-slate-500">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </label>
  );
}

export function Input(props) {
  return (
    <input
      {...props}
      className={`w-full rounded-md border border-slate-700 bg-slate-900/40 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-indigo-400 ${
        props.className || ""
      }`}
    />
  );
}

export function Select({ children, ...props }) {
  return (
    <select
      {...props}
      className={`w-full rounded-md border border-slate-700 bg-slate-900/40 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-indigo-400 ${
        props.className || ""
      }`}
    >
      {children}
    </select>
  );
}

export function Spinner() {
  return (
    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
  );
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
      ok: "GPU",
      moe: "MoE offload",
      partial: "GPU+RAM",
      cpu: "Solo CPU",
      fail: "No cabe",
      api: "API",
    }[status] || status
  );
}
