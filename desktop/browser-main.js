// The built-in browser: the page shows it as <webview> tabs in a side panel (web/js/browser.js),
// and the agent drives the same tabs through the Chrome DevTools Protocol. This file is the
// main-process half: it locks the webviews down, and gives the page a CDP bridge
// (attach/send/shot) to its own webview tabs only. The page relays that bridge to the backend.
"use strict";

const { BrowserWindow, ipcMain, nativeImage, webContents } = require("electron");

const PARTITION = "persist:afh-browser"; // its own cookies and sign-ins, kept between runs
const SCHEMES = new Set(["http:", "https:", "file:", "about:"]);
const wired = new WeakSet(); // tabs whose debugger events already go to the page

/** A webview tab of the window that asks; anything else (the AFH page itself, another window) is refused. */
function tabOf(event, id) {
  const wc = webContents.fromId(Number(id));
  if (!wc || wc.isDestroyed() || wc.getType() !== "webview" || wc.hostWebContents !== event.sender) throw new Error("No such browser tab");
  return wc;
}

function allowed(url) {
  try {
    return SCHEMES.has(new URL(url).protocol);
  } catch {
    return false;
  }
}

/** Called for the AFH window: webviews it creates get no preload, no Node and our own partition. */
function guardWindow(wc) {
  wc.on("will-attach-webview", (event, prefs, params) => {
    delete prefs.preload;
    prefs.nodeIntegration = false;
    prefs.nodeIntegrationInSubFrames = false;
    prefs.contextIsolation = true;
    prefs.sandbox = true;
    prefs.webSecurity = true;
    prefs.backgroundThrottling = false; // the agent works in tabs you aren't looking at
    if (params.partition !== PARTITION || (params.src && !allowed(params.src))) event.preventDefault();
  });
}

function registerBrowser() {
  // Links that open a new window open a new tab in the panel instead.
  require("electron").app.on("web-contents-created", (_e, wc) => {
    if (wc.getType() !== "webview") return;
    wc.setWindowOpenHandler(({ url }) => {
      const host = wc.hostWebContents;
      if (host && !host.isDestroyed() && allowed(url)) host.send("afh:browser:event", { id: wc.id, newTab: url });
      return { action: "deny" };
    });
    wc.on("will-navigate", (event, url) => {
      if (!allowed(url)) event.preventDefault();
    });
  });

  ipcMain.handle("afh:browser:attach", (event, id) => {
    const wc = tabOf(event, id);
    if (wc.debugger.isAttached()) return true;
    wc.debugger.attach("1.3");
    if (!wired.has(wc)) {
      wired.add(wc);
      const host = event.sender;
      wc.debugger.on("message", (_e, method, params) => {
        if (!host.isDestroyed()) host.send("afh:browser:event", { id: wc.id, method, params });
      });
      wc.debugger.on("detach", (_e, reason) => {
        if (!host.isDestroyed()) host.send("afh:browser:event", { id: wc.id, detached: String(reason || "") });
      });
    }
    return true;
  });

  ipcMain.handle("afh:browser:send", async (event, id, method, params) => {
    const wc = tabOf(event, id);
    if (!wc.debugger.isAttached()) throw new Error("The browser tab isn't connected");
    return wc.debugger.sendCommand(String(method), params && typeof params === "object" ? params : {});
  });

  // A screenshot sized in CSS pixels, so x,y read off it are the page's own coordinates.
  ipcMain.handle("afh:browser:shot", async (event, id, width) => {
    const wc = tabOf(event, id);
    let img = null;
    // capturePage can fail while a page swaps renderers mid-navigation: try again, then ask the page itself
    for (let attempt = 0; attempt < 3 && !img; attempt++) {
      try {
        const got = await wc.capturePage();
        if (!got.isEmpty()) img = got;
      } catch {}
      if (!img) await new Promise((r) => setTimeout(r, 350));
    }
    if (!img && wc.debugger.isAttached()) {
      try {
        const shot = await wc.debugger.sendCommand("Page.captureScreenshot", { format: "png" });
        img = nativeImage.createFromBuffer(Buffer.from(shot.data, "base64"));
      } catch {}
    }
    if (!img || img.isEmpty()) return { minimized: !!BrowserWindow.fromWebContents(event.sender)?.isMinimized() };
    const w = Math.round(Number(width) || 0);
    if (w > 0 && img.getSize().width > w) img = img.resize({ width: w, quality: "good" });
    const size = img.getSize();
    return { data: img.toJPEG(72).toString("base64"), width: size.width, height: size.height };
  });

  ipcMain.handle("afh:browser:detach", (event, id) => {
    try {
      const wc = tabOf(event, id);
      if (wc.debugger.isAttached()) wc.debugger.detach();
    } catch {}
    return true;
  });
}

module.exports = { registerBrowser, guardWindow, PARTITION };
