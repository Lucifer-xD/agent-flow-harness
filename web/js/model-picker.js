// The model picker: your providers down the side, their models beside them, one search across all.
// Used by the message box (choose the thread's model) and by Settings (choose the default model).

import { closePopover, el, fmtTokens, ico, icon, modalityBadges, popover, slidePills } from "./ui.js";

const RECENT_KEY = "afh-recent-models";
const same = (a, b) => !!a && !!b && a.id === b.id && a.providerID === b.providerID;

function recent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; }
}
/** Remember a picked model so it shows under Recent next time. */
export function rememberModel(ref) {
  if (!ref?.id) return;
  const list = [{ id: ref.id, providerID: ref.providerID }, ...recent().filter((r) => !same(r, ref))].slice(0, 6);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* private window */ }
}

/** A short line of facts about a model: context, effort levels, what it can't do. */
export function modelFacts(m) {
  return [m.context ? `${fmtTokens(m.context)} context` : null, m.variants?.length ? `effort ${m.variants.join(" · ")}` : null, m.tools === false ? "no tools" : null].filter(Boolean).join("  ·  ");
}

/**
 * opts: {models, current, providerName(pid), onPick(ref), onManage(), onAdd(), align, title}
 * `current` may carry a variant (effort); picking another model drops it.
 */
