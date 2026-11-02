// Live file pane: while the model writes or edits a file, show it happening. The engine streams
// the tool's input as it is generated, so a write can be shown typing out and an edit can be
// shown in place — the file is loaded, the old text found, and the new text typed over it.

import { api } from "./api.js";
import { logoNode } from "./logo.js";
import { basename, el, ico, toggle } from "./ui.js";

let ctx = null;
const st = { tool: null, kind: null, raw: "", input: null, file: null, filePath: null, loading: null, done: false, error: null, follow: true, frame: 0, scrolledTo: -1, startedAt: 0, pace: null };
export const liveState = st;

export function initLive(c) {
  ctx = c;
}

const WRITE = new Set(["write"]);
const EDIT = new Set(["edit", "multiedit"]);
const names = new Map(); // tool id -> tool name, so a later event can tell a command from other tools

/** A tool call that waits on a command's output: a foreground shell command, or jobs output/wait. */
function runsCommand(name, input) {
  if (name === "shell") return !input.background;
  return name === "jobs" && (input.action || "output") === "output";
}

export function onLiveEvent(ev) {
  if (!ctx || ctx.S.settings.ui.liveFiles === false) return;
  const d = ev.data || {};
  switch (ev.type) {
    case "session.tool.input.started": {
      const n = (d.name || "").toLowerCase();
      names.set(d.id, n);
      if (names.size > 200) names.delete(names.keys().next().value);
      if (!WRITE.has(n) && !EDIT.has(n)) return;
      Object.assign(st, { tool: d.id, kind: WRITE.has(n) ? "write" : "edit", raw: "", input: null, file: null, filePath: null, loading: null, done: false, error: null, scrolledTo: -1, startedAt: Date.now() });
      startPacing();
      ctx.openLive();
      schedule();
      break;
    }
    case "session.tool.input.delta":
      if (d.id === st.tool) { st.raw += d.delta || ""; schedule(); }
      break;
    case "session.tool.input.ended":
      if (d.id === st.tool && d.text) { st.raw = d.text; schedule(); }
      break;
    case "session.tool.called":
      if (d.id === st.tool) { st.input = d.input || {}; schedule(); }
      else if (runsCommand(names.get(d.id), d.input || {}) && (st.done || !st.tool || st.kind === "run")) {
        // A command shows as a terminal while it runs, unless a file is still being written.
        const i = d.input || {};
        const command = names.get(d.id) === "shell" ? String(i.command || "") : `job ${i.id || i.job || ""}`.trim();
        Object.assign(st, { tool: d.id, kind: "run", raw: "", input: i, command, out: "", file: null, filePath: null, loading: null, done: false, error: null, scrolledTo: -1, startedAt: Date.now(), pace: null });
        schedule();
      }
      break;
    case "session.tool.progress":
      if (d.id === st.tool && st.kind === "run" && d.content?.[0]?.text != null) { st.out = d.content[0].text; schedule(); }
      break;
    case "session.tool.success":
    case "session.tool.failed":
      if (d.id === st.tool) {
        st.done = true;
        st.error = ev.type.endsWith("failed") ? d.error?.message || "failed" : null;
        schedule();
      }
      break;
  }
}

// The model's text can arrive faster than anyone can watch (a whole file in two seconds), or
// all at once when a provider doesn't stream tool arguments. Either way the pane types it out
// at a readable pace and only lags the model by a second or two: the rate rises with the backlog.
const MIN_CPS = 260; // ~a line every third of a second
const CATCH_UP_SECONDS = 2.0;

