// The home page: smooth scrolling (Lenis), scroll-driven timelines (GSAP ScrollTrigger) and the
// 3D world they steer. The world tells the same story as the text: the mark comes apart as your
// request reaches the lead core, a plan appears around it, the work spreads to agents along live
// links, and the file being written appears in front — then the models' ring, and back to the mark.
import { createScene } from "./scene.js";
import { CODE } from "./code-sample.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap, ScrollTrigger } = window;
gsap.registerPlugin(ScrollTrigger);
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const scene = createScene($("#scene"), { mobile, reduced });
const { state } = scene;
window.afhScene = scene; // for poking at the world from the console
// On wide screens the mark sits to the right of the headline (and of the story's text).
const heroShift = () => (innerWidth > 1000 ? Math.min(4.6, innerWidth / 380) : 0);

// ---- smooth scroll ----
let lenis = null;
if (!reduced && window.Lenis) {
  lenis = new window.Lenis({ lerp: 0.085, wheelMultiplier: 0.9 });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
}
$$('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => {
  const target = $(a.getAttribute("href"));
  if (!target) return;
  e.preventDefault();
  if (lenis) lenis.scrollTo(target, { offset: 0, duration: 1.8 });
  else target.scrollIntoView({ behavior: "smooth" });
}));

/** A scroll-scrubbed timeline for one stretch of the page. */
const scrub = (trigger, start, end, opts = {}) => gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger, start, end, scrub: reduced ? true : 1, ...opts } });

// ---- 1 · hero: headline rises in, then the mark flies toward you as you scroll away ----
gsap.from(".hero .display .line > span", { yPercent: 110, rotate: 4, duration: 1.3, ease: "expo.out", stagger: 0.09, delay: 0.15 });
gsap.from([".hero .eyebrow", ".hero .lead", ".hero .cta-row", ".hero .fine"], { y: 24, opacity: 0, duration: 1.1, ease: "power3.out", stagger: 0.08, delay: 0.55 });
scrub(".hero", "top top", "bottom top")
  .to(".hero-copy", { y: -140, opacity: 0, filter: "blur(6px)" }, 0)
  .to(".scroll-hint", { opacity: 0 }, 0);

// ---- 2 · how it works: pinned, four steps, the world changes shape under each ----
const steps = $$(".step");
const flow = scrub(".flow", "top top", `+=${steps.length * 110}%`, { pin: ".flow-stage", anticipatePin: 1 });
flow.fromTo(".flow-progress i", { scaleX: 0 }, { scaleX: 1, duration: steps.length }, 0);
steps.forEach((step, i) => {
  if (i > 0) flow.fromTo(step, { autoAlpha: 0, y: 70, rotateX: -35, z: -120 }, { autoAlpha: 1, y: 0, rotateX: 0, z: 0, duration: 0.35, ease: "power2.out" }, i + 0.02);
  else flow.set(step, { autoAlpha: 1 }, 0);
  if (i < steps.length - 1) flow.to(step, { autoAlpha: 0, y: -70, rotateX: 35, z: -120, duration: 0.3, ease: "power2.in" }, i + 0.72);
});
flow.to({}, { duration: 0.2 }); // a short hold on the last step

// step 1: the prompt types itself; step 4 and the app's Live pane: code streams in
const typer = $("[data-type]");
ScrollTrigger.create({ trigger: ".flow", start: "top 60%", once: true, onEnter: () => {
  const text = typer.dataset.type;
  let i = 0;
  const tick = () => { typer.textContent = text.slice(0, ++i); if (i < text.length) setTimeout(tick, 28 + Math.random() * 40); };
  tick();
} });

function streamCode(el, speed = 16) {
  if (!el) return;
  let part = 0, ch = 0, span = null;
  const step = () => {
    if (part >= CODE.length) { setTimeout(() => { el.textContent = ""; part = 0; ch = 0; span = null; step(); }, 2600); return; }
    const [kind, text] = CODE[part];
    if (!span) { span = document.createElement("span"); if (kind) span.className = `tok-${kind}`; el.append(span); }
    const n = 1 + Math.floor(Math.random() * 3);
    span.textContent += text.slice(ch, ch + n);
    ch += n;
    if (ch >= text.length) { part++; ch = 0; span = null; }
    setTimeout(step, speed + Math.random() * speed);
  };
  step();
}
ScrollTrigger.create({ trigger: ".flow", start: "top top", once: true, onEnter: () => streamCode($("[data-code]"), 22) });
ScrollTrigger.create({ trigger: ".showcase", start: "top 80%", once: true, onEnter: () => streamCode($("[data-live]"), 14) });

// ---- 3 · the app tilts up into view; the agents drift back ----
scrub(".showcase", "top bottom", "center center")
  .fromTo(".device", { rotateX: 38, scale: 0.86, y: 60 }, { rotateX: 0, scale: 1, y: 0 }, 0);
