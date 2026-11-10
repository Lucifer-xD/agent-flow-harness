// The home page: the film at the top (js/film.js, a pinned 3D stage your scroll plays), then the
// app, the live file, the modes, the provider logos and the counters.
import { CODE } from "./code-sample.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const onSight = (el, fn, margin = "0px 0px -15% 0px") => {
  if (!el) return;
  const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: margin });
  io.observe(el);
};

// ---- the film ----
$$("[data-mark-big]").forEach((el) => { el.innerHTML = window.afhMarkSvg?.(240) || ""; });
const film = $(".film");
if (film) {
  import("./film.js")
    .then(({ createFilm }) => { window.afhFilm = createFilm(film); if (!window.afhFilm) film.classList.add("film-static"); })
    .catch((e) => { console.error(e); film.classList.add("film-static"); });
}

// ---- the turn chip: a turn, as the app shows it, on a loop ----
const chip = $(".turn-chip");
if (chip) {
  const title = $("[data-tc-title]", chip), bits = $("[data-tc-bits]", chip), time = $("[data-tc-time]", chip);
  const STEPS = ["Reading the project", "Read 6 files", "Writing the plan", "Editing login.tsx", "Edited 3 files", "Running npm test", "12 tests passed"];
  let t0 = performance.now(), i = 0, done = false;
  const fmt = (s) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`);
  const tick = () => {
    const s = Math.floor((performance.now() - t0) / 1000) * 4; // a turn runs four times faster here
    if (!done) {
      time.textContent = fmt(s);
      const k = Math.min(STEPS.length - 1, Math.floor(s / 5));
      if (k !== i) { i = k; bits.textContent = STEPS[k]; }
      if (s >= 36) {
        done = true;
        chip.classList.add("done");
        title.textContent = `Worked for ${fmt(s)}`;
        bits.textContent = "Edited 3 files · Ran 1 command";
        time.textContent = "";
        setTimeout(() => { done = false; i = 0; chip.classList.remove("done"); title.textContent = "Working"; bits.textContent = STEPS[0]; t0 = performance.now(); }, 4200);
      }
    }
  };
  if (!reduced) setInterval(tick, 250);
  else { chip.classList.add("done"); title.textContent = "Worked for 32s"; bits.textContent = "Edited 3 files · Ran 1 command"; time.textContent = ""; }
}

// ---- how a turn works: the strand fills as you read down, each step lights as it's reached ----
const steps = $(".steps");
if (steps) {
  const items = $$(".step", steps);
  const update = () => {
    const r = steps.getBoundingClientRect(), mid = innerHeight * 0.6;
    const p = Math.min(1, Math.max(0, (mid - r.top) / r.height));
    steps.style.setProperty("--prog", p.toFixed(4));
    items.forEach((it) => it.classList.toggle("lit", it.getBoundingClientRect().top + 20 < mid));
  };
  addEventListener("scroll", update, { passive: true });
  addEventListener("resize", update);
  update();
}

// ---- the folding demo: the work is open while it runs, then folds; click the bar to open it ----
const fold = $(".fold-demo");
if (fold) {
  const work = $(".fd-work", fold);
  work.innerHTML = `<div class="fd-work-in">${work.innerHTML}</div>`;
  const bar = $(".fd-bar", fold);
  bar.removeAttribute("tabindex");
  fold.removeAttribute("aria-hidden");
  bar.setAttribute("aria-expanded", "true");
  const set = (shut) => { fold.classList.toggle("shut", shut); bar.setAttribute("aria-expanded", String(!shut)); };
  bar.addEventListener("click", () => set(!fold.classList.contains("shut")));
  onSight(fold, () => setTimeout(() => set(true), 2200), "0px 0px -30% 0px");
}

// ---- the live file: the agent types a login form ----
function streamCode(el, speed = 18) {
  if (!el) return;
  if (reduced) { el.innerHTML = CODE.map(([k, t]) => `<span class="${k}">${t.replace(/</g, "&lt;")}</span>`).join(""); return; }
  let part = 0, ch = 0, span = null;
  const caret = document.createElement("span");
  caret.className = "caret";
  const pre = el.parentElement;
  const step = () => {
    if (part >= CODE.length) { setTimeout(() => { el.textContent = ""; part = 0; ch = 0; span = null; step(); }, 2600); return; }
    const [kind, text] = CODE[part];
    if (!span) { span = document.createElement("span"); span.className = kind; el.append(span); }
    span.textContent = text.slice(0, ++ch);
    el.append(caret);
    pre.scrollTop = pre.scrollHeight;
    if (ch >= text.length) { part++; ch = 0; span = null; }
    setTimeout(step, text[ch - 1] === "\n" ? speed * 5 : speed + Math.random() * speed);
  };
  step();
}
onSight($("[data-live]"), () => streamCode($("[data-live]"), 22));

// ---- modes ----
$$(".mode-tabs button").forEach((b) => b.addEventListener("click", () => {
  $$(".mode-tabs button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
  $$(".mode-pane").forEach((p) => p.classList.toggle("on", p.dataset.mode === b.dataset.mode));
}));

// ---- provider logos (Lobe Icons, MIT), loaded when the wall comes near ----
onSight($("[data-logos]"), async () => {
  try {
    const { providerLogo } = await import("./provider-logos.js");
    $$("[data-logos] [data-p]").forEach((el) => {
      const svg = providerLogo(el.dataset.p, el.textContent);
      if (!svg) return;
      const box = document.createElement("span");
      box.className = "lg";
      box.setAttribute("aria-hidden", "true");
      box.innerHTML = svg;
      el.prepend(box);
    });
  } catch { /* the names alone are fine */ }
}, "0px 0px 400px 0px");

// ---- counters ----
$$("[data-count]").forEach((el) => {
  const to = Number(el.dataset.count);
  if (reduced || !to) return;
  el.textContent = "0";
  onSight(el, () => {
    const t0 = performance.now(), dur = 1400;
    const run = () => {
      const k = Math.min(1, (performance.now() - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(to * e).toLocaleString("en-US");
      if (k < 1) requestAnimationFrame(run);
    };
    run();
  });
});

// ---- the phone's mark ----
$$("[data-mark-svg]").forEach((el) => { el.innerHTML = window.afhMarkSvg?.(26) || ""; });
