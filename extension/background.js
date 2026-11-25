// Agent Flow Harness in your browser.
//
// AFH (the desktop app) drives tabs here with the Chrome DevTools Protocol, the same protocol it uses
// for its own browser. Instead of the browser's remote-debugging switch, it goes through this
// extension: Chrome starts AFH's small "native messaging" helper (com.agentflowharness.bridge, set up
// by the AFH app), the helper relays to the running app, and this worker runs each command in the tab
// with chrome.debugger. Chrome shows its "is debugging this browser" bar while AFH works in a tab.
// The tabs AFH opens sit together in a tab group named AFH, whose title says what it is doing.
//
// What it speaks: CDP messages {id, method, params, sessionId}. The browser-level Target.* commands
// AFH needs are answered from chrome.tabs; everything else goes to the tab named by sessionId ("t" +
// tab id). Tab events go back as Target.targetCreated / targetInfoChanged / targetDestroyed.
// AFH asks the user about every site before it looks at it; the popup can pause AFH here at any time.

const HOST = "com.agentflowharness.bridge";
const attached = new Set(); // tab ids AFH is working in
let port = null;
let afh = "starting"; // starting | waiting (helper runs, AFH app isn't open) | connected | missing (helper not set up) | paused
let problem = "";
let paused = false;
let discover = false;

const sid = (tabId) => "t" + tabId;
const tabOf = (s) => Number(String(s || "").slice(1));

function browserName() {
  const brands = (navigator.userAgentData?.brands || []).map((b) => b.brand);
  if (brands.some((b) => /edge/i.test(b))) return "Edge";
  if (brands.some((b) => /brave/i.test(b))) return "Brave";
  if (brands.some((b) => /opera/i.test(b))) return "Opera";
  if (brands.some((b) => /google chrome/i.test(b))) return "Chrome";
  return "Chromium";
}

function browserVersion() {
  const m = /Chrom(?:e|ium)\/([\d.]+)/.exec(navigator.userAgent);
  return m ? m[1] : "";
}

function info(tab) {
  const out = { targetId: String(tab.id), type: "page", title: tab.title || "", url: tab.url || tab.pendingUrl || "",
    attached: attached.has(tab.id), browserContextId: "default" };
  if (tab.openerTabId != null) out.openerId = String(tab.openerTabId);
  return out;
}

function send(msg) {
  try { if (port) port.postMessage(msg); } catch (e) { /* the helper went away; onDisconnect follows */ }
}

function emit(method, params, sessionId) {
  send(sessionId ? { method, params, sessionId } : { method, params });
}

function setState(s, why = "") {
  afh = s;
  problem = why;
  const badge = { connected: "", waiting: "", starting: "", missing: "!", paused: "II" }[s] ?? "";
  chrome.action.setBadgeText({ text: badge }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ color: s === "missing" ? "#c0392b" : "#6b6257" }).catch(() => {});
}

// ---- the AFH tab group ---------------------------------------------------------------------------

const TITLES = { working: "\u23F3 AFH", asking: "\u270B AFH", done: "\u2705 AFH" };
const OURS = /^(\S+ )?AFH$/; // a group we made, whatever its title says now

/** The window new tabs go to: the one the user used last. Opens one when there is none. */
async function homeWindow() {
  try {
    const w = await chrome.windows.getLastFocused({ windowTypes: ["normal"] });
    if (w && w.type === "normal" && !w.incognito) return w.id;
  } catch (e) { /* no window is open */ }
  const all = (await chrome.windows.getAll({ windowTypes: ["normal"] })).filter((w) => !w.incognito);
  return all.length ? all[0].id : (await chrome.windows.create({ focused: true })).id;
}

/** Put a tab AFH opened in this window's AFH group, making the group when there is none. */
async function group(tab, state = "working") {
  try {
    const [found] = (await chrome.tabGroups.query({ windowId: tab.windowId })).filter((g) => OURS.test(g.title || ""));
    const id = await chrome.tabs.group(found ? { tabIds: [tab.id], groupId: found.id } : { tabIds: [tab.id], createProperties: { windowId: tab.windowId } });
    await chrome.tabGroups.update(id, { title: TITLES[state], ...(found ? {} : { color: "orange", collapsed: false }) });
  } catch (e) { /* tabs can't be grouped here (an app window, or the user is dragging a tab) */ }
}

/** Say in the group's title what AFH is doing. A tab the user took out of the group stays out. */
async function groupState(tabId, state) {
  const tab = await chrome.tabs.get(tabId);
  if (tab.groupId == null || tab.groupId < 0 || !TITLES[state]) return;
  const g = await chrome.tabGroups.get(tab.groupId);
  if (OURS.test(g.title || "") && g.title !== TITLES[state]) await chrome.tabGroups.update(g.id, { title: TITLES[state] });
}

async function detachAll() {
  for (const id of [...attached]) {
    attached.delete(id);
    try { await chrome.debugger.detach({ tabId: id }); } catch (e) { /* already gone */ }
  }
}

