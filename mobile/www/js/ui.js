// Small helpers shared by the screens: element builder, toasts, sheets, time and markdown.

/**
 * h("ion-button.grad", { expand: "block", on: { click } , props: { disabled: true } }, "Sign in")
 * Attributes are set as attributes, `props` as element properties (what Ionic components read),
 * `on` as event listeners.
 */
export function h(tag, attrs, ...kids) {
  const [name, ...classes] = tag.split(".");
  const node = document.createElement(name);
  if (classes.length) node.className = classes.join(" ");
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    kids.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
    else if (k === "props") Object.assign(node, v);
    else if (k === "html") node.innerHTML = v;
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) node.append(kid);
  return node;
}

export const icon = (name, attrs = {}) => h("ion-icon", { src: `vendor/ionic/svg/${name}.svg`, "aria-hidden": "true", ...attrs });

export async function toast(message, color = "medium", duration = 2600) {
  const t = h("ion-toast", { props: { message, duration, color, position: "top", cssClass: "afh-toast" } });
  document.body.append(t);
  await t.present();
  t.addEventListener("didDismiss", () => t.remove());
}

export async function confirmSheet(header, buttonText, destructive = true) {
  const sheet = h("ion-action-sheet", { props: { header, buttons: [{ text: buttonText, role: destructive ? "destructive" : "confirm" }, { text: "Cancel", role: "cancel" }] } });
  document.body.append(sheet);
  await sheet.present();
  const { role } = await sheet.onDidDismiss();
  sheet.remove();
  return role === "destructive" || role === "confirm";
}

export function ago(t) {
  if (!t) return "";
  const ms = t > 1e12 ? t : t * 1000;
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)} d ago`;
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const baseName = (path) => String(path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || path;

if (window.marked) window.marked.setOptions({ gfm: true, breaks: false });
export function markdown(text) {
  const html = window.marked ? window.marked.parse(String(text || "")) : String(text || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  return window.DOMPurify ? window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true } }) : html;
}

/** The AFH mark, as on the website and the app icon. */
export const mark = (width = 72) => h("img.mark", { src: "mark.svg", alt: "", width: String(width), height: String(Math.round(width * 140 / 240)) });

/** replaceChildren that skips the null/false entries conditional UI produces. */
export const fill = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