gsap.utils.toArray(".float-card").forEach((card, i) => {
  scrub(".showcase", "top bottom", "bottom top").fromTo(card, { y: 120 + i * 50 }, { y: -120 - i * 60 }, 0);
  gsap.from(card, { autoAlpha: 0, scale: 0.8, rotateY: i % 2 ? -25 : 25, duration: 1, ease: "back.out(1.6)", delay: 0.25 + i * 0.2, scrollTrigger: { trigger: ".device", start: "top 55%" } });
});
gsap.from(".showcase-copy > *", { y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".showcase-copy", start: "top 80%" } });

// ---- 4 · features: cards flip up out of the floor, tilt under the cursor ----
gsap.from(".features .section-head > *", { y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".features", start: "top 75%" } });
gsap.set(".card", { autoAlpha: 0 });
ScrollTrigger.batch(".card", {
  start: "top 90%",
  once: true,
  onEnter: (batch) => gsap.fromTo(batch, { autoAlpha: 0, y: 90, rotateX: -50, transformOrigin: "50% 100%" }, { autoAlpha: 1, y: 0, rotateX: 0, duration: 1.1, ease: "expo.out", stagger: 0.08 }),
});
if (!mobile) $$(".card").forEach((card) => {
  const rx = gsap.quickTo(card, "rotateX", { duration: 0.5, ease: "power3" });
  const ry = gsap.quickTo(card, "rotateY", { duration: 0.5, ease: "power3" });
  card.addEventListener("pointermove", (e) => {
    const r = card.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    rx((0.5 - y) * 14); ry((x - 0.5) * 16);
    card.style.setProperty("--mx", `${x * 100}%`); card.style.setProperty("--my", `${y * 100}%`);
  });
  card.addEventListener("pointerleave", () => { rx(0); ry(0); });
});

// ---- 5 · models: a 3D ring that turns as you scroll (and slowly on its own) ----
const ring = $(".ring");
const chips = $$(".ring span");
const R = mobile ? 250 : 520;
const stepDeg = 360 / chips.length;
const ringState = { scroll: 0, auto: 0 };
gsap.ticker.add((_, dt) => {
  if (!reduced) ringState.auto += dt * 0.006;
  const rot = ringState.scroll + ringState.auto;
  ring.style.transform = `rotateX(-14deg) rotateY(${-rot}deg)`;
  // each chip turns to face you; the ones at the back fade and blur a little
  chips.forEach((c, i) => {
    const a = stepDeg * i;
    c.style.transform = `translate(-50%, -50%) rotateY(${a}deg) translateZ(${R}px) rotateY(${rot - a}deg) rotateX(14deg)`;
    const facing = (Math.cos(((a - rot) * Math.PI) / 180) + 1) / 2;
    c.style.opacity = (0.18 + facing * 0.82).toFixed(3);
    c.style.filter = facing < 0.5 ? `blur(${((0.5 - facing) * 3).toFixed(2)}px)` : "none";
  });
});
scrub(".models", "top bottom", "bottom top").fromTo(ringState, { scroll: 0 }, { scroll: 140 }, 0);
gsap.from(".models .section-head > *", { y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".models", start: "top 75%" } });
gsap.from(".ring-stage", { autoAlpha: 0, scale: 0.7, duration: 1.4, ease: "expo.out", scrollTrigger: { trigger: ".ring-stage", start: "top 85%" } });

// ---- 6 · numbers count up ----
$$("[data-count]").forEach((el) => {
  const to = Number(el.dataset.count), suffix = el.dataset.suffix || "";
  const o = { v: 0 };
  gsap.to(o, { v: to, duration: 1.6, ease: "power2.out", scrollTrigger: { trigger: el, start: "top 90%" }, onUpdate: () => { el.textContent = Math.round(o.v).toLocaleString("en-US") + suffix; } });
});
gsap.from(".stat", { y: 50, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".stats", start: "top 85%" } });

// ---- 7 · download: everything pours back into the mark ----
gsap.from(".dl-title .line > span", { yPercent: 110, rotate: 4, duration: 1.2, ease: "expo.out", stagger: 0.1, scrollTrigger: { trigger: ".dl-card", start: "top 70%" } });
gsap.from([".download .lead", ".download .cta-row", ".dl-steps li", ".download .fine"], { y: 30, autoAlpha: 0, duration: 1, ease: "power3.out", stagger: 0.08, scrollTrigger: { trigger: ".dl-card", start: "top 70%" } });

// magnetic download buttons
if (!mobile) $$(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.25); y((e.clientY - r.top - r.height / 2) * 0.35); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

// a click on empty space sends a pulse out from the core
addEventListener("pointerdown", (e) => {
  if (e.button === 0 && !e.target.closest("a, button, input, .device, .card")) scene.burst(0.8);
});

