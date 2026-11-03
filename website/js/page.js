// The 3D world on every page but the home page (which scripts its own scroll story in main.js).
// <body data-scene="name"> picks a starting look from SCENES; any element with
// data-scene='{"tiles":1}' changes the world while it is in the middle of the screen, so the
// background always shows what the text is talking about. Scrolling turns the world slowly.
// Also: magnetic primary buttons. (Entrances and section menus are in layout.js, so the page
// never waits on WebGL.)
import { createScene } from "./scene.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap } = window;
const wide = () => innerWidth > 1000;

// Shapes are weights the world blends: a look names the one it wants and the rest go to 0.
const SHAPES = ["mark", "core", "net", "plan", "code", "ring", "spread"];
const shape = (o) => ({ ...Object.fromEntries(SHAPES.map((k) => [k, 0])), ...o });
// the header's stage box (above the words on portrait screens, beside them on landscape ones): the
// page's shape is fitted into it, where it is with the page at the top
const framed = (name, fill = 0.92) => {
  const el = document.querySelector("[data-stage]");
  if (!el) return {};
  const r = el.getBoundingClientRect();
  return scene.fit({ left: r.left, top: r.top + scrollY, width: r.width, height: r.height }, fill, name);
};
const SCENES = {
  features: () => shape({ net: 1, activity: 0.7, tilt: 0.18, ...framed("net") }),
  models: () => shape({ ring: 1, activity: 0.6, tilt: 0.55, ...framed("ring", 1) }),
  download: () => shape({ mark: 1, activity: 0.4, ...framed("mark", 0.94) }),
  docs: () => shape({ net: 1, activity: 0.35, zoom: -10, tilt: 0.2, shiftX: wide() ? 9.2 : 0, shiftY: wide() ? 3.8 : 5.8, dim: 0.6 }),
  lost: () => shape({ mark: 0.6, spread: 0.6, activity: 0.2, ...framed("mark", 0.8), dim: 0.8 }),
};

const name = document.body.dataset.scene || "docs";
const lite = name === "docs";
const scene = createScene(document.querySelector("#scene"), { mobile, reduced, lite });
const { state } = scene;
window.afhScene = scene; // for poking at the world from the console
const base = () => ({ ...(SCENES[name] || SCENES.docs)() });
// Pages with a stage box pin the world to it: every frame it is framed into the box where the box
// is right now, so it scrolls with the page and fades as the box leaves the screen.
const STAGE = { features: ["net", 0.92], models: ["ring", 1], download: ["mark", 0.94], lost: ["mark", 0.8] };
const stageEl = document.querySelector("[data-stage]");
const pinned = STAGE[name] && stageEl ? { name: STAGE[name][0], fill: STAGE[name][1] } : null;
// brightness (and, when pinned, framing) is handled per frame below, not by the looks
const strip = ({ dim, zoom, shiftX, shiftY, ...rest }) => (pinned ? rest : { zoom, shiftX, shiftY, ...rest });
Object.assign(state, strip(base()), shape({ spread: 1 }), { dim: 0 }); // the light gathers into the page's shape
const tween = (to, duration = 1.6) => gsap.to(state, { ...strip(to), duration: reduced ? 0.01 : duration, ease: "power3.inOut", overwrite: "auto" });
tween(base(), 2.6);

// sections that change the world while they're in view
let current = null;
const zones = [...document.querySelectorAll("[data-scene]:not(body)")];
const look = (el) => {
  const o = JSON.parse(el.dataset.scene || "{}");
  return SHAPES.some((k) => k in o) ? { ...base(), ...shape(o) } : { ...base(), ...o };
};
// The world floats in front of the page, so it only shows in the hero: it fades in on load and
// out as the hero scrolls away, and never sits on the text below.
const intro = { k: 0 };
gsap.to(intro, { k: 1, duration: reduced ? 0.01 : 2.2, ease: "power2.out" });
const brightness = () => {
  const hero = document.querySelector("[data-stage]")?.closest("section, header") || document.querySelector("main > :first-child");
  const bottom = hero ? hero.getBoundingClientRect().bottom : innerHeight;
  const fade = Math.min(1, Math.max(0, (bottom - 80) / (innerHeight * 0.3))); // gone once the hero's bottom nears the top
  return (base().dim ?? 1) * intro.k * fade;
};
if (zones.length && !pinned) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting && current !== e.target) { current = e.target; tween(look(e.target)); }
      else if (!e.isIntersecting && current === e.target) { current = null; tween(base()); }
    }
  }, { rootMargin: "-45% 0px -45% 0px" });
  zones.forEach((z) => io.observe(z));
}

// scrolling turns the world a little; the pointer leans it (in scene.js)
let spin = 0;
const visibility = (r) => { // 1 with the box well inside the screen, 0 once it has left
  const edge = Math.min(140, innerHeight * 0.18);
  return Math.min(1, Math.max(0, (r.bottom - 30) / edge)) * Math.min(1, Math.max(0, (innerHeight - r.top - 30) / edge));
};
gsap.ticker.add((_, dtMs) => {
  const target = (scrollY / Math.max(1, innerHeight)) * 0.45;
  spin += (target - spin) * 0.06;
  state.spin = spin;
  if (!pinned) { state.dim = brightness(); return; }
  const r = stageEl.getBoundingClientRect();
  const f = scene.fit(r, pinned.fill, pinned.name);
  const k = 1 - Math.exp(-Math.min(0.1, dtMs / 1000) * 14);
  state.zoom += (f.zoom - state.zoom) * k;
  state.shiftX += (f.shiftX - state.shiftX) * k;
  state.shiftY += (f.shiftY - state.shiftY) * k;
  state.dim = (base().dim ?? 1) * intro.k * visibility(r);
});
addEventListener("resize", () => { if (!current) tween(base(), 0.6); });

// a click on empty space sends a pulse out from the core
addEventListener("pointerdown", (e) => {
  if (e.button === 0 && !e.target.closest("a, button, input, textarea, select, summary, label, .code, pre")) scene.burst(0.7);
});

// magnetic primary buttons
if (!mobile && !reduced) document.querySelectorAll(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.22); y((e.clientY - r.top - r.height / 2) * 0.32); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

export { scene, tween, base, shape };
