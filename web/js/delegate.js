// Subagents and Delegate mode: their cards in the thread, the Watch pane, and the Delegation settings tab.
// A delegation is the engine's `subagent` tool call; its child session is tracked here so the
// card can show live progress and the Watch pane can mount the child's thread.

import { api } from "./api.js";
import { ChatView, collectEdits, createThread, loadThread, permissionCard, toolText } from "./chat.js";
import { logoNode } from "./logo.js";
import { closePopover, confirmDialog, el, ico, icon, markdown, popover, toast, toggle } from "./ui.js";

export const D = {
  children: new Map(), // childId -> { parent, msg, tool, title, agent, model }
  pendingByParent: new Map(), // parentId -> [{ msg, tool }] subagent calls waiting for their session.created
  watch: null, // child id shown in the Watch pane
};

let ctx = null;
let watchView = null;

export function initDelegate(c) {
  ctx = c;
}

function ensureChildThread(id, session) {
  const S = ctx.S;
  if (!S.threads.has(id)) {
    const t = createThread({ id, ...session });
    t.loaded = true; // events accumulate from the moment the child is born
    S.threads.set(id, t);
  }
  return S.threads.get(id);
}

/** Track child sessions as they are created. Returns the child id for a delegation event. */
export function trackEvent(ev) {
  const d = ev.data || {};
  if (ev.type === "session.created" && d.parentID) {
    const queue = D.pendingByParent.get(d.parentID) || [];
    const link = queue.shift();
    D.children.set(d.sessionID, { parent: d.parentID, msg: link?.msg || null, tool: link?.tool || null, title: d.title, agent: d.agent, model: d.model });
    ensureChildThread(d.sessionID, { title: d.title, agent: d.agent, model: d.model, parentID: d.parentID });
    return d.sessionID;
  }
  return null;
}

/** Called on session.tool.called in a parent thread: link subagent calls to their child session. */
export function registerDelegation(thread, d) {
  const m = thread.byId.get(d.assistantMessageID);
  const part = m?.content.find((x) => x.type === "tool" && x.id === d.id);
  if (!part || (part.name || "").toLowerCase() !== "subagent") return;
  const input = d.input || {};
  if (input.sessionID) {
    D.children.set(input.sessionID, { ...(D.children.get(input.sessionID) || {}), parent: thread.id, msg: m.id, tool: d.id, agent: input.agent });
    ensureChildThread(input.sessionID, { title: input.description, agent: input.agent, parentID: thread.id });
  } else {
    const q = D.pendingByParent.get(thread.id) || [];
    q.push({ msg: m.id, tool: d.id });
    D.pendingByParent.set(thread.id, q);
  }
}

/** A child session produced an event: refresh the Watch pane and the parent's card. */
export function onChildEvent(childId, result, view) {
  if (D.watch === childId && watchView) watchView.update(result);
  const info = D.children.get(childId);
  if (!info || ctx.S.current?.id !== info.parent) return;
  if (!info.msg) {
    // The link was lost (reload, or events arrived out of order): find the card by scanning.
    const parent = ctx.S.threads.get(info.parent);
    for (const m of parent?.messages || []) {
      if (m.type !== "assistant") continue;
      const p = m.content.find((x) => x.type === "tool" && (x.name || "").toLowerCase() === "subagent" && childFor(x, parent) === childId);
      if (p) { info.msg = m.id; info.tool = p.id; break; }
    }
  }
  // A working helper sends events all the time (every word it writes). Its card in the lead's thread is
  // redrawn a few times a second at most: redrawing the lead's whole message on every event made the app crawl.
  if (info.msg && !cardTimers.has(info.msg)) {
    const id = info.msg;
    cardTimers.set(id, setTimeout(() => { cardTimers.delete(id); view.update({ msg: id }); }, 220));
  }
}
const cardTimers = new Map();

