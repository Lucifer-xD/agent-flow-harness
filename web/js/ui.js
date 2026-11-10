// Shared UI helpers: icons, DOM builder, markdown, diffs, popovers, modals, toasts.

import { fileIconSvg, kindLabel, langKind } from "./fileicons.js";

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
  "arrow-up": P('<path d="M12 19V5M5 12l7-7 7 7"/>'),
  terminal: P('<path d="m4 17 6-5-6-5M12 19h8"/>'),
  "mouse-pointer": P('<path d="M5 3l15 9-6.3 1.2L17 20l-2.8 1.2-3.2-6.9L5 18z"/>'),
  monitor: P('<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>'),
  file: P('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'),
  edit: P('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  globe: P('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  github: P('<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>'),
  external: P('<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'),
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
  target: P('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>'),
  checklist: P('<path d="m3 6 1.5 1.5L7 5M3 12l1.5 1.5L7 11M3 18l1.5 1.5L7 17M11 6h10M11 12h10M11 18h10"/>'),
  coin: P('<circle cx="12" cy="12" r="9"/><path d="M14.8 9.2A2.8 2.4 0 0 0 12 8c-1.6 0-2.8.9-2.8 2s1.2 1.7 2.8 2 2.8.9 2.8 2-1.2 2-2.8 2a2.8 2.4 0 0 1-2.8-1.2M12 6.5V8M12 16v1.5"/>'),
  slash: P('<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m14.5 7-5 10"/>'),
  hook: P('<path d="M18 3v8a6 6 0 0 1-12 0V9"/><path d="m3 12 3-3 3 3"/>'),
  activity: P('<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
  image: P('<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-9 9"/>'),
  video: P('<rect x="2.5" y="6" width="13" height="12" rx="2.5"/><path d="m15.5 10.5 6-3.5v10l-6-3.5"/>'),
  mic: P('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  sun: P('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: P('<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>'),
  languages: P('<path d="M4 5h9M8.5 3v2M6 5c0 4 3 7 6 8M11 5c-1 4-4 7-7 8"/><path d="m13 21 4-9 4 9M14.5 18h5"/>'),
  command: P('<path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z"/>'),
  clock: P('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  code: P('<path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>'),
  bug: P('<rect x="7" y="8" width="10" height="12" rx="5"/><path d="M12 8V6M9 6.5 7.5 4M15 6.5 16.5 4M3 13h4M17 13h4M4 19l3.2-2M20 19l-3.2-2M4 7l3.2 2M20 7l-3.2 2"/>'),
  download: P('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>'),
  camera: P('<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>'),
  "git-merge": P('<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="12" r="2.5"/><path d="M6 8.5v7M8 7.5c2 3 5 4.5 7.5 4.5"/>'),
};

const MODALITY = { image: ["image", "Reads images"], video: ["video", "Understands video"], audio: ["mic", "Understands audio"], pdf: ["file", "Reads PDFs"] };

/** Small icons for what a model can take in besides text (image, video, audio, PDF). */
export function modalityBadges(input) {
  const kinds = (input || []).filter((k) => MODALITY[k]);
  if (!kinds.length) return null;
  return el("span.mods", { title: kinds.map((k) => MODALITY[k][1]).join(" · ") }, kinds.map((k) => el("span.mod", { html: icon(MODALITY[k][0]) })));
}

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
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) {
        if (sv == null) continue;
        if (sk.startsWith("--")) node.style.setProperty(sk, sv); // custom properties need setProperty
        else node.style[sk] = sv;
      }
    }
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

// The DOM's own insert methods turn null/undefined/false into the words "null"/"false" on screen.
// The code passes `cond ? el(...) : null` to them the same way it does to el(), so skip those here too.
for (const proto of [Element.prototype, DocumentFragment.prototype]) {
  for (const name of ["append", "prepend", "replaceChildren", "before", "after", "replaceWith"]) {
    const orig = proto[name];
    if (typeof orig !== "function") continue;
    proto[name] = function (...nodes) { return orig.apply(this, nodes.filter((n) => n != null && n !== false)); };
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
  const kind = langKind(language);
  const label = kind ? kindLabel(kind) : language || "text";
  const badge = kind ? `<span class="fi fi-${kind}" aria-hidden="true">${fileIconSvg(kind)}</span>` : "";
  return `<div class="codeblock${kind ? ` lang-${kind}` : ""}"><div class="codeblock-head"><span class="cb-lang">${badge}<span>${escapeHtml(label)}</span></span><button class="copy-btn" data-copy>${icon("copy").replace("<svg", '<svg class="ico"')}<span>Copy</span></button></div><pre><code class="hljs">${html}</code></pre></div>`;
};
renderer.link = (href, title, text) => `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer"${title ? ` title="${escapeHtml(title)}"` : ""}>${text}</a>`;
marked.setOptions({ renderer, gfm: true, breaks: false });

export function markdown(text) {
  const html = DOMPurify.sanitize(marked.parse(text || ""), { ADD_ATTR: ["target", "data-copy"] });
  // Each block takes its direction from its own text: Arabic right to left, English left to right.
  return html.replace(/<(p|ul|ol|li|h[1-6]|blockquote|table)(?=[\s>])/g, '<$1 dir="auto"');
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

export const fmtDur = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
};
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
  if (opts.className) pop.classList.add(...opts.className.split(" ").filter(Boolean));
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
          el("div.pi-main", el("div.pi-title", it.title, it.badges || null), it.sub ? el("div.pi-sub", it.sub) : null),
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

  const place = () => {
    const r = anchor.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = Math.min(r.left, innerWidth - pw - 10);
    if (opts.align === "right") left = Math.max(10, r.right - pw);
    // Open upward when the anchor sits in the lower half or there is no room below.
    const below = r.bottom + 6, above = r.top - ph - 6;
    const up = r.top > innerHeight / 2 || below + ph > innerHeight - 10;
    let top = up ? above : below;
    let origin = up ? "bottom left" : "top left";
    if (top < 10) { top = 10; }
    pop.style.maxHeight = Math.max(160, innerHeight - 20) + "px";
    pop.style.overflowY = "auto";
    Object.assign(pop.style, { left: Math.max(10, left) + "px", top: top + "px" });
    pop.style.setProperty("--origin", origin);
  };
  place();

  const onDown = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const onKey = (e) => { if (e.key === "Escape") closePopover(); };
  setTimeout(() => document.addEventListener("mousedown", onDown), 0);
  document.addEventListener("keydown", onKey);
  openPop = { cleanup: () => { pop.remove(); document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); }, place };
  return pop;
}

