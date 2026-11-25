// The built-in browser (desktop app only): a side panel of <webview> tabs you browse in like a
// normal browser, which the agent's `browser` tool drives too. The page connects to
// /api/browser/host and relays the DevTools Protocol of its tabs (window.afh.browser, see
// desktop/browser-main.js); afh/engine/tools/browser.py (PanelHost) is the other end.
// While the agent works in a tab, a bar says so and a glass pane keeps stray clicks out:
// click it (or "Take over") and the tab is yours until you hand it back or send a new message.

import { socketUrl } from "./api.js";
import { el, icon, ico, toast } from "./ui.js";

const B = { tabs: [], active: null, ws: null, open: false, hooks: {}, nextKey: 1 };
const bridge = () => window.afh?.browser;
const $ = (id) => document.getElementById(id);
const HOME = "about:blank";

/** Sets up the panel; false when this window has no built-in browser (not the desktop app). */
export function initBrowser(hooks) {
  if (!bridge()) return false;
  B.hooks = hooks;
  buildPane();
  bridge().onEvent(onBridgeEvent);
  connect();
  return true;
}

export const browserOpen = () => B.open;

/** Shows or hides the panel; opening it with no tabs starts a blank one. */
export function toggleBrowser(force) {
  const open = force ?? !B.open;
  if (open === B.open) return;
  B.open = open;
  $("browser-pane").classList.toggle("open", open);
  B.hooks.onToggle?.(open);
  if (open && !B.tabs.length) newTab(HOME, { focus: true });
}

/** Opens a URL in a new tab of the panel (for "Open in browser" on design mockups and the like). */
export function openBrowserTab(url) {
  toggleBrowser(true);
  select(newTab(url));
}

/** The agent's bar follows its thread's run: call when a run starts or ends. */
export function syncBrowserRuns() {
  for (const t of B.tabs) if (t.sid) drawAgent(t);
}

// ---- connection to the backend ----------------------------------------------------------------

function connect() {
  let ws;
  try {
    ws = new WebSocket(socketUrl("/api/browser/host"));
  } catch {
    return setTimeout(connect, 3000);
  }
  ws.onopen = () => {
    B.ws = ws;
    // a reconnected backend starts with no agent tabs: the old ones become plain tabs
    for (const t of B.tabs) if (t.sid) { t.sid = null; t.paused = false; drawTab(t); drawAgent(t); }
  };
  ws.onmessage = (m) => {
    let msg;
    try {
      msg = JSON.parse(m.data);
    } catch {
      return;
    }
    handle(msg);
  };
  ws.onclose = () => {
    if (B.ws === ws) B.ws = null;
    setTimeout(connect, 2000);
  };
}

function post(msg) {
  if (B.ws?.readyState === WebSocket.OPEN) B.ws.send(JSON.stringify(msg));
}

async function handle(msg) {
  if (msg.op === "activity") return showActivity(msg);
  if (msg.id == null) return;
  try {
    post({ id: msg.id, result: (await run(msg)) ?? null });
  } catch (err) {
    post({ id: msg.id, error: String(err?.message || err) });
  }
}

async function run(msg) {
  if (msg.op === "open") {
    let tab = B.tabs.find((t) => t.sid === msg.sid);
    if (!tab) {
      tab = newTab(HOME, { sid: msg.sid });
      toggleBrowser(true);
      select(tab);
    }
    await tab.ready;
    await bridge().attach(tab.wcId);
    return { tab: String(tab.wcId) };
  }
  const tab = B.tabs.find((t) => String(t.wcId) === String(msg.tab));
  if (!tab) throw new Error("That browser tab was closed");
  if (msg.op === "cdp") {
    const p = msg.params || {};
    if (msg.method === "Input.dispatchMouseEvent" && p.type !== "mouseWheel") pointer(tab, p.x, p.y, p.type === "mousePressed");
    return bridge().send(tab.wcId, msg.method, p);
  }
  if (msg.op === "shot") {
    if (!B.open) toggleBrowser(true); // a hidden panel has nothing to capture
    if (document.visibilityState === "visible") await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); // let it paint
    return bridge().shot(tab.wcId, tab.wv.clientWidth);
  }
  if (msg.op === "close") {
    closeTab(tab, { quiet: true });
    return true;
  }
  throw new Error(`Unknown request ${msg.op}`);
}