/** After a thread loads: register its existing children so cards can Watch them and stream live ones. */
export async function syncChildren(parentId) {
  let kids = [];
  try {
    kids = await api.get(`/api/sessions/${parentId}/children`);
  } catch {
    return;
  }
  for (const s of kids) {
    const known = D.children.get(s.id) || {};
    D.children.set(s.id, { ...known, parent: parentId, title: s.title, agent: s.agent, model: s.model, msg: known.msg || null, tool: known.tool || null });
    const t = ensureChildThread(s.id, s);
    const live = !s.time?.idle || (s.time?.updated || 0) > s.time.idle;
    if (live && !t.messages.length) {
      t.loaded = false;
      loadThread(t).then(() => { t.loaded = true; if (t.busy) ctx.S.busy.add(s.id); }).catch(() => (t.loaded = true));
    } else if (!t.messages.length) t.loaded = false; // Watch loads it on demand
  }
}

function childFor(p, thread) {
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  if (input.sessionID) return input.sessionID;
  if (p.state?.metadata?.sessionID) return p.state.metadata.sessionID;
  for (const [cid, info] of D.children) if (info.tool === p.id) return cid;
  // History reload: match by parent + title.
  for (const [cid, info] of D.children) if (thread && info.parent === thread.id && !info.tool && info.title === input.description) return cid;
  return null;
}

const stripWrapper = (s) => (s || "").replace(/^\s*<subagent[^>]*>\s*/i, "").replace(/\s*<\/subagent>\s*$/i, "").trim();

// Each built-in role has its own mark, so a glance tells who is doing what.
const ROLE_GLYPH = { explorer: "search", researcher: "globe", coder: "code", tester: "checklist", reviewer: "shield", writer: "edit", general: "code" };

/** Who a `subagent` call went to: its name (the role, or the delegate's name), colour, mark and model. */
export function whoIs(p, thread) {
  const S = ctx.S;
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const meta = p.state?.metadata || {};
  const id = String(meta.agent || input.role || input.agent || "").toLowerCase();
  const agent = S.agents.find((a) => a.id === id);
  const deleg = S.settings.delegation?.delegates?.find((d) => d.id === id);
  const kind = meta.kind || (deleg || agent?.delegate ? "delegate" : "subagent");
  const name = meta.name || deleg?.name || agent?.name || (id === "general" ? "Coder" : id ? id[0].toUpperCase() + id.slice(1) : "Subagent");
  const childId = childFor(p, thread);
  const child = childId && S.threads.get(childId);
  const modelRef = child?.session?.model || deleg?.model || agent?.model || thread?.session?.model;
  return { id, name, kind, color: deleg?.color || agent?.color || null, glyph: ROLE_GLYPH[id] || (kind === "delegate" ? null : "bot"), modelRef, childId, child };
}

/** "Researcher 2": when one reply starts several subagents with the same job, number them so the cards differ. */
function numbered(p, thread, who) {
  const same = [];
  for (const m of thread?.messages || []) {
    if (m.type !== "assistant") continue;
    for (const x of m.content || []) {
      if (x.type !== "tool" || (x.name || "").toLowerCase() !== "subagent") continue;
      const inp = typeof x.state?.input === "object" ? x.state.input : {};
      if (inp.sessionID) continue; // a continuation is the same subagent, not a new one
      const id = String(x.state?.metadata?.agent || inp.role || inp.agent || "").toLowerCase();
      if (id === who.id) same.push(x.id);
    }
  }
  const i = same.indexOf(p.id);
  return same.length > 1 && i > 0 ? `${who.name} ${i + 1}` : who.name;
}

const clock = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
};

function avatar(who, live) {
  if (!who.glyph) return el("span.deleg-avatar", logoNode({ size: 30, working: live }));
  return el(`span.deleg-avatar.role${live ? ".live" : ""}`, { style: who.color ? { "--role": who.color } : {} }, ico(who.glyph));
}