function connect() {
  if (port || paused) return;
  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (e) {
    port = null;
    setState("missing", String(e?.message || e));
    return;
  }
  setState("starting");
  port.onMessage.addListener(onMessage);
  port.onDisconnect.addListener(() => {
    const why = chrome.runtime.lastError?.message || "";
    port = null;
    detachAll();
    if (!paused) setState(/not found|forbidden|not allowed/i.test(why) ? "missing" : "waiting", why);
  });
  send({ hello: { browser: browserName(), version: browserVersion(), extension: chrome.runtime.getManifest().version } });
}

async function onMessage(msg) {
  if (msg && msg.afh) { // from the helper itself: is the AFH app there?
    if (msg.afh !== "connected") await detachAll();
    if (!paused) setState(msg.afh === "connected" ? "connected" : "waiting");
    return;
  }
  if (!msg || msg.id == null) return;
  try {
    send({ id: msg.id, result: (await run(msg)) || {} });
  } catch (e) {
    send({ id: msg.id, error: { message: String(e?.message || e) } });
  }
}

async function run({ method, params = {}, sessionId }) {
  if (paused) throw new Error("The user paused AFH in this browser (with the AFH extension's button). Ask them to resume it.");
  switch (method) {
    case "Target.setDiscoverTargets":
      discover = !!params.discover;
      return {};
    case "Browser.getVersion":
      return { product: `${browserName()}/${browserVersion()}`, userAgent: navigator.userAgent, protocolVersion: "1.3" };
    case "Target.getTargets":
      return { targetInfos: (await chrome.tabs.query({})).map(info) };
    case "Target.createTarget": {
      const tab = await chrome.tabs.create({ windowId: await homeWindow(), url: params.url || "about:blank", active: !params.background });
      await group(tab);
      return { targetId: String(tab.id) };
    }
    case "Target.attachToTarget": {
      const id = Number(params.targetId);
      if (!attached.has(id)) {
        await chrome.debugger.attach({ tabId: id }, "1.3");
        attached.add(id);
      }
      return { sessionId: sid(id) };
    }
    case "Target.detachFromTarget": {
      const id = tabOf(params.sessionId);
      if (attached.delete(id)) {
        try { await chrome.debugger.detach({ tabId: id }); } catch (e) { /* closed */ }
      }
      return {};
    }
    case "Target.activateTarget": {
      const tab = await chrome.tabs.update(Number(params.targetId), { active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      return {};
    }
    case "AFH.group":
      await groupState(Number(params.targetId), params.state);
      return {};
    case "AFH.reload": // a newer version of this extension is in its folder
      setTimeout(() => chrome.runtime.reload(), 200);
      return {};
    case "Target.closeTarget":
      await chrome.tabs.remove(Number(params.targetId));
      return { success: true };
  }
  if (!sessionId) throw new Error(`${method} needs a tab`);
  const id = tabOf(sessionId);
  if (!attached.has(id)) throw new Error("That tab was closed, or AFH let go of it");
  return await chrome.debugger.sendCommand({ tabId: id }, method, params);
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (source.tabId != null && attached.has(source.tabId)) emit(method, params || {}, sid(source.tabId));
});

chrome.debugger.onDetach.addListener((source, reason) => {
  // the tab closed, or the user clicked Cancel on the "is debugging this browser" bar
  if (source.tabId != null && attached.delete(source.tabId)) emit("Target.detachedFromTarget", { sessionId: sid(source.tabId), reason });
});

chrome.tabs.onCreated.addListener((tab) => { if (discover) emit("Target.targetCreated", { targetInfo: info(tab) }); });
chrome.tabs.onUpdated.addListener((id, change, tab) => {
  if (discover && (change.url || change.title || change.status)) emit("Target.targetInfoChanged", { targetInfo: info(tab) });
});
chrome.tabs.onRemoved.addListener((id) => {
  attached.delete(id);
  if (discover) emit("Target.targetDestroyed", { targetId: String(id) });
});

// The popup asks for the state and pauses / resumes.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.q === "status") {
    reply({ state: paused ? "paused" : afh, problem, tabs: attached.size, browser: browserName(), id: chrome.runtime.id });
  } else if (msg?.q === "pause") {
    paused = !!msg.paused;
    chrome.storage.local.set({ paused });
    if (paused) {
      detachAll();
      try { port?.disconnect(); } catch (e) { /* gone */ }
      port = null;
      setState("paused");
    } else {
      setState("starting");
      connect();
    }
    reply({ ok: true });
  } else if (msg?.q === "retry") {
    connect();
    reply({ ok: true });
  }
  return false;
});

// Keep trying while AFH isn't set up yet; the helper itself waits for the app to open.
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.alarms.create("afh-connect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "afh-connect") connect(); });

chrome.storage.local.get("paused").then((s) => {
  paused = !!s.paused;
  if (paused) setState("paused");
  else connect();
});
