// Thread model + rendering. History (message.list) and live events share one shape,
// so a single renderer draws both.

import { api } from "./api.js";
import { designCard, renderDesignTool } from "./design.js";
import { el, ico, icon, markdown, diffView, patchFromStrings, copyText, fmtDur, fmtTokens, basename, toast, progressRing } from "./ui.js";
import { fileIcon } from "./fileicons.js";
import { effortLabel } from "./model-picker.js";

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
  const [messages, perms, fresh] = await Promise.all([
    api.get(`/api/sessions/${t.id}/messages`),
    api.get(`/api/sessions/${t.id}/permissions`).catch(() => []),
    api.get(`/api/sessions/${t.id}`).catch(() => null),
  ]);
  if (fresh) t.session = { ...t.session, ...fresh };
  t.messages = [];
  t.byId.clear();
  for (const m of messages) addMessage(t, m);
  t.permissions = new Map(perms.map((p) => [p.id, p]));
  const last = [...t.messages].reverse().find((m) => m.type === "assistant" || m.type === "idle");
  // The server knows whether a run is going; an unfinished last message alone may be a run cut off by a restart.
  t.busy = typeof t.session?.running === "boolean" ? t.session.running : !!(last && last.type === "assistant" && !last.time?.completed && !last.finish);
  if (!t.busy) { t.runStart = null; t.phase = null; }
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

/** Apply one engine event. Returns {msg} for a message re-render, {all} for a full one, or {perm}. */
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
      t.phase = "delivered";
      return { status: true };
    }
    case "session.execution.started":
      t.busy = true;
      t.error = null;
      t.runStart = t.runStart || Date.now();
      if (t.phase !== "working") t.phase = "delivered";
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
    case "session.retry.scheduled": {
      t.retryError = d.error || t.retryError;
      if (!d.assistantMessageID) { // an older engine: only the status line can show it
        t.retry = d;
        return { status: true };
      }
      // The note belongs to the reply being retried, so it stays put while the run goes on.
      const m = assistant(t, d.assistantMessageID);
      m.retries = [...(m.retries || []).filter((x) => x.attempt !== d.attempt), { attempt: d.attempt, error: d.error, time: ev.created || Date.now() }];
      m.retrying = true;
      m.content = [];
      return { msg: m.id };
    }
    case "session.step.started": {
      const m = assistant(t, d.assistantMessageID, d);
      m.startedAt = d.started || Date.now();
      t.phase = "working"; // the model has the request and is producing the reply
      return { all: true, status: true };
    }
    case "session.served": {
      const m = assistant(t, d.assistantMessageID);
      m.served = { slug: d.slug, experience: d.experience };
      return { msg: m.id };
    }
    case "session.step.failed": {
      const m = assistant(t, d.assistantMessageID);
      m.retrying = false;
      if (isStop(d.error)) m.stopped = true;
      else m.error = d.error?.message;
      return { msg: m.id };
    }
    case "session.step.ended": {
      const m = assistant(t, d.assistantMessageID);
      m.retrying = false;
      m.tokens = d.tokens;
      if (d.cost != null) m.cost = d.cost;
      m.finish = d.finish;
      m.endedAt = Date.now();
      m.durationMs = m.endedAt - (m.startedAt || m.time?.created || m.endedAt);
      // Exact rate: the provider's output token count over the time we were actually receiving it.
      if (m.firstDelta) {
        const secs = (m.endedAt - m.firstDelta) / 1000;
        const out = (d.tokens?.output || 0) + (d.tokens?.reasoning || 0);
        if (secs > 0.1 && out > 0) { m.tps = out / secs; t.tps = m.tps; }
      }
      t.liveTps = 0;
      return { msg: m.id, status: true };
    }
    case "session.reasoning.started":
    case "session.text.started": {
      const m = assistant(t, d.assistantMessageID);
      m.retrying = false;
      part(m, ev.type.includes("reasoning") ? "reasoning" : "text", d.ordinal);
      return { msg: m.id };
    }
    case "session.reasoning.delta":
    case "session.text.delta": {
      const m = assistant(t, d.assistantMessageID);
      part(m, ev.type.includes("reasoning") ? "reasoning" : "text", d.ordinal).text += d.delta || "";
      const now = Date.now();
      m.firstDelta = m.firstDelta || now;
      m.liveChars = (m.liveChars || 0) + (d.delta || "").length;
      const secs = (now - m.firstDelta) / 1000;
      if (secs > 0.5) t.liveTps = m.liveChars / 4 / secs; // rough estimate until the step reports real counts
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
      m.retrying = false;
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
      if (d.cost != null) t.session.cost = d.cost;
      return { status: true };
    case "session.notice": {
      // The engine sent the agent back to work (goal autopilot, a stop hook, open to-dos), or stopped it.
      const m = d.message || { id: ev.id, type: "synthetic", text: "", metadata: { notice: d.kind, label: d.label } };
      m.time = m.time || { created: ev.created || Date.now() };
      addMessage(t, m);
      return { all: true };
    }
    case "session.compaction.started":
      t.compacting = { done: 0, total: 0, messages: d.messages };
      return { status: true };
    case "session.compaction.progress":
      t.compacting = { ...(t.compacting || {}), done: d.done, total: d.total };
      return { status: true };
    case "permission.asked":
      t.permissions.set(d.id, d);
      return { perm: true };
    case "permission.replied":
      t.permissions.delete(d.id || d.permissionID || d.requestID);
      return { perm: true };
    case "session.compaction.ended":
      t.compacting = false;
      return { status: true, reload: !d.skipped };
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
  const last = [...t.messages].reverse().find((m) => m.type === "assistant");
  if (last && t.runStart) last.turnMs = Date.now() - t.runStart;
  t.runStart = null;
  t.liveTps = 0;
}

/** Duration and tokens/s of a finished message, from live timing or the stored timestamps. */
function stepStats(m) {
  const out = (m.tokens?.output || 0) + (m.tokens?.reasoning || 0);
  const dur = m.durationMs ?? (m.time?.completed && m.time?.created ? m.time.completed - m.time.created : null);
  let tps = m.tps;
  if (!tps && m.time?.completed && m.time?.streamed && out) {
    const secs = (m.time.completed - m.time.streamed) / 1000;
    if (secs > 0.1) tps = out / secs;
  }
  return { dur, tps };
}

export const fmtCost = (usd) => (!usd ? "$0" : usd >= 100 ? `$${usd.toFixed(0)}` : usd >= 1 ? `$${usd.toFixed(2)}` : usd >= 0.01 ? `$${usd.toFixed(3)}` : `$${usd.toFixed(4)}`);

// ---- tools ----------------------------------------------------------------------

const pick = (o, ...keys) => {
  for (const k of keys) if (o && o[k] != null && o[k] !== "") return o[k];
  return null;
};