function onBridgeEvent(ev) {
  const tab = B.tabs.find((t) => t.wcId === ev.id);
  if (!tab) return;
  if (ev.newTab) {
    select(newTab(ev.newTab));
    return;
  }
  if (ev.method && tab.sid) post({ event: { tab: String(tab.wcId), method: ev.method, params: ev.params || {} } });
}

// ---- the panel ----------------------------------------------------------------------------------

function buildPane() {
  const pane = $("browser-pane");
  const handle = el("div.bw-resize", { title: "Drag to resize" });
  const strip = el("div.bw-tabs", { id: "bw-tabs" });
  const add = el("button.bw-add", { type: "button", title: "New tab", html: icon("plus"), on: { click: () => select(newTab(HOME, { focus: true })) } });
  const close = el("button.icon-btn.bw-close", { type: "button", title: "Close the browser", html: icon("x"), on: { click: () => toggleBrowser(false) } });
  const nav = (name, title, fn) => el(`button.icon-btn.bw-${name}`, { type: "button", title, on: { click: fn } });
  const back = nav("back", "Back", () => B.active?.wv.goBack());
  const fwd = nav("fwd", "Forward", () => B.active?.wv.goForward());
  const reload = nav("reload", "Reload", () => (B.active?.loading ? B.active.wv.stop() : B.active?.wv.reload()));
  back.innerHTML = arrow("left");
  fwd.innerHTML = arrow("right");
  reload.innerHTML = icon("refresh");
  const addr = el("input.bw-addr", { id: "bw-addr", spellcheck: "false", placeholder: "Search or type a URL", autocomplete: "off" });
  addr.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      go(addr.value);
    } else if (e.key === "Escape") {
      addr.value = B.active ? shown(B.active.url) : "";
      addr.blur();
    }
  });
  addr.addEventListener("focus", () => addr.select());
  const ext = nav("ext", "Open in your browser", () => B.active && /^https?:/.test(B.active.url) && window.afh.openExternal(B.active.url));
  ext.innerHTML = icon("external");
  const view = el("div.bw-view", { id: "bw-view" },
    el("div.bw-empty", { id: "bw-empty" }, ico("globe"), el("b", "Browse the web"), el("span", "Type a URL or a search above. The agent opens its own tab here when it uses the browser, and you can watch or take over.")));
  pane.append(handle, el("div.bw-head", strip, add, el("span.bw-gap"), close), el("div.bw-bar", back, fwd, reload, el("div.bw-addr-wrap", ico("globe"), addr), ext), view);

  const saved = Number(localStorage.getItem("afh-browser-w")) || 0;
  if (saved) pane.style.setProperty("--browser-w", `${saved}px`);
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing-browser");
    const rtl = document.documentElement.dir === "rtl";
    const right = pane.getBoundingClientRect()[rtl ? "left" : "right"];
    let w = pane.getBoundingClientRect().width;
    const move = (ev) => {
      w = Math.round(Math.max(360, Math.min(innerWidth - 420, rtl ? ev.clientX - right : right - ev.clientX)));
      pane.style.setProperty("--browser-w", `${w}px`);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", () => {
      handle.removeEventListener("pointermove", move);
      document.body.classList.remove("resizing-browser");
      try {
        localStorage.setItem("afh-browser-w", String(w));
      } catch {}
    }, { once: true });
  });
}