/** The card drawn in place of a raw `subagent` tool call. */
export function delegationCard(p, { thread, onWatch, open }) {
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const who = whoIs(p, thread);
  const { childId, child } = who;
  const name = numbered(p, thread, who);
  // the name without " · high": the effort has its own badge next to it
  const model = who.modelRef ? ctx.modelName({ ...who.modelRef, variant: undefined }) || who.modelRef.id : "thread model";
  const variant = who.modelRef?.variant && who.modelRef.variant !== "default" ? who.modelRef.variant : "";
  const status = p.state?.status || "streaming";
  const live = status === "running" || status === "streaming" || status === "pending";
  const failed = status === "error" || p.state?.metadata?.status === "failed";
  const continued = !!input.sessionID;
  const lead = who.kind === "delegate" ? "What the lead asked" : "Brief";

  let stats = null;
  if (child && child.messages.length) { // only real numbers: an unloaded child would read "0 tool calls"
    const tools = child.messages.filter((m) => m.type === "assistant").flatMap((m) => m.content).filter((x) => x.type === "tool");
    const files = collectEdits(child).length;
    const lastText = [...child.messages].reverse().flatMap((m) => (m.type === "assistant" ? [...m.content].reverse() : [])).find((x) => x.type === "text" && x.text)?.text;
    const running = tools.find((x) => x.state?.status === "running" || x.state?.status === "streaming");
    const at = running?.state?.input || {}; // (still a string while it streams)
    const now = String(at.description || at.command || at.path || at.file_path || at.query || "").split("\n")[0];
    stats = el("div.deleg-live",
      el("span.deleg-stat", ico("zap"), `${tools.length} step${tools.length === 1 ? "" : "s"}`),
      files ? el("span.deleg-stat", ico("edit"), `${files} file${files === 1 ? "" : "s"} changed`) : null,
      running && live ? el("span.deleg-stat.now", el("span.spinner"), el("b", running.name), now ? el("span.deleg-now-what", String(now).slice(0, 80)) : null) : null,
      lastText && live ? el("div.deleg-last", lastText.length > 220 ? lastText.slice(0, 220) + "…" : lastText) : null);
  }
  const report = !live ? stripWrapper(toolText(p.state?.content)).replace(/\n*The (subagent|delegate) stopped before finishing\.[\s\S]*$/, "").trim() : "";
  const reason = failed ? (report.match(/^Stopped on an error: ([^\n]+)/)?.[1] || p.state?.error?.message || "It stopped on an error.") : "";
  const body = failed ? report.replace(/^Stopped on an error: [^\n]+\n*/, "").trim() : report;
  const waiting = live && child ? [...child.permissions.values()] : [];
  const state = waiting.length ? "waiting" : failed ? "error" : live ? "running" : "completed";
  const label = waiting.length ? "Needs approval" : failed ? "Failed" : live ? (status === "running" ? "Working" : "Starting") : "Done";
  const started = p.state?.time?.start || p.time?.created || child?.session?.time?.created;
  const took = p.state?.metadata?.duration_ms;
  const timer = live && started ? el("span.deleg-time", { dataset: { since: String(started) } }, clock(Date.now() - started)) : took ? el("span.deleg-time", clock(took)) : null;
  // Brief and report: two toggles side by side in one footer row; each opens its own panel below it.
  const heads = [], bodies = [];
  const section = (key, title, glyph, content) => {
    const k = `${p.id}:${key}`;
    const box = el(`div.deleg-sec${open.has(k) ? ".open" : ""}`, el("div.deleg-sec-body", el("div", content)));
    const head = el(`button.deleg-sec-head${open.has(k) ? ".on" : ""}`, { type: "button", "aria-expanded": String(open.has(k)),
      on: { click: () => { const o = box.classList.toggle("open"); head.classList.toggle("on", o); head.setAttribute("aria-expanded", String(o)); open[o ? "add" : "delete"](k); } } },
    ico(glyph), title, el("span.chev", { html: icon("chev-down") }));
    heads.push(head); bodies.push(box);
  };
  if (input.prompt) section("brief", lead, "file", el("div.deleg-brief-text", input.prompt));
  if (body) section("report", failed ? "What it did before it stopped" : "Full report", "list", el("div.md", { html: markdown(body) }));
  return el(`div.deleg.${state}.kind-${who.kind}`, { dataset: { tool: p.id }, style: who.color ? { "--role": who.color } : {} },
    live ? el("div.deleg-progress") : null,
    el("div.deleg-head",
      avatar(who, live),
      el("div.deleg-main",
        el("div.deleg-title", el("span.deleg-name", name),
          el("span.deleg-model", model, variant ? el("span.deleg-variant", variant) : null),
          who.kind === "delegate" ? el("span.deleg-tag", "delegate") : null,
          continued ? el("span.deleg-tag", "continued") : null, input.background ? el("span.deleg-tag", "background") : null,
          input.worktree ? el("span.deleg-tag", ico("branch"), "worktree") : null),
        el("div.deleg-sub", { title: input.description || "" }, input.description || "Subagent task")),
      timer,
      el(`span.deleg-status.${state}`, el("i"), label),
      childId ? el("button.btn.ghost.sm.deleg-watch", { type: "button", title: "Open its thread beside this one", on: { click: () => onWatch(childId) } }, ico("eye"), "Watch") : null),
    stats,
    failed ? el("div.deleg-fail", ico("alert"), el("div", el("b", "Stopped before finishing"), el("span", reason))) : null,
    waiting.length ? el("div.deleg-perms", waiting.map((perm) => permissionCard(perm, childId, (id) => child.permissions.delete(id)))) : null,
    body && !failed ? el("div.deleg-gist", gist(body)) : null,
    heads.length ? el("div.deleg-foot", heads) : null,
    bodies);
}

