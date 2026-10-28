// Thread model + rendering. History (message.list) and live events share one shape,
// so a single renderer draws both.

import { api } from "./api.js";
import { el, ico, icon, markdown, diffView, patchFromStrings, copyText, fmtTokens, basename, toast } from "./ui.js";

// ---- state ----------------------------------------------------------------------

export function createThread(session) {
  return {
    id: session.id,
    session,
    messages: [],
    byId: new Map(),
    permissions: new Map(),
    busy: false,
    error: null,
    retry: null,
    loaded: false,
    tokens: session.tokens || null,
  };
}

export async function loadThread(t) {
  const [messages, perms] = await Promise.all([
    api.get(`/api/sessions/${t.id}/messages`),
    api.get(`/api/sessions/${t.id}/permissions`).catch(() => []),
  ]);
  t.messages = [];
  t.byId.clear();
  for (const m of messages) addMessage(t, m);
  t.permissions = new Map(perms.map((p) => [p.id, p]));
  const last = [...t.messages].reverse().find((m) => m.type === "assistant" || m.type === "idle");
  t.busy = !!(last && last.type === "assistant" && !last.time?.completed && !last.finish);
  t.loaded = true;
}

function addMessage(t, m) {
  if (t.byId.has(m.id)) return t.byId.get(m.id);
  t.byId.set(m.id, m);
  t.messages.push(m);
  return m;
}

function assistant(t, id, data = {}) {
  let m = t.byId.get(id);
  if (!m) m = addMessage(t, { id, type: "assistant", content: [], time: { created: Date.now() }, agent: data.agent, model: data.model, live: true });
  return m;
}

function part(m, type, ordinal) {
  let p = m.content.find((x) => x.type === type && x.ordinal === ordinal);
  if (!p) {
    p = { type, ordinal, text: "", live: true, started: Date.now() };
    m.content.push(p);
  }
  return p;
}

function tool(m, id, name) {
  let p = m.content.find((x) => x.type === "tool" && x.id === id);
  if (!p) {
    p = { type: "tool", id, name: name || "tool", state: { status: "streaming", input: "" } };
    m.content.push(p);
  }
  if (name) p.name = name;
  return p;
}

