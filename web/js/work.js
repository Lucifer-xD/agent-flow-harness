// A thread's working state, shown above the composer: its goal, the agent's to-do list, and the
// background jobs (servers, watchers) it started. The engine owns the state; this draws and edits it.

import { api } from "./api.js";
import { closePopover, confirmDialog, el, fmtDur, ico, icon, modal, popover, toast, toggle } from "./ui.js";

const STORE_KEY = "afh-dock";
let prefs = { todosOpen: true };
try { prefs = { ...prefs, ...JSON.parse(localStorage.getItem(STORE_KEY) || "{}") }; } catch {}
const savePrefs = () => { try { localStorage.setItem(STORE_KEY, JSON.stringify(prefs)); } catch {} };

/** Pull the goal and to-do list out of the session record (they live in metadata.afh). */
export function syncState(t) {
  const afh = t.session?.metadata?.afh || {};
  if (!t.todosFromEvents) t.todos = afh.todos || [];
  if (!t.goalFromEvents) t.goal = afh.goal || null;
  if (!t.historyFromEvents) { t.goalHistory = afh.goalHistory || []; t.todoHistory = afh.todoHistory || []; }
  t.jobs = t.jobs || [];
  return t;
}

export async function loadJobs(t) {
  try { t.jobs = await api.get(`/api/sessions/${t.id}/jobs`); } catch { t.jobs = []; }
}

/** Engine events for the working state. Returns true when the dock must redraw. */
export function applyWorkEvent(t, ev) {
  const d = ev.data || {};
  if (ev.type === "session.todos.updated") {
    const before = t.todos || [];
    t.todos = d.todos || [];
    t.todosFromEvents = true;
    if (d.history) { t.todoHistory = d.history; t.historyFromEvents = true; }
    if (allDone(t.todos) && !allDone(before)) celebrate(t, "todosShownUntil");
    t.justDone = new Set(t.todos.filter((x) => x.status === "completed" && before.find((b) => b.id === x.id && b.status !== "completed")).map((x) => x.id));
    return true;
  }
  if (ev.type === "session.goal.updated") {
    t.prevGoalStatus = t.goal?.status;
    t.goal = d.goal || null;
    t.goalFromEvents = true;
    if (d.history) { t.goalHistory = d.history; t.historyFromEvents = true; }
    if (t.goal?.status === "achieved" && t.prevGoalStatus !== "achieved") celebrate(t, "goalShownUntil");
    return true;
  }
  if (ev.type === "session.jobs.updated") {
    t.jobs = d.jobs || [];
    return true;
  }
  return false;
}

const allDone = (todos) => todos.length > 0 && todos.every((x) => x.status === "completed" || x.status === "cancelled") && todos.some((x) => x.status === "completed");
const SHOW_DONE_MS = 4500; // a finished goal or list stays a moment so you see it complete, then leaves the dock

/** Keep a just-finished goal or list on screen for a moment, then slide it out of the dock. */
function celebrate(t, key) {
  t[key] = Date.now() + SHOW_DONE_MS;
  setTimeout(() => {
    const part = document.querySelector(key === "goalShownUntil" ? ".dock-goal" : ".dock-todos");
    part?.classList.add("leaving");
    setTimeout(() => ctxRedraw?.(), 380);
  }, SHOW_DONE_MS);
}

const counts = (todos) => {
  const c = { total: todos.length, completed: 0, cancelled: 0, in_progress: 0, pending: 0 };
  for (const x of todos) c[x.status] = (c[x.status] || 0) + 1;
  c.done = c.completed;
  c.of = c.total - c.cancelled;
  return c;
};

// ---- the dock ---------------------------------------------------------------------------------

/**
 * Draw the dock for thread `t` into `box`. opts: { busy, onEditGoal(), onChanged() }.
 * Empty (hidden) when the thread has neither a goal nor a to-do list.
 */
export function renderDock(box, t, opts = {}) {
  const now = Date.now();
  // Achieved goals and finished lists leave the dock (they live on under the Goal button).
  const goal = t?.goal && (t.goal.status !== "achieved" || now < (t.goalShownUntil || 0)) ? t.goal : null;
  const todos = t?.todos && (!allDone(t.todos) || now < (t.todosShownUntil || 0) || t.showTodos) ? t.todos : [];
  const show = !!t && (goal || todos.length || t.showTodos);
  box.classList.toggle("on", !!show);
  if (!show) { box.replaceChildren(); return; }
  const card = el("div.dock-card");
  if (goal) card.append(goalRow(t, goal, opts));
  if (todos.length || t.showTodos) card.append(todoBlock(t, todos, opts));
  box.replaceChildren(card);
  t.justDone = null;
}

