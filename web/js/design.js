// Design first: the card where you pick one of the agent's design options (A, B, C…), the recap of a
// finished pick, and the full-size viewer. Each screen is a self-contained HTML mockup the agent wrote
// under <project>/.afh/designs/; it shows live in a sandboxed frame (no access to AFH) inside a device
// frame sized for its screen type. The engine side is afh/engine/design.py.

import { api } from "./api.js";
import { el, ico, toast } from "./ui.js";

const DEVICE_NAMES = { phone: "Phone", tablet: "Tablet", desktop: "Desktop", laptop: "Laptop", window: "App window", watch: "Watch", tv: "TV" };
const PLATFORM_NAMES = { web: "Web", android: "Android", ios: "iOS", windows: "Windows", macos: "macOS", linux: "Linux", "cross-platform": "Cross-platform", other: "" };
const cache = new Map(); // path -> Promise<html>

const load = (path) => {
  if (!cache.has(path)) cache.set(path, api.get(`/api/design/file?path=${encodeURIComponent(path)}`).then((r) => r.html || "").catch(() => { cache.delete(path); return null; }));
  return cache.get(path);
};

/** Hooks main.js fills in: openInBrowser(url) when the browser panel exists. */
export const designHooks = { openInBrowser: null };

/** A live mockup in its device frame, scaled to fit maxW × maxH. `interactive` lets you click inside it. */
function frame(screen, platform, maxW, maxH, { interactive = false } = {}) {
  const w = screen.width;
  const h = screen.height;
  const s = Math.min(maxW / w, maxH / h, 1);
  const iframe = el("iframe", { sandbox: "allow-scripts", referrerpolicy: "no-referrer", loading: "lazy", tabindex: interactive ? "0" : "-1",
    style: { width: `${w}px`, height: `${h}px`, transform: `scale(${s})`, pointerEvents: interactive ? "auto" : "none" } });
  const screenBox = el("div.dv-screen", { style: { width: `${Math.round(w * s)}px`, height: `${Math.round(h * s)}px` } }, iframe);
  load(screen.path).then((html) => {
    if (html == null) screenBox.replaceChildren(el("div.dv-missing", ico("alert"), "This mockup file is gone"));
    else iframe.srcdoc = html;
  });
  const kind = `${screen.device}${platform === "ios" || platform === "macos" ? ".ios" : platform === "android" ? ".android" : ""}`;
  const chrome = screen.device === "desktop" || screen.device === "laptop"
    ? el("div.dv-bar", el("i"), el("i"), el("i"), el("span.dv-url", screen.name))
    : null;
  return el(`div.dv.dv-${kind.replace(".", ".dv-")}${interactive ? ".live" : ""}`, chrome, screenBox);
}

function screenList(option, platform, onOpen, { maxW = 260, maxH = Math.max(200, Math.min(270, innerHeight * 0.3)) } = {}) {
  return el("div.d-screens", option.screens.map((sc, i) => {
    const big = sc.device === "desktop" || sc.device === "laptop" || sc.device === "tv" || sc.device === "window";
    return el("figure.d-shot", { title: "Open full size", on: { click: () => onOpen(option.letter, i) } },
      frame(sc, platform, big ? maxW * 1.55 : maxW, maxH),
      el("figcaption", el("b", sc.name), el("span", DEVICE_NAMES[sc.device] || sc.device)));
  }));
}

// The card shows the letter itself; threads saved before 1.16 may still have it in the name ("A — Calm").
const nameOf = (o) => o.name.replace(/^(?:option\s+)?[A-D]\s*[—–:.)\-]\s*/i, "") || o.name;

const subtitle = (d) => [d.title, PLATFORM_NAMES[d.platform]].filter(Boolean).join(" · ");