function startPacing() {
  const pace = { full: "", pos: 0, last: performance.now(), settled: false };
  st.pace = pace;
  const timer = setInterval(() => {
    if (st.pace !== pace) return clearInterval(timer); // superseded by a newer tool call
    const now = performance.now();
    const dt = (now - pace.last) / 1000;
    pace.last = now;
    const remaining = pace.full.length - pace.pos;
    if (remaining > 0) {
      const cps = Math.max(MIN_CPS, remaining / CATCH_UP_SECONDS);
      pace.pos = Math.min(pace.full.length, pace.pos + dt * cps);
      schedule();
    } else if (st.done && !pace.settled) {
      // Everything the model sent is on screen and the tool has finished: show the real file.
      pace.settled = true;
      clearInterval(timer);
      if (st.filePath) loadFile(st.filePath, true).then(schedule); else schedule();
    }
  }, 33);
}

/** The part of `value` that has been typed out so far. */
function paced(value) {
  const pace = st.pace;
  if (!pace || value == null) return value;
  if (pace.full !== value) {
    if (!value.startsWith(pace.full)) pace.pos = Math.min(pace.pos, value.length); // text was replaced, not extended
    pace.full = value;
  }
  return value.slice(0, Math.floor(pace.pos));
}

const caughtUp = () => !st.pace || st.pace.pos >= st.pace.full.length;

// A timer rather than requestAnimationFrame: rAF stops in hidden/minimized windows and a
// pending frame would block every later render.
function schedule() {
  if (st.frame) return;
  st.frame = setTimeout(() => { st.frame = 0; ctx.renderLive(); }, 33);
}

