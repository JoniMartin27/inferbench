// Grabador de la demo de InferBench. Es la traducción literal de docs/DEMO-GUION.md:
// si cambias una escena aquí, cambia el guion (y al revés).
//
// Conduce el frontend REAL de Vite (localhost:5173) contra el backend REAL de FastAPI
// (localhost:7777) con Playwright y graba un vídeo que después ffmpeg convierte en
// assets/inferbench-demo.gif. Nada está simulado: el hardware es el de la máquina, los
// runs del historial son benchmarks reales ya ejecutados (scripts/seed_demo_runs.py), el
// benchmark de la escena 3 corre de verdad contra llama-server y la imagen de la escena 5
// la genera stable-diffusion.cpp en ese momento.
//
// Se ejecuta desde un directorio de herramientas AISLADO para no meter Playwright en el
// package.json del repo. Como la resolución de imports de ESM parte del fichero, no del
// cwd, hay que COPIARLO al directorio de herramientas:
//   cp scripts/record-demo.mjs C:/tmp/pw-runner/ && cd C:/tmp/pw-runner && node record-demo.mjs
//
// Variables:
//   IB_OUT_DIR   destino del .webm            (por defecto C:/tmp/ib-rec)
//   IB_LANG      idioma de la UI grabada      (por defecto "en"; "es" saca el corte en castellano)
//   IB_FE        URL del frontend             (por defecto http://localhost:5173)
//   IB_API       URL del backend              (por defecto http://127.0.0.1:7777)
import { chromium } from "playwright";

const OUT_DIR = process.env.IB_OUT_DIR || "C:/tmp/ib-rec";
const FE = process.env.IB_FE || "http://localhost:5173";
const API = process.env.IB_API || "http://127.0.0.1:7777";
const LANG = process.env.IB_LANG || "en";
const W = 1280, H = 800;