/** The agent is waiting for you to choose: options as tabs, their screens live, notes, Choose / New options / Skip. */
export function designCard(p, sid, onDone) {
  const d = p.metadata.design;
  let pick = d.options[0].letter;
  let mode = "option"; // or "compare"
  let at = 0; // the screen compared across options
  const card = el("div.approval.dcard");
  const notes = el("textarea.q-other.d-notes", { rows: 1, placeholder: "Notes or a mix, e.g. \"A's colours with B's layout, bigger buttons\"",
    on: { input: (e) => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; draw(false); } } });
  const send = async (decision, answer) => {
    card.querySelectorAll("button, textarea").forEach((b) => (b.disabled = true));
    try {
      await api.post(`/api/sessions/${sid}/permissions/${p.id}`, { decision, answers: answer ? [answer] : undefined });
      onDone?.(p.id);
    } catch (e) {
      toast(e.message, "err");
      card.querySelectorAll("button, textarea").forEach((b) => (b.disabled = false));
    }
  };
  const choose = (letter) => send("answer", { choice: letter, notes: notes.value.trim() });
  const open = (letter, i) => openViewer(d, letter, i, { onChoose: (letter2) => { pick = letter2; choose(letter2); } });
  const body = el("div.d-body");
  const tabs = el("div.d-tabs");
  const actions = el("div.approval-actions");
  const draw = (full = true) => {
    const option = d.options.find((o) => o.letter === pick);
    tabs.replaceChildren(
      ...d.options.map((o) => el(`button.d-tab${mode === "option" && o.letter === pick ? ".on" : ""}`, { type: "button", on: { click: () => { mode = "option"; pick = o.letter; draw(); } } },
        el("span.d-letter", o.letter), el("span.d-name", nameOf(o)))),
      el("span.spacer"),
      el(`button.d-tab.d-compare${mode === "compare" ? ".on" : ""}`, { type: "button", title: "The same screen in every option, side by side", on: { click: () => { mode = "compare"; draw(); } } }, ico("list"), "Compare"));
    if (full) {
      if (mode === "option") {
        body.replaceChildren(option.summary ? el("p.d-summary", option.summary) : null, screenList(option, d.platform, open));
      } else {
        const names = d.options[0].screens.map((s) => s.name);
        at = Math.min(at, names.length - 1);
        body.replaceChildren(
          el("div.d-chips", names.map((n, i) => el(`button.d-chip${i === at ? ".on" : ""}`, { type: "button", on: { click: () => { at = i; draw(); } } }, n))),
          el("div.d-compare-row", d.options.map((o) => {
            const sc = o.screens.find((x) => x.name === names[at]) || o.screens[Math.min(at, o.screens.length - 1)];
            const i = o.screens.indexOf(sc);
            return el(`figure.d-shot.d-col${o.letter === pick ? ".picked" : ""}`, { on: { click: () => { pick = o.letter; draw(); } }, title: `Option ${o.letter}` },
              frame(sc, d.platform, sc.device === "phone" || sc.device === "watch" ? 230 : 330, 300),
              el("figcaption", el("b", `${o.letter} · ${nameOf(o)}`),
                el("button.btn.ghost.sm", { type: "button", on: { click: (e) => { e.stopPropagation(); open(o.letter, i); } } }, "Full size")));
          })));
      }
    }
    actions.replaceChildren(
      el("button.btn.ghost.sm", { type: "button", title: "Close without choosing; the agent goes with the option it thinks fits best", on: { click: () => send("dismiss") } }, "Skip"),
      el("span.spacer"),
      el("button.btn.sm", { type: "button", title: "None of these: the agent makes new options (say what to change in the notes)", on: { click: () => send("answer", { choice: "", notes: notes.value.trim() }) } }, ico("refresh"), "New options"),
      el("button.btn.primary.sm", { type: "button", on: { click: () => choose(pick) } }, ico("check"), notes.value.trim() ? `Choose ${pick} with notes` : `Choose ${pick}`));
  };
  card.append(
    el("div.approval-head", ico("sparkle"),
      el("div", el("div", "Choose a design"), el("div.approval-sub", `${subtitle(d)} — click a screen to see it full size and try it`))),
    tabs, body, el("div.d-notes-row", notes), actions);
  draw();
  return card;
}

