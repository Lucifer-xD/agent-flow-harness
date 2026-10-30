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

const SCENES = {
  features: () => ({ mark: 0, net: 1, core: 1, flow: 1, activity: 0.7, zoom: -1.5, tilt: 0.3, shiftX: wide() ? 3.4 : 0, shiftY: mobile ? 2.6 : 0 }),
  models: () => ({ mark: 0, net: 2, core: 0.75, flow: 2, activity: 0.6, zoom: -2.5, tilt: 0.42, shiftY: mobile ? 1.5 : -0.4 }),
  download: () => ({ mark: 1, net: 0, core: 0, flow: 0, activity: 0.4, zoom: mobile ? 0 : 0.6, shiftX: wide() ? 3.6 : 0, shiftY: mobile ? 6.4 : 0 }),
  docs: () => ({ mark: 0, net: 1, core: 0.85, flow: 1, activity: 0.35, zoom: -4, tilt: 0.35, shiftX: wide() ? 5 : 0, dim: 0.55 }),
  lost: () => ({ mark: 0.12, net: 0.45, core: 0, flow: 0, spread: 2.2, activity: 0.2, zoom: -1.5, shiftY: mobile ? 2 : 0.6, dim: 0.8 }),
};

const name = document.body.dataset.scene || "docs";
const lite = name === "docs";
const scene = createScene(document.querySelector("#scene"), { mobile, reduced, lite });
const { state } = scene;
window.afhScene = scene; // for poking at the world from the console
const base = () => ({ ...(SCENES[name] || SCENES.docs)() });
Object.assign(state, base(), { mark: 0, spread: 2.2, dim: 0 });
const tween = (to, duration = 1.6) => gsap.to(state, { ...to, duration: reduced ? 0.01 : duration, ease: "power3.inOut", overwrite: "auto" });
tween({ ...base(), spread: base().spread || 0, dim: base().dim ?? 1 }, 2.4);

// sections that change the world while they're in view
let current = null;
const zones = [...document.querySelectorAll("[data-scene]:not(body)")];
const look = (el) => ({ ...base(), ...JSON.parse(el.dataset.scene || "{}") });
if (zones.length) {
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
gsap.ticker.add(() => {
  const target = (scrollY / Math.max(1, innerHeight)) * 0.45;
  spin += (target - spin) * 0.06;
  state.spin = spin;
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

export { scene, tween, base };