/** The report's opening in plain text: a team of four reads at a glance, the full reports stay one click away. */
function gist(md) {
  const lines = md.replace(/```[\s\S]*?```/g, " ").split("\n").map((l) => l.trim())
    .filter((l) => l && !/^#{1,6}\s/.test(l) && !/^[-*_]{3,}$/.test(l) && !/^\|/.test(l))
    .map((l) => l.replace(/^(>\s*)+/, "").replace(/^([-*+•]|\d+[.)])\s+/, ""));
  // code spans stay as written (`amount * rate`); markup is removed only outside them
  const plain = lines.join(" ").split("`").map((s, i) => (i % 2 ? s : s.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/\*\*|__/g, "").replace(/(^|\W)[*_](\S[^*_]*?)[*_](?=\W|$)/g, "$1$2"))).join("").replace(/\s+/g, " ").trim();
  return plain.length > 260 ? plain.slice(0, 260).replace(/\s\S*$/, "") + "…" : plain;
}

// Running cards show their time ticking without redrawing the thread.
setInterval(() => {
  for (const t of document.querySelectorAll(".deleg-time[data-since]")) t.textContent = clock(Date.now() - Number(t.dataset.since));
}, 1000);

// ---- Watch pane ------------------------------------------------------------------------

export async function renderWatch(body, titleBox, { onOpenAsThread }) {
  const S = ctx.S;
  const id = D.watch;
  const info = D.children.get(id) || {};
  body.replaceChildren();
  if (!id) {
    body.append(el("div.drawer-empty", "Nothing to watch."));
    return;
  }
  let t = S.threads.get(id);
  if (!t) {
    t = ensureChildThread(id, { title: info.title });
    t.loaded = false;
  }
  const agentId = info.agent || t.session.agent;
  const deleg = S.settings.delegation?.delegates.find((d) => d.id === agentId);
  const live = t.busy || S.busy.has(id);
  const roleAgent = S.agents.find((a) => a.id === agentId);
  titleBox.replaceChildren(ROLE_GLYPH[agentId] ? el("span.deleg-avatar.role.sm", { style: roleAgent?.color ? { "--role": roleAgent.color } : {} }, ico(ROLE_GLYPH[agentId])) : logoNode({ size: 26, working: live }),
    el("span", deleg?.name || roleAgent?.name || (agentId === "general" ? "Coder" : agentId) || "Subagent"),
    el("span.pill-tag", ctx.modelName(deleg?.model || t.session.model) || "model"),
    el("button.btn.ghost.sm", { style: { marginLeft: "6px" }, title: "Open as its own thread", on: { click: () => onOpenAsThread(id) } }, ico("chev")));
  const root = el("div.thread-inner.watch-inner");
  body.append(root);
  if (!t.loaded || !t.messages.length) {
    root.append(el("div.drawer-empty", el("span.spinner")));
    try {
      await loadThread(t);
      if (t.busy) S.busy.add(id);
    } catch (e) {
      root.replaceChildren(el("div.drawer-empty", e.message));
      return;
    }
    if (D.watch !== id) return;
    root.replaceChildren();
  }
  watchView = new ChatView(root, body, { settings: () => S.settings, modelName: ctx.modelName, onFork: () => {}, onRetry: () => {}, onStatus: () => {} });
  watchView.mount(t);
}

