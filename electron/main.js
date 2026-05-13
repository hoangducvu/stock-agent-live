const { app, BrowserWindow, shell, dialog } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

let mainWindow;
let backendProcess;
const BACKEND_PORT = 8000;
const FRONTEND_PORT = 5173;
const isDev = !app.isPackaged;

// ── Start Python backend ──────────────────────────────────────────────────────
function startBackend() {
  const backendDir = path.join(__dirname, "..", "backend");
  const python = process.platform === "win32" ? "python" : "python3";

  backendProcess = spawn(python, ["-m", "uvicorn", "main:app", "--port", String(BACKEND_PORT), "--host", "0.0.0.0"], {
    cwd: backendDir,
    stdio: ["ignore", "pipe", "pipe"],
    detached: false,
  });

  backendProcess.stdout.on("data", (d) => process.stdout.write("[backend] " + d));
  backendProcess.stderr.on("data", (d) => process.stderr.write("[backend] " + d));

  backendProcess.on("exit", (code) => {
    console.log(`Backend exited with code ${code}`);
  });
}

// ── Wait for a port to be ready ───────────────────────────────────────────────
function waitForPort(port, retries = 40, delay = 500) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      http.get(`http://localhost:${port}/api/health`, (res) => {
        if (res.statusCode === 200) resolve();
        else if (n > 0) setTimeout(() => attempt(n - 1), delay);
        else reject(new Error(`Port ${port} not ready`));
      }).on("error", () => {
        if (n > 0) setTimeout(() => attempt(n - 1), delay);
        else reject(new Error(`Port ${port} not ready after retries`));
      });
    };
    attempt(retries);
  });
}

// ── Create main window ────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0a0e1a",
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: path.join(__dirname, "..", "frontend", "public", "favicon.svg"),
    show: false,
  });

  const url = isDev
    ? `http://localhost:${FRONTEND_PORT}`
    : `file://${path.join(__dirname, "..", "frontend", "dist", "index.html")}`;

  mainWindow.loadURL(url);

  mainWindow.once("ready-to-show", () => mainWindow.show());

  // Open external links in browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => { mainWindow = null; });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  startBackend();
  try {
    await waitForPort(BACKEND_PORT);
    console.log("Backend ready on port", BACKEND_PORT);
  } catch (e) {
    dialog.showErrorBox("Backend Error", "Could not start the Python backend.\n\nMake sure Python 3.10+ and the backend requirements are installed.\n\n" + e.message);
  }
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (backendProcess) backendProcess.kill();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backendProcess) backendProcess.kill();
});