/** Read a JSON string value that may still be streaming. Returns {value, complete} or null. */
function partialString(raw, key) {
  const i = raw.indexOf(`"${key}"`);
  if (i < 0) return null;
  const colon = raw.indexOf(":", i + key.length + 2);
  if (colon < 0) return null;
  let k = raw.indexOf('"', colon + 1);
  if (k < 0) return null;
  k++;
  let out = "";
  const esc = { n: "\n", t: "\t", r: "\r", '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f" };
  while (k < raw.length) {
    const c = raw[k];
    if (c === '"') return { value: out, complete: true };
    if (c === "\\") {
      if (k + 1 >= raw.length) break;
      const n = raw[k + 1];
      if (n === "u") {
        if (k + 5 >= raw.length) break;
        out += String.fromCharCode(parseInt(raw.slice(k + 2, k + 6), 16));
        k += 6;
      } else { out += esc[n] ?? n; k += 2; }
      continue;
    }
    out += c;
    k++;
  }
  return { value: out, complete: false };
}

const pickKey = (o, ...keys) => { for (const k of keys) if (o && o[k] != null) return o[k]; return null; };

/** Tool paths are often relative to the project folder; make them absolute for the reader. */
function absolute(path) {
  if (!path) return path;
  if (/^[a-zA-Z]:[\\/]|^[\\/]/.test(path)) return path;
  const root = ctx.project() || "";
  const sep = root.includes("\\") ? "\\" : "/";
  return root ? root.replace(/[\\/]+$/, "") + sep + path.replace(/^[\\/]+/, "") : path;
}

function parse() {
  const typed = (v) => {
    if (!v) return v;
    const shown = paced(v.value);
    return { value: shown, complete: v.complete && shown.length >= v.value.length };
  };
  if (st.input) {
    const i = st.input;
    const s = (v) => (v == null ? null : { value: String(v), complete: true });
    return {
      path: pickKey(i, "path", "filePath", "file_path", "file"),
      content: st.kind === "write" ? typed(s(i.content)) : s(i.content),
      old: s(pickKey(i, "oldString", "old_string", "old")),
      new_: st.kind === "edit" ? typed(s(pickKey(i, "newString", "new_string", "new"))) : s(pickKey(i, "newString", "new_string", "new")),
    };
  }
  const raw = st.raw;
  const path = partialString(raw, "path") || partialString(raw, "filePath") || partialString(raw, "file_path");
  return {
    path: path?.complete ? path.value : null,
    content: st.kind === "write" ? typed(partialString(raw, "content")) : partialString(raw, "content"),
    old: partialString(raw, "oldString") || partialString(raw, "old_string"),
    new_: st.kind === "edit" ? typed(partialString(raw, "newString") || partialString(raw, "new_string")) : (partialString(raw, "newString") || partialString(raw, "new_string")),
  };
}

async function loadFile(path, force = false) {
  if (!force && (st.loading === path || st.filePath === path && st.file != null)) return;
  st.loading = path;
  try {
    const r = await api.get(api.q("/api/files/read", { path }));
    if (st.loading === path) { st.file = r.content ?? ""; st.filePath = path; }
  } catch {
    if (st.loading === path) { st.file = ""; st.filePath = path; }
  }
  st.loading = null;
  schedule();
}

/** Draw the pane. `body` scrolls; `titleBox` is the drawer title. */
export function renderLive(body, titleBox) {
  if (!st.tool) {
    titleBox.replaceChildren(ico("eye"), el("span", "Live"));
    body.replaceChildren(el("div.live-note", "When the model writes or edits a file, or runs a command, it appears here as it happens."));
    return;
  }
  if (st.kind === "run") return renderRun(body, titleBox);
  const p = parse();
  if (p.path) p.path = absolute(p.path);
  if (p.path && st.filePath !== p.path && !st.loading) loadFile(p.path);
  const name = basename(p.path || "");
  const finished = st.done && caughtUp() && (st.pace?.settled ?? true);
  const verb = st.kind === "write" ? (finished ? "Wrote" : "Writing") : finished ? "Edited" : "Editing";
  titleBox.replaceChildren(logoNode({ size: 26, working: !finished }), el("span", `${verb} ${name || "…"}`),
    finished ? el("span.pill-tag", st.error ? "failed" : "done") : el("span.pill-tag.accent", "live"));

  let lines = [], marks = new Map(), focus = -1, caret = -1, note = null;
  if (st.kind === "write") {
    const text = finished && st.file != null ? st.file : p.content?.value ?? "";
    lines = text.split("\n");
    if (!finished) { caret = lines.length - 1; }
    for (let i = 0; i < lines.length; i++) marks.set(i, "new");
    if (!p.content && !finished) note = "Preparing the file…";
  } else {
    const file = st.file ?? "";
    const oldS = p.old, newS = p.new_;
    if (st.file == null) note = p.path ? "Loading the file…" : "Waiting for the file path…";
    else if (!oldS) { lines = file.split("\n"); note = "Waiting for the text to replace…"; }
    else {
      const idx = file.indexOf(oldS.value);
      if (idx < 0) {
        lines = file.split("\n");
        note = oldS.complete ? "The text to replace isn't in this copy of the file (it may have changed)." : "Locating the text to replace…";
      } else {
        const before = file.slice(0, idx);
        const startLine = before.split("\n").length - 1;
        if (!oldS.complete || !newS) {
          lines = file.split("\n");
          const n = oldS.value.split("\n").length;
          for (let i = 0; i < n; i++) marks.set(startLine + i, "old");
          focus = startLine;
        } else {
          const mid = newS.value;
          const settled = finished && st.file != null && st.file.indexOf(mid) >= 0;
          const text = settled ? file : before + mid + file.slice(idx + oldS.value.length);
          lines = text.split("\n");
          const s = (settled ? file.slice(0, file.indexOf(mid)) : before).split("\n").length - 1;
          const n = mid.split("\n").length;
          for (let i = 0; i < n; i++) marks.set(s + i, "new");
          focus = s;
          if (!newS.complete) caret = s + n - 1;
        }
      }
    }
  }

  // The pane is built once and then patched row by row: rebuilding it every frame cost thousands of
  // DOM nodes per frame and swapped the Follow switch out from under the user's click.
  const v = paneFor(body);
  v.path.classList.remove("cmd");
  v.code.hidden = false;
  v.path.textContent = p.path || "";
  v.path.title = p.path || "";
  v.note.textContent = note || "";
  v.note.hidden = !note;
  if (v.toggle.classList.contains("on") !== st.follow) setToggle(v.toggle, st.follow);
  if (lines.length > 4000) lines = lines.slice(0, 4000).concat(["… (truncated)"]);
  if (v.code.firstChild?.classList?.contains("live-term")) v.code.replaceChildren(); // was showing a command
  const rows = v.code.children;
  for (let i = 0; i < lines.length; i++) {
    const cls = `ln-row${marks.has(i) ? " " + marks.get(i) : ""}${i === caret ? " caret" : ""}`;
    let row = rows[i];
    if (!row) {
      row = el("div", el("span.ln", String(i + 1)), el("span.tx"));
      v.code.append(row);
    }
    if (row.className !== cls) row.className = cls;
    const tx = row.lastChild;
    if (tx.textContent !== lines[i]) tx.textContent = lines[i];
  }
  while (rows.length > lines.length) v.code.lastChild.remove();
  if (st.follow) {
    requestAnimationFrame(() => {
      v.auto = true;
      if (st.kind === "write" && !finished) body.scrollTop = body.scrollHeight;
      else if (focus >= 0 && st.scrolledTo !== focus) {
        const row = rows[focus];
        if (row) { body.scrollTop = Math.max(0, row.offsetTop - body.clientHeight / 3); st.scrolledTo = focus; }
      } else if (caret >= 0) {
        const row = rows[caret];
        if (row && row.offsetTop > body.scrollTop + body.clientHeight - 60) body.scrollTop = row.offsetTop - body.clientHeight + 80;
      }
      requestAnimationFrame(() => (v.auto = false));
    });
  }
}

/** A running command as a terminal: the command line, then its output as it arrives. */
function renderRun(body, titleBox) {
  const finished = st.done;
  titleBox.replaceChildren(logoNode({ size: 26, working: !finished }), el("span", finished ? "Ran a command" : "Running a command"),
    finished ? el("span.pill-tag", st.error ? "failed" : "done") : el("span.pill-tag.accent", "live"));
  const v = paneFor(body);
  v.path.textContent = st.command;
  v.path.title = st.command;
  v.path.classList.add("cmd");
  const out = (st.out || "").replace(/\s+$/, "");
  v.note.textContent = out ? "" : finished ? "(no output)" : "Waiting for the first output…";
  v.note.hidden = !!out;
  v.code.hidden = !out;
  if (v.toggle.classList.contains("on") !== st.follow) setToggle(v.toggle, st.follow);
  let term = v.code.firstChild;
  if (!term || !term.classList.contains("live-term")) { term = el("pre.live-term"); v.code.replaceChildren(term); }
  if (term.textContent !== out) term.textContent = out;
  if (st.follow) {
    requestAnimationFrame(() => {
      v.auto = true;
      body.scrollTop = body.scrollHeight;
      requestAnimationFrame(() => (v.auto = false));
    });
  }
}

let pane = null;

/** The pane's fixed parts, made once per drawer body: header with the Follow switch, a note, the code. */
function paneFor(body) {
  if (pane && pane.body === body && pane.root.isConnected) return pane;
  const toggleEl = toggle(st.follow, (on) => { st.follow = on; if (on) st.scrolledTo = -1; });
  const path = el("span.path");
  const note = el("div.live-note", { hidden: true });
  const code = el("div.live-code");
  const root = el("div.live-root", el("div.live-head", path, el("label.live-follow", el("span", "follow"), toggleEl)), note, code);
  body.replaceChildren(root);
  pane = { body, root, path, note, code, toggle: toggleEl, auto: false };
  // Scrolling up yourself means "let me read": follow switches off until you turn it back on.
  body.addEventListener("wheel", (e) => { if (e.deltaY < 0 && st.follow) { st.follow = false; setToggle(toggleEl, false); } }, { passive: true });
  return pane;
}

function setToggle(t, on) {
  t.classList.toggle("on", on);
  t.setAttribute("aria-checked", String(on));
}