function goalRow(t, goal, opts) {
  const st = goal.status || "active";
  const auto = goal.autopilot && st === "active";
  const label = (st === "achieved" ? "Goal achieved" : st === "blocked" ? "Goal blocked" : st === "paused" ? "Goal paused" : "Goal") + (goal.by === "agent" ? " · set by the agent" : goal.by === "auto" ? " · from your request" : "");
  const chip = auto
    ? el("button.goal-chip.auto", { type: "button", title: "Autopilot keeps the agent working until it reports the goal achieved or blocked. Click to turn it off.", on: { click: () => patchGoal(t, { autopilot: false }, "Autopilot off") } },
      el("span.pulse-dot"), goal.exhausted ? "Autopilot paused" : `Autopilot ${goal.turns || 0}/${goal.maxTurns || 10}`)
    : st === "active" ? el("button.goal-chip", { type: "button", title: "Turn autopilot on: the agent keeps going until the goal is achieved", on: { click: () => patchGoal(t, { autopilot: true }, "Autopilot on") } }, "Autopilot off")
      : null;
  const last = (goal.progress || []).at(-1);
  const sub = st === "achieved" || st === "blocked" ? goal.summary || last?.summary : last?.status === "progress" ? last.summary : goal.criteria ? `Done when: ${goal.criteria}` : "";
  const more = el("button.icon-btn.sm", { title: "Goal actions", html: icon("more"), on: { click: (e) => goalMenu(e.currentTarget, t, goal, opts) } });
  return el(`div.dock-goal.${st}${t.prevGoalStatus && t.prevGoalStatus !== st && st === "achieved" ? ".celebrate" : ""}`,
    el("span.goal-ico", ico(st === "achieved" ? "check" : st === "blocked" ? "alert" : "target")),
    el("div.goal-main",
      el("div.goal-top", el("span.goal-label", label), chip),
      el("div.goal-text", { title: goal.text }, goal.text),
      sub ? el("div.goal-sub", { title: sub }, sub) : null),
    el("button.icon-btn.sm", { title: "Edit goal", html: icon("edit"), on: { click: () => opts.onEditGoal?.() } }),
    more);
}

function goalMenu(anchor, t, goal, opts) {
  const st = goal.status;
  const items = [];
  if (st !== "achieved") items.push({ title: "Mark achieved", icon: "check", onSelect: () => patchGoal(t, { status: "achieved" }, "Goal marked achieved") });
  if (st === "achieved" || st === "blocked" || st === "paused") items.push({ title: "Reopen goal", sub: "Back to active, fresh autopilot budget", icon: "refresh", onSelect: () => patchGoal(t, { status: "active" }, "Goal reopened") });
  if (st === "active") items.push({ title: "Pause goal", sub: "The agent stops working toward it", icon: "stop", onSelect: () => patchGoal(t, { status: "paused" }, "Goal paused") });
  items.push({ title: "Edit…", icon: "edit", onSelect: () => opts.onEditGoal?.() });
  items.push({ sep: true }, { title: "Remove goal", icon: "trash", danger: true, onSelect: async () => {
    if (!(await confirmDialog({ title: "Remove the goal?", body: "The thread keeps its messages and to-do list; the agent stops working toward the goal.", confirm: "Remove", danger: true }))) return;
    try { await api.del(`/api/sessions/${t.id}/goal`); } catch (e) { toast(e.message, "err"); }
  } });
  popover(anchor, items, { width: 250, align: "right" });
}

async function patchGoal(t, body, okMsg) {
  try {
    t.goal = await api.patch(`/api/sessions/${t.id}/goal`, body);
    if (okMsg) toast(okMsg, "ok", 1600);
  } catch (e) {
    toast(e.message, "err");
  }
}