export function closeWatch() {
  D.watch = null;
  watchView = null;
}

// ---- Settings → Delegation ---------------------------------------------------------------

const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32) || "delegate";
const COLORS = ["#ff6a2a", "#ff3d71", "#f59f00", "#2fbf71", "#22b8cf", "#4f8cff", "#7c6cff", "#e64980"];

export async function delegationPane(pane, c) {
  const S = c.S;
  const data = await api.get("/api/delegation");
  const state = { leaderInstructions: data.leaderInstructions || "", delegates: (data.delegates || []).map((d) => ({ ...d })), builtinHelper: data.builtinHelper !== false };
  let dirty = false;
  const saveBtn = el("button.btn.primary", { disabled: true }, "Save & apply");
  const markDirty = () => { dirty = true; saveBtn.disabled = false; };

  pane.append(el("h2", "Delegation"),
    el("p.lead", "Delegate mode makes the thread's model the leader: it plans, talks to you and reviews, and hands tasks to the delegates below — each a different model with its own job. Pick “Delegate” in the mode menu of any thread, even mid-conversation."),
    el("div.note", el("b", "How the leader decides. "), "It reads each delegate's job description and delegates when a task matches. It can continue a delegate's existing session or start a fresh one, and can run a delegate in the background. You'll see a card for every delegation with live progress, a Watch button that opens the delegate's thread beside yours, and the delegate's report."));

  const list = el("div");
  const draw = () => {
    list.replaceChildren();
    if (!state.delegates.length) list.append(el("div.empty-row", "No delegates yet. Add one — for example a fast model whose job is “write and edit code”, or a strong model whose job is “review diffs and find bugs”."));
    state.delegates.forEach((d, i) => list.append(delegateEditor(d, i)));
  };
  const delegateEditor = (d, i) => {
    const modelSel = el("select.sel", el("option", { value: "" }, "Use the thread's model"), S.models.map((m) => el("option", { value: `${m.providerID}/${m.id}`, selected: d.model && d.model.id === m.id && d.model.providerID === m.providerID }, `${m.name} — ${m.providerID}`)));
    const variants = () => { const m = S.models.find((x) => d.model && x.id === d.model.id && x.providerID === d.model.providerID); return m?.variants || []; };
    const varSel = el("select.sel", { style: { width: "140px" } });
    const drawVariants = () => {
      varSel.replaceChildren(el("option", { value: "" }, "default effort"), variants().map((v) => el("option", { value: v, selected: d.model?.variant === v }, v)));
      varSel.disabled = !variants().length;
    };
    drawVariants();
    modelSel.addEventListener("change", () => { const [providerID, ...rest] = modelSel.value.split("/"); d.model = modelSel.value ? { providerID, id: rest.join("/") } : null; drawVariants(); markDirty(); });
    varSel.addEventListener("change", () => { if (d.model) d.model.variant = varSel.value || undefined; markDirty(); });
    const name = el("input.inp", { value: d.name || "", placeholder: "Coder", on: { input: (e) => { d.name = e.target.value; if (!d._idLocked) { d.id = slug(e.target.value); idBox.textContent = d.id; } markDirty(); } } });
    const idBox = el("code", { style: { font: "12px var(--mono)", color: "var(--text-3)" } }, d.id || "");
    d._idLocked = !!d.id && !!(data.delegates || []).find((x) => x.id === d.id);
    const job = el("textarea.ta", { rows: 3, value: d.job || "", placeholder: "Writes and edits code when the leader asks. Good at Python and TypeScript. Delegate implementation tasks, bug fixes and tests here.", on: { input: (e) => { d.job = e.target.value; markDirty(); } } });
    const sys = el("textarea.ta.code", { style: { minHeight: "110px" }, value: d.system || "", placeholder: "Optional extra instructions for this delegate (added to its system prompt).", on: { input: (e) => { d.system = e.target.value; markDirty(); } } });
    const swatches = el("div.swatches", COLORS.map((col) => el(`button.swatch${(d.color || COLORS[i % COLORS.length]) === col ? ".on" : ""}`, { type: "button", style: { background: col, width: "20px", height: "20px" }, on: { click: (e) => { d.color = col; swatches.querySelectorAll(".swatch").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); markDirty(); } } })));
    const card = el("div.card.dg-card", { style: { borderLeft: `3px solid ${d.color || COLORS[i % COLORS.length]}` } },
      el("div.card-head", el("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, logoNode({ size: 26 }), el("h3", d.name || "New delegate"), idBox),
        el("div", { style: { display: "flex", alignItems: "center", gap: "10px" } },
          el("span.h-muted", { style: { fontStyle: "normal", fontSize: "12px" } }, "enabled"), toggle(d.enabled !== false, (v) => { d.enabled = v; markDirty(); }),
          el("button.btn.ghost.sm.danger", { title: "Remove", on: { click: async () => { if (!(await confirmDialog({ title: `Remove ${d.name || "this delegate"}?`, body: "The leader will stop delegating to it.", confirm: "Remove", danger: true }))) return; state.delegates.splice(i, 1); markDirty(); draw(); } } }, ico("trash")))),
      el("div.card-body",
        el("div.grid2", el("div.field", el("label", "Name"), name), el("div.field", el("label", "Model"), el("div", { style: { display: "flex", gap: "8px" } }, modelSel, varSel))),
        el("div.field", el("label", "Its job — when should the leader delegate to it?"), job, el("div.help", "The leader reads this to decide. Be concrete: what it's good at, what to send it, what not to.")),
        el("details", el("summary", { style: { cursor: "pointer", color: "var(--text-2)", fontSize: "13px", marginBottom: "8px" } }, "Advanced: extra system prompt, read-only, color"),
          el("div.field", { style: { marginTop: "10px" } }, el("label", "Extra system prompt"), sys),
          el("div.row", { style: { padding: "8px 0" } }, el("div.rl", el("b", "Read only"), el("span", "Can read and search but never edit or run commands — good for reviewers")), toggle(!!d.readonly, (v) => { d.readonly = v; markDirty(); })),
          el("div.row", { style: { padding: "8px 0", borderBottom: 0 } }, el("div.rl", el("b", "Color")), swatches))));
    return card;
  };
  draw();

  const addBtn = el("button.btn.sm", { on: { click: () => { state.delegates.push({ id: "", name: "", model: null, job: "", system: "", enabled: true, readonly: false, color: COLORS[state.delegates.length % COLORS.length] }); markDirty(); draw(); list.lastElementChild?.querySelector("input")?.focus(); } } }, ico("plus"), "Add delegate");
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Subagents"), el("p", "In Build, Plan and your own modes the model can start subagents on its own model, each with one job: Explorer, Researcher, Coder, Tester, Reviewer and Writer. Delegate mode uses only the delegates below.")),
    toggle(state.builtinHelper, (v) => { state.builtinHelper = v; markDirty(); }))));
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Delegates"), el("p", `${state.delegates.length} configured`)), addBtn), list));

  const leaderTa = el("textarea.ta", { rows: 4, value: state.leaderInstructions, placeholder: "Always ask the Reviewer to check the Coder's work before reporting back.\nNever delegate anything that touches the payments module.", on: { input: (e) => { state.leaderInstructions = e.target.value; markDirty(); } } });
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Leader instructions"), el("p", "Extra rules for the leader, added to its system prompt"))), el("div.card-body", leaderTa)));

  saveBtn.addEventListener("click", async () => {
    const bad = state.delegates.find((d) => !d.name?.trim() || !d.job?.trim());
    if (bad) return toast("Every delegate needs a name and a job description", "err");
    const ids = state.delegates.map((d) => d.id || slug(d.name));
    if (new Set(ids).size !== ids.length) return toast("Two delegates have the same id — give them different names", "err");
    try {
      await api.put("/api/delegation", { builtinHelper: state.builtinHelper, leaderInstructions: state.leaderInstructions, delegates: state.delegates.map((d) => ({ ...d, id: d.id || slug(d.name), _idLocked: undefined })) });
      toast("Saved — applies to the next message", "ok");
      dirty = false;
      saveBtn.disabled = true;
      c.saveSettings({}).catch(() => {});
    } catch (e) {
      toast(e.message, "err", 6000);
    }
  });
  pane.append(el("div.actions", el("span.h-muted", { style: { flex: 1, fontStyle: "normal", fontSize: "12.5px", alignSelf: "center" } }, "Changes apply to the next message in every thread."), saveBtn));
}

