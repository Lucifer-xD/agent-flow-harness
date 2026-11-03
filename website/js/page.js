// The studio set on every page but the home page (which scripts its own in main.js): the ceramic
// objects rest round the hero's stage box (`[data-stage]`), measured every frame so they scroll
// with the page and shrink away as the hero leaves the screen. Pages without a stage (docs, the
// changelog) get a small group in the top-right corner of the hero. Also: magnetic primary buttons.
// (Entrances and section menus are in layout.js, so the page never waits on WebGL.)
import { createScene } from "./scene.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap } = window;

const name = document.body.dataset.scene || "docs";
const lite = name === "docs";
const scene = createScene(document.querySelector("#scene"), { mobile, reduced, lite });
window.afhScene = scene; // for poking at the set from the console

// how each page arranges the set in its stage box (CSS px placements)
const LAYOUTS = {
  features: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    hub: { x: cx, y: cy, r: s * 0.17 },
    sphereA: { x: cx - s * 0.34, y: cy - s * 0.2, r: s * 0.13 },
    sphereB: { x: cx + s * 0.34, y: cy - s * 0.26, r: s * 0.09 },
    cube: { x: cx + s * 0.32, y: cy + s * 0.2, r: s * 0.13, rot: 0.5 },
    pill: { x: cx - s * 0.3, y: cy + s * 0.26, r: s * 0.15, rot: 0.7 },
    torus: { x: cx + s * 0.02, y: cy - s * 0.42, r: s * 0.1, rot: 1 },
  }; },
  models: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    torus: { x: cx, y: cy, r: s * 0.34, rot: 0.2 },
    sphereA: { x: cx - s * 0.38, y: cy + s * 0.3, r: s * 0.12 },
    sphereB: { x: cx + s * 0.4, y: cy - s * 0.3, r: s * 0.08 },
    cube: { x: cx + s * 0.4, y: cy + s * 0.32, r: s * 0.11, rot: 0.4 },
    pill: { x: cx - s * 0.4, y: cy - s * 0.3, r: s * 0.13, rot: 0.3 },
  }; },
  download: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    hub: { x: cx - s * 0.1, y: cy - s * 0.02, r: s * 0.2 },
    torus: { x: cx + s * 0.3, y: cy - s * 0.2, r: s * 0.22, rot: 0.6 },
    pill: { x: cx + s * 0.26, y: cy + s * 0.3, r: s * 0.18, rot: 0.2 },
    sphereA: { x: cx - s * 0.36, y: cy + s * 0.3, r: s * 0.13 },
    sphereB: { x: cx - s * 0.38, y: cy - s * 0.3, r: s * 0.08 },
  }; },
  lost: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    cube: { x: cx - s * 0.2, y: cy + s * 0.1, r: s * 0.18, rot: 0.9 },
    sphereA: { x: cx + s * 0.24, y: cy + s * 0.18, r: s * 0.14 },
    pill: { x: cx + s * 0.1, y: cy - s * 0.26, r: s * 0.18, rot: 1.3 },
  }; },
  // no stage: a small group in the hero's top-right corner (docs, api, changelog, account pages)
  corner: (B) => { const x = B.right - 150, y = B.top + 120, s = 120; return {
    torus: { x, y, r: s * 0.3, rot: 0.4 },
    sphereB: { x: x - s * 0.5, y: y + s * 0.3, r: s * 0.12 },
    cube: { x: x + s * 0.5, y: y - s * 0.3, r: s * 0.14, rot: 0.3 },
  }; },
};
const stage = document.querySelector("[data-stage]");
const hero = stage || document.querySelector("main > :first-child");
const layout = stage && LAYOUTS[name] ? LAYOUTS[name] : LAYOUTS.corner;
const visibility = (r) => { // 1 with the box well inside the screen, 0 once it has left
  const edge = Math.min(160, innerHeight * 0.2);
  return Math.min(1, Math.max(0, (r.bottom - 20) / edge)) * Math.min(1, Math.max(0, (innerHeight - r.top - 20) / edge));
};
const intro = { k: 0 };
gsap.to(intro, { k: 1, duration: reduced ? 0.01 : 1.6, ease: "power2.out", delay: 0.3 });
gsap.ticker.add(() => {
  if (!hero) return;
  const r = hero.getBoundingClientRect();
  const B = stage ? r : { left: r.left, right: Math.min(r.right, innerWidth), top: Math.max(r.top, 0), bottom: r.bottom, width: r.width, height: r.height };
  const vis = visibility(r) * intro.k * (stage ? 1 : 0.9);
  const out = layout(B);
  for (const id of scene.ids) {
    if (out[id] && (!mobile || stage)) scene.place(id, { ...out[id], vis });
    else scene.hide(id);
  }
});

// magnetic primary buttons
if (!mobile && !reduced) document.querySelectorAll(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.22); y((e.clientY - r.top - r.height / 2) * 0.32); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

export { scene };
