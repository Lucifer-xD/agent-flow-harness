// The home page is a film you play with your scroll. One stage stays pinned while you scroll through
// it, and your scroll position is the playhead: scroll down to play, up to rewind, drag the bar to seek.
//
// The film follows one turn of AFH, told with the app's own mark at work:
//   Intro   the mark, beating exactly like the logo in the app while a model works
//   Say it  its three strands shoot out into one long braided rail: the turn, start to finish
//   Plan    the goal and the to-do list rise off the rail and tick themselves off
//   Work    the file being written and the terminal running the tests, then both fold into one line
//   Review  the diff, and the rewind
//   Models  the strands spin into three rings, with the providers orbiting them
//   Yours   everything settles back into the mark, at work again
//
// createFilm(section) returns false when there's no WebGL (the captions then show as plain text).
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { STRANDS, BEAT, drawn, leftDot, rightDot, glossy } from "./scene.js";

const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
const ramp = (p, a, b) => clamp01((p - a) / (b - a));
const sm = (t) => t * t * (3 - 2 * t);
const lerp = (a, b, t) => a + (b - a) * t;
const D2R = Math.PI / 180;

export const CHAPTERS = [
  { at: 0, name: "Intro" },
  { at: 0.12, name: "Say it" },
  { at: 0.3, name: "Plan" },
  { at: 0.46, name: "Work" },
  { at: 0.63, name: "Review" },
  { at: 0.72, name: "Models" },
  { at: 0.89, name: "Yours" },
];
const LENGTH = 48; // seconds, when it plays by itself

// world units: the logo's 240×140 box becomes 6 × 3.5
const U = 1 / 40, TUBE = 9 * U, DOT = 15 * U, DEPTH = 34 * U;
const END = new THREE.Vector3(34, 0, 0);
const RAIL = { x0: -2.6, x1: 36.6, y: -2.35, r: 0.5, turns: 7 };
const RING = 2.35;

// The camera: [progress, target x y z, yaw°, pitch°, frame width, frame height]. Between two keys it
// eases, so it holds still-ish while you read and travels in between.
const KEYS = [
  [0.0, 0, 0, 0, 0, 3, 5.4, 3.5],
  [0.055, 0, 0, 0, -28, 11, 6.0, 4.0],
  [0.115, 1.6, -0.4, 0, -36, 13, 8.6, 5.4],
  [0.175, 5.1, -0.25, 0, -15, 7, 5.3, 3.8],
  [0.28, 5.5, -0.25, 0, -6, 5, 5.3, 3.8],
  [0.345, 11.85, 0.15, 0, 11, 6, 5.8, 4.3],
  [0.44, 11.95, 0.15, 0, 3, 4, 5.8, 4.3],
  [0.5, 19.4, 0, 0, -12, 7, 6.9, 4.3],
  [0.565, 19.6, 0, 0, -5, 5, 6.9, 4.3],
  [0.615, 19.4, 0.25, 0.4, 0, 4, 5.2, 2.9],
  [0.665, 26, 0.1, 0, 12, 6, 5.5, 3.9],
  [0.71, 26.3, 0.1, 0, 4, 5, 5.5, 3.9],
  [0.785, 34, 0, 0, -30, 16, 11.4, 7.4],
  [0.865, 34, 0, 0, 26, 12, 11.4, 7.4],
  [0.935, 34, 0, 0, 0, 3, 5.4, 3.5],
  [1.0, 34, 0, 0, 0, 3, 5.4, 3.5],
];

// Phones and tall screens: the cards stack (see `tall` on each card) and the camera comes closer, so
// the cards fill the width and their text stays readable.
const TALL = {
  0.175: { tx: 5.0, fw: 4.95 }, 0.28: { tx: 5.0, fw: 4.95 },
  0.345: { tx: 11.8, ty: 0.45, fw: 4.65, fh: 3.9 }, 0.44: { tx: 11.8, ty: 0.45, fw: 4.65, fh: 3.9 },
  0.5: { tx: 18.85, ty: -0.05, fw: 4.85, fh: 4.4 }, 0.565: { tx: 18.85, ty: -0.05, fw: 4.85, fh: 4.4 },
  0.615: { fw: 4.8 }, 0.665: { fw: 4.85 }, 0.71: { fw: 4.85 }, 0.785: { fw: 8.4 }, 0.865: { fw: 8.4 },
};
const KEYS_TALL = KEYS.map((k) => {
  const o = TALL[k[0]];
  return o ? [k[0], o.tx ?? k[1], o.ty ?? k[2], k[3], k[4] * 0.6, k[5], o.fw ?? k[6], o.fh ?? k[7]] : [...k.slice(0, 6), k[6] * 1.06, k[7]];
});

const PAL = {
  light: { surface: "#ffffff", ink: "#111014", ink2: "#55535c", ink3: "#8b8993", line: "rgba(17,16,20,0.10)", soft: "#f4f3f1", add: "rgba(24,166,100,0.12)", del: "rgba(229,72,77,0.11)", green: "#12884e", red: "#d43a3f", kw: "#c0127f", str: "#b4470f", fn: "#6d3fd6", slab: 0xffffff, grid: 0x111014, gridA: 0.11 },
  dark: { surface: "#17151b", ink: "#f4f3f6", ink2: "#a8a6b0", ink3: "#77757f", line: "rgba(244,243,246,0.10)", soft: "#0f0e12", add: "rgba(40,200,120,0.14)", del: "rgba(255,90,95,0.14)", green: "#3ddc8a", red: "#ff6b70", kw: "#ff6fb5", str: "#ffb366", fn: "#b79bff", slab: 0x1b191f, grid: 0xf4f3f6, gridA: 0.075 },
};
const SANS = '"Geist", system-ui, -apple-system, "Segoe UI", sans-serif';
const MONO = '"Geist Mono", ui-monospace, "SFMono-Regular", Consolas, monospace';

