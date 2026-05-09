// Proceso principal de Electron — ventana única + sidecar del backend Python.
import { app, BrowserWindow, shell } from "electron";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isDev = !app.isPackaged;

let backendProcess = null;

function startBackendSidecar() {
  if (isDev) return; // En dev el usuario lanza uvicorn manualmente
  const exeName =
    process.platform === "win32" ? "inferbench-backend.exe" : "inferbench-backend";
  const exePath = path.join(process.resourcesPath, "sidecar", exeName);
  backendProcess = spawn(exePath, [], {
    stdio: "inherit",
    env: { ...process.env, INFERBENCH_BACKEND_PORT: "7777" },
  });
  backendProcess.on("exit", (code) => {
    console.log(`[sidecar] backend exited with code ${code}`);
    backendProcess = null;
  });
}

function stopBackendSidecar() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1320,
    height: 860,
    backgroundColor: "#020617", // slate-950
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  startBackendSidecar();
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
