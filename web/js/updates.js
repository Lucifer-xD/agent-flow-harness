// App updates (desktop app only; see desktop/main.js): a "Restart to update" pill once a new
// version has downloaded, and the Updates card in Settings → About.

import { el, ico, icon, toast, toggle } from "./ui.js";

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

async function install() {
  if (!(await U.install())) toast("The update isn't ready yet", "info");
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
  const feed = el("input.inp", { value: u.feed || "", placeholder: "https://agenflowharness.com/downloads/ (default)", style: { width: "320px" } });
  feed.addEventListener("change", () => save({ updates: { feed: feed.value.trim() } }, "Saved"));
  return card("Updates", "AFH checks for a new version every few hours, downloads it in the background and asks before restarting. Quitting also installs a downloaded update.", null,
    row("Status", null, el("div.inline", status, action)),
    row("Download updates automatically", "Off: AFH only tells you when one is available", toggle(u.auto !== false, (v) => save({ updates: { auto: v } }))),
    row("Update address", "The web folder holding latest.yml and the installer. Leave empty for the AFH website", feed));
}
