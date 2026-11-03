import { BASE, api, connectEvents, hooks as apiHooks, native, remoteLogin } from "./api.js";
import { browserHandBack, initBrowser, openBrowserTab, syncBrowserRuns, toggleBrowser } from "./browser.js";
import { designHooks } from "./design.js";
import { ChatView, applyEvent, collectEdits, createThread, fmtCost, hooks, loadThread, viewImage } from "./chat.js";
import { D, closeWatch, delegationCard, initDelegate, onChildEvent, registerDelegation, renderSubagentsChip, renderWatch, subagentsOf, subagentsPopover, syncChildren, trackEvent } from "./delegate.js";
import { PRESETS, applyAppearance as applyTheme, themeTransition } from "./appearance.js";
import { applyLanguage } from "./i18n.js";
import { openPalette } from "./palette.js";
import { openContextEditor } from "./context.js";
import { initLive, liveState, onLiveEvent, renderLive } from "./livefile.js";
import { logoNode, setWorking } from "./logo.js";
import { openSettings } from "./settings.js";
import { openAccount, refreshAccountButton } from "./settings-remote.js";
import { exportThread, openImportDialog } from "./transfer-ui.js";
import { initUpdates } from "./updates.js";
import { initUsage, refreshUsage, renderUsage } from "./usage.js";
import { applyWorkEvent, goalsPopover, jobsPopover, loadJobs, openGoalDialog, renderDock, renderJobsChip, setRedraw, syncState } from "./work.js";
import {
  ago, basename, closePopover, confirmDialog, contextRing, dayGroup, diffView, el, escapeHtml, fmtTokens,
  hydrateIcons, ico, icon, modal, modalityBadges, popover, promptDialog, repositionPopover, toast,
} from "./ui.js";

const $ = (id) => document.getElementById(id);

export const S = {
  settings: null,
  models: [],
  defaultModel: null,
  agents: [],
  sessions: [],
  threads: new Map(),
  busy: new Set(),
  current: null,
  draft: { model: null, agent: null, mode: null, files: [], goal: null, worktree: false },
  search: "",
  drawer: null, // the open workbench tab: "live" | "changes" | "browser" | "context" | "harness" | "watch", or null when closed
};

const MODES = {
  ask: { label: "Ask first", icon: "shield", sub: "Approve file edits and commands" },
  full: { label: "Full access", icon: "zap", sub: "Edit files and run commands freely" },
  readonly: { label: "Read only", icon: "eye", sub: "Can read and search, never edit or run" },
};

const view = new ChatView($("messages"), $("thread"), {
  settings: () => S.settings,
  modelName: (ref) => modelName(ref),
  avatar: (live) => logoNode({ size: 28, working: live }),
  onFork: (id) => forkThread(id),
  onRetry: () => retryLast(),
  onRevert: (id) => revertTo(id),
  onChangeModel: () => modelMenu(),
  onStatus: () => { renderComposerState(); renderRail(); },
  onScroll: (stick, top) => {
    updateRailActive();
    $("jump").hidden = stick || !S.current;
    document.querySelector(".topbar").classList.toggle("scrolled", top > 4);
  },
});

// ---- boot -----------------------------------------------------------------------

/** The engine failed to start: show why and offer a retry. */
function showSetup(message) {
  if (document.querySelector(".setup-box")) return;
  $("boot-status").textContent = "";
  $("boot").append(el("div.setup-box",
    el("h3", "AFH couldn't start"),
    el("p", (message || "").slice(0, 300)),
    el("div", { style: { display: "flex", gap: "8px", justifyContent: "center", marginTop: "10px" } }, el("button.btn", { on: { click: () => location.reload() } }, ico("refresh"), "Retry")),
    el("details", { style: { marginTop: "8px" } }, el("summary", { style: { cursor: "pointer", color: "var(--text-3)", fontSize: "12px" } }, "Technical details"), el("pre.h-pre", { style: { textAlign: "left", maxWidth: "560px" } }, message || ""))));
}

function showLogin() {
  if (document.querySelector(".login-box")) return;
  $("boot-status").textContent = "";
  const pw = el("input.inp", { type: "password", placeholder: "Password", autocomplete: "current-password", style: { maxWidth: "260px" } });
  const err = el("div", { style: { color: "var(--bad)", fontSize: "12.5px", minHeight: "18px" } });
  const go = async () => {
    err.textContent = "";
    try {
      await remoteLogin(pw.value);
      location.reload();
    } catch (e) {
      err.textContent = e.message;
    }
  };
  pw.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  $("boot").append(el("div.login-box", el("div", { style: { marginBottom: "8px", color: "var(--text-2)" } }, "Enter the remote-control password set on the host computer."), pw, err, el("button.btn.primary", { on: { click: go } }, "Sign in")));
  setTimeout(() => pw.focus(), 50);
}

// Minimize / maximize / close drawn by the page (Windows, Linux), so they take part in theme
// changes and the title bar's border runs the full width. Native controls would be a separate
// opaque layer the page cannot animate. macOS keeps its inset traffic lights.
const WIN_ICONS = {
  min: '<svg viewBox="0 0 10 10"><path d="M0 5.5h10" stroke="currentColor" stroke-width="1"/></svg>',
  max: '<svg viewBox="0 0 10 10"><rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1"/></svg>',
  restore: '<svg viewBox="0 0 10 10"><path d="M2.5 2.5V0.5h7v7h-2" fill="none" stroke="currentColor" stroke-width="1"/><rect x="0.5" y="2.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1"/></svg>',
  close: '<svg viewBox="0 0 10 10"><path d="M0.5 0.5l9 9M9.5 0.5l-9 9" stroke="currentColor" stroke-width="1"/></svg>',
};

function mountWindowControls() {
  const w = window.afh.window;
  document.body.classList.add("win-controls");
  const max = el("button.wc-btn", { type: "button", title: "Maximize", html: WIN_ICONS.max, on: { click: () => w.maximize() } });
  const setMax = (on) => { max.innerHTML = on ? WIN_ICONS.restore : WIN_ICONS.max; max.title = on ? "Restore down" : "Maximize"; };
  $("titlebar").append(el("span.wc-space"), el("div.win-controls",
    el("button.wc-btn", { type: "button", title: "Minimize", html: WIN_ICONS.min, on: { click: () => w.minimize() } }),
    max,
    el("button.wc-btn.wc-close", { type: "button", title: "Close", html: WIN_ICONS.close, on: { click: () => w.close() } })));
  w.isMaximized().then(setMax).catch(() => {});
  window.afh.onEvent?.((ev) => { if (ev?.type === "maximized") setMax(!!ev.value); });
}

async function boot() {
  hydrateIcons();
  $("boot-mark").append(logoNode({ size: 110, working: true }));
  $("brand").prepend(logoNode({ size: 30, working: true }));
  $("tb-logo").append(logoNode({ size: 30, working: true }));
  apiHooks.onUnauthorized = () => showLogin();
  if (BASE) { // opened through the AFH account (phone app): a way back to the list of computers
    document.body.classList.add("via-relay");
    $("btn-account").replaceWith(el("a.sb-foot-btn", { href: "/account", title: "Your computers" }, ico("cpu"), "Your computers"));
  }
  initUpdates();
  initUsage({ names: () => S.providerNames });
  if (native.electron()) {
    document.body.classList.add("electron");
    $("tb-brand").append(logoNode({ size: 22 }));
    if (window.afh?.platform !== "darwin") mountWindowControls();
  }
  for (const [id, name] of [["btn-collapse", "sidebar"], ["btn-expand", "sidebar"], ["btn-thread-menu", "more"], ["btn-attach", "paperclip"], ["btn-mic", "mic"], ["btn-drawer-close", "x"]]) $(id).innerHTML = icon(name);
  let data;
  for (let attempt = 0; ; attempt++) {
    try {
      data = await api.get("/api/bootstrap");
      if (data.ready) break;
      if (data.error) throw new Error(data.error);
    } catch (e) {
      if (document.querySelector(".login-box")) return; // waiting for the remote password
      $("boot-status").textContent = `Couldn't start the engine: ${e.message}`;
      $("boot-status").classList.add("err");
      if (attempt > 0) return showSetup(e.message);
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  S.settings = data.settings;
  S.models = data.models;
  S.defaultModel = data.defaultModel;
  S.providerNames = data.providerNames || {};
  S.agents = data.agents;
  S.migration = data.migration || {};
  S.providersConfigured = !!data.providersConfigured;
  applyAppearance();
  applyChatWidth(S.settings.ui.chatWidth);
  initDelegate(ctx);
  initLive(ctx);
  // A file being written opens the Live tab, unless you are busy in the Browser, Context or Agents tab.
  ctx.openLive = () => { if (!S.drawer || S.drawer === "changes" || S.drawer === "harness") showTab("live"); };
  ctx.renderLive = () => { if (S.drawer === "live") renderLive(wbBody("live"), wbTitle("live")); };
  hooks.delegation = (p, o) => delegationCard(p, { ...o, onWatch: openWatch });
  wire();
  wireBrowser();
  connectEvents(onEvent, (state) => $("conn").className = "conn " + (state === "open" ? "ok" : "bad"));
  $("app").hidden = false;
  $("boot").classList.add("gone");
  setTimeout(() => $("boot")?.remove(), 600);
  await loadSessions();
  const last = S.settings.ui.reopenLast && S.settings.lastThread;
  if (last && S.sessions.some((s) => s.id === last)) await openThread(last);
  else showHome();
  $("input").focus();
  if (!S.providersConfigured) setTimeout(() => openSettings("models", ctx, { onboarding: true }), 400);
}

export function applyAppearance() {
  applyTheme(S.settings.ui);
  renderThemeButton();
  applyLanguage(S.settings.ui.language || "en", S.settings.ui.direction || "auto");
  const lb = $("btn-lang");
  if (lb) lb.replaceChildren(el("span.lang-mark", S.settings.ui.language === "ar" ? "EN" : "ع"));
}

/** Switch the interface language live (Arabic turns the layout right to left unless you chose a direction). */
async function setLanguage(language) {
  S.settings.ui = { ...S.settings.ui, language };
  applyAppearance();
  syncPills(); // the pill's offsets flip with the direction
  try { S.settings = await api.put("/api/settings", { ui: { language } }); } catch (err) { toast(err.message, "err"); }
}

// ---- one-click dark / light, with a circular reveal from the button ---------------------------

function renderThemeButton() {
  const b = $("btn-theme");
  if (!b) return;
  const dark = document.documentElement.dataset.theme === "dark";
  b.innerHTML = icon(dark ? "sun" : "moon");
  b.title = dark ? "Switch to light" : "Switch to dark";
}

async function toggleTheme(e) {
  const u = S.settings.ui;
  const dark = document.documentElement.dataset.theme === "dark";
  const next = dark ? "light" : "dark";
  const fav = PRESETS[next === "dark" ? u.darkPreset : u.lightPreset];
  const patch = { theme: next };
  if (u.preset !== "custom") {
    if (PRESETS[u.preset]) patch[dark ? "darkPreset" : "lightPreset"] = u.preset; // remember where you came from
    patch.preset = fav && fav.dark === (next === "dark") ? (next === "dark" ? u.darkPreset : u.lightPreset) : next === "dark" ? "sunset" : "paper";
    const p = PRESETS[patch.preset];
    Object.assign(patch, { accentOverride: false, bg: p.bg, text: p.text, accent: p.accent });
  }
  const apply = () => { S.settings.ui = { ...u, ...patch }; applyAppearance(); };
  themeTransition(u, apply, e?.currentTarget || $("btn-theme"));
  try { S.settings = await api.put("/api/settings", { ui: patch }); } catch (err) { toast(err.message, "err"); }
}

// ---- notifications --------------------------------------------------------------------

let audio = null;
function beep(kind = "done") {
  if (!S.settings.ui.sounds) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const notes = kind === "ask" ? [660, 880] : kind === "error" ? [330, 220] : [523, 784];
    notes.forEach((f, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = "sine"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, audio.currentTime + i * 0.12);
      g.gain.exponentialRampToValueAtTime(0.12, audio.currentTime + i * 0.12 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + i * 0.12 + 0.25);
      o.connect(g).connect(audio.destination);
      o.start(audio.currentTime + i * 0.12); o.stop(audio.currentTime + i * 0.12 + 0.3);
    });
  } catch {}
}

function notify(kind, title, body, onClick) {
  beep(kind);
  if (!S.settings.ui.notify || !("Notification" in window) || document.hasFocus()) return;
  const show = () => {
    const n = new Notification(title, { body, silent: true });
    if (onClick) n.onclick = () => { window.focus(); onClick(); };
  };
  if (Notification.permission === "granted") show();
  else if (Notification.permission !== "denied") Notification.requestPermission().then((p) => p === "granted" && show());
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => S.settings && applyAppearance());

export async function saveSettings(patch) {
  S.settings = await api.put("/api/settings", patch);
  applyAppearance();
  renderComposerState();
  return S.settings;
}

export async function reloadCatalog() {
  const [m, agents] = await Promise.all([api.get("/api/models"), api.get("/api/agents")]);
  S.models = m.models;
  S.defaultModel = m.defaultModel;
  S.providerNames = m.providerNames || {};
  S.agents = agents;
  renderComposerState();
}

// ---- projects & sessions ------------------------------------------------------------

