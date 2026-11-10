// The model picker: a search box and one simple list, grouped under each provider's logo. Picking a
// model that has effort levels opens a second step to choose the effort. Used by the message box (the
// thread's model) and by Settings (the default model). While it is open it follows the live model list,
// so removing a provider or hiding a model in Settings shows at once.

import { closePopover, el, fmtTokens, ico, icon, popover } from "./ui.js";
import { providerLogo } from "./provider-logos.js";

const RECENT_KEY = "afh-recent-models";
const same = (a, b) => !!a && !!b && a.id === b.id && a.providerID === b.providerID;

function recent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; }
}
/** Remember a picked model (kept for other callers; the picker itself stays one plain list). */
export function rememberModel(ref) {
  if (!ref?.id) return;
  const list = [{ id: ref.id, providerID: ref.providerID }, ...recent().filter((r) => !same(r, ref))].slice(0, 6);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* private window */ }
}

/** A short line of facts about a model: context, effort levels, what it can't do. */
export function modelFacts(m) {
  return [m.context ? `${fmtTokens(m.context)} context` : null, m.variants?.length ? `effort ${m.variants.join(" · ")}` : null, m.tools === false ? "no tools" : null].filter(Boolean).join("  ·  ");
}

/** The provider's logo on a soft tile; two letters on the provider's own colour when there is no logo. */
export function providerMark(pid, label, size = 18) {
  const svg = providerLogo(pid, label);
  const style = { "--h": String(hue(pid)), "--s": `${size}px` };
  return svg
    ? el("span.pv-mark.has-logo", { style, "aria-hidden": "true", html: svg })
    : el("span.pv-mark", { style, "aria-hidden": "true" }, initials(label || pid));
}

/** Notify open pickers (and anything else listening) that the model list changed. */
export const modelsChanged = () => window.dispatchEvent(new CustomEvent("afh:models"));

// What each effort level means, in a few words. Unknown levels get a plain label.
const EFFORT = {
  default: ["Auto", "The provider's default"],
  none: ["None", "Answers straight away"],
  minimal: ["Minimal", "Barely thinks, fastest"],
  low: ["Low", "Quick, light thinking"],
  medium: ["Medium", "Balanced speed and depth"],
  high: ["High", "Thinks longer on hard tasks"],
  xhigh: ["Extra high", "Very thorough, slower"],
  max: ["Max", "Most thorough, slowest"],
};
export const effortLabel = (v) => EFFORT[v]?.[0] || v.charAt(0).toUpperCase() + v.slice(1);

/**
 * opts: {models | getModels(), current, providerName(pid), onPick(ref, {effortOnly}), onManage(), onAdd(), align, placeholder}
 * `current` may carry a variant (effort).
 */
