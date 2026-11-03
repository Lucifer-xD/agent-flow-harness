// The home page: smooth scrolling (Lenis), scroll-driven motion (GSAP ScrollTrigger) and the harness
// line behind the page. The line opens into the mark beside the product shot, threads down the page
// along the gutters and behind the cards (never under text), and opens into the mark again on the
// closing call; its route is measured from the real elements, so it follows the layout on any screen.
import { createScene } from "./scene.js";
import { CODE } from "./code-sample.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap, ScrollTrigger } = window;
gsap.registerPlugin(ScrollTrigger);
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const scene = createScene($("#scene"), { mobile, reduced });
window.afhScene = scene; // for poking at the line from the console

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

// ---- the line's route, in page pixels ----
const box = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top + scrollY, width: r.width, height: r.height, right: r.right, bottom: r.top + scrollY + r.height }; };
function buildRoute() {
  const W = innerWidth, wide = W >= 1100;
  const gL = (b, pad = 70) => Math.max(mobile ? 22 : 44, b.left - pad);
  const gR = (b, pad = 70) => Math.min(W - (mobile ? 22 : 44), b.right + pad);
  const stage = box($("[data-stage]")), shot = box($(".shot")), cta = box($("[data-cta-stage]"));
  const chap = $$(".chapter").map(box), c0 = chap[0], cl = chap[chap.length - 1];
  const wb = box($(".wb-track")), modes = box($(".mode-explorer")), wall = box($(".logo-wall")), stats = box($(".stats")), si = box($(".si-grid")), phone = box($(".phone"));
  const pts = [];
  const P = (x, y) => pts.push({ x, y });
  // Crossing behind a card: in at one side's gutter, across inside the card's own bounds (where
  // the card hides it), out at the other gutter — so it never shows under the text around the card.
  const behind = (b, from, y0 = 0.2, y1 = 0.8) => {
    const [gIn, gOut] = from === "left" ? [gL(b, 30), gR(b, 30)] : [gR(b, 30), gL(b, 30)];
    const xIn = from === "left" ? b.left + b.width * 0.12 : b.right - b.width * 0.12;
    const xOut = from === "left" ? b.right - b.width * 0.12 : b.left + b.width * 0.12;
    P(gIn, b.top + b.height * y0); P(xIn, b.top + b.height * (y0 + 0.08)); P(xOut, b.top + b.height * (y1 - 0.08)); P(gOut, b.top + b.height * y1);
  };
  // out of the hero mark's right side, then down beside the product shot
  if (wide) { P(stage.right + 24, stage.top + stage.height * 0.5); P(gL(shot, 34), shot.top + shot.height * 0.62); }
  else { P(stage.right + 10, stage.top + stage.height * 0.5); P(gR(shot, 16), shot.top + shot.height * 0.3); }
  // the chapters: down the left gutter, then behind the stack of cards to the right gutter
  P(gL(c0, 56), c0.top - 140);
  behind({ ...c0, bottom: cl.bottom, height: cl.bottom - c0.top }, "left", 0.15, 0.85);
  // the workbench: across behind the gallery (seen in the gaps between the cards), right to left
  behind(wb, "right", 0.3, 0.8);
  // the modes: behind the explorer
  behind(modes, "left");
  // the model wall: down the right gutter past the heading and the chips, then behind the numbers
  P(gR(wall, 40), wall.top - 80);
  P(gR(wall, 10), wall.top + wall.height * 0.5);
  behind(stats, "right", 0.25, 0.75);
  // the sign-in cards: through the gaps
  behind(si, "left", 0.25, 0.8);
  // round the phone, keeping to its side of the page
  P(gR(phone, 20), phone.top - 40);
  P(phone.left + phone.width * 0.5, phone.top + phone.height * 0.5);
  P(gL(phone, 30), phone.bottom + 30);
  // into the closing mark from its left
  P(cta.left - 60, cta.top - 60);
  P(cta.left - 20, cta.top + cta.height * 0.3);
  scene.setRoute({ marks: [stage, cta], points: pts, radius: Math.max(6, Math.min(11, W * 0.0082)), pageHeight: document.documentElement.scrollHeight });
}
gsap.ticker.add(() => { scene.state.scroll = lenis ? lenis.scroll : scrollY; });
ScrollTrigger.addEventListener("refresh", buildRoute);
buildRoute();
// the layout moves as fonts and images arrive: rebuild the route whenever the page's height changes
let routeTimer = 0;
new ResizeObserver(() => { clearTimeout(routeTimer); routeTimer = setTimeout(buildRoute, 120); }).observe(document.body);
document.fonts?.ready.then(buildRoute);

// ---- 1 · hero: the words rise, the product shot flattens up into view ----
gsap.from(".hero .display .line > span", { yPercent: 110, rotate: 3, duration: 1.3, ease: "expo.out", stagger: 0.09, delay: 0.15 });
gsap.from([".hero .eyebrow", ".hero .lead", ".hero .cta-row"], { y: 24, opacity: 0, duration: 1.1, ease: "power3.out", stagger: 0.08, delay: 0.5 });
gsap.fromTo(".shot", { rotateX: 16, y: 70, opacity: 0 }, { rotateX: 0, y: 0, opacity: 1, duration: 1.6, ease: "expo.out", delay: 0.65 });
gsap.from(".proof", { y: 16, opacity: 0, duration: 1, ease: "power3.out", delay: 1.1 });

// ---- 2 · chapters: each card sticks; the ones behind shrink back as the next slides over ----
const chapters = $$(".chapter");
chapters.forEach((card, i) => {
  const next = chapters[i + 1];
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

// ---- 6 · the closing call ----
gsap.from(".cta-title .line > span", { yPercent: 110, rotate: 3, duration: 1.2, ease: "expo.out", stagger: 0.1, scrollTrigger: { trigger: ".cta", start: "top 70%" } });
gsap.from([".cta .lead", ".cta .cta-row", ".cta .fine"], { y: 30, autoAlpha: 0, duration: 1, ease: "power3.out", stagger: 0.08, scrollTrigger: { trigger: ".cta", start: "top 70%" } });

// magnetic primary buttons
if (!mobile) $$(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.25); y((e.clientY - r.top - r.height / 2) * 0.35); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

addEventListener("load", () => {
  ScrollTrigger.refresh();
  buildRoute();
  const at = new URLSearchParams(location.search).get("at"); // ?at=.selector: jump straight to a section (for screenshots)
  const el = at && document.querySelector(at);
  if (el) setTimeout(() => scrollTo(0, el.getBoundingClientRect().top + scrollY - 84), 80);
});
