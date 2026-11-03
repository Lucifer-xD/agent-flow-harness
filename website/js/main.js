// The home page: smooth scrolling (Lenis), scroll-driven motion (GSAP ScrollTrigger) and the 3D
// mark that floats in front of the page. It hangs over the product shot in the hero, becomes each
// chapter's shape beside the words as the chapters stack up, and comes back whole on the closing
// call. Everywhere else it fades out so it never sits on text.
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
const SHAPES = ["mark", "core", "net", "plan", "code", "ring", "spread"];
const only = (name) => Object.fromEntries(SHAPES.map((k) => [k, k === name ? 1 : 0]));
const tween = (to, duration = 1.2) => gsap.to(state, { ...to, duration: reduced ? 0.01 : duration, ease: "power3.inOut", overwrite: "auto" });
const intro = { k: 0 }; // the light gathers into the mark on load (drives `dim` and `spread`)

// ---- smooth scroll ----
let lenis = null;
if (!reduced && window.Lenis && !location.search.includes("nolenis")) { // ?nolenis: plain scrolling, for screenshots
  lenis = new window.Lenis({ lerp: 0.085, wheelMultiplier: 0.9 });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
}
const scrollNow = () => (lenis ? lenis.scroll : scrollY);
$$('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => {
  const target = $(a.getAttribute("href"));
  if (!target) return;
  e.preventDefault();
  if (lenis) lenis.scrollTo(target, { offset: -70, duration: 1.6 });
  else target.scrollIntoView({ behavior: "smooth" });
}));
const scrub = (trigger, start, end, opts = {}) => gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger, start, end, scrub: reduced ? true : 1, ...opts } });

// ---- 1 · hero: the words rise, the product shot flattens up into view, the mark hangs over it ----
gsap.from(".hero .display .line > span", { yPercent: 110, rotate: 3, duration: 1.3, ease: "expo.out", stagger: 0.09, delay: 0.15 });
gsap.from([".hero .eyebrow", ".hero .lead", ".hero .cta-row"], { y: 24, opacity: 0, duration: 1.1, ease: "power3.out", stagger: 0.08, delay: 0.5 });
gsap.fromTo(".shot", { rotateX: 16, y: 70, opacity: 0 }, { rotateX: 0, y: 0, opacity: 1, duration: 1.6, ease: "expo.out", delay: 0.65 });
gsap.from(".proof", { y: 16, opacity: 0, duration: 1, ease: "power3.out", delay: 1.1 });
// ---- the mark is pinned to a box on the page ----
// Every frame the world is framed into the anchor box where it is *right now*, so the mark scrolls
// with the page like anything else in it, and it fades as its box leaves the screen. Sections only
// hand the anchor over (and change the shape); they never place the world themselves.
const anchor = { el: null, name: "mark", fill: 0.92 };
const setAnchor = (el, name, fill) => { anchor.el = el; anchor.name = name; anchor.fill = fill; };
const heroStage = $("[data-stage]");
setAnchor(heroStage, "mark", 0.92);
Object.assign(state, { ...only("mark"), spin: 0, tilt: 0.08, activity: 0.3, dim: 0 });
{ const f = scene.fit(heroStage.getBoundingClientRect(), 0.92, "mark"); Object.assign(state, f); }
const visibility = (r) => { // 1 with the box well inside the screen, 0 once it has left
  const edge = Math.min(140, innerHeight * 0.18);
  return Math.min(1, Math.max(0, (r.bottom - 30) / edge)) * Math.min(1, Math.max(0, (innerHeight - r.top - 30) / edge));
};
gsap.ticker.add((_, dtMs) => {
  if (!anchor.el) return;
  const r = anchor.el.getBoundingClientRect();
  const f = scene.fit(r, anchor.fill, anchor.name);
  const k = 1 - Math.exp(-Math.min(0.1, dtMs / 1000) * 14); // quick, but no jitter
  state.zoom += (f.zoom - state.zoom) * k;
  state.shiftX += (f.shiftX - state.shiftX) * k;
  state.shiftY += (f.shiftY - state.shiftY) * k;
  state.dim = visibility(r) * intro.k;
});
ScrollTrigger.create({ trigger: ".hero-shot", start: "top 40%", onLeaveBack: () => { setAnchor(heroStage, "mark", 0.92); tween({ ...only("mark"), spin: 0, tilt: 0.08, activity: 0.3 }); } });

// ---- 2 · chapters: each card sticks; while it is the one in front, the mark is its shape ----
const chapters = $$(".chapter");
const LOOK = {
  core: { spin: 0.5, tilt: 0.5, activity: 0.7, fill: 0.82 },
  plan: { spin: 0.1, tilt: 0.1, activity: 0.5, fill: 0.68 },
  net: { spin: 0.9, tilt: 0.2, activity: 1.1, fill: 0.84 },
  code: { spin: 0.2, tilt: 0.15, activity: 0.9, fill: 0.8 },
};
const showChapter = (card) => {
  const name = card.dataset.shape;
  const { fill, ...look } = LOOK[name];
  setAnchor($(".ch-world", card), name, fill);
  tween({ ...only(name), ...look });
};
chapters.forEach((card, i) => {
  const next = chapters[i + 1];
  ScrollTrigger.create({
    trigger: card, start: "top 62%",
    endTrigger: next || card, end: next ? "top 62%" : "bottom 35%",
    onEnter: () => showChapter(card), onEnterBack: () => showChapter(card),
  });
  // the cards behind shrink back a little as the next one slides over them
  if (next) scrub(next, "top 80%", "top 20%").to(card, { scale: 0.96, opacity: 0.85 }, 0);
});