export function modelPicker(anchor, opts) {
  const name = opts.providerName || ((pid) => pid);
  const source = () => (opts.getModels ? opts.getModels() : opts.models) || [];
  let models = source();
  let current = opts.current || null;
  let query = "";
  let kb = 0;
  let rows = [];
  let effortFor = null; // the model whose effort is being chosen (step two)

  const input = el("input.mpk-q", { placeholder: opts.placeholder || "Search models", spellcheck: false, autocomplete: "off", "aria-label": "Search models" });
  const search = el("label.mpk-search", ico("search"), input);
  const list = el("div.mpk-list", { role: "listbox" });
  const foot = el("div.mpk-foot");
  const box = el("div.mpk", search, list, foot);

  const matches = (m) => {
    if (!query) return true;
    const hay = `${m.name} ${m.id} ${name(m.providerID)}`.toLowerCase();
    return query.split(/\s+/).every((w) => hay.includes(w));
  };

  const row = (m) => {
    const on = same(m, current);
    const effort = on && current.variant && current.variant !== "default" ? effortLabel(current.variant) : null;
    const b = el(`button.mpk-row${on ? ".on" : ""}`, { type: "button", role: "option", "aria-selected": String(on), on: {
      click: () => choose(m), mousemove: () => { const i = rows.indexOf(b); if (i !== kb) { kb = i; mark(); } } } },
      el("span.mpk-name", m.name),
      m.context ? el("span.mpk-ctx", fmtTokens(m.context)) : null,
      effort ? el("span.mpk-eff", effort) : null,
      m.variants?.length ? el("span.mpk-more", { title: "Choose its effort next", html: icon("chev") }) : el("span.mpk-check", on ? { html: icon("check") } : null));
    rows.push(b);
    return b;
  };

  const drawModels = () => {
    effortFor = null;
    box.classList.remove("step-2");
    search.hidden = false;
    rows = [];
    const g = new Map();
    for (const m of models.filter(matches)) {
      if (!g.has(m.providerID)) g.set(m.providerID, []);
      g.get(m.providerID).push(m);
    }
    const parts = [];
    for (const [pid, ms] of g) parts.push(el("div.mpk-group", providerMark(pid, name(pid), 18), el("span", name(pid))), ...ms.map(row));
    if (!g.size) {
      parts.push(el("div.mpk-empty", ico(models.length ? "search" : "cpu"),
        el("b", models.length ? `Nothing matches “${query}”` : "No models yet"),
        el("span", models.length ? "Try a shorter name." : "Connect a provider in Settings to get models.")));
    }
    list.replaceChildren(...parts);
    kb = query ? 0 : Math.max(0, rows.findIndex((r) => r.classList.contains("on")));
    mark(true);
    drawFoot();
    requestAnimationFrame(reflow);
  };

  // Step two: the model is chosen, now its effort.
  const drawEffort = (m) => {
    effortFor = m;
    box.classList.add("step-2");
    search.hidden = true;
    rows = [];
    const levels = ["default", ...m.variants.filter((x) => x !== "default")];
    const was = same(m, current) ? current.variant || "default" : "default";
    const head = el("div.mpk-step",
      el("button.mpk-back", { type: "button", title: "Back to models", on: { click: () => { drawModels(); input.focus(); } }, html: icon("chev") }),
      providerMark(m.providerID, name(m.providerID), 22),
      el("span.mpk-step-t", el("b", m.name), el("small", "Choose the effort")));
    const opts2 = levels.map((v, i) => {
      const [label, sub] = EFFORT[v] || [effortLabel(v), ""];
      const b = el(`button.mpk-row.mpk-eff-row${v === was ? ".on" : ""}`, { type: "button", role: "option", on: {
        click: () => pick(m, v), mousemove: () => { const k = rows.indexOf(b); if (k !== kb) { kb = k; mark(); } } } },
        el("span.mpk-meter", { "aria-hidden": "true" }, ...[0, 1, 2, 3].map((k) => el(`i${v !== "default" && k < Math.ceil(((i) / (levels.length - 1)) * 4) ? ".f" : ""}`))),
        el("span.mpk-main", el("span.mpk-name", label), sub ? el("span.mpk-sub", sub) : null),
        el("span.mpk-check", v === was ? { html: icon("check") } : null));
      rows.push(b);
      return b;
    });
    list.replaceChildren(head, ...opts2);
    kb = Math.max(0, levels.indexOf(was));
    mark(true);
    foot.hidden = true;
    requestAnimationFrame(reflow);
    box.focus({ preventScroll: true });
  };

  const mark = (scrollToIt) => {
    rows.forEach((r, i) => r.classList.toggle("kb", i === kb));
    if (scrollToIt && rows[kb]) rows[kb].scrollIntoView({ block: "nearest" });
  };

  const drawFoot = () => {
    foot.replaceChildren(
      opts.onManage ? el("button.mpk-link", { type: "button", on: { click: () => { closePopover(); opts.onManage(); } } }, ico("sliders"), "Manage models") : null,
      el("span.mpk-grow"),
      opts.onAdd ? el("button.mpk-link", { type: "button", on: { click: () => { closePopover(); opts.onAdd(); } } }, ico("plus"), "Add provider") : null);
    foot.hidden = !foot.children.length;
  };

  // Opened above its button (the message box), the picker keeps its bottom edge there as the list grows or shrinks.
  const reflow = () => {
    const pop = box.closest(".pop");
    if (!pop || !anchor.isConnected) return;
    const a = (anchor.closest(".composer") || anchor).getBoundingClientRect();
    // offsetTop/offsetHeight ignore the opening animation's scale, which getBoundingClientRect would include.
    if (pop.offsetTop < a.top) pop.style.top = `${Math.max(8, a.top - pop.offsetHeight - 8)}px`;
  };

  const choose = (m) => (m.variants?.length ? drawEffort(m) : pick(m));
  const pick = (m, variant) => {
    const ref = { id: m.id, providerID: m.providerID };
    if (variant && variant !== "default") ref.variant = variant;
    rememberModel(ref);
    closePopover();
    opts.onPick?.(ref, {});
  };

  const keys = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      kb = Math.max(0, Math.min(rows.length - 1, kb + (e.key === "ArrowDown" ? 1 : -1)));
      mark(true);
    } else if (e.key === "Enter") {
      e.preventDefault();
      rows[kb]?.click();
    } else if (effortFor && (e.key === "ArrowLeft" || e.key === "Backspace")) {
      e.preventDefault();
      drawModels();
      input.focus();
    } else if (!effortFor && e.key === "ArrowRight" && rows[kb]) {
      const m = models.filter(matches)[kb];
      if (m?.variants?.length) { e.preventDefault(); drawEffort(m); }
    }
  };
  box.tabIndex = -1;
  box.addEventListener("keydown", keys);
  input.addEventListener("input", () => { query = input.value.trim().toLowerCase(); drawModels(); });

  // Follow the live list while open: a provider removed or a model hidden in Settings leaves at once.
  const onModels = () => {
    if (!box.isConnected) { window.removeEventListener("afh:models", onModels); return; }
    models = source();
    if (current && !models.some((m) => same(m, current))) current = null;
    if (effortFor && !models.some((m) => same(m, effortFor))) effortFor = null;
    if (effortFor) drawEffort(models.find((m) => same(m, effortFor)));
    else drawModels();
  };
  window.addEventListener("afh:models", onModels);

  drawModels();
  const width = Math.min(340, innerWidth - 20);
  popover(anchor, [], { header: box, width, align: opts.align || "right", className: "mpk-pop" });
  setTimeout(() => { input.focus(); mark(true); }, 20);
}

function hue(s) {
  let h = 7;
  for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}
function initials(label) {
  const words = String(label).replace(/[()]/g, "").split(/[\s\-_.]+/).filter(Boolean);
  return ((words[0]?.[0] || "?") + (words[1]?.[0] || "")).toUpperCase();
}
export { hue, initials };
