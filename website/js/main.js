// The home page: smooth scrolling (Lenis), scroll-driven motion (GSAP ScrollTrigger) and the studio
// set of ceramic objects that rest on the page. Each section lays the objects out next to its own
// elements (in CSS pixels, measured every frame, so they scroll with the page); sections hand the
// layout over as you scroll, and objects a layout doesn't use shrink away.
import { createScene } from "./scene.js";
import { CODE } from "./code-sample.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap, ScrollTrigger } = window;
gsap.registerPlugin(ScrollTrigger);
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const scene = createScene($("#scene"), { mobile, reduced });
window.afhScene = scene; // for poking at the set from the console

// ---- smooth scroll ----
let lenis = null;
if (!reduced && window.Lenis && !location.search.includes("nolenis")) { // ?nolenis: plain scrolling, for screenshots
  lenis = new window.Lenis({ lerp: 0.085, wheelMultiplier: 0.9 });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
}
$$('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => {
  const target = $(a.getAttribute("href"));
  if (!target) return;
  e.preventDefault();
  if (lenis) lenis.scrollTo(target, { offset: -70, duration: 1.6 });
  else target.scrollIntoView({ behavior: "smooth" });
}));
const scrub = (trigger, start, end, opts = {}) => gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger, start, end, scrub: reduced ? true : 1, ...opts } });

// ---- the set: layouts, one active at a time, measured every frame ----
// A layout is a function of its element's rect returning placements {id: {x, y, r, rot}} in CSS px.
// Objects sit beside the element, never on text; the ones a layout leaves out shrink away.
const rect = (el) => el.getBoundingClientRect();
const visibility = (r) => { // 1 with the element well inside the screen, 0 once it has left
  const edge = Math.min(160, innerHeight * 0.2);
  return Math.min(1, Math.max(0, (r.bottom - 20) / edge)) * Math.min(1, Math.max(0, (innerHeight - r.top - 20) / edge));
};
const LAYOUTS = {
  // the hero: objects resting round the product shot, the hub on its top edge
  hero: (R) => {
    const side = R.left; // room beside the shot
    const u = Math.min(1, side / 180); // smaller screens: smaller objects, tucked to the edges
    const out = {
      sphereB: { x: R.left + R.width * 0.1, y: R.top - 22, r: 22 + 8 * u },
      cube: { x: R.right - R.width * 0.1, y: R.top - 26, r: 26 + 12 * u, rot: 0.2 },
    };
    if (side > 70) Object.assign(out, { // beside the shot, resting against its edges
      hub: { x: R.left - (30 + 26 * u), y: R.top + 90, r: 30 + 18 * u },
      torus: { x: R.left - (40 + 40 * u), y: R.top + R.height * 0.64, r: 44 + 40 * u },
      pill: { x: R.right + (34 + 30 * u), y: R.top + 110, r: 36 + 30 * u, rot: 0.1 },
      sphereA: { x: R.right + (32 + 34 * u), y: R.top + R.height * 0.68, r: 32 + 28 * u },
    });
    return out;
  },
  // 01 · the hub takes the request: the hub with the torus and a sphere round it
  core: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    hub: { x: cx - s * 0.12, y: cy + s * 0.02, r: s * 0.2 },
    torus: { x: cx + s * 0.26, y: cy - s * 0.14, r: s * 0.22, rot: 0.6 },
    sphereB: { x: cx - s * 0.36, y: cy - s * 0.26, r: s * 0.09 },
    sphereA: { x: cx + s * 0.18, y: cy + s * 0.3, r: s * 0.12 },
  }; },
  // 02 · the plan: a cube, a pill and spheres laid in a row, like steps
  plan: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    cube: { x: cx - s * 0.32, y: cy - s * 0.1, r: s * 0.17, rot: 0.3 },
    pill: { x: cx + s * 0.02, y: cy + s * 0.08, r: s * 0.2, rot: -0.3 },
    sphereA: { x: cx + s * 0.36, y: cy - s * 0.16, r: s * 0.13 },
    sphereB: { x: cx + s * 0.3, y: cy + s * 0.3, r: s * 0.08 },
  }; },
  // 03 · the agents: the hub in the middle, the others round it
  net: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    hub: { x: cx, y: cy, r: s * 0.16 },
    sphereA: { x: cx - s * 0.34, y: cy - s * 0.2, r: s * 0.12 },
    sphereB: { x: cx + s * 0.34, y: cy - s * 0.24, r: s * 0.08 },
    cube: { x: cx + s * 0.32, y: cy + s * 0.2, r: s * 0.12, rot: 0.5 },
    pill: { x: cx - s * 0.3, y: cy + s * 0.26, r: s * 0.14, rot: 0.7 },
    torus: { x: cx + s * 0.02, y: cy - s * 0.4, r: s * 0.1, rot: 1 },
  }; },
  // 04 · the file lands: the torus and the pill, a sphere rolling in
  code: (B) => { const s = Math.min(B.width, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    torus: { x: cx - s * 0.2, y: cy, r: s * 0.26, rot: 0.3 },
    pill: { x: cx + s * 0.3, y: cy - s * 0.16, r: s * 0.2, rot: 0.9 },
    sphereB: { x: cx + s * 0.28, y: cy + s * 0.28, r: s * 0.1 },
  }; },
  // the closing call: the whole set gathered round the title
  cta: (B) => { const s = Math.min(B.width * 0.6, B.height), cx = B.left + B.width / 2, cy = B.top + B.height / 2; return {
    hub: { x: cx, y: cy - s * 0.08, r: s * 0.22 },
    torus: { x: cx - s * 0.7, y: cy + s * 0.06, r: s * 0.26, rot: 0.5 },
    pill: { x: cx + s * 0.66, y: cy - s * 0.04, r: s * 0.22, rot: 0.2 },
    sphereA: { x: cx + s * 0.38, y: cy + s * 0.36, r: s * 0.14 },
    sphereB: { x: cx - s * 0.36, y: cy - s * 0.38, r: s * 0.09 },
    cube: { x: cx + s * 0.3, y: cy - s * 0.4, r: s * 0.12, rot: 0.4 },
  }; },
};
let active = { el: $(".shot"), layout: "hero" };
const setLayout = (el, layout) => { active = { el, layout }; };
const intro = { k: 0 };
gsap.to(intro, { k: 1, duration: reduced ? 0.01 : 1.6, ease: "power2.out", delay: 0.5 });
gsap.ticker.add(() => {
  if (!active.el) { scene.hideAll(); return; }
  const r = rect(active.el);
  const vis = visibility(r) * intro.k;
  const out = LAYOUTS[active.layout](r);
  for (const id of scene.ids) {
    if (out[id]) scene.place(id, { ...out[id], vis });
    else scene.hide(id);
  }
});