/** A finished `design` call in the thread: which option won, with its screens. */
export function renderDesignTool(p) {
  const meta = p.state?.metadata || {};
  const status = p.state?.status || "streaming";
  const d = meta.design;
  if (!d || status === "streaming" || status === "running") return null; // still open: the card below the thread handles it
  const choice = meta.answer?.choice;
  const option = d.options.find((o) => o.letter === choice);
  const head = meta.dismissed ? "Design options — skipped" : option ? `Design ${option.letter} chosen: ${nameOf(option)}` : "Asked for new design options";
  const note = meta.answer?.notes;
  return el(`div.q-recap.d-recap${option ? "" : ".skipped"}`, { dataset: { tool: p.id } },
    el("div.q-recap-head", ico("sparkle"), el("b", head), el("span.d-recap-sub", subtitle(d)),
      el("button.btn.ghost.sm", { type: "button", on: { click: () => openViewer(d, choice || d.options[0].letter, 0) } }, "View all")),
    note ? el("div.d-recap-note", `“${note}”`) : null,
    screenList(option || d.options[0], d.platform, (letter, i) => openViewer(d, letter, i), { maxW: 150, maxH: 180 }));
}

/** Full size: one screen at a time, live and clickable, with option tabs and the screens of that option. */
export function openViewer(d, letter, index, { onChoose } = {}) {
  let pick = letter;
  let at = index;
  const stage = el("div.dview-stage");
  const top = el("div.dview-top");
  const scrim = el("div.dview", top, stage);
  const close = () => {
    scrim.remove();
    removeEventListener("keydown", onKey);
    removeEventListener("resize", draw);
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    const o = d.options.find((x) => x.letter === pick);
    if (e.key === "ArrowRight" && at < o.screens.length - 1) { at++; draw(); }
    if (e.key === "ArrowLeft" && at > 0) { at--; draw(); }
  };
  function draw() {
    const o = d.options.find((x) => x.letter === pick);
    at = Math.min(at, o.screens.length - 1);
    const sc = o.screens[at];
    top.replaceChildren(
      el("div.dview-tabs", d.options.map((x) => el(`button.d-tab${x.letter === pick ? ".on" : ""}`, { type: "button", on: { click: () => { pick = x.letter; draw(); } } },
        el("span.d-letter", x.letter), el("span.d-name", nameOf(x))))),
      el("div.d-chips", o.screens.map((s, i) => el(`button.d-chip${i === at ? ".on" : ""}`, { type: "button", on: { click: () => { at = i; draw(); } } }, s.name))),
      el("span.spacer"),
      designHooks.openInBrowser ? el("button.btn.sm", { type: "button", title: "Open this mockup in the browser panel", on: { click: () => { designHooks.openInBrowser(fileUrl(sc.path)); close(); } } }, ico("globe"), "Open in browser") : null,
      onChoose ? el("button.btn.primary.sm", { type: "button", on: { click: () => { close(); onChoose(pick); } } }, ico("check"), `Choose ${pick}`) : null,
      el("button.icon-btn", { type: "button", title: "Close (Esc)", on: { click: close } }, ico("x")));
    const room = stage.getBoundingClientRect();
    stage.replaceChildren(frame(sc, d.platform, Math.max(200, room.width - 64), Math.max(200, room.height - 64), { interactive: true }),
      el("div.dview-cap", `${o.letter} · ${nameOf(o)} — ${sc.name} · ${DEVICE_NAMES[sc.device] || sc.device} ${sc.width}×${sc.height}`));
  }
  document.getElementById("overlay-root").append(scrim);
  addEventListener("keydown", onKey);
  addEventListener("resize", draw);
  requestAnimationFrame(draw);
}

const fileUrl = (path) => "file:///" + String(path).replace(/\\/g, "/").replace(/^\/+/, "").split("/").map(encodeURIComponent).join("/").replace(/^([A-Za-z])%3A/, "$1:");