const arrow = (dir) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${dir === "left" ? '<path d="M19 12H5M12 19l-7-7 7-7"/>' : '<path d="M5 12h14M12 5l7 7-7 7"/>'}</svg>`;

/** What the address bar shows for a URL. */
const shown = (url) => (!url || url === HOME ? "" : url);

/** A URL from what you typed: a URL as is, a host gets https:// (http:// for localhost), anything else is a search. */
export function toUrl(text) {
  const q = String(text || "").trim();
  if (!q) return HOME;
  if (/^(https?|file|about):/i.test(q)) return q;
  if (/^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?(\/.*)?$/i.test(q)) return `http://${q}`;
  if (!/\s/.test(q) && /^[^/]+\.[a-z]{2,}(:\d+)?(\/.*)?$/i.test(q)) return `https://${q}`;
  return `https://www.google.com/search?q=${encodeURIComponent(q)}`;
}

function go(text) {
  const url = toUrl(text);
  const tab = B.active || newTab(HOME);
  select(tab);
  if (tab.sid && !tab.paused) takeOver(tab); // typing a new address in the agent's tab takes it over
  tab.wv.loadURL(url).catch(() => {});
  tab.wv.focus();
}

function newTab(url, { sid = null, focus = false } = {}) {
  const wv = document.createElement("webview");
  wv.setAttribute("partition", bridge().partition);
  wv.setAttribute("allowpopups", "");
  wv.setAttribute("src", url || HOME);
  const tab = { key: B.nextKey++, wv, wcId: null, sid, paused: false, title: "", url: url || HOME, favicon: "", loading: false, what: "" };
  tab.ready = new Promise((resolve) => {
    wv.addEventListener("dom-ready", () => {
      if (tab.wcId == null) {
        tab.wcId = wv.getWebContentsId();
        resolve();
      }
    });
  });
  const refresh = () => { drawTab(tab); if (tab === B.active) drawBar(); };
  wv.addEventListener("did-start-loading", () => { tab.loading = true; refresh(); });
  wv.addEventListener("did-stop-loading", () => { tab.loading = false; refresh(); });
  wv.addEventListener("page-title-updated", (e) => { tab.title = e.title; refresh(); });
  wv.addEventListener("page-favicon-updated", (e) => { tab.favicon = e.favicons?.[0] || ""; refresh(); });
  const nav = (e) => { if (e.isMainFrame === false) return; tab.url = e.url; if (/^about:/.test(e.url)) tab.favicon = ""; refresh(); };
  wv.addEventListener("did-navigate", nav);
  wv.addEventListener("did-navigate-in-page", nav);
  wv.addEventListener("did-fail-load", (e) => {
    if (e.isMainFrame && e.errorCode !== -3) toast(`Couldn't open ${e.validatedURL}: ${e.errorDescription}`, "err");
  });
  wv.addEventListener("render-process-gone", () => toast("A browser tab crashed; reload it to try again", "err"));
  const glass = el("div.bw-glass", { title: "Click to take over from the agent", on: { pointerdown: (e) => { e.preventDefault(); takeOver(tab); } } });
  const bar = el("div.bw-agent");
  const cursor = el("div.bw-cursor", { html: '<svg viewBox="0 0 30 32" width="30" height="32"><defs><linearGradient id="bwcg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffbe55"/><stop offset=".42" stop-color="#ff7a3d"/><stop offset="1" stop-color="#ff4668"/></linearGradient></defs><path d="M6.6 4.2 25.2 12.1c1.9.8 1.7 3.5-.2 4.1l-7.1 2.1c-.6.2-1.1.6-1.4 1.2l-3.1 6.6c-.9 1.8-3.6 1.5-4-.5L4.1 6.8C3.7 5 5.1 3.6 6.6 4.2Z" fill="url(#bwcg)" stroke="#fff" stroke-width="1.9" stroke-linejoin="round"/></svg>' });
  const trail = el("div.bw-trail");
  const glow = el("div.bw-glow", el("i.haze"), el("i.breath"), el("div.runs", el("i.t"), el("i.r"), el("i.u"), el("i.l")), el("i.rim"), el("i.flare"));
  tab.frame = el("div.bw-frame", wv, glass, glow, trail, cursor, bar);
  tab.trail = trail;
  tab.glass = glass;
  tab.bar = bar;
  tab.cursor = cursor;
  tab.btn = el("div.bw-tab", { role: "tab", on: { mousedown: (e) => { if (e.button === 1) { e.preventDefault(); closeTab(tab); } }, click: () => select(tab) } });
  B.tabs.push(tab);
  $("bw-view").append(tab.frame);
  $("bw-tabs").append(tab.btn);
  drawTab(tab);
  drawAgent(tab);
  if (!B.active || focus || sid) select(tab);
  if (focus) setTimeout(() => $("bw-addr").focus(), 30);
  return tab;
}

