// The home page: smooth scrolling (Lenis), scroll-driven timelines (GSAP ScrollTrigger) and the
// 3D world they steer. The world tells the same story as the text: your words coil round the hub,
// a plan is laid out beside it, the work spreads to agents, the file is written in front — then
// the models' ring, and back to the mark on the closing card.
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
/** Where the hero's stage box is with the page at the top: the mark is fitted into it. */
const heroFit = () => {
  const r = $("[data-stage]").getBoundingClientRect(), y = lenis ? lenis.scroll : scrollY;
  return scene.fit({ left: r.left, top: r.top + y, width: r.width, height: r.height }, 0.9);
};
/** The download card's mark box, where it will be on screen when that section is centred (scroll `at`). */
const ctaFit = (at) => {
  const r = $("[data-cta-stage]").getBoundingClientRect(), y = lenis ? lenis.scroll : scrollY;
  return scene.fit({ left: r.left, top: r.top + y - at, width: r.width, height: r.height }, 0.94);
};
/** The story's world box (beside the steps, or between heading and step on portrait screens), with the story pinned. */
const storyFit = (name, fill) => {
  const st = $(".flow-stage").getBoundingClientRect(), r = $("[data-world]").getBoundingClientRect();
  return scene.fit({ left: r.left, top: r.top - st.top, width: r.width, height: r.height }, fill, name);
};

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

// ---- 1 · hero: headline rises in, then the words slide away as you scroll ----
gsap.from(".hero .display .line > span", { yPercent: 110, rotate: 3, duration: 1.3, ease: "expo.out", stagger: 0.09, delay: 0.15 });
gsap.from([".hero .eyebrow", ".hero .lead", ".hero .cta-row", ".hero .proof"], { y: 24, opacity: 0, duration: 1.1, ease: "power3.out", stagger: 0.08, delay: 0.55 });
scrub(".hero", "top top", "bottom top")
  .to(".hero-copy", { y: -120, opacity: 0 }, 0)
  .to(".scroll-hint", { opacity: 0 }, 0);

// ---- 2 · how it works: pinned, four steps, the world changes shape under each ----
const steps = $$(".step");
const flow = scrub(".flow", "top top", `+=${steps.length * 110}%`, { pin: ".flow-stage", anticipatePin: 1 });
flow.fromTo(".flow-progress i", { scaleX: 0 }, { scaleX: 1, duration: steps.length }, 0);
steps.forEach((step, i) => {
  if (i > 0) flow.fromTo(step, { autoAlpha: 0, y: 70, rotateX: -30, z: -100 }, { autoAlpha: 1, y: 0, rotateX: 0, z: 0, duration: 0.35, ease: "power2.out" }, i + 0.02);
  else flow.set(step, { autoAlpha: 1 }, 0);
  if (i < steps.length - 1) flow.to(step, { autoAlpha: 0, y: -70, rotateX: 30, z: -100, duration: 0.3, ease: "power2.in" }, i + 0.72);
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

// ---- 3 · the app tilts up into view; the cards drift past ----
scrub(".showcase", "top bottom", "center center")
  .fromTo(".device", { rotateX: 30, scale: 0.9, y: 60 }, { rotateX: 0, scale: 1, y: 0 }, 0);
gsap.utils.toArray(".float-card").forEach((card, i) => {
  scrub(".showcase", "top bottom", "bottom top").fromTo(card, { y: 100 + i * 40 }, { y: -100 - i * 50 }, 0);
  gsap.from(card, { autoAlpha: 0, scale: 0.85, duration: 1, ease: "back.out(1.6)", delay: 0.25 + i * 0.2, scrollTrigger: { trigger: ".device", start: "top 55%" } });
});
gsap.from(".showcase-copy > *", { y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".showcase-copy", start: "top 80%" } });
// the screenshot in a light or a dark theme
$$(".shot-toggle button").forEach((b) => b.addEventListener("click", () => {
  $$(".shot-toggle button").forEach((x) => x.classList.toggle("on", x === b));
  const src = `/assets/app-${b.dataset.shot}.webp`;
  $("[data-shot-src]").srcset = src;
  $(".dv-shot").src = src;
}));

// ---- 4 · features: tiles rise in; modes and the chat lane too ----
gsap.from(".features .section-head > *", { y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".features", start: "top 75%" } });
gsap.set(".tile, .mode-card", { autoAlpha: 0 });
ScrollTrigger.batch(".tile, .mode-card", {
  start: "top 90%",
  once: true,
  onEnter: (batch) => gsap.fromTo(batch, { autoAlpha: 0, y: 50 }, { autoAlpha: 1, y: 0, duration: 1, ease: "expo.out", stagger: 0.07 }),
});
gsap.from(".modes .section-head > *", { y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".modes", start: "top 75%" } });

