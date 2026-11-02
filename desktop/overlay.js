// The overlay page: the glowing edge and pill while the agent works, AFH's cursor gliding along a
// gentle curve to each point, and an effect for every action — click ripples, drag trails, scroll
// chevrons, typing and keycaps, screenshot corners, zoom boxes — plus app approval cards and lesson
// tooltips. Effects play in order (a click waits for the glide before it). Only the pill, cards and
// tooltips catch the mouse; the rest of the window is click-through.
"use strict";

const $ = (id) => document.getElementById(id);
const body = document.body;
const api = window.overlayApi;
const params = new URLSearchParams(location.search);
const ORIGIN = params.get("origin") || "";
const TOKEN = params.get("token") || "";
const cursor = $("cursor");
const tag = $("tag");
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
  state = d || { active: false };
  body.classList.toggle("on", !!state.active);
  body.classList.toggle("home", !!state.home);
  body.classList.toggle("busy", !!state.busy);
  body.classList.toggle("teaching", !!state.teaching);
  if (state.active) body.classList.remove("stopped");
  $("who").textContent = state.teaching ? "AFH is showing you how" : "AFH is using your computer";
  $("stop-label").textContent = state.teaching ? "End lesson" : "Stop";
  setStatus(state.teaching ? "Follow the tooltip, then click Next" : state.status || (state.busy ? "Working…" : "Thinking…"));
  if (!state.active) {
    cursor.classList.remove("on", "held", "press");
    cur.x = null;
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

const cur = { x: null, y: null, bend: 1 };
let idleTimer = 0;
let tagTimer = 0;

function place(x, y) {
  cur.x = x;
  cur.y = y;
  cursor.style.transform = `translate(${x}px, ${y}px)`;
}

function wake() {
  cursor.classList.add("on");
  cursor.classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => cursor.classList.add("idle"), 7000);
}

function showTag(label, ms = 2600) {
  if (!label) return;
  tag.textContent = label;
  tag.classList.add("on");
  clearTimeout(tagTimer);
  tagTimer = setTimeout(() => tag.classList.remove("on"), ms);
}
function hideTag(ms) {
  clearTimeout(tagTimer);
  tagTimer = setTimeout(() => tag.classList.remove("on"), ms);
}

const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** Glide along a slight arc (like a hand moving a mouse), leaving a fading trail. */
function glide(x, y, ms) {
  wake();
  if (cur.x == null) {
    place(x, y);
    cursor.animate([{ opacity: 0, scale: 1.6 }, { opacity: 1, scale: 1 }], { duration: 320, easing: "cubic-bezier(.34,1.56,.64,1)" });
    return sleep(120);
  }
  const sx = cur.x, sy = cur.y, dx = x - sx, dy = y - sy;
  const dist = Math.hypot(dx, dy);
  if (dist < 3) {
    place(x, y);
    return Promise.resolve();
  }
  const dur = clamp((ms || 220) * (0.6 + Math.min(dist, 1600) / 1600), 140, 700);
  cur.bend = -cur.bend; // alternate the side of the arc so paths look natural
  const off = Math.min(70, dist * 0.1) * cur.bend;
  const cx = sx + dx / 2 + (-dy / dist) * off, cy = sy + dy / 2 + (dx / dist) * off;
  const t0 = performance.now();
  let frame = 0;
  return new Promise((done) => {
    const step = (now) => {
      const t = clamp((now - t0) / dur, 0, 1);
      const e = easeInOut(t);
      const u = 1 - e;
      const px = u * u * sx + 2 * u * e * cx + e * e * x;
      const py = u * u * sy + 2 * u * e * cy + e * e * y;
      place(px, py);
      if (++frame % 2 === 0 && t < 0.92) trail(px, py);
      if (t < 1) requestAnimationFrame(step);
      else done();
    };
    requestAnimationFrame(step);
  });
}

function trail(x, y) {
  const d = el("div", "trail");
  d.style.left = x + "px";
  d.style.top = y + "px";
  body.append(d);
  setTimeout(() => d.remove(), 500);
}