const project = () => S.settings.lastProject;

async function loadSessions() {
  renderProjectPicker();
  checkGit();
  if (!project()) {
    S.sessions = [];
    return renderThreads();
  }
  try {
    S.sessions = await api.get(api.q("/api/sessions", { directory: project() }));
  } catch (e) {
    S.sessions = [];
    toast(e.message, "err");
  }
  renderThreads();
}

let refreshTimer = 0;
function refreshSessionsSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    if (!project()) return;
    try {
      S.sessions = await api.get(api.q("/api/sessions", { directory: project() }));
      renderThreads();
      renderTopbar();
    } catch {}
  }, 350);
}

function renderProjectPicker() {
  const btn = $("project-picker");
  btn.replaceChildren(ico("folder"), el("span.pp-name", project() ? basename(project()) : "Choose a project folder"), el("span.ico", { html: icon("chev-down") }));
  btn.title = project() || "";
  refreshMemory();
}

// ---- Memory: what the agent knows about the project, kept between threads (<project>/.afh/memory.md) ----
// The thread bar's Memory button opens it: add facts, edit or forget them, or edit the whole file as
// text. The agent reads it in every thread (on every step, so edits apply at once) and adds to it with
// its `memory` tool; its changes land here live.

const NO_MEMORY = { text: "", facts: 0, items: [], notes: "", path: "" };
let memory = { ...NO_MEMORY };
let memoryView = null; // { render, fresh } while the Memory dialog is open

function showMemoryCount() {
  const btn = $("btn-memory"), n = $("memory-count"), pill = $("draft-memory");
  const title = memory.facts ? `Memory: ${memory.facts} thing${memory.facts === 1 ? "" : "s"} the agent knows about this project` : "Memory: what the agent knows about this project";
  btn.hidden = !project() || !S.current;
  n.textContent = memory.facts ? String(memory.facts) : "";
  n.hidden = !memory.facts;
  btn.title = title;
  pill.hidden = !project() || !!S.current;
  pill.title = title;
  pill.replaceChildren(...[ico("book"), el("span.lbl", "Memory"), memory.facts ? el("span.mem-n", String(memory.facts)) : null].filter(Boolean));
}
async function refreshMemory() {
  if (!project()) { memory = { ...NO_MEMORY }; showMemoryCount(); return; }
  const dir = project();
  let next;
  try { next = await api.get(api.q("/api/projects/memory", { directory: dir })); } catch { next = { ...NO_MEMORY }; }
  if (dir !== project()) return; // switched projects while loading
  if (memoryView) memoryView.fresh = new Set((next.items || []).filter((f) => !memory.items.includes(f)));
  memory = next;
  showMemoryCount();
  memoryView?.render();
}
async function saveMemory(body, done) {
  try {
    const next = await api.put("/api/projects/memory", { directory: project(), ...body });
    if (memoryView) memoryView.fresh = new Set();
    memory = next;
    showMemoryCount();
    memoryView?.render();
    if (done) toast(done, "ok", 1400);
    return true;
  } catch (e) {
    toast(e.message, "err");
    return false;
  }
}
const memoryLines = (text) => text.split(/\r?\n/).map((s) => s.replace(/^\s*[-*•]\s+/, "").trim()).filter(Boolean);
async function rememberFacts(lines) {
  if (!project()) { toast("Open a project folder first", "info"); return false; }
  if (!memory.path) await refreshMemory();
  const have = new Set(memory.items.map((f) => f.toLowerCase()));
  const fresh = lines.filter((l) => !have.has(l.toLowerCase()));
  if (!fresh.length) { toast("Already in memory", "info", 1400); return true; }
  return saveMemory({ facts: [...memory.items, ...fresh] }, fresh.length > 1 ? `Remembered ${fresh.length} things` : "Remembered");
}

function openMemory() {
  if (!project() || memoryView) return;
  // editing: the fact being edited (by its text, so the agent changing the list meanwhile is harmless);
  // draft: what is typed in it so far, kept across redraws
  let mode = "list", editing = null, draft = "", loaded = "";
  const growTa = (ta) => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, 140) + "px"; };
  const addBox = el("textarea.inp", { rows: 1, placeholder: "Something the agent should always know here… e.g. “Run the tests with pnpm test”" });
  const add = async () => {
    const lines = memoryLines(addBox.value);
    if (lines.length && await rememberFacts(lines)) { addBox.value = ""; growTa(addBox); addBox.focus(); }
  };
  addBox.addEventListener("input", () => growTa(addBox));
  addBox.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); add(); } });
  const ta = el("textarea.ta.code.memory-ta", { placeholder: "# Project memory\n\n- Run the tests with `pnpm test`\n- The API needs the dev server on port 4000\n- Use British spelling in the UI" });
  const saveText = async () => {
    const before = loaded;
    loaded = ta.value; // our own save is not "the agent changed it"
    if (!await saveMemory({ text: ta.value }, "Saved — the agent sees it from its next step")) loaded = before;
  };
  const body = el("div.mem-body");
  const toggle = el("button.btn.ghost.sm", { on: { click: () => { mode = mode === "list" ? "text" : "list"; editing = null; if (mode === "text") { ta.value = memory.text; loaded = ta.value; } render(); } } });

  const edit = (f) => { editing = f; draft = f; render(); };
  const stopEditing = () => { editing = null; render(); };
  const setItem = async (f, value) => {
    const lines = memoryLines(value);
    const items = [...memory.items];
    const i = items.indexOf(f);
    if (i < 0) items.push(...lines); else items.splice(i, 1, ...lines);
    editing = null;
    await saveMemory({ facts: items }, lines.length ? "Updated" : "Forgotten");
  };
  const forget = (f) => saveMemory({ facts: memory.items.filter((x) => x !== f) }, "Forgotten");
  const row = (f) => {
    if (f === editing) {
      const inp = el("textarea.inp.mem-edit", { value: draft, rows: 1 });
      inp.addEventListener("input", () => { draft = inp.value; growTa(inp); });
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); setItem(f, inp.value); }
        if (e.key === "Escape") { e.stopPropagation(); stopEditing(); }
      });
      return el("div.mem-row.editing", el("span.mem-dot"), inp,
        el("div.mem-acts", { style: { opacity: 1 } },
          el("button.icon-btn", { title: "Save (Enter)", on: { click: () => setItem(f, inp.value) } }, ico("check")),
          el("button.icon-btn", { title: "Cancel (Esc)", on: { click: stopEditing } }, ico("x"))));
    }
    const fresh = memoryView?.fresh?.has(f);
    return el(`div.mem-row${fresh ? ".fresh" : ""}`,
      el("span.mem-dot"),
      el("div.mem-text", { title: "Click to edit", on: { click: () => edit(f) } }, f, fresh ? el("span.mem-by", "new") : null),
      el("div.mem-acts",
        el("button.icon-btn", { title: "Edit", on: { click: () => edit(f) } }, ico("edit")),
        el("button.icon-btn", { title: "Forget", on: { click: () => forget(f) } }, ico("trash"))));
  };
  const render = () => {
    toggle.replaceChildren(ico(mode === "list" ? "file" : "list"), mode === "list" ? "Edit as text" : "Back to list");
    if (mode === "text") {
      body.replaceChildren(ta, el("div.mem-foot",
        el("span.h-muted", "Lines starting with “- ” are facts; anything else is a note the agent reads too."),
        el("button.btn.primary.sm", { on: { click: saveText } }, ico("check"), "Save")));
      return;
    }
    if (editing !== null && !memory.items.includes(editing)) editing = null; // the agent changed or removed it meanwhile
    const list = memory.items.length
      ? el("div.mem-list", memory.items.map(row))
      : el("div.mem-empty", "Nothing remembered yet.", el("br"), "Add something above, or tell the agent “remember …” in any thread — it also saves what it learns on its own.");
    const hadFocus = body.contains(document.activeElement) && document.activeElement === addBox;
    body.replaceChildren(...[el("div.mem-add", addBox, el("button.btn.primary", { on: { click: add } }, ico("plus"), "Add")), list,
      memory.notes ? el("div.mem-notes", el("div.mem-notes-h", "Your notes"), el("pre", memory.notes)) : null].filter(Boolean));
    const inp = body.querySelector(".mem-edit");
    if (inp) { growTa(inp); inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    else if (hadFocus) addBox.focus();
  };
  const m = modal(el("div.memory-dialog",
    el("div.mem-head",
      el("div.grow",
        el("h3", ico("book"), "Memory"),
        el("div.mem-sub", `What the agent knows about ${basename(project())}: how to run it, its conventions, how you like things done. Every thread here reads it, the agent adds what it learns, and your changes apply from its next step.`),
        el("div.mem-path", memory.path || ""),
        el("div.mem-private", ico("shield-check"), "Private to this computer and kept out of git — tokens and logins are fine here. It's sent only to your model provider, as part of the prompt.")),
      toggle),
    memory.inGit ? el("div.mem-warn", ico("alert"), "This file was committed to git before, so git still tracks it. Run ", el("code", "git rm --cached .afh/memory.md"), " in the project before saving credentials here.") : null,
    body,
    el("div.actions", el("button.btn.ghost", { on: { click: () => m.close() } }, "Close"))),
    { small: true, onClose: () => { memoryView = null; } });
  memoryView = { fresh: new Set(), render: () => {
    if (mode === "text") {
      if (ta.value === loaded) { ta.value = memory.text; loaded = ta.value; }
      else if (memory.text !== loaded) toast("The agent just changed the memory; save or go back to the list to see it", "info", 4000);
      return;
    }
    render();
  } };
  render();
  refreshMemory();
  addBox.focus();
}
function onMemoryEvent(d) {
  if (!d || d.directory !== project()) return;
  refreshMemory();
}

async function chooseFolder() {
  let path = native.available() ? await native.pickFolder() : null;
  if (!path && !native.available()) path = await promptDialog({ title: "Open a project folder", label: "Folder path", placeholder: "C:\\Users\\you\\code\\my-app", confirm: "Open" });
  if (!path) return;
  try {
    S.settings = await api.post("/api/projects", { path });
    S.current = null;
    await loadSessions();
    showHome();
  } catch (e) {
    toast(e.message, "err");
  }
}

function projectMenu() {
  const items = [{ group: "Projects" }];
  for (const p of S.settings.projects) {
    items.push({ title: basename(p), sub: p, icon: "folder", checked: p === project(), onSelect: () => switchProject(p) });
  }
  if (S.settings.projects.length) items.push({ sep: true });
  items.push({ title: "Open folder…", icon: "folder-plus", onSelect: chooseFolder });
  if (project()) items.push({ title: "Import thread…", sub: "From an export file, OpenCode or Zadloop", icon: "arrow-down", onSelect: importThread });
  if (project()) items.push({ title: "Remove from list", sub: basename(project()), icon: "x", danger: true, onSelect: removeProject });
  popover($("project-picker"), items, { width: 300 });
}

async function switchProject(p) {
  S.settings = await api.post("/api/projects", { path: p });
  S.current = null;
  await loadSessions();
  showHome();
}

async function removeProject() {
  if (!(await confirmDialog({ title: "Remove project?", body: `${project()} will be removed from AFH's list. Its threads and files are kept.`, confirm: "Remove" }))) return;
  S.settings = await api.del("/api/projects", { path: project() });
  S.current = null;
  await loadSessions();
  showHome();
}

const shownThreads = new Set(); // rows already on screen don't replay their entrance animation
function renderThreads() {
  const box = $("threads");
  box.replaceChildren();
  if (!project()) {
    box.append(el("div.th-empty", "Open a folder to start.", el("div", el("button.btn.sm", { style: { marginTop: "10px" }, on: { click: chooseFolder } }, ico("folder-plus"), "Open folder"))));
    return;
  }
  const q = S.search.toLowerCase();
  const list = S.sessions.filter((s) => !q || (s.title || "").toLowerCase().includes(q));
  if (!list.length) {
    box.append(el("div.th-empty", q ? "No matching threads" : "No threads yet"));
    return;
  }
  let group = null;
  list.forEach((s, i) => {
    const t = s.time?.updated || s.time?.created;
    const g = dayGroup(t);
    if (g !== group) box.append(el("div.th-group", (group = g)));
    const seen = shownThreads.has(s.id);
    shownThreads.add(s.id);
    const st = threadStatus(s);
    const preview = threadPreview(s.id);
    const item = el(`button.th-item.${st}${S.current?.id === s.id ? ".active" : ""}`, {
      type: "button", title: s.title || "New thread", style: seen ? { animation: "none" } : { animationDelay: `${Math.min(i, 12) * 18}ms` },
      dataset: preview ? { preview } : null,
      on: { click: () => openThread(s.id) },
    },
      statusRing(st),
      s.metadata?.afh?.worktree ? el("span.th-wt", { title: `Worktree · ${s.metadata.afh.worktree.branch}`, html: icon("branch") }) : null,
      s.metadata?.afh?.goal ? el(`span.th-goal.${s.metadata.afh.goal.status}`, { title: `Goal (${s.metadata.afh.goal.status}): ${s.metadata.afh.goal.text}`, html: icon(s.metadata.afh.goal.status === "achieved" ? "check" : "target") }) : null,
      el("span.th-title", s.title || "New thread"),
      el("span.th-time", ago(t)),
      el("span.th-del", { title: "Delete thread", html: icon("trash"), on: { click: (e) => { e.stopPropagation(); deleteThread(s.id); } } }));
    box.append(item);
  });
}

