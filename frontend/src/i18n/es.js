// Español — traducción. Mantener claves en sync con en.js (inglés es la fuente).
// Los namespaces por vista viven en ./views/*.js (cada uno exporta { en, es }).
import { guide } from "./views/guide.js";
import { dashboard } from "./views/dashboard.js";
import { engines } from "./views/engines.js";
import { models } from "./views/models.js";
import { benchmark } from "./views/benchmark.js";
import { history } from "./views/history.js";
import { settings } from "./views/settings.js";

export const es = {
  guide: guide.es,
  dashboard: dashboard.es,
  engines: engines.es,
  models: models.es,
  benchmark: benchmark.es,
  history: history.es,
  settings: settings.es,
  common: {
    retry: "Reintentar",
    loading: "Cargando…",
    cancel: "Cancelar",
    close: "Cerrar",
    save: "Guardar",
    delete: "Eliminar",
    refresh: "Actualizar",
    search: "Buscar",
    error: "Error",
    none: "Ninguno",
    back: "Volver",
    closeNotification: "Cerrar notificación",
  },
  compat: {
    label: {
      ok: "100% GPU",
      moe: "MoE offload",
      partial: "GPU + CPU",
      cpu: "Solo CPU",
      disk: "mmap disco",
      fail: "No cabe",
      api: "API",
    },
    desc: {
      ok: "Modelo entero en VRAM. Velocidad máxima.",
      moe: "Capas expert en CPU, gating+atención en GPU. Tps decente porque solo activos pocos params/token.",
      partial: "Algunas capas en GPU, resto en CPU. Funciona pero lento (1-10 tok/s típico).",
      cpu: "Todo en CPU. Muy lento, solo si no hay GPU.",
      disk: "Modelo paged desde disco vía mmap. Funciona pero MUY lento (0.1-2 tok/s con NVMe).",
      fail: "No cabe ni con la cuantización más agresiva, ni con paginación de disco.",
      api: "Cloud — depende del proveedor.",
    },
  },
  app: {
    nav: {
      start: "Empezar",
      workflow: "Workflow",
      data: "Datos",
      guide: "Guía",
      dashboard: "Dashboard",
      models: "Modelos",
      engines: "Motores",
      benchmark: "Benchmark",
      history: "Historial",
      settings: "Ajustes",
    },
    benchmarkRunning: "Benchmark en curso",
    viewLoadError: "No se pudo cargar esta vista.",
    backendStatus: "backend",
    docker: "Docker {version}",
    noDocker: "sin Docker",
    dockerUnavailable: "Docker no disponible",
    dockerHint: "llama.cpp y Ollama (nativo) funcionan sin Docker",
    installDocker: "Instalar Docker",
  },
};