function todoBlock(t, todos, opts) {
  const c = counts(todos);
  const current = todos.find((x) => x.status === "in_progress");
  const allDone = c.of > 0 && c.done === c.of;
  // A finished list folds away by itself; otherwise the last choice (open or folded) sticks.
  const isOpen = t.todoOpen ?? (allDone && !t.showTodos ? false : prefs.todosOpen !== false);
  const frac = c.of ? c.done / c.of : 0;
  const wrap = el(`div.dock-todos${isOpen ? ".open" : ""}`);
  const head = el("button.todo-head", { type: "button", title: isOpen ? "Collapse" : "Expand", on: { click: () => { t.todoOpen = !isOpen; if (!allDone) { prefs.todosOpen = !isOpen; savePrefs(); } opts.onChanged?.(); } } },
    el("span.chev", { html: icon("chev") }),
    el("span.todo-title", "To-do"),
    c.total ? el("span.todo-count", `${c.done}/${c.of}`) : el("span.todo-count", "empty"),
    el("span.todo-bar", el("i", { style: { width: `${Math.round(frac * 100)}%` } })),
    !isOpen && current ? el("span.todo-now", { title: current.content }, current.activeForm || current.content) : el("span.spacer"),
    c.total && c.done === c.of ? el("span.todo-alldone", ico("check"), "All done") : null);
  wrap.append(head);
  if (isOpen) {
    const list = el("div.todo-list");
    for (const x of todos) list.append(todoItem(t, x, todos));
    list.append(addRow(t, todos));
    wrap.append(list);
  }
  return wrap;
}

function todoItem(t, item, todos) {
  const st = item.status;
  const fresh = t.justDone?.has(item.id);
  const mark = el(`button.todo-mark.${st}`, { type: "button", title: st === "completed" ? "Mark not done" : "Mark done", on: { click: () => {
    const next = st === "completed" ? "pending" : "completed";
    saveTodos(t, todos.map((x) => (x.id === item.id ? { ...x, status: next } : x)));
  } } }, st === "in_progress" ? el("span.todo-spin") : st === "completed" ? ico("check") : st === "cancelled" ? ico("x") : null);
  const text = el("span.todo-text", { title: "Double-click to edit" }, st === "in_progress" && item.activeForm ? item.activeForm : item.content);
  text.addEventListener("dblclick", () => {
    const input = el("input.todo-edit", { value: item.content });
    let finished = false;
    const done = (save) => {
      if (finished) return;
      finished = true;
      const v = input.value.trim();
      if (save && v && v !== item.content) saveTodos(t, todos.map((x) => (x.id === item.id ? { ...x, content: v, activeForm: undefined } : x)));
      else input.replaceWith(text);
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    input.addEventListener("blur", () => done(true));
    text.replaceWith(input);
    input.focus();
    input.select();
  });
  const del = el("button.todo-del", { type: "button", title: "Remove", html: icon("x"), on: { click: () => saveTodos(t, todos.filter((x) => x.id !== item.id)) } });
  const run = el("button.todo-del", { type: "button", title: st === "in_progress" ? "Not in progress" : "Mark in progress", html: icon(st === "in_progress" ? "stop" : "zap"), on: { click: () => saveTodos(t, todos.map((x) => (x.id === item.id ? { ...x, status: st === "in_progress" ? "pending" : "in_progress" } : x.status === "in_progress" && st !== "in_progress" ? { ...x, status: "pending" } : x))) } });
  return el(`div.todo-item.${st}${fresh ? ".fresh" : ""}`, mark, text, el("span.todo-acts", st !== "completed" && st !== "cancelled" ? run : null, del));
}

function addRow(t, todos) {
  const input = el("input.todo-add", { placeholder: "Add a step… (Enter)", on: { keydown: (e) => {
    if (e.key !== "Enter" || !input.value.trim()) return;
    e.preventDefault();
    saveTodos(t, [...todos, { content: input.value.trim(), status: "pending" }]);
    input.value = "";
  } } });
  return el("div.todo-addrow", ico("plus"), input);
}

let saveTimer = 0;
function saveTodos(t, todos) {
  t.todos = todos;
  t.todosFromEvents = true;
  ctxRedraw?.();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      t.todos = await api.put(`/api/sessions/${t.id}/todos`, { todos: t.todos });
      ctxRedraw?.();
    } catch (e) {
      toast(e.message, "err");
    }
  }, 350);
}

let ctxRedraw = null;
export function setRedraw(fn) { ctxRedraw = fn; }

// ---- goal dialog -------------------------------------------------------------------------------

/**
 * Set or edit a goal. With a thread it saves to the engine; without one (the home screen) it hands
 * the values to onDraft so the first message creates the thread with the goal.
 * opts: { thread, draft, busy, onDraft(goal), onStart(goal) }
 */
