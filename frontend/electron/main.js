// Proceso principal de Electron — ventana única + sidecar del backend Python.
import { app, BrowserWindow, dialog, shell } from "electron";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isDev = !app.isPackaged;

// El nombre de la app lo fija `productName` en el package.json del frontend; Electron lo
// lee al arrancar, antes de resolver ninguna ruta. Esto es el cinturón: sin nombre correcto,
// userData caía en %APPDATA%\inferbench-frontend\ (el `name` interno del paquete) mientras
// el backend usa %APPDATA%\InferBench\ para sus cachés — dos carpetas para la misma app.
// `sessionData` se resuelve MUY pronto, así que lo realineamos explícitamente.
app.setName("InferBench");
app.setPath("sessionData", app.getPath("userData"));

// Icono de marca (Fervon). Lo genera `scripts/make-icons.mjs` desde el SVG del favicon.
// Vive bajo electron/ porque `build/` es buildResources y no entra en el paquete. En
// Windows el .ico ya va incrustado en el exe; esto cubre la ventana en dev y en Linux.
const WINDOW_ICON = path.join(__dirname, "icon-256.png");

let backendProcess = null;
let backendLogStream = null;

/** Fichero de log del sidecar, dentro de userData (se puede abrir desde el explorador). */
function backendLogPath() {
  const dir = path.join(app.getPath("userData"), "logs");
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, "backend.log");
}

/**
 * ¿Hay ya un backend de InferBench sano en el :7777?
 *
 * Pasa más de lo que parece: si la app se cierra a la fuerza (cuelgue, matar el proceso,
 * apagón del explorador) el `before-quit` no corre, el sidecar sobrevive y se queda con el
 * puerto. Medido: tras un `Stop-Process -Force` sobre la app, el hijo de PyInstaller sigue
 * escuchando. Si arrancásemos otro a ciegas, el nuevo moriría con un error de bind que el
 * usuario no ve. Reusar el que ya está es lo correcto y además hace el arranque instantáneo.
 */
async function healthyBackendAlreadyRunning() {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 1500);
    const resp = await fetch("http://127.0.0.1:7777/api/health", { signal: ctrl.signal });
    clearTimeout(t);
    if (!resp.ok) return false;
    // Comprobamos que sea NUESTRO backend y no otra cosa ocupando el puerto.
    const body = await resp.json();
    return body?.status === "ok" && typeof body?.version === "string";
  } catch {
    return false;
  }
}

async function startBackendSidecar() {
  if (isDev) return; // En dev el usuario lanza uvicorn manualmente

  if (await healthyBackendAlreadyRunning()) {
    backendLogStream = fs.createWriteStream(backendLogPath(), { flags: "a" });
    backendLogStream.write(
      `\n=== ${new Date().toISOString()} · ya había un backend sano en :7777, lo reuso ===\n`
    );
    backendLogStream.end();
    backendLogStream = null;
    return;
  }

  const exeName =
    process.platform === "win32" ? "inferbench-backend.exe" : "inferbench-backend";
  const exePath = path.join(process.resourcesPath, "sidecar", exeName);

  // En una app empaquetada de Windows NO hay consola: heredar stdio manda la salida del
  // backend a ninguna parte y deja un arranque fallido sin rastro. La volcamos a un fichero.
  const logFile = backendLogPath();
  backendLogStream = fs.createWriteStream(logFile, { flags: "a" });
  backendLogStream.write(`\n=== arranque ${new Date().toISOString()} · ${exePath} ===\n`);

  backendProcess = spawn(exePath, [], {
    stdio: ["ignore", "pipe", "pipe"],
    // El backend lee INFERBENCH_PORT (ver backend/main.py). Antes se pasaba
    // INFERBENCH_BACKEND_PORT, que no lo lee nadie.
    env: { ...process.env, INFERBENCH_PORT: "7777" },
    windowsHide: true,
  });
  backendProcess.stdout?.pipe(backendLogStream);
  backendProcess.stderr?.pipe(backendLogStream);

  // Sin este manejador, un ENOENT (sidecar ausente en el paquete) emite 'error' sin
  // escuchador y tumba el proceso principal: la app "no abre" y el usuario no sabe por qué.
  backendProcess.on("error", (err) => {
    backendLogStream?.write(`[sidecar] fallo al arrancar: ${err.message}\n`);
    backendProcess = null;
    dialog.showErrorBox(
      "InferBench no pudo arrancar su backend",
      `No se pudo ejecutar el sidecar:\n${exePath}\n\n${err.message}\n\n` +
        `Detalle en:\n${logFile}`
    );
  });

  backendProcess.on("exit", (code, signal) => {
    backendLogStream?.write(`[sidecar] terminó code=${code} signal=${signal}\n`);
    backendProcess = null;
  });
}

function stopBackendSidecar() {
  const proc = backendProcess;
  backendProcess = null;
  if (proc) {
    // `kill()` en Windows mata SOLO el proceso raíz. El exe de PyInstaller (onefile)
    // arranca un hijo con el intérprete real, que sobrevive y sigue ocupando el :7777.
    // `taskkill /T` se lleva el árbol entero.
    //
    // spawnSync, no spawn: esto corre desde `before-quit`, que NO espera trabajo asíncrono.
    // Con la versión asíncrona Electron se moría antes de que el taskkill llegase a
    // ejecutarse y el backend quedaba huérfano igual — MEDIDO: cerrando la ventana con
    // CloseMainWindow, el proceso de Electron desaparecía y `inferbench-backend` seguía
    // sirviendo el :7777.
    if (process.platform === "win32" && proc.pid) {
      const res = spawnSync("taskkill", ["/pid", String(proc.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      });
      if (res.error || res.status !== 0) proc.kill();
    } else {
      proc.kill();
    }
  }
  backendLogStream?.end();
  backendLogStream = null;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1320,
    height: 860,
    backgroundColor: "#0E0B0A", // Fervon carbon — mismo fondo que la UI, sin flash frío al abrir
    icon: fs.existsSync(WINDOW_ICON) ? WINDOW_ICON : undefined,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Evita el destello de ventana vacía: la mostramos cuando ya hay algo pintado.
  win.once("ready-to-show", () => win.show());

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  return win;
}

// Instancia única: un segundo doble-click sobre el acceso directo levantaría OTRO sidecar
// peleando por el :7777. En vez de eso, traemos al frente la ventana que ya existe.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    // Sin await a propósito: la ventana debe aparecer YA. El backend tarda unos segundos
    // en desempaquetarse (PyInstaller onefile) y la UI ya sabe pintar "conectando" y
    // reintentar el health por su cuenta.
    startBackendSidecar().catch((err) => {
      dialog.showErrorBox("InferBench no pudo arrancar su backend", String(err));
    });
    createWindow();
  });

  app.on("window-all-closed", () => {
    stopBackendSidecar();
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", stopBackendSidecar);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}