/** Apply one OpenCode event. Returns {msg} for a message re-render, {all} for a full one, or {perm}. */
export function applyEvent(t, ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "session.inbox.enqueued": {
      const item = d.item || {};
      if (item.type === "user" && !t.byId.has(d.inboxID)) {
        addMessage(t, { id: d.inboxID, type: "user", text: item.payload?.text || "", files: item.payload?.files, time: { created: ev.created || Date.now() }, pending: true });
        return { all: true };
      }
      return null;
    }
    case "session.inbox.delivered": {
      const m = t.byId.get(d.inboxID);
      if (m) m.pending = false;
      return null;
    }
    case "session.execution.started":
      t.busy = true;
      t.error = null;
      return { status: true };
    case "session.execution.succeeded":
    case "session.execution.interrupted":
      t.busy = false;
      t.retry = null;
      finishLive(t);
      return { status: true, all: true };
    case "session.execution.failed":
      t.busy = false;
      t.retry = null;
      t.error = d.error || { message: "The run failed" };
      finishLive(t);
      return { status: true, all: true };
    case "session.retry.scheduled":
      t.retry = d;
      t.retryError = d.error || t.retryError;
      return { status: true };
    case "session.step.started":
      assistant(t, d.assistantMessageID, d);
      return { all: true };
    case "session.step.failed": {
      const m = assistant(t, d.assistantMessageID);
      if (isStop(d.error)) m.stopped = true;
      else m.error = d.error?.message;
      return { msg: m.id };
    }
    case "session.step.ended": {
      const m = assistant(t, d.assistantMessageID);
      m.tokens = d.tokens;
      m.finish = d.finish;
      return { msg: m.id };
    }
    case "session.reasoning.started":
    case "session.text.started": {
      const m = assistant(t, d.assistantMessageID);
      part(m, ev.type.includes("reasoning") ? "reasoning" : "text", d.ordinal);
      return { msg: m.id };
    }
    case "session.reasoning.delta":
    case "session.text.delta": {
      const m = assistant(t, d.assistantMessageID);
      part(m, ev.type.includes("reasoning") ? "reasoning" : "text", d.ordinal).text += d.delta || "";
      return { msg: m.id, stream: true };
    }
    case "session.reasoning.ended":
    case "session.text.ended": {
      const m = assistant(t, d.assistantMessageID);
      const p = part(m, ev.type.includes("reasoning") ? "reasoning" : "text", d.ordinal);
      if (d.text != null) p.text = d.text;
      p.live = false;
      p.ended = Date.now();
      return { msg: m.id };
    }
    case "session.tool.input.started": {
      const m = assistant(t, d.assistantMessageID);
      tool(m, d.id, d.name);
      return { msg: m.id };
    }
    case "session.tool.input.delta": {
      const m = assistant(t, d.assistantMessageID);
      const p = tool(m, d.id);
      if (typeof p.state.input === "string") p.state.input += d.delta || "";
      return { msg: m.id, stream: true };
    }
    case "session.tool.called": {
      const m = assistant(t, d.assistantMessageID);
      const p = tool(m, d.id);
      p.state = { status: "running", input: d.input || {}, metadata: {} };
      return { msg: m.id };
    }
    case "session.tool.progress": {
      const m = assistant(t, d.assistantMessageID);
      const p = tool(m, d.id);
      p.state.metadata = { ...(p.state.metadata || {}), ...(d.metadata || {}) };
      if (d.content) p.state.content = d.content;
      return { msg: m.id, stream: true };
    }
    case "session.tool.success":
    case "session.tool.failed": {
      const m = assistant(t, d.assistantMessageID);
      const p = tool(m, d.id);
      const input = typeof p.state.input === "object" ? p.state.input : {};
      p.state = ev.type.endsWith("success")
        ? { status: "completed", input, content: d.content || [], metadata: d.metadata }
        : { status: "error", input, error: d.error, content: d.content, metadata: d.metadata };
      return { msg: m.id, changes: true };
    }
    case "session.usage.updated":
      t.tokens = d.tokens;
      return { status: true };
    case "permission.asked":
      t.permissions.set(d.id, d);
      return { perm: true };
    case "permission.replied":
      t.permissions.delete(d.id || d.permissionID || d.requestID);
      return { perm: true };
    case "session.compaction.ended":
      addMessage(t, { id: ev.id, type: "compaction", time: { created: Date.now() } });
      return { all: true };
    case "session.model.selected":
    case "session.agent.selected":
      return { status: true };
    default:
      return null;
  }
}

const isStop = (err) => /interrupt|abort|cancel/i.test(`${err?.type || ""} ${err?.message || ""}`);

function finishLive(t) {
  for (const m of t.messages) {
    if (m.type !== "assistant") continue;
    m.live = false;
    for (const p of m.content) p.live = false;
  }
}

// ---- tools ----------------------------------------------------------------------

const pick = (o, ...keys) => {
  for (const k of keys) if (o && o[k] != null && o[k] !== "") return o[k];
  return null;
};

