// The overlay page: a glow round the screen and a pill while the agent works, AFH's cursor gliding
// to each point with a light following it, and an effect for every action (a burst of light for a
// click, a beam for a drag, a light sliding for a scroll, typing, keycaps, zoom boxes), plus app
// approval cards and lesson tooltips. Effects play in order (a click waits for the glide before it).
// Only the pill, cards and tooltips catch the mouse; the rest of the window is click-through.
"use strict";

const $ = (id) => document.getElementById(id);
const body = document.body;
const api = window.overlayApi;
const params = new URLSearchParams(location.search);
const ORIGIN = params.get("origin") || "";
const TOKEN = params.get("token") || "";
const cursor = $("cursor");
const tag = $("tag");
const trail = $("trail");
const SVG_NS = "http://www.w3.org/2000/svg";

const ICON = {
  pointer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M5 3l15 9-6.3 1.2L17 20l-2.8 1.2-3.2-6.9L5 18z"/></svg>',
  keyboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2.5"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/></svg>',
  zoom: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2M11 8.5v5M8.5 11h5"/></svg>',
};

function el(tagName, cls, html) {
  const n = document.createElement(tagName);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}
const text = (tagName, cls, s) => {
  const n = el(tagName, cls);
  n.textContent = s;
  return n;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function later(node, ms, outMs = 400) {
  setTimeout(() => {
    node.classList.add("out");
    setTimeout(() => node.remove(), outMs);
  }, ms);
}

// ---- state: on/off, the pill ---------------------------------------------------------------------

let state = { active: false };
let statusText = "";

function setState(d) {
  const wasOn = !!state.active;
  state = d || { active: false };
  body.classList.toggle("on", !!state.active);
  body.classList.toggle("home", !!state.home);
  body.classList.toggle("busy", !!state.busy);
  body.classList.toggle("teaching", !!state.teaching);
  if (state.active) body.classList.remove("stopped");
  if (state.active && !wasOn) flare(1300);
  $("who").textContent = state.teaching ? "AFH is showing you how" : "AFH is using your computer";
  $("stop-label").textContent = state.teaching ? "End lesson" : "Stop";
  setStatus(state.teaching ? "Follow the tooltip, then click Next" : state.status || (state.busy ? "Working…" : "Thinking…"));
  if (!state.active) {
    dropCursor();
    hideTag(0);
  }
}

function setStatus(s) {
  if (s === statusText) return;
  statusText = s;
  const box = $("status");
  const old = box.querySelector("span:not(.out)");
  const span = text("span", "in", s);
  box.append(span);
  requestAnimationFrame(() => requestAnimationFrame(() => span.classList.remove("in")));
  if (old) {
    old.classList.add("out");
    setTimeout(() => old.remove(), 400);
  }
}

// ---- AFH's cursor ------------------------------------------------------------------------------------

const cur = { x: null, y: null, bend: 1, tx: 0, ty: 0, raf: 0 }; // tx, ty: where the following light is
let idleTimer = 0;
let tagTimer = 0;

function place(x, y, tilt = 0) {
  cur.x = x;
  cur.y = y;
  cursor.style.transform = `translate(${x}px, ${y}px) rotate(${tilt}deg)`;
  follow();
}

/** The light trails the cursor like something with weight, and asks for no more frames once it has caught up. */
function follow() {
  if (cur.raf) return;
  const step = () => {
    cur.raf = 0;
    if (cur.x == null) return;
    const gx = cur.x + 6 - cur.tx, gy = cur.y + 7 - cur.ty;
    cur.tx += gx * 0.2;
    cur.ty += gy * 0.2;
    trail.style.transform = `translate(${cur.tx}px, ${cur.ty}px)`;
    if (Math.abs(gx) + Math.abs(gy) > 0.4) cur.raf = requestAnimationFrame(step);
  };
  cur.raf = requestAnimationFrame(step);
}

function wake() {
  cursor.classList.add("on");
  cursor.classList.remove("idle");
  body.classList.add("cursor");
  body.classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    cursor.classList.add("idle");
    body.classList.add("idle");
  }, 7000);
}

function dropCursor() {
  cursor.classList.remove("on", "held", "press");
  body.classList.remove("cursor", "press");
  cur.x = null;
}

function press(on) {
  cursor.classList.toggle("press", on);
  body.classList.toggle("press", on);
}

