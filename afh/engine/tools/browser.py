"""The `browser` tool: a real browser the agent drives to check its own work — open a page (your
dev server, a site), look at a screenshot, read the text, click, type, run JavaScript and read
the console.

It uses the Chrome or Edge already on the computer through the Chrome DevTools Protocol, with
its own profile in ~/.afh/browser-profile/<browser> (your normal browser and sign-ins are never touched).
One tab per thread; it runs headless unless Settings → Agent → "Show the browser window" is on.
Screenshots go to vision models as images and show in the tool card.
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
ACTIONS = ("open", "screenshot", "text", "click", "type", "press", "scroll", "evaluate", "console", "close")


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


class CDP:
    """One DevTools websocket (a page): request/response by id, events kept for the console."""

    def __init__(self, ws):
        self.ws = ws
        self.ids = itertools.count(1)
        self.waiting: dict[int, asyncio.Future] = {}
        self.listeners: list[tuple[str, asyncio.Future]] = []
        self.console: list[str] = []
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
                method = msg.get("method", "")
                params = msg.get("params") or {}
                if method == "Runtime.consoleAPICalled":
                    text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
                    self._log(f"[{params.get('type', 'log')}] {text}")
                elif method == "Runtime.exceptionThrown":
                    d = params.get("exceptionDetails") or {}
                    self._log(f"[exception] {(d.get('exception') or {}).get('description') or d.get('text', '')}")
                elif method == "Log.entryAdded":
                    e = params.get("entry") or {}
                    self._log(f"[{e.get('level', 'log')}] {e.get('text', '')} {e.get('url', '')}".rstrip())
                for name, fut in list(self.listeners):
                    if name == method and not fut.done():
                        fut.set_result(params)
                self.listeners = [(n, f) for n, f in self.listeners if not f.done()]
        except Exception:
            pass
        finally:
            for fut in self.waiting.values():
                if not fut.done():
                    fut.set_exception(ToolError("The browser tab closed"))

    def _log(self, line: str) -> None:
        self.console.append(line[:2000])
        del self.console[:-200]

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        i = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout)

    def wait_for(self, method: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self.listeners.append((method, fut))
        return fut

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
            for m in ("Page.enable", "Runtime.enable", "Log.enable"):
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
            "A real web browser (Chrome/Edge) to check your work like a user would: open your dev server or any page, see a "
            "screenshot, read the page text, click, type, press keys, scroll, run JavaScript, and read console errors. One tab "
            "per thread that keeps its state between calls. Actions: `open` (url), `screenshot`, `text`, `click` (target: CSS "
            "selector or visible text), `type` (target, text; submit:true presses Enter), `press` (key, e.g. Enter, Tab, "
            "Escape), `scroll` (direction up/down), `evaluate` (script: a JS expression), `console` (messages and errors since "
            "the last call), `close`. open/click/type/press/scroll return a fresh screenshot. Start a dev server with the shell "
            "tool (background: true) first when you need one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS), "description": "What to do in this thread's tab."},
                "url": {"type": "string", "description": "For open: the page (http(s):// or file://)."},
                "target": {"type": "string", "description": "For click/type: a CSS selector or the element's visible text."},
                "text": {"type": "string", "description": "For type: the text to enter."},
                "submit": {"type": "boolean", "description": "For type: press Enter afterwards."},
                "key": {"type": "string", "description": "For press: a key name such as Enter, Tab, Escape, ArrowDown."},
                "direction": {"type": "string", "enum": ["up", "down"], "description": "For scroll."},
                "script": {"type": "string", "description": "For evaluate: a JavaScript expression; its value is returned."},
            },
            "required": ["action"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        action = str_arg(input, "action").strip().lower()
        if action not in ACTIONS:
            raise ToolError(f"Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}.")
        if action == "close":
            await MANAGER.close_tab(ctx.session_id)
            return ToolResult(text="Closed this thread's browser tab.")
        if action == "open":
            url = str_arg(input, "url").strip()
            if not urlsplit(url).scheme:
                url = "http://" + url
            if urlsplit(url).scheme not in ("http", "https", "file"):
                raise ToolError("Only http(s):// and file:// pages can be opened.")
            await ctx.permissions.require("web", [url], {"url": url, "tool": "browser"})
        elif action == "evaluate":
            await ctx.permissions.require("web", ["javascript"], {"tool": "browser", "script": str(input.get("script", ""))[:500]})
        page = await MANAGER.tab(ctx.session_id, ctx.settings)

        if action == "open":
            for attempt in range(3):
                loaded = page.wait_for("Page.loadEventFired")
                res = await page.send("Page.navigate", {"url": url})
                # a fresh browser can report the network changing while it settles: try again
                if res.get("errorText") not in ("net::ERR_NETWORK_CHANGED", "net::ERR_NETWORK_IO_SUSPENDED") or attempt == 2:
                    break
                await asyncio.sleep(1)
            if res.get("errorText"):
                return ToolResult(text=f"Couldn't open {url}: {res['errorText']}", is_error=True)
            try:
                await asyncio.wait_for(loaded, NAV_TIMEOUT)
            except asyncio.TimeoutError:
                pass  # still loading; show what is there
            await asyncio.sleep(0.6)
            return await self._shot(page, f"Opened {await self._where(page)}")
        if action == "screenshot":
            return await self._shot(page, f"Screenshot of {await self._where(page)}")
        if action == "text":
            text = await self._eval(page, "document.body ? document.body.innerText : ''")
            text = str(text or "")
            cut = len(text) > MAX_TEXT
            return ToolResult(text=f"{await self._where(page)}\n\n{text[:MAX_TEXT]}" + ("\n\n[…cut]" if cut else ""), truncated=cut)
        if action in ("click", "type"):
            target = str_arg(input, "target")
            spot = await self._eval(page, f"({_FIND_JS})({json.dumps(target)})")
            if not spot:
                return ToolResult(text=f"No element matches {target!r} on {await self._where(page)}. Try `text` or a screenshot to see what's there.", is_error=True)
            x, y = spot["x"], spot["y"]
            for kind in ("mousePressed", "mouseReleased"):
                await page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})
            what = f"{spot['tag']}{' “' + spot['text'] + '”' if spot.get('text') else ''}"
            if action == "type":
                await page.send("Input.insertText", {"text": str(input.get("text", ""))})
                if input.get("submit"):
                    await self._key(page, "Enter")
                await asyncio.sleep(0.5)
                return await self._shot(page, f"Typed into {what}" + (" and pressed Enter" if input.get("submit") else ""))
            await asyncio.sleep(0.6)
            return await self._shot(page, f"Clicked {what}")
        if action == "press":
            key = str_arg(input, "key")
            await self._key(page, key)
            await asyncio.sleep(0.4)
            return await self._shot(page, f"Pressed {key}")
        if action == "scroll":
            dy = -650 if str(input.get("direction", "down")).lower() == "up" else 650
            await page.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": VIEWPORT[0] / 2, "y": VIEWPORT[1] / 2, "deltaX": 0, "deltaY": dy})
            await asyncio.sleep(0.5)
            return await self._shot(page, f"Scrolled {'up' if dy < 0 else 'down'}")
        if action == "evaluate":
            value = await self._eval(page, str_arg(input, "script"))
            out = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str)
            return ToolResult(text=str(out)[:MAX_TEXT])
        # console
        lines, page.console = page.console[:], []
        return ToolResult(text="\n".join(lines) if lines else "No console messages since the last check.")

    @staticmethod
    async def _eval(page: CDP, expr: str):
        res = await page.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            raise ToolError(f"JavaScript error: {(d.get('exception') or {}).get('description') or d.get('text', '')}")
        return (res.get("result") or {}).get("value")

    async def _where(self, page: CDP) -> str:
        info = await self._eval(page, "({t: document.title, u: location.href})") or {}
        return f"{info.get('t') or '(untitled)'} — {info.get('u', '')}"

    @staticmethod
    async def _key(page: CDP, key: str) -> None:
        codes = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39, "Space": 32}
        params = {"key": key, "code": key, "windowsVirtualKeyCode": codes.get(key, 0)}
        if key == "Enter":
            params["text"] = "\r"
        await page.send("Input.dispatchKeyEvent", {"type": "keyDown", **params})
        await page.send("Input.dispatchKeyEvent", {"type": "keyUp", **params})

    async def _shot(self, page: CDP, summary: str) -> ToolResult:
        shot = await page.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70})
        uri = "data:image/jpeg;base64," + shot["data"]
        errors = [line for line in page.console if line.startswith(("[error]", "[exception]"))]
        note = f"\n\nConsole errors on this page:\n" + "\n".join(errors[-10:]) if errors else ""
        size = len(base64.b64decode(shot["data"])) // 1024
        return ToolResult(text=f"{summary}. Screenshot attached ({VIEWPORT[0]}×{VIEWPORT[1]}, {size} KB).{note}", images=[uri], metadata={"screenshot": True})
