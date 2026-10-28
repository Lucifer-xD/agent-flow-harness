// Shared UI helpers: icons, DOM builder, markdown, diffs, popovers, modals, toasts.

const P = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
export const ICONS = {
  plus: P('<path d="M12 5v14M5 12h14"/>'),
  search: P('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  settings: P('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  sidebar: P('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>'),
  folder: P('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  "folder-plus": P('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>'),
  chev: P('<path d="m9 6 6 6-6 6"/>'),
  "chev-down": P('<path d="m6 9 6 6 6-6"/>'),
  send: P('<path d="M12 19V5M5 12l7-7 7 7"/>'),
  stop: '<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/></svg>',
  paperclip: P('<path d="m21 11-8.6 8.6a5 5 0 0 1-7-7L14 4a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4L15.6 7"/>'),
  x: P('<path d="M18 6 6 18M6 6l12 12"/>'),
  check: P('<path d="M20 6 9 17l-5-5"/>'),
  copy: P('<rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>'),
  more: P('<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>'),
  trash: P('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  diff: P('<path d="M6 3v12M18 9v12M3 6h6M15 18h6M15 6l3-3 3 3M3 18l3 3 3-3"/>'),
  scroll: P('<path d="M8 21h11a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2h4M6 3h12a2 2 0 0 1 2 2v12"/><path d="M10 8h6M10 12h6"/>'),
  "arrow-down": P('<path d="M12 5v14M19 12l-7 7-7-7"/>'),
  terminal: P('<path d="m4 17 6-5-6-5M12 19h8"/>'),
  file: P('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'),
  edit: P('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  globe: P('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  plug: P('<path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0zM12 17v5"/>'),
  puzzle: P('<path d="M19.4 13.6a2.5 2.5 0 1 0 0-3.2V7a1 1 0 0 0-1-1h-3.4a2.5 2.5 0 1 0-3.2 0H8.4a1 1 0 0 0-1 1v3.4a2.5 2.5 0 1 0 0 3.2V17a1 1 0 0 0 1 1h3.4a2.5 2.5 0 1 0 3.2 0h3.4a1 1 0 0 0 1-1z"/>'),
  cpu: P('<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
  user: P('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  sliders: P('<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>'),
  bot: P('<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M8 4h8M9 14h.01M15 14h.01"/>'),
  info: P('<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>'),
  alert: P('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  shield: P('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'),
  "shield-check": P('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>'),
  zap: P('<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>'),
  eye: P('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  sparkle: P('<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/>'),
  key: P('<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.3-9.3M17 6l3 3M14 9l2 2"/>'),
  refresh: P('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
  branch: P('<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="8" r="2.5"/><path d="M6 8.5v7M18 10.5a6 6 0 0 1-6 6H8.5"/>'),
  archive: P('<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>'),
  book: P('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>'),
  list: P('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
};

export function icon(name) {
  return ICONS[name] || ICONS.sparkle;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((n) => {
    if (!n.firstChild) n.innerHTML = icon(n.dataset.icon);
  });
}

// el("div.cls#id", {attrs, on: {click}}, children...)
export function el(spec, props, ...children) {
  if (props == null || typeof props !== "object" || props instanceof Node || Array.isArray(props)) {
    if (props !== undefined && props !== null) children.unshift(props);
    props = {};
  }
  const [, tag = "div", rest = ""] = spec.match(/^([a-z0-9]*)(.*)$/i);
  const node = document.createElement(tag || "div");
  for (const part of rest.match(/[.#][^.#]+/g) || []) {
    if (part[0] === ".") node.classList.add(part.slice(1));
    else node.id = part.slice(1);
  }
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else if (k === "value") node.value = v;
    else if (k === "className") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k in node && typeof v !== "string") node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const ch of children.flat(Infinity)) {
    if (ch == null || ch === false) continue;
    node.append(ch instanceof Node ? ch : document.createTextNode(String(ch)));
  }
}

export const ico = (name, cls = "") => el(`span.ico${cls ? "." + cls : ""}`, { html: icon(name) });

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// ---- markdown ---------------------------------------------------------------

const renderer = new marked.Renderer();
renderer.code = (code, lang) => {
  const language = (lang || "").split(/\s/)[0];
  let html;
  try {
    html = language && hljs.getLanguage(language) ? hljs.highlight(code, { language }).value : hljs.highlightAuto(code).value;
  } catch {
    html = escapeHtml(code);
  }
  return `<div class="codeblock"><div class="codeblock-head"><span>${escapeHtml(language || "text")}</span><button class="copy-btn" data-copy>${icon("copy").replace("<svg", '<svg class="ico"')}<span>Copy</span></button></div><pre><code class="hljs">${html}</code></pre></div>`;
};
renderer.link = (href, title, text) => `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer"${title ? ` title="${escapeHtml(title)}"` : ""}>${text}</a>`;
marked.setOptions({ renderer, gfm: true, breaks: false });

export function markdown(text) {
  return DOMPurify.sanitize(marked.parse(text || ""), { ADD_ATTR: ["target", "data-copy"] });
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const code = btn.closest(".codeblock")?.querySelector("code")?.innerText ?? btn.dataset.copy;
  await copyText(code);
  const label = btn.querySelector("span");
  if (label) {
    label.textContent = "Copied";
    setTimeout(() => (label.textContent = "Copy"), 1400);
  }
});

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = el("textarea", { value: text, style: { position: "fixed", opacity: "0" } });
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

// ---- diffs --------------------------------------------------------------------

export function diffView(patch) {
  const box = el("div.diff");
  let oldNo = 0, newNo = 0;
  for (const line of (patch || "").split("\n")) {
    if (line.startsWith("Index:") || line.startsWith("====") || line.startsWith("---") || line.startsWith("+++") || line.startsWith("\\ No newline")) continue;
    if (line.startsWith("@@")) {
      const m = line.match(/-(\d+)(?:,\d+)? \+(\d+)/);
      if (m) [oldNo, newNo] = [Number(m[1]), Number(m[2])];
      box.append(el("div.diff-line.hunk", el("span.ln", "⋯"), el("span.tx", line)));
    } else if (line.startsWith("+")) {
      box.append(el("div.diff-line.add", el("span.ln", String(newNo++)), el("span.tx", line)));
    } else if (line.startsWith("-")) {
      box.append(el("div.diff-line.del", el("span.ln", String(oldNo++)), el("span.tx", line)));
    } else if (line.length || box.childElementCount) {
      oldNo++;
      box.append(el("div.diff-line", el("span.ln", String(newNo++)), el("span.tx", " " + line.slice(1))));
    }
  }
  return box;
}

export function patchFromStrings(oldText = "", newText = "") {
  const a = oldText.split("\n"), b = newText.split("\n");
  return ["@@ -1," + a.length + " +1," + b.length + " @@", ...a.filter((l) => oldText).map((l) => "-" + l), ...b.map((l) => "+" + l)].join("\n");
}

// ---- time ---------------------------------------------------------------------

export function ago(ms) {
  if (!ms) return "";
  const s = (Date.now() - ms) / 1000;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 604800) return `${Math.floor(s / 86400)}d`;
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function dayGroup(ms) {
  const d = new Date(ms), now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (ms >= start) return "Today";
  if (ms >= start - 86400000) return "Yesterday";
  if (ms >= start - 6 * 86400000) return "This week";
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString(undefined, { month: "long" });
  return String(d.getFullYear());
}

export const fmtTokens = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(Math.round(n || 0)));
export const basename = (p) => (p || "").split(/[\\/]/).filter(Boolean).pop() || p;

// ---- popovers -----------------------------------------------------------------

let openPop = null;
export function closePopover() {
  if (openPop) {
    openPop.cleanup();
    openPop = null;
  }
}

/**
 * Anchored menu. items: [{group}|{sep}|{title, sub, icon, checked, danger, onSelect}].
 * opts: {search: bool, footer: Node, width}
 */
export function popover(anchor, items, opts = {}) {
  closePopover();
  const list = el("div.pop-list");
  const pop = el("div.pop", { style: { width: opts.width ? opts.width + "px" : null } });
  let kb = -1;
  let query = "";
  const render = () => {
    list.replaceChildren();
    const q = query.toLowerCase();
    let lastGroup = null;
    // searchItems: a flat list searched instead of the menu when the user types
    const source = q && opts.searchItems ? opts.searchItems : items;
    for (const it of source) {
      if (it.group) { lastGroup = it.group; continue; }
      if (it.sep) { if (!q) list.append(el("div.pop-sep")); continue; }
      if (q && !`${it.title} ${it.sub || ""} ${it.keywords || ""}`.toLowerCase().includes(q)) continue;
      if (lastGroup) { list.append(el("div.pop-group", lastGroup)); lastGroup = null; }
      list.append(
        el(`button.pop-item${it.danger ? ".danger" : ""}`, { type: "button", on: { click: () => { if (!it.keepOpen) closePopover(); it.onSelect?.(); } } },
          it.icon ? ico(it.icon) : null,
          el("div.pi-main", el("div.pi-title", it.title), it.sub ? el("div.pi-sub", it.sub) : null),
          it.count != null ? el("span.pi-count", String(it.count)) : null,
          it.checked ? el("span.check", { html: icon("check") }) : null,
          it.arrow ? el("span.chev", { html: icon("chev"), style: { width: "14px", height: "14px", color: "var(--text-3)" } }) : null)
      );
    }
    if (!list.childElementCount && !opts.header) list.append(el("div.empty-row", "Nothing matches"));
    kb = -1;
  };
  if (opts.header) pop.append(opts.header);
  if (opts.search) {
    const input = el("input", { placeholder: opts.placeholder || "Search…", on: {
      input: (e) => { query = e.target.value; render(); },
      keydown: (e) => {
        const btns = [...list.querySelectorAll(".pop-item")];
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          kb = Math.max(0, Math.min(btns.length - 1, kb + (e.key === "ArrowDown" ? 1 : -1)));
          btns.forEach((b, i) => b.classList.toggle("kb", i === kb));
          btns[kb]?.scrollIntoView({ block: "nearest" });
        } else if (e.key === "Enter") {
          e.preventDefault();
          (btns[kb] || btns[0])?.click();
        }
      },
    } });
    pop.append(el("div.pop-search", ico("search"), input));
    setTimeout(() => input.focus(), 10);
  }
  pop.append(list);
  if (opts.footer) pop.append(opts.footer);
  render();
  document.getElementById("overlay-root").append(pop);

  const r = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = Math.min(r.left, innerWidth - pw - 10);
  let top = r.bottom + 6;
  let origin = "top left";
  if (top + ph > innerHeight - 10) { top = r.top - ph - 6; origin = "bottom left"; }
  if (opts.align === "right") left = Math.max(10, r.right - pw);
  Object.assign(pop.style, { left: Math.max(10, left) + "px", top: Math.max(10, top) + "px", "--origin": origin });

  const onDown = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const onKey = (e) => { if (e.key === "Escape") closePopover(); };
  setTimeout(() => document.addEventListener("mousedown", onDown), 0);
  document.addEventListener("keydown", onKey);
  openPop = { cleanup: () => { pop.remove(); document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); } };
  return pop;
}

// ---- modals -------------------------------------------------------------------

export function modal(content, { small = false, onClose } = {}) {
  const box = el(`div.modal${small ? ".small" : ""}`, { role: "dialog" }, content);
  const scrim = el("div.scrim", box);
  const close = () => {
    scrim.classList.add("closing");
    setTimeout(() => scrim.remove(), 200);
    document.removeEventListener("keydown", onKey);
    onClose?.();
  };
  const onKey = (e) => { if (e.key === "Escape" && !document.querySelector(".pop")) close(); };
  scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
  document.addEventListener("keydown", onKey);
  document.getElementById("overlay-root").append(scrim);
  return { close, box };
}

export function confirmDialog({ title, body, confirm = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); m.close(); } };
    const m = modal(
      el("div.m-body", { style: { padding: "22px 24px" } },
        el("h2", title),
        el("p.lead", { style: { marginBottom: "18px" } }, body),
        el("div.actions",
          el("button.btn.ghost", { on: { click: () => finish(false) } }, "Cancel"),
          el(`button.btn.${danger ? "danger" : "primary"}`, { on: { click: () => finish(true) } }, confirm))),
      { small: true, onClose: () => { if (!done) { done = true; resolve(false); } } }
    );
  });
}

export function promptDialog({ title, label, value = "", placeholder = "", confirm = "Save" }) {
  return new Promise((resolve) => {
    let done = false;
    const input = el("input.inp", { value, placeholder });
    const finish = (v) => { if (!done) { done = true; resolve(v); m.close(); } };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") finish(input.value); });
    const m = modal(
      el("div.m-body", { style: { padding: "22px 24px" } },
        el("h2", { style: { marginBottom: "16px" } }, title),
        el("div.field", label ? el("label", label) : null, input),
        el("div.actions",
          el("button.btn.ghost", { on: { click: () => finish(null) } }, "Cancel"),
          el("button.btn.primary", { on: { click: () => finish(input.value) } }, confirm))),
      { small: true, onClose: () => { if (!done) { done = true; resolve(null); } } }
    );
    setTimeout(() => { input.focus(); input.select(); }, 30);
  });
}

// ---- toasts -------------------------------------------------------------------

export function toast(message, kind = "info", ms = 3200) {
  const t = el(`div.toast.${kind}`, ico(kind === "err" ? "alert" : kind === "ok" ? "check" : "info"), el("span", message));
  document.getElementById("toasts").append(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 260); }, ms);
}

export function toggle(on, onChange) {
  const t = el(`button.toggle${on ? ".on" : ""}`, { type: "button", role: "switch", "aria-checked": String(!!on) });
  t.addEventListener("click", () => {
    const next = !t.classList.contains("on");
    t.classList.toggle("on", next);
    t.setAttribute("aria-checked", String(next));
    onChange(next, t);
  });
  return t;
}

export function contextRing(fraction) {
  const f = Math.max(0, Math.min(1, fraction || 0));
  const r = 8, c = 2 * Math.PI * r;
  const color = f > 0.85 ? "var(--bad)" : f > 0.6 ? "var(--warn)" : "var(--accent)";
  return `<svg viewBox="0 0 22 22"><circle cx="11" cy="11" r="${r}" fill="none" stroke="var(--panel-3)" stroke-width="2.5"/><circle cx="11" cy="11" r="${r}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - f)}" transform="rotate(-90 11 11)" style="transition:stroke-dashoffset .6s var(--ease)"/></svg>`;
}