// code streams into the Workbench's Live card
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
ScrollTrigger.create({ trigger: ".workbench", start: "top 80%", once: true, onEnter: () => streamCode($("[data-live]"), 18) });

// ---- 3 · the workbench gallery: arrows slide it a card at a time ----
const track = $(".wb-track");
$$("[data-wb]").forEach((b) => b.addEventListener("click", () => {
  const card = $(".wb-card", track);
  track.scrollBy({ left: Number(b.dataset.wb) * (card.getBoundingClientRect().width + 16), behavior: "smooth" });
}));
gsap.set(".wb-card", { autoAlpha: 0 });
ScrollTrigger.batch(".wb-card", { start: "top 90%", once: true, onEnter: (batch) => gsap.fromTo(batch, { autoAlpha: 0, y: 40 }, { autoAlpha: 1, y: 0, duration: 0.9, ease: "expo.out", stagger: 0.08 }) });

// ---- 4 · modes explorer ----
$$(".mode-tabs button").forEach((b) => b.addEventListener("click", () => {
  $$(".mode-tabs button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
  $$(".mode-pane").forEach((p) => p.classList.toggle("on", p.dataset.mode === b.dataset.mode));
}));

// the screenshot in a light or a dark theme
$$(".shot-toggle button").forEach((b) => b.addEventListener("click", () => {
  $$(".shot-toggle button").forEach((x) => x.classList.toggle("on", x === b));
  const src = `/assets/app-${b.dataset.shot}.webp`;
  $("[data-shot-src]").srcset = src;
  $(".dv-shot").src = src;
}));

// ---- 5 · entrances and numbers ----
gsap.set(".si-card, .logo-wall span, .stat", { autoAlpha: 0 });
ScrollTrigger.batch(".si-card, .stat", { start: "top 90%", once: true, onEnter: (batch) => gsap.fromTo(batch, { autoAlpha: 0, y: 40 }, { autoAlpha: 1, y: 0, duration: 0.9, ease: "expo.out", stagger: 0.07 }) });
ScrollTrigger.batch(".logo-wall span", { start: "top 92%", once: true, batchMax: 40, onEnter: (batch) => gsap.fromTo(batch, { autoAlpha: 0, scale: 0.8 }, { autoAlpha: 1, scale: 1, duration: 0.7, ease: "back.out(1.4)", stagger: 0.025 }) });
["modes", "wall", "signin", "chapters"].forEach((cls) => gsap.from(`.${cls} .section-head > *`, { y: 36, autoAlpha: 0, stagger: 0.1, duration: 1, ease: "power3.out", scrollTrigger: { trigger: `.${cls}`, start: "top 78%" } }));
gsap.from(".mode-explorer", { y: 50, autoAlpha: 0, duration: 1.1, ease: "expo.out", scrollTrigger: { trigger: ".mode-explorer", start: "top 85%" } });
$$("[data-count]").forEach((el) => {
  const to = Number(el.dataset.count);
  const o = { v: 0 };
  gsap.to(o, { v: to, duration: 1.6, ease: "power2.out", scrollTrigger: { trigger: el, start: "top 90%" }, onUpdate: () => { el.textContent = Math.round(o.v).toLocaleString("en-US"); } });
});

// ---- 6 · the closing call: the mark comes back whole, in the middle of the card ----
gsap.from(".cta-title .line > span", { yPercent: 110, rotate: 3, duration: 1.2, ease: "expo.out", stagger: 0.1, scrollTrigger: { trigger: ".cta", start: "top 70%" } });
gsap.from([".cta .lead", ".cta .cta-row", ".cta .fine"], { y: 30, autoAlpha: 0, duration: 1, ease: "power3.out", stagger: 0.08, scrollTrigger: { trigger: ".cta", start: "top 70%" } });
const lastChapter = chapters[chapters.length - 1];
ScrollTrigger.create({ trigger: ".cta", start: "top 85%",
  onEnter: () => { setAnchor($("[data-cta-stage]"), "mark", 0.94); tween({ ...only("mark"), spin: 2 * Math.PI, tilt: 0.08, activity: 0.3 }, 1.4); },
  onLeaveBack: () => { if (lastChapter) showChapter(lastChapter); } });

// magnetic primary buttons
if (!mobile) $$(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.25); y((e.clientY - r.top - r.height / 2) * 0.35); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});
// a click on empty space sends a ring out from the mark
addEventListener("pointerdown", (e) => {
  if (e.button === 0 && !e.target.closest("a, button, input, .shot, .chapter, .wb-card, .mode-explorer")) scene.burst(0.8);
});

// the mark gathers out of the dark into place, then everything is laid out again once fonts and images settle
gsap.to(intro, { k: 1, duration: 2.4, ease: "power3.out", onUpdate: () => { state.spread = (1 - intro.k) * 1.2; } });
addEventListener("load", () => {
  ScrollTrigger.refresh();
  const at = new URLSearchParams(location.search).get("at"); // ?at=.selector: jump straight to a section (for screenshots)
  const el = at && document.querySelector(at);
  if (el) setTimeout(() => scrollTo(0, el.getBoundingClientRect().top + scrollY - 84), 80);
});