async function openThread(id) {
  closePopover();
  let t = S.threads.get(id);
  const session = S.sessions.find((s) => s.id === id) || (await api.get(`/api/sessions/${id}`));
  if (!t) {
    t = createThread(session);
    S.threads.set(id, t);
  } else t.session = session;
  syncState(t);
  S.current = t;
  renderThreads();
  renderTopbar();
  if (!t.loaded) {
    view.mount({ ...t, messages: [], permissions: new Map() });
    try {
      await loadThread(t);
      if (t.busy) S.busy.add(t.id);
    } catch (e) {
      toast(e.message, "err");
    }
    syncChildren(t.id).then(() => { if (S.current === t) view.update({ all: true }); });
  }
  if (S.current !== t) return;
  view.mount(t);
  loadJobs(t).then(() => { if (S.current === t) renderWork(); });
  renderComposerState();
  refreshDrawer("thread");
  if (sidebarMode() === "hidden") { $("app").classList.remove("sb-open"); applySidebar(); } // phones: the overlay sidebar closes once a thread is picked
  $("input").focus();
  if (S.settings.lastThread !== id) { S.settings.lastThread = id; api.put("/api/settings", { lastThread: id }).catch(() => {}); }
}

function showHome() {
  S.current = null;
  S.draft.files = [];
  renderThreads();
  renderTopbar();
  renderComposerState();
  if (S.drawer !== "browser") closeDrawer(); // the browser is useful without a thread; the thread tabs are not
  const root = $("messages");
  view.thread = null;
  root.replaceChildren();
  renderRail();
  $("jump").hidden = true;
  if (!project()) {
    root.append(el("div.hero.no-project", logoNode({ size: 112 }), el("h2", "Welcome to Agent Flow Harness"),
      el("p", "Open a project folder and AFH will read, edit and run code there with any model you choose."),
      el("button.btn.primary", { on: { click: chooseFolder } }, ico("folder-plus"), "Open a folder")));
    return;
  }
  const name = S.settings.personalization?.name;
  const ideas = [
    ["book", "Explain this codebase", "Give me a tour of the architecture and the main entry points."],
    ["bug", "Find and fix a bug", "Run the tests, find what's failing, and fix it."],
    ["checklist", "Write tests", "Add tests for the parts of this project that have none."],
    ["diff", "Review my changes", "Review the uncommitted changes and point out problems."],
  ];
  // The welcome: a greeting for the time of day, the project as a chip, the last few threads as
  // cards with a status ring, and the suggested tasks as icon tiles. Same hooks as before (.hero,
  // .hero-proj, .suggest, .sg-ico); only the layout around them is new.
  const hour = new Date().getHours();
  const greet = hour < 5 ? "Good evening" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const recent = S.sessions.slice(0, 4);
  root.append(el("div.hero.hero-2",
    el("div.hero-top", el("span.hero-mark", logoNode({ size: 72, working: true })),
      el("div.hero-text",
        el("h2", name ? `${greet}, ${name}` : greet),
        el("p", el("span", "Working in"), el("span.hero-proj", ico("folder"), basename(project())), el("span.hero-sub", "What are we building?")))),
    recent.length ? el("section.hero-sec.hero-recent",
      el("h3.hero-h", ico("clock"), el("span", "Recent threads")),
      el("div.recent-cards", recent.map((s, i) => {
        const st = threadStatus(s);
        return el("button.recent-card", { type: "button", title: s.title || "New thread", style: { animationDelay: `${80 + i * 45}ms` }, on: { click: () => openThread(s.id) } },
          el("span.rc-top", statusRing(st), el("span.rc-time", ago(s.time?.updated || s.time?.created))),
          el("span.rc-title", s.title || "New thread"),
          el("span.rc-foot", el("span.rc-state", st === "running" ? "Working" : st === "done" ? "Done" : "New"), el("span.rc-go", ico("chev"))));
      }))) : null,
    el("section.hero-sec",
      el("h3.hero-h", ico("sparkle"), el("span", "Suggested tasks")),
      el("div.suggest", ideas.map(([icon, title, text], i) => el("button", { type: "button", dataset: { tone: String(i) }, style: { animationDelay: `${160 + i * 45}ms` }, on: { click: () => { setInput(text); $("input").focus(); } } },
        el("span.sg-ico", ico(icon)), el("b", title), el("span", text)))))));
}

/** "running" while the engine works on it, "done" once it has produced a reply, "idle" for a fresh thread. */
function threadStatus(s) {
  if (S.busy.has(s.id) || s.running) return "running";
  if (s.time?.idle || (s.tokens?.output || 0) > 0 || S.threads.get(s.id)?.messages?.some((m) => m.type === "assistant")) return "done";
  return "idle";
}

/** The status ring drawn in the thread list and on the welcome cards: a hollow ring, a pulsing one, or a check. */
function statusRing(status) {
  return el(`span.st-ring.${status}`, { title: status === "running" ? "Working" : status === "done" ? "Done" : "New" }, status === "done" ? ico("check") : null);
}

/** The last thing said in a thread we already have in memory, for the hover preview (no extra requests). */
function threadPreview(id) {
  const t = S.threads.get(id);
  if (!t?.messages?.length) return "";
  for (let i = t.messages.length - 1; i >= 0; i--) {
    const m = t.messages[i];
    const text = m.type === "user" ? m.text : m.type === "assistant" ? m.content?.filter((p) => p.type === "text").map((p) => p.text).join(" ") : "";
    if (text?.trim()) return text.replace(/\s+/g, " ").trim().slice(0, 160);
  }
  return "";
}

async function deleteThread(id) {
  const s = S.sessions.find((x) => x.id === id);
  if (S.settings.ui.confirmDelete !== false && !(await confirmDialog({ title: "Delete thread?", body: `"${s?.title || "New thread"}" and its history will be deleted. Files it changed are not reverted.`, confirm: "Delete", danger: true }))) return;
  try {
    const res = await api.del(`/api/sessions/${id}`);
    const kept = (res?.worktrees || []).filter((w) => w.kept);
    if (kept.length) toast(`Its worktree has unmerged work, so it was kept: ${kept[0].path}`, "info", 9000);
    S.sessions = S.sessions.filter((x) => x.id !== id);
    S.threads.delete(id);
    if (S.current?.id === id) showHome();
    else renderThreads();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function forkThread(messageId) {
  if (!S.current) return;
  const idx = S.current.messages.findIndex((m) => m.id === messageId);
  const next = S.current.messages.slice(idx + 1).find((m) => m.type === "user");
  try {
    const s = await api.post(`/api/sessions/${S.current.id}/fork`, next ? { before: next.id } : {});
    toast("Forked into a new thread", "ok");
    S.sessions.unshift(s);
    await openThread(s.id);
  } catch (e) {
    toast(e.message, "err");
  }
}

// ---- undo (revert) & context editing -----------------------------------------

async function reloadCurrent(id = S.current?.id) {
  if (!id) return;
  const t = S.threads.get(id);
  if (t) t.loaded = false;
  await openThread(id);
  refreshSessionsSoon();
}

async function revertTo(messageId) {
  const t = S.current;
  if (!t) return;
  const undone = t.messages.find((m) => m.id === messageId);
  let staged;
  try {
    staged = await api.post(`/api/sessions/${t.id}/revert`, { messageId, files: true });
  } catch (e) {
    return toast(e.message, "err", 6000);
  }
  const files = staged?.files?.length || 0;
  document.querySelector(".revert-bar")?.remove();
  const bar = el("div.revert-bar", ico("refresh"),
    el("span", el("b", "Rewound. "), `Messages after that point are set aside${files ? ` and ${files} file${files > 1 ? "s" : ""} restored on disk` : ""}. Keep it, or put everything back.`),
    el("button.btn.ghost.sm", { on: { click: async () => { try { await api.post(`/api/sessions/${t.id}/revert/clear`); } catch (e) { toast(e.message, "err"); } bar.remove(); reloadCurrent(t.id); } } }, "Put it back"),
    el("button.btn.primary.sm", { on: { click: async () => { try { await api.post(`/api/sessions/${t.id}/revert/commit`); toast("Undone", "ok"); } catch (e) { toast(e.message, "err"); } bar.remove(); reloadCurrent(t.id); } } }, ico("check"), "Keep"));
  await reloadCurrent(t.id);
  $("messages").prepend(bar);
  bar.scrollIntoView({ behavior: "smooth", block: "nearest" });
  // The message you undid goes back into the composer, ready to edit and send again.
  if (undone?.type === "user" && undone.text) {
    const input = $("input");
    input.value = undone.text;
    autosize();
    renderComposerState();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

function editContext() {
  const t = S.current;
  if (!t) return;
  openContextEditor(ctx, t, {
    onSaved: async (session) => {
      if (session.id !== t.id) {
        S.threads.delete(t.id);
        S.sessions = S.sessions.filter((s) => s.id !== t.id);
        S.sessions.unshift(session);
      }
      await reloadCurrent(session.id);
    },
  });
}

async function importThread() {
  if (!project()) return chooseFolder();
  openImportDialog(ctx, async (session) => {
    S.sessions.unshift(session);
    await openThread(session.id);
  });
}

async function renameThread() {
  const t = S.current;
  if (!t) return;
  const title = await promptDialog({ title: "Rename thread", value: t.session.title || "" });
  if (title == null || !title.trim()) return;
  await patchSession({ title: title.trim() });
}

async function patchSession(body) {
  const t = S.current;
  try {
    t.session = await api.patch(`/api/sessions/${t.id}`, body);
    const i = S.sessions.findIndex((s) => s.id === t.id);
    if (i >= 0) S.sessions[i] = t.session;
    renderThreads();
    renderTopbar();
    renderComposerState();
  } catch (e) {
    toast(e.message, "err");
  }
}

// ---- topbar ----------------------------------------------------------------------

const subChip = $("btn-subagents"); // lives inside the title, beside the thread name
function renderTopbar() {
  const box = $("tb-title");
  box.replaceChildren();
  const t = S.current;
  $("tb-thread").textContent = t ? t.session.title || "New thread" : project() ? basename(project()) : "";
  $("btn-thread-menu").hidden = !t;
  $("btn-changes").hidden = !t;
  $("btn-harness").hidden = !t;
  $("btn-context").hidden = !t;
  $("btn-live").hidden = !t;
  if (!t) {
    if (project()) box.append(el("span.tb-crumb", { title: project() }, ico("folder"), el("span.tb-path", basename(project()))));
    box.append(subChip);
    renderWork();
    syncPills();
    return;
  }
  // The title is a pill: click (or double-click) to rename in place, Enter saves, Esc cancels.
  const h = el("h1", { title: "Click to rename" }, el("span.tb-ttl", t.session.title || "New thread"), el("span.tb-edit", { html: icon("edit") }));
  const edit = () => {
    if (!h.isConnected) return;
    const input = el("input", { value: t.session.title || "" });
    let finished = false;
    const done = async (save) => {
      if (finished) return;
      finished = true;
      if (save && input.value.trim() && input.value !== t.session.title) await patchSession({ title: input.value.trim() });
      else renderTopbar();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    input.addEventListener("blur", () => done(true));
    h.replaceWith(input);
    input.focus();
    input.select();
  };
  h.addEventListener("click", edit);
  h.addEventListener("dblclick", edit);
  box.append(h, el("span.tb-crumb", { title: project() }, el("span.tb-sep"), ico("folder"), el("span.tb-path", basename(project()))), subChip);
  renderWork();
  syncPills();
}

// ---- the sliding pill behind the active chip of the segmented controls (top bar + workbench tabs) ----

const pillFor = new WeakMap();
function syncPill(group) {
  if (!group) return;
  let pill = pillFor.get(group);
  if (!pill) {
    pill = el("span.seg-pill", { "aria-hidden": "true" });
    group.prepend(pill);
    pillFor.set(group, pill);
    group.classList.add("has-pill");
  }
  const on = [...group.children].find((c) => c !== pill && c.classList.contains("on") && !c.hidden);
  if (!on) { pill.classList.remove("show"); return; }
  const first = !pill.classList.contains("show");
  if (first) pill.style.transition = "none"; // the first appearance lands in place instead of sliding in from the corner
  pill.style.width = `${on.offsetWidth}px`;
  pill.style.height = `${on.offsetHeight}px`;
  pill.style.transform = `translate(${on.offsetLeft}px, ${on.offsetTop}px)`;
  pill.classList.add("show");
  if (first) requestAnimationFrame(() => { pill.style.transition = ""; });
}
function syncPills() {
  requestAnimationFrame(() => { syncPill($("tb-seg")); syncPill($("wb-tabs")); });
}

// ---- message rail: one line per message of yours, click to jump back to it --------------------

let railIds = [];

function renderRail() {
  const rail = $("msg-rail");
  const t = S.current;
  const users = t ? t.messages.filter((m) => m.type === "user" && view.nodes.has(m.id)) : [];
  if (users.length < 2) {
    rail.classList.remove("on");
    if (railIds.length) rail.replaceChildren();
    railIds = [];
    return;
  }
  const ids = users.map((m) => m.id);
  if (ids.join() !== railIds.join()) {
    const known = new Set(railIds);
    railIds = ids;
    rail.replaceChildren(...users.map((m, i) => {
      const text = (m.command ? `/${m.command.name} ${m.command.args || ""}` : m.text || "").replace(/\s+/g, " ").trim();
      const when = m.time?.created ? new Date(m.time.created).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
      return el(`button.rail-tick${known.has(m.id) ? "" : ".new"}`, { type: "button", dataset: { id: m.id }, style: { "--i": String(Math.min(i, 40)) }, on: { click: () => jumpTo(m.id), mouseenter: (e) => showRailTip(e.currentTarget), mouseleave: hideRailTip } },
        el("i"),
        el("span.rail-tip", el("span.rail-meta", el("b", `#${i + 1}`), when ? el("em", when) : null), el("span.rail-text", text.slice(0, 140) || "(attachment)")));
    }));
    rail.classList.add("on");
  }
  updateRailActive();
}

let railTip = null;
function showRailTip(tick) {
  hideRailTip();
  const r = tick.getBoundingClientRect();
  railTip = el("div.rail-float", ...[...tick.querySelector(".rail-tip").childNodes].map((n) => n.cloneNode(true)));
  railTip.style.left = `${r.right + 12}px`;
  railTip.style.top = `${r.top + r.height / 2}px`;
  document.body.append(railTip);
}
function hideRailTip() {
  railTip?.remove();
  railTip = null;
}

let railFrame = 0;
function updateRailActive() {
  if (railFrame || !railIds.length) return;
  railFrame = requestAnimationFrame(() => {
    railFrame = 0;
    const line = $("thread").getBoundingClientRect().top + 110;
    let active = railIds[0];
    for (const id of railIds) {
      const n = view.nodes.get(id);
      if (n && n.getBoundingClientRect().top <= line) active = id;
    }
    for (const b of $("msg-rail").children) {
      const on = b.dataset.id === active;
      if (on && !b.classList.contains("active")) b.scrollIntoView({ block: "nearest" });
      b.classList.toggle("active", on);
    }
  });
}

function jumpTo(id) {
  const n = view.nodes.get(id);
  if (!n) return;
  view.stick = false;
  n.scrollIntoView({ behavior: document.body.classList.contains("no-anim") ? "auto" : "smooth", block: "start" });
  n.classList.remove("flash");
  void n.offsetWidth; // restart the highlight
  n.classList.add("flash");
}

// ---- chat width: drag the handle at the column's edge ------------------------------------------

const CHAT_W = 920; // the reading column
function applyChatWidth(w) {
  document.documentElement.style.setProperty("--chat-w", `${Math.max(560, Math.min(2400, Number(w) || CHAT_W))}px`);
}

function wireResize() {
  const h = $("chat-resize");
  h.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    h.setPointerCapture(e.pointerId);
    const box = document.querySelector(".main").getBoundingClientRect();
    const center = box.left + box.width / 2;
    let w = CHAT_W;
    document.body.classList.add("resizing");
    const move = (ev) => {
      w = Math.round(Math.max(560, Math.min(box.width - 40, 2 * Math.abs(ev.clientX - center) + 40)));
      applyChatWidth(w);
    };
    const up = () => {
      h.removeEventListener("pointermove", move);
      document.body.classList.remove("resizing");
      saveSettings({ ui: { chatWidth: w } }).catch(() => {});
    };
    h.addEventListener("pointermove", move);
    h.addEventListener("pointerup", up, { once: true });
  });
  h.addEventListener("dblclick", () => { applyChatWidth(CHAT_W); saveSettings({ ui: { chatWidth: CHAT_W } }).catch(() => {}); toast("Chat width reset", "info", 1200); });
}

// ---- command palette ---------------------------------------------------------------------------

/** The built-in browser panel (desktop app): the Browser button, Ctrl+Shift+B, and what the panel needs to know. */
function wireBrowser() {
  const on = initBrowser({
    threadTitle: (sid) => S.sessions.find((s) => s.id === sid)?.title || "",
    isBusy: (sid) => S.busy.has(sid) || !!S.threads.get(sid)?.busy,
    stop: (sid) => api.post(`/api/sessions/${sid}/interrupt`).catch((e) => toast(e.message, "err")),
    // The panel lives in the workbench's Browser tab: "open" means that tab is showing.
    onToggle: (open) => { if (open !== (S.drawer === "browser")) (open ? showTab("browser") : closeDrawer()); },
  });
  if (!on) return;
  designHooks.openInBrowser = openBrowserTab;
  $("btn-browser").hidden = false;
  wbTab("browser").hidden = false;
  $("btn-browser").addEventListener("click", () => openDrawer("browser"));
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "b") {
      e.preventDefault();
      toggleBrowser();
    }
  });
}

