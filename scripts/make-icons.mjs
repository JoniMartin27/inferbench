// Genera los iconos de la app de escritorio a partir del SVG de marca Fervon
// (`frontend/public/favicon.svg`), para que el acceso directo del escritorio, la barra de
// tareas y el instalador lleven el icono de InferBench y no el átomo genérico de Electron.
//
//   node scripts/make-icons.mjs
//
// Salida (en `frontend/build/`, que es el `buildResources` por defecto de electron-builder):
//   icon.ico   multi-tamaño 16..256, entradas PNG  -> Windows (ventana, atajo, instalador)
//   icon.png   1024x1024                           -> Linux/macOS (electron-builder convierte)
//
// Y además `frontend/electron/icon-256.png`, que es el que carga `main.js` en tiempo de
// ejecución para el icono de ventana: tiene que vivir bajo `electron/` porque `build/` es
// buildResources y NO entra en el paquete (`files` solo mete `dist/**` y `electron/**`).
//
// Renderiza con el Chrome ya instalado vía puppeteer-core: no hace falta ImageMagick,
// sharp, ni ninguna dependencia nativa. Es un script de mantenimiento — se corre a mano
// cuando cambia el SVG de marca y el resultado se commitea.
//
// Igual que `record-demo.mjs`, se invoca desde un directorio de herramientas AISLADO para
// no meter puppeteer en el package.json del repo:
//   mkdir C:/tmp/ib-icons && cd C:/tmp/ib-icons && npm i puppeteer-core@23
//   IB_TOOLS_DIR=C:/tmp/ib-icons node <repo>/scripts/make-icons.mjs
//
// (NODE_PATH no vale: los módulos ES resuelven los specifiers desnudos subiendo desde la
// ruta del PROPIO fichero, no desde el cwd ni desde NODE_PATH. De ahí el createRequire.)

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SVG = path.join(ROOT, "frontend", "public", "favicon.svg");
const OUT = path.join(ROOT, "frontend", "build");

// Windows no admite entradas de más de 256 px en un .ico.
const ICO_SIZES = [16, 24, 32, 48, 64, 128, 256];

/** Carga puppeteer-core desde el directorio de herramientas aislado (o desde donde se pueda). */
function loadPuppeteer() {
  const bases = [
    process.env.IB_TOOLS_DIR && path.join(process.env.IB_TOOLS_DIR, "package.json"),
    path.join(ROOT, "package.json"),
  ].filter(Boolean);
  for (const base of bases) {
    try {
      return createRequire(base)("puppeteer-core");
    } catch {
      // probamos la siguiente base
    }
  }
  throw new Error(
    "No encuentro puppeteer-core. Instálalo en un directorio de herramientas aparte y " +
      "apunta ahí con IB_TOOLS_DIR:\n" +
      "  mkdir C:/tmp/ib-icons && cd C:/tmp/ib-icons && npm i puppeteer-core@23\n" +
      "  IB_TOOLS_DIR=C:/tmp/ib-icons node scripts/make-icons.mjs"
  );
}

const CHROME_CANDIDATES = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
];

function findChrome() {
  const hit = CHROME_CANDIDATES.find((p) => fs.existsSync(p));
  if (!hit) {
    throw new Error(
      `No encuentro Chrome. Rutas probadas:\n  ${CHROME_CANDIDATES.join("\n  ")}\n` +
        `Pasa la ruta con PUPPETEER_EXECUTABLE_PATH.`
    );
  }
  return hit;
}

/** Empaqueta varios PNG en un .ico. Windows Vista+ acepta entradas PNG tal cual. */
function buildIco(pngs) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reservado
  header.writeUInt16LE(1, 2); // tipo: 1 = icono
  header.writeUInt16LE(pngs.length, 4);

  const DIR_ENTRY = 16;
  let offset = header.length + pngs.length * DIR_ENTRY;
  const entries = pngs.map(({ size, data }) => {
    const e = Buffer.alloc(DIR_ENTRY);
    e.writeUInt8(size === 256 ? 0 : size, 0); // 0 significa 256
    e.writeUInt8(size === 256 ? 0 : size, 1);
    e.writeUInt8(0, 2); // paleta: 0 = sin paleta
    e.writeUInt8(0, 3); // reservado
    e.writeUInt16LE(1, 4); // planos
    e.writeUInt16LE(32, 6); // bits por píxel
    e.writeUInt32LE(data.length, 8);
    e.writeUInt32LE(offset, 12);
    offset += data.length;
    return e;
  });

  return Buffer.concat([header, ...entries, ...pngs.map((p) => p.data)]);
}

const svg = fs.readFileSync(SVG, "utf8");
fs.mkdirSync(OUT, { recursive: true });

const puppeteer = loadPuppeteer();
const nav = await puppeteer.launch({
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || findChrome(),
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--force-device-scale-factor=1"],
});

try {
  const pag = await nav.newPage();

  /** Renderiza el SVG a PNG cuadrado de `size` px con fondo transparente. */
  const render = async (size) => {
    await pag.setViewport({ width: size, height: size, deviceScaleFactor: 1 });
    await pag.setContent(
      `<body style="margin:0;width:${size}px;height:${size}px">` +
        `<div style="width:${size}px;height:${size}px">${svg}</div></body>`
    );
    return Buffer.from(await pag.screenshot({ omitBackground: true, type: "png" }));
  };

  const pngs = [];
  for (const size of ICO_SIZES) pngs.push({ size, data: await render(size) });

  const ico = path.join(OUT, "icon.ico");
  fs.writeFileSync(ico, buildIco(pngs));
  console.log(`icon.ico       ${ICO_SIZES.join("/")} px  ->  ${fs.statSync(ico).size} B`);

  const png1024 = path.join(OUT, "icon.png");
  fs.writeFileSync(png1024, await render(1024));
  console.log(`icon.png       1024 px  ->  ${fs.statSync(png1024).size} B`);

  // Este va bajo electron/ a propósito: es el único que se lee en RUNTIME.
  const runtimeIcon = path.join(ROOT, "frontend", "electron", "icon-256.png");
  fs.writeFileSync(runtimeIcon, await render(256));
  console.log(`electron/icon-256.png  256 px  ->  ${fs.statSync(runtimeIcon).size} B`);
} finally {
  await nav.close();
}
