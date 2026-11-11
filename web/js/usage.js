// The usage meter by the message box: the current provider's plan limits, live. ChatGPT shows its
// 5-hour and weekly windows, Copilot its monthly premium requests, Antigravity the quota left per
// model family, coding plans (Kimi, Z.AI) their 5-hour and weekly windows, OpenRouter, DeepSeek and
// Moonshot their balance; any other API key shows the rate limits from its last answer and what AFH
// sent through it. Click for the details and every other provider. Data: GET /api/usage/limits.

import { api } from "./api.js";
import { providerMark } from "./model-picker.js";
import { el, fmtTokens, ico, popover, repositionPopover } from "./ui.js";

const POLL = 60_000; // the server caches live answers for as long
const AFTER_RUN_GAP = 20_000;

const U = { pid: null, reports: new Map(), loading: new Set(), lastForced: 0, names: () => ({}), open: false };

const level = (p) => (p >= 90 ? "bad" : p >= 70 ? "warn" : "ok");

function untilText(ms) {
  if (!ms) return "";
  const s = Math.round((ms - Date.now()) / 1000);
  if (s <= 0) return "resets now";
  if (s < 3600) return `resets in ${Math.max(1, Math.round(s / 60))}m`;
  if (s < 48 * 3600) return `resets in ${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
  return `resets ${new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

function agoText(ms) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  return s < 10 ? "just now" : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
}

const money = (b) => (b.currency === "USD" ? `$${b.amount.toFixed(2)}` : b.currency === "credits" ? `${Math.round(b.amount)} credits` : `${b.amount.toFixed(2)} ${b.currency}`);
const windowsOf = (r) => (r?.windows || []).filter((w) => w.usedPercent != null);

/** The one or two numbers that matter most, for the chip. */
function headline(r) {
  const ws = windowsOf(r);
  if (ws.length) {
    const top = ws.reduce((a, b) => (b.usedPercent > a.usedPercent ? b : a));
    return { kind: "bars", bars: ws.slice(0, 2), pct: top.usedPercent, text: `${Math.round(top.usedPercent)}%`,
      title: ws.map((w) => `${w.label}: ${Math.round(w.usedPercent)}% used${w.resetsAt ? `, ${untilText(w.resetsAt)}` : ""}`).join("\n") };
  }
  if (r?.balance) return { kind: "text", text: money(r.balance), title: `Balance: ${money(r.balance)}` };
  if (r?.rates?.length) {
    const top = r.rates.reduce((a, b) => (b.usedPercent > a.usedPercent ? b : a));
    return { kind: "bars", bars: [top], pct: top.usedPercent, text: `${Math.round(top.usedPercent)}%`, title: `${top.label} rate limit: ${Math.round(top.usedPercent)}% used` };
  }
  const l = r?.local?.["5h"];
  if (l?.steps) return { kind: "text", text: fmtTokens(l.tokens), title: `AFH sent ${fmtTokens(l.tokens)} tokens through this provider in the last 5 hours` };
  return null;
}

function chip() {
  const box = document.getElementById("usage-meter");
  if (!box) return;
  const r = U.reports.get(U.pid);
  const h = headline(r);
  if (!U.pid || !h) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.title = `${h.title}\nClick for usage details`;
  box.className = `usage-chip ${h.pct != null ? level(h.pct) : ""}${r?.limited ? " limited" : ""}`;
  const parts = [];
  if (h.kind === "bars") parts.push(el("span.um-bars", h.bars.map((w) => el("i", el("b", { className: level(w.usedPercent), style: { width: `${Math.min(100, w.usedPercent)}%` } })))));
  parts.push(el("span.um-txt", h.text));
  box.replaceChildren(...parts);
}

async function load(pid, force = false) {
  if (!pid || U.loading.has(pid)) return;
  U.loading.add(pid);
  try {
    U.reports.set(pid, await api.get(`/api/usage/limits?provider=${encodeURIComponent(pid)}${force ? "&force=true" : ""}`));
  } catch {
    /* the meter just stays as it was */
  } finally {
    U.loading.delete(pid);
  }
  if (pid === U.pid) chip();
}

/** Call on every render: switches the meter to the current model's provider. */
export function renderUsage(ref) {
  const pid = ref?.providerID || null;
  if (pid !== U.pid) {
    U.pid = pid;
    chip();
    if (pid && !U.reports.has(pid)) load(pid);
    else if (pid) load(pid);
  } else chip();
}

/** After a run: the plan's numbers have moved. */
export function refreshUsage() {
  if (!U.pid || Date.now() - U.lastForced < AFTER_RUN_GAP) return load(U.pid);
  U.lastForced = Date.now();
  return load(U.pid, true);
}

// ---- the popover ---------------------------------------------------------------------------------

function bar(pct) {
  return el("div.um-bar", el("i", { className: level(pct), style: { width: `${Math.min(100, pct)}%` } }));
}

function detail(r) {
  const out = [];
  const ws = windowsOf(r);
  for (const w of ws) {
    const amount = w.limit != null && w.used != null ? ` · ${fmtNum(w.used)} of ${fmtNum(w.limit)}${w.unit ? ` ${w.unit}` : ""}` : "";
    out.push(el("div.um-win", el("div.um-row", el("b", w.label), el("span", `${Math.round(w.usedPercent)}% used`)), bar(w.usedPercent),
      el("div.um-sub", `${untilText(w.resetsAt) || "no reset time given"}${amount}`)));
  }
  if (r.limited) out.push(el("div.um-note.bad", "Limit reached — requests fail until the window resets."));
  if (r.balance) out.push(el("div.um-row", el("b", "Balance"), el("span", money(r.balance))));
  if (r.spend && Object.keys(r.spend).length) {
    out.push(el("div.um-row", el("b", "Spent"), el("span", ["daily", "weekly", "monthly"].filter((k) => r.spend[k] != null).map((k) => `$${Number(r.spend[k]).toFixed(2)} ${k === "daily" ? "today" : k === "weekly" ? "this week" : "this month"}`).join(" · "))));
  }
  for (const x of r.rates || []) {
    out.push(el("div.um-win", el("div.um-row", el("b", `${x.label} rate limit`), el("span", `${fmtNum(x.remaining)} of ${fmtNum(x.limit)} left`)), bar(x.usedPercent),
      el("div.um-sub", untilText(x.resetsAt) || "")));
  }
  const l = r.local;
  if (l) {
    const line = (b) => (b.steps ? `${b.steps} step${b.steps === 1 ? "" : "s"} · ${fmtTokens(b.tokens)} tokens${b.cost ? ` · $${b.cost.toFixed(2)}` : ""}` : "nothing yet");
    out.push(el("div.um-local", el("div.um-head", "Sent by AFH"), el("div.um-row", el("span", "Last 5 hours"), el("span", line(l["5h"]))), el("div.um-row", el("span", "Last 7 days"), el("span", line(l.week)))));
  }
  const src = r.error && !ws.length ? `Couldn't read the plan's usage: ${r.error}`
    : r.source === "live" ? `Live from ${r.name} · updated ${agoText(r.updated)}`
    : r.source === "headers" ? `From ${r.name}'s last answer · ${agoText(r.ratesAt || r.updated)}`
    : r.rates?.length ? `Rate limits from the last answer · ${agoText(r.ratesAt || r.updated)}`
    : `${r.name} doesn't publish plan limits; this is what AFH tracked`;
  out.push(el("div.um-source", src));
  return out;
}

const fmtNum = (n) => (n >= 10_000 ? fmtTokens(n) : Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 }));