function showPalette() {
  const t = S.current;
  const items = [
    { group: "Actions", title: "New thread", icon: "plus", sub: "Ctrl+N", run: () => { showHome(); $("input").focus(); } },
    { group: "Actions", title: document.documentElement.dataset.theme === "dark" ? "Switch to light" : "Switch to dark", icon: "sun", keywords: "theme mode dark light", run: () => toggleTheme() },
    { group: "Actions", title: S.settings.ui.language === "ar" ? "English interface" : "العربية — Arabic interface", icon: "languages", keywords: "language arabic rtl", run: () => setLanguage(S.settings.ui.language === "ar" ? "en" : "ar") },
    { group: "Actions", title: "Set a goal", icon: "target", run: () => editGoal() },
    ...($("btn-browser").hidden ? [] : [{ group: "Actions", title: "Browser", icon: "globe", sub: "Ctrl+Shift+B", keywords: "web page internet tab", run: () => openDrawer("browser") }]),
    { group: "Actions", title: "Open folder…", icon: "folder-plus", run: chooseFolder },
    { group: "Actions", title: "Import thread…", icon: "arrow-down", run: importThread },
    ...(t ? [
      { group: "Thread", title: "Compact now", icon: "archive", sub: "Summarise older messages", run: () => localCommand("/compact") },
      { group: "Thread", title: "Live", icon: "eye", run: () => openDrawer("live") },
      { group: "Thread", title: "Changes", icon: "diff", run: () => openDrawer("changes") },
      { group: "Thread", title: "Prompt", icon: "scroll", run: () => openDrawer("harness") },
      { group: "Thread", title: "Context", icon: "list", run: () => openDrawer("context") },
      { group: "Thread", title: "Context editor", icon: "edit", run: editContext },
      { group: "Thread", title: "Rename", icon: "edit", run: renameThread },
      { group: "Thread", title: "Fork thread", icon: "branch", run: () => forkThread(t.messages.at(-1)?.id) },
    ] : []),
    ...[["general", "General"], ["appearance", "Appearance"], ["agent", "Agent"], ["delegation", "Delegation"], ["models", "Models & providers"], ["usage", "Usage & cost"], ["skills", "Skills"], ["mcp", "MCP servers"], ["prompts", "Prompts & agents"], ["commands", "Commands"], ["hooks", "Hooks"], ["schedules", "Schedules"], ["developer", "Developer"], ["remote", "Remote control"], ["bug", "Report a bug"], ["about", "About"]]
      .map(([id, label]) => ({ group: "Settings", title: label, icon: "settings", keywords: "settings", run: () => openSettings(id, ctx) })),
    ...S.sessions.slice(0, 80).map((s) => ({ group: "Threads", title: s.title || "New thread", sub: ago(s.time?.updated), icon: s.metadata?.afh?.goal ? "target" : "list", run: () => openThread(s.id) })),
    ...S.models.map((m) => ({ group: "Models", title: m.name, sub: providerName(m.providerID), icon: "cpu", keywords: m.id, run: () => chooseModel({ id: m.id, providerID: m.providerID }) })),
    ...Object.entries(PRESETS).map(([id, p]) => ({ group: "Themes", title: p.name, sub: p.dark ? "dark" : "light", icon: p.dark ? "moon" : "sun", keywords: "theme color", run: () => applyPreset(id) })),
  ];
  openPalette(items);
}

async function applyPreset(id) {
  const p = PRESETS[id];
  const patch = { preset: id, accentOverride: false, bg: p.bg, text: p.text, accent: p.accent, theme: p.dark ? "dark" : "light", [p.dark ? "darkPreset" : "lightPreset"]: id };
  const apply = () => { S.settings.ui = { ...S.settings.ui, ...patch }; applyAppearance(); };
  themeTransition(S.settings.ui, apply, $("btn-theme"));
  try { S.settings = await api.put("/api/settings", { ui: patch }); } catch (err) { toast(err.message, "err"); }
}

// ---- the workbench can be dragged wider or narrower (its left edge); the width is remembered -------

const WB_W_KEY = "afh-wb-w";
function wireDrawerResize() {
  const wb = $("workbench");
  const handle = $("wb-resize");
  let saved = 0;
  try { saved = Number(localStorage.getItem(WB_W_KEY)) || 0; } catch {}
  saved = saved || Number(S.settings.ui.drawerWidth) || 0;
  if (saved) wb.style.setProperty("--wb-w", `${saved}px`);
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing-drawer");
    const rtl = document.documentElement.dir === "rtl";
    let w = wb.getBoundingClientRect().width;
    const move = (ev) => {
      w = Math.round(Math.max(320, Math.min(innerWidth - 360, rtl ? ev.clientX : innerWidth - ev.clientX)));
      wb.style.setProperty("--wb-w", `${w}px`);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", () => {
      handle.removeEventListener("pointermove", move);
      document.body.classList.remove("resizing-drawer");
      try { localStorage.setItem(WB_W_KEY, String(w)); } catch {}
      saveSettings({ ui: { drawerWidth: w } }).catch(() => {});
    }, { once: true });
  });
  handle.addEventListener("dblclick", () => {
    wb.style.removeProperty("--wb-w");
    try { localStorage.removeItem(WB_W_KEY); } catch {}
    saveSettings({ ui: { drawerWidth: 0 } }).catch(() => {});
  });
}

// ---- goal, to-do list, background jobs, worktree ------------------------------------------

