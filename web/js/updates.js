// App updates (desktop app only; see desktop/main.js): a "Restart to update" pill once a new
// version has downloaded, and the Updates card in Settings → About.

import { api } from "./api.js";
import { el, ico, icon, modal, toast, toggle } from "./ui.js";

const U = window.afh?.updates;
const listeners = new Set();
let current = null;
let pill = null;

export function initUpdates() {
  if (!U) return;
  window.afh.onEvent((ev) => { if (ev?.type === "update") apply(ev.update); });
  U.state().then(apply).catch(() => {});
}

function apply(s) {
  current = s;
  for (const fn of listeners) fn(s);
  renderPill();
}

function renderPill() {
  if (current?.state !== "ready") {
    pill?.remove();
    pill = null;
    return;
  }
  if (pill) return;
  pill = el("div.update-pill", ico("download"), el("span", `AFH ${current.version} is ready`),
    el("button.btn.primary.sm", { type: "button", on: { click: install } }, "Restart to update"),
    el("button.icon-btn", { type: "button", title: "Later — it installs when you quit", html: icon("x"), on: { click: () => pill?.classList.add("hidden") } }));
  document.body.append(pill);
}

let waiting = null; // a restart held until the running threads finish

/** Threads with a run going right now (restarting would cut them off). */
async function runningThreads() {
  try {
    return (await api.get("/api/sessions?limit=500")).filter((s) => s.running).length;
  } catch {
    return 0;
  }
}

async function install() {
  const n = await runningThreads();
  if (n && !(await askWhenToRestart(n))) return;
  if (!(await U.install())) toast("The update isn't ready yet", "info");
}

function askWhenToRestart(n) {
  // true = restart now; "later" holds the restart until every run has ended; false = not now
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; m.close(); if (v === "later") holdRestart(); resolve(v === true); } };
    const words = n === 1 ? "A thread is still working" : `${n} threads are still working`;
    const m = modal(
      el("div.m-body", { style: { padding: "22px 24px" } },
        el("h2", words),
        el("p.lead", { style: { marginBottom: "18px" } }, "Restarting now stops their work halfway. AFH can wait and restart by itself the moment they finish."),
        el("div.actions",
          el("button.btn.ghost", { on: { click: () => finish(false) } }, "Cancel"),
          el("button.btn", { on: { click: () => finish(true) } }, "Restart now"),
          el("button.btn.primary", { on: { click: () => finish("later") } }, "Restart when they finish"))),
      { small: true, onClose: () => { if (!done) { done = true; resolve(false); } } });
  });
}

function holdRestart() {
  if (waiting) return;
  const label = pill?.querySelector("span");
  if (label) label.textContent = `AFH ${current?.version || ""} installs when the running threads finish`;
  toast("AFH will restart to update when the running threads finish", "info");
  waiting = setInterval(async () => {
    if (await runningThreads()) return;
    clearInterval(waiting);
    waiting = null;
    if (!(await U.install())) toast("The update isn't ready yet", "info");
  }, 5000);
}

function describe(s) {
  switch (s?.state) {
    case "checking": return "Checking for a new version…";
    case "latest": return `You have the latest version (${s.current})`;
    case "available": return `Version ${s.version} is available`;
    case "downloading": return `Downloading ${s.version}… ${s.progress || 0}%`;
    case "ready": return `Version ${s.version} is downloaded and ready`;
    case "nofeed": return "Set the update address below to get updates";
    case "error": return `Couldn't check: ${s.error}`;
    case "dev": return "Development run — updates are off";
    case "unsupported": return "Updates aren't available in this build";
    default: return `Version ${s?.current || ""}`;
  }
}

/** The Updates card for Settings → About. `save(patch, message)` saves AFH settings. */
export function updatesCard({ card, row, settings, save }) {
  if (!U) return card("Updates", "Updates come with the desktop app. In a browser window, update the app on the computer it runs on.", null);
  const u = settings.updates || {};
  const status = el("span.update-status");
  const action = el("span");
  let shown = false;
  const paint = (s) => {
    if (status.isConnected) shown = true;
    else if (shown) return listeners.delete(paint); // the settings pane was closed
    status.textContent = describe(s);
    status.className = `update-status ${s?.state || ""}`;
    const btn = (label, ic, fn) => el("button.btn.sm", { type: "button", on: { click: fn } }, ico(ic), label);
    action.replaceChildren(
      s?.state === "available" ? btn("Download", "download", () => U.download())
        : s?.state === "ready" ? el("button.btn.primary.sm", { type: "button", on: { click: install } }, "Restart to update")
          : ["checking", "downloading", "dev", "unsupported"].includes(s?.state) ? ""
            : btn("Check now", "refresh", () => U.check().then(apply)));
  };
  listeners.add(paint);
  paint(current);
  const feed = el("input.inp", { value: u.feed || "", placeholder: "https://agentflowharness.com/downloads/ (default)", style: { width: "320px" } });
  feed.addEventListener("change", () => save({ updates: { feed: feed.value.trim() } }, "Saved"));
  return card("Updates", "AFH checks for a new version every few hours, downloads it in the background and asks before restarting. Quitting also installs a downloaded update.", null,
    row("Status", null, el("div.inline", status, action)),
    row("Download updates automatically", "Off: AFH only tells you when one is available", toggle(u.auto !== false, (v) => save({ updates: { auto: v } }))),
    row("Update address", "The web folder holding latest.yml and the installer. Leave empty for the AFH website", feed));
}
