// Delegate mode: delegation cards in the thread, the Watch pane, and the Delegation settings tab.
// A delegation is the engine's `subagent` tool call; its child session is tracked here so the
// card can show live progress and the Watch pane can mount the child's thread.

import { api } from "./api.js";
import { ChatView, collectEdits, createThread, loadThread, permissionCard, toolText } from "./chat.js";
import { logoNode } from "./logo.js";
import { confirmDialog, el, ico, icon, markdown, toast, toggle } from "./ui.js";

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
  if (info.msg) view.update({ msg: info.msg });
}

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

/** The card drawn in place of a raw `subagent` tool call. */
export function delegationCard(p, { thread, onWatch, open }) {
  const S = ctx.S;
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const agent = S.agents.find((a) => a.id === input.agent);
  const deleg = S.settings.delegation?.delegates.find((d) => d.id === input.agent);
  const name = deleg?.name || agent?.name || input.agent || "delegate";
  const modelRef = deleg?.model || agent?.model;
  const model = modelRef ? ctx.modelName(modelRef) || modelRef.id : "thread model";
  const status = p.state?.status || "streaming";
  const live = status === "running" || status === "streaming";
  const childId = childFor(p, thread);
  const child = childId && S.threads.get(childId);
  const continued = !!input.sessionID;

  let stats = null;
  if (child) {
    const tools = child.messages.filter((m) => m.type === "assistant").flatMap((m) => m.content).filter((x) => x.type === "tool");
    const files = collectEdits(child).length;
    const lastText = [...child.messages].reverse().flatMap((m) => (m.type === "assistant" ? [...m.content].reverse() : [])).find((x) => x.type === "text" && x.text)?.text;
    const running = tools.find((x) => x.state?.status === "running" || x.state?.status === "streaming");
    stats = el("div.deleg-live",
      el("span.deleg-stat", ico("zap"), `${tools.length} tool call${tools.length === 1 ? "" : "s"}`),
      el("span.deleg-stat", ico("edit"), `${files} file${files === 1 ? "" : "s"}`),
      running ? el("span.deleg-stat.now", el("span.spinner"), running.name) : null,
      lastText ? el("div.deleg-last", lastText.length > 180 ? lastText.slice(0, 180) + "…" : lastText) : null);
  }
  const result = !live ? stripWrapper(toolText(p.state?.content)) : "";
  const waiting = live && child ? [...child.permissions.values()] : [];
  const label = waiting.length ? "needs approval" : status === "completed" ? "done" : status === "error" ? "failed" : status === "running" ? "working" : "preparing";
  return el(`div.deleg.${status}${open.has(p.id) ? ".open" : ""}`, { dataset: { tool: p.id } },
    el("div.deleg-head",
      logoNode({ size: 40, working: live }),
      el("div.deleg-main",
        el("div.deleg-title", `Delegated to ${name}`, el("span.pill-tag", model), continued ? el("span.pill-tag", "continued") : null, input.background ? el("span.pill-tag", "background") : null),
        el("div.deleg-sub", input.description || "")),
      el(`span.deleg-status.${waiting.length ? "waiting" : status}`, label),
      childId ? el("button.btn.sm", { type: "button", title: "Open the delegate's thread beside this one", on: { click: () => onWatch(childId) } }, ico("eye"), "Watch") : null),
    stats,
    waiting.length ? el("div.deleg-perms", waiting.map((perm) => permissionCard(perm, childId, (id) => child.permissions.delete(id)))) : null,
    input.prompt ? el("details.deleg-brief", el("summary", "Brief sent to the delegate"), el("pre.tool-pre", input.prompt)) : null,
    result ? el("div.deleg-result", el("div.tool-section-label", "Report"), el("div.md", { html: markdown(result) })) : null,
    p.state?.error ? el("div.error-card", ico("alert"), el("div", p.state.error.message || "Delegation failed")) : null);
}

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
  const deleg = S.settings.delegation?.delegates.find((d) => d.id === (info.agent || t.session.agent));
  const live = t.busy || S.busy.has(id);
  titleBox.replaceChildren(logoNode({ size: 26, working: live }), el("span", deleg?.name || info.agent || "Delegate"),
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
  const state = { leaderInstructions: data.leaderInstructions || "", delegates: (data.delegates || []).map((d) => ({ ...d })) };
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
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Delegates"), el("p", `${state.delegates.length} configured`)), addBtn), list));

  const leaderTa = el("textarea.ta", { rows: 4, value: state.leaderInstructions, placeholder: "Always ask the Reviewer to check the Coder's work before reporting back.\nNever delegate anything that touches the payments module.", on: { input: (e) => { state.leaderInstructions = e.target.value; markDirty(); } } });
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Leader instructions"), el("p", "Extra rules for the leader, added to its system prompt"))), el("div.card-body", leaderTa)));

  saveBtn.addEventListener("click", async () => {
    const bad = state.delegates.find((d) => !d.name?.trim() || !d.job?.trim());
    if (bad) return toast("Every delegate needs a name and a job description", "err");
    const ids = state.delegates.map((d) => d.id || slug(d.name));
    if (new Set(ids).size !== ids.length) return toast("Two delegates have the same id — give them different names", "err");
    try {
      await api.put("/api/delegation", { leaderInstructions: state.leaderInstructions, delegates: state.delegates.map((d) => ({ ...d, id: d.id || slug(d.name), _idLocked: undefined })) });
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