function renderWork() {
  const t = S.current;
  renderDock($("work-dock"), t, { busy: !!t && (t.busy || S.busy.has(t.id)), onEditGoal: () => editGoal(), onChanged: renderWork });
  renderJobsChip($("jobs-pill"), t);
  renderSubagentsChip(subChip, t);
  const gb = $("btn-goal");
  gb.hidden = !t;
  const g = t?.goal;
  gb.classList.toggle("on", !!g && g.status === "active");
  gb.classList.toggle("achieved", g?.status === "achieved");
  gb.title = g ? `Goal: ${g.text}` : "Set a goal: the agent keeps working until it is achieved";
  const wt = t?.session?.metadata?.afh?.worktree;
  const wb = $("btn-worktree");
  wb.hidden = !wt;
  if (wt) wb.replaceChildren(ico("branch"), el("span.wt-branch", wt.branch.replace(/^afh\//, "")));
  // Draft pills: only before the thread exists.
  const dg = $("draft-goal"), dw = $("draft-worktree");
  dg.hidden = !!t || !project();
  dg.classList.toggle("on", !!S.draft.goal);
  dg.replaceChildren(ico("target"), el("span.lbl", S.draft.goal ? "Goal set" : "Goal"));
  dg.title = S.draft.goal ? `Goal: ${S.draft.goal.text} — click to edit` : "Set a goal for the new thread";
  showMemoryCount();
  dw.hidden = !!t || !project() || !S.gitRepo;
  dw.classList.toggle("on", !!S.draft.worktree);
  dw.replaceChildren(ico("branch"), el("span.lbl", S.draft.worktree ? "Worktree" : "Worktree"));
}
setRedraw(() => renderWork());

function editGoal() {
  const t = S.current;
  if (!t) {
    openGoalDialog({ draft: S.draft.goal, onDraft: (g) => { S.draft.goal = g; renderWork(); }, onStart: (g) => startWithGoal(g) });
    return;
  }
  openGoalDialog({ thread: t, busy: t.busy || S.busy.has(t.id), onSaved: () => renderWork() });
}

/** Home screen "Start now": a new thread with the goal, and the first message toward it. */
async function startWithGoal(g) {
  const text = $("input").value.trim();
  $("input").value = "";
  autosize();
  await submit(text || `Work toward the goal of this thread:\n\n${g.text}`);
}

async function checkGit() {
  S.gitRepo = false;
  if (!project()) return;
  try { S.gitRepo = (await api.get(api.q("/api/git/check", { directory: project() }))).repo; } catch {}
  renderWork();
}

async function worktreeMenu() {
  const t = S.current;
  const wt = t?.session?.metadata?.afh?.worktree;
  if (!wt) return;
  const box = el("div.wt-pop", el("div.empty-row", el("span.spinner")));
  popover($("btn-worktree"), [], { header: box, width: 340, align: "right" });
  let st;
  try { st = await api.get(`/api/sessions/${t.id}/worktree`); } catch (e) { box.replaceChildren(el("div.empty-row", e.message)); return; }
  const act = (label, iconName, fn, cls = "") => el(`button.pop-item${cls}`, { type: "button", on: { click: () => { closePopover(); fn(); } } }, ico(iconName), el("div.pi-main", el("div.pi-title", label)));
  box.replaceChildren(
    el("h4", ico("branch"), "Worktree"),
    el("div.ctx-row", el("span", "Branch"), el("b", st.branch)),
    el("div.ctx-row", el("span", "Made from"), el("b", st.base || "—")),
    el("div.ctx-row", el("span", "Changes"), el("b", st.exists ? `${st.dirty.length} uncommitted · ${st.ahead} commit${st.ahead === 1 ? "" : "s"}${st.merged ? " · merged" : ""}` : "folder is gone")),
    el("div.wt-path", { title: st.path }, st.path),
    el("div.pop-sep"),
    st.exists && (st.dirty.length || (st.ahead && !st.merged)) ? act(`Merge into ${st.base || "the main branch"}`, "git-merge", () => mergeWorktree(t)) : null,
    act("Copy folder path", "copy", async () => { await navigator.clipboard.writeText(st.path); toast("Path copied", "ok", 1400); }),
    act("Open the folder", "folder", () => api.post("/api/reveal", { path: st.path }).catch((e) => toast(e.message, "err"))),
    act("Remove worktree…", "trash", () => removeWorktree(t, st), ".danger"));
  repositionPopover();
}

async function mergeWorktree(t) {
  if (!(await confirmDialog({ title: "Merge this thread's branch?", body: "AFH commits any uncommitted changes in the worktree, then merges its branch into the branch your project folder is on. If there are conflicts nothing is changed.", confirm: "Merge" }))) return;
  try {
    const r = await api.post(`/api/sessions/${t.id}/worktree/merge`);
    toast(`Merged into ${r.into}`, "ok", 4000);
  } catch (e) {
    toast(e.message, "err", 9000);
  }
}

async function removeWorktree(t, st) {
  const unsaved = st.dirty.length || (st.ahead && !st.merged);
  if (!(await confirmDialog({ title: "Remove the worktree?", body: unsaved ? `It still has ${st.dirty.length} uncommitted file(s) and ${st.ahead} unmerged commit(s) — they will be lost. The thread stays.` : "The folder and its branch are deleted. The thread stays.", confirm: "Remove", danger: true }))) return;
  try {
    await api.post(`/api/sessions/${t.id}/worktree/remove`, { force: true });
    toast("Worktree removed", "ok");
  } catch (e) {
    toast(e.message, "err");
  }
}

function threadMenu() {
  const t = S.current;
  if (!t) return;
  popover($("btn-thread-menu"), [
    { title: "Rename", icon: "edit", onSelect: renameThread },
    { title: "Fork thread", icon: "branch", onSelect: () => forkThread(t.messages.at(-1)?.id) },
    { title: "Edit context…", sub: "Change or remove anything the model sees", icon: "list", onSelect: editContext },
    { title: "Export thread…", sub: "Save as .afh-session.json to share or move", icon: "arrow-down", onSelect: () => exportThread(t.id, t.session.title) },
    { title: "Copy as Markdown", icon: "copy", onSelect: copyThread },
    { title: "Archive", icon: "archive", onSelect: async () => { await patchSession({ archived: true }); S.sessions = S.sessions.filter((s) => s.id !== t.id); showHome(); toast("Thread archived", "ok"); } },
    { sep: true },
    { title: "Delete", icon: "trash", danger: true, onSelect: () => deleteThread(t.id) },
  ], { align: "right", width: 220 });
}

async function copyThread() {
  const lines = [];
  for (const m of S.current.messages) {
    if (m.type === "user") lines.push(`## You\n\n${m.text}`);
    if (m.type === "assistant") {
      const text = m.content.filter((p) => p.type === "text").map((p) => p.text).join("\n\n");
      if (text) lines.push(`## Assistant\n\n${text}`);
    }
  }
  await navigator.clipboard.writeText(lines.join("\n\n"));
  toast("Thread copied", "ok");
}

// ---- the workbench: one right-hand panel with tabs (Live, Changes, Browser, Context, Prompt, Agents) ----
// Each tab keeps its own body, so switching never loses what was drawn. `openDrawer`/`closeDrawer`
// keep their old names and toggle semantics for the chips, the palette and the live pane.

const WB_TABS = ["live", "changes", "browser", "context", "harness", "watch"];
const WB_CHIP = { live: "btn-live", changes: "btn-changes", browser: "btn-browser", context: "btn-context", harness: "btn-harness" };
const WB_TAB_KEY = "afh-wb-tab";
const wbTab = (kind) => document.querySelector(`#wb-tabs .wb-tab[data-tab="${kind}"]`);
const wbPane = (kind) => document.querySelector(`#wb-panes .wb-pane[data-pane="${kind}"]`);
const wbBody = (kind) => document.querySelector(`#wb-panes [data-body="${kind}"]`);
const wbTitle = (kind) => document.querySelector(`#wb-panes [data-title="${kind}"]`);
const wbDrawn = { context: null }; // which thread the Context tab was drawn for (it is a full editor; redraw only when needed)

/** Toggle a tab: clicking the chip of the open tab closes the workbench, anything else shows that tab. */
function openDrawer(kind) {
  if (S.drawer === kind) return closeDrawer();
  showTab(kind);
}

/** Show a tab (never closes). */
function showTab(kind) {
  if (!WB_TABS.includes(kind)) return;
  const was = S.drawer;
  S.drawer = kind;
  const wb = $("workbench");
  wb.classList.add("open");
  wb.setAttribute("aria-hidden", "false");
  for (const k of WB_TABS) {
    wbPane(k).hidden = k !== kind;
    wbTab(k).classList.toggle("on", k === kind);
    wbTab(k).setAttribute("aria-selected", String(k === kind));
    const chip = WB_CHIP[k] && $(WB_CHIP[k]);
    if (chip) chip.classList.toggle("on", k === kind);
  }
  if (kind === "watch") wbTab("watch").hidden = false;
  if (kind === "browser") toggleBrowser(true); // the panel's own "open" flag (screenshots need a visible pane)
  else if (was === "browser") toggleBrowser(false);
  try { localStorage.setItem(WB_TAB_KEY, kind); } catch {}
  refreshDrawer("open");
  syncPills();
}

function closeDrawer() {
  const was = S.drawer;
  if (was === "watch") closeWatch();
  S.drawer = null;
  const wb = $("workbench");
  wb.classList.remove("open");
  wb.setAttribute("aria-hidden", "true");
  for (const k of WB_TABS) {
    wbTab(k).classList.remove("on");
    const chip = WB_CHIP[k] && $(WB_CHIP[k]);
    if (chip) chip.classList.remove("on");
  }
  if (was === "browser") toggleBrowser(false);
  syncWatchTab();
  syncPills();
}

/** Reopen the workbench on the tab it was last on (the close button's counterpart: Ctrl+Shift+W). */
function reopenWorkbench() {
  let last = null;
  try { last = localStorage.getItem(WB_TAB_KEY); } catch {}
  if (!last || !WB_TABS.includes(last) || wbTab(last).hidden) last = "live";
  showTab(last);
}

/** The Agents tab shows only when there is something to show: a watched subagent or subagents in this thread. */
function syncWatchTab() {
  const t = S.current;
  wbTab("watch").hidden = !D.watch && !(t && subagentsOf(t).length);
}

function openWatch(childId) {
  D.watch = childId;
  if (S.drawer !== "watch") showTab("watch");
  else refreshDrawer("open");
}

/** Redraw the open tab. `reason`: "open" (tab shown), "thread" (another thread), "changes" (a tool finished), "run" (a run ended). */
async function refreshDrawer(reason = "changes") {
  const t = S.current;
  updateChangesBadge();
  syncWatchTab();
  if (!S.drawer || S.drawer === "browser") return;
  if (!t) {
    for (const k of WB_TABS) if (k !== "browser") { wbBody(k).replaceChildren(el("div.drawer-empty", ico(wbTab(k).querySelector(".ico").dataset.icon || "list"), el("div", "Open a thread to use the workbench."))); wbTitle(k).replaceChildren(); }
    wbDrawn.context = null;
    return;
  }
  const body = wbBody(S.drawer), title = wbTitle(S.drawer);
  if (S.drawer === "watch") {
    if (!D.watch) {
      title.replaceChildren(ico("bot"), el("span", "Agents"));
      const all = subagentsOf(t);
      body.replaceChildren(all.length ? el("div.wb-agents", all.map((p) => delegationCard(p, { thread: t, open: new Set(), onWatch: openWatch }))) : el("div.drawer-empty", ico("bot"), el("div", "No subagents in this thread yet.")));
      return;
    }
    await renderWatch(body, title, { onOpenAsThread: (id) => { closeDrawer(); openThread(id); } });
    return;
  }
  if (S.drawer === "live") {
    renderLive(body, title);
    return;
  }
  if (S.drawer === "context") {
    // A full editor: draw it when the tab opens, the thread changes or a run ends — not on every tool call.
    if (reason === "changes" && wbDrawn.context === t.id) return;
    wbDrawn.context = t.id;
    title.replaceChildren(ico("list"), el("span", "Context"), el("button.btn.ghost.sm", { title: "Open in a dialog", on: { click: editContext } }, ico("external")));
    body.replaceChildren(el("div.drawer-empty", el("span.spinner")));
    await openContextEditor(ctx, t, { mount: body, onSaved: async (session) => {
      if (session.id !== t.id) {
        S.threads.delete(t.id);
        S.sessions = S.sessions.filter((s) => s.id !== t.id);
        S.sessions.unshift(session);
      }
      wbDrawn.context = null;
      await reloadCurrent(session.id);
    } });
    return;
  }
  if (S.drawer === "changes") {
    title.replaceChildren(ico("diff"), "Changes");
    let diffs = [];
    try {
      diffs = await api.get(`/api/sessions/${t.id}/diff`);
    } catch {}
    const source = diffs.length ? "git" : "thread";
    if (!diffs.length) diffs = collectEdits(t);
    body.replaceChildren();
    if (!diffs.length) {
      body.append(el("div.drawer-empty", ico("diff"), el("div", "No file changes in this thread yet.")));
      return;
    }
    const add = diffs.reduce((a, d) => a + (d.additions || 0), 0), del = diffs.reduce((a, d) => a + (d.deletions || 0), 0);
    body.append(el("div.h-muted", { style: { marginBottom: "12px", fontStyle: "normal" } },
      `${diffs.length} file${diffs.length > 1 ? "s" : ""} · `, el("span", { style: { color: "var(--add-ink)" } }, `+${add}`), " ", el("span", { style: { color: "var(--del-ink)" } }, `−${del}`),
      source === "thread" ? " · from this thread's edits" : " · working tree vs. thread start"));
    diffs.forEach((d, i) => {
      const card = el(`div.file-diff${diffs.length <= 3 ? ".open" : ""}`, { style: { animationDelay: `${i * 30}ms` } });
      card.append(el("button.file-diff-head", { type: "button", on: { click: () => card.classList.toggle("open") } },
        el(`span.st.${d.status || "modified"}`, (d.status || "modified").slice(0, 1).toUpperCase()),
        el("span.fn", { title: d.file }, d.file),
        el("span.tool-stat", el("span.plus", `+${d.additions ?? 0}`), el("span.minus", `−${d.deletions ?? 0}`))),
        diffView(d.patch));
      body.append(card);
    });
  } else {
    title.replaceChildren(ico("scroll"), "What the model is told");
    body.replaceChildren(el("div.drawer-empty", el("span.spinner")));
    try {
      const h = await api.get(`/api/sessions/${t.id}/harness`);
      body.replaceChildren(...renderHarness(h));
    } catch (e) {
      body.replaceChildren(el("div.drawer-empty", e.message));
    }
  }
}

function renderHarness(h) {
  const sec = (title, content, action) => el("div.h-section", el("h4", title, action || null), content);
  const pre = (text, empty) => (text && text.trim() ? el("pre.h-pre", text) : el("div.h-muted", empty));
  const edit = (tab) => el("button.btn.ghost.sm", { on: { click: () => openSettings("prompts", ctx, { agent: h.agent }) } }, ico("edit"), "Edit");
  const out = [
    el("div.note", "Assembled in this order: the mode's system prompt → goal & project memory → AGENTS.md files → personalization → skills → MCP instructions → date & environment. This is the full text the model receives."),
    sec("Agent · model", el("div", el("span.tag", h.agent), h.model ? el("span.tag", `${h.model.providerID}/${h.model.id}${h.model.variant && h.model.variant !== "default" ? "#" + h.model.variant : ""}`) : el("span.tag", "default model"))),
    sec("System prompt (exactly as sent)", pre(h.systemPrompt, "Empty."), edit()),
    sec("Tools available", el("div", (h.tools || []).map((t) => el("span.tag", t)))),
    sec("Personalization", pre(h.personalization, "Nothing set."), el("button.btn.ghost.sm", { on: { click: () => openSettings("personalization", ctx) } }, ico("edit"), "Edit")),
    sec("Global AGENTS.md", pre(h.globalInstructions, "Empty."), edit()),
    sec("Project AGENTS.md", pre(h.projectInstructions, "No AGENTS.md in this project."), edit()),
    sec("Project memory", pre(h.memory, "Nothing remembered yet."), el("button.btn.ghost.sm", { on: { click: openMemory } }, ico("edit"), "Edit")),
  ];
  const msgs = h.systemMessages || [];
  out.push(sec(`Injected instructions (${msgs.length})`, msgs.length
    ? el("div", msgs.map((m) => el("div", { style: { marginBottom: "10px" } }, el("div", m.sources.map((s) => el("span.tag", s))), el("pre.h-pre", m.text))))
    : el("div.h-muted", "None yet — they appear after the first message.")));
  out.push(sec("Thread permissions", el("pre.h-pre", (h.permissions || []).map((r) => `${r.effect.padEnd(5)}  ${r.action}  ${r.resource}`).join("\n") || "inherited")));
  return out;
}

function updateChangesBadge() {
  const t = S.current;
  const n = t ? collectEdits(t).length : 0;
  for (const badge of [$("changes-count"), $("wb-changes-count")]) {
    badge.hidden = !n;
    badge.textContent = n;
  }
}

// ---- composer -----------------------------------------------------------------------

/** The model the next message uses: the thread's, the draft's or the default — the first one still in the
 *  picker. A removed provider or a hidden model never stays selected. */
function currentModel() {
  for (const ref of [S.current?.session.model, S.draft.model, S.settings?.defaultModel, S.defaultModel]) if (findModel(ref)) return ref;
  return null;
}
/** The model this thread or draft asked for, when it is no longer available. */
function missingModel() {
  const ref = S.current ? S.current.session.model : S.draft.model;
  return ref && !findModel(ref) ? ref : null;
}
const currentAgent = () => S.current?.session.agent || S.draft.agent || S.settings.defaultAgent || "build";
const currentMode = () => S.current?.session.metadata?.afh?.mode || S.draft.mode || S.settings.defaultMode || "ask";

function findModel(ref) {
  return ref && S.models.find((m) => m.id === ref.id && m.providerID === ref.providerID);
}
function modelName(ref) {
  if (!ref) return null;
  const m = findModel(ref);
  return (m?.name || ref.id) + (ref.variant && ref.variant !== "default" ? ` · ${ref.variant}` : "");
}

function renderComposerState() {
  if (!S.settings) return;
  const ref = currentModel();
  const gone = missingModel();
  $("pick-model").replaceChildren(ico("cpu"), el("span.lbl", modelName(ref) || "Choose model"), el("span.chev", { html: icon("chev-down") }));
  $("pick-model").title = gone ? `${gone.id} is no longer available, so ${modelName(ref) || "no model"} is used` : "";
  const agent = S.agents.find((a) => a.id === currentAgent());
  const agentChip = $("pick-agent");
  agentChip.replaceChildren(ico(agentIcon(agent)), el("span.lbl", agent?.name || currentAgent()), el("span.chev", { html: icon("chev-down") }));
  agentChip.style.setProperty("--agent-color", agent?.color || "");
  agentChip.classList.toggle("has-agent-color", !!agent?.color);
  const mode = MODES[currentMode()] || MODES.ask;
  const mp = $("pick-mode");
  mp.className = `pill mode-${currentMode()}`;
  mp.replaceChildren(ico(mode.icon), el("span.lbl", mode.label), el("span.chev", { html: icon("chev-down") }));

  const t = S.current;
  const busy = !!t && (t.busy || S.busy.has(t.id));
  $("tb-logo").hidden = !busy; // the mark flows beside the title while a model works
  const send = $("btn-send");
  send.classList.toggle("stop", busy);
  send.innerHTML = icon(busy ? "stop" : "send");
  send.title = busy ? "Stop (Esc)" : S.settings.ui.sendKey === "ctrl-enter" ? "Send (Ctrl+Enter)" : "Send (Enter)";
  send.disabled = !busy && !$("input").value.trim();

  // Context meter: the latest step's prompt size against the model's window. Click for details.
  const ctxm = $("ctx-meter");
  const last = t && [...t.messages].reverse().find((m) => m.type === "assistant" && m.tokens);
  const limit = findModel(ref)?.context;
  if (t && (last || t.messages.length)) {
    const used = last ? (last.tokens.input || 0) + (last.tokens.cache?.read || 0) + (last.tokens.cache?.write || 0) : 0;
    ctxm.className = "ctx on";
    ctxm.innerHTML = contextRing(limit ? used / limit : 0);
    ctxm.title = limit ? `Context: ${fmtTokens(used)} of ${fmtTokens(limit)} tokens — click for details` : "Context details";
  } else ctxm.className = "ctx";
  renderUsage(ref);

  renderTps();
  const hint = $("composer-hint");
  if (busy) hint.replaceChildren(el("span", "Working… press Esc to stop, or type to queue a follow-up"));
  else if (project()) hint.replaceChildren(el("span", MODES[currentMode()].sub), " · ", el("bdi", basename(project())), " · ", el("span", "type / for commands"));
  else hint.replaceChildren();
  renderAttachments();
  renderWork();
}

const IMAGE_FILE = /\.(png|jpe?g|gif|webp)$/i;
const UPLOAD_PREFIX = /^\d{8}-\d{6}-[0-9a-f]{6}-/; // how /api/uploads names saved files
const thumbs = new Map(); // path -> object URL of an image pasted or dropped in this window

function renderAttachments() {
  const box = $("attachments");
  box.replaceChildren(...S.draft.files.map((f, i) => {
    const src = IMAGE_FILE.test(f) ? thumbs.get(f) || api.url("/api/image", { path: f }) : null;
    return el(src ? "span.file-chip.img-chip" : "span.file-chip", { title: f },
      src ? el("img.chip-thumb", { src, alt: "", on: { click: () => viewImage(src) } }) : ico("file"), el("span", basename(f).replace(UPLOAD_PREFIX, "")),
      el("button", { type: "button", html: icon("x"), on: { click: () => { S.draft.files.splice(i, 1); renderAttachments(); } } }));
  }));
}

/** Attach dropped or pasted files. Ones with no path on disk (a screenshot in the clipboard) are saved first. */
async function addFiles(list) {
  for (const f of list) {
    let path = window.afh?.pathForFile?.(f) || f.pywebviewFullPath || f.path || "";
    if (!path) {
      try {
        path = (await api.raw("/api/uploads", f, { "x-filename": encodeURIComponent(f.name || "pasted.png") })).path;
      } catch (err) {
        toast(err.message, "err");
        continue;
      }
    }
    if (f.type?.startsWith("image/")) thumbs.set(path, URL.createObjectURL(f));
    if (!S.draft.files.includes(path)) S.draft.files.push(path);
  }
  renderAttachments();
}

// ---- voice input: record with the mic button, transcribe, type the words into the composer ----

const mic = { rec: null, stream: null };

async function toggleMic() {
  const btn = $("btn-mic");
  if (mic.rec) return mic.rec.stop();
  if (btn.classList.contains("busy")) return;
  try {
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    return toast("AFH can't use the microphone — check Windows Settings → Privacy → Microphone", "err", 5000);
  }
  const type = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"].find((t) => window.MediaRecorder?.isTypeSupported(t)) || "";
  const rec = new MediaRecorder(mic.stream, type ? { mimeType: type } : {});
  const chunks = [];
  const started = Date.now();
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    mic.stream.getTracks().forEach((t) => t.stop());
    mic.rec = mic.stream = null;
    btn.classList.remove("rec");
    btn.title = "Speak — your words are typed here";
    if (Date.now() - started < 600) return;
    btn.classList.add("busy");
    try {
      const { text } = await api.raw("/api/transcribe", new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
      if (!text) return toast("Didn't catch any words — try again", "info");
      const cur = $("input").value;
      setInput(cur.trim() ? `${cur.replace(/\s*$/, "")} ${text}` : text);
      $("input").focus();
    } catch (err) {
      toast(err.message, "err", 6000);
    } finally {
      btn.classList.remove("busy");
    }
  };
  mic.rec = rec;
  rec.start();
  btn.classList.add("rec");
  btn.title = "Stop and transcribe";
}

function setInput(text) {
  const ta = $("input");
  ta.value = text;
  autosize();
  renderComposerState();
}

function autosize() {
  const ta = $("input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 260) + "px";
}

// Two steps: pick a provider, then one of its models. Search jumps straight to models.
const PROVIDER_NAMES = { "kimi-code-plan-global": "Kimi (kimi.ai)", "kimi-code-plan": "Kimi (kimi.com)", "zai-coding-plan": "Z.AI", openai: "OpenAI", anthropic: "Anthropic", google: "Google", "github-copilot": "GitHub Copilot" };
const providerName = (pid) => S.providerNames?.[pid] || PROVIDER_NAMES[pid] || pid.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
let lastProvider = null;

function modelMenu(pid = null) {
  const ref = currentModel();
  const byProvider = new Map();
  for (const m of S.models) {
    if (!byProvider.has(m.providerID)) byProvider.set(m.providerID, []);
    byProvider.get(m.providerID).push(m);
  }
  if (byProvider.size === 1) pid = [...byProvider.keys()][0];
  const anchor = $("pick-model");
  if (!pid) {
    const items = [{ group: "Providers" }];
    for (const [p, list] of byProvider) {
      items.push({ title: providerName(p), sub: list.length === 1 ? list[0].name : `${list.length} models`, icon: "cpu", count: list.length, arrow: true, checked: ref?.providerID === p, onSelect: () => modelMenu(p) });
    }
    items.push({ sep: true }, { title: "Add or manage providers…", icon: "key", onSelect: () => openSettings("models", ctx) });
    const all = S.models.map((m) => ({ title: m.name, badges: modalityBadges(m.input), sub: `${providerName(m.providerID)}${m.context ? ` · ${fmtTokens(m.context)} ctx` : ""}`, keywords: `${m.providerID} ${m.id}`, hidden: true, checked: ref && ref.id === m.id && ref.providerID === m.providerID, onSelect: () => chooseModel({ id: m.id, providerID: m.providerID }) }));
    popover(anchor, items, { search: true, placeholder: "Search all models…", width: 320, align: "right", searchItems: all });
    return;
  }
  lastProvider = pid;
  const list = byProvider.get(pid) || [];
  const items = list.map((m) => ({
    title: m.name, badges: modalityBadges(m.input),
    sub: `${m.id}${m.context ? ` · ${fmtTokens(m.context)} context` : ""}${m.variants?.length ? ` · effort ${m.variants.join("/")}` : ""}${m.tools ? "" : " · no tools"}`, keywords: m.id,
    checked: ref && ref.id === m.id && ref.providerID === pid,
    onSelect: () => chooseModel({ id: m.id, providerID: pid }),
  }));
  const header = el("div.pop-header", byProvider.size > 1 ? el("button.icon-btn", { html: icon("chev"), style: { transform: "rotate(180deg)" }, title: "All providers", on: { click: (e) => { e.stopPropagation(); modelMenu(null); } } }) : null, el("span", providerName(pid)), el("span.pi-count", { style: { marginLeft: "auto" } }, `${list.length} models`));
  const model = findModel(ref);
  let footer = null;
  if (model?.variants?.length && ref.providerID === pid) {
    const seg = el("div.seg");
    for (const v of ["default", ...model.variants.filter((x) => x !== "default")]) {
      seg.append(el(`button${(ref.variant || "default") === v ? ".on" : ""}`, { type: "button", on: { click: () => { closePopover(); chooseModel({ ...ref, variant: v === "default" ? undefined : v }); } } }, v));
    }
    footer = el("div.pop-variants", el("span", "Effort"), seg);
  }
  popover(anchor, items, { search: list.length > 6, placeholder: `Search ${providerName(pid)} models`, width: 340, align: "right", header, footer });
}

async function contextPopover() {
  const t = S.current;
  if (!t) return;
  const box = el("div.ctx-pop", el("div.empty-row", el("span.spinner")));
  popover($("ctx-meter"), [], { header: box, width: 300, align: "right" });
  try {
    const u = await api.get(`/api/sessions/${t.id}/usage`);
    const frac = u.contextLimit ? Math.min(1, u.lastInput / u.contextLimit) : 0;
    const tot = u.totals || {};
    box.replaceChildren(el("div",
      el("h4", ico("list"), "Context"),
      el("div.ctx-row", el("span", "In the window now"), el("b", `${fmtTokens(u.lastInput)}${u.contextLimit ? ` / ${fmtTokens(u.contextLimit)}` : ""}`)),
      el("div.ctx-bar", el("i", { style: { width: `${Math.round(frac * 100)}%` } })),
      el("div.ctx-row", el("span", "Model"), el("b", u.modelName || modelName(u.model) || "—")),
      el("div.ctx-row", el("span", "Mode"), el("b", u.agent || "build")),
      el("div.ctx-row", el("span", "Messages"), el("b", `${u.messages.user} you · ${u.messages.assistant} model · ${u.messages.tools} tools`)),
      el("div.ctx-row", el("span", "Tokens this thread"), el("b", `${fmtTokens((tot.input || 0) + (tot.cache?.read || 0) + (tot.cache?.write || 0))} in · ${fmtTokens(tot.output || 0)} out`)),
      tot.cache?.read ? el("div.ctx-row", el("span", "From the prompt cache"), el("b", `${fmtTokens(tot.cache.read)} (${Math.round((100 * tot.cache.read) / Math.max(1, (tot.input || 0) + tot.cache.read + (tot.cache.write || 0)))}%)`)) : null,
      el("div.ctx-row", el("span", "Cost"), el("b", u.plan ? "plan (no per-token cost)" : u.cost ? fmtCost(u.cost) : u.price ? "$0" : "price not set")),
      !u.plan && !u.price ? el("div.h-muted", { style: { fontSize: "11.5px", fontStyle: "normal", margin: "2px 0 6px" } }, "Set this model's price in Settings → Usage & cost to track spending.") : null,
      el("div.actions", { style: { marginTop: "8px" } },
        el("button.btn.sm.ghost", { title: "Summarise older messages now to free up context", on: { click: async () => { closePopover(); await localCommand("/compact"); } } }, ico("archive"), "Compact now"),
        el("button.btn.sm", { on: { click: () => { closePopover(); editContext(); } } }, ico("edit"), "Context editor"))));
  } catch (e) {
    box.replaceChildren(el("div.empty-row", e.message));
  }
  repositionPopover();
}

// ---- live timer & tokens/s -------------------------------------------------------------

function renderTps() {
  const t = S.current;
  const chip = $("tps");
  if (!t) { chip.className = "tps"; return; }
  const live = t.busy || S.busy.has(t.id);
  const rate = live && t.liveTps ? t.liveTps : t.tps;
  if (!rate) { chip.className = "tps"; return; }
  chip.className = `tps on${live && t.liveTps ? " live" : ""}`;
  chip.replaceChildren(el("b", `${Math.round(rate)}`), el("span", live && t.liveTps ? "~tok/s" : "tok/s"));
  chip.title = live && t.liveTps ? "Estimated while streaming; exact when the step finishes" : "Output tokens per second of the last step (provider token count ÷ streaming time)";
}

setInterval(() => {
  const t = S.current;
  if (!t || !(t.busy || S.busy.has(t.id))) return;
  view.tick();
  renderTps();
}, 1000);

async function chooseModel(ref) {
  if (S.current) await patchSession({ model: ref });
  else S.draft.model = ref;
  renderComposerState();
}

const agentIcon = (a) => (a?.id === "redteam" ? "shield" : a?.id === "plan" ? "list" : "bot");

function agentMenu() {
  const items = S.agents.filter((a) => !a.hidden && a.mode !== "subagent").map((a) => ({
    title: a.name, sub: a.description, icon: agentIcon(a), checked: a.id === currentAgent(),
    onSelect: async () => { if (S.current) await patchSession({ agent: a.id }); else S.draft.agent = a.id; renderComposerState(); },
  }));
  items.push({ sep: true }, { title: "Create or edit agents…", icon: "sliders", onSelect: () => openSettings("prompts", ctx) });
  popover($("pick-agent"), items, { width: 320 });
}

function modeMenu() {
  popover($("pick-mode"), Object.entries(MODES).map(([id, m]) => ({
    title: m.label, sub: m.sub, icon: m.icon, checked: id === currentMode(),
    onSelect: async () => { if (S.current) await patchSession({ mode: id }); else S.draft.mode = id; renderComposerState(); },
  })), { width: 300 });
}

async function attach() {
  if (!native.available()) return toast("File picking needs the desktop window — paste a path in your message instead.", "info", 4000);
  const files = (await native.pickFiles()) || [];
  for (const f of files) if (!S.draft.files.includes(f)) S.draft.files.push(f);
  renderAttachments();
}

// ---- slash commands menu ---------------------------------------------------------------------

const slash = { open: false, items: [], index: 0 };
let cmdCache = { dir: null, at: 0, list: [] };

async function commandList() {
  if (cmdCache.dir === project() && Date.now() - cmdCache.at < 30_000) return cmdCache.list;
  try {
    cmdCache = { dir: project(), at: Date.now(), list: await api.get(api.q("/api/commands", { directory: project() })) };
  } catch {
    cmdCache = { dir: project(), at: Date.now(), list: [] };
  }
  return cmdCache.list;
}
const invalidateCommands = () => { cmdCache.at = 0; };

const RUN_NOW = new Set(["new", "todo", "jobs", "cost", "compact"]);

async function updateSlash() {
  const v = $("input").value;
  const m = v.match(/^\/([a-z0-9_:-]*)$/i);
  if (!m) return closeSlash();
  const q = m[1].toLowerCase();
  const needsThread = new Set(["compact", "cost", "jobs", "todo"]);
  const list = (await commandList()).filter((c) => (S.current || !needsThread.has(c.name)) && (!q || c.name.startsWith(q) || c.name.includes(q) || (c.description || "").toLowerCase().includes(q)));
  if ($("input").value !== v) return; // typed on while loading
  if (!list.length) return closeSlash();
  list.sort((a, b) => (b.name.startsWith(q) - a.name.startsWith(q)) || 0);
  slash.items = list.slice(0, 12);
  slash.index = Math.min(slash.index, slash.items.length - 1);
  slash.open = true;
  drawSlash();
}

function drawSlash() {
  const box = $("slash-menu");
  box.hidden = false;
  box.replaceChildren(el("div.slash-head", ico("slash"), "Commands", el("span.slash-keys", "↑↓ choose · Enter run · Esc close")),
    ...slash.items.map((c, i) => el(`button.slash-item${i === slash.index ? ".on" : ""}`, { type: "button", on: { mousedown: (e) => { e.preventDefault(); pickSlash(c); }, mousemove: () => { if (slash.index !== i) { slash.index = i; drawSlash(); } } } },
      el("span.slash-name", `/${c.name}`), c.args ? el("span.slash-args", c.args) : null, el("span.slash-desc", c.description || ""),
      el("span.slash-src", c.builtin ? "built-in" : c.source === "project" ? "project" : c.source === "global" ? "global" : "yours"))));
}

function closeSlash() {
  slash.open = false;
  slash.index = 0;
  $("slash-menu").hidden = true;
}

function pickSlash(c) {
  closeSlash();
  if (RUN_NOW.has(c.name)) { setInput(`/${c.name}`); submit(); return; }
  if (c.name === "goal") { setInput(""); editGoal(); return; }
  if (c.name === "memory") { setInput(""); openMemory(); return; }
  setInput(`/${c.name} `);
  $("input").focus();
}

function slashKey(e) {
  if (!slash.open) return false;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    slash.index = (slash.index + (e.key === "ArrowDown" ? 1 : -1) + slash.items.length) % slash.items.length;
    drawSlash();
    return true;
  }
  if (e.key === "Enter" || e.key === "Tab") {
    e.preventDefault();
    pickSlash(slash.items[slash.index]);
    return true;
  }
  if (e.key === "Escape") { e.preventDefault(); closeSlash(); return true; }
  return false;
}

/** Slash commands the composer runs itself. Returns true when handled (nothing is sent). */
async function localCommand(text) {
  const m = text.match(/^\/([a-z0-9][a-z0-9_:-]*)(?:\s+([\s\S]*))?$/i);
  if (!m) return false;
  const name = m[1].toLowerCase(), args = (m[2] || "").trim();
  const t = S.current;
  const clear = () => { $("input").value = ""; autosize(); renderComposerState(); };
  if (name === "new") { clear(); showHome(); return true; }
  if (name === "goal" && !args) { clear(); editGoal(); return true; }
  if (name === "memory") { clear(); openMemory(); return true; }
  if (name === "remember") {
    if (!args) { clear(); openMemory(); return true; }
    if (await rememberFacts(memoryLines(args))) clear();
    return true;
  }
  if (name === "todo") {
    clear();
    if (!t) { toast("Start a thread first", "info"); return true; }
    // A finished list has moved to the Goal menu; /todo starts a fresh one.
    if (t.todos?.length && t.todos.every((x) => x.status === "completed" || x.status === "cancelled")) { t.todos = []; t.todosFromEvents = true; }
    t.showTodos = true;
    renderWork();
    setTimeout(() => document.querySelector(".todo-add")?.focus(), 50);
    return true;
  }
  if (name === "jobs") { clear(); if (t) jobsPopover($("jobs-pill").hidden ? $("btn-send") : $("jobs-pill"), t); return true; }
  if (name === "cost") { clear(); if (t) contextPopover(); return true; }
  if (name === "compact") {
    clear();
    if (!t) return true;
    try {
      toast("Compacting…", "info", 1500);
      const r = await api.post(`/api/sessions/${t.id}/compact`);
      toast(r.ok ? "Older messages summarised" : "Nothing to compact yet", r.ok ? "ok" : "info");
      if (r.ok) reloadCurrent(t.id);
    } catch (e) { toast(e.message, "err"); }
    return true;
  }
  return false;
}

async function submit(override) {
  closeSlash();
  const ta = $("input");
  const text = (typeof override === "string" ? override : ta.value).trim();
  const t = S.current;
  if (t && (t.busy || S.busy.has(t.id)) && !text) return interrupt();
  if (!text) return;
  if (!project()) return chooseFolder();
  if (text.startsWith("/") && (await localCommand(text))) return;
  if (!currentModel()) {
    toast("Add a provider and pick a model first", "info");
    return openSettings("models", ctx);
  }
  const gone = missingModel();
  if (gone) {  // keep the thread on a model that exists, so the next run doesn't fail on it
    const next = currentModel();
    toast(`${gone.id} is no longer available — using ${modelName(next)}`, "info", 4000);
    if (S.current) await patchSession({ model: next }); else S.draft.model = null;
  }
  const files = [...S.draft.files];
  ta.value = "";
  S.draft.files = [];
  autosize();
  try {
    let thread = S.current;
    if (!thread) {
      const goal = S.draft.goal;
      const worktree = S.draft.worktree && S.gitRepo;
      if (worktree) toast("Creating a worktree…", "info", 1800);
      const session = await api.post("/api/sessions", { directory: project(), model: currentModel(), agent: currentAgent(), mode: currentMode(), worktree, worktreeName: worktree ? text.replace(/^\/\S+\s*/, "").split(/\s+/).slice(0, 5).join(" ") : undefined });
      if (goal) session.metadata = { ...(session.metadata || {}), afh: { ...(session.metadata?.afh || {}), goal: await api.put(`/api/sessions/${session.id}/goal`, goal) } };
      S.sessions.unshift(session);
      thread = createThread(session);
      syncState(thread);
      thread.loaded = true;
      S.threads.set(session.id, thread);
      S.current = thread;
      S.draft = { model: null, agent: null, mode: null, files: [], goal: null, worktree: false };
      S.settings.lastThread = session.id;
      api.put("/api/settings", { lastThread: session.id }).catch(() => {});
      renderThreads();
      renderTopbar();
      view.mount(thread);
    }
    thread.error = null;
    thread.busy = true;
    thread.runStart = Date.now(); // the timer starts the moment you send
    thread.phase = "sending";
    thread.liveTps = 0;
    S.busy.add(thread.id);
    browserHandBack(thread.id);
    renderComposerState();
    renderThreads();
    view.stick = true;
    view.update({ status: true });
    await api.post(`/api/sessions/${thread.id}/prompt`, { text, files });
  } catch (e) {
    toast(e.message, "err");
    if (!ta.value) setInput(text);
    if (S.current) S.busy.delete(S.current.id);
    renderComposerState();
  }
}

async function interrupt() {
  const t = S.current;
  if (!t) return;
  try {
    await api.post(`/api/sessions/${t.id}/interrupt`);
  } catch (e) {
    toast(e.message, "err");
  }
}

async function retryLast() {
  const t = S.current;
  const lastUser = t && [...t.messages].reverse().find((m) => m.type === "user");
  if (!lastUser) return;
  t.error = null;
  view.renderStatus();
  S.busy.add(t.id);
  renderComposerState();
  try {
    await api.post(`/api/sessions/${t.id}/prompt`, { text: "Continue — the previous attempt failed. Pick up where you left off." });
  } catch (e) {
    toast(e.message, "err");
  }
}

// ---- events -----------------------------------------------------------------------

let restartPill = null;
function onEvent(ev) {
  const type = ev.type || "";
  if (type === "computer.active" || type === "computer.fx" || type === "computer.teach") return; // drawn by the desktop overlay
  if (type === "computer.apps.changed") { ctx.onComputerAppsChanged?.(); return; }
  if (type === "project.memory.updated") return onMemoryEvent(ev.data);
  if (type === "schedule.ran") {
    const job = ev.data?.job || {};
    toast(`Scheduled job "${job.name}" started`, "ok", 5000);
    notify("done", "Scheduled job started", job.name, () => openThreadIn(ev.data.sessionID, job.directory));
    if (job.directory === project()) refreshSessionsSoon();
    return;
  }
  if (type === "schedule.failed") { toast(`Scheduled job "${ev.data?.job?.name}" couldn't start: ${ev.data?.error}`, "err", 8000); return; }
  if (type === "session.revert.committed" && ev.data?.sessionID === S.current?.id) document.querySelector(".revert-bar")?.remove();
  if (type === "afh.restarting") {
    restartPill?.remove();
    restartPill = el("div.restarting", el("span.spinner"), "Applying changes…");
    document.body.append(restartPill);
    $("conn").className = "conn busy";
    return;
  }
  if (type === "afh.ready") {
    restartPill?.remove();
    restartPill = null;
    $("conn").className = "conn ok";
    reloadCatalog().catch(() => {});
    ctx.onReady?.();
    return;
  }
  if (type === "afh.error") {
    restartPill?.remove();
    toast(`Engine error: ${ev.data?.message}`, "err", 8000);
    return;
  }

  trackEvent(ev); // delegation children register themselves on session.created
  const sid = ev.data?.sessionID || ev.data?.session_id || (type.startsWith("session.") ? ev.data?.id : null);
  if (type === "session.execution.started" && sid) S.busy.add(sid);
  if (type.startsWith("session.execution.")) queueMicrotask(syncBrowserRuns); // the agent's bar in its browser tab
  if (/^session\.execution\.(succeeded|failed|interrupted)$/.test(type) && sid) {
    S.busy.delete(sid);
    if (S.current?.id === sid) renderComposerState();  // settle the dock/to-do spinner the moment the run ends
  }
  if (/^session\.(created|deleted|renamed|archived|unarchived|forked|moved|execution\.(started|succeeded|failed|interrupted))$/.test(type)) {
    if (type === "session.renamed" && sid) {
      const s = S.sessions.find((x) => x.id === sid);
      if (s) s.title = ev.data.title;
      if (S.current?.id === sid) S.current.session.title = ev.data.title;
      renderTopbar();
    }
    renderThreads();
    refreshSessionsSoon();
  }
  if (type.startsWith("model.") || type.startsWith("agent.")) reloadCatalogSoon();
  if (type.startsWith("mcp.") || type.startsWith("plugin.")) ctx.onCatalogEvent?.(type);

  const t = sid && S.threads.get(sid);
  if (t && applyWorkEvent(t, ev)) {
    if (S.current === t) renderWork();
    if (type === "session.goal.updated" && ev.data?.goal?.status === "achieved" && t.prevGoalStatus && t.prevGoalStatus !== "achieved") {
      notify("done", "Goal achieved", ev.data.goal.text);
      toast("Goal achieved", "ok", 4000);
    }
  }
  if (!t || !t.loaded) return;
  const result = applyEvent(t, ev);
  if (result?.reload && S.current === t) {
    if (!t.busy) { reloadCurrent(t.id); return; }
    t.needsReload = true; // compacted mid-run: show the summary once the run ends
  }
  if (t.needsReload && S.current === t && /^session\.execution\.(succeeded|failed|interrupted)$/.test(type)) { t.needsReload = false; setTimeout(() => reloadCurrent(t.id), 300); }
  if (type === "session.tool.called") registerDelegation(t, ev.data);
  if (S.current === t && type.startsWith("session.tool.")) { onLiveEvent(ev); renderSubagentsChip(subChip, t); }
  if (!result) return;
  if (S.current === t) {
    view.update(result);
    if (result.status) renderComposerState();
    if (/execution\.(succeeded|failed|interrupted)/.test(type)) refreshDrawerSoon("run");
    else if (result.changes) refreshDrawerSoon("changes");
  } else if (D.children.has(sid)) {
    onChildEvent(sid, result, view);
    if (D.watch === sid && result.status) refreshDrawerSoon();
  }
  if (type === "permission.asked") {
    const asking = ev.data?.action === "question";
    if (S.current !== t) toast(`"${t.session.title || "A thread"}" is ${asking ? "asking you a question" : "waiting for your approval"}`, "info", 5000);
    notify("ask", ev.data?.metadata?.title || (asking ? "A question for you" : "Approval needed"), `${t.session.title || "A thread"} ${asking ? "has a question" : `wants to ${ev.data?.action || "run a tool"}`}`);
  }
  if (type === "session.execution.succeeded" && !D.children.has(sid)) notify("done", "Done", t.session.title || "The thread finished");
  if ((type === "session.execution.succeeded" || type === "session.execution.failed") && sid === S.current?.id) refreshUsage();
  if (type === "session.execution.failed" && !D.children.has(sid)) notify("error", "Run failed", ev.data?.error?.message || t.session.title || "");
}

let catalogTimer = 0;
const reloadCatalogSoon = () => { clearTimeout(catalogTimer); catalogTimer = setTimeout(() => reloadCatalog().catch(() => {}), 800); };
let drawerTimer = 0, drawerReason = "changes";
const refreshDrawerSoon = (reason = "changes") => {
  if (reason === "run") drawerReason = "run"; // a run ending outranks a tool finishing
  clearTimeout(drawerTimer);
  drawerTimer = setTimeout(() => { const r = drawerReason; drawerReason = "changes"; refreshDrawer(r); }, 300);
};

// ---- wiring ------------------------------------------------------------------------

/** Open a thread, switching to its project first when needed (Schedules, notifications). */
async function openThreadIn(id, directory) {
  if (directory && directory !== project()) await switchProject(directory);
  else await loadSessions();
  await openThread(id);
}

export const ctx = { S, saveSettings, reloadCatalog, project, modelName, invalidateCommands, setLanguage, openThread: openThreadIn, onReady: null, onCatalogEvent: null };
window.__afh = { S, D, ctx, view, live: liveState }; // for debugging from the devtools console

// ---- sidebar: an icon rail that expands on hover, pinned open or collapsed with Ctrl+B ----------------
// Wide windows start expanded, windows under 1100px start as the rail; a pin (the collapse button or
// Ctrl+B) is remembered. Phones have no rail: the sidebar hides and slides over the chat when asked.

const SB_KEY = "afh-sidebar";
const RAIL_BELOW = 1100, PHONE_BELOW = 640;
let sbPin = "";
try { sbPin = localStorage.getItem(SB_KEY) || ""; } catch {}

function sidebarMode() {
  if (innerWidth <= PHONE_BELOW) return "hidden";
  if (sbPin === "open" || sbPin === "rail") return sbPin;
  return innerWidth < RAIL_BELOW ? "rail" : "open";
}

function applySidebar() {
  const app = $("app");
  const mode = sidebarMode();
  app.classList.toggle("sb-rail", mode === "rail");
  app.classList.toggle("sb-hidden", mode === "hidden");
  if (mode !== "hidden") app.classList.remove("sb-open");
  if (mode !== "rail") app.classList.remove("sb-peek");
  $("btn-expand").hidden = mode !== "hidden" || app.classList.contains("sb-open");
  $("btn-collapse").title = mode === "rail" ? "Show sidebar (Ctrl+B)" : "Hide sidebar (Ctrl+B)";
}

function toggleSidebar() {
  const app = $("app");
  if (sidebarMode() === "hidden") {
    app.classList.toggle("sb-open");
    $("btn-expand").hidden = app.classList.contains("sb-open");
    return;
  }
  sbPin = sidebarMode() === "rail" ? "open" : "rail";
  try { localStorage.setItem(SB_KEY, sbPin); } catch {}
  applySidebar();
}

/** Bring the sidebar into view without pinning it (Ctrl+K, the rail's search button). */
function revealSidebar() {
  const app = $("app");
  const mode = sidebarMode();
  if (mode === "rail") app.classList.add("sb-peek");
  if (mode === "hidden") { app.classList.add("sb-open"); $("btn-expand").hidden = true; }
}

function wireSidebar() {
  const app = $("app"), sb = $("sidebar");
  let timer = 0;
  const peek = () => { clearTimeout(timer); if (app.classList.contains("sb-rail")) app.classList.add("sb-peek"); };
  const unpeek = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (sb.matches(":hover")) return;
      if (sb.contains(document.activeElement) && document.activeElement.matches("input, textarea")) return; // typing in the search box
      if (document.querySelector("#overlay-root .pop")) { timer = setTimeout(unpeek, 250); return; } // a menu opened from the sidebar
      app.classList.remove("sb-peek");
    }, 160);
  };
  sb.addEventListener("pointerenter", () => { clearTimeout(timer); timer = setTimeout(peek, 150); });
  sb.addEventListener("pointerleave", unpeek);
  sb.addEventListener("focusin", peek);
  sb.addEventListener("focusout", unpeek);
  $("sb-search").addEventListener("click", () => { revealSidebar(); $("thread-search").focus(); });
  addEventListener("resize", applySidebar);
  applySidebar();
}