const HARNESS_VERBS = {
  list: ["Checked what's installed", "Checking what's installed"], install_skill: ["Installed skill", "Installing skill"], remove_skill: ["Removed skill", "Removing skill"],
  add_mcp: ["Added MCP server", "Adding MCP server"], remove_mcp: ["Removed MCP server", "Removing MCP server"], add_command: ["Added command", "Adding command"],
  remove_command: ["Removed command", "Removing command"], add_hook: ["Added hook", "Adding hook"], remove_hook: ["Removed hook", "Removing hook"],
  add_agent: ["Added agent", "Adding agent"], remove_agent: ["Removed agent", "Removing agent"],
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
  if (name === "browser") return { icon: "eye", label: "Browser", target: pick(input, "url", "target", "key", "script", "direction") || "" };
  if (name === "chrome") return { icon: "globe", label: "Your browser", target: pick(input, "url", "tab", "target", "key", "script", "direction") || "" };
  if (/web|fetch|browse/.test(name)) return { icon: "globe", label: name === "websearch" ? "Search web" : "Fetch", target: pick(input, "url", "query") || "" };
  if (/task|agent/.test(name)) return { icon: "bot", label: "Subagent", target: pick(input, "description", "prompt") || "" };
  if (name === "question") return { icon: "info", label: "Asked", target: pick((input.questions || [])[0] || {}, "question") || "" };
  if (name === "design") return { icon: "sparkle", label: "Design", target: input.title || "" };
  if (/todo/.test(name)) return { icon: "list", label: "Plan", target: "" };
  if (name === "memory") return { icon: "book", label: "Memory", target: pick(input, "text", "old") || "" };
  if (name === "harness") return { icon: "plug", label: (HARNESS_VERBS[input.action] || ["Harness"])[0], target: pick(input, "source", "name", "id", "url") || "" };
  if (name === "computer") return { icon: input.action === "teach" ? "book" : "mouse-pointer", label: "Computer",
    target: pick(input, "intent", "title", "app", "key", "text", "direction") || (input.action === "batch" ? `${(input.actions || []).length} steps` : "") || (Array.isArray(input.apps) ? input.apps.join(", ") : "") };
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

// Activity timeline: each tool call is a step on a rail — verb, target, outcome — expandable.
const VERBS = {
  write: ["Wrote", "Writing"], edit: ["Edited", "Editing"], multiedit: ["Edited", "Editing"], patch: ["Patched", "Patching"], apply_patch: ["Patched", "Patching"],
  shell: ["Ran", "Running"], bash: ["Ran", "Running"], execute: ["Ran code", "Running code"], read: ["Read", "Reading"], glob: ["Found files", "Finding files"],
  grep: ["Searched", "Searching"], list: ["Listed", "Listing"], ls: ["Listed", "Listing"], webfetch: ["Fetched", "Fetching"], websearch: ["Searched the web", "Searching the web"],
  skill: ["Loaded skill", "Loading skill"], question: ["Asked", "Asking"], design: ["Showed design options", "Preparing design options"], todowrite: ["Planned", "Planning"], todoread: ["Checked plan", "Checking plan"],
  memory: ["Updated project memory", "Updating project memory"],
};
const MEMORY_VERBS = { add: ["Remembered", "Remembering"], remove: ["Forgot", "Forgetting"], replace: ["Corrected memory", "Correcting memory"], list: ["Checked memory", "Checking memory"] };
const kindOf = (name) => (/^(write|edit|multiedit|patch|apply_patch)$/.test(name) ? "edit" : /^(shell|bash|execute)$/.test(name) ? "run" : /^(read|glob|grep|list|ls)$/.test(name) ? "read" : /web|fetch/.test(name) ? "web" : "other");


/** What a group of steps did, in short phrases, and a few icons for the files and kinds of work. */
function stepSummary(tools) {
  const edits = new Set(), reads = new Set();
  let runs = 0, searches = 0, web = 0, other = 0;
  const icons = [];
  const add = (k, node) => { if (icons.length < 4 && !icons.some((x) => x.k === k)) icons.push({ k, node }); };
  for (const p of tools) {
    const name = (p.name || "").toLowerCase();
    if (/^(todo|todowrite|goal|question)$/.test(name)) continue; // planning and asking, not work on files
    const kind = kindOf(name);
    const t = describeTool(p).target || "";
    if (kind === "edit") {
      const ps = toolPatches(p);
      for (const x of ps) if (x.file && x.file !== "patch") edits.add(x.file);
      if (!ps.length && t) edits.add(t);
      add("f:" + (ps[0]?.file || t), fileIcon(ps[0]?.file || t));
    } else if (kind === "read") {
      if (/^(glob|grep|list|ls)$/.test(name)) { searches++; add("search", ico("search")); }
      else { reads.add(t); add("f:" + t, fileIcon(t)); }
    } else if (kind === "run") { runs++; add("run", ico("terminal")); }
    else if (kind === "web") { web++; add("web", ico("globe")); }
    else { other++; add("o:" + name, ico(describeTool(p).icon || "zap")); }
  }
  const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  const bits = [
    edits.size ? `Edited ${n(edits.size, "file", "files")}` : null,
    runs ? `Ran ${n(runs, "command", "commands")}` : null,
    reads.size ? `Read ${n(reads.size, "file", "files")}` : null,
    searches ? `Searched ${n(searches, "time", "times")}` : null,
    web ? `Browsed ${n(web, "page", "pages")}` : null,
    other ? `${n(other, "other step", "other steps")}` : null,
  ].filter(Boolean).slice(0, 3);
  return { bits, icons: icons.map((x) => el("span.si", x.node)) };
}

function pathNode(target) {
  const i = Math.max(target.lastIndexOf("/"), target.lastIndexOf("\\"));
  if (i < 0) return el("span.tool-target.path", { title: target }, el("span.name", target));
  const dir = target.slice(0, i + 1).split(/[\\/]/).filter(Boolean).slice(-2).join("/");
  return el("span.tool-target.path", { title: target }, el("span.dir", dir ? dir + "/" : ""), el("span.name", target.slice(i + 1)));
}

const TODO_MARK = { completed: "check", cancelled: "x", in_progress: "zap", pending: null };

/** The agent's `todo` call: the list as it stands after the call, not raw JSON. */
function renderTodoTool(p, openSet, t0) {
  const status = p.state?.status || "streaming";
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const todos = p.state?.metadata?.todos || (Array.isArray(input.todos) && !input.merge ? input.todos : []);
  const done = todos.filter((x) => x.status === "completed").length;
  const of = todos.filter((x) => x.status !== "cancelled").length;
  const read = p.state?.metadata?.read;
  const live = status === "streaming" || status === "running";
  const card = el(`div.tool.plan.${status}${openSet.has(p.id) || (!openSet.has("x" + p.id) && todos.length <= 8) ? ".open" : ""}`, { dataset: { tool: p.id } });
  const head = el("button.tool-head", { type: "button", on: { click: () => { const o = card.classList.toggle("open"); openSet[o ? "add" : "delete"](p.id); openSet[o ? "delete" : "add"]("x" + p.id); } } },
    t0 && p.time?.created ? el("span.tool-time", { "aria-hidden": "true" }, stepClock(p.time.created - t0)) : null,
    el("span.tool-ico", live ? el("span.spinner") : status === "error" ? ico("alert") : todos.length ? progressRing(done, of, 18) : ico("checklist")),
    el("span.tool-name", live ? "Planning" : read ? "Checked the to-do list" : "Updated the to-do list"),
    el("span.tool-target", ""),
    todos.length ? el("span.tool-stat", `${done}/${of} done`) : null,
    el("span.tool-chev", { html: icon("chev-down") }));
  const list = el("div.plan-list", todos.map((x) => el(`div.plan-item.${x.status || "pending"}`, el("span.plan-mark", TODO_MARK[x.status] ? ico(TODO_MARK[x.status]) : null), el("span", x.status === "in_progress" && x.activeForm ? x.activeForm : x.content))));
  const err = p.state?.error ? el("pre.tool-pre.tool-error", p.state.error.message || "") : null;
  card.append(head, el("div.tool-body", el("div", todos.length ? list : null, err)));
  return card;
}

/** The agent's `goal` report: achieved / blocked get a card of their own. */
function renderGoalTool(p, openSet) {
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const status = p.state?.status || "streaming";
  if (input.status === "set" && status !== "error" && input.text) {
    return el("div.goal-note.set", { dataset: { tool: p.id } }, ico("target"), el("span", el("b", "Goal set: "), input.text, input.criteria ? el("span.goal-note-sub", ` — done when ${input.criteria}`) : null));
  }
  if (status === "error" || !["achieved", "blocked", "progress"].includes(input.status)) return null;
  if (input.status === "progress") {
    return el("div.goal-note", { dataset: { tool: p.id } }, ico("target"), el("span", el("b", "Milestone: "), input.summary || ""));
  }
  const ok = input.status === "achieved";
  return el(`div.goal-card.${ok ? "achieved" : "blocked"}`, { dataset: { tool: p.id } },
    el("div.goal-card-head", el("span.goal-card-ico", ico(ok ? "check" : "alert")), el("b", ok ? "Goal achieved" : "Goal blocked — needs you")),
    input.summary ? el("div.goal-card-text", input.summary) : null,
    input.evidence ? el("details", el("summary", "How it was verified"), el("pre.tool-pre", input.evidence)) : null);
}

/** A finished `question` call: the questions with the answer the user chose. */
function renderQuestionTool(p) {
  const meta = p.state?.metadata || {};
  const input = typeof p.state?.input === "object" ? p.state.input : {};
  const questions = meta.questions || input.questions;
  const status = p.state?.status || "streaming";
  if (!Array.isArray(questions) || status === "streaming" || status === "running") return null;  // still open: the card below the thread handles it
  const answers = meta.answers;
  const dismissed = meta.dismissed || !answers;
  return el(`div.q-recap${dismissed ? ".skipped" : ""}`, { dataset: { tool: p.id } },
    el("div.q-recap-head", ico("info"), el("b", dismissed ? "Asked — skipped" : questions.length > 1 ? `Asked ${questions.length} questions` : "Asked a question")),
    el("div.q-recap-list", questions.map((q, i) => {
      const a = answers?.[i] || {};
      const said = [...(a.selected || []), a.other ? `"${a.other}"` : null].filter(Boolean).join(", ");
      return el("div.q-recap-row", el("span.q-recap-q", q.question), el("span.q-recap-a", said || (dismissed ? "skipped" : "—")));
    })));
}

const LIVE_LINES = 14; // lines of a running command's output shown under its card

/**
 * Streaming text, block by block: blocks that are already on screen keep their nodes (so a block
 * fades in once, when it starts, instead of flickering on every delta), the growing last block is
 * updated in place and carries the caret, and only brand-new blocks arrive with the entrance.
 */
function patchBlocks(target, html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const fresh = [...tpl.content.children];
  if (!fresh.length || tpl.content.childNodes.length !== fresh.length) { // bare text, or text mixed with elements: no block structure to keep
    target.innerHTML = html;
    (target.lastElementChild || target).classList.add("caret");
    return;
  }
  target.classList.remove("caret");
  const olds = [...target.children];
  fresh.forEach((n, i) => {
    const o = olds[i];
    const lastOne = i === fresh.length - 1;
    if (o && o.tagName === n.tagName) {
      if (o.innerHTML !== n.innerHTML) o.innerHTML = n.innerHTML;
      o.classList.toggle("caret", lastOne);
    } else {
      n.classList.add("blk-in");
      if (lastOne) n.classList.add("caret");
      if (o) o.replaceWith(n); else target.append(n);
    }
  });
  while (target.children.length > fresh.length) target.lastElementChild.remove();
}

/** The last lines of a running command's output, or "" when the tool isn't streaming any. */
function liveTail(p) {
  const out = p.state?.metadata?.live ? toolText(p.state.content) : "";
  return out ? out.replace(/\s+$/, "").split("\n").slice(-LIVE_LINES).join("\n") : "";
}

/** m:ss since the turn started, for the activity margin (Paper). */
function stepClock(ms) {
  if (!(ms >= 0)) return "";
  const s = Math.round(ms / 1000);
  return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function renderTool(p, openSet, thread, t0) {
  const name = (p.name || "tool").toLowerCase();
  if (name === "subagent" && hooks.delegation) return hooks.delegation(p, { thread, open: openSet });
  if (name === "todo") return renderTodoTool(p, openSet, t0);
  if (name === "goal") { const g = renderGoalTool(p, openSet); if (g) return g; }
  if (name === "question") { const q = renderQuestionTool(p); if (q) return q; }
  if (name === "design") { const d = renderDesignTool(p); if (d) return d; }
  const info = describeTool(p);
  const status = p.state?.status || "streaming";
  const live = status === "streaming" || status === "running";
  const kind = kindOf(name);
  const input0 = typeof p.state?.input === "object" ? p.state.input : {};
  const BROWSER = { open: ["Opened in browser", "Opening in browser"], screenshot: ["Took a screenshot", "Taking a screenshot"], text: ["Read the page", "Reading the page"],
    click: ["Clicked", "Clicking"], type: ["Typed into", "Typing into"], press: ["Pressed", "Pressing"], scroll: ["Scrolled", "Scrolling"],
    double_click: ["Double-clicked", "Double-clicking"], hover: ["Pointed at", "Pointing at"], drag: ["Dragged", "Dragging"],
    back: ["Went back", "Going back"], forward: ["Went forward", "Going forward"], reload: ["Reloaded", "Reloading"],
    evaluate: ["Ran JavaScript", "Running JavaScript"], console: ["Read the console", "Reading the console"], close: ["Closed the browser tab", "Closing the browser tab"],
    network: ["Checked the network", "Checking the network"], sources: ["Read the page's files", "Reading the page's files"] };
  const CHROME = { ...BROWSER, open: ["Opened in your browser", "Opening in your browser"], tabs: ["Listed your tabs", "Listing your tabs"],
    switch_tab: ["Switched to your tab", "Switching to your tab"], close: ["Left the tab", "Leaving the tab"] };
  const COMPUTER = { screenshot: ["Looked at the screen", "Looking at the screen"], zoom: ["Looked closer", "Looking closer"], apps: ["Listed apps", "Listing apps"],
    request_access: ["Asked to use apps", "Asking to use apps"], launch: ["Opened an app", "Opening an app"], focus: ["Switched app", "Switching app"],
    switch_display: ["Switched display", "Switching display"], cursor_position: ["Found the pointer", "Finding the pointer"], move: ["Moved the pointer", "Moving the pointer"],
    click: ["Clicked", "Clicking"], double_click: ["Double-clicked", "Double-clicking"], triple_click: ["Triple-clicked", "Triple-clicking"],
    right_click: ["Right-clicked", "Right-clicking"], middle_click: ["Middle-clicked", "Middle-clicking"], mouse_down: ["Pressed the mouse", "Pressing the mouse"],
    mouse_up: ["Released the mouse", "Releasing the mouse"], drag: ["Dragged", "Dragging"], scroll: ["Scrolled", "Scrolling"], type: ["Typed", "Typing"],
    key: ["Pressed keys", "Pressing keys"], hold_key: ["Held a key", "Holding a key"], wait: ["Waited", "Waiting"], read_clipboard: ["Read the clipboard", "Reading the clipboard"],
    set_clipboard: ["Set the clipboard", "Setting the clipboard"], batch: ["Did several steps", "Doing several steps"], teach: ["Showed you a step", "Showing you a step"] };
  const verbs = name === "computer" ? COMPUTER[input0.action] || ["Used the computer", "Using the computer"]
    : name === "browser" ? BROWSER[input0.action] || ["Used the browser", "Using the browser"]
    : name === "chrome" ? CHROME[input0.action] || ["Used your browser", "Using your browser"]
    : name === "shell" && input0.background ? ["Started in background", "Starting in background"]
    : name === "jobs" ? ({ stop: ["Stopped job", "Stopping job"], list: ["Listed jobs", "Listing jobs"] }[input0.action] || ["Read job output", "Waiting for job output"])
      : name === "harness" ? HARNESS_VERBS[input0.action] || ["Changed AFH setup", "Changing AFH setup"]
      : name === "memory" ? MEMORY_VERBS[input0.action] || VERBS.memory
      : VERBS[name] || [p.name, p.name];
  const patches = info.edit ? toolPatches(p) : [];
  const meta = p.state?.metadata || {};
  let stat = null;
  if (patches.length) {
    const [a, r] = patches.reduce((acc, x) => { const [aa, rr] = x.additions != null ? [x.additions, x.deletions] : countPatch(x.patch); return [acc[0] + aa, acc[1] + rr]; }, [0, 0]);
    stat = el("span.tool-stat", el("span.plus", `+${a}`), el("span.minus", `−${r}`));
  } else if (meta.blockedBy) stat = el("span.tool-stat", { style: { color: "var(--warn)" } }, "blocked by hook");
  else if (status === "error") stat = el("span.tool-stat", { style: { color: "var(--bad)" } }, "failed");
  else if (status === "streaming") stat = el("span.tool-stat", "preparing");
  else if (status === "running") stat = el("span.tool-stat", name === "jobs" && input0.wait ? `waiting up to ${input0.wait}s` : "running");
  else if (meta.job) stat = el("span.tool-stat", el("span.job-id", meta.job.id), meta.job.running ? " running" : meta.job.stopped ? " stopped" : ` exited ${meta.job.exitCode ?? ""}`);
  const diag = meta.diagnostics;
  const diagChip = diag ? el(`span.diag-chip.${diag.ok ? "ok" : "bad"}`, { title: `Checked with ${diag.ran.join(", ")}` }, ico(diag.ok ? "shield-check" : "alert"), diag.ok ? "checked" : `${diag.problems} problem${diag.problems === 1 ? "" : "s"}`) : null;
  const hookRuns = meta.hooks || [];
  const hookChip = hookRuns.length && !meta.blockedBy ? el(`span.diag-chip.hook${hookRuns.some((h) => h.code !== 0) ? ".bad" : ""}`, { title: hookRuns.map((h) => `${h.event} · ${h.name}: exit ${h.code}`).join("\n") }, ico("hook"), `${hookRuns.length} hook${hookRuns.length > 1 ? "s" : ""}`) : null;
  const target = name === "jobs" ? input0.id || "" : info.target || "";
  const targetNode = kind === "edit" || kind === "read" ? pathNode(target) : el("span.tool-target", { title: target }, target);

  // The card style: icon tile, verb, target, outcome — expandable.
  const card = el(`div.tool.${kind}.${status}${openSet.has(p.id) ? ".open" : ""}`, { dataset: { tool: p.id } });
  // Header: icon tile · verb · target chip · (status, checks, hooks) at the right · chevron.
  const head = el("button.tool-head", { type: "button", on: { click: () => { card.classList.toggle("open"); openSet[card.classList.contains("open") ? "add" : "delete"](p.id); } } },
    t0 && p.time?.created ? el("span.tool-time", { "aria-hidden": "true" }, stepClock(p.time.created - t0)) : null,
    el(`span.tool-ico${(kind === "edit" || kind === "read") && target && name !== "glob" && name !== "grep" ? ".is-file" : ""}`,
      live && !((kind === "edit" || kind === "read") && target) ? el("span.spinner")
        : status === "error" ? ico("alert")
          : (kind === "edit" || kind === "read") && target && name !== "glob" && name !== "grep" ? fileIcon(target)
            : ico(name === "jobs" ? "activity" : info.icon)),
    el("span.tool-name", live ? verbs[1] : verbs[0]),
    targetNode,
    el("span.tool-right", stat, diagChip, hookChip, el("span.tool-chev", { html: icon("chev-down") })));
  const sections = [];
  const out = toolText(p.state?.content);
  const errText = p.state?.error ? p.state.error.message || JSON.stringify(p.state.error) : "";
  if (kind === "run" && name !== "jobs" && !patches.length) {
    // A command opens as a small terminal: the command, then its output, with how it ended.
    const input = p.state?.input;
    const cmd = typeof input === "string" ? input : pick(input || {}, "command", "cmd") || "";
    const code = meta.exit_code;
    const bad = status === "error" || (code != null && code !== 0) || meta.timed_out;
    const state = live ? el("span.term-state.run", "running")
      : el(`span.term-state.${bad ? "bad" : "ok"}`, ico(bad ? "alert" : "check"), meta.timed_out ? "timed out" : code != null ? `exit ${code}` : bad ? "failed" : "done");
    sections.push(el("div.term",
      el("div.term-head", ico("terminal"), el("span.term-title", { title: meta.description || "" }, meta.description || "Terminal"), el("span.term-grow"),
        meta.duration_ms != null && !live ? el("span.term-dur", fmtDur(meta.duration_ms)) : null, state,
        el("span.term-copy", { role: "button", tabIndex: 0, title: "Copy the command", html: icon("copy"), on: { click: async (e) => { e.stopPropagation(); await copyText(cmd); toast("Copied", "ok", 1200); } } })),
      el("pre.tool-pre.term-cmd", cmd),
      out ? el("pre.term-out", out.length > 20000 ? out.slice(0, 20000) + "\n…" : out) : !live && !errText ? el("div.term-empty", "No output") : null,
      errText ? el("pre.tool-pre.tool-error.term-err", errText) : null));
  } else {
    if (patches.length) for (const x of patches) sections.push(el("div.tool-section", patches.length > 1 ? el("div.tool-section-label", fileIcon(x.file || ""), basename(x.file)) : null, diffView(x.patch)));
    else {
      const input = p.state?.input;
      const inputText = typeof input === "string" ? input : input && Object.keys(input).length ? (kind === "run" ? pick(input, "command", "cmd") : JSON.stringify(input, null, 2)) : "";
      if (inputText) sections.push(el("div.tool-section", el("div.tool-section-label", kind === "run" ? "Command" : "Input"), el("pre.tool-pre", inputText)));
    }
    if (out) sections.push(el("div.tool-section", el("div.tool-section-label", "Output"), el("pre.tool-pre", out.length > 20000 ? out.slice(0, 20000) + "\n…" : out)));
    if (errText) sections.push(el("div.tool-section", el("pre.tool-pre.tool-error", errText)));
  }
  // Browser screenshots stay visible under the card's header; click one to see it full size.
  const shots = (p.state?.content || []).filter((c) => c.type === "image" && c.uri);
  const gallery = shots.length ? el("div.tool-shots", { dataset: { n: String(shots.length) } }, shots.map((c) => el("img.tool-shot", { src: c.uri, alt: "Browser screenshot", loading: "lazy", on: { click: () => viewImage(c.uri) } }))) : null;
  // A running command shows its latest output under the header as it arrives, no click needed.
  const tail = live ? liveTail(p) : "";
  const liveOut = tail ? el("div.tool-live", el("pre.tool-live-pre", tail)) : null;
  // Native .append stringifies null ("null" text node), so leave the gallery out when there is none.
  card.append(head, ...(liveOut ? [liveOut] : []), ...(gallery ? [gallery] : []), el("div.tool-body", el("div", sections)));
  return card;
}

// ---- view -----------------------------------------------------------------------

const WINDOW = 150; // messages drawn at once; "Show earlier" adds more
const toolIds = (root) => new Set([...root.querySelectorAll("[data-tool]")].map((n) => n.dataset.tool));

/** Cards that were already on screen keep still when their message re-renders (no replayed fade-in). */
function stillAnimations(node, seen) {
  if (!seen.size) return;
  for (const n of node.querySelectorAll("[data-tool]")) if (seen.has(n.dataset.tool)) n.style.animation = "none";
}

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
    if (switching || !this.thread) this.window = WINDOW;
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
    const seenTools = quiet ? toolIds(this.root) : new Set();
    this.nodes.clear();
    this.root.replaceChildren();
    if (!t) return;
    // Very long threads (imports run to thousands of messages) draw only the newest part.
    const start = Math.max(0, t.messages.length - (this.window || WINDOW));
    this.hidden = new Set(t.messages.slice(0, start).map((m) => m.id));
    if (start > 0) {
      this.root.append(el("div.show-earlier", el("button.btn.ghost.sm", { on: { click: () => {
        const before = this.scroller.scrollHeight, top = this.scroller.scrollTop;
        this.window = (this.window || WINDOW) + WINDOW;
        this.stick = false;
        this.renderAll(true);
        this.scroller.scrollTop = top + (this.scroller.scrollHeight - before);
      } } }, ico("arrow-down"), `Show earlier messages (${start})`)));
    }
    for (const m of t.messages.slice(start)) {
      // Only messages that weren't on screen before get the entrance animation.
      const n = this.renderMessage(m, quiet && seen.has(m.id));
      if (n) {
        stillAnimations(n, seenTools);
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
        // Studio: a reply's bar (on its first message) sums up the whole reply, and the message before a new
        // one turns from answer into work, so both redraw too; then the reply's fold is applied everywhere.
        const turns = new Set();
        if (this.opts.rich?.()) {
          for (const id of [...this.pending]) {
            const m = this.thread.byId.get(id);
            if (m?.type !== "assistant") continue;
            const T = this.turnOf(m);
            const k = T.msgs.indexOf(m);
            if (T.msgs[0] && T.msgs[0] !== m) this.pending.add(T.msgs[0].id);
            if (k > 0) this.pending.add(T.msgs[k - 1].id);
            turns.add(m);
          }
        }
        for (const id of this.pending) this.rerender(id);
        for (const m of turns) { const T = this.turnOf(m); this.applyTurn(T.id, T.collapsed, T.live); }
        this.pending.clear();
        this.streaming.clear();
      }
      this.follow();
    });
  }

  rerender(id) {
    const m = this.thread.byId.get(id);
    const old = this.nodes.get(id);
    if (!old && this.hidden?.has(id)) return; // not drawn: older than the window
    const fresh = m && this.renderMessage(m, true);
    if (fresh && old) {
      stillAnimations(fresh, toolIds(old));
      old.replaceWith(fresh);
    }
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
        if (p.state?.status === "running" && p.state.metadata?.live) {
          const pre = node.querySelector(`[data-tool="${p.id}"] .tool-live-pre`);
          if (!pre) return false; // the first output: draw the card with its live box
          const tail = liveTail(p);
          if (pre.textContent !== tail) pre.textContent = tail;
          continue;
        }
        if (p.state?.status !== "streaming") continue;
        const pre = node.querySelector(`[data-tool="${p.id}"] .tool-pre`);
        if (!pre) return false;
        pre.textContent = p.state.input;
      } else if (p.live) {
        const target = node.querySelector(`[data-part="${p.type}:${p.ordinal}"]`);
        if (!target) return false;
        if (p.type === "reasoning") target.textContent = p.text || "…";
        else patchBlocks(target, markdown(p.text));
      }
    }
    return true;
  }

  follow() {
    if (this.stick) this.scrollToEnd();
  }

  /** Once a second while busy: advance the visible timers without re-rendering anything else. */
  tick() {
    const now = Date.now();
    for (const n of this.root.querySelectorAll(".pending-row .timer, .live-dur")) n.textContent = fmtDur(now - Number(n.dataset.start || now));
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
        const files = (m.files || []).map((f) => String(f.uri || "").startsWith("data:image/")
          ? el("img.msg-img", { src: f.uri, alt: f.name || "", title: f.name || "", on: { click: () => viewImage(f.uri) } })
          : el("span.file-chip", fileIcon(f.name || f.uri || ""), el("span", f.name || basename(f.uri))));
        const actions = this.opts.onRevert && !m.pending && !this.thread.busy ? el("div.msg-actions.user-actions",
          el("button.icon-btn", { title: "Undo to here — rewind the thread and the files to just before this message", html: icon("refresh"), on: { click: () => this.opts.onRevert(m.id) } }),
          el("button.icon-btn", { title: "Copy", html: icon("copy"), on: { click: async () => { await copyText(m.text || ""); toast("Copied", "ok", 1200); } } })) : null;
        const cmd = m.command;
        const content = !cmd ? [m.text || ""]
          : cmd.name === "goal" ? [el("span.cmd-chip.goal", ico("target"), "Goal"), " ", cmd.args]
            : [el("span.cmd-chip", `/${cmd.name}`), cmd.args ? ` ${cmd.args}` : "", el("details.cmd-full", el("summary", "prompt"), el("div", m.text || ""))];
        return el("div.msg.user", anim, el("div.bubble", { style: m.pending ? { opacity: 0.7 } : null }, content, files.length ? el("div.att", files) : null), actions);
      }
      case "synthetic": {
        const n = m.metadata?.notice;
        if (!n) return null;
        const icons = { goal: "target", hook: "hook", todo: "checklist", limit: "alert", resume: "refresh", chrome: "globe", account: "user" };
        const label = m.metadata?.label || (n === "goal" ? "Goal not achieved yet — continuing" : n === "hook" ? "A stop hook failed — continuing" : n === "todo" ? "To-do items still open — checking" : "Notice");
        return el(`div.notice.${n}`, anim, ico(icons[n] || "info"), el("span", label), m.text ? el("details", el("summary", "what the agent was told"), el("pre", m.text)) : null);
      }
      case "assistant":
        return this.renderAssistant(m, settings, anim);
      case "compaction": {
        // Like Thinking: a quiet line you can open to read exactly what the model now has instead of the old messages.
        const key = "compaction:" + m.id;
        const n = m.metadata?.compacted;
        const box = el(`div.think.compact-box${this.openThinks.has(key) ? ".open" : ""}`, anim);
        box.append(
          el("button.think-head", { type: "button", on: { click: () => { box.classList.toggle("open"); this.openThinks[box.classList.contains("open") ? "add" : "delete"](key); } } },
            el("span.chev", { html: icon("chev") }), el("span.compact-ico", { html: icon("archive") }),
            el("span.think-label", n ? `Compacted ${n} earlier message${n === 1 ? "" : "s"} — summary` : "Earlier context was compacted — summary")),
          el("div.think-body", el("div", m.text ? el("div.compact-text.md", { html: markdown(m.text) }) : el("div.compact-text", "No summary was kept for this compaction."))));
        return box;
      }
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
    const { prev, next, list, i } = this.neighbors(m);
    const cont = prev?.type === "assistant";
    let j = i;
    while (j > 0 && list[j - 1].type !== "user") j--;
    const t0 = list[j - 1]?.time?.created || m.time?.created || 0; // when this turn began
    const last = next?.type !== "assistant";
    const rich = !!this.opts.rich?.(); // Studio: a reply's work folds under one bar, a logo on each reply, files changed at the end
    const parts = [];
    const kinds = []; // what each part is: think, text, tool, note
    const add = (node, kind) => { parts.push(node); kinds.push(kind); };
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
            el("span.chev", { html: icon("chev") }), el("span.think-ico", ico("sparkle")), el("span.think-label", label)),
          el("div.think-body", el("div", el("div.think-text", { dataset: { part: `reasoning:${p.ordinal}` } }, p.text || "…"))));
        add(box, "think");
      } else if (p.type === "text") {
        if (!p.text && !p.live) continue;
        const md = el("div.md", { html: markdown(p.text), dataset: { part: `text:${p.ordinal}` } });
        if (p.live && p === lastText) md.lastElementChild ? md.lastElementChild.classList.add("caret") : md.classList.add("caret");
        add(md, "text");
      } else if (p.type === "tool") {
        add(renderTool(p, this.openTools, this.thread, t0), "tool");
      }
    }
    const stopped = m.stopped || isStop(m.error);
    const last2 = this.thread.messages[this.thread.messages.length - 1] === m;
    if (m.error && !stopped && !(last2 && this.thread.error)) add(errorCard(m.error, { model: this.opts.modelName(m.model) }), "note");
    if (stopped) add(el("div.sys-note", "Stopped"), "note");
    if (!parts.length && !m.live && !m.retries?.length) return null;
    if (!parts.length && (m.live || m.retrying)) add(el("div.think.live", el("span.think-head", el("span.think-label", m.retrying ? "Waiting to retry" : "Working"))), "think");
    if (m.retries?.length) { parts.unshift(retryNote(m)); kinds.unshift("note"); }

    // Output already includes reasoning; input is the uncached part, so add what the cache served.
    const tokens = m.tokens ? fmtTokens((m.tokens.input || 0) + (m.tokens.cache?.read || 0) + (m.tokens.cache?.write || 0) + (m.tokens.output || 0)) + " tokens" : null;
    const cost = m.cost != null && m.cost > 0 ? fmtCost(m.cost) : null;
    const when = m.time?.created ? new Date(m.time.created).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
    const { dur, tps } = stepStats(m);
    const turnDone = last && m.turnMs ? m.turnMs : null;
    const meta = el("div.msg-meta",
      rich && m.model ? el("span.model", this.opts.modelMark ? this.opts.modelMark(m.model) : null, this.opts.modelName({ ...m.model, variant: undefined }) || m.model.id,
        m.model.variant && m.model.variant !== "default" ? el("span.eff-badge", effortLabel(m.model.variant)) : null)
        : el("span.model", this.opts.modelName(m.model) || m.model?.id || "Assistant"),
      m.served?.slug ? (m.served.slug === m.model?.id
        ? el("span.served-tag.ok", { title: `Confirmed by ChatGPT: this reply came from the real model ${m.served.slug}${m.served.experience ? ` (${m.served.experience})` : ""}` }, ico("check"), "real model")
        : el("span.served-tag.warn", { title: `ChatGPT served ${m.served.slug} instead of ${m.model?.id} (a fallback)` }, `served as ${m.served.slug}`)) : null,
      m.agent ? [el("span.dot"), el("span", m.agent)] : null,
      tokens ? [el("span.dot"), el("span", { title: m.tokens.cache?.read ? `${fmtTokens(m.tokens.cache.read)} read from the prompt cache` : null }, tokens)] : null,
      cost ? [el("span.dot"), el("span", { title: "cost of this step" }, cost)] : null,
      when ? [el("span.dot"), el("span", when)] : null,
      m.live ? [el("span.dot"), el("span.dur.live-dur", { dataset: { start: String(m.startedAt || m.time?.created || Date.now()) } }, fmtDur(Date.now() - (m.startedAt || m.time?.created || Date.now())))]
        : dur != null ? [el("span.dot"), el("span.dur", { title: turnDone ? `this step ${fmtDur(dur)} · whole reply ${fmtDur(turnDone)}` : "completed in" }, `completed in ${fmtDur(turnDone || dur)}`)] : null,
      tps ? [el("span.dot"), el("span.dur", { title: "output tokens per second (provider count ÷ streaming time)" }, `${Math.round(tps)} tok/s`)] : null);
    const text = last && !m.live ? this.turnText(m) : "";
    const actions = m.live || !last || this.thread.busy ? null : el("div.msg-actions",
      text ? el("button.icon-btn", { title: "Copy", html: icon("copy"), on: { click: async () => { await copyText(text); toast("Copied", "ok", 1400); } } }) : null,
      el("button.icon-btn", { title: "Fork thread from here", html: icon("branch"), on: { click: () => this.opts.onFork(m.id) } }));
    const avatar = el("div.avatar", this.opts.avatar ? this.opts.avatar(m.live) : null);
    const files = rich && last && !m.live ? this.turnFiles(list.slice(j, i + 1)) : null;
    // Studio: everything the model did on the way (its notes, thinking and steps) sits in one work column
    // under a "Worked for …" bar; the answer at the end of the reply stays outside it.
    let body = el("div.msg-body", parts);
    const T = rich ? this.turnOf(m) : null;
    if (T && T.tools.length) {
      let from = parts.length;
      if (last && !m.live) while (from > 0 && (kinds[from - 1] === "text" || kinds[from - 1] === "note")) from--;
      const work = parts.slice(0, from);
      body = el("div.msg-body",
        cont ? null : this.turnBar(T),
        work.length ? el(`div.work${T.collapsed ? ".shut" : ""}${T.live ? ".live" : ""}`, { dataset: { turn: T.id } }, el("div.work-in", work)) : null,
        ...parts.slice(from));
    }
    return el(`div.msg.assistant${m.live ? ".live" : ""}${cont ? ".cont" : ""}${T && T.tools.length ? ".has-work" : ""}`, anim, avatar, cont ? null : meta, body, files, actions);
  }

  /** The reply `m` belongs to: its messages, its steps, whether it is still running and folded. */
  turnOf(m) {
    const msgs = this.thread.messages;
    const i = msgs.indexOf(m);
    let a = i, b = i;
    while (a > 0 && msgs[a - 1].type !== "user") a--;
    while (b < msgs.length - 1 && msgs[b + 1].type !== "user") b++;
    const turn = msgs.slice(a, b + 1).filter((x) => x.type === "assistant");
    const tools = turn.flatMap((x) => x.content.filter((p) => p.type === "tool"));
    const id = turn[0]?.id || m.id;
    const live = turn.some((x) => x.live) || (!!this.thread.busy && b === msgs.length - 1);
    const collapsed = this.openTools.has("tc:" + id) ? true : this.openTools.has("t:" + id) ? false : !live && tools.length >= 3;
    return { id, msgs: turn, tools, live, collapsed };
  }

  /** "Worked for 1m 12s · Edited 3 files · Ran 2 commands": click to fold or unfold the work. */
  turnBar(T) {
    const sum = stepSummary(T.tools);
    const first = T.msgs[0], end = T.msgs[T.msgs.length - 1];
    // How long the reply took: the live run's own clock, else first start to last finish, else the steps added up.
    const finish = Math.max(0, ...T.msgs.map((x) => x.time?.completed || (x.time?.created && x.durationMs ? x.time.created + x.durationMs : 0)));
    const ms = end?.turnMs || (finish && first?.time?.created ? finish - first.time.created : 0) || T.msgs.reduce((n, x) => n + (stepStats(x).dur || 0), 0);
    const start = first?.time?.created || Date.now();
    const bar = el(`button.turn-bar${T.collapsed ? ".shut" : ""}${T.live ? ".live" : ""}`, { type: "button", dataset: { turn: T.id }, "aria-expanded": String(!T.collapsed), on: { click: () => {
      const shut = !bar.classList.contains("shut");
      this.openTools.delete(shut ? "t:" + T.id : "tc:" + T.id);
      this.openTools.add(shut ? "tc:" + T.id : "t:" + T.id);
      this.applyTurn(T.id, shut);
    } } },
      el("span.tb-chev", { html: icon("chev") }),
      T.live ? el("span.tb-what", el("span.tb-pulse"), "Working", el("span.dur.live-dur", { dataset: { start: String(start) } }, fmtDur(Date.now() - start)))
        : el("span.tb-what", ms > 0 ? `Worked for ${fmtDur(ms)}` : "Worked"),
      el("span.tb-bits", sum.bits.map((b) => el("span.steps-bit", b))),
      el("span.steps-icons", sum.icons),
      el("span.steps-n", `${T.tools.length} ${T.tools.length === 1 ? "step" : "steps"}`));
    return bar;
  }

  applyTurn(id, shut, live) {
    for (const n of this.root.querySelectorAll(`[data-turn="${id}"]`)) {
      n.classList.toggle("shut", shut);
      if (live != null) n.classList.toggle("live", live);
      if (n.classList.contains("turn-bar")) n.setAttribute("aria-expanded", String(!shut));
    }
  }

  /** The files a whole reply changed, as a card at its end. */
  turnFiles(msgs) {
    const files = new Map();
    for (const x of msgs) {
      if (x.type !== "assistant") continue;
      for (const p of x.content) {
        if (p.type !== "tool" || p.state?.status !== "completed") continue;
        for (const pt of toolPatches(p)) {
          if (!pt.file || pt.file === "patch") continue;
          const [a, r] = pt.additions != null ? [pt.additions, pt.deletions || 0] : countPatch(pt.patch);
          const o = files.get(pt.file) || { a: 0, r: 0 };
          files.set(pt.file, { a: o.a + a, r: o.r + r });
        }
      }
    }
    if (!files.size) return null;
    let A = 0, R = 0;
    for (const s of files.values()) { A += s.a; R += s.r; }
    const review = () => this.opts.onReview?.();
    return el("div.turn-files",
      el("div.tf-head", ico("diff"), el("b", `${files.size} ${files.size === 1 ? "file" : "files"} changed`),
        el("span.tool-stat", el("span.plus", `+${A}`), el("span.minus", `−${R}`)), el("span.tf-grow"),
        this.opts.onReview ? el("button.tf-btn", { type: "button", on: { click: review } }, "Review", el("span.tf-arrow", { html: icon("chev") })) : null),
      el("div.tf-list", [...files].map(([f, s]) => {
        const k = Math.max(f.lastIndexOf("/"), f.lastIndexOf("\\"));
        const dir = k > 0 ? f.slice(0, k).split(/[\\/]/).filter(Boolean).slice(-2).join("/") : "";
        return el("button.tf-row", { type: "button", title: f, on: { click: review } }, fileIcon(f), el("span.tf-name", f.slice(k + 1)), dir ? el("span.tf-dir", dir) : null,
          el("span.tool-stat", el("span.plus", `+${s.a}`), el("span.minus", `−${s.r}`)));
      })));
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
    // Sent but no reply yet: show the mark at work with a running timer right away. Once the
    // model's reply exists (even before its first word) it shows its own "Working" row, so this one goes.
    const streaming = t.messages.some((m) => m.type === "assistant" && m.live);
    if ((t.busy || t.runStart) && !streaming && !t.error) {
      const model = this.opts.modelName(t.session.model) || "the model";
      const label = t.phase === "working" ? `${model} is working` : t.phase === "delivered" ? `Delivered · waiting for ${model}` : "Sending your message";
      this.statusBox.append(el("div.msg.assistant.pending", { style: { animation: "none" } }, el("div.avatar", this.opts.avatar ? this.opts.avatar(true) : null),
        el("div.msg-body", el("div.pending-row", el("span.lbl", label), el("span.timer", { dataset: { start: String(t.runStart || Date.now()) } }, fmtDur(Date.now() - (t.runStart || Date.now())))))));
    }
    if (t.compacting) {
      const c = t.compacting;
      const what = c.messages ? `${c.messages} older messages` : "older messages";
      this.statusBox.append(el("div.notice.compacting", el("span.spinner"), el("span", c.total > 1 ? `Summarising ${what} in ${c.total - 1} parts… ${Math.min(c.done, c.total)}/${c.total}` : `Summarising ${what} to free up context…`),
        c.total > 1 ? el("span.compact-bar", el("i", { style: { width: `${Math.round((100 * c.done) / c.total)}%` } })) : null));
    }
    if (t.retry) {
      const err = t.retry.error || {};
      this.statusBox.append(el("div.sys-note", { title: err.message || "" }, `Provider error — retrying${t.retry.attempt ? ` (attempt ${t.retry.attempt})` : ""}${err.message ? `: ${String(err.message).slice(0, 90)}` : ""}…`));
    }
    if (t.error) this.statusBox.append(errorCard(t.error, { model: this.opts.modelName(t.session.model), onRetry: () => this.opts.onRetry(), onChangeModel: this.opts.onChangeModel }));
    this.opts.onStatus?.(t);
  }
}