// Etiquetas de navegación por idioma (App.jsx > NAV_GROUPS).
const NAV = {
  en: { dashboard: "Dashboard", models: "Models", benchmark: "Benchmark", serve: "Serve / MCP", history: "History" },
  es: { dashboard: "Panel", models: "Modelos", benchmark: "Benchmark", serve: "Serve / MCP", history: "Historial" },
};
// Prompts que se DESmarcan en la escena 3 para que el run entre en la escena.
const DROP_PROMPTS = {
  en: ["Reasoning", "Code", "Long context"],
  es: ["Razonamiento", "Código", "Contexto largo"],
};
const L = NAV[LANG] || NAV.en;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rx = (s) => new RegExp(s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"), "i");
const t0 = Date.now();
const mark = (msg) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${msg}`);

async function clickNav(page, label) {
  await page.locator("nav button", { hasText: rx(label) }).first().click();
  await sleep(600);
}

// El contenedor que scrollea es <main>; con el ratón parado en (0,0) la rueda movería la
// barra lateral, así que se scrollea por código y no con page.mouse.wheel.
async function scrollMain(page, top, smooth = true) {
  await page.evaluate(
    ([y, sm]) => {
      const m = document.querySelector("main");
      const opts = { top: y, behavior: sm ? "smooth" : "auto" };
      if (m && m.scrollHeight > m.clientHeight) m.scrollTo(opts);
      else window.scrollTo(opts);
    },
    [top, smooth]
  );
}

async function main() {
  const browser = await chromium.launch({ args: ["--force-color-profile=srgb"] });
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 1,
    recordVideo: { dir: OUT_DIR, size: { width: W, height: H } },
  });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));

  await page.addInitScript((lang) => {
    try { localStorage.setItem("inferbench:lang", lang); } catch {}
    try { localStorage.setItem("inferbench:lastView", "guide"); } catch {}
  }, LANG);

  await page.goto(FE, { waitUntil: "networkidle" });

  // ---- Puerta de pre-calentado: no se empieza hasta que la vista está POBLADA.
  // Sin esto se cuela el fotograma a medio cargar (backend en "checking", tarjetas vacías).
  await page.locator("nav").first().waitFor({ timeout: 30000 });
  await page.locator("main").getByText(/100%|\d+ \/ \d+/).first().waitFor({ timeout: 30000 }).catch(() => {});
  await sleep(900);

  // ---- Escena 0: Guide — el flujo de un vistazo (2,5 s) ----
  mark("escena 0 · Guide");
  await sleep(2400);

  // ---- Escena 1: Dashboard — tu máquina, tus modelos (4,0 s) ----
  mark("escena 1 · Dashboard");
  await clickNav(page, L.dashboard);
  await sleep(1200);
  await scrollMain(page, 430);
  await sleep(1400);
  await scrollMain(page, 0);
  await sleep(400);

  // ---- Escena 2: Models — la config óptima para TU equipo (6,0 s) ----
  mark("escena 2 · Models");
  await clickNav(page, L.models);
  await sleep(900);
  const search = page.getByPlaceholder(/Search|Buscar/i).first();
  await search.click();
  await search.type("llama-3.2", { delay: 80 });
  await sleep(1000);
  await page.locator("tbody tr button", { hasText: /Optimize|Optimizar/i }).first().click({ timeout: 8000 });
  await page.getByText(/OPTIMIZATION TECHNIQUES|TÉCNICAS DE OPTIMIZACIÓN/i).first().waitFor({ timeout: 15000 }).catch(() => {});
  await sleep(900);
  await scrollMain(page, 230); // encuadra el panel de configuración óptima entero
  await sleep(2000);

  // ---- Escena 3: Benchmark — medir, no adivinar (12,0 s) ----
  mark("escena 3 · Benchmark");
  await clickNav(page, L.benchmark);
  await sleep(1500); // deja leer la tabla ENGINES FOR THIS MODEL

  const modelSelect = page.locator("select").filter({ has: page.locator('option[value="llama-3.2-1b"]') }).first();
  await modelSelect.selectOption("llama-3.2-1b");
  await sleep(900);

  // Quant explícito. El optimizador propone Q8_0 y en esta máquina eso significa ctx 131k:
  // la KV se va a RAM y el run cae a 4,6 tok/s y 246 s — no cabe en la escena, y además es
  // justo lo que la escena 4 enseña con datos.
  //
  // Hay que INSISTIR: al cambiar de modelo la vista recalcula la compatibilidad de cada
  // quant en segundo plano y, cuando la respuesta llega, repuebla el desplegable y lo
  // devuelve al quant recomendado. Si seleccionas antes de eso tu elección se pierde en
  // silencio y el run acaba corriendo con OTRO quant (pasó: arrancó Q8_0 con -c 131072).
  const quantSelect = page.locator("select").filter({ has: page.locator('option[value="Q4_K_M"]') }).first();
  await quantSelect.waitFor({ timeout: 20000 });
  let stable = 0;
  for (let i = 0; i < 14 && stable < 3; i++) {
    if ((await quantSelect.inputValue().catch(() => "")) === "Q4_K_M") {
      stable++;
    } else {
      await quantSelect.selectOption("Q4_K_M").catch(() => {});
      stable = 0;
    }
    await sleep(600);
  }
  if ((await quantSelect.inputValue().catch(() => "")) !== "Q4_K_M") {
    throw new Error("no pude fijar el quant a Q4_K_M");
  }
  mark("   quant fijado a Q4_K_M");

  // Solo Summary + Knowledge: el run entero cabe en la escena (~10 s medidos).
  for (const label of DROP_PROMPTS[LANG] || DROP_PROMPTS.en) {
    const b = page.locator('button[aria-pressed="true"]', { hasText: rx(label) }).first();
    await b.click({ timeout: 2500 }).catch(() => {});
    await sleep(120);
  }
  await sleep(500);

  // Anclado arriba: el panel EXECUTION (cabecera + TTFT/tok-s + log negro) tiene que
  // quedar entero en cuadro mientras el SSE va llenándolo.
  await scrollMain(page, 0, false);
  await page.getByRole("button", { name: /Launch benchmark|Lanzar benchmark/i }).first().click();
  mark("   benchmark lanzado");

  // Primero hay que ver ARRANCAR el run: React tarda un instante en cambiar el botón por
  // "Stop", y sin esta espera el bucle de abajo daba el run por terminado en el mismo
  // fotograma en que se lanzaba, y la escena se quedaba sin benchmark.
  await page.getByRole("button", { name: /^Stop$|^Detener$/i }).first().waitFor({ timeout: 20000 });

  // Se re-ancla el scroll mientras corre: el layout crece y si no la cabecera del panel se
  // sale de cuadro. El final se detecta por el botón: la reaparición de "Launch benchmark"
  // ES el fin del run. (Contar filas de tabla no vale: la tabla de motores del modelo ya
  // tiene 7 y el bucle salía antes de tiempo, dejando la escena sin fila de resultados.)
  const launchAgain = page.getByRole("button", { name: /Launch benchmark|Lanzar benchmark/i }).first();
  for (let i = 0; i < 60; i++) {
    await scrollMain(page, 0, false);
    if (await launchAgain.isVisible().catch(() => false)) break;
    await sleep(700);
  }
  mark("   benchmark terminado");

  // sd-turbo se carga AQUÍ, en cuanto el run termina y el motor suelta la VRAM: MEDIDO,
  // con el modelo de imagen residente el benchmark pasa de 9,2 s a 18,6 s y de ~250 a
  // ~154 tok/s, porque en una 3070 sd.cpp se lleva ~3,9 GB de los 8. Cargarlo antes
  // arruinaba la escena principal; cargarlo ahora lo deja listo para la escena 5.
  fetch(`${API}/api/serve/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: "sd-turbo", engine: "stablediffusion" }),
  }).catch((e) => console.error("serve/load falló:", e.message));

  await sleep(900);
  // Baja a la tarjeta de RESULTS. Un scrollTop fijo NO vale: la de configuración es larga
  // (tabla de motores + sweep + compresión + prompts + juez) y 620 px se quedaba en los
  // presets de compresión, dejando la escena sin resultados. Se busca la tarjeta.
  await page.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) return;
    const title = [...main.querySelectorAll("*")].find(
      (e) => e.children.length === 0 && /^(Results|Resultados)$/i.test((e.textContent || "").trim())
    );
    const card = title?.closest("section") || title?.parentElement;
    if (!card) return;
    const top = card.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - 24;
    main.scrollTo({ top, behavior: "smooth" });
  });
  await sleep(3000);

  // ---- Escena 4: History — compara y decide (5,0 s) ----
  mark("escena 4 · History");
  await clickNav(page, L.history);
  await sleep(1100);
  for (const note of ["demo Q8_0", "demo Q4_K_M"]) {
    const row = page.locator("li", { hasText: note }).first();
    await row.locator('input[type="checkbox"]').check({ timeout: 8000 });
    await sleep(400);
  }
  await sleep(200);
  await page.getByRole("button", { name: /Compare|Comparar/i }).first().click();
  await sleep(1400);
  await scrollMain(page, 520); // encuadra las gráficas por prompt (incluida QUALITY)
  await sleep(2400);

  // ---- Escena 5: Serve / MCP — y luego, sírvelo (5,5 s) ----
  mark("escena 5 · Serve / MCP");
  await clickNav(page, L.serve);
  // La carga disparada al terminar el benchmark debería estar lista; si no, se espera
  // fuera de cámara antes de entrar en la vista (no se filma un spinner de carga).
  for (let i = 0; i < 60; i++) {
    const st = await fetch(`${API}/api/serve/status`).then((r) => r.json()).catch(() => ({}));
    if (st.phase === "ready") break;
    if (i === 0) mark("   esperando a sd-turbo…");
    await sleep(1000);
  }
  await sleep(1500);
  const promptBox = page.locator("textarea").first();
  await promptBox.click();
  await promptBox.fill("a cozy reading nook by a rainy window, warm lamp light, watercolor");
  await sleep(700);
  await page.getByRole("button", { name: /^Generate$|^Generar$/i }).first().click();
  await page.locator('img[src^="data:image"], img[src^="blob:"]').first().waitFor({ timeout: 60000 }).catch(() => {});
  mark("   imagen generada");
  await sleep(1500);
  await scrollMain(page, 700); // hasta "Connect over MCP"
  await sleep(2400);

  mark("fin");
  await sleep(400);
  await context.close(); // vuelca el vídeo
  const video = page.video();
  const path = video ? await video.path() : null;
  await browser.close();
  if (consoleErrors.length) console.error("CONSOLE_ERRORS=" + JSON.stringify(consoleErrors, null, 1));
  console.log("VIDEO_PATH=" + path);
}

main().catch((e) => { console.error("REC_ERROR", e); process.exit(1); });