// ---- top bar: every subagent of the open thread ----------------------------------------

/** Every `subagent` call in a thread, newest first. */
export function subagentsOf(thread) {
  const out = [];
  for (const m of thread?.messages || []) {
    if (m.type !== "assistant") continue;
    for (const p of m.content || []) if (p.type === "tool" && (p.name || "").toLowerCase() === "subagent") out.push(p);
  }
  return out.reverse();
}

const isLive = (p) => ["running", "streaming", "pending"].includes(p.state?.status || "streaming");

/** The chip beside the thread title: how many subagents work right now, or how many ran. */
export function renderSubagentsChip(btn, thread) {
  const all = subagentsOf(thread);
  if (!all.length) { btn.hidden = true; return; }
  const live = all.filter(isLive).length;
  btn.hidden = false;
  btn.className = `sub-chip${live ? " live" : ""}`;
  btn.title = live ? `${live} subagent${live > 1 ? "s" : ""} working — click to see what they were asked and what they said` : `${all.length} subagent${all.length > 1 ? "s" : ""} in this thread`;
  btn.dataset.n = String(live || all.length); // a narrow top bar shows only the mark and this number
  btn.replaceChildren(live ? el("span.sub-dots", el("i"), el("i"), el("i")) : ico("bot"), el("span.sub-txt", live ? `${live} working` : `${all.length} subagent${all.length > 1 ? "s" : ""}`));
}