function ripple(x, y, cls = "") {
  const r = el("div", "ripple " + cls);
  r.style.left = x + "px";
  r.style.top = y + "px";
  body.append(r);
  setTimeout(() => r.remove(), 700);
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
    cursor.classList.remove("on");
    cur.x = null;
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
      cursor.classList.add("press");
      const alt = d.button === "right" ? "alt" : "";
      if (d.mods) chip(d.x, d.y, [text("span", "", "Holding"), ...keycaps(d.mods).children], 1200);
      if (d.button === "right") chip(d.x, d.y + 54, text("span", "", "Right-click"), 1000);
      for (let i = 0; i < (d.count || 1); i++) {
        ripple(d.x, d.y, alt);
        ripple(d.x, d.y, "dot");
        if (i < d.count - 1) await sleep(110);
      }
      await sleep(130);
      cursor.classList.remove("press");
      return;
    }
    case "press":
      cursor.classList.add("held");
      ripple(d.x, d.y, "dot");
      return;
    case "release":
      cursor.classList.remove("held");
      ripple(d.x, d.y);
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
      return shot(d.rect);
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
  ripple(d.x, d.y, "dot");
  const svg = $("drag");
  const g = document.createElementNS(SVG_NS, "g");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", `M${d.x},${d.y} L${d.x2},${d.y2}`);
  const a = document.createElementNS(SVG_NS, "circle");
  a.setAttribute("cx", d.x);
  a.setAttribute("cy", d.y);
  a.setAttribute("r", 4);
  g.append(path, a);
  svg.append(g);
  const len = path.getTotalLength();
  // draw the line as the cursor travels: a dash pattern revealed by a growing mask length
  path.style.strokeDasharray = `0 ${len}`;
  path.animate([{ strokeDasharray: `0 ${len}` }, { strokeDasharray: `${len} 0` }], { duration: d.ms || 450, easing: "ease-out", fill: "forwards" });
  await glide(d.x2, d.y2, d.ms || 450);
  const b = a.cloneNode();
  b.setAttribute("cx", d.x2);
  b.setAttribute("cy", d.y2);
  g.append(b);
  cursor.classList.remove("held");
  ripple(d.x2, d.y2);
  setTimeout(() => g.classList.add("fade"), 500);
  setTimeout(() => g.remove(), 1200);
}

async function scroll(d) {
  if (cur.x == null || Math.hypot(cur.x - d.x, cur.y - d.y) > 3) await glide(d.x, d.y, 200);
  const s = el("div", "scroll");
  s.append(el("i"), el("i"), el("i"));
  const rot = { down: 0, up: 180, left: 90, right: -90 }[d.direction] ?? 0;
  s.style.left = d.x + 34 + "px";
  s.style.top = d.y - 24 + "px";
  s.style.transform = `rotate(${rot}deg)`;
  body.append(s);
  setTimeout(() => s.remove(), 1100);
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
    bar.animate([{ width: "0%" }, { width: "100%" }], { duration: d.hold * 1000, fill: "forwards" });
    setTimeout(() => set.querySelectorAll(".cap").forEach((c) => c.classList.remove("down")), d.hold * 1000);
    later(set, d.hold * 1000 + 700);
  } else {
    later(set, 1500);
  }
  if (d.label) setStatus(d.label);
  await sleep(160);
}

function shot(r) {
  const rect = r || { x: 0, y: 0, w: innerWidth, h: innerHeight };
  const inset = rect.w >= innerWidth - 4 ? 14 : 0;
  const f = el("div", "frame");
  Object.assign(f.style, { left: rect.x + inset + "px", top: rect.y + inset + "px", width: rect.w - inset * 2 + "px", height: rect.h - inset * 2 + "px" });
  f.append(el("i"), el("i"), el("i"), el("i"));
  body.append(f, el("div", "flash"));
  setTimeout(() => f.remove(), 700);
  setTimeout(() => document.querySelectorAll(".flash").forEach((n) => n.remove()), 600);
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
  setStatus(label || "Stopped");
  $("who").textContent = "AFH stopped";
  $("stop-label").textContent = "Stop";
  cursor.classList.remove("on", "held", "press");
  cur.x = null;
  document.querySelectorAll(".tip").forEach((t) => t.remove());
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
  cursor.classList.remove("on"); // the user drives during a lesson
  cur.x = null;
  body.classList.add("lesson");
  body.classList.toggle("nopoint", !point);
  const shade = $("shade");
  if (point) {
    shade.style.setProperty("--sx", t.x + "px");
    shade.style.setProperty("--sy", t.y + "px");
    shade.animate([{ "--r": "1400px" }, { "--r": "86px" }], { duration: 650, easing: "cubic-bezier(.22,.61,.36,1)", fill: "forwards" });
    shade.style.setProperty("--r", "86px");
    const b = el("div", "beacon");
    b.append(el("i"), el("i"), el("i"), el("b"));
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
  const next = text("button", "btn primary", t.total && t.step >= t.total ? "Done" : "Next →");
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
  const W = 340, H = tip.offsetHeight || 160, gap = 34;
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
