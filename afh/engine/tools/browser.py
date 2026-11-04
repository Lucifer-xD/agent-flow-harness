"""The `browser` tool: a real browser the agent drives to check its own work, or to do things on the
web for you — open a page (your dev server, a site), look at a screenshot, read the text, click and
type (on an element, or at x,y on the screenshot), run JavaScript and read the console.

Two places it can run:
- **The panel in the AFH window** (the desktop app): tabs in a side panel you watch live, can take
  over at any time, and browse in yourself. The page connects to /api/browser/host and relays the
  Chrome DevTools Protocol of its <webview> tabs (desktop/browser-main.js, web/js/browser.js).
- **Chrome or Edge** already on the computer, through the DevTools Protocol, with its own profile in
  ~/.afh/browser-profile/<browser> (your normal browser and sign-ins are never touched). It runs
  headless unless Settings → Agent → "Show the browser window" is on. Used by the CLI, when the
  window isn't open, or when Settings → Agent → Browser is set to Chrome/Edge.
One tab per thread either way. Screenshots go to vision models as images and show in the tool card.
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from afh.engine.tools.files import BaseTool, ToolError, str_arg
from afh.engine.types import ToolContext, ToolResult, ToolSpec

log = logging.getLogger("afh.browser")
VIEWPORT = (1280, 800)
MAX_TEXT = 30_000
NAV_TIMEOUT = 30.0
ACTIONS = ("open", "screenshot", "text", "click", "double_click", "hover", "drag", "type", "press", "scroll", "back", "forward",
           "reload", "evaluate", "console", "network", "sources", "close")
MODIFIERS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "cmd": 4, "command": 4, "win": 4, "shift": 8}


def find_browsers(settings: dict | None = None) -> list[str]:
    """Browsers to try, best first: the one set in Settings, then Chrome, then Edge."""
    custom = ((settings or {}).get("browser") or {}).get("path")
    candidates: list[str] = [custom] if custom else []
    if sys.platform == "win32":
        bases = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        candidates += [os.path.join(b, "Google", "Chrome", "Application", "chrome.exe") for b in bases if b]
        candidates += [os.path.join(b, "Microsoft", "Edge", "Application", "msedge.exe") for b in bases if b]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    return list(dict.fromkeys(c for c in candidates if c and Path(c).is_file()))


class Tab:
    """One browser tab the tool talks to: DevTools commands, events, and the console kept for `console`."""

    viewport: tuple[int, int] = VIEWPORT

    def __init__(self):
        self.listeners: list[tuple[str, asyncio.Future]] = []
        self.console: list[str] = []
        self.requests: dict[str, dict] = {}  # requestId -> record, insertion-ordered, capped (the Network tab)

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        raise NotImplementedError

    async def screenshot(self) -> tuple[str, int, int]:
        """(base64 JPEG, width, height); width × height is the page's own coordinate space."""
        shot = await self.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70})
        return shot["data"], self.viewport[0], self.viewport[1]

    async def close(self) -> None:
        pass

    def _event(self, method: str, params: dict) -> None:
        if method == "Runtime.consoleAPICalled":
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
            self._log(f"[{params.get('type', 'log')}] {text}")
        elif method == "Runtime.exceptionThrown":
            d = params.get("exceptionDetails") or {}
            self._log(f"[exception] {(d.get('exception') or {}).get('description') or d.get('text', '')}")
        elif method == "Log.entryAdded":
            e = params.get("entry") or {}
            self._log(f"[{e.get('level', 'log')}] {e.get('text', '')} {e.get('url', '')}".rstrip())
        elif method.startswith("Network."):
            self._net(method, params)
        for name, fut in list(self.listeners):
            if name == method and not fut.done():
                fut.set_result(params)
        self.listeners = [(n, f) for n, f in self.listeners if not f.done()]

    def _log(self, line: str) -> None:
        self.console.append(line[:2000])
        del self.console[:-200]

    def _net(self, method: str, params: dict) -> None:
        """Keep a record per request for the `network` action (last 300, like a DevTools Network tab)."""
        rid = params.get("requestId")
        if not rid:
            return
        if method == "Network.requestWillBeSent":
            req = params.get("request") or {}
            prev = self.requests.pop(rid, None)  # a redirect reuses the id: keep it newest in order
            self.requests[rid] = {
                "id": rid, "url": req.get("url", ""), "method": req.get("method", ""), "type": params.get("type", ""),
                "reqHeaders": req.get("headers") or {}, "start": params.get("timestamp"), "status": None, "statusText": "",
                "mime": "", "respHeaders": {}, "size": None, "ms": None, "error": None, "fromCache": False,
            }
            if prev and prev.get("url"):
                self.requests[rid]["redirectedFrom"] = prev["url"]
            while len(self.requests) > 300:
                self.requests.pop(next(iter(self.requests)))
        elif method == "Network.responseReceived":
            r = self.requests.get(rid)
            if r:
                resp = params.get("response") or {}
                r["status"], r["statusText"] = resp.get("status"), resp.get("statusText") or ""
                r["mime"], r["respHeaders"] = resp.get("mimeType", ""), resp.get("headers") or {}
                r["fromCache"] = bool(resp.get("fromDiskCache") or resp.get("fromPrefetchCache"))
                r["type"] = params.get("type") or r["type"]
        elif method == "Network.loadingFinished":
            r = self.requests.get(rid)
            if r:
                r["size"] = params.get("encodedDataLength")
                if r.get("start") is not None and params.get("timestamp") is not None:
                    r["ms"] = round((params["timestamp"] - r["start"]) * 1000)
        elif method == "Network.loadingFailed":
            r = self.requests.get(rid)
            if r:
                r["error"] = params.get("errorText") or ("canceled" if params.get("canceled") else "failed")
                r["type"] = params.get("type") or r["type"]

    def wait_for(self, method: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self.listeners.append((method, fut))
        return fut


class CDP(Tab):
    """One DevTools websocket (a page of the Chrome/Edge the tool started): request/response by id."""

    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        self.ids = itertools.count(1)
        self.waiting: dict[int, asyncio.Future] = {}
        self.reader = asyncio.create_task(self._read())

    @classmethod
    async def connect(cls, url: str) -> "CDP":
        import websockets

        ws = await websockets.connect(url, max_size=64 * 1024 * 1024, ping_interval=None)
        return cls(ws)

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self.waiting.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(ToolError(f"Browser: {msg['error'].get('message', msg['error'])}"))
                        else:
                            fut.set_result(msg.get("result") or {})
                    continue
                self._event(msg.get("method", ""), msg.get("params") or {})
        except Exception:
            pass
        finally:
            for fut in self.waiting.values():
                if not fut.done():
                    fut.set_exception(ToolError("The browser tab closed"))

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        i = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout)

    async def close(self) -> None:
        self.reader.cancel()
        try:
            await self.ws.close()
        except Exception:
            pass