function showTag(label, ms = 2600) {
  if (!label) return;
  tag.firstChild.textContent = label;
  tag.classList.add("on");
  clearTimeout(tagTimer);
  tagTimer = setTimeout(() => tag.classList.remove("on"), ms);
}
function hideTag(ms) {
  clearTimeout(tagTimer);
  tagTimer = setTimeout(() => tag.classList.remove("on"), ms);
}

/** A soft start and a long, soft landing. */
const landing = (t) => 1 - Math.pow(1 - t * t * (3 - 2 * t), 1.8);

/** Glide along a slight arc, leaning into the direction of travel and settling upright. */
function glide(x, y, ms) {
  wake();
  if (cur.x == null) {
    cur.tx = x;
    cur.ty = y;
    place(x, y);
    const opts = { duration: 460, easing: "cubic-bezier(.16,1,.3,1)" };
    cursor.animate([{ opacity: 0, scale: 1.9 }, { opacity: 1, scale: 1 }], opts);
    trail.animate([{ opacity: 0, scale: 2.2 }, { opacity: 1, scale: 1 }], opts);
    return sleep(160);
  }
  const sx = cur.x, sy = cur.y, dx = x - sx, dy = y - sy;
  const dist = Math.hypot(dx, dy);
  if (dist < 3) {
    place(x, y);
    return Promise.resolve();
  }
  const dur = clamp((ms || 220) * (0.62 + Math.min(dist, 1600) / 1500), 160, 720);
  cur.bend = -cur.bend; // alternate the side of the arc so paths look natural
  const off = Math.min(64, dist * 0.1) * cur.bend;
  const cx = sx + dx / 2 + (-dy / dist) * off, cy = sy + dy / 2 + (dx / dist) * off;
  const lean = clamp(dx / 60, -11, 11) * Math.min(1, dist / 220);
  const t0 = performance.now();
  return new Promise((done) => {
    const step = (now) => {
      const t = clamp((now - t0) / dur, 0, 1);
      const e = landing(t);
      const u = 1 - e;
      place(u * u * sx + 2 * u * e * cx + e * e * x, u * u * sy + 2 * u * e * cy + e * e * y, lean * Math.sin(Math.PI * Math.sqrt(t)));
      if (t < 1) return requestAnimationFrame(step);
      place(x, y);
      done();
    };
    requestAnimationFrame(step);
  });
}

function at(cls, x, y) {
  const n = el("div", cls);
  n.style.left = x + "px";
  n.style.top = y + "px";
  body.append(n);
  setTimeout(() => n.remove(), 700);
}

/** A click: light bursting from the point, a ring leaving it. */
function burst(x, y, cls = "") {
  at(`burst ${cls}`, x, y);
  at(`ring ${cls}`, x, y);
}

/** The whole edge swells with light once. */
function flare(ms = 700, strength = 1) {
  $("flare").animate([{ opacity: 0 }, { opacity: strength, offset: 0.3 }, { opacity: 0 }], { duration: ms, easing: "ease-in-out" });
}

function chip(x, y, node, ms = 1600) {
  const c = el("div", "chip");
  c.append(...[].concat(node));
  c.style.left = clamp(x + 22, 8, innerWidth - 260) + "px";
  c.style.top = clamp(y - 34, 8, innerHeight - 40) + "px";
  body.append(c);
  later(c, ms);
  return c;
}

function keycaps(combo) {
  const set = el("div", "keyset");
  const parts = String(combo).split("+").map((s) => s.trim()).filter(Boolean);
  const nice = { ctrl: "Ctrl", control: "Ctrl", alt: "Alt", shift: "Shift", win: "Win", cmd: "Ctrl", enter: "Enter", return: "Enter", esc: "Esc",
    escape: "Esc", tab: "Tab", space: "Space", backspace: "⌫", delete: "Del", up: "↑", down: "↓", left: "←", right: "→", pageup: "PgUp", pagedown: "PgDn" };
  parts.forEach((p, i) => {
    if (i) set.append(text("span", "plus", "+"));
    const cap = text("span", "cap", nice[p.toLowerCase()] || (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)));
    cap.style.animationDelay = i * 70 + "ms";
    set.append(cap);
  });
  return set;
}

// ---- effects, played in order --------------------------------------------------------------------------

let queue = Promise.resolve();
function enqueue(fn) {
  queue = queue.then(fn).catch(() => {});
}

