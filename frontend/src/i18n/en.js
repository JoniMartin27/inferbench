// English — source of truth. Keep keys in sync with es.js.
// Per-view namespaces live in ./views/*.js (each exports { en, es }); wired in below.
import { guide } from "./views/guide.js";
import { dashboard } from "./views/dashboard.js";
import { engines } from "./views/engines.js";
import { models } from "./views/models.js";
import { benchmark } from "./views/benchmark.js";
import { history } from "./views/history.js";
import { settings } from "./views/settings.js";

export const en = {
  guide: guide.en,
  dashboard: dashboard.en,
  engines: engines.en,
  models: models.en,
  benchmark: benchmark.en,
  history: history.en,
  settings: settings.en,
  common: {
    retry: "Retry",
    loading: "Loading…",
    cancel: "Cancel",
    close: "Close",
    save: "Save",
    delete: "Delete",
    refresh: "Refresh",
    search: "Search",
    error: "Error",
    none: "None",
    back: "Back",
    closeNotification: "Close notification",
  },
  compat: {
    label: {
      ok: "100% GPU",
      moe: "MoE offload",
      partial: "GPU + CPU",
      cpu: "CPU only",
      disk: "disk mmap",
      fail: "Won't fit",
      api: "API",
    },
    desc: {
      ok: "Whole model in VRAM. Maximum speed.",
      moe: "Expert layers on CPU, gating + attention on GPU. Decent tps since only a few params/token are active.",
      partial: "Some layers on GPU, the rest on CPU. Works but slow (typically 1-10 tok/s).",
      cpu: "Everything on CPU. Very slow, only if there's no GPU.",
      disk: "Model paged from disk via mmap. Works but VERY slow (0.1-2 tok/s on NVMe).",
      fail: "Won't fit even with the most aggressive quantization or disk paging.",
      api: "Cloud — depends on the provider.",
    },
  },
  app: {
    nav: {
      start: "Start",
      workflow: "Workflow",
      data: "Data",
      guide: "Guide",
      dashboard: "Dashboard",
      models: "Models",
      engines: "Engines",
      benchmark: "Benchmark",
      history: "History",
      settings: "Settings",
    },
    benchmarkRunning: "Benchmark running",
    viewLoadError: "This view could not be loaded.",
    backendStatus: "backend",
    docker: "Docker {version}",
    noDocker: "no Docker",
    dockerUnavailable: "Docker unavailable",
    dockerHint: "llama.cpp and Ollama (native) work without Docker",
    installDocker: "Install Docker",
  },
};