function select(tab) {
  B.active = tab;
  for (const t of B.tabs) {
    t.frame.classList.toggle("on", t === tab);
    t.btn.classList.toggle("on", t === tab);
  }
  tab.btn.scrollIntoView({ block: "nearest", inline: "nearest" });
  drawBar();
}

function closeTab(tab, { quiet = false } = {}) {
  const i = B.tabs.indexOf(tab);
  if (i < 0) return;
  B.tabs.splice(i, 1);
  if (tab.sid && !quiet) post({ op: "closed", tab: String(tab.wcId) });
  if (tab.wcId != null) bridge().detach(tab.wcId).catch(() => {});
  tab.frame.remove();
  tab.btn.remove();
  if (B.active === tab) {
    B.active = null;
    if (B.tabs.length) select(B.tabs[Math.min(i, B.tabs.length - 1)]);
    else drawBar();
  }
}

function drawTab(tab) {
  const name = tab.title || (tab.url === HOME ? "New tab" : tab.url.replace(/^https?:\/\/(www\.)?/, ""));
  const fav = tab.loading ? el("span.spinner.bw-fav") : tab.favicon ? el("img.bw-fav", { src: tab.favicon, alt: "", on: { error: (e) => e.currentTarget.replaceWith(ico("globe")) } }) : ico(tab.sid ? "bot" : "globe");
  const who = tab.sid ? el("span.bw-who", { title: `The agent's tab for "${B.hooks.threadTitle?.(tab.sid) || "a thread"}"`, html: icon("bot") }) : null;
  tab.btn.title = `${name}${tab.sid ? ` — agent tab: ${B.hooks.threadTitle?.(tab.sid) || ""}` : ""}`;
  tab.btn.classList.toggle("agent", !!tab.sid);
  tab.btn.replaceChildren(...[fav, el("span.bw-name", name), who].filter(Boolean),
    el("button.bw-x", { type: "button", title: "Close tab", html: icon("x"), on: { click: (e) => { e.stopPropagation(); closeTab(tab); } } }));
}

function drawBar() {
  const tab = B.active;
  $("bw-empty").hidden = !!tab && tab.url !== HOME; // a blank tab shows the start message too
  for (const t of B.tabs) t.frame.classList.toggle("blank", t.url === HOME);
  const addr = $("bw-addr");
  if (document.activeElement !== addr) addr.value = tab ? shown(tab.url) : "";
  const pane = $("browser-pane");
  const ready = !!tab && tab.wcId != null;
  pane.querySelector(".bw-back").disabled = !ready || !tab.wv.canGoBack();
  pane.querySelector(".bw-fwd").disabled = !ready || !tab.wv.canGoForward();
  const reload = pane.querySelector(".bw-reload");
  reload.disabled = !tab;
  reload.innerHTML = icon(tab?.loading ? "x" : "refresh");
  reload.title = tab?.loading ? "Stop loading" : "Reload";
  pane.querySelector(".bw-ext").disabled = !tab || !/^https?:/.test(tab.url);
}

// ---- the agent in a tab ---------------------------------------------------------------------------