export function describeTool(p) {
  const name = (p.name || "tool").toLowerCase();
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const path = pick(input, "path", "filePath", "file_path", "file");
  const short = (s) => (s ? String(s).replace(/^.*[\\/](?=[^\\/]+[\\/][^\\/]+$)/, "…/") : "");
  if (/^(write|edit|multiedit|patch|apply_patch)$/.test(name)) return { icon: "edit", label: name === "write" ? "Write" : "Edit", target: short(path), edit: true };
  if (name === "read") return { icon: "file", label: "Read", target: short(path) };
  if (/^(shell|bash|exec|command)$/.test(name)) return { icon: "terminal", label: "Run", target: pick(input, "command", "cmd") || "" };
  if (/^(grep|glob|search|find|list|ls)$/.test(name)) return { icon: "search", label: name[0].toUpperCase() + name.slice(1), target: pick(input, "pattern", "query", "path") || "" };
  if (/web|fetch|browse/.test(name)) return { icon: "globe", label: name === "websearch" ? "Search web" : "Fetch", target: pick(input, "url", "query") || "" };
  if (/task|agent/.test(name)) return { icon: "bot", label: "Subagent", target: pick(input, "description", "prompt") || "" };
  if (/todo/.test(name)) return { icon: "list", label: "Plan", target: "" };
  if (/skill/.test(name)) return { icon: "book", label: "Skill", target: pick(input, "name", "id") || "" };
  const first = Object.values(input).find((v) => typeof v === "string") || "";
  return { icon: name.includes("_") || name.includes(".") ? "plug" : "zap", label: p.name, target: first };
}

/** File patches a tool produced: from metadata.files when present, else rebuilt from its input. */
export function toolPatches(p) {
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const meta = p.state?.metadata || {};
  if (Array.isArray(meta.files) && meta.files.length) return meta.files.map((f) => ({ file: f.file, patch: f.patch, additions: f.additions, deletions: f.deletions, status: f.status }));
  const file = pick(input, "path", "filePath", "file_path");
  const name = (p.name || "").toLowerCase();
  if (pick(input, "patch", "patchText", "diff")) return [{ file: file || "patch", patch: pick(input, "patch", "patchText", "diff") }];
  if (name === "write" && typeof input.content === "string") return [{ file, patch: patchFromStrings("", input.content), status: "added" }];
  const oldS = pick(input, "oldString", "old_string", "old"), newS = pick(input, "newString", "new_string", "new");
  if (newS != null) return [{ file, patch: patchFromStrings(oldS || "", newS), status: "modified" }];
  if (Array.isArray(input.edits)) return input.edits.map((e) => ({ file, patch: patchFromStrings(pick(e, "oldString", "old_string") || "", pick(e, "newString", "new_string") || ""), status: "modified" }));
  return [];
}

const countPatch = (patch) => {
  let a = 0, r = 0;
  for (const l of (patch || "").split("\n")) {
    if (l.startsWith("+") && !l.startsWith("+++")) a++;
    else if (l.startsWith("-") && !l.startsWith("---")) r++;
  }
  return [a, r];
};

export function toolText(content) {
  return (content || []).map((c) => (c.type === "text" ? c.text : c.type === "file" ? `[file] ${c.name || c.uri || ""}` : "")).join("\n").trim();
}

/** Renderers other modules plug in: hooks.delegation(part, {thread, open}) draws `subagent` calls. */
export const hooks = {};

