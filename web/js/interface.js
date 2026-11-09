// Interfaces (Settings → Appearance → Interface). Studio, The Harness and Paper share every feature;
// interfaces.css restyles the app per <html data-ui>, and each interface has its own themes
// (appearance.js INTERFACE_LOOKS). This module adds the two pieces of structure CSS can't make on its
// own: Paper's document head and the port in the composer where The Harness strand lands.

import { ago, el } from "./ui.js";
import { logoNode, setWorking } from "./logo.js";

let A = null; // the app's state and actions, handed over by initInterface()

export const uiName = () => document.documentElement.dataset.ui || "studio";

// ---- Paper: the thread as a document — a title and a row of facts above the conversation ----------

export function docHead(t) {
  if (!A || !t) return null;
  const head = el("header.doc-head");
  fillDocHead(head, t);
  return head;
}

function fillDocHead(head, t) {
  const m = A.meta(t);
  const h = el("h1.doc-title", { title: "Click to rename" }, t.session.title || "New thread");
  h.addEventListener("click", () => {
    const input = el("input.doc-title-input", { value: t.session.title || "", "aria-label": "Thread title" });
    let finished = false;
    const done = async (save) => {
      if (finished) return;
      finished = true;
      const v = input.value.trim();
      if (save && v && v !== t.session.title) await A.rename(v);
      else refreshDocHead();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    input.addEventListener("blur", () => done(true));
    h.replaceWith(input);
    input.focus();
    input.select();
  });
  const started = t.session.time?.created;
  head.replaceChildren(h, el("div.doc-meta",
    m.agent ? el("span", m.agent) : null,
    m.mode ? el(`span${m.modeKey === "full" ? ".acc" : ""}`, m.mode) : null,
    m.model ? el("span", m.model) : null,
    started ? el("span", `started ${ago(started)}`) : null,
    m.changes ? el("button.doc-chip", { type: "button", on: { click: () => A.openChanges() } }, `Changes · ${m.changes} file${m.changes === 1 ? "" : "s"}`) : null));
}

/** Title, model or changes moved: redraw the head in place. */
export function refreshDocHead() {
  const head = document.querySelector("#messages > .doc-head");
  const t = A?.S.current;
  if (head && t && !head.contains(document.activeElement)) fillDocHead(head, t); // never while you rename it
}

// ---- The Harness: the port in the composer where the strand lands ---------------------------------

function mountPort() {
  const box = document.getElementById("composer");
  if (!box || box.querySelector(".ui-port")) return;
  box.prepend(el("span.ui-port", { "aria-hidden": "true" }, logoNode({ size: 22 })));
}

export function setPortWorking(on) {
  setWorking(document.querySelector("#composer .ui-port"), on);
}

// ---- switching ------------------------------------------------------------------------------------

/** `app`: S, meta(t), rename(title), openChanges(), redraw(). */
export function initInterface(app) {
  A = app;
  mountPort();
  addEventListener("afh-interface", () => A.redraw());
}