// ---------- 2D helpers for the cards ----------
function rr(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function grad(ctx, x0, y0, x1, y1) {
  const g = ctx.createLinearGradient(x0, y0, x1, y1);
  g.addColorStop(0, "#ffb11f"); g.addColorStop(0.36, "#ff6a2a"); g.addColorStop(0.72, "#ff3d8a"); g.addColorStop(1, "#e0169a");
  return g;
}
function wrap(ctx, text, maxW) {
  const out = [];
  let line = "";
  for (const word of text.split(" ")) {
    const t = line ? `${line} ${word}` : word;
    if (ctx.measureText(t).width > maxW && line) { out.push(line); line = word; } else line = t;
  }
  if (line) out.push(line);
  return out;
}
function check(ctx, cx, cy, r, color = "#fff") {
  ctx.save();
  ctx.strokeStyle = color; ctx.lineWidth = r * 0.28; ctx.lineCap = "round"; ctx.lineJoin = "round";
  ctx.beginPath(); ctx.moveTo(cx - r * 0.42, cy + r * 0.02); ctx.lineTo(cx - r * 0.1, cy + r * 0.34); ctx.lineTo(cx + r * 0.46, cy - r * 0.3); ctx.stroke();
  ctx.restore();
}
function cardBase(ctx, W, H, P, r = 14) {
  ctx.clearRect(0, 0, W, H);
  rr(ctx, 0, 0, W, H, r);
  ctx.fillStyle = P.surface; ctx.fill();
  ctx.strokeStyle = P.line; ctx.lineWidth = 1.5; ctx.stroke();
}
// a line of code: tokens [kind, text], drawn up to `chars` characters; returns the characters used
function codeLine(ctx, P, toks, x, y, chars) {
  let used = 0;
  for (const [k, t] of toks) {
    if (used >= chars) break;
    const s = t.slice(0, chars - used);
    ctx.fillStyle = k === "kw" ? P.kw : k === "str" ? P.str : k === "fn" ? P.fn : k === "p" ? P.ink2 : P.ink;
    ctx.fillText(s, x, y);
    x += ctx.measureText(s).width;
    used += s.length;
  }
  return x;
}

// ---------- what's on each card ----------
const PROMPT = "Make login keep the session, and send people back to the page they came from.";
const TODO = ["Read the auth code", "Keep the session in a cookie", "Send people back after login", "Run the tests"];
const CODE = [
  [["kw", "import"], ["", " { useSession } "], ["kw", "from"], ["str", ' "../auth/session"'], ["p", ";"]],
  [],
  [["kw", "export function "], ["fn", "Login"], ["p", "({ "], ["", "next"], ["p", " = "], ["str", '"/"'], ["p", " }) {"]],
  [["kw", "  const "], ["", "session"], ["p", " = "], ["fn", "useSession"], ["p", "();"]],
  [["kw", "  async function "], ["fn", "submit"], ["p", "("], ["", "form"], ["p", ") {"]],
  [["kw", "    await "], ["", "session."], ["fn", "signIn"], ["p", "("], ["", "form"], ["p", ", { "], ["", "keep"], ["p", ": "], ["kw", "true"], ["p", " });"]],
  [["", "    location."], ["fn", "assign"], ["p", "("], ["", "next"], ["p", ");"]],
  [["p", "  }"]],
  [["kw", "  return "], ["p", "<"], ["fn", "LoginForm"], ["", " onSubmit"], ["p", "={"], ["", "submit"], ["p", "} />;"]],
  [["p", "}"]],
];
const ADDED = new Set([0, 3, 4, 5, 6, 7]);
const TERM = [
  ["$ npm test", "cmd"],
  ["✓ auth › keeps the session (31 ms)", "dim"],
  ["✓ login › sends you back (12 ms)", "dim"],
  ["✓ login › redirects home (9 ms)", "dim"],
  ["Tests: 12 passed, 12 total", "ok"],
];
const PROVIDERS = [
  ["openai", "OpenAI"], ["anthropic", "Anthropic"], ["google", "Gemini"], ["xai", "Grok"], ["deepseek", "DeepSeek"], ["openrouter", "OpenRouter"],
  ["mistral", "Mistral"], ["moonshotai", "Kimi"], ["groq", "Groq"], ["alibaba", "Qwen"], ["zai", "GLM"], ["ollama", "Ollama"],
  ["perplexity", "Perplexity"], ["minimax", "MiniMax"], ["nvidia", "NVIDIA"], ["github-copilot", "Copilot"],
];

const DRAW = {
  chat(ctx, W, H, k, P) {
    cardBase(ctx, W, H, P, 18);
    ctx.font = `500 13px ${MONO}`; ctx.fillStyle = P.ink3; ctx.textBaseline = "alphabetic";
    ctx.fillText("NEW THREAD · my-app", 24, 34);
    const n = Math.round(PROMPT.length * k);
    ctx.font = `500 19px ${SANS}`;
    const lines = n ? wrap(ctx, PROMPT.slice(0, n), W - 48) : [];
    if (!n) { ctx.fillStyle = P.ink3; ctx.fillText("Ask AFH to build anything…", 24, 68); }
    ctx.fillStyle = P.ink;
    lines.forEach((l, i) => ctx.fillText(l, 24, 68 + i * 27));
    if (k < 1) { // the caret
      const last = lines[lines.length - 1] || "", x = 24 + ctx.measureText(last).width + 2, y = 68 + Math.max(0, lines.length - 1) * 27;
      ctx.fillStyle = grad(ctx, x, y - 18, x, y + 4); ctx.fillRect(x, y - 18, 2.5, 22);
    }
    // the model chip and the send button
    const y = H - 46;
    ctx.font = `600 14px ${SANS}`;
    const label = "Claude Opus 5.5", lw = ctx.measureText(label).width;
    ctx.font = `500 14px ${SANS}`;
    const eff = " · High", ew = ctx.measureText(eff).width;
    rr(ctx, 18, y, 46 + lw + ew, 32, 10); ctx.fillStyle = P.soft; ctx.fill(); ctx.strokeStyle = P.line; ctx.stroke();
    ctx.beginPath(); ctx.arc(36, y + 16, 7, 0, Math.PI * 2); ctx.fillStyle = grad(ctx, 29, y + 9, 43, y + 23); ctx.fill();
    ctx.font = `600 14px ${SANS}`; ctx.fillStyle = P.ink; ctx.fillText(label, 52, y + 21);
    ctx.font = `500 14px ${SANS}`; ctx.fillStyle = P.ink3; ctx.fillText(eff, 52 + lw, y + 21);
    const sx = W - 40, sy = y + 16;
    if (k >= 1) { ctx.beginPath(); ctx.arc(sx, sy, 24, 0, Math.PI * 2); ctx.fillStyle = "rgba(255,106,42,0.16)"; ctx.fill(); }
    ctx.beginPath(); ctx.arc(sx, sy, 18, 0, Math.PI * 2); ctx.fillStyle = k > 0.05 ? grad(ctx, sx - 18, sy - 18, sx + 18, sy + 18) : P.line; ctx.fill();
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.6; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(sx, sy + 8); ctx.lineTo(sx, sy - 8); ctx.moveTo(sx - 6.5, sy - 1.5); ctx.lineTo(sx, sy - 8); ctx.lineTo(sx + 6.5, sy - 1.5); ctx.stroke();
  },
  goal(ctx, W, H, k, P) {
    cardBase(ctx, W, H, P, 16);
    ctx.font = `600 12.5px ${MONO}`; ctx.fillStyle = grad(ctx, 22, 0, 80, 0); ctx.fillText("GOAL", 22, 32);
    ctx.font = `600 17px ${SANS}`; ctx.fillStyle = P.ink;
    wrap(ctx, "All tests pass and login keeps the session", W - 150).forEach((l, i) => ctx.fillText(l, 22, 60 + i * 23));
    const set = k > 0.5;
    ctx.font = `600 13px ${SANS}`;
    const t = set ? "set" : "…", tw = ctx.measureText(t).width + 34;
    rr(ctx, W - tw - 18, 20, tw, 28, 14); ctx.fillStyle = set ? "rgba(255,106,42,0.12)" : P.soft; ctx.fill();
    ctx.beginPath(); ctx.arc(W - tw - 18 + 15, 34, 4.5, 0, Math.PI * 2); ctx.fillStyle = set ? "#ff6a2a" : P.ink3; ctx.fill();
    ctx.fillStyle = set ? "#e8481f" : P.ink3; ctx.fillText(t, W - tw - 18 + 25, 39);
  },
  todo(ctx, W, H, k, P) {
    cardBase(ctx, W, H, P, 18);
    const step = k * (TODO.length + 0.35), done = Math.min(TODO.length, Math.floor(step));
    ctx.font = `600 17px ${SANS}`; ctx.fillStyle = P.ink; ctx.fillText("To-do", 24, 38);
    ctx.font = `500 13px ${MONO}`; ctx.fillStyle = P.ink3;
    const c = `${done} of ${TODO.length}`; ctx.fillText(c, W - 24 - ctx.measureText(c).width, 38);
    rr(ctx, 24, 54, W - 48, 5, 2.5); ctx.fillStyle = P.line; ctx.fill();
    if (step > 0) { rr(ctx, 24, 54, Math.max(5, (W - 48) * Math.min(1, step / TODO.length)), 5, 2.5); ctx.fillStyle = grad(ctx, 24, 0, W - 24, 0); ctx.fill(); }
    TODO.forEach((t, i) => {
      const y = 96 + i * 44, cx = 38, cy = y - 6;
      const state = i < done ? "done" : i === done ? "now" : "todo";
      if (state === "done") {
        ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.fillStyle = grad(ctx, cx - 11, cy - 11, cx + 11, cy + 11); ctx.fill();
        check(ctx, cx, cy, 11);
      } else if (state === "now") {
        ctx.lineWidth = 3; ctx.strokeStyle = P.line; ctx.beginPath(); ctx.arc(cx, cy, 10, 0, Math.PI * 2); ctx.stroke();
        ctx.strokeStyle = grad(ctx, cx - 10, cy - 10, cx + 10, cy + 10); ctx.lineCap = "round";
        const a = (step % 1) * Math.PI * 2 - Math.PI / 2;
        ctx.beginPath(); ctx.arc(cx, cy, 10, -Math.PI / 2, Math.max(-Math.PI / 2 + 0.4, a)); ctx.stroke();
      } else {
        ctx.lineWidth = 2; ctx.strokeStyle = P.ink3; ctx.globalAlpha = 0.6; ctx.beginPath(); ctx.arc(cx, cy, 10, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = 1;
      }
      ctx.font = `${state === "now" ? 600 : 500} 16px ${SANS}`;
      ctx.fillStyle = state === "done" ? P.ink3 : P.ink;
      ctx.fillText(t, 62, y);
      if (state === "done") { const w = ctx.measureText(t).width; ctx.fillRect(62, y - 6, w, 1.5); }
    });
  },
  code(ctx, W, H, k, P) {
    cardBase(ctx, W, H, P, 16);
    // tab
    ctx.fillStyle = P.soft; rr(ctx, 0, 0, W, 46, 16); ctx.fill(); ctx.fillRect(0, 30, W, 16);
    ctx.fillStyle = P.line; ctx.fillRect(0, 46, W, 1.5);
    ctx.font = `500 14px ${MONO}`; ctx.fillStyle = P.ink; ctx.fillText("src/pages/login.tsx", 20, 29);
    ctx.font = `600 14px ${MONO}`;
    const minus = "−3", mw = ctx.measureText(minus).width;
    ctx.fillStyle = P.red; ctx.fillText(minus, W - 20 - mw, 29);
    ctx.fillStyle = P.green; const plus = "+84 "; ctx.fillText(plus, W - 20 - mw - ctx.measureText(plus).width, 29);
    // lines, typed in
    const total = CODE.reduce((n, l) => n + l.reduce((m, [, t]) => m + t.length, 0) + 1, 0);
    let budget = Math.round(total * k);
    ctx.font = `500 14px ${MONO}`;
    CODE.forEach((toks, i) => {
      const y = 76 + i * 21.5, len = toks.reduce((m, [, t]) => m + t.length, 0);
      const shown = budget > 0 || i === 0;
      if (ADDED.has(i) && budget > 0) { ctx.fillStyle = P.add; ctx.fillRect(0, y - 15, W, 21.5); ctx.fillStyle = P.green; ctx.fillRect(0, y - 15, 3, 21.5); }
      ctx.fillStyle = P.ink3; ctx.fillText(String(i + 1).padStart(2, " "), 14, y);
      if (shown) {
        const x = codeLine(ctx, P, toks, 50, y, budget);
        if (budget <= len && k < 1) { ctx.fillStyle = grad(ctx, x, y - 14, x, y + 4); ctx.fillRect(x + 1, y - 14, 2.5, 18); }
      }
      budget -= len + 1;
    });
  },
  term(ctx, W, H, k) {
    ctx.clearRect(0, 0, W, H);
    rr(ctx, 0, 0, W, H, 16); ctx.fillStyle = "#121116"; ctx.fill(); ctx.strokeStyle = "rgba(255,255,255,0.09)"; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.font = `500 13px ${MONO}`; ctx.fillStyle = "#8b8993"; ctx.fillText("Terminal", 20, 30);
    const n = Math.floor(k * (TERM.length + 0.6));
    if (n >= TERM.length) {
      ctx.font = `600 13px ${MONO}`; const e = "exit 0", ew = ctx.measureText(e).width;
      ctx.fillStyle = "#3ddc8a"; ctx.fillText(e, W - 20 - ew, 30);
      ctx.font = `500 13px ${MONO}`; ctx.fillStyle = "#8b8993"; const s = "4.2s  "; ctx.fillText(s, W - 20 - ew - ctx.measureText(s).width, 30);
    }
    ctx.fillStyle = "rgba(255,255,255,0.07)"; ctx.fillRect(0, 44, W, 1.5);
    ctx.font = `500 14.5px ${MONO}`;
    TERM.slice(0, Math.max(1, n)).forEach(([t, kind], i) => {
      const y = 74 + i * 23;
      if (kind === "cmd") { ctx.fillStyle = grad(ctx, 20, 0, 34, 0); ctx.fillText("$", 20, y); ctx.fillStyle = "#f4f3f6"; ctx.fillText(t.slice(1), 30, y); }
      else { ctx.fillStyle = kind === "ok" ? "#3ddc8a" : "#a8a6b0"; ctx.fillText(t, 20, y); }
    });
  },
  worked(ctx, W, H, k, P) {
    cardBase(ctx, W, H, P, 18);
    const cx = 36, cy = 36;
    ctx.beginPath(); ctx.arc(cx, cy, 12, 0, Math.PI * 2); ctx.fillStyle = grad(ctx, cx - 12, cy - 12, cx + 12, cy + 12); ctx.fill(); check(ctx, cx, cy, 12);
    ctx.font = `600 17px ${SANS}`; ctx.fillStyle = P.ink; ctx.fillText("Worked for 32s", 60, 42);
    const w1 = ctx.measureText("Worked for 32s").width;
    ctx.font = `500 15px ${SANS}`; ctx.fillStyle = P.ink3; ctx.fillText("Edited 3 files · Ran 1 command", 72 + w1, 42);
    ctx.strokeStyle = P.ink3; ctx.lineWidth = 2; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(W - 34, 33); ctx.lineTo(W - 28, 39); ctx.lineTo(W - 22, 33); ctx.stroke();
    ctx.fillStyle = P.line; ctx.fillRect(20, 66, W - 40, 1.5);
    ctx.font = `500 17px ${SANS}`; ctx.fillStyle = P.ink;
    wrap(ctx, "Login now keeps you signed in and sends you back to the page you came from. All 12 tests pass.", W - 44).forEach((l, i) => ctx.fillText(l, 22, 98 + i * 25));
  },
  diff(ctx, W, H, k, P) {
    cardBase(ctx, W, H, P, 18);
    ctx.font = `600 17px ${SANS}`; ctx.fillStyle = P.ink; ctx.fillText("Changes", 22, 38);
    ctx.font = `500 13px ${MONO}`; ctx.fillStyle = P.ink3; const f = "3 files"; ctx.fillText(f, W - 22 - ctx.measureText(f).width, 38);
    const files = [["login.tsx", "+84", "−3"], ["session.ts", "+22", "−1"], ["login.test.ts", "+40", ""]];
    const n = Math.floor(k * 7.5);
    files.forEach(([name, a, d], i) => {
      if (i >= n) return;
      const y = 74 + i * 32;
      rr(ctx, 16, y - 21, W - 32, 29, 8); ctx.fillStyle = i === 0 ? P.soft : "transparent"; ctx.fill();
      ctx.font = `500 14.5px ${MONO}`; ctx.fillStyle = P.ink; ctx.fillText(name, 28, y - 2);
      ctx.font = `600 14px ${MONO}`;
      const dw = d ? ctx.measureText(d).width : 0;
      if (d) { ctx.fillStyle = P.red; ctx.fillText(d, W - 28 - dw, y - 2); }
      ctx.fillStyle = P.green; ctx.fillText(a, W - 28 - dw - (d ? 10 : 0) - ctx.measureText(a).width, y - 2);
    });
    const hunk = [["−", "location.assign(\"/\");", "del"], ["+", "location.assign(next);", "add"], ["+", "await session.signIn(form, { keep: true });", "add"]];
    hunk.forEach(([s, t, kind], i) => {
      if (i + 3 >= n) return;
      const y = 186 + i * 23;
      ctx.fillStyle = kind === "add" ? P.add : P.del; ctx.fillRect(16, y - 16, W - 32, 23);
      ctx.font = `500 13.5px ${MONO}`; ctx.fillStyle = kind === "add" ? P.green : P.red; ctx.fillText(s, 26, y);
      ctx.fillStyle = P.ink; ctx.fillText(t, 44, y);
    });
    if (n >= 7) {
      ctx.font = `600 14px ${SANS}`; const r = "↶  Rewind to here", rw = ctx.measureText(r).width + 32;
      rr(ctx, W - 22 - rw, H - 52, rw, 34, 11); ctx.fillStyle = P.soft; ctx.fill(); ctx.strokeStyle = P.line; ctx.stroke();
      ctx.fillStyle = P.ink; ctx.fillText(r, W - 22 - rw + 16, H - 30);
    }
  },
  tile(ctx, W, H, k, P, card) {
    ctx.clearRect(0, 0, W, H);
    rr(ctx, 0, 0, W, H, 18); ctx.fillStyle = "#ffffff"; ctx.fill(); ctx.strokeStyle = "rgba(17,16,20,0.08)"; ctx.lineWidth = 1.5; ctx.stroke();
    if (card.img?.complete && card.img.naturalWidth) ctx.drawImage(card.img, W / 2 - 26, 20, 52, 52);
    else { ctx.font = `700 30px ${SANS}`; ctx.fillStyle = "#111014"; ctx.textAlign = "center"; ctx.fillText(card.label[0], W / 2, 58); ctx.textAlign = "left"; }
    ctx.font = `600 14px ${SANS}`; ctx.fillStyle = "#111014"; ctx.textAlign = "center"; ctx.fillText(card.label, W / 2, H - 20); ctx.textAlign = "left";
  },
};

// in: when it rises; out: when it leaves; k: what drives its content; fold: where it folds to
const CARDS = [
  { id: "chat", w: 4.7, h: 1.62, pos: [5.0, 0.5, 0], yaw: -4, in: [0.125, 0.175], k: [0.175, 0.255], out: [0.295, 0.335] },
  { id: "goal", w: 3.7, h: 1.02, pos: [11.0, 1.42, 0.65], tall: [11.6, 1.5, 0.45], yaw: 6, in: [0.3, 0.335], k: [0.33, 0.36], out: [0.45, 0.485] },
  { id: "todo", w: 4.3, h: 2.5, pos: [12.45, -0.15, 0], tall: [11.85, -0.45, 0], yaw: 3, in: [0.315, 0.35], k: [0.355, 0.44], out: [0.45, 0.49] },
  { id: "code", w: 4.5, h: 2.75, pos: [18.7, 0.5, 0], tall: [18.8, 0.6, 0], yaw: -3, in: [0.46, 0.5], k: [0.49, 0.56], fold: [0.57, 0.61] },
  { id: "term", dark: true, w: 3.7, h: 1.72, pos: [20.35, -0.95, 0.75], tall: [19.15, -1.3, 0.6], yaw: -8, in: [0.49, 0.525], k: [0.525, 0.565], fold: [0.57, 0.61] },
  { id: "worked", w: 4.5, h: 1.42, pos: [19.4, 0.25, 0.4], yaw: 0, in: [0.585, 0.62], k: [0, 1], out: [0.645, 0.675] },
  { id: "diff", w: 4.5, h: 2.62, pos: [26.0, 0.25, 0], yaw: 5, in: [0.635, 0.67], k: [0.67, 0.71], out: [0.715, 0.75] },
];

export function createFilm(root, { reduced = matchMedia("(prefers-reduced-motion: reduce)").matches } = {}) {
  const pin = root.querySelector(".film-pin"), canvas = root.querySelector(".film-canvas");
  const coarse = matchMedia("(pointer: coarse)").matches;
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" }); }
  catch { return false; }
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.06;
  renderer.setClearColor(0x000000, 0);
  const small = Math.min(innerWidth, innerHeight) < 600;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, small ? 2 : 1.75));
  const aniso = Math.min(8, renderer.capabilities.getMaxAnisotropy());

  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 400);
  const key = new THREE.DirectionalLight(0xfff3e8, 1.7); key.position.set(-0.5, 0.9, 1);
  const rim = new THREE.DirectionalLight(0xff5c9a, 0.75); rim.position.set(0.9, -0.3, -0.6);
  const fill = new THREE.HemisphereLight(0xffffff, 0x3a2030, 0.75);
  scene.add(key, rim, fill);

  let theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";

  // ---------- the floor: a faint grid that gives the camera something to move over ----------
  const floorMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uColor: { value: new THREE.Color(PAL[theme].grid) }, uAlpha: { value: PAL[theme].gridA }, uCam: { value: new THREE.Vector3() } },
    vertexShader: "varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }",
    fragmentShader: `uniform vec3 uColor; uniform float uAlpha; uniform vec3 uCam; varying vec3 vW;
      void main(){
        vec2 g = vW.xz * 1.0; vec2 d = fwidth(g); vec2 a = abs(fract(g - 0.5) - 0.5) / max(d, vec2(1e-4));
        float line = 1.0 - min(min(a.x, a.y), 1.0);
        float fade = exp(-pow(length(vW.xz - uCam.xz) / 15.0, 2.0));
        gl_FragColor = vec4(uColor, line * fade * uAlpha);
      }`,
  });
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(160, 80), floorMat);
  floor.rotation.x = -Math.PI / 2; floor.position.set(17, -3.3, 0);
  scene.add(floor);

  // ---------- the glow behind the mark ----------
  const glowTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const x = c.getContext("2d"), g = x.createRadialGradient(128, 128, 0, 128, 128, 128);
    g.addColorStop(0, "rgba(255,120,50,0.55)"); g.addColorStop(0.45, "rgba(255,61,138,0.22)"); g.addColorStop(1, "rgba(255,61,138,0)");
    x.fillStyle = g; x.fillRect(0, 0, 256, 256);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const glows = [new THREE.Vector3(0, 0, -0.6), END.clone().setZ(-0.6)].map((p) => {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, depthWrite: false, transparent: true }));
    s.position.copy(p); s.scale.set(10, 7, 1); s.renderOrder = -1; scene.add(s); return s;
  });

  // ---------- the three strands: tubes whose centre line is rebuilt every frame ----------
  const N = small ? 220 : 320, RAD = small ? 14 : 20;
  const logo = STRANDS.map((s) => {
    const P = s.pts.map(([x, y], i) => new THREE.Vector3((x - 120) * U, (70 - y) * U, s.z[i] * DEPTH));
    const path = new THREE.CurvePath();
    path.add(new THREE.CubicBezierCurve3(P[0], P[1], P[2], P[3]));
    path.add(new THREE.CubicBezierCurve3(P[3], P[4], P[5], P[6]));
    return Array.from({ length: N + 1 }, (_, i) => path.getPointAt(i / N));
  });
  const COS = Float32Array.from({ length: RAD + 1 }, (_, j) => Math.cos((j / RAD) * Math.PI * 2));
  const SIN = Float32Array.from({ length: RAD + 1 }, (_, j) => Math.sin((j / RAD) * Math.PI * 2));
  const ringQ = [[14, 0], [14, 60], [14, 120]].map(([ax, ay]) => new THREE.Quaternion().setFromEuler(new THREE.Euler(ax * D2R, ay * D2R, 0, "YXZ")));

  const strandU = STRANDS.map(() => ({ uHead: { value: 1 }, uTail: { value: 0 }, uGlow: { value: 0.35 }, uTime: { value: 0 }, uPulse: { value: 0 }, uSeed: { value: 0 } }));
  const strands = STRANDS.map((s, k) => {
    const verts = (N + 1) * (RAD + 1);
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(verts * 3), nor = new Float32Array(verts * 3), uv = new Float32Array(verts * 2), col = new Float32Array(verts * 3);
    const from = new THREE.Color(s.from), to = new THREE.Color(s.to), c = new THREE.Color();
    for (let i = 0; i <= N; i++) for (let j = 0; j <= RAD; j++) {
      const v = i * (RAD + 1) + j;
      uv[v * 2] = i / N; uv[v * 2 + 1] = j / RAD;
      c.copy(from).lerp(to, i / N); c.toArray(col, v * 3);
    }
    const idx = [];
    for (let i = 0; i < N; i++) for (let j = 0; j < RAD; j++) {
      const a = i * (RAD + 1) + j, b = a + RAD + 1, cc = b + 1, d = a + 1;
      idx.push(a, d, b, b, d, cc);
    }
    g.setIndex(idx);
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute("normal", new THREE.BufferAttribute(nor, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    const m = glossy({ vertexColors: true, emissive: 0xffffff });
    strandU[k].uSeed.value = k / 3;
    m.onBeforeCompile = (sh) => {
      Object.assign(sh.uniforms, strandU[k]);
      sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nvarying float vU;").replace("#include <begin_vertex>", "#include <begin_vertex>\nvU = uv.x;");
      sh.fragmentShader = sh.fragmentShader
        .replace("#include <common>", "#include <common>\nuniform float uHead, uTail, uGlow, uTime, uPulse, uSeed; varying float vU;")
        .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
          if (vU > uHead || vU < uTail) discard;
          float lead = exp(-max(0.0, uHead - vU) * 9.0) * step(uHead, 0.999);
          // lights that run along the rail, the way the work runs through a turn
          float ph = fract(vU * 9.0 - uTime * 0.55 + uSeed);
          float pulse = pow(max(0.0, 1.0 - abs(ph - 0.5) * 2.0), 10.0) * uPulse;
          totalEmissiveRadiance = vColor.rgb * (0.10 + lead * uGlow + pulse * 1.3);`);
    };
    m.customProgramCacheKey = () => "afh-film-strand";
    const mesh = new THREE.Mesh(g, m);
    mesh.frustumCulled = false;
    scene.add(mesh);
    return { g, pos, nor, mesh, P: Array.from({ length: N + 1 }, () => new THREE.Vector3()) };
  });
  const capGeo = new THREE.SphereGeometry(TUBE, 24, 16);
  const dotGeo = new THREE.SphereGeometry(DOT, small ? 32 : 44, small ? 22 : 30);
  const ends = STRANDS.map((s) => {
    const capT = new THREE.Mesh(capGeo, glossy()), capH = new THREE.Mesh(capGeo, glossy());
    const L = new THREE.Mesh(dotGeo, glossy({ color: s.from })), R = new THREE.Mesh(dotGeo, glossy({ color: s.to, transparent: true }));
    R.renderOrder = 2;
    scene.add(capT, capH, L, R);
    return { capT, capH, L, R };
  });

  const T = new THREE.Vector3(), Nv = new THREE.Vector3(), B = new THREE.Vector3(), tmp = new THREE.Vector3(), q = new THREE.Vector3();
  const UP = new THREE.Vector3(0, 1, 0), X = new THREE.Vector3(1, 0, 0), rotY = new THREE.Quaternion();
  function railPt(k, u, t, out) {
    const ph = u * RAIL.turns * Math.PI * 2 + (k * Math.PI * 2) / 3 - t * 0.3;
    return out.set(lerp(RAIL.x0, RAIL.x1, u), RAIL.y + Math.sin(ph) * RAIL.r, Math.cos(ph) * RAIL.r);
  }
  function orbitPt(k, u, t, spin, out) {
    const a = u * Math.PI * 2 + (k % 2 ? -1 : 1) * t * 0.35 + k * 2.1;
    out.set(Math.cos(a) * RING, Math.sin(a) * RING, 0).applyQuaternion(ringQ[k]).applyQuaternion(rotY.setFromAxisAngle(UP, spin));
    return out.add(END);
  }
  // staggered blend: one end of the strand leads, the other follows
  const stag = (t, u, s = 0.55) => sm(clamp01(t * (1 + s) - u * s));

  function buildStrand(k, p, t) {
    const S = strands[k], P = S.P;
    const a = ramp(p, 0.075, 0.2), b = ramp(p, 0.705, 0.8), c = ramp(p, 0.845, 0.93);
    const spin = (p - 0.72) * 3.2;
    for (let i = 0; i <= N; i++) {
      const u = i / N, L = logo[k][i], pt = P[i];
      const wa = stag(a, 1 - u), wb = stag(b, u), wc = stag(c, 1 - u);
      pt.copy(L);
      if (wa > 0) pt.lerp(railPt(k, u, t, tmp), wa);
      if (wb > 0) pt.lerp(orbitPt(k, u, t, spin, tmp), wb);
      if (wc > 0) pt.lerp(q.copy(L).add(END), wc);
    }
    // a tube around the line, with frames carried along it
    const pos = S.pos, nor = S.nor;
    for (let i = 0; i <= N; i++) {
      T.subVectors(P[Math.min(N, i + 1)], P[Math.max(0, i - 1)]).normalize();
      if (i === 0) { Nv.copy(Math.abs(T.y) < 0.9 ? UP : X); Nv.addScaledVector(T, -Nv.dot(T)).normalize(); }
      else { Nv.addScaledVector(T, -Nv.dot(T)).normalize(); }
      B.crossVectors(T, Nv);
      const C = P[i];
      for (let j = 0; j <= RAD; j++) {
        const v = (i * (RAD + 1) + j) * 3;
        const nx = COS[j] * Nv.x + SIN[j] * B.x, ny = COS[j] * Nv.y + SIN[j] * B.y, nz = COS[j] * Nv.z + SIN[j] * B.z;
        nor[v] = nx; nor[v + 1] = ny; nor[v + 2] = nz;
        pos[v] = C.x + nx * TUBE; pos[v + 1] = C.y + ny * TUBE; pos[v + 2] = C.z + nz * TUBE;
      }
    }
    S.g.attributes.position.needsUpdate = true;
    S.g.attributes.normal.needsUpdate = true;
  }
  const at = (P, u) => { const f = clamp01(u) * N, i = Math.min(N - 1, Math.floor(f)); return tmp.copy(P[i]).lerp(P[i + 1], f - i); };

  // ---------- the cards ----------
  const PPU = small ? 215 : 235; // texture pixels per world unit
  function makeCard(spec) {
    const W = spec.w * 100, H = spec.h * 100;
    const cv = document.createElement("canvas");
    cv.width = Math.round(spec.w * PPU); cv.height = Math.round(spec.h * PPU);
    const ctx = cv.getContext("2d");
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = aniso;
    const r = 0.14, w = spec.w - 0.04, h = spec.h - 0.04;
    const shape = new THREE.Shape();
    shape.moveTo(-w / 2 + r, -h / 2); shape.lineTo(w / 2 - r, -h / 2); shape.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
    shape.lineTo(w / 2, h / 2 - r); shape.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2); shape.lineTo(-w / 2 + r, h / 2);
    shape.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r); shape.lineTo(-w / 2, -h / 2 + r); shape.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
    const slabGeo = new THREE.ExtrudeGeometry(shape, { depth: 0.05, bevelEnabled: true, bevelThickness: 0.025, bevelSize: 0.03, bevelSegments: 3, curveSegments: 6 });
    slabGeo.translate(0, 0, -0.075);
    const slabMat = glossy({ color: spec.dark ? 0x121116 : PAL[theme].slab, transparent: true, roughness: 0.3 });
    const slab = new THREE.Mesh(slabGeo, slabMat);
    const faceMat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, toneMapped: false, depthWrite: false });
    const face = new THREE.Mesh(new THREE.PlaneGeometry(spec.w, spec.h), faceMat);
    face.position.z = 0.004; face.renderOrder = 3;
    const inner = new THREE.Group(); inner.add(slab, face);
    const group = new THREE.Group(); group.add(inner);
    group.visible = false;
    scene.add(group);
    const wideHome = new THREE.Vector3(...(spec.pos || [0, 0, 0])), tallHome = new THREE.Vector3(...(spec.tall || spec.pos || [0, 0, 0]));
    const card = { ...spec, W, H, cv, ctx, tex, slabMat, faceMat, group, inner, last: -1, wideHome, tallHome, home: wideHome };
    card.draw = (k) => {
      ctx.setTransform(cv.width / W, 0, 0, cv.height / H, 0, 0);
      ctx.textBaseline = "alphabetic";
      DRAW[spec.draw || spec.id](ctx, W, H, k, PAL[theme], card);
      tex.needsUpdate = true;
    };
    return card;
  }
  const cards = CARDS.map(makeCard);
  const byId = Object.fromEntries(cards.map((c) => [c.id, c]));

  // the providers, on tiles that orbit the rings
  const tiles = PROVIDERS.map(([id, label], i) => makeCard({ id: `tile-${id}`, draw: "tile", label, w: 1.02, h: 1.2, i }));
  import("./provider-logos.js").then(({ providerLogo }) => {
    tiles.forEach((tile, i) => {
      let svg = providerLogo(PROVIDERS[i][0], PROVIDERS[i][1]);
      if (!svg) return;
      svg = svg.replace("<svg", '<svg width="104" height="104" color="#111014"');
      if (!/xmlns=/.test(svg)) svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
      const img = new Image();
      img.onload = () => { tile.img = img; tile.last = -1; };
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    });
  }).catch(() => {});

  const redrawAll = () => { [...cards, ...tiles].forEach((c) => { c.last = -1; }); };
  document.fonts?.ready.then(redrawAll);
  document.fonts?.load(`600 16px ${SANS}`).then(redrawAll).catch(() => {});

  document.addEventListener("afh:theme", (e) => {
    theme = e.detail === "dark" ? "dark" : "light";
    floorMat.uniforms.uColor.value.set(PAL[theme].grid); floorMat.uniforms.uAlpha.value = PAL[theme].gridA;
    cards.forEach((c) => { if (!c.dark) c.slabMat.color.set(PAL[theme].slab); });
    glows.forEach((g) => { g.material.blending = theme === "dark" ? THREE.AdditiveBlending : THREE.NormalBlending; g.material.needsUpdate = true; });
    redrawAll();
  });
  glows.forEach((g) => { g.material.blending = theme === "dark" ? THREE.AdditiveBlending : THREE.NormalBlending; });

  function placeCard(c, p, t) {
    const kin = sm(ramp(p, c.in[0], c.in[1]));
    const kout = c.out ? sm(ramp(p, c.out[0], c.out[1])) : 0;
    const kfold = c.fold ? ramp(p, c.fold[0], c.fold[1]) : 0;
    const vis = kin > 0.002 && kout < 0.998 && kfold < 0.995;
    c.group.visible = vis;
    if (!vis) return;
    const g = c.group, f = sm(kfold);
    g.position.copy(c.home);
    g.position.y += (1 - kin) * -0.9 + kout * 0.7 + (reduced ? 0 : Math.sin(t * 0.8 + c.home.x) * 0.04);
    g.position.z += kout * -0.5;
    g.rotation.set((1 - kin) * -1.15 + kout * 0.35, (c.yaw || 0) * D2R, 0);
    g.scale.setScalar(lerp(0.82, 1, kin));
    if (f > 0) { // fold flat into the "Worked for" line
      const to = byId.worked.home;
      g.position.lerp(to, f);
      g.scale.y *= lerp(1, 0.06, f);
      g.rotation.x += f * -0.4;
    }
    const o = kin * (1 - kout) * (1 - sm(ramp(kfold, 0.55, 1)));
    c.slabMat.opacity = o; c.faceMat.opacity = o;
    const kc = c.k ? clamp01((p - c.k[0]) / (c.k[1] - c.k[0])) : 1;
    const qk = Math.round(kc * 160) / 160;
    if (qk !== c.last) { c.last = qk; c.draw(qk); }
  }
  function placeTiles(p, t, landscape) {
    const kin = ramp(p, 0.715, 0.8), kout = ramp(p, 0.855, 0.9);
    const R = landscape ? 5 : 3.25;
    const spin = (p - 0.72) * 2.4 + (reduced ? 0 : t * 0.04);
    tiles.forEach((tile, i) => {
      const ti = sm(clamp01(kin * 1.8 - (i / tiles.length) * 0.8));
      const to = sm(clamp01(kout * 1.6 - ((tiles.length - 1 - i) / tiles.length) * 0.6));
      const vis = ti > 0.002 && to < 0.998;
      tile.group.visible = vis;
      if (!vis) return;
      const a = (i / tiles.length) * Math.PI * 2 + spin;
      const r = R * lerp(0.4, 1, ti) * lerp(1, 0.3, to);
      tile.group.position.set(END.x + Math.cos(a) * r, END.y + Math.sin(a * 2) * 0.35 + Math.sin(a) * r * 0.18, END.z + Math.sin(a) * r);
      tile.group.quaternion.copy(camera.quaternion);
      tile.group.scale.setScalar(lerp(0.4, 1, ti) * lerp(1, 0.4, to));
      const o = ti * (1 - to);
      tile.slabMat.opacity = o; tile.faceMat.opacity = o;
      if (tile.last !== 1) { tile.last = 1; tile.draw(1); }
    });
  }

  // ---------- the camera ----------
  const cam = { tx: 0, ty: 0, tz: 0, yaw: 0, pitch: 0, fw: 6, fh: 4 };
  function camAt(p) {
    const K = landscape ? KEYS : KEYS_TALL;
    let i = 0;
    while (i < K.length - 2 && p > K[i + 1][0]) i++;
    const A = K[i], Bk = K[i + 1], e = sm(ramp(p, A[0], Bk[0]));
    cam.tx = lerp(A[1], Bk[1], e); cam.ty = lerp(A[2], Bk[2], e); cam.tz = lerp(A[3], Bk[3], e);
    cam.yaw = lerp(A[4], Bk[4], e); cam.pitch = lerp(A[5], Bk[5], e); cam.fw = lerp(A[6], Bk[6], e); cam.fh = lerp(A[7], Bk[7], e);
  }

  // ---------- size and layout: where the picture sits next to the captions ----------
  let W = 0, H = 0, landscape = true;
  const wide = matchMedia("(min-width: 700px) and (min-aspect-ratio: 21/20)");
  function resize() {
    W = pin.clientWidth; H = pin.clientHeight;
    landscape = wide.matches;
    cards.forEach((c) => { c.home = landscape ? c.wideHome : c.tallHome; });
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
  }
  function region() {
    if (landscape) {
      const capR = Math.max(24, W * 0.05) + Math.min(470, W * 0.38);
      return { x0: capR + 44, x1: W - Math.max(16, W * 0.03), y0: 84, y1: H - 92 };
    }
    return { x0: 10, x1: W - 10, y0: 66, y1: H * 0.57 };
  }

  const pointer = { x: 0, y: 0, sx: 0, sy: 0 };
  if (!coarse) addEventListener("pointermove", (e) => { pointer.x = e.clientX / innerWidth - 0.5; pointer.y = e.clientY / innerHeight - 0.5; }, { passive: true });

  // ---------- the playhead ----------
  const span = () => Math.max(1, root.offsetHeight - pin.offsetHeight);
  const top = () => root.getBoundingClientRect().top + scrollY;
  const scrollP = () => clamp01((scrollY - top()) / span());
  let shown = scrollP(), playing = false;
  const seek = (p, smooth = false) => scrollTo({ top: top() + clamp01(p) * span(), behavior: smooth ? "smooth" : "instant" });

  // captions
  const caps = [...root.querySelectorAll(".cap")].map((el) => ({ el, a: +el.dataset.a, b: +el.dataset.b, last: -1 }));
  function placeCaps(p) {
    for (const c of caps) {
      const fade = 0.022;
      const kin = c.a <= 0 ? 1 : sm(ramp(p, c.a - fade, c.a + fade));
      const kout = c.b >= 1 ? 0 : sm(ramp(p, c.b - fade, c.b + fade));
      const o = kin * (1 - kout);
      const qo = Math.round(o * 200) / 200, dy = Math.round(((1 - kin) * 28 - kout * 28) * 10) / 10;
      const key = qo * 1000 + dy;
      if (key === c.last) continue;
      c.last = key;
      c.el.style.setProperty("--o", qo);
      c.el.style.setProperty("--dy", `${dy}px`);
      c.el.classList.toggle("on", qo > 0.5);
      c.el.toggleAttribute("inert", qo < 0.5);
    }
  }

  // the player bar
  const player = root.querySelector(".player");
  const track = player?.querySelector(".pl-track"), timeEl = player?.querySelector("[data-time]"), chapEl = player?.querySelector("[data-chap]"), playBtn = player?.querySelector("[data-play]");
  const segs = [];
  if (track) {
    track.innerHTML = "";
    CHAPTERS.forEach((ch, i) => {
      const end = CHAPTERS[i + 1]?.at ?? 1;
      const s = document.createElement("button");
      s.type = "button"; s.className = "pl-seg"; s.style.flexGrow = String(end - ch.at);
      s.setAttribute("aria-label", `Go to ${ch.name}`); s.tabIndex = -1;
      s.innerHTML = `<i></i><span>${ch.name}</span>`;
      track.append(s);
      segs.push({ el: s, i: s.firstChild, a: ch.at, b: end });
    });
    const thumb = document.createElement("b"); thumb.className = "pl-thumb"; track.append(thumb);
    segs.thumb = thumb;
    const fromX = (x) => { const r = track.getBoundingClientRect(); return clamp01((x - r.left) / r.width); };
    let drag = false;
    track.addEventListener("pointerdown", (e) => { drag = true; playing = false; track.setPointerCapture(e.pointerId); track.classList.add("drag"); seek(fromX(e.clientX)); });
    track.addEventListener("pointermove", (e) => { if (drag) seek(fromX(e.clientX)); });
    const up = () => { drag = false; track.classList.remove("drag"); };
    track.addEventListener("pointerup", up); track.addEventListener("pointercancel", up);
    track.addEventListener("keydown", (e) => {
      const p = scrollP(), cur = CHAPTERS.findLastIndex((c) => c.at <= p + 0.001);
      if (e.key === "ArrowRight") seek(CHAPTERS[Math.min(CHAPTERS.length - 1, cur + 1)].at + 0.02);
      else if (e.key === "ArrowLeft") seek(p - CHAPTERS[cur].at > 0.03 ? CHAPTERS[cur].at + 0.02 : CHAPTERS[Math.max(0, cur - 1)].at + (cur > 1 ? 0.02 : 0));
      else if (e.key === "Home") seek(0); else if (e.key === "End") seek(1);
      else return;
      e.preventDefault();
    });
  }
  const setPlaying = (on) => {
    playing = on;
    root.classList.toggle("playing", on);
    playBtn?.setAttribute("aria-label", on ? "Pause" : "Play");
    root.querySelectorAll("[data-play-film]").forEach((b) => b.setAttribute("aria-pressed", String(on)));
  };
  const toggle = () => { if (!playing && scrollP() >= 0.999) seek(0); setPlaying(!playing); };
  playBtn?.addEventListener("click", toggle);
  root.querySelectorAll("[data-play-film]").forEach((b) => b.addEventListener("click", toggle));
  root.querySelector("[data-skip]")?.addEventListener("click", () => { setPlaying(false); scrollTo({ top: top() + root.offsetHeight - 70, behavior: "smooth" }); });
  for (const ev of ["wheel", "touchstart"]) addEventListener(ev, () => { if (playing) setPlaying(false); }, { passive: true });
  addEventListener("keydown", (e) => { if (playing && ["ArrowDown", "ArrowUp", "PageDown", "PageUp", " ", "Home", "End"].includes(e.key) && !e.target.closest?.(".player, [data-play-film]")) setPlaying(false); });
  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  let lastUi = -1;
  function placeUi(p) {
    const qp = Math.round(p * 1000);
    if (qp === lastUi || !track) return;
    lastUi = qp;
    segs.forEach((s) => { const f = clamp01((p - s.a) / (s.b - s.a)); s.i.style.transform = `scaleX(${f})`; s.el.classList.toggle("on", p >= s.a && p < s.b + (s.b === 1 ? 1 : 0)); });
    segs.thumb.style.left = `${p * 100}%`;
    track.setAttribute("aria-valuenow", String(Math.round(p * 100)));
    track.setAttribute("aria-valuetext", `${CHAPTERS.findLast((c) => c.at <= p + 0.0001).name}, ${fmt(p * LENGTH)} of ${fmt(LENGTH)}`);
    if (timeEl) timeEl.textContent = `${fmt(p * LENGTH)} / ${fmt(LENGTH)}`;
    if (chapEl) chapEl.textContent = CHAPTERS.findLast((c) => c.at <= p + 0.0001).name;
    root.style.setProperty("--film-p", p.toFixed(4));
  }

  // ---------- the frame ----------
  const clock = new THREE.Clock();
  let last = performance.now(), first = true;
  const ry = new THREE.Vector3();
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    const r = root.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) { if (playing) setPlaying(false); return; }
    if (pin.clientWidth !== W || pin.clientHeight !== H || wide.matches !== landscape) resize();

    if (playing) {
      const np = scrollP() + dt / LENGTH;
      if (np >= 1) { seek(1); setPlaying(false); } else seek(np);
    }
    const target = scrollP();
    shown = first ? target : shown + (target - shown) * (1 - Math.exp(-dt * (playing ? 14 : 6.5)));
    if (Math.abs(target - shown) < 0.00005) shown = target;
    const p = shown, t = clock.getElapsedTime();

    // the beat: at work in the intro and at the end, fully drawn in between
    const loopW = reduced ? 0 : Math.max(1 - sm(ramp(p, 0.012, 0.05)), sm(ramp(p, 0.935, 0.975)));
    const pulse = reduced ? 0 : sm(ramp(p, 0.12, 0.2)) * (1 - sm(ramp(p, 0.7, 0.78))) + 0.25 * sm(ramp(p, 0.75, 0.8)) * (1 - sm(ramp(p, 0.86, 0.92)));
    STRANDS.forEach((s, k) => {
      buildStrand(k, p, reduced ? 0 : t);
      const ph = (((t + s.delay) / BEAT) % 1 + 1) % 1;
      const [tl, hd] = drawn(ph);
      const head = lerp(1, hd, loopW), tail = lerp(0, tl, loopW);
      const U_ = strandU[k];
      U_.uHead.value = head; U_.uTail.value = tail; U_.uTime.value = t; U_.uPulse.value = pulse;
      const P = strands[k].P, E = ends[k];
      const from = new THREE.Color(s.from), to = new THREE.Color(s.to);
      const on = head - tail > 0.004;
      E.capT.visible = E.capH.visible = on;
      if (on) {
        E.capT.position.copy(at(P, Math.max(0.0005, tail))); E.capT.material.color.copy(from).lerp(to, tail);
        E.capH.position.copy(at(P, Math.min(0.9995, head))); E.capH.material.color.copy(from).lerp(to, head);
      }
      const ls = lerp(1, leftDot(ph), loopW), [rs0, ro0] = rightDot(ph);
      const rs = lerp(1, rs0, loopW), ro = lerp(1, ro0, loopW);
      // in the rings the dots shrink away (a ring has no ends)
      const ringK = sm(ramp(p, 0.72, 0.79)) * (1 - sm(ramp(p, 0.86, 0.92)));
      E.L.position.copy(P[0]); E.R.position.copy(P[N]);
      E.L.scale.setScalar(ls * lerp(1, 0.001, ringK)); E.R.scale.setScalar(rs * lerp(1, 0.001, ringK));
      E.R.material.opacity = ro;
      E.R.material.emissive.copy(to).multiplyScalar(Math.max(0, rs - 1) * 1.4);
      E.L.material.emissive.copy(from).multiplyScalar(Math.max(0, ls - 1) * 1.6);
    });

    // camera
    camAt(p);
    if (!coarse) { pointer.sx += (pointer.x - pointer.sx) * 0.05; pointer.sy += (pointer.y - pointer.sy) * 0.05; }
    const idle = reduced ? 0 : 1;
    const yaw = (cam.yaw + pointer.sx * 7 + Math.sin(t * 0.35) * 2.2 * idle) * D2R;
    const pitch = (cam.pitch + pointer.sy * 5 + Math.sin(t * 0.27 + 1) * 1.2 * idle) * D2R;
    const R = region(), rw = R.x1 - R.x0, rh = R.y1 - R.y0;
    const fw = cam.fw, fh = cam.fh;
    const dist = Math.max((fh * H) / rh, (fw * H) / rw) / (2 * Math.tan((camera.fov * D2R) / 2));
    ry.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)).multiplyScalar(dist);
    camera.position.set(cam.tx + ry.x, cam.ty + ry.y, cam.tz + ry.z);
    camera.lookAt(cam.tx, cam.ty, cam.tz);
    camera.setViewOffset(W, H, W / 2 - (R.x0 + R.x1) / 2, H / 2 - (R.y0 + R.y1) / 2, W, H);
    camera.updateProjectionMatrix();
    floorMat.uniforms.uCam.value.copy(camera.position);

    // the glow behind the mark: at the start and at the end
    glows[0].material.opacity = (1 - sm(ramp(p, 0.05, 0.16))) * (theme === "dark" ? 0.9 : 0.75);
    glows[1].material.opacity = sm(ramp(p, 0.76, 0.9)) * (theme === "dark" ? 0.9 : 0.75);
    glows[0].visible = glows[0].material.opacity > 0.01; glows[1].visible = glows[1].material.opacity > 0.01;

    cards.forEach((c) => placeCard(c, p, t));
    placeTiles(p, t, landscape);
    placeCaps(p);
    placeUi(p);
    renderer.render(scene, camera);
    if (first) { first = false; root.classList.add("film-live"); }
  }
  resize();
  requestAnimationFrame(frame);
  return { seek, play: () => setPlaying(true), pause: () => setPlaying(false), get progress() { return shown; } };
}
