// The computer-use overlay: one transparent, click-through, always-on-top window per display that
// shows, while the agent controls the computer, a glowing edge, AFH's own cursor gliding to each
// point, click ripples, drag trails, scroll arrows, keycaps, a Stop pill, app approval cards and
// lesson tooltips (teach mode). The windows keep themselves out of screen capture
// (setContentProtection), so what the agent screenshots is the real desktop, never the overlay.
//
// The main process listens to the backend's event stream itself, so the overlay works even while
// AFH's window is minimized (it steps aside on its own while a task runs) or closed to the tray.
"use strict";

const { BrowserWindow, screen, ipcMain } = require("electron");
const path = require("path");

const overlays = new Map(); // display id -> BrowserWindow
let api = null; // { origin, token }
let getMain = () => null;
let streamAbort = null;
let active = null; // { sessionID, status, busy, hideWindow, effects }
let homeDisplay = null; // the display the pill, cards and toasts show on (follows AFH's cursor)
let hidTheWindow = false; // we minimized AFH's window for this task; restore it after
let lessons = new Map(); // teach id -> data (re-sent when the overlay reloads)
let asks = new Map(); // permission id -> data
let hideTimer = null;

// ---- the backend's event stream ------------------------------------------------------------

function connect(backendUrl) {
  try {
    const u = new URL(backendUrl);
    const token = new URLSearchParams(u.hash.replace(/^#/, "")).get("token") || "";
    api = { origin: u.origin, token };
  } catch {
    return;
  }
  listen();
}

async function listen() {
  if (!api) return;
  if (streamAbort) streamAbort.abort();
  const ctl = new AbortController();
  streamAbort = ctl;
  try {
    const res = await fetch(`${api.origin}/api/events`, { headers: { "x-afh-token": api.token }, signal: ctl.signal });
    if (!res.ok || !res.body) throw new Error(`events ${res.status}`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue;
          try {
            onEvent(JSON.parse(line.slice(5)));
          } catch {}
        }
      }
    }
  } catch (e) {
    if (ctl.signal.aborted) return;
  }
  if (streamAbort === ctl) setTimeout(listen, 1500); // the backend restarted or the stream dropped
}

