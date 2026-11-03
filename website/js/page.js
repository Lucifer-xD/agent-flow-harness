// The harness line on every page but the home page (which scripts its own route in main.js): on a
// page with a hero stage box (`[data-stage]`) the line opens into the mark there and runs down the
// page's outer gutter, the dots riding it as you scroll. Pages without a stage show no line.
// Also: magnetic primary buttons. (Entrances and section menus are in layout.js.)
import { createScene } from "./scene.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 760px)").matches;
const { gsap } = window;

const name = document.body.dataset.scene || "docs";
const stage = document.querySelector("[data-stage]");
const scene = createScene(document.querySelector("#scene"), { mobile, reduced, lite: !stage });
window.afhScene = scene; // for poking at the line from the console

const box = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top + scrollY, width: r.width, height: r.height, right: r.right, bottom: r.top + scrollY + r.height }; };
function buildRoute() {
  if (!stage) return;
  const W = innerWidth, S = box(stage), pageH = document.documentElement.scrollHeight;
  const main = document.querySelector("main .wrap, main section") || document.body;
  const M = box(main);
  const side = S.left + S.width / 2 < W / 2 ? "left" : "right"; // the stage's side of the page: the line runs down that gutter
  const gx = side === "left" ? Math.max(mobile ? 22 : 44, M.left - 60) : Math.min(W - (mobile ? 22 : 44), M.right + 60);
  const pts = [];
  const P = (x, y) => pts.push({ x, y });
  if (side === "left") { P(S.right + 24, S.top + S.height * 0.5); P(S.right - S.width * 0.1, S.bottom + 90); P(gx, S.bottom + 260); }
  else { P(S.right + 20, S.top + S.height * 0.5); P(W - 30, S.bottom + 100); P(gx, S.bottom + 260); }
  // down the gutter, with a slow wave so it reads as a cable, off the bottom of the page
  for (let y = S.bottom + 600; y < pageH + 300; y += 520) P(gx + (side === "left" ? 1 : -1) * Math.sin(y / 700) * 12, y);
  P(gx, pageH + 400);
  scene.setRoute({ marks: [S], points: pts, radius: Math.max(6, Math.min(11, W * 0.0082)), pageHeight: pageH });
}
gsap.ticker.add(() => { scene.state.scroll = scrollY; });
buildRoute();
addEventListener("load", buildRoute);
addEventListener("resize", buildRoute);
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