function renderTool(p, openSet, thread) {
  if ((p.name || "").toLowerCase() === "subagent" && hooks.delegation) return hooks.delegation(p, { thread, open: openSet });
  const info = describeTool(p);
  const status = p.state?.status || "streaming";
  const live = status === "streaming" || status === "running";
  const patches = info.edit ? toolPatches(p) : [];
  let stat = null;
  if (patches.length) {
    const [a, r] = patches.reduce((acc, x) => { const [aa, rr] = x.additions != null ? [x.additions, x.deletions] : countPatch(x.patch); return [acc[0] + aa, acc[1] + rr]; }, [0, 0]);
    stat = el("span.tool-stat", el("span.plus", `+${a}`), el("span.minus", `−${r}`));
  } else if (status === "error") stat = el("span.tool-stat", "failed");
  else if (live) stat = el("span.tool-stat", status === "streaming" ? "preparing" : "running");

  const card = el(`div.tool.${status}${openSet.has(p.id) ? ".open" : ""}`, { dataset: { tool: p.id } });
  const head = el("button.tool-head", { type: "button", on: { click: () => { card.classList.toggle("open"); openSet[card.classList.contains("open") ? "add" : "delete"](p.id); } } },
    el("span.tool-ico", live ? el("span.spinner") : ico(info.icon)),
    el("span.tool-name", info.label),
    el("span.tool-target", { title: info.target }, info.target),
    stat);
  const sections = [];
  if (patches.length) for (const x of patches) sections.push(el("div.tool-section", patches.length > 1 ? el("div.tool-section-label", basename(x.file)) : null, diffView(x.patch)));
  else {
    const input = p.state?.input;
    const inputText = typeof input === "string" ? input : input && Object.keys(input).length ? (info.label === "Run" ? pick(input, "command", "cmd") : JSON.stringify(input, null, 2)) : "";
    if (inputText) sections.push(el("div.tool-section", el("div.tool-section-label", "Input"), el("pre.tool-pre", inputText)));
  }
  const out = toolText(p.state?.content);
  if (out) sections.push(el("div.tool-section", el("div.tool-section-label", "Output"), el("pre.tool-pre", out.length > 20000 ? out.slice(0, 20000) + "\n…" : out)));
  if (p.state?.error) sections.push(el("div.tool-section", el("pre.tool-pre.tool-error", p.state.error.message || JSON.stringify(p.state.error))));
  card.append(head, el("div.tool-body", el("div", sections)));
  return card;
}

// ---- view -----------------------------------------------------------------------

export class ChatView {
  constructor(root, scroller, opts) {
    this.root = root;
    this.scroller = scroller;
    this.opts = opts; // {settings(), modelName(ref), onFork(msgId), onRetry()}
    this.thread = null;
    this.nodes = new Map();
    this.pending = new Set();
    this.streaming = new Set();
    this.openTools = new Set();
    this.openThinks = new Set();
    this.frame = 0;
    this.stick = true;
    this.autoScrolling = false;
    // Programmatic scrolls must not flip `stick`; only the user's own scrolling does.
    scroller.addEventListener("scroll", () => {
      if (!this.autoScrolling) this.stick = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 60;
      opts.onScroll?.(this.stick, scroller.scrollTop);
    });
    scroller.addEventListener("wheel", (e) => { if (e.deltaY < 0) this.stick = false; }, { passive: true });
    scroller.addEventListener("touchmove", () => { this.stick = false; }, { passive: true });
  }

  mount(thread) {
    const switching = this.thread && this.thread.id !== thread.id;
    this.thread = thread;
    this.openTools.clear();
    this.stick = true;
    this.renderAll();
    requestAnimationFrame(() => this.scrollToEnd(true));
    if (switching && !document.body.classList.contains("no-anim") && this.root.animate) {
      this.root.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }], { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }

  renderAll(quiet = false) {
    const t = this.thread;
    const seen = new Set(this.nodes.keys());
    this.nodes.clear();
    this.root.replaceChildren();
    if (!t) return;
    for (const m of t.messages) {
      // Only messages that weren't on screen before get the entrance animation.
      const n = this.renderMessage(m, quiet && seen.has(m.id));
      if (n) {
        this.nodes.set(m.id, n);
        this.root.append(n);
      }
    }
    this.permBox = el("div.perms");
    this.statusBox = el("div.thread-status");
    this.root.append(this.permBox, this.statusBox);
    this.renderPermissions();
    this.renderStatus();
  }