function drawAgent(tab) {
  const working = !!tab.sid && !!B.hooks.isBusy?.(tab.sid);
  const driving = working && !tab.paused;
  tab.frame.classList.toggle("driving", driving);
  tab.glass.hidden = !driving;
  if (!driving) {
    tab.cursor.classList.remove("show");
    tab.trail.classList.remove("show");
    tab.frame.classList.remove("acting");
  }
  if (!tab.sid || (!working && !tab.paused)) {
    tab.bar.hidden = true;
    return;
  }
  tab.bar.hidden = false;
  const thread = B.hooks.threadTitle?.(tab.sid) || "This thread";
  if (tab.paused) {
    tab.bar.replaceChildren(ico("user"), el("span.bw-msg", el("b", "You're in control"), el("small", `The agent of "${thread}" waits until you hand the tab back`)),
      el("button.btn.sm", { type: "button", on: { click: () => handBack(tab) } }, "Hand back"));
    return;
  }
  tab.bar.replaceChildren(el("span.bw-live"), el("span.bw-msg", el("b", "AFH is using this tab"), el("small", tab.what || thread)),
    el("button.btn.sm", { type: "button", title: "Use this tab yourself; the agent stops using it", on: { click: () => takeOver(tab) } }, "Take over"),
    el("button.btn.sm.danger", { type: "button", title: "Stop the agent's run", on: { click: () => B.hooks.stop?.(tab.sid) } }, ico("stop"), "Stop"));
}

function showActivity(msg) {
  const tab = B.tabs.find((t) => t.sid === msg.sid);
  if (!tab) return;
  tab.what = msg.what || "";
  drawAgent(tab);
  if (tab.paused) return;
  // the light runs while something is happening and settles between steps
  tab.frame.classList.add("acting");
  clearTimeout(tab.calm);
  tab.calm = setTimeout(() => tab.frame.classList.remove("acting"), 5000);
  if (msg.kind === "look") tab.frame.querySelector(".flare")?.animate([{ opacity: 0 }, { opacity: 1, offset: 0.3 }, { opacity: 0 }], { duration: 640, easing: "ease-in-out" });
  if (msg.x != null && msg.y != null) {
    pointer(tab, msg.x, msg.y, false);
    if (msg.kind === "drag" && msg.x2 != null) setTimeout(() => pointer(tab, msg.x2, msg.y2, true), 380);
  }
}

/** Moves the agent's pointer to x,y (page coordinates); a ripple when it clicks. */
function pointer(tab, x, y, press) {
  if (x == null || y == null || tab.paused) return;
  tab.cursor.classList.add("show");
  tab.trail.classList.add("show");
  tab.cursor.style.transform = `translate(${x - 5}px, ${y - 4}px)`; // the arrow's tip on the point
  tab.trail.style.transform = `translate(${x + 6}px, ${y + 7}px)`;
  if (press) {
    const burst = el("i.bw-burst", { style: { left: `${x}px`, top: `${y}px` } });
    const ring = el("i.bw-ring", { style: { left: `${x}px`, top: `${y}px` } });
    tab.frame.append(burst, ring);
    setTimeout(() => { burst.remove(); ring.remove(); }, 700);
  }
}

function takeOver(tab) {
  if (!tab.sid || tab.paused) return;
  tab.paused = true;
  post({ op: "takeover", sid: tab.sid });
  drawAgent(tab);
  tab.wv.focus();
  toast("You have the tab. The agent stops using it until you hand it back or send a message.", "ok", 5000);
}

function handBack(tab) {
  tab.paused = false;
  post({ op: "handback", sid: tab.sid });
  drawAgent(tab);
}

/** A new message to a thread hands its tab back (the backend does the same). */
export function browserHandBack(sid) {
  const tab = B.tabs.find((t) => t.sid === sid);
  if (tab?.paused) {
    tab.paused = false;
    drawAgent(tab);
  }
}
