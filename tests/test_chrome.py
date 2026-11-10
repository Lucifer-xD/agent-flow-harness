"""The `chrome` tool: the user's own browser. A fake browser stands in for Chrome's DevTools websocket."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import socket

import pytest
from PIL import Image

from afh import store as appstore
from afh.engine.tools import chrome as ch
from afh.engine.tools.files import ToolError
from afh.engine.tools.registry import builtin_tools
from afh.engine.types import PermissionDenied, ToolContext


def jpeg(w: int, h: int) -> str:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (30, 60, 90)).save(out, "JPEG")
    return base64.b64encode(out.getvalue()).decode()


class FakeChrome:
    """Answers the DevTools commands the tool sends, as a browser with tabs would."""

    def __init__(self, css=(1000, 600), dpr=1):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.css, self.dpr = css, dpr
        self.targets: dict[str, dict] = {}
        self.sessions: dict[str, str] = {}  # sessionId -> targetId
        self.n = 0
        self.on_click = None  # called with (fake, sessionId) when the mouse is released
        self.closed = False
        self.add("https://news.example.com/today", "Today's news")
        self.add("chrome://settings/", "Settings")

    # -- what the tests drive --

    def add(self, url: str, title: str = "", opener: str | None = None) -> str:
        self.n += 1
        tid = f"T{self.n}"
        info = {"targetId": tid, "type": "page", "title": title, "url": url, "attached": False}
        if opener:
            info["openerId"] = opener
        self.targets[tid] = info
        return tid

    def emit(self, method: str, params: dict, session: str | None = None) -> None:
        msg = {"method": method, "params": params}
        if session:
            msg["sessionId"] = session
        self.inbox.put_nowait(json.dumps(msg))

    def calls(self, method: str) -> list[dict]:
        return [m.get("params") or {} for m in self.sent if m.get("method") == method]

    def move(self, session: str, url: str, title: str = "") -> None:
        tid = self.sessions[session]
        self.targets[tid].update(url=url, title=title or url)
        self.emit("Target.targetInfoChanged", {"targetInfo": dict(self.targets[tid])})

    # -- the websocket the Link reads and writes --

    async def send(self, raw: str) -> None:
        msg = json.loads(raw)
        self.sent.append(msg)
        method, params, session = msg["method"], msg.get("params") or {}, msg.get("sessionId")
        result: dict = {}
        if method == "Target.setDiscoverTargets":
            for info in self.targets.values():
                self.emit("Target.targetCreated", {"targetInfo": dict(info)})
        elif method == "Browser.getVersion":
            result = {"product": "Chrome/157.0.0.0"}
        elif method == "Target.createTarget":
            tid = self.add(params.get("url", "about:blank"))
            self.emit("Target.targetCreated", {"targetInfo": dict(self.targets[tid])})
            result = {"targetId": tid}
        elif method == "Target.attachToTarget":
            sid = f"S{len(self.sessions) + 1}"
            self.sessions[sid] = params["targetId"]
            result = {"sessionId": sid}
        elif method == "Target.getTargets":
            result = {"targetInfos": [dict(i) for i in self.targets.values()]}
        elif method == "Target.closeTarget":
            self.targets.pop(params["targetId"], None)
            self.emit("Target.targetDestroyed", {"targetId": params["targetId"]})
        elif method == "Page.navigate":
            self.move(session, params["url"], "Page at " + params["url"])
            self.emit("Page.loadEventFired", {}, session)
        elif method == "Page.captureScreenshot":
            result = {"data": jpeg(self.css[0] * self.dpr, self.css[1] * self.dpr)}
        elif method == "Page.getLayoutMetrics":
            result = {"cssVisualViewport": {"clientWidth": self.css[0], "clientHeight": self.css[1]}}
        elif method == "Runtime.evaluate":
            expr = params.get("expression", "")
            info = self.targets.get(self.sessions.get(session, ""), {})
            if "document.title" in expr and "location.href" in expr:
                value = {"t": info.get("title"), "u": info.get("url")}
            elif "innerText" in expr and "querySelector" not in expr:
                value = "page text"
            elif "elementFromPoint" in expr:
                value = "button “Go”"
            elif "querySelector" in expr:
                value = {"x": 300, "y": 200, "tag": "button", "text": "Go"}
            else:
                value = None
            result = {"result": {"value": value}}
        elif method == "Input.dispatchMouseEvent" and params.get("type") == "mouseReleased" and self.on_click:
            self.on_click(self, session)
        self.inbox.put_nowait(json.dumps({"id": msg["id"], "result": result}))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        raw = await self.inbox.get()
        if raw is None:
            raise StopAsyncIteration
        return raw

    async def close(self) -> None:
        self.closed = True
        self.inbox.put_nowait(None)


class Gate:
    """Ask mode, with the user's answer scripted."""

    def __init__(self, answer="once", rules=None):
        self.answer = answer
        self.rules = rules if rules is not None else [{"action": "edit", "resource": "*", "effect": "ask"}]
        self.asked: list[dict] = []

    async def require(self, action, resources, metadata=None):
        pass

    async def ask_user(self, action, metadata):
        self.asked.append(metadata)
        return self.answer, None, None