  // Coalesce bursts of streaming events into at most one DOM update per frame. Deltas only
  // patch the live part of a message; everything else re-renders that message once.
  update(result) {
    if (!result || !this.thread) return;
    if (result.all) this.needAll = true;
    if (result.msg) (result.stream ? this.streaming : this.pending).add(result.msg);
    if (result.perm) this.renderPermissions();
    if (result.status) this.renderStatus();
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      if (this.needAll) {
        this.needAll = false;
        this.pending.clear();
        this.streaming.clear();
        this.renderAll(true);
      } else {
        for (const id of this.streaming) if (!this.pending.has(id) && !this.patchLive(id)) this.pending.add(id);
        for (const id of this.pending) this.rerender(id);
        this.pending.clear();
        this.streaming.clear();
      }
      this.follow();
    });
  }

  rerender(id) {
    const m = this.thread.byId.get(id);
    const old = this.nodes.get(id);
    const fresh = m && this.renderMessage(m, true);
    if (fresh && old) old.replaceWith(fresh);
    else if (fresh) this.permBox.before(fresh);
    else if (old) old.remove();
    if (fresh) this.nodes.set(id, fresh);
    else this.nodes.delete(id);
  }

  /** Update the streaming parts of a message in place. False when a full re-render is needed. */
  patchLive(id) {
    const m = this.thread.byId.get(id);
    const node = this.nodes.get(id);
    if (!m || !node) return false;
    for (const p of m.content) {
      if (p.type === "tool") {
        if (p.state?.status !== "streaming") continue;
        const pre = node.querySelector(`.tool[data-tool="${p.id}"] .tool-pre`);
        if (!pre) return false;
        pre.textContent = p.state.input;
      } else if (p.live) {
        const target = node.querySelector(`[data-part="${p.type}:${p.ordinal}"]`);
        if (!target) return false;
        if (p.type === "reasoning") target.textContent = p.text || "…";
        else {
          target.innerHTML = markdown(p.text);
          (target.lastElementChild || target).classList.add("caret");
        }
      }
    }
    return true;
  }

  follow() {
    if (this.stick) this.scrollToEnd();
  }

  // Eased follow: closes the gap a little each frame, so growing content glides instead of jumping.
  scrollToEnd(instant) {
    const s = this.scroller;
    const set = (top) => { this.autoScrolling = true; s.scrollTop = top; requestAnimationFrame(() => (this.autoScrolling = false)); };
    if (instant) return set(s.scrollHeight);
    if (this.following) return;
    this.following = true;
    const step = () => {
      const gap = s.scrollHeight - s.clientHeight - s.scrollTop;
      if (!this.stick || Math.abs(gap) < 1) { this.following = false; if (this.stick) set(s.scrollHeight); return; }
      set(s.scrollTop + gap * 0.22);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  renderMessage(m, quiet) {
    const settings = this.opts.settings();
    const anim = quiet ? { style: { animation: "none" } } : {};
    switch (m.type) {
      case "user": {
        const files = (m.files || []).map((f) => el("span.file-chip", ico("file"), el("span", f.name || basename(f.uri))));
        const actions = this.opts.onRevert && !m.pending && !this.thread.busy ? el("div.msg-actions.user-actions",
          el("button.icon-btn", { title: "Undo to here — rewind the thread and the files to just before this message", html: icon("refresh"), on: { click: () => this.opts.onRevert(m.id) } }),
          el("button.icon-btn", { title: "Copy", html: icon("copy"), on: { click: async () => { await copyText(m.text || ""); toast("Copied", "ok", 1200); } } })) : null;
        return el("div.msg.user", anim, el("div.bubble", { style: m.pending ? { opacity: 0.7 } : null }, m.text || "", files.length ? el("div.att", files) : null), actions);
      }
      case "assistant":
        return this.renderAssistant(m, settings, anim);
      case "compaction":
        return el("div.sys-note", anim, "Earlier context was compacted");
      case "model-switched":
        return el("div.sys-note", anim, `Switched model to ${this.opts.modelName(m.model) || m.model?.id || "another model"}`);
      case "agent-switched":
        return el("div.sys-note", anim, `Switched agent to ${m.agent || "another agent"}`);
      case "shell":
        return el("div.msg.assistant", anim, renderTool({ id: m.id, name: "shell", state: { status: "completed", input: { command: m.command || m.text || "" }, content: m.output ? [{ type: "text", text: m.output }] : [] } }, this.openTools));
      case "idle": {
        // History: a failed run. Skip when the live status card already shows the same error.
        const isLast = this.thread.messages[this.thread.messages.length - 1] === m;
        if (m.outcome !== "failed" || !m.error || (isLast && this.thread.error)) return null;
        return errorCard(m.error, { model: this.opts.modelName(this.thread.session.model) });
      }
      default:
        return null;
    }
  }

  // One user prompt can produce several assistant steps; draw them as a single turn.
  neighbors(m) {
    const VISIBLE = new Set(["user", "assistant", "compaction", "model-switched", "agent-switched", "shell"]);
    const list = this.thread.messages.filter((x) => VISIBLE.has(x.type));
    const i = list.indexOf(m);
    return { prev: list[i - 1], next: list[i + 1], list, i };
  }

  turnText(m) {
    const { list, i } = this.neighbors(m);
    let start = i;
    while (start > 0 && list[start - 1].type === "assistant") start--;
    return list.slice(start, i + 1).flatMap((x) => x.content.filter((p) => p.type === "text").map((p) => p.text)).join("\n\n");
  }

  renderAssistant(m, settings, anim) {
    const { prev, next } = this.neighbors(m);
    const cont = prev?.type === "assistant";
    const last = next?.type !== "assistant";
    const parts = [];
    const lastText = [...m.content].reverse().find((p) => p.type === "text");
    for (const p of m.content) {
      if (p.type === "reasoning") {
        if (!settings.ui.showReasoning || (!p.text && !p.live)) continue;
        const key = m.id + ":" + p.ordinal;
        const secs = p.time?.completed && p.time?.created ? (p.time.completed - p.time.created) / 1000 : p.ended && p.started ? (p.ended - p.started) / 1000 : null;
        const label = p.live ? "Thinking" : secs ? `Thought for ${secs < 10 ? secs.toFixed(1) : Math.round(secs)}s` : "Thoughts";
        const box = el(`div.think${p.live ? ".live" : ""}${this.openThinks.has(key) ? ".open" : ""}`);
        box.append(
          el("button.think-head", { type: "button", on: { click: () => { box.classList.toggle("open"); this.openThinks[box.classList.contains("open") ? "add" : "delete"](key); } } },
            el("span.chev", { html: icon("chev") }), el("span.think-label", label)),
          el("div.think-body", el("div", el("div.think-text", { dataset: { part: `reasoning:${p.ordinal}` } }, p.text || "…"))));
        parts.push(box);
      } else if (p.type === "text") {
        if (!p.text && !p.live) continue;
        const md = el("div.md", { html: markdown(p.text), dataset: { part: `text:${p.ordinal}` } });
        if (p.live && p === lastText) md.lastElementChild ? md.lastElementChild.classList.add("caret") : md.classList.add("caret");
        parts.push(md);
      } else if (p.type === "tool") {
        parts.push(renderTool(p, this.openTools, this.thread));
      }
    }
    const stopped = m.stopped || isStop(m.error);
    const last2 = this.thread.messages[this.thread.messages.length - 1] === m;
    if (m.error && !stopped && !(last2 && this.thread.error)) parts.push(errorCard(m.error, { model: this.opts.modelName(m.model) }));
    if (stopped) parts.push(el("div.sys-note", "Stopped"));
    if (!parts.length && !m.live) return null;
    if (!parts.length) parts.push(el("div.think.live", el("span.think-head", el("span.think-label", "Working"))));

    const tokens = m.tokens ? fmtTokens((m.tokens.input || 0) + (m.tokens.output || 0) + (m.tokens.reasoning || 0)) + " tokens" : null;
    const when = m.time?.created ? new Date(m.time.created).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
    const meta = el("div.msg-meta",
      el("span.model", this.opts.modelName(m.model) || m.model?.id || "Assistant"),
      m.agent ? [el("span.dot"), el("span", m.agent)] : null,
      tokens ? [el("span.dot"), el("span", tokens)] : null,
      when ? [el("span.dot"), el("span", when)] : null);
    const text = last && !m.live ? this.turnText(m) : "";
    const actions = m.live || !last || this.thread.busy ? null : el("div.msg-actions",
      text ? el("button.icon-btn", { title: "Copy", html: icon("copy"), on: { click: async () => { await copyText(text); toast("Copied", "ok", 1400); } } }) : null,
      el("button.icon-btn", { title: "Fork thread from here", html: icon("branch"), on: { click: () => this.opts.onFork(m.id) } }));
    const avatar = el("div.avatar", this.opts.avatar ? this.opts.avatar(m.live) : null);
    return el(`div.msg.assistant${m.live ? ".live" : ""}${cont ? ".cont" : ""}`, anim, avatar, cont ? null : meta, el("div.msg-body", parts), actions);
  }

  renderPermissions() {
    if (!this.permBox || !this.thread) return;
    this.permBox.replaceChildren();
    for (const p of this.thread.permissions.values()) this.permBox.append(this.renderPermission(p));
    if (this.thread.permissions.size) this.scrollToEnd();
  }

  renderPermission(p) {
    return permissionCard(p, this.thread.id, (id) => { this.thread.permissions.delete(id); this.renderPermissions(); });
  }

  renderStatus() {
    if (!this.statusBox || !this.thread) return;
    const t = this.thread;
    this.statusBox.replaceChildren();
    if (t.retry) {
      const err = t.retry.error || {};
      this.statusBox.append(el("div.sys-note", { title: err.message || "" }, `Provider error — retrying${t.retry.attempt ? ` (attempt ${t.retry.attempt})` : ""}${err.message ? `: ${String(err.message).slice(0, 90)}` : ""}…`));
    }
    if (t.error) this.statusBox.append(errorCard(t.error, { model: this.opts.modelName(t.session.model), onRetry: () => this.opts.onRetry(), onChangeModel: this.opts.onChangeModel }));
    this.opts.onStatus?.(t);
  }
}

/** A readable error card: what went wrong, with which model, why it probably happened, and the raw details. */
export function errorCard(err, { model, onRetry, onChangeModel } = {}) {
  const e = typeof err === "string" ? { message: err } : err || {};
  const msg = String(e.message || e.type || "Something went wrong");
  const text = `${e.type || ""} ${msg} ${e.status || ""}`;
  let title = e.type && !/error$/i.test(e.type) ? e.type : "The run failed";
  let hint = "";
  if (/ConnectionRefused|ECONNREFUSED|ENOTFOUND|fetch failed|unable to connect|network/i.test(text)) {
    title = "Couldn't reach the provider";
    hint = "The model's endpoint didn't answer. If it's a local server (Ollama, LM Studio, a bridge), make sure it's running; otherwise check the provider's base URL in Settings → Models & providers.";
  } else if (/\b401\b|unauthori[sz]ed|invalid api key|authentication/i.test(text)) {
    title = "The provider rejected the credentials";
    hint = "The API key or sign-in for this provider isn't accepted. Reconnect it in Settings → Models & providers.";
  } else if (/\b429\b|rate ?limit|too many requests/i.test(text)) {
    title = "Rate limited";
    hint = "The provider is throttling requests. Wait a moment and retry, or switch to another model.";
  } else if (/\b402\b|quota|billing|insufficient|credit|subscription plan/i.test(text)) {
    title = "Plan or credit limit";
    hint = "Your plan doesn't allow this model or has run out of credits. Pick another model or top up with the provider.";
  } else if (/timeout|timed out|\b504\b/i.test(text)) {
    title = "The provider timed out";
    hint = "The model took too long to answer. Retry, or try a faster model for this step.";
  } else if (/context|too long|maximum.*tokens|\b413\b/i.test(text)) {
    title = "The conversation is too long for this model";
    hint = "Use Context to trim or delete messages, start a fresh thread, or pick a model with a bigger context window.";
  } else if (/\b5\d\d\b|internal server|overloaded|unavailable/i.test(text)) {
    title = "The provider had a problem";
    hint = "That's on their side. Retry in a bit or switch models.";
  }
  const details = e.response ? (typeof e.response === "string" ? e.response : JSON.stringify(e.response, null, 2)) : "";
  return el("div.err",
    el("div.err-head", ico("alert"), el("div", { style: { minWidth: 0 } },
      el("div.err-title", title),
      el("div.err-msg", msg),
      hint ? el("div.err-hint", hint) : null,
      el("div.err-chips", model ? el("span.pill-tag", model) : null, e.status ? el("span.pill-tag", `HTTP ${e.status}`) : null, e.type && e.type !== title ? el("span.pill-tag", e.type) : null),
      details ? el("details", el("summary", "Raw response"), el("pre", details.slice(0, 4000))) : null,
      onRetry || onChangeModel ? el("div.err-actions",
        onRetry ? el("button.btn.sm", { on: { click: onRetry } }, ico("refresh"), "Retry") : null,
        onChangeModel ? el("button.btn.ghost.sm", { on: { click: onChangeModel } }, ico("cpu"), "Change model") : null) : null)));
}

/** An approval request for session `sid`; `onDone(id)` runs after the reply is accepted. */
export function permissionCard(p, sid, onDone) {
  const action = p.action || "tool";
  const title = action === "edit" ? "Allow file changes?" : action === "shell" ? "Run this command?" : `Allow ${action}?`;
  const files = p.metadata?.files || [];
  const cmd = p.metadata?.command;
  const reply = async (decision, btn) => {
    const box = btn.closest(".approval");
    box.querySelectorAll("button").forEach((b) => (b.disabled = true));
    const message = decision === "reject" ? box.querySelector("input")?.value || undefined : undefined;
    try {
      await api.post(`/api/sessions/${sid}/permissions/${p.id}`, { decision, message });
      onDone?.(p.id);
    } catch (e) {
      toast(e.message, "err");
      box.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  };
  const feedback = el("input.inp", { placeholder: "Tell the agent what to do instead (optional)", style: { flex: "1 1 220px", height: "28px", fontSize: "12.5px" } });
  return el("div.approval",
    el("div.approval-head", ico(action === "shell" ? "terminal" : "shield"), el("div", title, p.message ? el("div.approval-sub", p.message) : null)),
    cmd ? el("pre.tool-pre", { style: { borderTop: "1px solid var(--border)", paddingTop: "10px" } }, cmd) : null,
    !files.length && (p.resources || []).length ? el("div.approval-res", p.resources.join("\n")) : null,
    files.map((f) => el("div", el("div.tool-section-label", { style: { paddingBottom: "6px" } }, `${f.status || "change"} · ${f.file}`), diffView(f.patch))),
    el("div.approval-actions",
      el("button.btn.primary.sm", { on: { click: (e) => reply("once", e.currentTarget) } }, ico("check"), "Approve"),
      el("button.btn.sm", { title: "Don't ask again for this in this thread", on: { click: (e) => reply("always", e.currentTarget) } }, "Always allow"),
      el("span.spacer"),
      feedback,
      el("button.btn.danger.sm", { on: { click: (e) => reply("reject", e.currentTarget) } }, "Reject")));
}

/** Every file edit made in a thread, for the Changes drawer when the project isn't a git repo. */
export function collectEdits(t) {
  const files = new Map();
  for (const m of t.messages) {
    if (m.type !== "assistant") continue;
    for (const p of m.content) {
      if (p.type !== "tool" || p.state?.status !== "completed" || !describeTool(p).edit) continue;
      for (const x of toolPatches(p)) {
        const key = x.file || "file";
        const entry = files.get(key) || { file: key, patches: [], status: x.status || "modified" };
        entry.patches.push(x.patch);
        files.set(key, entry);
      }
    }
  }
  return [...files.values()].map((f) => {
    const patch = f.patches.join("\n");
    const [additions, deletions] = countPatch(patch);
    return { file: f.file, patch, additions, deletions, status: f.status };
  });
}