export function subagentsPopover(anchor, thread, onWatch) {
  const S = ctx.S;
  const box = el("div.sub-pop");
  const draw = () => {
    const all = subagentsOf(thread);
    const live = all.filter(isLive).length;
    box.replaceChildren(el("div.sub-pop-head", ico("bot"), el("b", "Subagents"), el("span", live ? `${live} working · ${all.length} in this thread` : `${all.length} in this thread`)));
    if (!all.length) box.append(el("div.empty-row", "No subagents in this thread yet."));
    for (const p of all) {
      const input = typeof p.state?.input === "object" ? p.state.input : {};
      const who = whoIs(p, thread);
      const name = numbered(p, thread, who);
      const childId = who.childId;
      const failed = p.state?.status === "error" || p.state?.metadata?.status === "failed";
      const st = isLive(p) ? (p.state?.status === "running" ? "running" : "streaming") : failed ? "error" : "completed";
      const reply = !isLive(p) ? stripWrapper(toolText(p.state?.content)) : "";
      box.append(el(`div.sub-item.${st}`,
        el("div.sub-item-head",
          el(`span.deleg-status.${st}`, el("i"), st === "completed" ? "Done" : st === "error" ? "Failed" : st === "running" ? "Working" : "Starting"),
          el("b", name), el("span.sub-desc", { title: input.description || "" }, input.description || ""),
          childId ? el("button.btn.ghost.sm", { on: { click: () => { closeSubPop(); onWatch(childId); } } }, ico("eye"), "Watch") : null),
        input.prompt ? el("details", el("summary", who.kind === "delegate" ? "What the lead asked" : "Brief"), el("div.sub-text", input.prompt)) : null,
        reply ? el("details", el("summary", "Report"), el("div.sub-text.md", { html: markdown(reply) })) : isLive(p) ? el("div.sub-wait", el("span.spinner"), "Working on it…") : null));
    }
  };
  draw();
  const pop = popover(anchor, [], { header: box, width: 480 });
  // Keep it live while open, but leave sections the user opened alone: only redraw while something works.
  const timer = setInterval(() => { if (!pop.isConnected) return clearInterval(timer); if (subagentsOf(thread).some(isLive) && !box.querySelector("details[open]")) draw(); }, 1500);
}

const closeSubPop = () => closePopover();