export function openGoalDialog(opts = {}) {
  const g = opts.thread?.goal || opts.draft || {};
  const text = el("textarea.ta", { rows: 3, value: g.text || "", placeholder: "e.g. Users can sign up and log in with email; all tests pass" });
  const criteria = el("textarea.ta", { rows: 2, value: g.criteria || "", placeholder: "Optional: how to check it, e.g. `npm test` passes and the login page works in the browser" });
  let autopilot = g.autopilot !== false;
  const turns = el("input.inp", { type: "number", min: 1, max: 100, value: g.maxTurns || 10, style: { width: "90px" } });
  const err = el("div", { style: { color: "var(--bad)", fontSize: "12.5px", minHeight: "16px" } });
  const values = () => ({ text: text.value.trim(), criteria: criteria.value.trim(), autopilot, maxTurns: Math.max(1, Math.min(100, Number(turns.value) || 10)) });
  const save = async (start) => {
    const v = values();
    if (!v.text) { err.textContent = "Describe the goal first."; text.focus(); return; }
    if (!opts.thread) {
      opts.onDraft?.(v);
      m.close();
      if (start) opts.onStart?.(v);
      return;
    }
    try {
      opts.thread.goal = await api.put(`/api/sessions/${opts.thread.id}/goal`, { ...v, start: !!start });
      m.close();
      toast(start ? "Goal set — working on it" : "Goal saved", "ok");
      opts.onSaved?.(opts.thread.goal);
    } catch (e) {
      err.textContent = e.message;
    }
  };
  const body = el("div.m-body", { style: { padding: "22px 24px 24px" } },
    el("h2", el("span", { style: { display: "inline-flex", verticalAlign: "-3px", marginRight: "8px", color: "var(--accent)" } }, ico("target")), g.text ? "Edit the goal" : "Set a goal"),
    el("p.lead", "Tell the agent what done looks like. It plans the steps in its to-do list, works through them, verifies the result, and reports the goal achieved — or blocked, if it needs you."),
    el("div.field", el("label", "Goal"), text),
    el("div.field", el("label", "Done when"), criteria),
    el("div.row", { style: { padding: "10px 0" } }, el("div.rl", el("b", "Autopilot"), el("span", "Keep working until the goal is achieved, without stopping to ask")), toggle(autopilot, (v) => { autopilot = v; })),
    el("div.row", { style: { padding: "6px 0 12px" } }, el("div.rl", el("b", "Continuations"), el("span", "How many times autopilot may send it back to work per message")), turns),
    err,
    el("div.actions",
      el("button.btn.ghost", { on: { click: () => m.close() } }, "Cancel"),
      el("button.btn", { on: { click: () => save(false) } }, opts.thread ? "Save" : "Set goal"),
      opts.busy ? null : el("button.btn.primary", { on: { click: () => save(true) } }, ico("zap"), opts.thread ? "Save & start" : "Start now")));
  const m = modal(body, { small: true });
  setTimeout(() => text.focus(), 40);
  return m;
}

// ---- background jobs --------------------------------------------------------------------------

export function renderJobsChip(btn, t) {
  const jobs = t?.jobs || [];
  if (!jobs.length) { btn.hidden = true; return; }
  const running = jobs.filter((j) => j.running).length;
  btn.hidden = false;
  btn.className = `pill jobs-pill${running ? " live" : ""}`;
  btn.title = running ? `${running} background job${running > 1 ? "s" : ""} running — click to see output or stop` : "Background jobs (finished)";
  btn.replaceChildren(running ? el("span.pulse-dot") : ico("terminal"), el("span.lbl", running ? `${running} running` : `${jobs.length} job${jobs.length > 1 ? "s" : ""}`));
}

const jobState = (j) => (j.running ? `running ${fmtDur(Date.now() - j.started)}` : j.stopped ? "stopped" : `exited ${j.exitCode ?? "?"}`);

export function jobsPopover(anchor, t) {
  const jobs = t?.jobs || [];
  const box = el("div.jobs-pop");
  const draw = () => {
    box.replaceChildren(el("h4", ico("terminal"), "Background jobs"));
    if (!(t.jobs || []).length) box.append(el("div.empty-row", "No background jobs in this thread."));
    for (const j of t.jobs || []) {
      box.append(el(`div.job-row${j.running ? ".running" : ""}`,
        el("div.job-head", el(`span.status-dot.${j.running ? "active" : j.exitCode === 0 || j.stopped ? "disabled" : "error"}`), el("code.job-cmd", { title: j.command }, j.command), el("span.job-state", jobState(j))),
        j.description ? el("div.job-desc", j.description) : null,
        j.tail ? el("pre.job-tail", j.tail.split("\n").slice(-10).join("\n")) : null,
        el("div.job-acts",
          el("button.btn.ghost.sm", { on: { click: () => { closePopover(); jobOutput(j.id, t); } } }, ico("eye"), "Output"),
          j.running ? el("button.btn.sm.danger", { on: { click: async (e) => { e.currentTarget.disabled = true; try { await api.post(`/api/jobs/${j.id}/stop`); await loadJobs(t); draw(); } catch (er) { toast(er.message, "err"); } } } }, ico("stop"), "Stop")
            : el("button.btn.ghost.sm", { on: { click: async () => { await api.del(`/api/jobs/${j.id}`).catch(() => {}); await loadJobs(t); draw(); } } }, ico("x"), "Dismiss"))));
    }
  };
  draw();
  popover(anchor, [], { header: box, width: 420, align: "right" });
  loadJobs(t).then(draw);
}