/** A readable error card: what went wrong, with which model, why it probably happened, and the raw details. */
/** "Provider error — retrying…" at the top of the reply it happened in; it stays there afterwards. */
function retryNote(m) {
  const r = m.retries[m.retries.length - 1];
  const message = r.error?.message ? String(r.error.message) : "";
  const why = message ? `: ${message.slice(0, 90)}${message.length > 90 ? "…" : ""}` : "";
  const n = m.retries.length;
  const text = m.retrying ? `Provider error — retrying (attempt ${r.attempt + 1})${why}`
    : m.error && !m.stopped ? `Provider error — gave up after ${n + 1} attempts${why}`
      : `Provider error — recovered after ${n} ${n === 1 ? "retry" : "retries"}${why}`;
  return el(`div.sys-note.retry-note${m.retrying ? ".live" : ""}`, { title: message }, text);
}

export function errorCard(err, { model, onRetry, onChangeModel } = {}) {
  const e = typeof err === "string" ? { message: err } : err || {};
  const msg = String(e.message || e.type || "Something went wrong");
  const text = `${e.type || ""} ${msg} ${e.status || ""}`;
  let title = e.type && !/error$/i.test(e.type) ? e.type : "The run failed";
  let hint = "";
  if (/ConnectionRefused|ECONNREFUSED|ENOTFOUND|fetch failed|unable to connect|network/i.test(text)) {
    title = "Couldn't reach the provider";
    hint = "The model's endpoint didn't answer. If it's a local server (Ollama, LM Studio, a bridge), make sure it's running; otherwise check the provider's base URL in Settings → Models & accounts.";
  } else if (/\b401\b|unauthori[sz]ed|invalid api key|authentication/i.test(text)) {
    title = "The provider rejected the credentials";
    hint = "The API key or sign-in for this provider isn't accepted. Reconnect it in Settings → Models & accounts.";
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
  if (p.action === "question" && Array.isArray(p.metadata?.questions)) return questionCard(p, sid, onDone);
  if (p.action === "design" && p.metadata?.design) return designCard(p, sid, onDone);
  if (p.action === "computer" && p.metadata?.kind === "computer") return computerCard(p, sid, onDone);
  if (p.action === "chrome" && p.metadata?.kind === "chrome") return chromeSiteCard(p, sid, onDone);
  const action = p.action || "tool";
  const title = p.metadata?.title || (action === "edit" ? "Allow file changes?" : action === "shell" ? "Run this command?" : `Allow ${action}?`);
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

/** The agent wants to use desktop apps with the mouse and keyboard; the user allows them (once/always) or not. */
export function computerCard(p, sid, onDone) {
  const apps = p.metadata?.apps?.length ? p.metadata.apps : [p.metadata?.app || {}];
  const TIER = { full: "Full control", click: "Click only", read: "View only" };
  const reply = async (decision, btn) => {
    const box = btn.closest(".approval");
    box.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      await api.post(`/api/sessions/${sid}/permissions/${p.id}`, { decision });
      onDone?.(p.id);
    } catch (e) {
      toast(e.message, "err");
      box.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  };
  const icon = (a) => {
    const box = el("span.comp-ico", (a.name || "?").trim()[0] || "?");
    if (/\.exe$/i.test(a.path || "")) {
      const img = new Image();
      img.onload = () => box.replaceChildren(img);
      img.src = api.url("/api/computer/icon", { path: a.path, size: 64 });
    }
    return box;
  };
  const many = apps.length > 1;
  return el("div.approval.computer-approval",
    el("div.approval-head", el("span.comp-badge", ico("mouse-pointer")),
      el("div", el("div", p.metadata?.title || `Let AFH use ${apps[0].name || "this app"}?`),
        el("div.approval-sub", p.metadata?.reason || `AFH will take over the mouse and keyboard in ${many ? "these apps" : "it"} while it works. Press Esc any time to stop.`))),
    el("div.comp-list", apps.map((a) => el("div.comp-app", icon(a), el("span.comp-name", a.name || a.id || "App"),
      el("span.comp-tier" + (a.tier === "full" || !a.tier ? ".full" : ""), TIER[a.tier] || "Full control")))),
    el("div.approval-actions",
      el("button.btn.primary.sm", { on: { click: (e) => reply("once", e.currentTarget) } }, ico("check"), "Allow"),
      el("button.btn.sm", { title: many ? "Don't ask again for these apps" : "Don't ask again for this app", on: { click: (e) => reply("always", e.currentTarget) } }, "Always allow"),
      el("span.spacer"),
      el("button.btn.danger.sm", { on: { click: (e) => reply("reject", e.currentTarget) } }, "Don't allow")));
}

/** The agent wants to use a site in the user's own browser, signed in as them; they allow it (once/always) or not. */
export function chromeSiteCard(p, sid, onDone) {
  const m = p.metadata || {};
  const reply = async (decision, btn) => {
    const box = btn.closest(".approval");
    box.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      await api.post(`/api/sessions/${sid}/permissions/${p.id}`, { decision });
      onDone?.(p.id);
    } catch (e) {
      toast(e.message, "err");
      box.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  };
  return el("div.approval.computer-approval",
    el("div.approval-head", el("span.comp-badge", ico("globe")),
      el("div", el("div", m.title || `Let AFH use ${m.site || "this site"} in your browser?`),
        el("div.approval-sub", m.note || "AFH will see this site the way you do, signed in as you, and can click and type there."))),
    el("div.comp-list", el("div.comp-app", el("span.comp-ico", (m.site || "?")[0].toUpperCase()), el("span.comp-name", m.site || ""),
      el("span.comp-tier.full", `Your ${m.browser || "browser"}`))),
    el("div.approval-actions",
      el("button.btn.primary.sm", { on: { click: (e) => reply("once", e.currentTarget) } }, ico("check"), "Allow"),
      el("button.btn.sm", { title: "Don't ask again for this site", on: { click: (e) => reply("always", e.currentTarget) } }, "Always allow"),
      el("span.spacer"),
      el("button.btn.danger.sm", { on: { click: (e) => reply("reject", e.currentTarget) } }, "Don't allow")));
}

/** The agent paused to ask: one multiple-choice question at a time, with Back / Next / Submit. */
export function questionCard(p, sid, onDone) {
  const questions = p.metadata.questions;
  const answers = questions.map(() => ({ selected: [], other: "" }));
  let at = 0;
  const card = el("div.approval.qcard");
  const send = async (decision, payload) => {
    card.querySelectorAll("button, input, textarea").forEach((b) => (b.disabled = true));
    try {
      await api.post(`/api/sessions/${sid}/permissions/${p.id}`, { decision, ...payload });
      onDone?.(p.id);
    } catch (e) {
      toast(e.message, "err");
      card.querySelectorAll("button, input, textarea").forEach((b) => (b.disabled = false));
    }
  };
  const draw = () => {
    const q = questions[at];
    const a = answers[at];
    const toggle = (label) => {
      if (q.multiple) a.selected = a.selected.includes(label) ? a.selected.filter((x) => x !== label) : [...a.selected, label];
      else a.selected = a.selected.includes(label) ? [] : [label];
      draw();
    };
    const opts = el("div.q-opts", q.options.map((o) => {
      const on = a.selected.includes(o.label);
      return el(`button.q-opt${on ? ".on" : ""}`, { type: "button", on: { click: () => toggle(o.label) } },
        el("span.q-check", on ? ico("check") : null),
        el("span.q-opt-main", el("span.q-opt-label", o.label), o.description ? el("span.q-opt-desc", o.description) : null));
    }));
    const other = el("textarea.q-other", { rows: 1, placeholder: "Or type your own answer…", value: a.other,
      on: { input: (e) => { a.other = e.target.value; e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; } } });
    const last = at === questions.length - 1;
    const hasAns = a.selected.length || a.other.trim();
    card.replaceChildren(
      el("div.approval-head", ico("info"),
        el("div", el("div", "The agent has a question"), questions.length > 1 ? el("div.approval-sub", `Question ${at + 1} of ${questions.length}`) : null),
        questions.length > 1 ? el("span.q-dots", questions.map((_, i) => el(`span.q-dot${i === at ? ".on" : ""}${(answers[i].selected.length || answers[i].other.trim()) ? ".done" : ""}`))) : null),
      el("div.q-body",
        q.header ? el("div.q-header", q.header) : null,
        el("div.q-text", q.question),
        q.multiple ? el("div.q-hint", "Pick any that apply") : null,
        opts, other),
      el("div.approval-actions",
        at > 0 ? el("button.btn.sm", { type: "button", on: { click: () => { at--; draw(); } } }, "Back") : null,
        el("span.spacer"),
        el("button.btn.ghost.sm", { type: "button", title: "Skip the questions and let the agent continue", on: { click: () => send("dismiss") } }, "Skip"),
        last
          ? el("button.btn.primary.sm", { type: "button", disabled: !hasAns, on: { click: () => send("answer", { answers }) } }, ico("check"), "Submit")
          : el("button.btn.primary.sm", { type: "button", on: { click: () => { at++; draw(); } } }, "Next")));
  };
  draw();
  return card;
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

/** A full-size look at an image (browser screenshots, pasted images). */
export function viewImage(src) {
  const box = el("div.image-view", { on: { click: () => box.remove() } }, el("img", { src, alt: "" }));
  document.body.append(box);
  const onKey = (e) => { if (e.key === "Escape") { box.remove(); removeEventListener("keydown", onKey); } };
  addEventListener("keydown", onKey);
}
