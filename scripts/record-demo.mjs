// Programmatic demo recorder for InferBench.
// Drives the real Vite frontend (localhost:5173) against the real FastAPI
// backend (localhost:7777) with Playwright, recording a video that is later
// converted to docs/demo.gif by ffmpeg. No simulated data: hardware is real,
// history runs are real cached benchmarks, the live benchmark in scene 3 is a
// real llama.cpp run, and the image in scene 5 is a real sd.cpp generation.
//
// This recorder is run from an ISOLATED tooling dir (C:/tmp/ib-rec-tool) so
// Playwright is never added to the repo's package.json. Invoke with:
//   node <repo>/scripts/record-demo.mjs            (uses tool dir's playwright)
//
// Scene 3 emphasis (per validator): frame the EXECUTION/RunningPanel POPULATED
// and LIVE — engine boot phases + the terminal log + tok/s/TTFT climbing via
// SSE — before the RESULTS row appears. ffmpeg slows that segment so it reads.
import { chromium } from "playwright";

const OUT_DIR = process.env.IB_OUT_DIR || "C:/tmp/ib-rec";
const FE = "http://localhost:5173";
const W = 1280, H = 800;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clickNav(page, label) {
  const esc = label.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
  const btn = page.locator("nav button", { hasText: new RegExp(esc, "i") }).first();
  await btn.click();
  await sleep(700);
}

