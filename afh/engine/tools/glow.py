"""AFH's glow in a tab of the user's own browser: the light round the page, AFH's cursor gliding to each
point, a burst for a click, and a small bar with a Stop button.

It is drawn by a script in an isolated world (the page's own scripts can't see or call it), inside a
closed shadow root on one element next to <body>, so it never shows up in the page's text or among the
things the agent can click. It is taken off the page for every screenshot. Everything here is cosmetic:
whatever fails (a page that is loading, a tab behind another one) is ignored and the action goes on.
"""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("afh.chrome.glow")
WORLD = "AFH"
STOP = "afhStop"

JS = r"""(() => {
  if (globalThis.__afhGlow) return;
  const css = `
  :host { all: initial; position: fixed !important; inset: 0 !important; z-index: 2147483647 !important; pointer-events: none !important; display: block !important;
    --a: 255,177,60; --b: 255,122,61; --c: 255,78,98; --d: 232,44,150; --hot: 255,226,196; --out: cubic-bezier(.16,1,.3,1); --ease: cubic-bezier(.4,0,.2,1); --spring: cubic-bezier(.3,1.45,.5,1); }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  .w { position: absolute; inset: 0; overflow: hidden; font: 13px/1.3 "Segoe UI", system-ui, -apple-system, sans-serif; color: #f7f4f1; direction: ltr; }
  .g { position: absolute; inset: 0; opacity: 0; transform: scale(1.03); transition: opacity .55s var(--ease), transform .9s var(--out); }
  .on .g { opacity: .74; transform: none; } .on.busy .g { opacity: 1; }
  .g > * { position: absolute; inset: 0; }
  .haze { box-shadow: inset 0 0 22px rgba(var(--b),.48), inset 0 0 60px rgba(var(--b),.28), inset 0 0 130px rgba(var(--c),.15); }
  .breath { opacity: .12; box-shadow: inset 0 0 34px rgba(var(--a),.5), inset 0 0 96px rgba(var(--b),.32), inset 0 0 190px rgba(var(--d),.14); }
  .on .breath { animation: breath 3.4s ease-in-out infinite; }
  @keyframes breath { 0%,100% { opacity: .12 } 50% { opacity: .95 } }
  .rim { box-shadow: inset 0 0 0 1.5px rgba(var(--hot),.6), inset 0 0 5px 1px rgba(var(--a),.76), inset 0 0 12px 1px rgba(var(--b),.6); }
  .runs { opacity: 0; transition: opacity .9s var(--ease); } .on.busy .runs { opacity: 1; }
  .runs i { position: absolute; opacity: 0; animation: 7.2s linear infinite paused; }
  .on.busy .runs i { animation-play-state: running; }
  .t, .u { left: 0; width: 64vw; height: 160px; background: radial-gradient(closest-side, rgba(var(--a),.8), rgba(var(--b),.46) 30%, rgba(var(--c),.2) 60%, transparent); }
  .r, .l { top: 0; width: 160px; height: 84vh; background: radial-gradient(closest-side, rgba(var(--b),.78), rgba(var(--c),.46) 32%, rgba(var(--d),.18) 64%, transparent); }
  .runs .t { top: -80px; animation-name: rt } .runs .u { bottom: -80px; animation-name: ru } .runs .r { right: -80px; animation-name: rr } .runs .l { left: -80px; animation-name: rl }
  @keyframes rt { 0% { transform: translateX(-52vw); opacity: 0 } 7%,30% { opacity: 1 } 37%,100% { transform: translateX(88vw); opacity: 0 } }
  @keyframes rr { 0%,25% { transform: translateY(-70vh); opacity: 0 } 32%,48% { opacity: 1 } 55%,100% { transform: translateY(86vh); opacity: 0 } }
  @keyframes ru { 0%,46% { transform: translateX(88vw); opacity: 0 } 53%,76% { opacity: 1 } 83%,100% { transform: translateX(-52vw); opacity: 0 } }
  @keyframes rl { 0%,74% { transform: translateY(86vh); opacity: 0 } 81%,95% { opacity: 1 } 100% { transform: translateY(-70vh); opacity: 0 } }
  .flare { opacity: 0; box-shadow: inset 0 0 30px rgba(var(--hot),.75), inset 0 0 90px rgba(var(--a),.5), inset 0 0 190px rgba(var(--b),.26); }
  .pill { position: absolute; left: 50%; bottom: 20px; display: flex; align-items: center; gap: 12px; height: 46px; padding: 0 6px 0 15px; border-radius: 23px; max-width: calc(100% - 32px); pointer-events: auto;
    background: rgba(20,17,16,.95); box-shadow: inset 0 0 0 1px rgba(255,255,255,.09), 0 12px 34px rgba(0,0,0,.4), 0 0 40px rgba(var(--b),.4); opacity: 0; transform: translate(-50%, 24px) scale(.92); transition: opacity .3s var(--ease), transform .55s var(--spring); }
  .on .pill { opacity: 1; transform: translate(-50%, 0); } .quiet .pill { opacity: .25; } .guard .pill, .w:not(.on) .pill { pointer-events: none; }
  .pill svg { width: 27px; height: 17px; flex: none; }
  .words { min-width: 150px; overflow: hidden; } .who { font-weight: 600; white-space: nowrap; } .what { font-size: 11.5px; color: #cdc6c0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 320px; }
  .stop { all: unset; display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 15px 0 13px; border-radius: 17px; background: #f7f4f1; color: #1a1513; font: 600 12.5px "Segoe UI", system-ui, sans-serif; cursor: pointer; flex: none; }
  .stop:hover { background: #fff } .stop i { width: 10px; height: 10px; border-radius: 2px; background: #f0442f }
  .trail, .cur { position: absolute; left: 0; top: 0; width: 0; height: 0; opacity: 0; transition: opacity .35s }
  .trail i { position: absolute; left: -56px; top: -55px; width: 124px; height: 124px; border-radius: 50%; background: radial-gradient(closest-side, rgba(var(--a),.6), rgba(var(--b),.32) 34%, rgba(var(--c),.13) 64%, transparent) }
  .cur svg { position: absolute; left: -5px; top: -4px; overflow: visible; filter: drop-shadow(0 1px 1.5px rgba(50,12,0,.6)) drop-shadow(0 4px 8px rgba(50,12,0,.28)) drop-shadow(0 0 9px rgba(var(--b),.6)) }
  .cur.s, .trail.s { opacity: 1 }
  .burst, .ring { position: absolute; border-radius: 50% }
  .burst { width: 150px; height: 150px; margin: -75px; background: radial-gradient(closest-side, rgba(var(--hot),.95), rgba(var(--a),.6) 16%, rgba(var(--b),.3) 42%, rgba(var(--c),.1) 70%, transparent) }
  .ring { width: 46px; height: 46px; margin: -23px; box-shadow: 0 0 0 1.5px rgba(var(--hot),.95), 0 0 14px rgba(var(--b),.85), inset 0 0 10px rgba(var(--b),.5) }
  .field { position: absolute; border-radius: 9px; box-shadow: 0 0 0 2px rgba(var(--b),.95), 0 0 20px 2px rgba(var(--b),.6), 0 0 54px 4px rgba(var(--c),.3) }
  .track { position: absolute; width: 26px; height: 66px; margin: -33px 0 0 34px; border-radius: 13px; overflow: hidden; background: rgba(20,17,16,.92); box-shadow: 0 6px 20px rgba(0,0,0,.34), 0 0 26px rgba(var(--b),.4) }
  .track i { position: absolute; left: -4px; right: -4px; top: 0; height: 42px; background: radial-gradient(closest-side, rgba(var(--hot),1), rgba(var(--a),.8) 30%, rgba(var(--b),.35) 62%, transparent) }
  @media (prefers-reduced-motion: reduce) { .on .breath { animation: none; opacity: .5 } .runs { display: none } * { transition-duration: .01ms !important } }`;
  const NS = "http://www.w3.org/2000/svg";
  const el = (cls, tag = "div", ...kids) => { const n = document.createElement(tag); if (cls) n.className = cls; n.append(...kids); return n; };
  const svg = (box, w, h, ...shapes) => {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", box); s.setAttribute("width", w); s.setAttribute("height", h); s.setAttribute("fill", "none");
    for (const [tag, attrs] of shapes) { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); s.append(n); }
    return s;
  };
  const line = (d, c) => ["path", { d, stroke: c, "stroke-width": 14, "stroke-linecap": "round" }];
  const dot = (x, y, c) => ["circle", { cx: x, cy: y, r: 15, fill: c }];
  const mark = svg("28 10 184 120", 27, 17,
    line("M46 112C108 112 116 66 146 66C172 66 170 112 194 112", "#f02a92"), line("M46 70C92 70 98 58 120 60C150 63 152 82 194 70", "#ff6058"),
    line("M46 28C104 28 108 74 134 74C160 74 164 28 194 28", "#ff962e"), dot(46, 112, "#ff3d8a"), dot(194, 112, "#e0169a"), dot(46, 70, "#ff7747"),
    dot(194, 70, "#ff4a68"), dot(46, 28, "#ffb11f"), dot(194, 28, "#ff7a3d"));
  const arrow = svg("0 0 30 32", 30, 32, ["path", { d: "M6.6 4.2 25.2 12.1c1.9.8 1.7 3.5-.2 4.1l-7.1 2.1c-.6.2-1.1.6-1.4 1.2l-3.1 6.6c-.9 1.8-3.6 1.5-4-.5L4.1 6.8C3.7 5 5.1 3.6 6.6 4.2Z",
    fill: "#ff7440", stroke: "#fff", "stroke-width": 1.9, "stroke-linejoin": "round" }]);
  const what = el("what"), flareBox = el("flare");
  const stop = el("stop", "button", el("", "i"), document.createTextNode("Stop"));
  const trail = el("trail", "div", el("", "i")), cur = el("cur", "div", arrow);
  const wrap = el("w", "div",
    el("g", "div", el("haze"), el("breath"), el("runs", "div", el("t", "i"), el("r", "i"), el("u", "i"), el("l", "i")), el("rim"), flareBox),
    trail, cur, el("pill", "div", mark, el("words", "div", Object.assign(el("who"), { textContent: "AFH is using this tab" }), what), stop));
  const host = document.createElement("afh-glow");
  host.setAttribute("aria-hidden", "true");
  const root = host.attachShadow({ mode: "closed" });
  try { const sheet = new CSSStyleSheet(); sheet.replaceSync(css); root.adoptedStyleSheets = [sheet]; }
  catch { const st = document.createElement("style"); st.textContent = css; root.append(st); }
  root.append(wrap);
  stop.addEventListener("click", (e) => { if (e.isTrusted && !wrap.classList.contains("guard")) { try { globalThis.afhStop("stop"); } catch {} say("Stopping…"); } });

  let px = null, py = null, calm = 0, guard = 0;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const put = (n, x, y, ms, frames, easing = "cubic-bezier(.16,1,.3,1)") => {
    n.style.left = x + "px"; n.style.top = y + "px"; wrap.append(n);
    (n._move || n).animate(frames, { duration: ms, easing, fill: "both" });
    setTimeout(() => n.remove(), ms + 60);
  };
  const mount = () => { const at = document.documentElement; if (at && host.parentNode !== at) at.append(host); return !!at; };
  const say = (s) => { what.textContent = s || ""; what.style.display = s ? "" : "none"; };
  const busy = () => {
    wrap.classList.add("on", "busy");
    clearTimeout(calm);
    calm = setTimeout(() => wrap.classList.remove("busy"), 5000);
  };
  const flare = (ms) => flareBox.animate([{ opacity: 0 }, { opacity: 1, offset: .3 }, { opacity: 0 }], { duration: ms, easing: "ease-in-out" });
  const burst = (x, y) => {
    put(el("burst"), x, y, 620, [{ transform: "scale(.12)", opacity: 0 }, { opacity: 1, offset: .18 }, { transform: "scale(1)", opacity: 0 }]);
    put(el("ring"), x, y, 620, [{ transform: "scale(.2)", opacity: 1 }, { transform: "scale(1.7)", opacity: 0 }]);
  };
  async function glide(x, y, ms) {
    const to = `translate(${x}px,${y}px)`;
    if (px === null) {
      cur.style.transform = trail.style.transform = to;
      cur.classList.add("s"); trail.classList.add("s");
      [cur, trail].forEach((n) => n.animate([{ opacity: 0, scale: 1.9 }, { opacity: 1, scale: 1 }], { duration: 420, easing: "cubic-bezier(.16,1,.3,1)" }));
      ms = 200;
    } else {
      const dist = Math.hypot(x - px, y - py);
      ms = ms || Math.max(170, Math.min(520, 150 + dist * .42));
      if (dist < 3) ms = 0;
      const from = `translate(${px}px,${py}px)`, lean = Math.max(-11, Math.min(11, (x - px) / 60));
      const mx = px + (x - px) * .62 - (y - py) * .06, my = py + (y - py) * .62 + (x - px) * .06;
      cur.animate([{ transform: from }, { transform: `translate(${mx}px,${my}px) rotate(${lean}deg)`, offset: .46 }, { transform: to }], { duration: ms, easing: "cubic-bezier(.3,.1,.15,1)" });
      trail.animate([{ transform: from }, { transform: to }], { duration: ms + 190, easing: "cubic-bezier(.25,.1,.2,1)" });
      cur.style.transform = trail.style.transform = to;
    }
    px = x; py = y;
    if (ms) await sleep(ms);
  }
  const G = {
    on(status) { if (!mount()) return; const first = !wrap.classList.contains("on"); if (first) void wrap.offsetWidth; busy(); if (status !== undefined) say(status); if (first) flare(1200); },
    async fx(d) {
      if (!mount()) return;
      busy();
      say(d.what);
      // the agent's own mouse must never land on the Stop button
      const had = d.x != null;
      wrap.classList.add("guard"); wrap.classList.toggle("quiet", had);
      clearTimeout(guard);
      guard = setTimeout(() => wrap.classList.remove("guard", "quiet"), 2200);
      if (document.hidden) return;
      if (had && d.kind !== "scroll") await glide(d.x, d.y);
      else if (had) { await glide(d.x, d.y); const tr = el("track", "div", el("", "i")); tr._move = tr.firstChild; tr.style.rotate = ({ up: 180, left: 90, right: -90 }[d.dir] || 0) + "deg";
        put(tr, d.x, d.y, 760, [{ transform: "translateY(-36px)", opacity: 0 }, { opacity: 1, offset: .3 }, { opacity: 1, offset: .7 }, { transform: "translateY(62px)", opacity: 0 }]); }
      if (d.kind === "click") { burst(d.x, d.y); if (d.count === 2) setTimeout(() => burst(d.x, d.y), 120); cur.animate([{ scale: 1 }, { scale: .8 }, { scale: 1 }], { duration: 260 }); }
      if (d.kind === "drag") { burst(d.x, d.y); setTimeout(async () => { await glide(d.x2, d.y2, 260); burst(d.x2, d.y2); }, 60); }
      if (d.kind === "type") {
        const a = document.activeElement, r = a && a !== document.body && a.getBoundingClientRect();
        if (r && r.width > 8 && r.height > 8) {
          const f = el("field");
          Object.assign(f.style, { width: r.width + 8 + "px", height: r.height + 8 + "px" });
          put(f, r.left - 4, r.top - 4, 1300, [{ opacity: 0, transform: "scale(1.03)" }, { opacity: 1, transform: "none", offset: .2 }, { opacity: 1, offset: .75 }, { opacity: 0 }], "ease-out");
        }
      }
      if (d.kind === "look") flare(640);
    },
    /** Off the page for a screenshot, and back. */
    hide() { host.style.setProperty("visibility", "hidden", "important"); if (document.hidden) return; return new Promise((r) => { const t = setTimeout(r, 120); requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(t); r(); })); }); },
    show() { host.style.removeProperty("visibility"); },
    off() { wrap.classList.remove("on", "busy"); clearTimeout(calm); cur.classList.remove("s"); trail.classList.remove("s"); px = null; setTimeout(() => { if (!wrap.classList.contains("on")) host.remove(); }, 700); },
  };
  globalThis.__afhGlow = G;
})()"""