// ---- the 3D world along the page ----
// One track of keyframes keyed to scroll positions; every frame the scene takes the eased mix of
// the two keyframes around the current scroll. (One owner for the scene's state, so sections
// can't fight over it.)
const KEYS = ["zoom", "spin", "tilt", "shiftX", "shiftY", "mark", "net", "core", "flow", "tiles", "code", "spread", "activity"];
let track = [];
const at = (trigger, start, end) => ScrollTrigger.create({ trigger, start, end });
const marks = {
  hero: at(".hero", "top top", "bottom top"),
  flow: ScrollTrigger.getAll().find((t) => t.pin),
  show: at(".showcase", "top bottom", "center center"),
  feat: at(".features", "top bottom", "bottom top"),
  models: at(".models", "top bottom", "bottom top"),
  dl: at(".download", "top bottom", "center center"),
};
function buildTrack() {
  const H = heroShift();
  const f = marks.flow, fl = (x) => f.start + (f.end - f.start) * (x / 4.2); // positions on the story's timeline
  const ft = marks.feat;
  track = [
    // the mark; on phones it floats in the space above the headline
    [0, { zoom: 0, spin: 0, tilt: 0, shiftX: H, shiftY: mobile ? 7.8 : 0, mark: 1, net: 0, core: 0, flow: 0, tiles: 0, code: 0, spread: 0, activity: 0.3 }],
    // 01 · your words reach the lead: the core lights up inside the mark
    [marks.hero.end, { zoom: 2.4, spin: 0.55, tilt: 0.12, shiftY: 0, spread: 0.5, core: 0.7, activity: 0.7 }],
    [fl(0.55), { spread: 0, core: 1, mark: 0.55, net: 0.12, zoom: 2.2, spin: 0.9 }],
    // 02 · a goal and a plan appear around it; the agents start to come loose
    [fl(1.25), { tiles: 1, mark: 0, net: 0.5, flow: 0.45, spin: 1.5, tilt: 0.22, zoom: 1.4, activity: 0.5 }],
    [fl(1.75), { tiles: 1, net: 0.6, spin: 1.85 }],
    // 03 · the work spreads to agents along live links
    [fl(2.3), { tiles: 0, net: 1, flow: 1, activity: 1.1, spin: 2.6, tilt: 0.32, zoom: 0.8 }],
    [fl(2.8), { spin: 3.0 }],
    // 04 · the file being written appears in front, fed by the links
    [fl(3.3), { code: 1, spin: 3.25, tilt: 0.16, zoom: 1.5, activity: 0.9 }],
    [f.end, { code: 1, spin: 3.5 }],
    // the app: pull back, everything keeps working behind it
    [marks.show.end, { code: 0, zoom: -3, spin: 4.4, tilt: 0.45, shiftX: 0, activity: 0.6 }],
    [ft.start + (ft.end - ft.start) * 0.4, { zoom: -2, spin: 5.0, tilt: 0.35 }],
    // models: the agents spread out into a ring and the particles become a galaxy of models
    [ft.end, { zoom: -1, spin: 5.6, tilt: 0.3, net: 1.6, flow: 1.6, core: 0.8 }],
    [marks.models.end, { zoom: 0.5, spin: 6.4, tilt: 0.38, net: 2, flow: 2, core: 0.6 }],
    // the call to action: everything pours back into the mark
    [marks.dl.end, { mark: 1, net: 0, core: 0, flow: 0, tiles: 0, code: 0, zoom: -3, spin: 2 * Math.PI, tilt: 0, shiftY: mobile ? 2.8 : 2.9, activity: 0.3 }],
  ];
  track.sort((p, q) => p[0] - q[0]);
  // fill in every value so each keyframe is complete (unchanged values carry forward)
  let prev = track[0][1];
  track = track.map(([y, v]) => { prev = { ...prev, ...v }; return [y, prev]; });
}
const ease = (x) => x * x * (3 - 2 * x);
const intro = { mark: 0, spread: 1.4 };
gsap.to(intro, { mark: 1, spread: 0, duration: 2.4, ease: "power3.out" });
gsap.ticker.add(() => {
  if (!track.length) return;
  const y = lenis ? lenis.scroll : scrollY;
  let i = 0;
  while (i < track.length - 2 && y > track[i + 1][0]) i++;
  const [y0, a] = track[i], [y1, b] = track[i + 1];
  const t = ease(Math.min(1, Math.max(0, (y - y0) / Math.max(1, y1 - y0))));
  for (const k of KEYS) state[k] = a[k] + (b[k] - a[k]) * t;
  state.mark *= intro.mark;
  if (intro.mark < 1) state.net *= intro.mark;
  state.spread += intro.spread;
});
ScrollTrigger.addEventListener("refresh", buildTrack);
buildTrack();
addEventListener("load", () => ScrollTrigger.refresh());
