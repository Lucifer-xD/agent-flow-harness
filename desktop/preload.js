// Preload for the AFH window. Runs sandboxed with context isolation: the page only
// ever sees the `window.afh` object built here, never Node or Electron internals.
"use strict";

const { contextBridge, ipcRenderer, webUtils } = require("electron");

const EVENT_CHANNEL = "afh:event";

// Fetched once, synchronously, so `window.afh.version` is a plain string (not a promise).
const info = ipcRenderer.sendSync("afh:info") || {};

contextBridge.exposeInMainWorld("afh", {
  version: String(info.version || ""),
  platform: String(info.platform || process.platform || ""),

  /** Native folder picker. Resolves to the chosen path, or null when cancelled. */
  pickFolder: () => ipcRenderer.invoke("afh:pick-folder"),

  /** Native multi-select file picker. Resolves to an array of paths (empty when cancelled). */
  pickFiles: () => ipcRenderer.invoke("afh:pick-files"),

  /** The path on disk of a dropped File ("" for things with no file behind them, like a pasted image). */
  pathForFile: (file) => {
    try {
      return webUtils.getPathForFile(file) || "";
    } catch {
      return "";
    }
  },

  /** Opens an http(s) URL in the user's default browser. Other schemes are rejected. */
  openExternal: (url) => ipcRenderer.invoke("afh:open-external", String(url)),

  /** App updates (see main.js): state(), check(), download(), install() → restarts into the new version. */
  updates: {
    state: () => ipcRenderer.invoke("afh:update:state"),
    check: () => ipcRenderer.invoke("afh:update:check"),
    download: () => ipcRenderer.invoke("afh:update:download"),
    install: () => ipcRenderer.invoke("afh:update:install"),
  },

  window: {
    minimize: () => ipcRenderer.invoke("afh:window:minimize"),
    maximize: () => ipcRenderer.invoke("afh:window:maximize"),
    close: () => ipcRenderer.invoke("afh:window:close"),
    isMaximized: () => ipcRenderer.invoke("afh:window:is-maximized"),
    /**
     * Re-tint the native window-control overlay (Windows/Linux) to match the page theme.
     * `color` / `symbolColor` are hex strings (#rgb, #rrggbb, #rrggbbaa); the height is fixed
     * at 38px by the main process. Resolves to true when applied, false when unsupported.
     */
    setTitleBarOverlay: (opts) => {
      const o = opts && typeof opts === "object" ? opts : {};
      return ipcRenderer.invoke("afh:window:set-title-bar-overlay", {
        color: o.color == null ? undefined : String(o.color),
        symbolColor: o.symbolColor == null ? undefined : String(o.symbolColor),
      });
    },
  },

  /**
   * Subscribe to main-process events such as `{ type: "maximized", value: true }`.
   * Returns an unsubscribe function.
   */
  onEvent: (cb) => {
    if (typeof cb !== "function") return () => {};
    const handler = (_event, payload) => {
      try {
        cb(payload);
      } catch (err) {
        console.error("[afh] onEvent callback failed", err);
      }
    };
    ipcRenderer.on(EVENT_CHANNEL, handler);
    return () => ipcRenderer.removeListener(EVENT_CHANNEL, handler);
  },
});