// ---- 5 · models: a 3D ring that turns as you scroll (and slowly on its own) ----
const ring = $(".ring");
// on a phone the ring takes every other chip, so they don't pile up
const chips = $$(".ring span").filter((c, i) => { const keep = !mobile || i % 2 === 0; if (!keep) c.remove(); return keep; });
let R = 0; // the ring's radius follows the screen's width
const sizeRing = () => { R = Math.round(Math.min(520, Math.max(150, innerWidth * (mobile ? 0.46 : 0.4)))); };
sizeRing();
addEventListener("resize", sizeRing);
const stepDeg = 360 / chips.length;
const ringState = { scroll: 0, auto: 0 };
gsap.ticker.add((_, dt) => {
  if (!reduced) ringState.auto += dt * 0.006;
  const rot = ringState.scroll + ringState.auto;
  ring.style.transform = `rotateX(-14deg) rotateY(${-rot}deg)`;
  chips.forEach((c, i) => {
    const a = stepDeg * i;
    c.style.transform = `translate(-50%, -50%) rotateY(${a}deg) translateZ(${R}px) rotateY(${rot - a}deg) rotateX(14deg)`;
    const facing = (Math.cos(((a - rot) * Math.PI) / 180) + 1) / 2;
    c.style.opacity = (0.1 + facing * 0.9).toFixed(3);
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
gsap.from(".dl-title .line > span", { yPercent: 110, rotate: 3, duration: 1.2, ease: "expo.out", stagger: 0.1, scrollTrigger: { trigger: ".dl-card", start: "top 70%" } });
gsap.from([".download .lead", ".download .cta-row", ".dl-steps li", ".download .fine"], { y: 30, autoAlpha: 0, duration: 1, ease: "power3.out", stagger: 0.08, scrollTrigger: { trigger: ".dl-card", start: "top 70%" } });

// magnetic primary buttons
if (!mobile) $$(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.25); y((e.clientY - r.top - r.height / 2) * 0.35); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

// a click on empty space sends a ring out from the core
addEventListener("pointerdown", (e) => {
  if (e.button === 0 && !e.target.closest("a, button, input, .device, .tile, .mode-card")) scene.burst(0.8);
});

// ---- the 3D world along the page ----
// One track of keyframes keyed to scroll positions; every frame the scene takes the eased mix of
// the two keyframes around the current scroll. (One owner for the scene's state, so sections
// can't fight over it.)
const KEYS = ["zoom", "spin", "tilt", "shiftX", "shiftY", "mark", "core", "net", "plan", "code", "ring", "spread", "activity", "dim"];
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
// one shape at a time (the scene blends whatever weights it gets; a keyframe names its shape)
const only = (name, w = 1) => ({ mark: 0, core: 0, net: 0, plan: 0, code: 0, ring: 0, spread: 0, [name]: w });
function buildTrack() {
  const f = marks.flow, fl = (x) => f.start + (f.end - f.start) * (x / 4.2); // positions on the story's timeline
  const ft = marks.feat, mm = marks.models, mz = mobile ? -1.6 : 0; // phones: the ring further back
  track = [
    // the mark, fitted into the hero's stage box (beside the headline, or above it on portrait screens)
    [0, { ...heroFit(), spin: 0, tilt: 0.1, ...only("mark"), activity: 0.3, dim: 1 }],
    // 01 · your words coil round the hub
    [marks.hero.end, { ...storyFit("core", 0.85), spin: 0.3, tilt: 0.5, mark: 0.45, core: 0.55, activity: 0.7 }],
    [fl(0.55), { ...only("core"), ...storyFit("core", 0.85), spin: 0.6, tilt: 0.55 }],
    // 02 · the plan is laid out beside the list
    [fl(1.25), { ...only("plan"), ...storyFit("plan", 0.96), spin: 0.15, tilt: 0.12, activity: 0.5 }],
    [fl(1.75), { spin: 0.3 }],
    // 03 · the work spreads to agents along live links
    [fl(2.3), { ...only("net"), ...storyFit("net", 0.95), activity: 1.1, spin: 0.9, tilt: 0.18 }],
    [fl(2.8), { spin: 1.2 }],
    // 04 · the file is written by the orange agent
    [fl(3.3), { ...only("code"), ...storyFit("code", 0.96), spin: 0.2, tilt: 0.15, activity: 0.9 }],
    [f.end, { spin: 0.45 }],
    // the app and the features: the agents keep working far behind the page, faint
    [marks.show.end, { ...only("net"), zoom: -4, spin: 1.6, tilt: 0.3, shiftX: 0, shiftY: 0, activity: 0.6, dim: 0.12 }],
    [ft.start + (ft.end - ft.start) * 0.4, { zoom: -3, spin: 2.2, tilt: 0.35, dim: 0.08 }],
    // models: the network opens into the ring of models, under the chips
    [ft.end, { net: 0.4, ring: 0.6, zoom: -2, spin: 2.8, tilt: 0.45, dim: 0.08 }],
    [mm.start + (mm.end - mm.start) * 0.12, { ...only("ring"), zoom: -1.8 + mz, spin: 3.0, tilt: 0.6, shiftY: -1.3, dim: 0.08 }],
    [mm.start + (mm.end - mm.start) * 0.45, { ...only("ring"), zoom: -1.4 + mz, spin: 3.3, tilt: 0.6, shiftY: -1.3, dim: mobile ? 0.5 : 0.75 }],
    [mm.end, { ...only("ring"), zoom: -2.2 + mz, spin: 3.8, tilt: 0.6, shiftY: -1.3, dim: 0.08 }],
    // the call to action: everything pours back into the mark
    [marks.dl.start + (marks.dl.end - marks.dl.start) * 0.5, { ...only("mark"), ...ctaFit(marks.dl.end), spin: 2 * Math.PI - 0.6, tilt: 0.1, activity: 0.3, dim: 0.4 }],
    [marks.dl.end, { ...only("mark"), ...ctaFit(marks.dl.end), spin: 2 * Math.PI, tilt: 0.1, activity: 0.3, dim: 1 }],
  ];
  track.sort((p, q) => p[0] - q[0]);
  // fill in every value so each keyframe is complete (unchanged values carry forward)
  let prev = track[0][1];
  track = track.map(([y, v]) => { prev = { ...prev, ...v }; return [y, prev]; });
}
const ease = (x) => x * x * (3 - 2 * x);
const intro = { k: 0 };
gsap.to(intro, { k: 1, duration: 2.6, ease: "power3.out" }); // the strands gather into the mark
gsap.ticker.add(() => {
  if (!track.length) return;
  const y = lenis ? lenis.scroll : scrollY;
  let i = 0;
  while (i < track.length - 2 && y > track[i + 1][0]) i++;
  const [y0, a] = track[i], [y1, b] = track[i + 1];
  const t = ease(Math.min(1, Math.max(0, (y - y0) / Math.max(1, y1 - y0))));
  for (const k of KEYS) state[k] = a[k] + (b[k] - a[k]) * t;
  state.spread += (1 - intro.k) * 1.2;
});
ScrollTrigger.addEventListener("refresh", buildTrack);
buildTrack();
addEventListener("load", () => ScrollTrigger.refresh());