async function play(d) {
  const k = d.kind;
  if (k === "leave") {
    dropCursor();
    return;
  }
  if (k === "stopped") return stopped(d.label);
  if (d.label && ["move", "launch", "focus", "wait"].includes(k)) setStatus(d.label);
  switch (k) {
    case "move":
      showTag(d.label);
      return glide(d.x, d.y, d.ms);
    case "click": {
      if (cur.x == null || Math.hypot(cur.x - d.x, cur.y - d.y) > 3) await glide(d.x, d.y, 200);
      press(true);
      const alt = d.button === "right" ? "alt" : "";
      if (d.mods) chip(d.x, d.y, [text("span", "", "Holding"), ...keycaps(d.mods).children], 1200);
      if (d.button === "right") chip(d.x, d.y + 54, text("span", "", "Right-click"), 1000);
      for (let i = 0; i < (d.count || 1); i++) {
        burst(d.x, d.y, alt);
        if (i < (d.count || 1) - 1) await sleep(120);
      }
      await sleep(130);
      press(false);
      return;
    }
    case "press":
      cursor.classList.add("held");
      burst(d.x, d.y);
      return;
    case "release":
      cursor.classList.remove("held");
      burst(d.x, d.y);
      return;
    case "drag":
      return drag(d);
    case "scroll":
      return scroll(d);
    case "type":
      return typing(d);
    case "key":
      return keys(d);
    case "shot":
      return flare(640, 0.85); // a look at the screen: the edge swells with light
    case "zoom":
      return zoom(d.rect);
    case "focus":
      if (d.rect) {
        const b = el("div", "winfocus");
        Object.assign(b.style, { left: d.rect.x + "px", top: d.rect.y + "px", width: d.rect.w + "px", height: d.rect.h + "px" });
        body.append(b);
        setTimeout(() => b.remove(), 1000);
      }
      return;
    case "wait":
      return waiting(d.secs || 1);
  }
}

async function drag(d) {
  await glide(d.x, d.y, 200);
  cursor.classList.add("held");
  burst(d.x, d.y);
  const g = document.createElementNS(SVG_NS, "g");
  const ms = d.ms || 450;
  for (const cls of ["w", "m", "h"]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("class", cls);
    path.setAttribute("d", `M${d.x},${d.y} L${d.x2},${d.y2}`);
    path.setAttribute("pathLength", 1);
    g.append(path);
    path.animate([{ strokeDasharray: "0 1" }, { strokeDasharray: "1 0" }], { duration: ms, easing: "cubic-bezier(.2,.7,.2,1)", fill: "both" });
  }
  $("drag").append(g);
  await glide(d.x2, d.y2, ms);
  cursor.classList.remove("held");
  burst(d.x2, d.y2);
  setTimeout(() => g.classList.add("fade"), 350);
  setTimeout(() => g.remove(), 900);
}

async function scroll(d) {
  if (cur.x == null || Math.hypot(cur.x - d.x, cur.y - d.y) > 3) await glide(d.x, d.y, 200);
  const s = el("div", "scroll");
  s.append(el("i"));
  Object.assign(s.style, { left: d.x + "px", top: d.y + "px", rotate: ({ down: 0, up: 180, left: 90, right: -90 }[d.direction] ?? 0) + "deg" });
  body.append(s);
  later(s, 1200);
}

async function typing(d) {
  wake();
  const full = String(d.text || "");
  const row = [el("span", "", ICON.keyboard), text("span", "txt", ""), el("span", "caret")];
  const c = chip(cur.x ?? d.x ?? innerWidth / 2, cur.y ?? d.y ?? innerHeight / 2, row, Math.min(4200, 1400 + full.length * 30));
  c.classList.add("typing");
  const out = c.querySelector(".txt");
  const per = clamp(900 / Math.max(1, full.length), 8, 40);
  for (let i = 1; i <= full.length; i++) {
    out.textContent = full.slice(0, i).replace(/\n/g, "⏎ ");
    await sleep(per);
  }
}

async function keys(d) {
  const box = $("keys");
  box.replaceChildren();
  const set = keycaps(d.keys || "");
  box.append(set);
  if (d.hold) {
    set.querySelectorAll(".cap").forEach((c) => c.classList.add("down"));
    const bar = el("div", "bar");
    set.append(bar);
    bar.animate([{ transform: "scaleX(0)" }, { transform: "none" }], { duration: d.hold * 1000, fill: "forwards" });
    setTimeout(() => set.querySelectorAll(".cap").forEach((c) => c.classList.remove("down")), d.hold * 1000);
    later(set, d.hold * 1000 + 700);
  } else {
    later(set, 1500);
  }
  if (d.label) setStatus(d.label);
  await sleep(160);
}

