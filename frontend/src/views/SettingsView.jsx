import { useEffect, useState } from "react";
import { api, humanizeError } from "../api";
import { PageHeader, Card, Stat, Badge, Button, Input, Field } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { useT } from "../i18n/index.jsx";
import { LanguageSelector } from "../i18n/LanguageSelector.jsx";

export default function SettingsView() {
  const t = useT();
  const [hw, setHw] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.hardware().then(setHw).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeader title={t("settings.header.title")} subtitle={t("settings.header.subtitle")} />
      <div className="grid gap-6 p-8 md:grid-cols-2">
        <Card title={t("settings.appearance.title")} className="md:col-span-2">
          <Field label={t("settings.language.label")} hint={t("settings.language.hint")}>
            <LanguageSelector />
          </Field>
        </Card>

        <Card title={t("settings.backend.title")}>
          <dl className="text-sm">
            <Row k={t("settings.backend.apiBase")} v="http://localhost:7777" />
            <Row k={t("settings.backend.db")} v="backend/data/inferbench.sqlite" />
            <Row k={t("settings.backend.frontendDev")} v="http://localhost:5173" />
          </dl>
        </Card>

        <Card title={t("settings.hardware.title")}>
          {error && <p className="text-rose-300">{error}</p>}
          {hw && (
            <div className="grid grid-cols-2 gap-4">
              <Stat label={t("settings.hardware.cpu")} value={hw.cpu.name} />
              <Stat
                label={t("settings.hardware.ram")}
                value={`${hw.ram_gb} GB`}
                hint={t("settings.hardware.ramFree", { gb: hw.ram_available_gb })}
              />
              <Stat
                label={t("settings.hardware.gpu")}
                value={hw.gpus[0]?.name || "—"}
                hint={
                  hw.gpus[0]
                    ? t("settings.hardware.vram", { gb: hw.gpus[0].vram_gb })
                    : t("settings.hardware.cpuOnly")
                }
                tone="accent"
              />
              <Stat
                label={t("settings.hardware.os")}
                value={hw.os}
                hint={hw.os_version}
              />
            </div>
          )}
        </Card>

        <Card title={t("settings.gpus.title")} className="md:col-span-2">
          {!hw?.gpus?.length && <p className="text-slate-500">{t("settings.gpus.none")}</p>}
          <ul className="space-y-2">
            {hw?.gpus?.map((g, i) => (
              <li
                key={i}
                className="flex items-center justify-between rounded border border-slate-800 px-3 py-2"
              >
                <div>
                  <div className="font-medium">{g.name}</div>
                  <div className="text-xs text-slate-500">
                    {t("settings.gpus.driver", { vendor: g.vendor, driver: g.driver || "?" })}
                  </div>
                </div>
                <Badge tone="indigo">{g.vram_gb} GB</Badge>
              </li>
            ))}
          </ul>
        </Card>

        <ApiKeysCard />
      </div>
    </>
  );
}

const PROVIDERS = [
  { id: "openai", label: "OpenAI", ph: "sk-…" },
  { id: "anthropic", label: "Anthropic", ph: "sk-ant-…" },
  { id: "openrouter", label: "OpenRouter", ph: "sk-or-…" },
  { id: "nvidia", label: "NVIDIA NIM", ph: "nvapi-…" },
];

function ApiKeysCard() {
  const t = useT();
  const toast = useToast();
  const [saved, setSaved] = useState({});
  const [inputs, setInputs] = useState({});

  const refresh = () => api.listKeys().then(setSaved).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const save = async (id) => {
    const key = (inputs[id] || "").trim();
    if (!key) return;
    try {
      await api.saveKey(id, key);
      setInputs((s) => ({ ...s, [id]: "" }));
      await refresh();
      toast.success(t("settings.apiKeys.saved", { provider: id }));
    } catch (e) {
      toast.error(humanizeError(e, t("settings.apiKeys.saveError")));
    }
  };

  const clear = async (id) => {
    try {
      await api.deleteKey(id);
      await refresh();
      toast.success(t("settings.apiKeys.deleted", { provider: id }));
    } catch (e) {
      toast.error(humanizeError(e, t("settings.apiKeys.deleteError")));
    }
  };

  return (
    <Card title={t("settings.apiKeys.title")} className="md:col-span-2">
      <p className="mb-3 text-xs text-slate-500">{t("settings.apiKeys.description")}</p>
      <div className="space-y-2">
        {PROVIDERS.map((p) => (
          <div key={p.id} className="flex items-center gap-2">
            <div className="w-28 shrink-0 text-sm text-slate-300">{p.label}</div>
            <Input
              type="password"
              autoComplete="off"
              placeholder={saved[p.id] ? t("settings.apiKeys.placeholderSaved") : p.ph}
              value={inputs[p.id] || ""}
              onChange={(e) => setInputs((s) => ({ ...s, [p.id]: e.target.value }))}
            />
            <Button size="sm" onClick={() => save(p.id)} disabled={!(inputs[p.id] || "").trim()}>
              {t("settings.apiKeys.save")}
            </Button>
            {saved[p.id] ? (
              <>
                <Badge tone="emerald">{t("settings.apiKeys.badgeSaved")}</Badge>
                <Button size="sm" variant="ghost" onClick={() => clear(p.id)}>
                  {t("settings.apiKeys.delete")}
                </Button>
              </>
            ) : (
              <Badge tone="slate">{t("settings.apiKeys.badgeNone")}</Badge>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Row({ k, v }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-2 py-1">
      <dt className="text-slate-500">{k}</dt>
      <dd className="truncate font-mono text-xs text-slate-200">{v}</dd>
    </div>
  );
}