export async function usagePopover(anchor, pid = U.pid) {
  if (!pid) return;
  const body = el("div.um-pop");
  const draw = () => {
    const r = U.reports.get(pid);
    const head = el("div.um-title", providerMark(pid, r?.name || U.names()[pid] || pid, 18), el("b", r?.name || U.names()[pid] || pid), r?.account ? el("span.um-acct", r.account) : null, r?.plan ? el("span.um-plan", r.plan) : null,
      el("button.icon-btn", { title: "Refresh", type: "button", on: { click: async (e) => { e.stopPropagation(); body.classList.add("loading"); await load(pid, true); body.classList.remove("loading"); draw(); } } }, ico("refresh")));
    const others = [...U.reports.values()].filter((x) => x.providerID !== pid);
    body.replaceChildren(head, ...(r ? detail(r) : [el("div.empty-row", el("span.spinner"))]),
      others.length ? el("div.um-others", el("div.um-head", "Other providers"), ...others.map((o) => {
        const h = headline(o);
        return el("button.um-other", { type: "button", on: { click: (e) => { e.stopPropagation(); pid = o.providerID; draw(); if (!U.loading.has(pid)) load(pid).then(draw); } } },
          el("span.um-other-name", providerMark(o.providerID, o.name, 16), o.name), h ? el("span", { className: `um-other-val ${h.pct != null ? level(h.pct) : ""}` }, h.text) : el("span.um-other-val.muted", "—"));
      })) : null);
    repositionPopover?.();
  };
  popover(anchor, [], { header: body, width: 330, align: "right" });
  draw();
  await load(pid, false);
  draw();
  // fill "Other providers" in the background
  api.get("/api/usage/limits").then((all) => {
    for (const r of all.providers || []) if (!U.reports.has(r.providerID) || r.providerID !== U.pid) U.reports.set(r.providerID, r);
    if (document.body.contains(body)) draw();
  }).catch(() => {});
}

export function initUsage({ names } = {}) {
  if (names) U.names = names;
  const box = document.getElementById("usage-meter");
  box?.addEventListener("click", () => usagePopover(box));
  setInterval(() => { if (document.visibilityState === "visible" && U.pid) load(U.pid); }, POLL);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && U.pid) load(U.pid); });
}
