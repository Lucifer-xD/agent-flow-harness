// Preload for the AFH window. Runs sandboxed with context isolation: the page only
// ever sees the `window.afh` object built here, never Node or Electron internals.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

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

  /** Opens an http(s) URL in the user's default browser. Other schemes are rejected. */
  openExternal: (url) => ipcRenderer.invoke("afh:open-external", String(url)),

  window: {
    minimize: () => ipcRenderer.invoke("afh:window:minimize"),
    maximize: () => ipcRenderer.invoke("afh:window:maximize"),
    close: () => ipcRenderer.invoke("afh:window:close"),
    isMaximized: () => ipcRenderer.invoke("afh:window:is-maximized"),
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
