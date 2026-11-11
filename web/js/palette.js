// Command palette (Ctrl+P): one search box for actions, threads, models, themes and settings.

import { el, ico } from "./ui.js";

let open = null;

/** items: [{ title, sub, icon, mark, group, keywords, run }]; mark() returns a node shown in place of the icon */
export function openPalette(items, { placeholder = "Type a command, thread, model or theme…" } = {}) {
  if (open) { open.close(); return; }
  const input = el("input.pal-input", { placeholder, spellcheck: false });
  const list = el("div.pal-list");
  const box = el("div.pal", el("div.pal-search", ico("command"), input, el("kbd", "Esc")), list);
  const scrim = el("div.pal-scrim", box);
  let shown = [];
  let index = 0;
  const score = (it, q) => {
    if (!q) return 1;
    const hay = `${it.title} ${it.sub || ""} ${it.keywords || ""} ${it.group || ""}`.toLowerCase();
    const title = it.title.toLowerCase();
    if (title.startsWith(q)) return 4;
    if (title.includes(q)) return 3;
    if (hay.includes(q)) return 2;
    let i = 0; // letters in order ("nth" finds "New thread")
    for (const ch of hay) if (ch === q[i]) i++;
    return i === q.length ? 1 : 0;
  };
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    shown = items.map((it) => [score(it, q), it]).filter(([s]) => s > 0).sort((a, b) => b[0] - a[0]).slice(0, 60).map(([, it]) => it);
    index = Math.min(index, Math.max(0, shown.length - 1));
    list.replaceChildren();
    let group = null;
    shown.forEach((it, i) => {
      if (!q && it.group !== group) { group = it.group; list.append(el("div.pal-group", group)); }
      list.append(el(`button.pal-item${i === index ? ".on" : ""}`, { type: "button", on: { mousemove: () => { if (index !== i) { index = i; mark(); } }, click: () => run(it) } },
        it.mark ? it.mark() : ico(it.icon || "chev"), el("span.pal-title", it.title), it.sub ? el("span.pal-sub", it.sub) : null, q ? el("span.pal-tag", it.group) : null));
    });
    if (!shown.length) list.append(el("div.empty-row", "Nothing matches"));
  };
  const mark = () => list.querySelectorAll(".pal-item").forEach((b, i) => { b.classList.toggle("on", i === index); if (i === index) b.scrollIntoView({ block: "nearest" }); });
  const run = (it) => { close(); setTimeout(() => it.run(), 0); };
  const close = () => {
    scrim.classList.add("closing");
    setTimeout(() => scrim.remove(), 160);
    document.removeEventListener("keydown", onKey, true);
    open = null;
  };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); index = (index + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % Math.max(1, shown.length); mark(); }
    else if (e.key === "Enter") { e.preventDefault(); if (shown[index]) run(shown[index]); }
  };
  input.addEventListener("input", () => { index = 0; draw(); });
  scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
  document.addEventListener("keydown", onKey, true);
  document.getElementById("overlay-root").append(scrim);
  draw();
  setTimeout(() => input.focus(), 10);
  open = { close };
}