/** Re-run placement after a popover's content changed size. */
export function repositionPopover() {
  openPop?.place?.();
}

// ---- segmented controls: one highlight that slides to the chosen option -----------

function placePill(seg) {
  const pill = seg.querySelector(":scope > .seg-pill");
  if (!pill) return;
  const on = [...seg.children].find((c) => c !== pill && c.classList.contains("on") && !c.hidden);
  if (!on || !on.offsetWidth) { pill.classList.remove("show"); return; }
  const first = !pill.classList.contains("show");
  if (first) pill.style.transition = "none"; // the first time it lands in place instead of sliding in from the corner
  pill.style.width = `${on.offsetWidth}px`;
  pill.style.height = `${on.offsetHeight}px`;
  pill.style.transform = `translate(${on.offsetLeft}px, ${on.offsetTop}px)`;
  pill.classList.add("show");
  if (first) requestAnimationFrame(() => requestAnimationFrame(() => { pill.style.transition = ""; }));
}

function fitPill(seg) {
  if (!seg.querySelector(":scope > .seg-pill")) {
    seg.prepend(el("span.seg-pill", { "aria-hidden": "true" }));
    seg.classList.add("has-pill");
    seg.addEventListener("click", () => requestAnimationFrame(() => placePill(seg)));
    if (window.ResizeObserver) new ResizeObserver(() => placePill(seg)).observe(seg);
  }
  placePill(seg);
}

/** Every .seg under `root` gets a sliding highlight, including ones added later. */
export function slidePills(root) {
  if (!root || root._pills) return;
  root._pills = true;
  root.querySelectorAll(".seg").forEach(fitPill);
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "attributes") {
        if (r.target.classList.contains("seg-pill")) continue;
        const seg = r.target.parentElement;
        if (seg?.classList.contains("has-pill")) placePill(seg);
        continue;
      }
      for (const n of r.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.classList.contains("seg")) fitPill(n);
        n.querySelectorAll?.(".seg").forEach(fitPill);
      }
    }
  }).observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
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

/** A small progress ring: how much of a list is done. */
export function progressRing(done, of, size = 18) {
  const r = (size - 3) / 2, c = 2 * Math.PI * r, f = of ? Math.min(1, done / of) : 0, h = size / 2;
  const t = document.createElement("template");
  t.innerHTML = `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true"><circle class="ring-bg" cx="${h}" cy="${h}" r="${r}" fill="none" stroke-width="2.5"/><circle class="ring-fg" cx="${h}" cy="${h}" r="${r}" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${(c * (1 - f)).toFixed(2)}" transform="rotate(-90 ${h} ${h})"/></svg>`;
  return t.content.firstChild;
}