export function jobOutput(jid, t) {
  const pre = el("pre.job-full", "Loading…");
  const state = el("span.job-state");
  const stop = el("button.btn.sm.danger", { on: { click: async () => { try { await api.post(`/api/jobs/${jid}/stop`); refresh(); } catch (e) { toast(e.message, "err"); } } } }, ico("stop"), "Stop");
  let stick = true;
  pre.addEventListener("scroll", () => { stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 30; });
  let timer = 0;
  const refresh = async () => {
    try {
      const j = await api.get(`/api/jobs/${jid}?tail=200000`);
      title.replaceChildren(ico("terminal"), el("code", j.command));
      state.textContent = jobState(j);
      pre.textContent = j.tail || "(no output yet)";
      stop.hidden = !j.running;
      if (stick) pre.scrollTop = pre.scrollHeight;
      if (j.running) timer = setTimeout(refresh, 1500);
    } catch (e) {
      pre.textContent = e.message;
    }
  };
  const title = el("h3.job-title");
  const m = modal(el("div.m-body", { style: { padding: "18px 20px" } }, el("div.job-modal-head", title, state, el("span.spacer"), stop), pre), { onClose: () => clearTimeout(timer) });
  m.box.classList.add("wide");
  refresh();
}

// ---- the Goal menu: the current goal, achieved goals and completed lists ----------------------

export function goalsPopover(anchor, t, { onEdit, onNew }) {
  const goal = t.goal;
  const goals = [...(t.goalHistory || [])].reverse();
  const lists = [...(t.todoHistory || [])].reverse();
  const box = el("div.goals-pop");
  const when = (ms) => (ms ? new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
  if (goal && goal.status !== "achieved") {
    box.append(el("div.gp-section", el("div.gp-title", ico("target"), "Current goal"),
      el("div.gp-goal", el("div.gp-text", goal.text), goal.criteria ? el("div.gp-sub", goal.criteria) : null),
      el("div.gp-actions", el("button.btn.sm", { on: { click: () => { closePopover(); onEdit(); } } }, ico("edit"), "Edit"))));
  } else {
    box.append(el("div.gp-section", el("div.gp-actions", el("button.btn.sm.primary", { on: { click: () => { closePopover(); onNew(); } } }, ico("target"), "Set a new goal"))));
  }
  box.append(el("div.gp-title", ico("check"), el("span", "Achieved goals"), goals.length ? el("span.gp-n", String(goals.length)) : null));
  if (!goals.length) box.append(el("div.empty-row", "No achieved goals in this thread yet."));
  for (const g of goals) {
    box.append(el("details.gp-item", el("summary", el("span.gp-check", ico("check")), el("span.gp-text", g.text), el("span.gp-when", when(g.achieved))),
      g.summary ? el("div.gp-body", g.summary) : null, g.criteria ? el("div.gp-sub", g.criteria) : null));
  }
  box.append(el("div.gp-title", ico("checklist"), el("span", "Completed lists"), lists.length ? el("span.gp-n", String(lists.length)) : null));
  if (!lists.length) box.append(el("div.empty-row", "No completed to-do lists yet."));
  for (const l of lists) {
    const done = l.todos.filter((x) => x.status === "completed").length;
    box.append(el("details.gp-item", el("summary", el("span.gp-check", ico("checklist")), el("span.gp-text", l.todos[0]?.content || "To-do list"), el("span.gp-when", `${done}/${l.todos.length} · ${when(l.completed)}`)),
      el("div.gp-body", l.todos.map((x) => el(`div.plan-item.${x.status}`, el("span.plan-mark", x.status === "completed" ? ico("check") : x.status === "cancelled" ? ico("x") : null), el("span", x.content))))));
  }
  popover(anchor, [], { header: box, width: 420, align: "right" });
}
