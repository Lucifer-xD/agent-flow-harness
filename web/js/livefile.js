// Live file pane: while the model writes or edits a file, show it happening. OpenCode streams
// the tool's input as it is generated, so a write can be shown typing out and an edit can be
// shown in place — the file is loaded, the old text found, and the new text typed over it.

import { api } from "./api.js";
import { logoNode } from "./logo.js";
import { basename, el, ico, toggle } from "./ui.js";

let ctx = null;
const st = { tool: null, kind: null, raw: "", input: null, file: null, filePath: null, loading: null, done: false, error: null, follow: true, frame: 0, scrolledTo: -1, startedAt: 0 };
export const liveState = st;

export function initLive(c) {
  ctx = c;
}

const WRITE = new Set(["write"]);
const EDIT = new Set(["edit", "multiedit"]);

export function onLiveEvent(ev) {
  if (!ctx || ctx.S.settings.ui.liveFiles === false) return;
  const d = ev.data || {};
  switch (ev.type) {
    case "session.tool.input.started": {
      const n = (d.name || "").toLowerCase();
      if (!WRITE.has(n) && !EDIT.has(n)) return;
      Object.assign(st, { tool: d.id, kind: WRITE.has(n) ? "write" : "edit", raw: "", input: null, file: null, filePath: null, loading: null, done: false, error: null, scrolledTo: -1, startedAt: Date.now() });
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
      break;
    case "session.tool.success":
    case "session.tool.failed":
      if (d.id === st.tool) {
        st.done = true;
        st.error = ev.type.endsWith("failed") ? d.error?.message || "failed" : null;
        if (st.filePath) loadFile(st.filePath, true).then(schedule);
        schedule();
      }
      break;
  }
}

function schedule() {
  if (st.frame) return;
  st.frame = requestAnimationFrame(() => { st.frame = 0; ctx.renderLive(); });
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
  if (st.input) {
    const i = st.input;
    const s = (v) => (v == null ? null : { value: String(v), complete: true });
    return { path: pickKey(i, "path", "filePath", "file_path", "file"), content: s(i.content), old: s(pickKey(i, "oldString", "old_string", "old")), new_: s(pickKey(i, "newString", "new_string", "new")) };
  }
  const raw = st.raw;
  const path = partialString(raw, "path") || partialString(raw, "filePath") || partialString(raw, "file_path");
  return {
    path: path?.complete ? path.value : null,
    content: partialString(raw, "content"),
    old: partialString(raw, "oldString") || partialString(raw, "old_string"),
    new_: partialString(raw, "newString") || partialString(raw, "new_string"),
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
    body.replaceChildren(el("div.live-note", "When the model writes or edits a file, it appears here as it happens."));
    return;
  }
  const p = parse();
  if (p.path) p.path = absolute(p.path);
  if (p.path && st.filePath !== p.path && !st.loading) loadFile(p.path);
  const name = basename(p.path || "");
  const verb = st.kind === "write" ? (st.done ? "Wrote" : "Writing") : st.done ? "Edited" : "Editing";
  titleBox.replaceChildren(logoNode({ size: 26, working: !st.done }), el("span", `${verb} ${name || "…"}`),
    st.done ? el("span.pill-tag", st.error ? "failed" : "done") : el("span.pill-tag.accent", "live"));

  let lines = [], marks = new Map(), focus = -1, caret = -1, note = null;
  if (st.kind === "write") {
    const text = st.done && st.file != null ? st.file : p.content?.value ?? "";
    lines = text.split("\n");
    if (!st.done) { caret = lines.length - 1; for (let i = 0; i < lines.length; i++) marks.set(i, "new"); }
    else for (let i = 0; i < lines.length; i++) marks.set(i, "new");
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
          const text = st.done && st.file != null && st.file.indexOf(mid) >= 0 ? file : before + mid + file.slice(idx + oldS.value.length);
          lines = text.split("\n");
          const s = (st.done && st.file.indexOf(mid) >= 0 ? file.slice(0, file.indexOf(mid)) : before).split("\n").length - 1;
          const n = mid.split("\n").length;
          for (let i = 0; i < n; i++) marks.set(s + i, "new");
          focus = s;
          if (!newS.complete) caret = s + n - 1;
        }
      }
    }
  }

  const follow = toggle(st.follow, (v) => (st.follow = v));
  const head = el("div.live-head", el("span.path", { title: p.path || "" }, p.path || ""), el("span", "follow"), follow);
  const code = el("div.live-code");
  if (lines.length > 4000) lines = lines.slice(0, 4000).concat(["… (truncated)"]);
  const frag = document.createDocumentFragment();
  lines.forEach((l, i) => {
    const row = el(`div.ln-row${marks.has(i) ? "." + marks.get(i) : ""}${i === caret ? ".caret" : ""}`, el("span.ln", String(i + 1)), el("span.tx", l));
    if (i === focus) row.id = "live-focus";
    frag.append(row);
  });
  code.append(frag);
  body.replaceChildren(head, note ? el("div.live-note", note) : null, code);
  if (st.follow) {
    requestAnimationFrame(() => {
      if (st.kind === "write" && !st.done) body.scrollTop = body.scrollHeight;
      else if (focus >= 0 && st.scrolledTo !== focus) {
        const row = body.querySelector("#live-focus");
        if (row) { body.scrollTop = Math.max(0, row.offsetTop - body.clientHeight / 3); st.scrolledTo = focus; }
      } else if (caret >= 0) {
        const row = body.querySelectorAll(".ln-row")[caret];
        if (row && row.offsetTop > body.scrollTop + body.clientHeight - 60) body.scrollTop = row.offsetTop - body.clientHeight + 80;
      }
    });
  }
}
