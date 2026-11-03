// The harness line on every page but the home page (which scripts its own route in main.js): on a
// page with a hero stage box (`[data-stage]`) the line opens into the mark there and runs down the
// page's outer gutter, the dots riding it as you scroll. Pages without a stage show no line.
// Also: magnetic primary buttons. (Entrances and section menus are in layout.js.)
import { createScene, markBounds } from "./scene.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap } = window;

const name = document.body.dataset.scene || "docs";
const stage = document.querySelector("[data-stage]");
const scene = createScene(document.querySelector("#scene"), { mobile, reduced, lite: !stage });
window.afhScene = scene; // for poking at the line from the console

// layout boxes, not painted ones, so entrances don't move the route
const box = (el) => {
  let left = 0, top = 0;
  for (let e = el; e; e = e.offsetParent) { left += e.offsetLeft; top += e.offsetTop; }
  return { left, top, width: el.offsetWidth, height: el.offsetHeight, right: left + el.offsetWidth, bottom: top + el.offsetHeight };
};
function buildRoute() {
  if (!stage) return;
  const W = innerWidth, S = box(stage), m = markBounds(S), narrow = W <= 760, pageH = document.documentElement.scrollHeight;
  const main = document.querySelector("main .wrap, main section") || document.body;
  const M = box(main);
  const side = S.left + S.width / 2 < W * 0.45 ? "left" : "right"; // the stage's side of the page: the line runs down that gutter
  const edge = W >= 1280 ? 44 : Math.max(7, Math.min(64, Math.max(18, W * 0.045)) * 0.42), gx = side === "left" ? Math.max(edge, M.left - 60) : Math.min(W - edge, M.right + 60);
  const pts = [];
  const P = (x, y) => pts.push({ x, y });
  // the strands gather below the mark, then the line swings into the gutter
  if (side === "left") { P(m.right + 24, m.bottom + m.dot + 60); P(m.right - 20, m.bottom + m.dot + 150); P(gx, S.bottom + 250); }
  else { P(gx, m.bottom + m.dot + 24); P(gx, S.bottom + 260); }
  // down the gutter, with a slow wave so it reads as a cable, off the bottom of the page
  for (let y = S.bottom + 600; y < pageH + 300; y += 520) P(gx + (side === "left" ? 1 : -1) * Math.sin(y / 700) * 12, y);
  P(gx, pageH + 400);
  scene.setRoute({ marks: [S], points: pts, radius: narrow ? 4.5 : W >= 1280 ? Math.max(6, Math.min(11, W * 0.0082)) : Math.min(8, W * 0.0075), tight: W < 1280, pageHeight: pageH });
}
gsap.ticker.add(() => { scene.state.scroll = scrollY; });
buildRoute();
addEventListener("load", buildRoute);
let lastW = innerWidth; // a phone's address bar sliding away is a resize too, but it moves nothing
addEventListener("resize", () => { if (innerWidth !== lastW) { lastW = innerWidth; buildRoute(); } });
let routeTimer = 0; // the layout moves as fonts and images arrive
new ResizeObserver(() => { clearTimeout(routeTimer); routeTimer = setTimeout(buildRoute, 120); }).observe(document.body);
document.fonts?.ready.then(buildRoute);
if (name === "lost") scene.state.activity = 0.1;

// magnetic primary buttons
if (!mobile && !reduced) document.querySelectorAll(".btn-primary").forEach((b) => {
  const x = gsap.quickTo(b, "x", { duration: 0.6, ease: "power3" }), y = gsap.quickTo(b, "y", { duration: 0.6, ease: "power3" });
  b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) * 0.22); y((e.clientY - r.top - r.height / 2) * 0.32); });
  b.addEventListener("pointerleave", () => { x(0); y(0); });
});

export { scene };
