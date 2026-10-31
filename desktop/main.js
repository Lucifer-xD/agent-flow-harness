// Electron main process for Agent Flow Harness.
//
// Responsibilities: own the Python backend process (dev: ../.venv + ../run.py, packaged:
// resources/backend/afh-backend.exe), wait for its "AFH is running at <url>" line, show a
// single BrowserWindow on that URL, expose native dialogs over IPC (see preload.js), and
// make sure the whole backend process tree is gone when the app quits.
"use strict";

const { app, BrowserWindow, dialog, ipcMain, Menu, Tray, shell, nativeImage, screen } = require("electron");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const APP_ID = "com.agentflowharness.app";
const BACKEND_TIMEOUT_MS = 60_000;
const URL_RE = /AFH is running at (http:\/\/\S+)/;
const STDERR_TAIL_LINES = 40;

// Custom title bar: the page draws its own drag strip (`-webkit-app-region: drag`) and, on
// Windows/Linux, its own minimize/maximize/close buttons (so they follow theme changes and the
// title bar border runs the full width; a native overlay is a separate opaque layer the page
// cannot animate). On macOS the traffic lights are inset instead.

let mainWindow = null;
let tray = null;
let backend = null; // ChildProcess
let backendUrl = null;
let backendOrigin = null;
let backendExited = false;
let gracefulQuitStarted = false;
let quitting = false; // set in before-quit: backend exit is expected from then on
let killRequested = false;
let fatalShown = false;
const stderrTail = [];

const log = (...args) => console.log("[afh]", ...args);
const logErr = (...args) => console.error("[afh]", ...args);

// ---- single instance ---------------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  log("another instance is already running; exiting");
  app.quit();
} else {
  if (IS_WIN) app.setAppUserModelId(APP_ID);
  app.on("second-instance", () => showWindow());
  startBackend();
  app.whenReady().then(onReady);
}

// ---- backend process ---------------------------------------------------------------------

function backendCommand() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", IS_WIN ? "afh-backend.exe" : "afh-backend");
    return { cmd: exe, args: ["--headless"], cwd: path.dirname(exe) };
  }
  const repoRoot = path.resolve(__dirname, "..");
  const python = IS_WIN
    ? path.join(repoRoot, ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, ".venv", "bin", "python");
  return { cmd: python, args: [path.join(repoRoot, "run.py"), "--headless"], cwd: repoRoot };
}

function startBackend() {
  const { cmd, args, cwd } = backendCommand();
  log("starting backend:", cmd, args.join(" "), "(cwd:", cwd + ")");
  if (!fs.existsSync(cmd)) {
    fatal("Backend not found", `The AFH backend executable is missing:\n\n${cmd}`);
    return;
  }

  try {
    backend = spawn(cmd, args, {
      cwd,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" }, // AFH_HOME etc. pass through
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      detached: !IS_WIN, // own process group on POSIX so we can signal the whole tree
    });
  } catch (err) {
    fatal("Backend failed to start", String(err && err.message ? err.message : err));
    return;
  }
  log("backend pid", backend.pid);

  const timer = setTimeout(() => {
    if (backendUrl) return;
    fatal(
      "Backend did not start",
      `The AFH backend did not report a URL within ${BACKEND_TIMEOUT_MS / 1000} seconds.\n\n${stderrText()}`
    );
  }, BACKEND_TIMEOUT_MS);

  readLines(backend.stdout, (line) => {
    log("[backend]", line);
    if (backendUrl) return;
    const m = URL_RE.exec(line);
    if (!m) return;
    clearTimeout(timer);
    backendUrl = m[1];
    backendOrigin = new URL(backendUrl).origin;
    log("backend URL parsed:", backendOrigin);
    if (app.isReady()) createWindow();
  });
  readLines(backend.stderr, (line) => {
    stderrTail.push(line);
    if (stderrTail.length > STDERR_TAIL_LINES) stderrTail.shift();
    logErr("[backend]", line);
  });

  backend.on("error", (err) => {
    clearTimeout(timer);
    fatal("Backend failed to start", `${err.message}\n\nCommand: ${cmd} ${args.join(" ")}`);
  });
  backend.on("exit", (code, signal) => {
    clearTimeout(timer);
    backendExited = true;
    log(`backend exited (code=${code}, signal=${signal})`);
    if (quitting || gracefulQuitStarted) {
      // Expected: we stopped it ourselves. Never pop a dialog while quitting.
      if (gracefulQuitStarted) app.quit();
      return;
    }
    if (!backendUrl) {
      fatal("Backend exited", `The AFH backend exited before it was ready (code ${code}).\n\n${stderrText()}`);
    } else if (!fatalShown) {
      fatal("Backend stopped", `The AFH backend process exited unexpectedly (code ${code}).\n\n${stderrText()}`);
    }
  });
}