function post(p, body) {
  if (!api) return Promise.resolve();
  return fetch(`${api.origin}${p}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-afh-token": api.token },
    body: JSON.stringify(body || {}),
  }).catch(() => {});
}

function onEvent(ev) {
  const t = ev && ev.type;
  const d = (ev && ev.data) || {};
  if (t === "computer.active") return onActive(d);
  if (t === "computer.fx") return onFx(d);
  if (t === "computer.teach") return onTeach(d);
  if (t === "permission.asked" && d.action === "computer" && d.metadata && d.metadata.kind === "computer") return onAsk(d);
  if (t === "permission.replied" && asks.has(d.id)) {
    asks.delete(d.id);
    broadcast("overlay:ask-done", { id: d.id, decision: d.decision });
  }
}

// ---- windows, one per display ------------------------------------------------------------------

function makeOverlay(display) {
  const w = new BrowserWindow({
    ...display.bounds,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    closable: false,
    focusable: false,
    skipTaskbar: true,
    hasShadow: false,
    show: false,
    alwaysOnTop: true,
    fullscreenable: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "overlay-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  w.setAlwaysOnTop(true, "screen-saver"); // above normal windows and most fullscreen apps
  w.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  try {
    // keep the overlay out of screenshots (AFH_OVERLAY_CAPTURE=1 shows it in captures, for testing the overlay itself)
    if (process.env.AFH_OVERLAY_CAPTURE !== "1") w.setContentProtection(true);
  } catch {}
  w.setIgnoreMouseEvents(true, { forward: true }); // click-through; the page still sees mousemove
  w.displayId = display.id;
  w.ready = false;
  w.webContents.once("did-finish-load", () => {
    w.ready = true;
    w.setBounds(display.bounds); // Windows may have scaled it on creation across mixed-DPI displays
    syncWindow(w);
  });
  w.loadFile(path.join(__dirname, "overlay.html"), { query: { origin: api ? api.origin : "", token: api ? api.token : "" } });
  w.on("closed", () => overlays.delete(display.id));
  overlays.set(display.id, w);
  return w;
}

function ensureOverlays() {
  const displays = screen.getAllDisplays();
  const ids = new Set(displays.map((d) => d.id));
  for (const [id, w] of overlays) if (!ids.has(id) && !w.isDestroyed()) w.destroy();
  for (const d of displays) {
    const w = overlays.get(d.id);
    if (!w || w.isDestroyed()) makeOverlay(d);
    else w.setBounds(d.bounds);
  }
  if (!homeDisplay || !ids.has(homeDisplay)) homeDisplay = screen.getPrimaryDisplay().id;
}

function showAll() {
  ensureOverlays();
  for (const w of overlays.values()) {
    if (w.isDestroyed()) continue;
    if (!w.isVisible()) w.showInactive();
    w.setAlwaysOnTop(true, "screen-saver");
  }
}

function hideAll() {
  for (const w of overlays.values()) if (!w.isDestroyed() && w.isVisible()) w.hide();
}

function send(w, channel, payload) {
  if (w && !w.isDestroyed() && w.ready) w.webContents.send(channel, payload);
}

function broadcast(channel, payload) {
  for (const w of overlays.values()) send(w, channel, payload);
}

/** Bring a freshly loaded overlay up to date: state, the home display, open cards and tooltips. */
function syncWindow(w) {
  const home = w.displayId === homeDisplay;
  send(w, "overlay:state", { ...(active || { active: false }), active: !!active || lessons.size > 0 || asks.size > 0, home });
  if (home) for (const a of asks.values()) send(w, "overlay:ask", a);
  for (const l of lessons.values()) if (l.displayId === w.displayId) send(w, "overlay:teach", l.local);
}

function pushState() {
  for (const w of overlays.values()) {
    send(w, "overlay:state", {
      ...(active || {}),
      active: !!active || lessons.size > 0 || asks.size > 0,
      teaching: lessons.size > 0,
      home: w.displayId === homeDisplay,
    });
  }
}

// ---- coordinates: the backend speaks physical pixels, windows speak DIP --------------------------

function toLocal(x, y) {
  let dip;
  try {
    dip = screen.screenToDipPoint({ x: Math.round(x), y: Math.round(y) });
  } catch {
    dip = { x, y };
  }
  const display = screen.getDisplayNearestPoint(dip);
  return { display, x: dip.x - display.bounds.x, y: dip.y - display.bounds.y };
}

function rectLocal(rect) {
  const a = toLocal(rect[0], rect[1]);
  const b = toLocal(rect[2] - 1, rect[3] - 1);
  return { display: a.display, x: a.x, y: a.y, w: Math.max(1, b.x - a.x), h: Math.max(1, b.y - a.y) };
}

// ---- what the backend asks the overlay to show -------------------------------------------------

function onActive(d) {
  if (d.active) {
    clearTimeout(hideTimer);
    const first = !active;
    active = { sessionID: d.sessionID, status: d.status || "", busy: d.busy !== false, hideWindow: d.hideWindow !== false, effects: d.effects !== false };
    if (first) {
      homeDisplay = screen.getPrimaryDisplay().id;
      stepAside(active.hideWindow);
    }
    showAll();
    pushState();
  } else if (active && (!d.sessionID || d.sessionID === active.sessionID)) {
    active = null;
    pushState();
    // let the fade-out play, then hide the windows and give AFH's window back
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (active || lessons.size || asks.size) return;
      hideAll();
    }, 700);
    comeBack();
  }
}

/** Minimize AFH's own window while it works, so the agent sees (and the user watches) the apps. */
function stepAside(want) {
  const w = getMain();
  hidTheWindow = false;
  if (!want || !w || w.isDestroyed() || !w.isVisible() || w.isMinimized()) return;
  w.minimize();
  hidTheWindow = true;
}

function comeBack() {
  const w = getMain();
  if (!hidTheWindow || !w || w.isDestroyed()) return;
  hidTheWindow = false;
  if (w.isMinimized()) w.restore();
}

function onFx(d) {
  if (d.kind === "stopped") return broadcast("overlay:fx", { kind: "stopped", label: d.label || "Stopped" });
  if (!active) return;
  const out = { ...d };
  let display = null;
  if (typeof d.x === "number" && typeof d.y === "number") {
    const p = toLocal(d.x, d.y);
    display = p.display;
    out.x = p.x;
    out.y = p.y;
    if (typeof d.x2 === "number") {
      const q = toLocal(d.x2, d.y2);
      out.x2 = q.x;
      out.y2 = q.y;
    }
  } else if (Array.isArray(d.rect)) {
    const r = rectLocal(d.rect);
    display = r.display;
    out.rect = { x: r.x, y: r.y, w: r.w, h: r.h };
  }
  if (active.effects === false) return;
  if (display && ["move", "click", "drag", "scroll", "press", "release"].includes(d.kind) && display.id !== homeDisplay) {
    homeDisplay = display.id; // the pill follows AFH's cursor to the display it is working on
    pushState();
    for (const a of asks.values()) send(overlays.get(homeDisplay), "overlay:ask", a);
  }
  const target = display ? overlays.get(display.id) : overlays.get(homeDisplay);
  for (const w of overlays.values()) {
    if (w === target) send(w, "overlay:fx", out);
    else if (["move", "click", "drag"].includes(d.kind)) send(w, "overlay:fx", { kind: "leave" });
  }
}

function onTeach(d) {
  if (d.done) {
    lessons.delete(d.id);
    broadcast("overlay:teach-done", { id: d.id });
    pushState();
    if (!active && !lessons.size && !asks.size) setTimeout(() => !active && !lessons.size && !asks.size && hideAll(), 700);
    return;
  }
  showAll();
  let local = { ...d };
  let displayId = homeDisplay;
  if (typeof d.x === "number" && typeof d.y === "number") {
    const p = toLocal(d.x, d.y);
    displayId = p.display.id;
    local.x = p.x;
    local.y = p.y;
  } else if (Array.isArray(d.display)) {
    displayId = rectLocal(d.display).display.id;
    delete local.x;
    delete local.y;
  }
  lessons.set(d.id, { displayId, local });
  pushState();
  send(overlays.get(displayId), "overlay:teach", local);
}

function onAsk(d) {
  const m = d.metadata || {};
  const a = { id: d.id, sessionID: d.sessionID, title: m.title || "", reason: m.reason || "", apps: m.apps || (m.app ? [m.app] : []), tierNote: m.tierNote || "" };
  asks.set(d.id, a);
  showAll();
  pushState();
  send(overlays.get(homeDisplay), "overlay:ask", a);
}

// ---- wiring -------------------------------------------------------------------------------------

function registerOverlay({ backendUrl, mainWindow }) {
  getMain = mainWindow || (() => null);
  ipcMain.on("afh:overlay:interactive", (e, on) => {
    const w = BrowserWindow.fromWebContents(e.sender);
    if (w && !w.isDestroyed()) w.setIgnoreMouseEvents(!on, { forward: true });
  });
  ipcMain.on("afh:overlay:stop", (_e, d) => {
    for (const l of lessons.keys()) post("/api/computer/teach", { id: l, choice: "exit" });
    if (d && d.lessonOnly && lessons.size) return; // "End lesson": the agent hears the user left and wraps up
    const sid = active && active.sessionID;
    if (sid) post(`/api/sessions/${sid}/interrupt`, {});
    broadcast("overlay:fx", { kind: "stopped", label: "Stopped" });
  });
  ipcMain.on("afh:overlay:answer", (_e, d) => {
    const a = d && asks.get(d.id);
    if (!a) return;
    post(`/api/sessions/${a.sessionID}/permissions/${a.id}`, { decision: String(d.decision || "reject") });
  });
  ipcMain.on("afh:overlay:teach", (_e, d) => {
    if (d && d.id) post("/api/computer/teach", { id: String(d.id), choice: d.choice === "exit" ? "exit" : "next" });
  });
  ipcMain.on("afh:overlay:open-afh", () => {
    const w = getMain();
    if (w && !w.isDestroyed()) {
      if (w.isMinimized()) w.restore();
      w.show();
      w.focus();
    }
  });
  screen.on("display-added", () => overlays.size && ensureOverlays());
  screen.on("display-removed", () => overlays.size && ensureOverlays());
  screen.on("display-metrics-changed", () => overlays.size && ensureOverlays());
  if (backendUrl) connect(backendUrl);
}

/** The backend's URL becomes known (or changes after a restart). */
function setBackend(backendUrl) {
  connect(backendUrl);
}

function destroyOverlay() {
  if (streamAbort) streamAbort.abort();
  streamAbort = null;
  for (const w of overlays.values()) if (!w.isDestroyed()) w.destroy();
  overlays.clear();
}

module.exports = { registerOverlay, setBackend, destroyOverlay };