class FakeEngine:
    def __init__(self):
        self.events: list[dict] = []

    def settings(self):
        return appstore.load_settings()

    def publish(self, ev):
        self.events.append(ev)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "afh-home"
    h.mkdir()
    monkeypatch.setattr(appstore, "AFH_DIR", h)
    monkeypatch.setattr(appstore, "SETTINGS_PATH", h / "settings.json")
    return h


@pytest.fixture
def chrome(home, monkeypatch):
    """A fresh manager wired to a fake browser that is "ready"."""
    fake = FakeChrome()
    manager = ch.ChromeManager()
    monkeypatch.setattr(ch, "CHROME", manager)
    monkeypatch.setattr(ch, "candidates", lambda settings=None: [
        {"id": "chrome", "name": "Chrome", "scheme": "chrome", "installed": True, "ready": True, "ws": "ws://fake"}])

    async def connect(url, name="Chrome", browser_id="chrome", timeout=0):
        link = ch.Link(fake, name, browser_id)
        await link.send("Target.setDiscoverTargets", {"discover": True})
        link.version = (await link.send("Browser.getVersion"))["product"]
        return link

    monkeypatch.setattr(ch.Link, "connect", staticmethod(connect))
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep(asyncio.sleep))
    return fake


def _fast_sleep(real):
    async def sleep(delay, *a):
        await real(0)
    return sleep


def ctx(gate=None, engine=None, sid="ses_1", emitted=None):
    return ToolContext(session_id=sid, message_id="msg", directory=".", permissions=gate or Gate(), snapshots=None,
                       emit=lambda t, d: emitted.append((t, d)) if emitted is not None else None, settings={}, engine=engine or FakeEngine())


def run(coro):
    return asyncio.run(coro)


# ---- finding the browser ---------------------------------------------------------------