function readLines(stream, onLine) {
  if (!stream) return;
  let buf = "";
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    buf += chunk;
    let idx;
    while ((idx = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, idx).replace(/\r$/, "");
      buf = buf.slice(idx + 1);
      if (line.trim()) onLine(line);
    }
  });
  stream.on("end", () => {
    if (buf.trim()) onLine(buf.replace(/\r$/, ""));
  });
}

function stderrText() {
  return stderrTail.length ? "Backend output:\n" + stderrTail.join("\n") : "(no backend error output)";
}

function backendAlive() {
  return !!backend && !backendExited && backend.exitCode === null && backend.signalCode === null;
}

/** Hard-kill the backend and everything it spawned (python, MCP servers). Synchronous. */
function killBackendTree() {
  if (!backendAlive() || killRequested) return;
  killRequested = true;
  const pid = backend.pid;
  log("killing backend process tree, pid", pid);
  if (IS_WIN) {
    const r = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, encoding: "utf8" });
    if (r.status !== 0) logErr("taskkill failed:", (r.stderr || r.stdout || "").trim());
  } else {
    try {
      process.kill(-pid, "SIGTERM"); // whole process group
    } catch {
      try {
        backend.kill("SIGTERM");
      } catch {}
    }
  }
}

/** POSIX only: ask run.py to shut down cleanly (it handles KeyboardInterrupt), then quit. */
function requestGracefulQuit() {
  gracefulQuitStarted = true;
  try {
    backend.kill("SIGINT");
  } catch {
    app.quit();
    return;
  }
  setTimeout(() => app.quit(), 5000).unref();
}

function fatal(title, message) {
  if (fatalShown || quitting) return;
  fatalShown = true;
  logErr(title + ":", message);
  const show = () => {
    dialog.showErrorBox(title, message);
    app.quit();
  };
  if (app.isReady()) show();
  else app.whenReady().then(show);
}

// ---- window --------------------------------------------------------------------------------

function statePath() {
  return path.join(app.getPath("userData"), "window-state.json");
}

function loadWindowState() {
  try {
    const s = JSON.parse(fs.readFileSync(statePath(), "utf8"));
    if (s && typeof s === "object") return s;
  } catch {}
  return {};
}

let saveTimer = null;
function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const bounds = mainWindow.getNormalBounds();
  const state = { ...bounds, maximized: mainWindow.isMaximized() };
  try {
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(state));
  } catch (err) {
    logErr("could not save window state:", err.message);
  }
}
function scheduleSaveWindowState() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveWindowState, 400);
}

function boundsVisible(b) {
  if (![b.x, b.y, b.width, b.height].every(Number.isFinite)) return false;
  return screen.getAllDisplays().some((d) => {
    const a = d.workArea;
    return b.x < a.x + a.width && b.x + b.width > a.x && b.y < a.y + a.height && b.y + b.height > a.y;
  });
}

function appIcon() {
  const p = path.join(__dirname, "assets", "icon.png");
  const img = nativeImage.createFromPath(p);
  return img.isEmpty() ? undefined : img;
}

function createWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    showWindow();
    return;
  }
  if (!backendUrl) return;

  const saved = loadWindowState();
  const opts = {
    width: 1320,
    height: 860,
    minWidth: 860,
    minHeight: 560,
    backgroundColor: "#0f0d0c",
    show: false,
    autoHideMenuBar: true,
    title: "Agent Flow Harness",
    icon: appIcon(),
    // Frameless-looking window; the page draws the window controls (see the title bar note above).
    // "hidden" keeps the resize borders and Windows snapping.
    titleBarStyle: IS_MAC ? "hiddenInset" : "hidden",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  };
  if (boundsVisible(saved)) {
    opts.x = saved.x;
    opts.y = saved.y;
    opts.width = Math.max(saved.width, opts.minWidth);
    opts.height = Math.max(saved.height, opts.minHeight);
  }

  mainWindow = new BrowserWindow(opts);
  mainWindow.removeMenu();
  if (saved.maximized) mainWindow.maximize();

  mainWindow.once("ready-to-show", () => {
    log("window ready-to-show");
    mainWindow.show();
  });
  mainWindow.on("resize", scheduleSaveWindowState);
  mainWindow.on("move", scheduleSaveWindowState);
  mainWindow.on("maximize", () => {
    scheduleSaveWindowState();
    sendEvent({ type: "maximized", value: true });
  });
  mainWindow.on("unmaximize", () => {
    scheduleSaveWindowState();
    sendEvent({ type: "maximized", value: false });
  });
  mainWindow.on("close", () => {
    clearTimeout(saveTimer);
    saveWindowState();
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  const wc = mainWindow.webContents;
  wc.on("did-finish-load", () => {
    log("did-finish-load", wc.getURL().split("#")[0]);
    wc.executeJavaScript("typeof window.afh").then(
      (t) => log("window.afh bridge:", t),
      (err) => logErr("bridge check failed:", err.message)
    );
  });
  wc.on("did-fail-load", (_e, code, desc, url, isMainFrame) => {
    if (isMainFrame) logErr(`did-fail-load ${code} ${desc} ${url}`);
  });
  wc.on("preload-error", (_e, preloadPath, err) => logErr("preload error in", preloadPath, err));
  wc.on("render-process-gone", (_e, details) => logErr("renderer gone:", details.reason));

  // target=_blank / window.open → default browser; never a second Electron window.
  wc.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: "deny" };
  });
  // In-page navigation away from the backend origin also goes to the browser.
  wc.on("will-navigate", (event, url) => {
    let origin = null;
    try {
      origin = new URL(url).origin;
    } catch {}
    if (origin !== backendOrigin) {
      event.preventDefault();
      openExternal(url);
    }
  });

  log("loading", backendOrigin);
  mainWindow.loadURL(backendUrl);
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function sendEvent(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("afh:event", payload);
}

async function openExternal(url) {
  let parsed;
  try {
    parsed = new URL(String(url));
  } catch {
    return;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return;
  await shell.openExternal(parsed.href);
}

// ---- updates -----------------------------------------------------------------------------------
//
// electron-updater with a "generic" feed: a folder on a web server holding latest.yml and the
// installer that `npm run dist` writes. The address is Settings → About → Updates (updates.feed in
// ~/.afh/settings.json), else AFH_UPDATE_URL, else the AFH website. New versions download in the
// background when updates.auto is on; the page offers "Restart to update", and quitting installs it anyway.

const DEFAULT_FEED = "https://agenflowharness.com/downloads/";
let autoUpdater = null;
const update = { state: "idle", version: null, progress: 0, error: null, feed: "", current: app.getVersion() };
const UPDATE_EVERY_MS = 6 * 60 * 60 * 1000;

function afhSettings() {
  try {
    const home = process.env.AFH_HOME || path.join(os.homedir(), ".afh");
    return JSON.parse(fs.readFileSync(path.join(home, "settings.json"), "utf8"));
  } catch {
    return {};
  }
}

function updateSettings() {
  const u = afhSettings().updates || {};
  const feed = String(u.feed || process.env.AFH_UPDATE_URL || DEFAULT_FEED).trim();
  return { auto: u.auto !== false, feed: feed && !feed.endsWith("/") ? feed + "/" : feed };
}

const firstLine = (err) => String(err?.message || err).split(/\r?\n/)[0].slice(0, 300);

function setUpdate(patch) {
  Object.assign(update, patch);
  sendEvent({ type: "update", update: { ...update } });
}

function initUpdater() {
  if (!app.isPackaged) {
    update.state = "dev"; // a development run has nothing to update
    return;
  }
  try {
    ({ autoUpdater } = require("electron-updater"));
  } catch (err) {
    logErr("electron-updater unavailable:", err.message);
    update.state = "unsupported";
    return;
  }
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.logger = { info: (m) => log("update:", m), warn: (m) => log("update:", m), error: (m) => logErr("update:", m), debug: () => {} };
  autoUpdater.on("checking-for-update", () => setUpdate({ state: "checking", error: null }));
  autoUpdater.on("update-not-available", () => setUpdate({ state: "latest", checked: Date.now() }));
  autoUpdater.on("update-available", (info) => {
    setUpdate({ state: "available", version: info.version, checked: Date.now() });
    if (updateSettings().auto) autoUpdater.downloadUpdate().catch(() => {});
  });
  autoUpdater.on("download-progress", (p) => setUpdate({ state: "downloading", progress: Math.round(p.percent || 0) }));
  autoUpdater.on("update-downloaded", (info) => setUpdate({ state: "ready", version: info.version, progress: 100 }));
  autoUpdater.on("error", (err) => setUpdate({ state: "error", error: firstLine(err) }));
  setTimeout(() => checkForUpdates(false), 20_000).unref();
  setInterval(() => checkForUpdates(false), UPDATE_EVERY_MS).unref();
}

async function checkForUpdates(manual) {
  if (!autoUpdater) return { ...update };
  if (["checking", "downloading", "ready"].includes(update.state)) return { ...update };
  const { auto, feed } = updateSettings();
  if (!manual && !auto) return { ...update };
  if (!feed) {
    setUpdate({ state: "nofeed", feed: "" });
    return { ...update };
  }
  update.feed = feed;
  autoUpdater.setFeedURL({ provider: "generic", url: feed });
  try {
    await autoUpdater.checkForUpdates();
  } catch (err) {
    setUpdate({ state: "error", error: firstLine(err) });
  }
  return { ...update };
}

ipcMain.handle("afh:update:state", () => ({ ...update }));
ipcMain.handle("afh:update:check", () => checkForUpdates(true));
ipcMain.handle("afh:update:download", async () => {
  if (autoUpdater && update.state === "available") await autoUpdater.downloadUpdate().catch(() => {});
  return { ...update };
});
ipcMain.handle("afh:update:install", () => {
  if (!autoUpdater || update.state !== "ready") return false;
  quitting = true;
  setImmediate(() => autoUpdater.quitAndInstall(true, true)); // silent, then start the new version
  return true;
});

// ---- tray ------------------------------------------------------------------------------------

function createTray() {
  const base = appIcon();
  if (!base) return;
  const icon = IS_MAC ? base.resize({ width: 18, height: 18 }) : base.resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip("Agent Flow Harness");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open", click: () => showWindow() },
      { type: "separator" },
      { label: "Quit", click: () => app.quit() },
    ])
  );
  tray.on("click", () => showWindow());
  tray.on("double-click", () => showWindow());
}