// ---- 1 · hero: the words rise, the product shot flattens up into view ----
gsap.from(".hero .display .line > span", { yPercent: 110, rotate: 3, duration: 1.3, ease: "expo.out", stagger: 0.09, delay: 0.15 });
gsap.from([".hero .eyebrow", ".hero .lead", ".hero .cta-row"], { y: 24, opacity: 0, duration: 1.1, ease: "power3.out", stagger: 0.08, delay: 0.5 });
gsap.fromTo(".shot", { rotateX: 16, y: 70, opacity: 0 }, { rotateX: 0, y: 0, opacity: 1, duration: 1.6, ease: "expo.out", delay: 0.65 });
gsap.from(".proof", { y: 16, opacity: 0, duration: 1, ease: "power3.out", delay: 1.1 });
ScrollTrigger.create({ trigger: ".hero-shot", start: "top 40%", onLeaveBack: () => setLayout($(".shot"), "hero") });

// ---- 2 · chapters: each card sticks; while it is the one in front, the set is its scene ----
const chapters = $$(".chapter");
const showChapter = (card) => setLayout($(".ch-world", card), card.dataset.shape);
chapters.forEach((card, i) => {
  const next = chapters[i + 1];
  ScrollTrigger.create({
    trigger: card, start: "top 62%",
    endTrigger: next || card, end: next ? "top 62%" : "bottom 35%",
    onEnter: () => showChapter(card), onEnterBack: () => showChapter(card),
  });
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

// ---- 6 · the closing call: the whole set gathers round the title ----
gsap.from(".cta-title .line > span", { yPercent: 110, rotate: 3, duration: 1.2, ease: "expo.out", stagger: 0.1, scrollTrigger: { trigger: ".cta", start: "top 70%" } });
gsap.from([".cta .lead", ".cta .cta-row", ".cta .fine"], { y: 30, autoAlpha: 0, duration: 1, ease: "power3.out", stagger: 0.08, scrollTrigger: { trigger: ".cta", start: "top 70%" } });
const lastChapter = chapters[chapters.length - 1];
ScrollTrigger.create({ trigger: ".cta", start: "top 85%",
  onEnter: () => setLayout($("[data-cta-stage]"), "cta"),
  onLeaveBack: () => { if (lastChapter) showChapter(lastChapter); } });

// magnetic primary buttons
if (!mobile) $$(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.25); y((e.clientY - r.top - r.height / 2) * 0.35); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

addEventListener("load", () => {
  ScrollTrigger.refresh();
  const at = new URLSearchParams(location.search).get("at"); // ?at=.selector: jump straight to a section (for screenshots)
  const el = at && document.querySelector(at);
  if (el) setTimeout(() => scrollTo(0, el.getBoundingClientRect().top + scrollY - 84), 80);
});
