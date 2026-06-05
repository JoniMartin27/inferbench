import { SUPPORTED_LANGS, useI18n } from "./index.jsx";

// Selector de idioma compacto. Inglés por defecto; refleja/cambia la preferencia persistida.
export function LanguageSelector({ className = "" }) {
  const { lang, setLang } = useI18n();
  return (
    <select
      value={lang}
      onChange={(e) => setLang(e.target.value)}
      className={`rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-200 outline-none focus:border-indigo-500 ${className}`}
    >
      {SUPPORTED_LANGS.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  );
}