// ---- IPC (contract implemented by preload.js as window.afh) -------------------------------------

function windowOf(event) {
  return BrowserWindow.fromWebContents(event.sender) || mainWindow;
}

ipcMain.on("afh:info", (event) => {
  event.returnValue = { version: app.getVersion(), platform: process.platform };
});

ipcMain.handle("afh:pick-folder", async (event) => {
  const r = await dialog.showOpenDialog(windowOf(event), {
    properties: ["openDirectory", "createDirectory"],
  });
  return r.canceled || !r.filePaths.length ? null : r.filePaths[0];
});

ipcMain.handle("afh:pick-files", async (event) => {
  const r = await dialog.showOpenDialog(windowOf(event), {
    properties: ["openFile", "multiSelections"],
  });
  return r.canceled ? [] : r.filePaths;
});

ipcMain.handle("afh:open-external", (_event, url) => openExternal(url));

ipcMain.handle("afh:window:minimize", (event) => {
  const w = windowOf(event);
  if (w) w.minimize();
});
ipcMain.handle("afh:window:maximize", (event) => {
  const w = windowOf(event);
  if (!w) return;
  if (w.isMaximized()) w.unmaximize();
  else w.maximize();
});
ipcMain.handle("afh:window:close", (event) => {
  const w = windowOf(event);
  if (w) w.close();
});
ipcMain.handle("afh:window:is-maximized", (event) => {
  const w = windowOf(event);
  return !!w && w.isMaximized();
});
// Kept for older pages: the window controls are drawn by the page now, so there is nothing to re-tint.
ipcMain.handle("afh:window:set-title-bar-overlay", () => false);

// ---- app lifecycle -----------------------------------------------------------------------------

function onReady() {
  log("app ready; version", app.getVersion(), "packaged:", app.isPackaged, "userData:", app.getPath("userData"));
  Menu.setApplicationMenu(null);
  createTray();
  initUpdater();
  if (backendUrl) createWindow();

  app.on("activate", () => {
    // macOS: clicking the dock icon with no windows open re-creates the window.
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else showWindow();
  });
}

app.on("window-all-closed", () => {
  // Windows/Linux: closing the window quits (and stops the backend). macOS keeps running.
  if (!IS_MAC) app.quit();
});

app.on("before-quit", (event) => {
  quitting = true;
  if (!IS_WIN && backendAlive() && !gracefulQuitStarted) {
    // Give run.py a chance to stop its MCP servers; will-quit hard-kills whatever is left.
    event.preventDefault();
    requestGracefulQuit();
  }
});

app.on("will-quit", () => {
  killBackendTree();
  if (tray) {
    tray.destroy();
    tray = null;
  }
});

process.on("exit", killBackendTree);
