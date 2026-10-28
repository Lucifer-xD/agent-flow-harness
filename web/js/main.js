import { api, connectEvents, hooks as apiHooks, native, remoteLogin } from "./api.js";
import { ChatView, applyEvent, collectEdits, createThread, hooks, loadThread } from "./chat.js";
import { D, closeWatch, delegationCard, initDelegate, onChildEvent, registerDelegation, renderWatch, syncChildren, trackEvent } from "./delegate.js";
import { openContextEditor } from "./context.js";
import { logoNode, setWorking } from "./logo.js";
import { openSettings } from "./settings.js";
import { exportThread, openImportDialog } from "./transfer-ui.js";
import {
  ago, basename, closePopover, confirmDialog, contextRing, dayGroup, diffView, el, escapeHtml, fmtTokens,
  hydrateIcons, ico, icon, popover, promptDialog, toast,
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
  draft: { model: null, agent: null, mode: null, files: [] },
  search: "",
  drawer: null, // "changes" | "harness"
};

const MODES = {
  ask: { label: "Ask first", icon: "shield", sub: "Approve file edits and commands" },
  full: { label: "Full access", icon: "zap", sub: "Edit files and run commands freely" },
  readonly: { label: "Read only", icon: "eye", sub: "Can read and search, never edit or run" },
};

const view = new ChatView($("messages"), $("thread"), {
  settings: () => S.settings,
  modelName: (ref) => modelName(ref),
  onFork: (id) => forkThread(id),
  onRetry: () => retryLast(),
  onRevert: (id) => revertTo(id),
  onStatus: () => renderComposerState(),
  onScroll: (stick, top) => {
    $("jump").hidden = stick || !S.current;
    document.querySelector(".topbar").classList.toggle("scrolled", top > 4);
  },
});

// ---- boot -----------------------------------------------------------------------