def test_a_port_file_only_counts_while_something_listens(tmp_path, monkeypatch):
    folder = tmp_path / "User Data"
    folder.mkdir()
    monkeypatch.setattr(ch, "browsers", lambda: [{"id": "chrome", "name": "Chrome", "scheme": "chrome", "dir": folder}])
    assert ch.candidates()[0] == {"id": "chrome", "name": "Chrome", "scheme": "chrome", "installed": True, "ready": False, "ws": ""}
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    (folder / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/abc-123")  # Chrome writes no trailing newline
    assert ch.candidates()[0]["ready"] is False  # bound but not listening: a stale file
    server.listen(1)
    try:
        found = ch.candidates()[0]
        assert found["ready"] and found["ws"] == f"ws://127.0.0.1:{port}/devtools/browser/abc-123"
        assert ch.candidates({"chrome": {"browser": "edge"}}) == []  # the user picked another browser
    finally:
        server.close()
    assert ch.candidates()[0]["ready"] is False


def test_a_bad_port_file_is_ignored(tmp_path):
    for text in ("", "abc\n/devtools/browser/x", "9222", "9222\n/json/version", "0\n/devtools/browser/x"):
        (tmp_path / "DevToolsActivePort").write_text(text)
        assert ch.read_port(tmp_path) is None


def test_the_setup_steps_name_the_users_browser():
    edge = [{"id": "edge", "name": "Edge", "scheme": "edge", "installed": True, "ready": False, "ws": ""}]
    text = ch.setup_help(edge)
    assert "edge://inspect/#remote-debugging" in text and "Allow remote debugging for this browser instance" in text
    assert "`browser` tool" in ch.setup_help([{"id": "chrome", "name": "Chrome", "scheme": "chrome", "installed": False, "ready": False, "ws": ""}])


def test_no_ready_browser_explains_the_one_time_setup(home, monkeypatch):
    manager = ch.ChromeManager()
    monkeypatch.setattr(ch, "CHROME", manager)
    monkeypatch.setattr(ch, "candidates", lambda settings=None: [
        {"id": "chrome", "name": "Chrome", "scheme": "chrome", "installed": True, "ready": False, "ws": ""}])
    res = run(ch.ChromeTool().run(ctx(), {"action": "tabs"}))
    assert res.is_error and "chrome://inspect/#remote-debugging" in res.text


def test_a_refused_or_unanswered_prompt_is_explained(monkeypatch):
    import websockets

    class Refused(Exception):
        response = type("R", (), {"status_code": 403})()

    async def refused(url, **kw):
        raise Refused()

    async def never(url, **kw):
        await asyncio.Event().wait()

    monkeypatch.setattr(websockets, "connect", refused)
    with pytest.raises(ToolError, match="clicked Cancel"):
        run(ch.Link.connect("ws://x", "Chrome"))
    monkeypatch.setattr(websockets, "connect", never)
    with pytest.raises(ToolError, match="click Allow"):
        run(ch.Link.connect("ws://x", "Chrome", timeout=0.05))


# ---- sites ------------------------------------------------------------------------------


def test_site_rules():
    assert ch.site_of("https://www.GitHub.com/a/b?c") == "github.com"
    assert ch.site_of("file:///C:/x.html") == "local files"
    assert ch.site_of("about:blank") == "" and ch.site_of("chrome://newtab/") == ""
    assert ch.allows(["github.com"], "github.com") and ch.allows(["https://www.github.com/login"], "github.com")
    assert not ch.allows(["google.com"], "mail.google.com")  # allowing a site doesn't allow its subdomains
    assert ch.allows(["*.google.com"], "mail.google.com") and ch.allows(["*.google.com"], "google.com")
    assert ch.blocks(["mybank.com"], "online.mybank.com") and ch.blocks(["*.mybank.com"], "mybank.com")
    assert not ch.blocks(["bank.com"], "mybank.com")


def test_each_new_site_asks_once(chrome):
    async def go():
        gate, tool = Gate("once"), ch.ChromeTool()
        emitted = []
        res = await tool.run(ctx(gate, emitted=emitted), {"action": "open", "url": "github.com/pulls"})
        assert not res.is_error and res.images and "Opened" in res.text
        assert [m["site"] for m in gate.asked] == ["github.com"]
        assert gate.asked[0]["kind"] == "chrome" and gate.asked[0]["title"] == "Let AFH use github.com in your Chrome?"
        assert any(t == "session.notice" and "click Allow in Chrome" in d["label"] for t, d in emitted)  # Chrome's own prompt is up
        await tool.run(ctx(gate), {"action": "text"})
        await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/issues"})
        assert len(gate.asked) == 1
        await tool.run(ctx(gate), {"action": "open", "url": "https://gitlab.com/"})
        assert [m["site"] for m in gate.asked] == ["github.com", "gitlab.com"]
        assert chrome.calls("Target.createTarget") == [{"url": "about:blank", "background": False}]  # one tab for the thread

    run(go())


def test_always_allow_is_remembered_in_settings(chrome):
    async def go():
        engine, tool = FakeEngine(), ch.ChromeTool()
        await tool.run(ctx(Gate("always"), engine), {"action": "open", "url": "https://github.com/"})
        assert appstore.load_settings()["chrome"]["allowed"] == ["github.com"]
        assert {"type": "chrome.sites.changed", "data": {}} in engine.events
        other = Gate("reject")
        res = await tool.run(ctx(other, engine, sid="ses_2"), {"action": "open", "url": "https://github.com/x"})
        assert not res.is_error and other.asked == []  # another thread: no question
        ch.forget_site(engine, "github.com")
        assert appstore.load_settings()["chrome"]["allowed"] == []

    run(go())


def test_a_site_the_user_refuses_is_not_opened(chrome):
    async def go():
        with pytest.raises(PermissionDenied, match="example.org"):
            await ch.ChromeTool()._run(ctx(Gate("reject")), {"action": "open", "url": "https://example.org/"})
        assert chrome.calls("Page.navigate") == []

    run(go())


def test_a_blocked_site_is_never_used_even_with_full_access(chrome):
    async def go():
        appstore.save_settings({"chrome": {"blocked": ["mybank.com"]}})
        full = Gate("once", rules=[{"action": "*", "resource": "*", "effect": "allow"}])
        res = await ch.ChromeTool().run(ctx(full), {"action": "open", "url": "https://online.mybank.com/"})
        assert res.is_error and "blocked list" in res.text and full.asked == []
        ok = await ch.ChromeTool().run(ctx(full), {"action": "open", "url": "https://github.com/"})
        assert not ok.is_error and full.asked == []  # full access: other sites don't ask

    run(go())


def test_moving_to_another_site_asks_before_anything_goes_to_the_model(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/"})
        chrome.on_click = lambda fake, session: fake.move(session, "https://accounts.example.net/login", "Sign in")
        gate.answer = "reject"
        with pytest.raises(PermissionDenied, match="accounts.example.net"):
            await tool._run(ctx(gate), {"action": "click", "target": "Sign in"})
        assert [m["site"] for m in gate.asked] == ["github.com", "accounts.example.net"]
        assert chrome.calls("Page.navigate")[-1] == {"url": "https://github.com/"}  # and AFH went back to where it was
        assert ch.CHROME.tabs["ses_1"].url == "https://github.com/"

    run(go())


def test_a_refused_new_tab_is_closed_and_a_refused_tab_of_the_users_is_let_go(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/"})
        first = ch.CHROME.tabs["ses_1"].target_id

        def popup(fake, session):
            tid = fake.add("https://ads.example.net/offer", "Offer", opener=first)
            fake.emit("Target.targetCreated", {"targetInfo": dict(fake.targets[tid])})

        chrome.on_click = popup
        gate.answer = "reject"
        with pytest.raises(PermissionDenied, match="left that page"):
            await tool._run(ctx(gate), {"action": "click", "target": "Offer"})
        assert ch.CHROME.tabs["ses_1"].target_id == first and len(chrome.calls("Target.closeTarget")) == 1
        chrome.on_click = None
        with pytest.raises(PermissionDenied):
            await tool._run(ctx(gate, sid="ses_2"), {"action": "switch_tab", "tab": "news"})
        assert "ses_2" not in ch.CHROME.tabs and "T1" in chrome.targets and len(chrome.calls("Target.closeTarget")) == 1

    run(go())


# ---- acting in the tab ------------------------------------------------------------------


def test_screenshots_are_sized_to_the_page_and_clicks_map_back(chrome):
    async def go():
        chrome.css, chrome.dpr = (3136, 1200), 2  # a very large HiDPI window
        tool, gate = ch.ChromeTool(), Gate("once")
        res = await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/"})
        img = Image.open(io.BytesIO(base64.b64decode(res.images[0].split(",", 1)[1])))
        assert img.size == (1568, 600) and "1568×600" in res.text
        await tool.run(ctx(gate), {"action": "click", "x": 100, "y": 50})
        pressed = [p for p in chrome.calls("Input.dispatchMouseEvent") if p["type"] == "mousePressed"]
        assert (pressed[-1]["x"], pressed[-1]["y"]) == (200, 100)  # image pixels back to page pixels

    run(go())


def test_fit_shot_keeps_a_normal_window_as_is():
    data, w, h, scale = ch.fit_shot(jpeg(1280, 720), 1280, 720)
    assert (w, h, scale) == (1280, 720, 1.0)
    data, w, h, scale = ch.fit_shot(jpeg(2560, 1440), 1280, 720)  # 2x screen
    assert (w, h, scale) == (1280, 720, 1.0) and Image.open(io.BytesIO(base64.b64decode(data))).size == (1280, 720)


def test_dialogs_are_answered_so_the_page_never_hangs(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/"})
        chrome.on_click = lambda fake, session: fake.emit("Page.javascriptDialogOpening", {"type": "confirm", "message": "Delete the repo?"}, session)
        res = await tool.run(ctx(gate), {"action": "click", "target": "Delete"})
        assert "confirm dialog “Delete the repo?” was dismissed" in res.text
        res = await tool.run(ctx(gate), {"action": "click", "target": "Delete", "accept_dialogs": True})
        assert "was accepted" in res.text
        chrome.on_click = lambda fake, session: fake.emit("Page.javascriptDialogOpening", {"type": "alert", "message": "Saved"}, session)
        res = await tool.run(ctx(gate), {"action": "click", "target": "Save"})
        assert "alert dialog “Saved” was accepted" in res.text
        assert [p["accept"] for p in chrome.calls("Page.handleJavaScriptDialog")] == [False, True, True]

    run(go())


def test_a_link_that_opens_a_new_tab_moves_the_thread_there(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/"})
        first = ch.CHROME.tabs["ses_1"].target_id

        def popup(fake, session):
            tid = fake.add("https://github.com/docs", "Docs", opener=first)
            fake.emit("Target.targetCreated", {"targetInfo": dict(fake.targets[tid])})

        chrome.on_click = popup
        res = await tool.run(ctx(gate), {"action": "click", "target": "Docs"})
        assert "opened a new tab (Docs — https://github.com/docs)" in res.text
        now = ch.CHROME.tabs["ses_1"]
        assert now.target_id != first and now.url == "https://github.com/docs" and now.owned
        assert first in chrome.targets  # the first tab is left open

    run(go())


# ---- the user's own tabs ----------------------------------------------------------------


def test_tabs_lists_web_pages_only_and_switch_tab_asks_about_the_site(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        listing = await tool.run(ctx(gate), {"action": "tabs"})
        assert "1. Today's news — https://news.example.com/today" in listing.text and "chrome://settings" not in listing.text
        assert gate.asked == []  # listing titles asks nothing
        res = await tool.run(ctx(gate), {"action": "switch_tab", "tab": "1"})
        assert "Now working in the user's tab: Today's news" in res.text and res.images
        assert [m["site"] for m in gate.asked] == ["news.example.com"]
        assert chrome.calls("Target.activateTarget") == [{"targetId": "T1"}]
        assert chrome.calls("Target.createTarget") == []  # no tab of AFH's own was opened
        by_name = await tool.run(ctx(gate, sid="ses_2"), {"action": "switch_tab", "tab": "news"})
        assert not by_name.is_error
        missing = await tool.run(ctx(gate), {"action": "switch_tab", "tab": "nothing like this"})
        assert missing.is_error and "No open tab" in missing.text

    run(go())


def test_close_never_closes_a_tab_of_the_users(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        await tool.run(ctx(gate), {"action": "switch_tab", "tab": "1"})
        res = await tool.run(ctx(gate), {"action": "close"})
        assert "stays open" in res.text and chrome.calls("Target.closeTarget") == [] and "T1" in chrome.targets
        await tool.run(ctx(gate), {"action": "open", "url": "https://news.example.com/x"})
        mine = ch.CHROME.tabs["ses_1"].target_id
        res = await tool.run(ctx(gate), {"action": "close"})
        assert "Closed the tab AFH opened" in res.text and chrome.calls("Target.closeTarget") == [{"targetId": mine}]

    run(go())


def test_disconnecting_leaves_the_browser_and_its_tabs_alone(chrome):
    async def go():
        tool = ch.ChromeTool()
        await tool.run(ctx(Gate("once")), {"action": "open", "url": "https://github.com/"})
        await ch.CHROME.shutdown()
        assert chrome.closed and not ch.CHROME.connected
        assert not {m["method"] for m in chrome.sent} & {"Browser.close", "Target.closeTarget"}

    run(go())


def test_a_closed_tab_is_replaced_on_the_next_action(chrome):
    async def go():
        tool, gate = ch.ChromeTool(), Gate("once")
        await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/"})
        first = ch.CHROME.tabs["ses_1"].target_id
        chrome.targets.pop(first)
        chrome.emit("Target.targetDestroyed", {"targetId": first})  # the user closed AFH's tab
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        res = await tool.run(ctx(gate), {"action": "open", "url": "https://github.com/a"})
        assert not res.is_error and ch.CHROME.tabs["ses_1"].target_id != first

    run(go())


# ---- wiring -----------------------------------------------------------------------------


def test_the_tool_is_offered_unless_turned_off():
    assert "chrome" in [t.spec.name for t in builtin_tools({})]
    assert "chrome" not in [t.spec.name for t in builtin_tools({"chrome": {"enabled": False}})]
    spec = ch.ChromeTool.spec
    assert set(spec.parameters["properties"]["action"]["enum"]) >= {"tabs", "switch_tab", "open", "click", "close"}


def test_the_prompt_tells_the_agent_how_to_behave_in_the_users_browser():
    from afh.engine.prompt import harness_guide

    guide = harness_guide(["browser", "chrome"])
    assert "`chrome` tool" in guide and "data" in guide and "passwords" in guide and "For your own checks and public pages use `browser`" in guide
    assert "`chrome` tool" not in harness_guide(["browser"])


def test_status_for_settings(home, monkeypatch):
    monkeypatch.setattr(ch, "CHROME", ch.ChromeManager())
    monkeypatch.setattr(ch, "candidates", lambda settings=None: [
        {"id": "chrome", "name": "Chrome", "scheme": "chrome", "installed": True, "ready": False, "ws": ""},
        {"id": "edge", "name": "Edge", "scheme": "edge", "installed": False, "ready": False, "ws": ""}])
    appstore.save_settings({"chrome": {"allowed": ["GitHub.com", "https://www.example.org/x"], "blocked": ["mybank.com"]}})
    s = ch.status(appstore.load_settings())
    assert s["enabled"] and not s["connected"] and s["setupPage"] == "chrome://inspect/#remote-debugging"
    assert s["allowed"] == ["github.com", "example.org"] and s["blocked"] == ["mybank.com"]
    assert [b["id"] for b in s["browsers"]] == ["chrome", "edge"] and "ws" not in s["browsers"][0]