class Glow:
    """The glow in one ChromeTab. Every method swallows its own failures."""

    def __init__(self, tab):
        self.tab = tab
        self.world: int | None = None  # the isolated world's context id, until the page moves on
        self.lit = False
        self.ready = False  # the Stop binding was added
        self.status = ""

    def on_event(self, method: str, params: dict) -> None:
        if method == "Runtime.executionContextsCleared" or (method == "Page.frameNavigated" and not (params.get("frame") or {}).get("parentId")):
            self.world = None
        elif method == "Page.domContentEventFired" and self.lit:
            asyncio.ensure_future(self.on())  # the page moved: light it again
        elif method == "Runtime.bindingCalled" and params.get("name") == STOP and self.tab.on_stop:
            self.tab.on_stop()

    async def _call(self, expr: str, timeout: float = 2.0) -> None:
        try:
            await asyncio.wait_for(self._eval(expr), timeout)
        except Exception as err:
            self.world = None
            log.debug("glow: %s", err)

    async def _eval(self, expr: str) -> None:
        if not self.ready:
            self.ready = True
            await self.tab.send("Runtime.addBinding", {"name": STOP, "executionContextName": WORLD}, timeout=3)
        if self.world is None:
            frame = (await self.tab.send("Page.getFrameTree", timeout=3))["frameTree"]["frame"]["id"]
            made = await self.tab.send("Page.createIsolatedWorld", {"frameId": frame, "worldName": WORLD}, timeout=3)
            self.world = made["executionContextId"]
            await self.tab.send("Runtime.evaluate", {"expression": JS, "contextId": self.world}, timeout=3)
        res = await self.tab.send("Runtime.evaluate", {"expression": expr, "contextId": self.world, "awaitPromise": True}, timeout=3)
        if res.get("exceptionDetails"):
            log.debug("glow script: %s", str(res["exceptionDetails"])[:300])

    async def on(self, status: str | None = None) -> None:
        self.lit = True
        if status is not None:
            self.status = status
        await self._call(f"__afhGlow.on({json.dumps(self.status)})")

    async def fx(self, what: str, **more) -> None:
        if not self.lit:
            return
        self.status = what[:120]
        await self._call(f"__afhGlow.fx({json.dumps({'what': self.status, **more})})")

    async def hide(self) -> None:
        if self.lit:
            await self._call("__afhGlow.hide()", 1.0)

    async def show(self) -> None:
        if self.lit:
            await self._call("__afhGlow.show()", 1.0)

    async def off(self) -> None:
        if self.lit:
            self.lit = False
            await self._call("__afhGlow.off()", 1.0)