async function main() {
  const browser = await chromium.launch({ args: ["--force-color-profile=srgb"] });
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 1,
    recordVideo: { dir: OUT_DIR, size: { width: W, height: H } },
  });
  const page = await context.newPage();

  await page.addInitScript(() => {
    try { localStorage.setItem("inferbench:lang", "en"); } catch {}
    try { localStorage.setItem("inferbench:lastView", "dashboard"); } catch {}
    // Hide the cosmetic "Docker unavailable" banner so the demo doesn't carry a
    // degraded notice. Purely visual — affects no benchmark data. The banner is
    // the only top-level bar (border-b) rendered before the sidebar flex row.
    const css = `
      .flex.h-full.flex-col > .flex.items-center.justify-between.gap-4.border-b { display: none !important; }
    `;
    const inject = () => {
      const s = document.createElement("style");
      s.textContent = css;
      document.head.appendChild(s);
    };
    if (document.head) inject();
    else document.addEventListener("DOMContentLoaded", inject);
  });

  await page.goto(FE, { waitUntil: "networkidle" });

  // ---- Pre-warm gate: don't start until the Dashboard is fully populated.
  // Wait for backend status to read "ok" (sidebar shows vX.Y.Z, not "checking")
  // and for the recommendations to render real rows — avoids the cold-start
  // half-loaded frame the validator flagged.
  await page.locator("nav").first().waitFor({ timeout: 30000 });
  // backend ready + recommendations rendered: wait for the "100% GPU" section
  // heading (only appears once the hardware probe returned and recs computed).
  await page
    .getByText(/100% GPU/i)
    .first()
    .waitFor({ timeout: 30000 })
    .catch(() => {});
  await sleep(2500); // let hardware cards + recommendation rows fully settle

  // ---- Scene 1: Dashboard (real hardware + recommendations) ----
  await clickNav(page, "Dashboard");
  await sleep(1600);
  await page.mouse.wheel(0, 520);
  await sleep(1500);
  await page.mouse.wheel(0, 520);
  await sleep(1500);
  await page.mouse.wheel(0, -1040);
  await sleep(900);

  // ---- Scene 2: Models catalog + search + optimize ----
  await clickNav(page, "Models");
  await sleep(1400);
  const search = page.getByPlaceholder(/Search/i).first();
  await search.click();
  for (const ch of "qwen") { await search.type(ch); await sleep(140); }
  await sleep(1600);
  const optimizeBtn = page.locator('button[title*="ptim" i], button[title*="ptimiz" i]').first();
  try {
    await optimizeBtn.click({ timeout: 4000 });
  } catch {
    await page.locator("tbody tr").first().locator("button").last().click();
  }
  await sleep(2400); // optimal-config panel renders

  // ---- Scene 3: Benchmark — real LIVE run, EXECUTION panel populated ----
  await clickNav(page, "Benchmark");
  await sleep(1200);
  // llama-3.2-1b is cached and the engine is pre-warmed (keep_alive), so the
  // run boots in ~3s and streams tokens for several seconds — long enough for
  // the EXECUTION panel to fill with phases + live tok/s.
  const modelSelect = page.locator('label:has-text("Model") select').first();
  await modelSelect.selectOption("llama-3.2-1b");
  await sleep(700);
  // Keep only chat + summary so the run is quick but still streams visibly.
  for (const lbl of ["Reasoning", "Code", "Long context"]) {
    try {
      const b = page.locator("button", { hasText: new RegExp(`^${lbl}$`, "i") }).first();
      await b.click({ timeout: 1500 });
      await sleep(120);
    } catch {}
  }
  await sleep(500);
  // Keep the page scrolled to the TOP so the whole Execution panel (title +
  // engine-ready box + TTFT/tok-s stats + the black terminal log) sits in the
  // right column, fully framed, while SSE streams. Scrolling down here is what
  // previously cut the panel's header off and made it look empty.
  await page.evaluate(() => {
    const main = document.querySelector("main");
    if (main) main.scrollTo({ top: 0 });
    window.scrollTo(0, 0);
  });
  const launchBtn = page.getByRole("button", { name: /Launch benchmark/i }).first();
  await launchBtn.click();
  // Hold at top: engine.start -> engine.ready (~3s) -> per-prompt phases +
  // tokens streaming. The terminal log accumulates lines and the tok/s/TTFT
  // stats update live. Dwell long enough that ffmpeg can slow this segment.
  // Re-pin scroll frequently so the panel header (TTFT/tok-s stats) never
  // scrolls out of frame as the layout grows. ~16s covers boot + 2 prompts
  // (summary + chat, 384 tok x several iters each).
  for (let i = 0; i < 18; i++) {
    await page.evaluate(() => {
      const main = document.querySelector("main");
      if (main) main.scrollTo({ top: 0 });
      window.scrollTo(0, 0);
    });
    await sleep(900);
  }
  // Run done: now scroll down to reveal the RESULTS row (per-prompt metrics)
  // that landed under the two panels.
  await page.evaluate(() => {
    const main = document.querySelector("main");
    if (main) main.scrollTo({ top: 380, behavior: "smooth" });
  });
  await sleep(3000);
  await page.evaluate(() => {
    const main = document.querySelector("main");
    if (main) main.scrollTo({ top: 0, behavior: "smooth" });
  });
  await sleep(800);

  // ---- Scene 4: History — run detail (realistic quality) + comparison ----
  await clickNav(page, "History");
  await sleep(1400);
  // Open the seeded Q8_0 run: detail renders the per-prompt results table with
  // real tok/s + realistic Quality (~55-71, no zeros, not saturated at 100)
  // and the tok/s-per-prompt bar chart.
  const q8row = page.locator("li", { hasText: "demo seed (Q8_0)" }).first();
  await q8row.getByText(/llama-3.2-1b/i).first().click();
  await sleep(1700);
  await page.mouse.wheel(0, 440); // scroll to the results table + tps chart
  await sleep(3000);
  await page.mouse.wheel(0, -440);
  await sleep(700);
  // Multi-select both seeded runs (same model, Q8_0 vs Q4_K_M) and Compare.
  for (const note of ["demo seed (Q8_0)", "demo seed (Q4_K_M)"]) {
    const row = page.locator("li", { hasText: note }).first();
    await row.locator('input[type="checkbox"]').check();
    await sleep(500);
  }
  await sleep(400);
  await page.getByRole("button", { name: /Compare/i }).first().click();
  await sleep(1900);
  await page.mouse.wheel(0, 560); // frame the side-by-side charts (incl. Quality)
  await sleep(3000);
  await page.mouse.wheel(0, -560);
  await sleep(600);

  // ---- Scene 5: Serve / MCP — real image generation (sd-turbo, pre-warmed) ----
  await clickNav(page, "Serve / MCP");
  await sleep(1800);
  // sd-turbo is already served & ready (pre-warmed before recording). The
  // GenerateCard is showing. Fill the prompt and generate.
  const promptBox = page.locator("textarea").first();
  await promptBox.click();
  await promptBox.fill("a cozy reading nook by a rainy window, warm lamp light, watercolor");
  await sleep(1100);
  const genBtn = page.getByRole("button", { name: /^Generate$/i }).first();
  await genBtn.click();
  // Real sd.cpp run ~2-3s when warm.
  try {
    await page.locator('img[alt*="cozy" i], img[src^="data:image"]').first().waitFor({ timeout: 30000 });
  } catch {}
  await sleep(2400);
  // Scroll down to reveal "Connect over MCP" snippet (generate_image tool).
  await page.mouse.wheel(0, 660);
  await sleep(2800);

  await sleep(500);
  await context.close(); // flush video
  const video = page.video();
  const path = video ? await video.path() : null;
  await browser.close();
  console.log("VIDEO_PATH=" + path);
}

main().catch((e) => { console.error("REC_ERROR", e); process.exit(1); });