/** First-run help when the OpenCode engine can't start (usually: not installed yet). */
async function showSetup(message) {
  if (document.querySelector(".setup-box")) return;
  let info = {};
  try { info = await api.get("/api/setup"); } catch {}
  const missing = !info.opencode;
  $("boot-status").textContent = ""; // the box below explains it better than the raw error
  const status = el("div", { style: { color: "var(--text-3)", fontSize: "12.5px", minHeight: "18px" } });
  const box = el("div.setup-box",
    el("h3", missing ? "One more thing: install OpenCode" : "OpenCode couldn't start"),
    el("p", missing
      ? "AFH runs on the open-source OpenCode engine. It's a one-time install (about a minute)."
      : (message || "").slice(0, 300)),
    missing && !info.npm ? el("p", el("b", "Node.js is needed first. "), "Download the LTS version from ", el("a", { href: "https://nodejs.org", target: "_blank", rel: "noopener" }, "nodejs.org"), ", install it, then come back and click Retry.") : null,
    el("div", { style: { display: "flex", gap: "8px", justifyContent: "center", marginTop: "10px", flexWrap: "wrap" } },
      missing && info.npm ? el("button.btn.primary", { on: { click: async (e) => {
        e.currentTarget.disabled = true;
        status.textContent = "Installing OpenCode… this takes about a minute.";
        try {
          await api.post("/api/setup/install-opencode");
          status.textContent = "Installed. Starting…";
          setTimeout(() => location.reload(), 3000);
        } catch (err) {
          status.textContent = err.message;
          e.currentTarget.disabled = false;
        }
      } } }, ico("arrow-down"), "Install OpenCode") : null,
      el("button.btn", { on: { click: () => location.reload() } }, ico("refresh"), "Retry")),
    status,
    el("details", { style: { marginTop: "8px" } }, el("summary", { style: { cursor: "pointer", color: "var(--text-3)", fontSize: "12px" } }, "Technical details"), el("pre.h-pre", { style: { textAlign: "left", maxWidth: "560px" } }, `${message || ""}\n\nopencode: ${info.opencode || "not found"}\nnode: ${info.node || "not found"}\nnpm: ${info.npm || "not found"}`)));
  $("boot").append(box);
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

async function boot() {
  hydrateIcons();
  $("boot-mark").append(logoNode({ size: 110, working: true }));
  $("brand").prepend(logoNode({ size: 30 }));
  $("tb-logo").append(logoNode({ size: 30, working: true }));
  apiHooks.onUnauthorized = () => showLogin();
  for (const [id, name] of [["btn-collapse", "sidebar"], ["btn-expand", "sidebar"], ["btn-thread-menu", "more"], ["btn-attach", "paperclip"], ["btn-drawer-close", "x"]]) $(id).innerHTML = icon(name);
  let data;
  for (let attempt = 0; ; attempt++) {
    try {
      data = await api.get("/api/bootstrap");
      if (data.ready) break;
      if (data.error) throw new Error(data.error);
    } catch (e) {
      if (document.querySelector(".login-box")) return; // waiting for the remote password
      $("boot-status").textContent = `Couldn't start OpenCode: ${e.message}`;
      $("boot-status").classList.add("err");
      if (attempt > 0) return showSetup(e.message);
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  S.settings = data.settings;
  S.models = data.models;
  S.defaultModel = data.defaultModel;
  S.agents = data.agents;
  applyAppearance();
  initDelegate(ctx);
  hooks.delegation = (p, o) => delegationCard(p, { ...o, onWatch: openWatch });
  wire();
  connectEvents(onEvent, (state) => $("conn").className = "conn " + (state === "open" ? "ok" : "bad"));
  $("app").hidden = false;
  $("boot").classList.add("gone");
  setTimeout(() => $("boot")?.remove(), 600);
  await loadSessions();
  showHome();
  $("input").focus();
}

export function applyAppearance() {
  const ui = S.settings.ui;
  const root = document.documentElement;
  const dark = ui.theme === "dark" || (ui.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.density = ui.density;
  root.style.setProperty("--accent", ui.accent);
  root.style.setProperty("--fs", `${ui.fontSize}px`);
  document.body.classList.toggle("no-anim", !ui.animations);
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
  S.agents = agents;
  renderComposerState();
}

// ---- projects & sessions ------------------------------------------------------------

const project = () => S.settings.lastProject;

async function loadSessions() {
  renderProjectPicker();
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
  if (project()) items.push({ title: "Import thread…", sub: "From a file, OpenCode or Zadloop", icon: "arrow-down", onSelect: importThread });
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
    const item = el(`button.th-item${S.current?.id === s.id ? ".active" : ""}`, {
      type: "button", title: s.title || "New thread", style: { animationDelay: `${Math.min(i, 12) * 18}ms` },
      on: { click: () => openThread(s.id) },
    },
      S.busy.has(s.id) ? logoNode({ size: 18, working: true }) : null,
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
  renderComposerState();
  refreshDrawer();
  $("input").focus();
}

function showHome() {
  S.current = null;
  S.draft.files = [];
  renderThreads();
  renderTopbar();
  renderComposerState();
  closeDrawer();
  const root = $("messages");
  view.thread = null;
  root.replaceChildren();
  if (!project()) {
    root.append(el("div.hero.no-project", logoNode({ size: 150 }), el("h2", "Welcome to Agent Flow Harness"),
      el("p", "Open a project folder and AFH will read, edit and run code there with any model you choose."),
      el("button.btn.primary", { on: { click: chooseFolder } }, ico("folder-plus"), "Open a folder")));
    return;
  }
  const name = S.settings.personalization?.name;
  const ideas = [
    ["Explain this codebase", "Give me a tour of the architecture and the main entry points."],
    ["Find and fix a bug", "Run the tests, find what's failing, and fix it."],
    ["Write tests", "Add tests for the parts of this project that have none."],
    ["Review my changes", "Review the uncommitted changes and point out problems."],
  ];
  root.append(el("div.hero", logoNode({ size: 150 }),
    el("h2", name ? `What are we building, ${name}?` : "What are we building?"),
    el("p", el("span", "in "), el("b", basename(project()))),
    el("div.suggest", ideas.map(([title, text]) => el("button", { type: "button", on: { click: () => { setInput(text); $("input").focus(); } } }, el("b", title), text)))));
}

async function deleteThread(id) {
  const s = S.sessions.find((x) => x.id === id);
  if (!(await confirmDialog({ title: "Delete thread?", body: `"${s?.title || "New thread"}" and its history will be deleted. Files it changed are not reverted.`, confirm: "Delete", danger: true }))) return;
  try {
    await api.del(`/api/sessions/${id}`);
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

// ---- undo (OpenCode revert) & context editing -----------------------------------------

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
  $("messages").prepend(bar);
  bar.scrollIntoView({ behavior: "smooth", block: "nearest" });
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

function renderTopbar() {
  const box = $("tb-title");
  box.replaceChildren();
  const t = S.current;
  $("btn-thread-menu").hidden = !t;
  $("btn-changes").hidden = !t;
  $("btn-harness").hidden = !t;
  $("btn-context").hidden = !t;
  if (!t) {
    if (project()) box.append(el("span.tb-path", project()));
    return;
  }
  const h = el("h1", { title: "Double-click to rename" }, t.session.title || "New thread");
  h.addEventListener("dblclick", () => {
    const input = el("input", { value: t.session.title || "" });
    const done = async (save) => {
      if (save && input.value.trim() && input.value !== t.session.title) await patchSession({ title: input.value.trim() });
      else renderTopbar();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    input.addEventListener("blur", () => done(true));
    h.replaceWith(input);
    input.focus();
    input.select();
  });
  box.append(h, el("span.tb-path", basename(project())));
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

// ---- drawer ------------------------------------------------------------------------

function openDrawer(kind) {
  if (S.drawer === kind) return closeDrawer();
  if (S.drawer === "watch") closeWatch();
  S.drawer = kind;
  $("drawer").classList.add("open");
  $("drawer").classList.toggle("watch", kind === "watch");
  $("drawer").setAttribute("aria-hidden", "false");
  $("btn-changes").classList.toggle("on", kind === "changes");
  $("btn-harness").classList.toggle("on", kind === "harness");
  refreshDrawer();
}

function closeDrawer() {
  if (S.drawer === "watch") closeWatch();
  S.drawer = null;
  $("drawer").classList.remove("open", "watch");
  $("drawer").setAttribute("aria-hidden", "true");
  $("btn-changes").classList.remove("on");
  $("btn-harness").classList.remove("on");
}

function openWatch(childId) {
  D.watch = childId;
  if (S.drawer !== "watch") openDrawer("watch");
  else refreshDrawer();
}

async function refreshDrawer() {
  const t = S.current;
  updateChangesBadge();
  if (!S.drawer || !t) return;
  const body = $("drawer-body");
  if (S.drawer === "watch") {
    await renderWatch(body, $("drawer-title"), { onOpenAsThread: (id) => { closeDrawer(); openThread(id); } });
    return;
  }
  if (S.drawer === "changes") {
    $("drawer-title").replaceChildren(ico("diff"), "Changes");
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
    $("drawer-title").replaceChildren(ico("scroll"), "What the model is told");
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
    el("div.note", "Assembled in this order: agent system prompt → MCP/skill guidance → AGENTS.md files → configured instructions (incl. personalization) → date & environment."),
    sec("Agent · model", el("div", el("span.tag", h.agent), h.model ? el("span.tag", `${h.model.providerID}/${h.model.id}${h.model.variant && h.model.variant !== "default" ? "#" + h.model.variant : ""}`) : el("span.tag", "default model"))),
    sec("System prompt", pre(h.systemPrompt, `No override — OpenCode's built-in "${h.agent}" prompt for this provider is used.`), edit()),
    sec("Personalization", pre(h.personalization, "Nothing set."), el("button.btn.ghost.sm", { on: { click: () => openSettings("personalization", ctx) } }, ico("edit"), "Edit")),
    sec("Global AGENTS.md", pre(h.globalInstructions, "Empty."), edit()),
    sec("Project AGENTS.md", pre(h.projectInstructions, "No AGENTS.md in this project."), edit()),
  ];
  const msgs = h.systemMessages || [];
  out.push(sec(`Injected instructions (${msgs.length})`, msgs.length
    ? el("div", msgs.map((m) => el("div", { style: { marginBottom: "10px" } }, el("div", m.sources.map((s) => el("span.tag", s))), el("pre.h-pre", m.text))))
    : el("div.h-muted", "None yet — they appear after the first message.")));
  out.push(sec("Thread permissions", el("pre.h-pre", (h.permissions || []).map((r) => `${r.effect.padEnd(5)}  ${r.action}  ${r.resource}`).join("\n") || "inherited")));
  return out;
}

function updateChangesBadge() {
  const badge = $("changes-count");
  const t = S.current;
  const n = t ? collectEdits(t).length : 0;
  badge.hidden = !n;
  badge.textContent = n;
}

// ---- composer -----------------------------------------------------------------------

const currentModel = () => S.current?.session.model || S.draft.model || S.settings.defaultModel || S.defaultModel;
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
  $("pick-model").replaceChildren(ico("cpu"), el("span.lbl", modelName(ref) || "Choose model"), el("span.chev", { html: icon("chev-down") }));
  const agent = S.agents.find((a) => a.id === currentAgent());
  $("pick-agent").replaceChildren(ico("bot"), el("span.lbl", agent?.name || currentAgent()), el("span.chev", { html: icon("chev-down") }));
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

  // Context meter: the latest step's prompt size against the model's window.
  const ctx = $("ctx-meter");
  const last = t && [...t.messages].reverse().find((m) => m.type === "assistant" && m.tokens);
  const limit = findModel(ref)?.context;
  if (last && limit) {
    const used = (last.tokens.input || 0) + (last.tokens.cache?.read || 0);
    ctx.className = "ctx on";
    ctx.innerHTML = contextRing(used / limit);
    ctx.title = `Context: ${fmtTokens(used)} of ${fmtTokens(limit)} tokens`;
  } else ctx.className = "ctx";

  const hint = $("composer-hint");
  hint.textContent = busy ? "Working… press Esc to stop, or type to queue a follow-up" : project() ? `${MODES[currentMode()].sub} · ${basename(project())}` : "";
  renderAttachments();
}

function renderAttachments() {
  const box = $("attachments");
  box.replaceChildren(...S.draft.files.map((f, i) => el("span.file-chip", { title: f }, ico("file"), el("span", basename(f)),
    el("button", { type: "button", html: icon("x"), on: { click: () => { S.draft.files.splice(i, 1); renderAttachments(); } } }))));
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

function modelMenu() {
  const ref = currentModel();
  const byProvider = new Map();
  for (const m of S.models) {
    if (!byProvider.has(m.providerID)) byProvider.set(m.providerID, []);
    byProvider.get(m.providerID).push(m);
  }
  const items = [];
  for (const [pid, list] of byProvider) {
    items.push({ group: pid });
    for (const m of list) {
      items.push({
        title: m.name, sub: `${pid}${m.context ? ` · ${fmtTokens(m.context)} context` : ""}${m.tools ? "" : " · no tools"}`, keywords: pid + " " + m.id,
        checked: ref && ref.id === m.id && ref.providerID === pid,
        onSelect: () => chooseModel({ id: m.id, providerID: pid }),
      });
    }
  }
  items.push({ sep: true }, { title: "Add or manage providers…", icon: "key", onSelect: () => openSettings("models", ctx) });
  const model = findModel(ref);
  let footer = null;
  if (model?.variants?.length) {
    const seg = el("div.seg");
    for (const v of ["default", ...model.variants.filter((x) => x !== "default")]) {
      seg.append(el(`button${(ref.variant || "default") === v ? ".on" : ""}`, { type: "button", on: { click: () => { closePopover(); chooseModel({ ...ref, variant: v === "default" ? undefined : v }); } } }, v));
    }
    footer = el("div.pop-variants", el("span", "Effort"), seg);
  }
  popover($("pick-model"), items, { search: true, placeholder: "Search models", width: 340, footer, align: "right" });
}

async function chooseModel(ref) {
  if (S.current) await patchSession({ model: ref });
  else S.draft.model = ref;
  renderComposerState();
}

function agentMenu() {
  const items = S.agents.filter((a) => !a.hidden && a.mode !== "subagent").map((a) => ({
    title: a.name, sub: a.description, icon: "bot", checked: a.id === currentAgent(),
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

async function submit() {
  const ta = $("input");
  const text = ta.value.trim();
  const t = S.current;
  if (t && (t.busy || S.busy.has(t.id)) && !text) return interrupt();
  if (!text) return;
  if (!project()) return chooseFolder();
  if (!currentModel()) {
    toast("Add a provider and pick a model first", "info");
    return openSettings("models", ctx);
  }
  const files = [...S.draft.files];
  ta.value = "";
  S.draft.files = [];
  autosize();
  try {
    let thread = S.current;
    if (!thread) {
      const session = await api.post("/api/sessions", { directory: project(), model: currentModel(), agent: currentAgent(), mode: currentMode() });
      S.sessions.unshift(session);
      thread = createThread(session);
      thread.loaded = true;
      S.threads.set(session.id, thread);
      S.current = thread;
      S.draft = { model: null, agent: null, mode: null, files: [] };
      renderThreads();
      renderTopbar();
      view.mount(thread);
    }
    thread.error = null;
    S.busy.add(thread.id);
    renderComposerState();
    renderThreads();
    view.stick = true;
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
  if (type === "afh.restarting") {
    restartPill?.remove();
    restartPill = el("div.restarting", el("span.spinner"), "Applying changes — restarting OpenCode…");
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
    toast(`OpenCode error: ${ev.data?.message}`, "err", 8000);
    return;
  }

  trackEvent(ev); // delegation children register themselves on session.created
  const sid = ev.data?.sessionID || ev.data?.session_id || (type.startsWith("session.") ? ev.data?.id : null);
  if (type === "session.execution.started" && sid) S.busy.add(sid);
  if (/^session\.execution\.(succeeded|failed|interrupted)$/.test(type) && sid) S.busy.delete(sid);
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
  if (!t || !t.loaded) return;
  const result = applyEvent(t, ev);
  if (type === "session.tool.called") registerDelegation(t, ev.data);
  if (!result) return;
  if (S.current === t) {
    view.update(result);
    if (result.status) renderComposerState();
    if (result.changes || /execution\.(succeeded|failed|interrupted)/.test(type)) refreshDrawerSoon();
  } else if (D.children.has(sid)) {
    onChildEvent(sid, result, view);
    if (D.watch === sid && result.status) refreshDrawerSoon();
  }
  if (type === "permission.asked" && S.current !== t) toast(`"${t.session.title || "A thread"}" is waiting for your approval`, "info", 5000);
}

let catalogTimer = 0;
const reloadCatalogSoon = () => { clearTimeout(catalogTimer); catalogTimer = setTimeout(() => reloadCatalog().catch(() => {}), 800); };
let drawerTimer = 0;
const refreshDrawerSoon = () => { clearTimeout(drawerTimer); drawerTimer = setTimeout(refreshDrawer, 300); };

// ---- wiring ------------------------------------------------------------------------

export const ctx = { S, saveSettings, reloadCatalog, project, modelName, onReady: null, onCatalogEvent: null };
window.__afh = { S, D, ctx }; // for debugging from the devtools console

function toggleSidebar() {
  $("app").classList.toggle(innerWidth <= 980 ? "sb-open" : "sb-hidden");
  syncSidebarButton();
}

function syncSidebarButton() {
  const app = $("app");
  $("btn-expand").hidden = innerWidth <= 980 ? app.classList.contains("sb-open") : !app.classList.contains("sb-hidden");
}
addEventListener("resize", syncSidebarButton);

function wire() {
  const ta = $("input");
  ta.addEventListener("input", () => { autosize(); renderComposerState(); });
  ta.addEventListener("keydown", (e) => {
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
    const paths = [...(e.dataTransfer?.files || [])].map((f) => f.pywebviewFullPath || f.path).filter(Boolean);
    if (!paths.length) return toast("Use the paperclip to attach files", "info");
    S.draft.files.push(...paths.filter((p) => !S.draft.files.includes(p)));
    renderAttachments();
  });
  $("btn-attach").addEventListener("click", attach);
  $("pick-model").addEventListener("click", modelMenu);
  $("pick-agent").addEventListener("click", agentMenu);
  $("pick-mode").addEventListener("click", modeMenu);
  $("btn-new").addEventListener("click", () => { showHome(); ta.focus(); });
  $("project-picker").addEventListener("click", projectMenu);
  $("btn-settings").addEventListener("click", () => openSettings("general", ctx));
  $("btn-thread-menu").addEventListener("click", threadMenu);
  $("btn-changes").addEventListener("click", () => openDrawer("changes"));
  $("btn-harness").addEventListener("click", () => openDrawer("harness"));
  $("btn-context").addEventListener("click", editContext);
  $("btn-drawer-close").addEventListener("click", closeDrawer);
  $("btn-collapse").addEventListener("click", toggleSidebar);
  $("btn-expand").addEventListener("click", toggleSidebar);
  $("jump").addEventListener("click", () => { view.stick = true; view.scrollToEnd(); });
  $("thread-search").addEventListener("input", (e) => { S.search = e.target.value; renderThreads(); });

  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const overlay = document.querySelector(".scrim, .pop");
    if (mod && e.key.toLowerCase() === "n") { e.preventDefault(); showHome(); ta.focus(); }
    else if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); toggleSidebar(); }
    else if (mod && e.key === ",") { e.preventDefault(); openSettings("general", ctx); }
    else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("thread-search").focus(); }
    else if (e.key === "Escape" && !overlay && S.current && (S.current.busy || S.busy.has(S.current.id))) { e.preventDefault(); interrupt(); }
  });
  setInterval(renderThreads, 60_000);
  syncSidebarButton();
}

boot();
