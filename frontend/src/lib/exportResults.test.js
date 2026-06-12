// Tests del exportador de resultados (CSV/JSON). Funciones puras → runner nativo de Node
// (`node --test`), sin dependencias extra. Se ejecuta en CI con `npm run test:unit`.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  csvEscape,
  runToRows,
  buildCsv,
  buildJson,
  exportFilename,
  kvLabel,
} from "./exportResults.js";

const RUN = {
  run: {
    id: "r1",
    engine: "llamacpp",
    // Forma REAL que guarda el benchmark: kvCacheK/kvCacheV por separado (no un único
    // `kvCache`). El balanced preset usa K=V=q8_0.
    opts_json: JSON.stringify({
      model: "Qwen2.5-7B",
      quant: "Q4_K_M",
      engine_opts: { kvCacheK: "q8_0", kvCacheV: "q8_0", contextLen: 8192 },
    }),
  },
  results: [
    {
      prompt_id: "code",
      ttft_ms: 120,
      ttft_std: 3,
      tps: 75.2,
      tps_std: 1.1,
      prefill_tps: 900,
      n_samples: 3,
      vram_gb: 6.1,
      quality: 0.8,
      ctx_used: 512,
      error: null,
    },
    {
      prompt_id: "chat, with comma",
      ttft_ms: 90,
      tps: 80,
      vram_gb: 6.0,
      quality: 1,
      error: 'boom "quoted"\nsecond line',
    },
  ],
};

test("csvEscape only quotes when needed", () => {
  assert.equal(csvEscape("plain"), "plain");
  assert.equal(csvEscape("a,b"), '"a,b"');
  assert.equal(csvEscape('he "said"'), '"he ""said"""');
  assert.equal(csvEscape("line\nbreak"), '"line\nbreak"');
  assert.equal(csvEscape(null), "");
  assert.equal(csvEscape(undefined), "");
  assert.equal(csvEscape(0), "0");
});

test("kvLabel deriva la KV del par kvCacheK/kvCacheV real del benchmark", () => {
  // K=V se colapsa a un único valor
  assert.equal(kvLabel({ engine_opts: { kvCacheK: "q8_0", kvCacheV: "q8_0" } }), "q8_0");
  // K≠V (preset "compressed") se muestra como K/V
  assert.equal(kvLabel({ engine_opts: { kvCacheK: "q8_0", kvCacheV: "iq4_nl" } }), "q8_0/iq4_nl");
  // Solo uno presente: se reutiliza para el otro
  assert.equal(kvLabel({ engine_opts: { kvCacheK: "f16" } }), "f16");
  // Fallback legacy a kvCache / kv_cache
  assert.equal(kvLabel({ engine_opts: { kvCache: "q4_0" } }), "q4_0");
  assert.equal(kvLabel({ kv_cache: "f16" }), "f16");
  // Sin datos → cadena vacía (no "undefined")
  assert.equal(kvLabel({}), "");
  assert.equal(kvLabel({ engine_opts: {} }), "");
});

test("runToRows desnormaliza las opciones del run en cada fila", () => {
  const rows = runToRows(RUN);
  assert.equal(rows.length, 2);
  for (const row of rows) {
    assert.equal(row.run_id, "r1");
    assert.equal(row.engine, "llamacpp");
    assert.equal(row.model, "Qwen2.5-7B");
    assert.equal(row.quant, "Q4_K_M");
    assert.equal(row.kv_cache, "q8_0");
    assert.equal(row.context_len, 8192);
  }
  assert.equal(rows[0].prompt_id, "code");
  assert.equal(rows[0].tps, 75.2);
});

test("buildCsv produce cabecera + una fila por prompt, con escaping", () => {
  const csv = buildCsv(RUN);
  const lines = csv.split("\n");
  // cabecera + 2 filas. La 2ª fila tiene un salto de línea entrecomillado dentro del campo
  // error, así que contamos por contenido, no por número de líneas crudas.
  assert.ok(lines[0].startsWith("run_id,engine,model,quant,kv_cache,context_len,prompt_id"));
  assert.ok(csv.includes('"chat, with comma"'));
  assert.ok(csv.includes('"boom ""quoted""\nsecond line"'));
});

test("buildCsv acepta un array de runs (comparación) y los aplana todos", () => {
  const csv = buildCsv([RUN, RUN]);
  const dataRows = csv.split("\n").length; // header + filas (los saltos internos van entrecomillados)
  // 1 header + 2 prompts x 2 runs = pero el campo error trae un salto interno por run.
  // Comprobamos por presencia: ambos runs aparecen con su id.
  const occurrences = (csv.match(/(^|,)r1(,|$)/gm) || []).length;
  assert.equal(occurrences, 4); // run_id "r1" en las 4 filas de datos
  assert.ok(dataRows >= 5);
});

test("buildCsv con resultados vacíos devuelve solo la cabecera", () => {
  const csv = buildCsv({ run: { id: "x", engine: "e", opts_json: "{}" }, results: [] });
  assert.ok(!csv.includes("\n"));
  assert.ok(csv.startsWith("run_id,"));
});

test("opts_json corrupto no lanza (cae a objeto vacío)", () => {
  const rows = runToRows({ run: { id: "z", engine: "e", opts_json: "{not json" }, results: [{ prompt_id: "p" }] });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].model, "");
  assert.equal(rows[0].quant, "");
});

test("buildJson serializa tal cual", () => {
  const parsed = JSON.parse(buildJson(RUN));
  assert.equal(parsed.run.id, "r1");
  assert.equal(parsed.results.length, 2);
});

test("exportFilename es seguro y lleva extensión", () => {
  const name = exportFilename("inferbench-r1", "csv");
  assert.match(name, /^inferbench-r1-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.csv$/);
  // caracteres problemáticos se sustituyen
  assert.match(exportFilename("a/b c:d", "json"), /^a_b_c_d-.*\.json$/);
});