class BrowserManager:
    """The browser process (started on first use) and one tab per thread."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.visible = False
        self.browser_ws: str | None = None
        self.tabs: dict[str, tuple[str, CDP]] = {}  # session id -> (target id, connection)
        self.lock = asyncio.Lock()

    def _profile(self) -> Path:
        from afh import store

        return store.AFH_DIR / "browser-profile"

    async def _ensure(self, settings: dict) -> None:
        visible = bool((settings.get("browser") or {}).get("visible"))
        if self.port and visible == self.visible and await self._alive():
            return
        await self.shutdown()
        exes = find_browsers(settings)
        if not exes:
            raise ToolError("No Chrome or Edge found on this computer. Install one, or set its path in Settings → Agent → Browser.")
        problem = ""
        for exe in exes:  # some installs exit at once (policies, launch stubs): try the next one
            try:
                await self._launch(exe, visible)
                return
            except ToolError as err:
                problem = str(err)
                log.info("browser %s didn't start: %s", exe, err)
        raise ToolError(problem)

    async def _launch(self, exe: str, visible: bool) -> None:
        profile = self._profile() / Path(exe).stem.lower()  # Chrome and Edge profiles don't mix
        profile.mkdir(parents=True, exist_ok=True)
        port_file = profile / "DevToolsActivePort"
        await self._close_stale(port_file)
        args = [exe, "--remote-debugging-port=0", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate", f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}", "about:blank"]
        if not visible:
            args.insert(1, "--headless=new")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        self.visible = visible
        for _ in range(150):
            found = self._read_port(port_file)
            if found:
                self.port, self.browser_ws = found
                break
            # Edge's launcher can exit with 0 after handing off to the real browser: keep waiting then
            code = self.proc.poll()
            if code not in (None, 0):
                self.proc = None
                raise ToolError(f"{Path(exe).name} exited right after starting (code {code})")
            await asyncio.sleep(0.1)
        else:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc = None
            raise ToolError(f"{Path(exe).name} didn't start within 15 seconds")
        log.info("browser started: %s (port %s, %s)", Path(exe).name, self.port, "visible" if visible else "headless")

    @staticmethod
    def _read_port(port_file: Path) -> tuple[int, str] | None:
        try:
            lines = port_file.read_text().splitlines()
            return int(lines[0]), f"ws://127.0.0.1:{int(lines[0])}{lines[1]}"
        except (OSError, ValueError, IndexError):
            return None

    async def _close_stale(self, port_file: Path) -> None:
        """A browser left over from an earlier run (AFH crashed) still holds the profile: close it."""
        found = self._read_port(port_file)
        port_file.unlink(missing_ok=True)
        if found:
            await self._close_browser(found[1])
            await asyncio.sleep(1)

    @staticmethod
    async def _close_browser(ws_url: str) -> None:
        try:
            import websockets

            async with websockets.connect(ws_url, open_timeout=3) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
                await asyncio.wait_for(ws.recv(), 3)
        except Exception:
            pass

    async def tab(self, sid: str, settings: dict) -> CDP:
        async with self.lock:
            await self._ensure(settings)
            if sid in self.tabs:
                return self.tabs[sid][1]
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.put(f"http://127.0.0.1:{self.port}/json/new?about:blank")
                info = r.json()
            cdp = await CDP.connect(info["webSocketDebuggerUrl"])
            for m in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
                await cdp.send(m)
            await cdp.send("Emulation.setDeviceMetricsOverride", {"width": VIEWPORT[0], "height": VIEWPORT[1], "deviceScaleFactor": 1, "mobile": False})
            self.tabs[sid] = (info["id"], cdp)
            return cdp

    async def close_tab(self, sid: str) -> None:
        entry = self.tabs.pop(sid, None)
        if not entry:
            return
        target, cdp = entry
        await cdp.close()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(f"http://127.0.0.1:{self.port}/json/close/{target}")
        except httpx.HTTPError:
            pass

    async def shutdown(self) -> None:
        for sid in list(self.tabs):
            await self.close_tab(sid)
        if self.browser_ws:
            await self._close_browser(self.browser_ws)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.port = None
        self.browser_ws = None

    async def _alive(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                return (await client.get(f"http://127.0.0.1:{self.port}/json/version")).status_code == 200
        except httpx.HTTPError:
            return False


MANAGER = BrowserManager()


class PanelTab(Tab):
    """A tab of the browser panel in the AFH window; commands go through the page (PanelHost)."""

    def __init__(self, host: "PanelHost", tab: str):
        super().__init__()
        self.host = host
        self.tab = tab

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        return await self.host.request("cdp", timeout, tab=self.tab, method=method, params=params or {}) or {}

    async def screenshot(self) -> tuple[str, int, int]:
        shot = await self.host.request("shot", 30, tab=self.tab) or {}
        if shot.get("minimized"):
            raise ToolError("The AFH window is minimized, so its browser panel can't be seen. The action itself went through; "
                            "ask the user to restore the window (it can stay behind other windows), or use `text` to read the page.")
        if not shot.get("data"):
            raise ToolError("The browser panel couldn't take a screenshot; try again, or use `text` to read the page.")
        self.viewport = (int(shot["width"]), int(shot["height"]))
        return shot["data"], self.viewport[0], self.viewport[1]


class PanelHost:
    """The AFH window's browser panel, connected over /api/browser/host while the desktop app is open.

    Messages to the page: {id, op: "open", sid} → {tab}; {id, op: "cdp", tab, method, params} → the result;
    {id, op: "shot", tab} → {data, width, height}; {id, op: "close", tab}; {op: "activity", sid, tab, what}.
    From the page: {id, result} / {id, error}; {event: {tab, method, params}}; {op: "closed", tab} when you
    close a tab; {op: "takeover", sid} / {op: "handback", sid} when you take the agent's tab over or give it back.
    """

    def __init__(self):
        self.ws = None
        self.ids = itertools.count(1)
        self.pending: dict[int, asyncio.Future] = {}
        self.tabs: dict[str, PanelTab] = {}  # session id -> its tab
        self.paused: set[str] = set()  # threads whose tab you took over
        self.send_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self.ws is not None

    async def serve(self, ws) -> None:
        """Runs for as long as the page stays connected; a newer page replaces an older one."""
        await ws.accept()
        old, self.ws = self.ws, ws
        if old is not None:
            self._drop()
            try:
                await old.close()
            except Exception:
                pass
        log.info("browser panel connected")
        try:
            while True:
                self._receive(await ws.receive_json())
        except Exception:
            pass
        finally:
            if self.ws is ws:
                self.ws = None
                self._drop()
                log.info("browser panel disconnected")

    def _receive(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        if "id" in msg and ("result" in msg or "error" in msg):
            fut = self.pending.pop(msg["id"], None)
            if fut and not fut.done():
                if msg.get("error"):
                    fut.set_exception(ToolError(f"Browser: {msg['error']}"))
                else:
                    fut.set_result(msg.get("result"))
            return
        if isinstance(msg.get("event"), dict):
            ev = msg["event"]
            for tab in self.tabs.values():
                if tab.tab == ev.get("tab"):
                    tab._event(str(ev.get("method", "")), ev.get("params") or {})
            return
        op, sid = msg.get("op"), str(msg.get("sid") or "")
        if op == "closed":
            for key, tab in list(self.tabs.items()):
                if tab.tab == msg.get("tab"):
                    del self.tabs[key]
        elif op == "takeover" and sid:
            self.paused.add(sid)
        elif op == "handback" and sid:
            self.paused.discard(sid)

    def _drop(self) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(ToolError("The AFH window's browser panel closed"))
        self.pending.clear()
        self.tabs.clear()

    async def _send(self, msg: dict) -> None:
        if self.ws is None:
            raise ToolError("The AFH window isn't open, so its browser panel isn't available")
        async with self.send_lock:
            await self.ws.send_json(msg)

    async def request(self, op: str, timeout: float = 30, **fields):
        i = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        try:
            await self._send({"id": i, "op": op, **fields})
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise ToolError(f"The browser panel didn't answer ({op})") from None
        finally:
            self.pending.pop(i, None)

    async def tab(self, sid: str) -> PanelTab:
        if sid in self.tabs:
            return self.tabs[sid]
        info = await self.request("open", 30, sid=sid) or {}
        tab = PanelTab(self, str(info.get("tab", "")))
        for m in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
            await tab.send(m)
        self.tabs[sid] = tab
        return tab

    async def activity(self, sid: str, what: str, x: float | None = None, y: float | None = None) -> None:
        """Tells the page what the agent is doing, for the "AFH is using this tab" bar."""
        tab = self.tabs.get(sid)
        try:
            await self._send({"op": "activity", "sid": sid, "tab": tab.tab if tab else None, "what": what, "x": x, "y": y})
        except Exception:
            pass

    async def close_tab(self, sid: str) -> None:
        tab = self.tabs.pop(sid, None)
        if tab and self.ws is not None:
            try:
                await self.request("close", 10, tab=tab.tab)
            except ToolError:
                pass


PANEL = PanelHost()


def use_panel(settings: dict) -> bool:
    """The panel when the AFH window is open, unless Settings → Agent → Browser says Chrome/Edge."""
    return PANEL.connected and ((settings or {}).get("browser") or {}).get("where") != "external"

# Finds an element by CSS selector or by its visible text (buttons, links, labels).
_FIND_JS = """(q) => {
  let el = null;
  try { el = document.querySelector(q); } catch (e) {}
  if (!el) {
    const want = q.trim().toLowerCase();
    const all = [...document.querySelectorAll('a,button,input,textarea,select,label,[role=button],[role=link],summary,[onclick],[tabindex]')];
    el = all.find(e => (e.innerText || e.value || e.getAttribute('aria-label') || e.placeholder || '').trim().toLowerCase() === want)
      || all.find(e => (e.innerText || e.value || e.getAttribute('aria-label') || e.placeholder || '').trim().toLowerCase().includes(want));
  }
  if (!el) return null;
  el.scrollIntoView({block: 'center', inline: 'center'});
  const r = el.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, tag: el.tagName.toLowerCase(), text: (el.innerText || el.value || '').slice(0, 80)};
}"""


class BrowserTool(BaseTool):
    spec = ToolSpec(
        name="browser",
        description=(
            "A real web browser with DevTools to check your work like a user would, or to do things on the web: open your dev "
            "server or any page, see a screenshot, read the page text, click, type, press keys, scroll, run JavaScript in the "
            "page, read console errors, inspect network requests, and read the source files the page loaded. "
            "One tab per thread that keeps its state (and sign-ins) between calls; in the AFH app it is a side panel the user "
            "watches live and can take over. Actions: `open` (url), `screenshot`, `text`, `click` / `double_click` / `hover` "
            "(target: CSS selector or visible text, or x,y read off the latest screenshot), `drag` (x,y to to_x,to_y), `type` "
            "(text; into target or x,y if given, else the focused field; submit:true presses Enter), `press` (key, e.g. Enter, Tab, "
            "Escape, Ctrl+A), `scroll` (direction up/down/left/right, optional amount in pixels and x,y), `back`, `forward`, "
            "`reload`, `evaluate` (script: a JS expression, run in the page console — its value is returned), `console` (log "
            "messages and errors since the last call), `network` (the requests the page made — method, status, type, size, "
            "timing; pass url=<part of a URL> to get one request's headers and response body), `sources` (the files the page "
            "loaded — the HTML document, scripts, stylesheets; pass url=<part of a URL> to read one file's contents), `close`. "
            "Every action except text/evaluate/console/network/sources/close returns a fresh screenshot whose pixels are the "
            "page's coordinates. Start a dev server with the shell tool (background: true) first when you need one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS), "description": "What to do in this thread's tab."},
                "url": {"type": "string", "description": "For open: the page (http(s):// or file://). For network/sources: part of a request or file URL to drill into (omit to list)."},
                "target": {"type": "string", "description": "For click/double_click/hover/type: a CSS selector or the element's visible text."},
                "x": {"type": "number", "description": "For click/double_click/hover/drag/type/scroll: x on the latest screenshot (instead of target)."},
                "y": {"type": "number", "description": "y on the latest screenshot."},
                "to_x": {"type": "number", "description": "For drag: where to drop, x."},
                "to_y": {"type": "number", "description": "For drag: where to drop, y."},
                "text": {"type": "string", "description": "For type: the text to enter."},
                "submit": {"type": "boolean", "description": "For type: press Enter afterwards."},
                "key": {"type": "string", "description": "For press: a key such as Enter, Tab, Escape, ArrowDown, or a combination like Ctrl+A."},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "For scroll."},
                "amount": {"type": "number", "description": "For scroll: how far in pixels (default 650)."},
                "script": {"type": "string", "description": "For evaluate: a JavaScript expression; its value is returned."},
            },
            "required": ["action"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        action = str_arg(input, "action").strip().lower()
        if action not in ACTIONS:
            raise ToolError(f"Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}.")
        panel = use_panel(ctx.settings)
        sid = ctx.session_id
        if panel and sid in PANEL.paused:
            return ToolResult(text="The user has taken over this thread's browser tab and is using it themselves. Don't use the browser "
                                   "until they hand it back or ask you to; tell them what you wanted to do there.", is_error=True)
        if action == "close":
            await (PANEL.close_tab(sid) if panel else MANAGER.close_tab(sid))
            return ToolResult(text="Closed this thread's browser tab.")
        url = ""
        if action == "open":
            url = str_arg(input, "url").strip()
            if not urlsplit(url).scheme:
                url = "http://" + url
            if urlsplit(url).scheme not in ("http", "https", "file"):
                raise ToolError("Only http(s):// and file:// pages can be opened.")
            await ctx.permissions.require("web", [url], {"url": url, "tool": "browser"})
        elif action == "evaluate":
            await ctx.permissions.require("web", ["javascript"], {"tool": "browser", "script": str(input.get("script", ""))[:500]})
        page = await (PANEL.tab(sid) if panel else MANAGER.tab(sid, ctx.settings))

        async def show(what: str, x=None, y=None) -> None:
            if panel:
                await PANEL.activity(sid, what, x, y)

        if action == "open":
            await show(f"Opening {url}")
            for attempt in range(3):
                loaded = page.wait_for("Page.loadEventFired")
                res = await page.send("Page.navigate", {"url": url})
                # a fresh browser can report the network changing while it settles: try again
                if res.get("errorText") not in ("net::ERR_NETWORK_CHANGED", "net::ERR_NETWORK_IO_SUSPENDED") or attempt == 2:
                    break
                await asyncio.sleep(1)
            if res.get("errorText"):
                return ToolResult(text=f"Couldn't open {url}: {res['errorText']}", is_error=True)
            await self._settle(loaded)
            return await self._shot(page, f"Opened {await self._where(page)}")
        if action == "screenshot":
            return await self._shot(page, f"Screenshot of {await self._where(page)}")
        if action == "text":
            await show("Reading the page")
            text = await self._eval(page, "document.body ? document.body.innerText : ''")
            text = str(text or "")
            cut = len(text) > MAX_TEXT
            return ToolResult(text=f"{await self._where(page)}\n\n{text[:MAX_TEXT]}" + ("\n\n[…cut]" if cut else ""), truncated=cut)
        if action in ("back", "forward", "reload"):
            await show({"back": "Going back", "forward": "Going forward", "reload": "Reloading"}[action])
            loaded = page.wait_for("Page.loadEventFired")
            if action == "reload":
                await page.send("Page.reload", {})
            else:
                await self._eval(page, f"history.{action}()")
            await self._settle(loaded, 10)
            return await self._shot(page, f"{'Reloaded' if action == 'reload' else 'Went ' + action}: {await self._where(page)}")
        into = ""
        if action in ("click", "double_click", "hover", "drag") or (action == "type" and (input.get("target") or input.get("x") is not None)):
            spot = await self._spot(page, input)
            if isinstance(spot, ToolResult):
                return spot
            x, y, what = spot
            if action == "hover":
                await show(f"Pointing at {what}", x, y)
                await self._mouse(page, "mouseMoved", x, y)
                await asyncio.sleep(0.4)
                return await self._shot(page, f"Moved the pointer to {what}")
            if action == "drag":
                if input.get("to_x") is None or input.get("to_y") is None:
                    raise ToolError("drag needs to_x and to_y.")
                tx, ty = float(input["to_x"]), float(input["to_y"])
                await show(f"Dragging from {what} to ({round(tx)}, {round(ty)})", x, y)
                await self._mouse(page, "mouseMoved", x, y)
                await self._mouse(page, "mousePressed", x, y, clicks=1)
                for i in range(1, 9):  # a few steps in between, so pages that track the movement see it
                    await self._mouse(page, "mouseMoved", x + (tx - x) * i / 8, y + (ty - y) * i / 8, buttons=1)
                    await asyncio.sleep(0.02)
                await self._mouse(page, "mouseReleased", tx, ty, clicks=1)
                await asyncio.sleep(0.5)
                return await self._shot(page, f"Dragged from {what} to ({round(tx)}, {round(ty)})")
            clicks = 2 if action == "double_click" else 1
            await show(f"{'Double-clicking' if clicks == 2 else 'Clicking'} {what}", x, y)
            await self._mouse(page, "mouseMoved", x, y)
            for n in range(1, clicks + 1):
                await self._mouse(page, "mousePressed", x, y, clicks=n)
                await self._mouse(page, "mouseReleased", x, y, clicks=n)
            if action != "type":
                await asyncio.sleep(0.6)
                return await self._shot(page, f"{'Double-clicked' if clicks == 2 else 'Clicked'} {what}")
            into = f" into {what}"
        if action == "type":
            await show(f"Typing{into}")
            await page.send("Input.insertText", {"text": str(input.get("text", ""))})
            if input.get("submit"):
                await self._key(page, "Enter")
            await asyncio.sleep(0.5)
            return await self._shot(page, f"Typed{into or ' into the focused field'}" + (" and pressed Enter" if input.get("submit") else ""))
        if action == "press":
            key = str_arg(input, "key")
            await show(f"Pressing {key}")
            await self._key(page, key)
            await asyncio.sleep(0.4)
            return await self._shot(page, f"Pressed {key}")
        if action == "scroll":
            direction = str(input.get("direction", "down")).lower()
            amount = abs(float(input.get("amount") or 650))
            dx = {"left": -amount, "right": amount}.get(direction, 0)
            dy = 0 if dx else (-amount if direction == "up" else amount)
            if input.get("x") is not None and input.get("y") is not None:
                x, y = float(input["x"]), float(input["y"])
            else:
                w, h = await self._size(page)
                x, y = w / 2, h / 2
            await show(f"Scrolling {direction}", x, y)
            await page.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy})
            await asyncio.sleep(0.5)
            return await self._shot(page, f"Scrolled {direction}")
        if action == "evaluate":
            await show("Running JavaScript")
            value = await self._eval(page, str_arg(input, "script"))
            out = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str)
            return ToolResult(text=str(out)[:MAX_TEXT])
        if action == "network":
            await show("Inspecting network")
            return await self._network(page, input)
        if action == "sources":
            await show("Inspecting source files")
            return await self._sources(page, input)
        # console
        lines, page.console = page.console[:], []
        return ToolResult(text="\n".join(lines) if lines else "No console messages since the last check.")

    @staticmethod
    async def _settle(loaded: asyncio.Future, timeout: float = NAV_TIMEOUT) -> None:
        try:
            await asyncio.wait_for(loaded, timeout)
        except asyncio.TimeoutError:
            pass  # still loading; show what is there
        await asyncio.sleep(0.6)

    async def _spot(self, page: Tab, input: dict):
        """(x, y, description) of the target element or the given point, or a ToolResult explaining the miss."""
        if input.get("x") is not None and input.get("y") is not None:
            x, y = float(input["x"]), float(input["y"])
            label = await self._eval(page, f"({_AT_JS})({x}, {y})")
            return x, y, f"{label or 'the page'} at ({round(x)}, {round(y)})"
        target = str(input.get("target") or "").strip()
        if not target:
            raise ToolError("Give a target (CSS selector or visible text) or x and y from the screenshot.")
        spot = await self._eval(page, f"({_FIND_JS})({json.dumps(target)})")
        if not spot:
            return ToolResult(text=f"No element matches {target!r} on {await self._where(page)}. Try `text`, or a screenshot and x,y.", is_error=True)
        return spot["x"], spot["y"], f"{spot['tag']}{' “' + spot['text'] + '”' if spot.get('text') else ''}"

    @staticmethod
    async def _mouse(page: Tab, kind: str, x: float, y: float, clicks: int = 0, buttons: int = 0) -> None:
        params = {"type": kind, "x": x, "y": y}
        if kind in ("mousePressed", "mouseReleased"):
            params.update(button="left", clickCount=clicks, buttons=1 if kind == "mousePressed" else 0)
        elif buttons:
            params.update(button="left", buttons=buttons)
        await page.send("Input.dispatchMouseEvent", params)

    @classmethod
    async def _size(cls, page: Tab) -> tuple[float, float]:
        size = await cls._eval(page, "[innerWidth, innerHeight]")
        return (float(size[0]), float(size[1])) if isinstance(size, list) and len(size) == 2 else page.viewport

    @staticmethod
    async def _eval(page: Tab, expr: str):
        res = await page.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            raise ToolError(f"JavaScript error: {(d.get('exception') or {}).get('description') or d.get('text', '')}")
        return (res.get("result") or {}).get("value")

    async def _where(self, page: Tab) -> str:
        info = await self._eval(page, "({t: document.title, u: location.href})") or {}
        return f"{info.get('t') or '(untitled)'} — {info.get('u', '')}"

    @staticmethod
    def _keys(combo: str) -> dict:
        """The DevTools key event for "Enter", "a", "Ctrl+A", "Shift+Tab"…"""
        parts = [p for p in combo.replace(" ", "").split("+") if p] or ["+"]
        *mods, key = parts if not combo.strip().endswith("++") else [*parts, "+"]
        mask = 0
        for m in mods:
            mask |= MODIFIERS.get(m.lower(), 0)
        key = _KEY_NAMES.get(key.lower(), key)
        if len(key) == 1 and key.isalpha():
            key = key.upper() if mask & 8 else key.lower()
        if len(key) == 1:
            vk = ord(key.upper()) if key.isalnum() else _KEY_CODES.get(key, 0)
            code = f"Key{key.upper()}" if key.isalpha() else f"Digit{key}" if key.isdigit() else "Space" if key == " " else ""
        else:
            vk, code = _KEY_CODES.get(key, 0), key
        params = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "modifiers": mask}
        if key == "Enter" and not mask:
            params["text"] = "\r"
        elif len(key) == 1 and not mask & ~8:  # plain or with Shift: it types the character
            params["text"] = key
        command = _EDIT_COMMANDS.get((mask & ~4 | (2 if mask & 4 else 0), key.lower()))  # Cmd works like Ctrl
        if command:
            params["commands"] = [command]  # pages get the key, the field does the edit
        return params

    @classmethod
    async def _key(cls, page: Tab, combo: str) -> None:
        params = cls._keys(combo)
        await page.send("Input.dispatchKeyEvent", {"type": "keyDown" if "text" in params else "rawKeyDown", **params})
        await page.send("Input.dispatchKeyEvent", {"type": "keyUp", **{k: v for k, v in params.items() if k != "text"}})

    # ---- DevTools: network & sources --------------------------------------------------------------

    async def _network(self, page: Tab, input: dict) -> ToolResult:
        """List the requests the page made, or (with url) one request's headers and response body."""
        reqs = list(page.requests.values())
        if not reqs:
            return ToolResult(text="No network requests recorded for this tab yet. Open or reload a page first "
                                   "(requests are captured from when the tab opens).")
        want = str(input.get("url") or "").strip().lower()
        if want:
            matches = [r for r in reqs if want in (r.get("url") or "").lower()]
            if not matches:
                return ToolResult(text=f"No recorded request's URL contains {want!r}. Call `network` with no url to list them.", is_error=True)
            blocks = [await self._request_detail(page, r) for r in matches[-5:]]
            head = "" if len(matches) <= 5 else f"(showing the last 5 of {len(matches)} matching requests)\n\n"
            return ToolResult(text=head + ("\n\n" + "─" * 48 + "\n\n").join(blocks), truncated=len(matches) > 5)
        lines = [self._request_line(r) for r in reqs[-150:]]
        extra = "" if len(reqs) <= 150 else f"(last 150 of {len(reqs)})\n"
        return ToolResult(text=f"Network requests (oldest first) — status, method, type, size, time, URL:\n{extra}" + "\n".join(lines) +
                               "\n\nCall `network` with url=<part of a URL> to see one request's headers and response body.")

    @staticmethod
    def _request_line(r: dict) -> str:
        status = "ERR" if r.get("error") else (str(r["status"]) if r.get("status") is not None else "...")
        size = r.get("size")
        size_s = (f"{round(size / 1024)}K" if isinstance(size, (int, float)) and size >= 1024
                  else str(int(size)) if isinstance(size, (int, float)) else "-")
        ms = f"{r['ms']}ms" if r.get("ms") is not None else ("cache" if r.get("fromCache") else "-")
        return f"{status:>4} {r.get('method', ''):4} {(r.get('type') or '')[:11]:11} {size_s:>6} {ms:>7}  {(r.get('url') or '')[:170]}"

    async def _request_detail(self, page: Tab, r: dict) -> str:
        def headers(h: dict) -> str:
            return "\n".join(f"  {k}: {v}" for k, v in list((h or {}).items())[:40]) or "  (none)"

        status = f"FAILED ({r['error']})" if r.get("error") else (
            f"{r['status']} {r.get('statusText', '')}".strip() if r.get("status") is not None else "(pending)")
        parts = [f"{r.get('method', '')} {r.get('url', '')}",
                 f"Status: {status}   Type: {r.get('type') or '?'}   {r.get('mime') or ''}".rstrip()]
        if r.get("redirectedFrom"):
            parts.append(f"Redirected from: {r['redirectedFrom']}")
        parts.append("Request headers:\n" + headers(r.get("reqHeaders")))
        if r.get("respHeaders"):
            parts.append("Response headers:\n" + headers(r.get("respHeaders")))
        body = "(not fetched)"
        try:
            got = await page.send("Network.getResponseBody", {"requestId": r["id"]})
            raw = got.get("body") or ""
            body = f"(binary, {len(raw)} base64 chars)" if got.get("base64Encoded") else raw
        except ToolError:
            body = "(response body not available — it may have been evicted from the buffer, or the request has no body)"
        cut = len(body) > 8000
        parts.append("Response body:\n" + body[:8000] + ("\n[…cut]" if cut else ""))
        return "\n".join(parts)

    async def _sources(self, page: Tab, input: dict) -> ToolResult:
        """List the files the page loaded, or (with url) read one file's contents."""
        tree = await page.send("Page.getResourceTree")
        res: list[dict] = []

        def walk(node: dict) -> None:
            frame = node.get("frame") or {}
            if frame.get("url"):
                res.append({"frameId": frame.get("id"), "url": frame["url"], "type": "Document"})
            for item in node.get("resources") or []:
                res.append({"frameId": frame.get("id"), "url": item.get("url"), "type": item.get("type"), "size": item.get("contentSize")})
            for child in node.get("childFrames") or []:
                walk(child)

        walk(tree.get("frameTree") or {})
        if not res:
            return ToolResult(text="No source files found. Open a page first.")
        want = str(input.get("url") or "").strip().lower()
        if want:
            match = next((x for x in res if want in (x.get("url") or "").lower()), None)
            if not match:
                return ToolResult(text=f"No loaded file's URL contains {want!r}. Call `sources` with no url to list them.", is_error=True)
            try:
                got = await page.send("Page.getResourceContent", {"frameId": match["frameId"], "url": match["url"]})
            except ToolError as err:
                return ToolResult(text=f"Couldn't read {match['url']}: {err}", is_error=True)
            content = got.get("content") or ""
            if got.get("base64Encoded"):
                return ToolResult(text=f"{match['url']} ({match.get('type')}) is binary ({len(content)} base64 chars); not shown as text.")
            cut = len(content) > MAX_TEXT
            return ToolResult(text=f"{match['url']} ({match.get('type')}):\n\n{content[:MAX_TEXT]}" + ("\n\n[…cut]" if cut else ""), truncated=cut)
        lines = [f"{(x.get('type') or '?'):10} {(x.get('url') or '')[:180]}" for x in res[:200]]
        extra = "" if len(res) <= 200 else f"(first 200 of {len(res)})\n"
        return ToolResult(text=f"Source files this page loaded (document, scripts, stylesheets, images…):\n{extra}" + "\n".join(lines) +
                               "\n\nCall `sources` with url=<part of a URL> to read one file's contents.")

    async def _shot(self, page: Tab, summary: str) -> ToolResult:
        data, w, h = await page.screenshot()
        uri = "data:image/jpeg;base64," + data
        errors = [line for line in page.console if line.startswith(("[error]", "[exception]"))]
        note = "\n\nConsole errors on this page:\n" + "\n".join(errors[-10:]) if errors else ""
        size = len(base64.b64decode(data)) // 1024
        return ToolResult(text=f"{summary}. Screenshot attached ({w}×{h}, {size} KB; x,y on it are page coordinates).{note}",
                          images=[uri], metadata={"screenshot": True})


_KEY_NAMES = {"enter": "Enter", "return": "Enter", "tab": "Tab", "escape": "Escape", "esc": "Escape", "backspace": "Backspace",
              "delete": "Delete", "del": "Delete", "arrowdown": "ArrowDown", "down": "ArrowDown", "arrowup": "ArrowUp", "up": "ArrowUp",
              "arrowleft": "ArrowLeft", "left": "ArrowLeft", "arrowright": "ArrowRight", "right": "ArrowRight", "space": " ",
              "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown"}
_KEY_CODES = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46, "ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37,
              "ArrowRight": 39, " ": 32, "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34}

_EDIT_COMMANDS = {(2, "a"): "selectAll", (2, "c"): "copy", (2, "x"): "cut", (2, "v"): "paste", (2, "z"): "undo", (10, "z"): "redo",
                  (2, "y"): "redo"}

# Names what is at a point (for "Clicked button “Save” at (412, 230)").
_AT_JS = """(x, y) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return '';
  const t = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('alt') || el.placeholder || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
  return el.tagName.toLowerCase() + (t ? ' “' + t + '”' : '');
}"""
