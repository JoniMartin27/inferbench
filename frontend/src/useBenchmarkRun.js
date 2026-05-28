// Hook que mantiene el estado de un benchmark en curso a nivel de App,
// para que sobreviva al cambio de pestaña. La suscripción SSE no se cierra
// al desmontar BenchmarkView porque vive aquí, en App.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeBenchmark } from "./api";

const MAX_EVENTS = 400;

export function useBenchmarkRun() {
  const [running, setRunning] = useState(null); // run_id o null
  const [events, setEvents] = useState([]);
  const [results, setResults] = useState([]);
  const [progress, setProgress] = useState({});
  const [lastConfig, setLastConfig] = useState(null);
  const unsubRef = useRef(null);

  const log = useCallback((level, text) => {
    setEvents((arr) => [...arr.slice(-MAX_EVENTS), { type: "log", level, text }]);
  }, []);

  const subscribe = useCallback((runId) => {
    unsubRef.current?.();
    setRunning(runId); // mostrar "running" inmediatamente; el evento "done" lo limpia
    unsubRef.current = subscribeBenchmark(runId, (evt) => {
      setEvents((arr) => [...arr.slice(-MAX_EVENTS), evt]);

      if (evt.type === "engine.install") {
        setProgress({ kind: "engine.install", ...evt });
      } else if (evt.type === "model.download") {
        setProgress({ kind: "model.download", ...evt });
      } else if (evt.type === "engine.ready") {
        setProgress({ kind: "engine.ready" });
      } else if (evt.type === "tokens") {
        setProgress({
          kind: "tokens",
          current: evt.current,
          target: evt.target,
          tps: evt.tps_current,
        });
      } else if (evt.phase === "ttft") {
        setProgress((p) => ({ ...p, kind: "tokens", ttft: evt.ttft_ms }));
      }

      if (evt.type === "result") setResults((r) => [...r, evt.result]);
      if (evt.type === "done") {
        setRunning(null);
        unsubRef.current?.();
        unsubRef.current = null;
      }
    });
  }, []);

  const start = useCallback(
    async (config) => {
      // Reset estado para una nueva corrida
      setEvents([]);
      setResults([]);
      setProgress({});
      setLastConfig(config);
      const { run_id } = await api.startBenchmark(config);
      subscribe(run_id); // ya setea running
      return run_id;
    },
    [subscribe]
  );

  const stop = useCallback(async () => {
    if (!running) return;
    await api.stopBenchmark(running);
  }, [running]);

  const clear = useCallback(() => {
    setEvents([]);
    setResults([]);
    setProgress({});
  }, []);

  // Cleanup definitivo al desmontar el hook (i.e. cerrar la app)
  useEffect(() => () => unsubRef.current?.(), []);

  return {
    running,
    events,
    results,
    progress,
    lastConfig,
    start,
    stop,
    clear,
    subscribe, // expuesto por si sweep necesita re-suscribirse a una sub-corrida
    log, // para empujar mensajes informativos (ej. desde sweep)
  };
}