function wire() {
  const ta = $("input");
  ta.addEventListener("input", () => { autosize(); renderComposerState(); updateSlash(); });
  ta.addEventListener("blur", () => setTimeout(closeSlash, 120));
  ta.addEventListener("keydown", (e) => {
    if (slashKey(e)) return;
    if (e.key !== "Enter" || e.isComposing) return;
    const ctrlMode = S.settings.ui.sendKey === "ctrl-enter";
    if ((ctrlMode && (e.ctrlKey || e.metaKey)) || (!ctrlMode && !e.shiftKey && !e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  });
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  $("composer").addEventListener("dragover", (e) => { e.preventDefault(); $("composer").classList.add("drag"); });
  $("composer").addEventListener("dragleave", () => $("composer").classList.remove("drag"));
  $("composer").addEventListener("drop", (e) => {
    e.preventDefault();
    $("composer").classList.remove("drag");
    const files = [...(e.dataTransfer?.files || [])];
    if (!files.length) return toast("Use the paperclip to attach files", "info");
    addFiles(files);
  });
  ta.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (!files.length) return;
    e.preventDefault();
    addFiles(files);
  });
  $("btn-attach").addEventListener("click", attach);
  $("btn-mic").addEventListener("click", toggleMic);
  $("ctx-meter").addEventListener("click", contextPopover);
  $("pick-model").addEventListener("click", () => modelMenu(lastProvider && S.models.some((m) => m.providerID === lastProvider) && currentModel()?.providerID === lastProvider ? lastProvider : null));
  $("pick-agent").addEventListener("click", agentMenu);
  $("pick-mode").addEventListener("click", modeMenu);
  $("btn-new").addEventListener("click", () => { showHome(); ta.focus(); });
  $("project-picker").addEventListener("click", projectMenu);
  $("btn-settings").addEventListener("click", () => openSettings("general", ctx));
  if ($("btn-account")) {
    $("btn-account").addEventListener("click", () => openAccount());
    refreshAccountButton();
    setInterval(() => !document.hidden && refreshAccountButton(), 15000);
  }
  $("btn-memory").addEventListener("click", openMemory);
  $("btn-theme").addEventListener("click", toggleTheme);
  $("btn-lang").addEventListener("click", () => setLanguage(S.settings.ui.language === "ar" ? "en" : "ar"));
  $("btn-thread-menu").addEventListener("click", threadMenu);
  $("btn-changes").addEventListener("click", () => openDrawer("changes"));
  $("btn-harness").addEventListener("click", () => openDrawer("harness"));
  $("btn-context").addEventListener("click", () => openDrawer("context"));
  $("btn-live").addEventListener("click", () => openDrawer("live"));
  $("wb-tabs").addEventListener("click", (e) => { const tab = e.target.closest(".wb-tab"); if (tab) showTab(tab.dataset.tab); });
  $("btn-goal").addEventListener("click", () => {
    const t = S.current;
    if (t && (t.goal || t.goalHistory?.length || t.todoHistory?.length)) goalsPopover($("btn-goal"), t, { onEdit: editGoal, onNew: () => openGoalDialog({ thread: { ...t, goal: null, id: t.id }, onSaved: (g) => { t.goal = g; renderWork(); } }) });
    else editGoal();
  });
  $("btn-worktree").addEventListener("click", worktreeMenu);
  $("draft-goal").addEventListener("click", editGoal);
  $("draft-memory").addEventListener("click", openMemory);
  $("draft-worktree").addEventListener("click", () => { S.draft.worktree = !S.draft.worktree; renderWork(); if (S.draft.worktree) toast("The new thread gets its own git worktree: a separate folder on a new branch", "info", 3500); });
  $("jobs-pill").addEventListener("click", () => S.current && jobsPopover($("jobs-pill"), S.current));
  subChip.addEventListener("click", () => S.current && subagentsPopover(subChip, S.current, openWatch));
  wireResize();
  wireDrawerResize();
  wireComposerHeight();
  $("btn-drawer-close").addEventListener("click", closeDrawer);
  $("btn-collapse").addEventListener("click", toggleSidebar);
  $("btn-expand").addEventListener("click", toggleSidebar);
  $("jump").addEventListener("click", () => { view.stick = true; view.scrollToEnd(); });
  $("thread-search").addEventListener("input", (e) => { S.search = e.target.value; renderThreads(); });

  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const overlay = document.querySelector(".scrim, .pop");
    if (mod && e.key.toLowerCase() === "n") { e.preventDefault(); showHome(); ta.focus(); }
    else if (mod && e.shiftKey && e.key.toLowerCase() === "w") { e.preventDefault(); S.drawer ? closeDrawer() : reopenWorkbench(); }
    else if (mod && e.key.toLowerCase() === "b" && !e.shiftKey) { e.preventDefault(); toggleSidebar(); }
    else if (mod && e.key === ",") { e.preventDefault(); openSettings("general", ctx); }
    else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); revealSidebar(); $("thread-search").focus(); }
    else if (mod && e.key.toLowerCase() === "p") { e.preventDefault(); showPalette(); }
    else if (e.key === "Escape" && !overlay && S.current && (S.current.busy || S.busy.has(S.current.id))) { e.preventDefault(); interrupt(); }
  });
  setInterval(renderThreads, 60_000);
  wireSidebar();
  // the segmented controls' sliding pill follows the active chip through resizes and language changes
  if ("ResizeObserver" in window) { const ro = new ResizeObserver(() => syncPills()); ro.observe($("tb-seg")); ro.observe($("wb-tabs")); }
  addEventListener("resize", syncPills);
}

/** The composer floats over the thread, so the thread needs room under its last message: --composer-h. */
function wireComposerHeight() {
  const wrap = $("composer-wrap"), main = document.querySelector(".main");
  const set = () => main.style.setProperty("--composer-h", `${wrap.offsetHeight}px`);
  if ("ResizeObserver" in window) new ResizeObserver(set).observe(wrap);
  set();
}

boot();
