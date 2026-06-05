import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { en } from "./en.js";
import { es } from "./es.js";

// i18n ligero, sin dependencias. Inglés es la fuente de verdad; español se carga si el
// locale del sistema empieza por "es". El usuario puede forzar idioma desde Ajustes
// (persistido en localStorage). Claves anidadas con notación de punto: t("dashboard.summary").

const DICTS = { en, es };
export const SUPPORTED_LANGS = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
];

const STORAGE_KEY = "inferbench:lang";

// Detección: preferencia guardada > locale del sistema (navigator.language) > inglés.
export function detectLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && DICTS[saved]) return saved;
  } catch {
    /* localStorage no disponible */
  }
  const sys = (typeof navigator !== "undefined" && (navigator.language || navigator.languages?.[0])) || "en";
  return sys.toLowerCase().startsWith("es") ? "es" : "en";
}

function lookup(dict, key) {
  return key.split(".").reduce((acc, part) => (acc == null ? undefined : acc[part]), dict);
}

// Interpola {var} con values[var]. Soporta plural simple via "{count|singular|plural}".
function interpolate(str, vars) {
  if (!vars || typeof str !== "string") return str;
  return str.replace(/\{(\w+)(?:\|([^|}]*)\|([^}]*))?\}/g, (_, name, sing, plur) => {
    const v = vars[name];
    if (sing !== undefined) return Number(v) === 1 ? `${v} ${sing}` : `${v} ${plur}`;
    return v == null ? "" : String(v);
  });
}

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(detectLang);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const t = useCallback(
    (key, vars) => {
      const hit = lookup(DICTS[lang], key);
      const fallback = hit === undefined ? lookup(en, key) : hit;
      return interpolate(fallback === undefined ? key : fallback, vars);
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within <I18nProvider>");
  return ctx;
}

// Atajo: const t = useT();
export function useT() {
  return useI18n().t;
}