export function modelPicker(anchor, opts) {
  const models = opts.models || [];
  const name = opts.providerName || ((pid) => pid);
  let current = opts.current || null;
  const groups = new Map();
  for (const m of models) {
    if (!groups.has(m.providerID)) groups.set(m.providerID, []);
    groups.get(m.providerID).push(m);
  }
  const multi = groups.size > 1;
  let scope = current && groups.has(current.providerID) ? current.providerID : multi ? "all" : [...groups.keys()][0] || "all";
  let query = "";
  let kb = 0;
  let rows = [];

  const input = el("input.mp-q", { placeholder: opts.placeholder || "Search models", spellcheck: false, autocomplete: "off", "aria-label": "Search models" });
  const rail = el("div.mp-rail", { hidden: !multi });
  const list = el("div.mp-list", { role: "listbox" });
  const foot = el("div.mp-foot");
  const box = el("div.mp", el("div.mp-head", ico("search"), input, el("span.mp-hint", `${models.length} model${models.length === 1 ? "" : "s"}`)),
    el(`div.mp-cols${multi ? "" : ".single"}`, rail, list), foot);

  const matches = (m) => {
    if (!query) return true;
    const hay = `${m.name} ${m.id} ${name(m.providerID)}`.toLowerCase();
    return query.split(/\s+/).every((w) => hay.includes(w));
  };

  const drawRail = () => {
    const count = (pid) => (pid === "all" ? models : groups.get(pid) || []).filter(matches).length;
    const item = (pid, label, ic) => {
      const n = count(pid);
      return el(`button.mp-prov${scope === pid ? ".on" : ""}${n ? "" : ".none"}${current?.providerID === pid ? ".has" : ""}`, { type: "button", title: label, on: { click: () => { scope = pid; draw(); input.focus(); } } },
        ic ? ico(ic) : el("span.mp-mono", { style: { "--h": String(hue(pid)) } }, initials(label)),
        el("span.mp-prov-name", label), el("span.mp-count", String(n)));
    };
    rail.replaceChildren(item("all", "All models", "list"), el("div.mp-rail-sep"),
      ...[...groups.keys()].map((pid) => item(pid, name(pid))),
      opts.onAdd ? el("button.mp-add", { type: "button", on: { click: () => { closePopover(); opts.onAdd(); } } }, ico("plus"), el("span", "Add a provider")) : null);
  };

  const row = (m, showProvider) => {
    const on = same(m, current);
    const b = el(`button.mp-row${on ? ".on" : ""}`, { type: "button", role: "option", "aria-selected": String(on), on: {
      click: () => pick(m), mouseenter: () => { kb = rows.indexOf(b); mark(); } } },
      el("span.mp-check", on ? { html: icon("check") } : null),
      el("span.mp-main",
        el("span.mp-name", el("span.mp-name-t", m.name), modalityBadges(m.input), m.reasoning ? el("span.mp-tag", "thinks") : null, m.tools === false ? el("span.mp-tag.warn", "no tools") : null),
        el("span.mp-sub", [showProvider ? name(m.providerID) : null, m.id !== m.name ? m.id : null].filter(Boolean).join("  ·  "))),
      el("span.mp-meta", m.context ? el("span.mp-ctx", fmtTokens(m.context)) : null, m.variants?.length ? el("span.mp-eff", { title: `Effort: default, ${m.variants.join(", ")}` }, ico("sliders")) : null));
    rows.push(b);
    return b;
  };

  const drawList = () => {
    rows = [];
    const parts = [];
    if (scope === "all" && !query) {
      const rec = recent().map((r) => models.find((m) => same(m, r))).filter(Boolean).slice(0, 4);
      if (rec.length && multi) parts.push(el("div.mp-group", ico("clock"), "Recent"), ...rec.map((m) => row(m, true)));
      for (const [pid, ms] of groups) parts.push(el("div.mp-group", name(pid), el("span", String(ms.length))), ...ms.map((m) => row(m, false)));
    } else {
      const pool = (scope === "all" ? models : groups.get(scope) || []).filter(matches);
      if (scope !== "all" && multi && !query) parts.push(el("div.mp-group", name(scope), el("span", `${pool.length}`)));
      parts.push(...pool.map((m) => row(m, scope === "all" || !!query)));
      if (!pool.length) {
        const elsewhere = query && scope !== "all" ? models.filter(matches).length : 0;
        parts.push(el("div.mp-empty", query ? `No model here matches “${query}”.` : "No models yet.",
          elsewhere ? el("button.btn.ghost.sm", { type: "button", on: { click: () => { scope = "all"; draw(); input.focus(); } } }, `Search all providers (${elsewhere})`) : null));
      }
    }
    list.replaceChildren(...parts);
    kb = Math.max(0, rows.findIndex((r) => r.classList.contains("on")));
    if (query) kb = 0;
    mark(true);
  };

  const mark = (scrollToIt) => {
    rows.forEach((r, i) => r.classList.toggle("kb", i === kb));
    if (scrollToIt && rows[kb]) rows[kb].scrollIntoView({ block: "nearest" });
  };

  const drawFoot = () => {
    const m = current && models.find((x) => same(x, current));
    const parts = [];
    if (m?.variants?.length) {
      const seg = el("div.seg.mp-seg");
      for (const v of ["default", ...m.variants.filter((x) => x !== "default")]) {
        seg.append(el(`button${(current.variant || "default") === v ? ".on" : ""}`, { type: "button", on: { click: (e) => {
          seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === e.currentTarget));
          current = { ...current, variant: v === "default" ? undefined : v };
          opts.onPick?.(current, { effortOnly: true });
        } } }, v));
      }
      parts.push(el("span.mp-foot-label", "Effort"), seg);
    } else if (m) {
      parts.push(el("span.mp-foot-now", ico("cpu"), el("span", el("b", m.name), ` · ${name(m.providerID)}`)));
    }
    parts.push(el("span.mp-grow"));
    if (opts.onManage) parts.push(el("button.mp-link", { type: "button", on: { click: () => { closePopover(); opts.onManage(); } } }, ico("sliders"), "Manage models"));
    foot.replaceChildren(...parts);
    slidePills(foot);
  };

  const draw = () => { drawRail(); drawList(); };
  const pick = (m) => {
    const ref = { id: m.id, providerID: m.providerID };
    rememberModel(ref);
    closePopover();
    opts.onPick?.(ref, {});
  };

  input.addEventListener("input", () => {
    query = input.value.trim().toLowerCase();
    if (query && scope !== "all" && !(groups.get(scope) || []).some(matches)) scope = "all";
    draw();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      kb = Math.max(0, Math.min(rows.length - 1, kb + (e.key === "ArrowDown" ? 1 : -1)));
      mark(true);
    } else if (e.key === "Enter") {
      e.preventDefault();
      rows[kb]?.click();
    } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !input.value && multi) {
      e.preventDefault();
      const order = ["all", ...groups.keys()];
      const i = order.indexOf(scope) + (e.key === "ArrowRight" ? 1 : -1);
      scope = order[(i + order.length) % order.length];
      draw();
    }
  });

  draw();
  drawFoot();
  const width = Math.min(multi ? 620 : 420, innerWidth - 20);
  popover(anchor, [], { header: box, width, align: opts.align || "right", className: `mp-pop${multi ? "" : " single"}` });
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