function zoom(r) {
  if (!r) return;
  const z = el("div", "zoombox");
  Object.assign(z.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
  z.append(el("b", "", ICON.zoom));
  body.append(z);
  setTimeout(() => z.remove(), 1300);
}

function waiting(secs) {
  body.classList.add("waiting");
  const c = $("wait").querySelector("circle");
  c.animate([{ strokeDashoffset: 0 }, { strokeDashoffset: 100 }], { duration: secs * 1000, fill: "forwards" });
  setTimeout(() => body.classList.remove("waiting"), secs * 1000);
}

function stopped(label) {
  body.classList.add("stopped");
  flare(900);
  setStatus(label || "Stopped");
  $("who").textContent = "AFH stopped";
  $("stop-label").textContent = "Stop";
  dropCursor();
  document.querySelectorAll(".tip, .beacon").forEach((t) => t.remove());
  body.classList.remove("lesson", "nopoint");
}

// ---- app approval cards --------------------------------------------------------------------------------

const TIERS = { full: "Full control", click: "Click only", read: "View only" };

function iconFor(app) {
  const box = el("div", "ico");
  box.textContent = (app.name || "?").trim()[0] || "?";
  if (app.path && /\.exe$/i.test(app.path) && ORIGIN) {
    const img = new Image();
    img.onload = () => box.replaceChildren(img);
    img.src = `${ORIGIN}/api/computer/icon?size=64&token=${encodeURIComponent(TOKEN)}&path=${encodeURIComponent(app.path)}`;
  }
  return box;
}

function showAsk(a) {
  if (document.querySelector(`.ask[data-id="${CSS.escape(a.id)}"]`)) return;
  const card = el("div", "ask");
  card.dataset.id = a.id;
  card.dataset.hit = "";
  const head = el("div", "head");
  const words = el("div");
  words.append(text("h2", "", a.title || "Let AFH use this app?"));
  if (a.reason) words.append(text("div", "reason", a.reason));
  head.append(el("div", "badge", ICON.pointer), words);
  const list = el("div", "apps");
  (a.apps || []).forEach((app, i) => {
    const row = el("div", "app");
    row.style.animationDelay = 60 + i * 50 + "ms";
    row.append(iconFor(app), text("span", "nm", app.name || app.id), text("span", "tier " + (app.tier || "full"), TIERS[app.tier] || "Full control"));
    list.append(row);
  });
  const note = text("div", "note", "AFH will move the mouse and type in " + ((a.apps || []).length > 1 ? "these apps" : "it") + " while it works. Press Esc any time to stop.");
  const btns = el("div", "btns");
  const b = (label, cls, decision) => {
    const n = text("button", "btn " + cls, label);
    n.addEventListener("click", () => {
      btns.querySelectorAll("button").forEach((x) => (x.disabled = true));
      api.answer(a.id, decision);
      dismissAsk(a.id);
    });
    return n;
  };
  btns.append(b("Don't allow", "deny", "reject"), el("span", "sp"), b("Always allow", "", "always"), b("Allow", "primary", "once"));
  card.append(head, list, note, btns);
  $("asks").append(card);
}

function dismissAsk(id) {
  const card = document.querySelector(`.ask[data-id="${CSS.escape(id)}"]`);
  if (!card || card.classList.contains("out")) return;
  card.classList.add("out");
  setTimeout(() => card.remove(), 350);
  setTimeout(checkHit, 360);
}

// ---- teach mode -----------------------------------------------------------------------------------

function showTeach(t) {
  document.querySelectorAll(".tip, .beacon").forEach((n) => n.remove());
  const point = typeof t.x === "number" && typeof t.y === "number";
  dropCursor(); // the user drives during a lesson
  body.classList.add("lesson");
  body.classList.toggle("nopoint", !point);
  const shade = $("shade");
  if (point) {
    shade.style.setProperty("--sx", t.x + "px");
    shade.style.setProperty("--sy", t.y + "px");
    shade.style.setProperty("--r", "92px");
    shade.animate([{ "--r": "1400px" }, { "--r": "92px" }], { duration: 700, easing: "cubic-bezier(.16,1,.3,1)" });
    const b = el("div", "beacon");
    b.append(el("i"), el("i"), el("b"));
    b.style.left = t.x + "px";
    b.style.top = t.y + "px";
    body.append(b);
  }
  const tip = el("div", "tip");
  tip.dataset.hit = "";
  tip.dataset.id = t.id;
  const top = el("div", "top");
  if (t.step) top.append(text("span", "stepn", t.total ? `Step ${t.step} of ${t.total}` : `Step ${t.step}`));
  if (t.total && t.total > 1 && t.total <= 12) {
    const dots = el("div", "dots");
    for (let i = 1; i <= t.total; i++) dots.append(el("i", i < t.step ? "on" : i === t.step ? "on now" : ""));
    top.append(dots);
  }
  if (top.children.length) tip.append(top);
  if (t.title) tip.append(text("h3", "", t.title));
  tip.append(text("p", "", t.text || ""));
  const btns = el("div", "btns");
  const exit = text("button", "btn", "Exit");
  const next = text("button", "btn primary", t.total && t.step >= t.total ? "Done" : "Next");
  const finish = (choice) => {
    btns.querySelectorAll("button").forEach((x) => (x.disabled = true));
    api.teach(t.id, choice);
    hideTeach(t.id);
  };
  exit.addEventListener("click", () => finish("exit"));
  next.addEventListener("click", () => finish("next"));
  btns.append(exit, el("span", "sp"), next);
  tip.append(btns);
  body.append(tip);
  // place the tooltip beside the point, on the side with the most room
  const W = 344, H = tip.offsetHeight || 160, gap = 34;
  let x = innerWidth / 2 - W / 2, y = innerHeight / 2 - H / 2;
  if (point) {
    const right = innerWidth - t.x, below = innerHeight - t.y;
    x = right > W + gap + 20 ? t.x + gap : t.x - gap - W;
    y = clamp(t.y - H / 2, 70, innerHeight - H - 20);
    if (t.x < W + gap + 20 && right < W + gap + 20) {
      x = clamp(t.x - W / 2, 16, innerWidth - W - 16);
      y = below > H + gap + 20 ? t.y + gap + 10 : t.y - gap - H - 10;
    }
    const arrow = el("div", "arrow");
    if (x > t.x) Object.assign(arrow.style, { left: "-8px", top: clamp(t.y - y - 7, 14, H - 28) + "px", transform: "rotate(-45deg)" });
    else if (x + W < t.x) Object.assign(arrow.style, { right: "-8px", top: clamp(t.y - y - 7, 14, H - 28) + "px", transform: "rotate(135deg)" });
    else if (y > t.y) Object.assign(arrow.style, { top: "-8px", left: clamp(t.x - x - 7, 14, W - 28) + "px" });
    else Object.assign(arrow.style, { bottom: "-8px", left: clamp(t.x - x - 7, 14, W - 28) + "px", transform: "rotate(225deg)" });
    tip.append(arrow);
  }
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}

function hideTeach(id) {
  const tip = document.querySelector(`.tip[data-id="${CSS.escape(String(id))}"]`);
  if (!tip) return;
  tip.classList.add("out");
  setTimeout(() => tip.remove(), 320);
  document.querySelectorAll(".beacon").forEach((n) => n.remove());
  body.classList.remove("lesson", "nopoint");
  setTimeout(checkHit, 340);
}

// ---- only the pill, cards and tooltips catch the mouse ---------------------------------------------

let interactive = false;
let lastPoint = { x: -1, y: -1 };
function hitAt(x, y) {
  for (const n of document.querySelectorAll("[data-hit]")) {
    if (n.id === "pill" && !(body.classList.contains("on") && body.classList.contains("home"))) continue;
    const r = n.getBoundingClientRect();
    if (r.width && x >= r.left - 4 && x <= r.right + 4 && y >= r.top - 4 && y <= r.bottom + 4) return true;
  }
  return false;
}
function checkHit() {
  const on = hitAt(lastPoint.x, lastPoint.y);
  if (on !== interactive) {
    interactive = on;
    api.setInteractive(on);
  }
}
document.addEventListener("mousemove", (e) => {
  lastPoint = { x: e.clientX, y: e.clientY };
  checkHit();
});
$("stop").addEventListener("click", () => api.stop(!!state.teaching));

// ---- wiring ---------------------------------------------------------------------------------------

api.onState((d) => setState(d));
api.onFx((d) => enqueue(() => play(d)));
api.onAsk((a) => showAsk(a));
api.onAskDone((d) => dismissAsk(d.id));
api.onTeach((t) => showTeach(t));
api.onTeachDone((d) => hideTeach(d.id));
setStatus("Working…");
