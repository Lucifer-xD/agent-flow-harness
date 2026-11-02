"""The built-in browser panel: the backend half (PanelHost) and the browser tool driving it. The page side
(web/js/browser.js + desktop/browser-main.js) is played by a fake socket that answers like the panel would."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from afh.engine.tools.browser import PANEL, BrowserTool, PanelHost, use_panel
from afh.engine.types import ToolContext

from tests.test_tools import FakeGate, FakeSnapshots


class FakePanel:
    """A socket whose other end acts like the AFH window's browser panel."""

    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = False

    async def accept(self):
        pass

    async def close(self):
        self.closed = True

    async def receive_json(self):
        msg = await self.inbox.get()
        if msg is None:
            raise WebSocketDisconnect(1000)
        return msg

    async def send_json(self, msg):
        self.sent.append(msg)
        if "id" in msg:
            self.inbox.put_nowait({"id": msg["id"], "result": self.answer(msg)})
            if msg.get("method") == "Page.navigate":
                self.inbox.put_nowait({"event": {"tab": "7", "method": "Page.loadEventFired", "params": {}}})

    def answer(self, msg):
        if msg["op"] == "open":
            return {"tab": "7"}
        if msg["op"] == "shot":
            return {"data": "AAAA", "width": 800, "height": 600}
        if msg["op"] == "cdp" and msg["method"] == "Runtime.evaluate":
            expr = msg["params"]["expression"]
            if "elementFromPoint" in expr:
                value = "button “Save”"
            elif "innerWidth" in expr:
                value = [800, 600]
            elif "document.title" in expr:
                value = {"t": "Shop", "u": "https://shop.test/"}
            else:
                value = 42
            return {"result": {"value": value}}
        return {}

    def cdp(self, method):
        return [m["params"] for m in self.sent if m.get("op") == "cdp" and m["method"] == method]


@pytest.fixture
def panel():
    PANEL.ws = None
    PANEL.tabs.clear()
    PANEL.paused.clear()
    yield PANEL
    PANEL.ws = None
    PANEL.tabs.clear()
    PANEL.paused.clear()


def ctx(settings=None) -> ToolContext:
    return ToolContext(session_id="ses_b", message_id="msg", directory=".", permissions=FakeGate(),
                       snapshots=FakeSnapshots(), emit=lambda *_: None, settings=settings or {})


async def connected(fake: FakePanel):
    task = asyncio.create_task(PANEL.serve(fake))
    await asyncio.sleep(0)
    return task


def test_panel_is_used_only_while_connected_and_not_set_to_external(panel):
    assert not use_panel({})

    async def go():
        fake = FakePanel()
        task = await connected(fake)
        assert use_panel({}) and use_panel({"browser": {"where": "panel"}})
        assert not use_panel({"browser": {"where": "external"}})
        fake.inbox.put_nowait(None)  # the window closed
        await task
        assert not use_panel({})

    asyncio.run(go())


def test_click_at_a_point_drives_the_panel_tab_and_shows_it(panel):
    async def go():
        fake = FakePanel()
        task = await connected(fake)
        res = await BrowserTool().run(ctx(), {"action": "click", "x": 100, "y": 50})
        assert not res.is_error, res.text
        assert "Clicked button “Save” at (100, 50)" in res.text and "800×600" in res.text
        assert res.images == ["data:image/jpeg;base64,AAAA"]
        presses = [p for p in fake.cdp("Input.dispatchMouseEvent") if p["type"] in ("mousePressed", "mouseReleased")]
        assert [(p["type"], p["x"], p["y"], p["clickCount"]) for p in presses] == [("mousePressed", 100, 50, 1), ("mouseReleased", 100, 50, 1)]
        opened = [m for m in fake.sent if m.get("op") == "open"]
        assert opened == [{"id": opened[0]["id"], "op": "open", "sid": "ses_b"}]
        activity = [m for m in fake.sent if m.get("op") == "activity"]
        assert activity and activity[0]["what"].startswith("Clicking button") and activity[0]["x"] == 100
        # the tab is kept for the thread: a second call doesn't open another
        await BrowserTool().run(ctx(), {"action": "double_click", "x": 10, "y": 20})
        assert len([m for m in fake.sent if m.get("op") == "open"]) == 1
        assert [p["clickCount"] for p in fake.cdp("Input.dispatchMouseEvent") if p["type"] == "mousePressed"][-2:] == [1, 2]
        fake.inbox.put_nowait(None)
        await task

    asyncio.run(go())


def test_open_type_scroll_drag_and_keys(panel):
    async def go():
        fake = FakePanel()
        task = await connected(fake)
        tool = BrowserTool()
        res = await tool.run(ctx(), {"action": "open", "url": "shop.test"})
        assert "Opened Shop — https://shop.test/" in res.text
        assert fake.cdp("Page.navigate")[0]["url"] == "http://shop.test"
        res = await tool.run(ctx(), {"action": "type", "text": "hello", "submit": True})
        assert "into the focused field and pressed Enter" in res.text
        assert fake.cdp("Input.insertText")[-1] == {"text": "hello"}
        await tool.run(ctx(), {"action": "scroll", "direction": "right", "amount": 300})
        wheel = fake.cdp("Input.dispatchMouseEvent")[-1]
        assert (wheel["type"], wheel["deltaX"], wheel["deltaY"], wheel["x"], wheel["y"]) == ("mouseWheel", 300, 0, 400, 300)
        await tool.run(ctx(), {"action": "drag", "x": 10, "y": 10, "to_x": 90, "to_y": 50})
        moves = fake.cdp("Input.dispatchMouseEvent")
        assert moves[-1] == {"type": "mouseReleased", "x": 90.0, "y": 50.0, "button": "left", "clickCount": 1, "buttons": 0}
        assert any(m["type"] == "mouseMoved" and m.get("buttons") == 1 for m in moves)
        await tool.run(ctx(), {"action": "press", "key": "Ctrl+A"})
        down = fake.cdp("Input.dispatchKeyEvent")[-2]
        assert down["type"] == "rawKeyDown" and down["modifiers"] == 2 and down["commands"] == ["selectAll"]
        fake.inbox.put_nowait(None)
        await task

    asyncio.run(go())


def test_taking_over_the_tab_stops_the_agent_until_handed_back(panel):
    async def go():
        fake = FakePanel()
        task = await connected(fake)
        tool = BrowserTool()
        await tool.run(ctx(), {"action": "screenshot"})
        fake.inbox.put_nowait({"op": "takeover", "sid": "ses_b"})
        await asyncio.sleep(0.01)
        sent = len(fake.sent)
        res = await tool.run(ctx(), {"action": "click", "x": 1, "y": 1})
        assert res.is_error and "taken over" in res.text
        assert len(fake.sent) == sent  # nothing reached the tab
        fake.inbox.put_nowait({"op": "handback", "sid": "ses_b"})
        await asyncio.sleep(0.01)
        assert not (await tool.run(ctx(), {"action": "click", "x": 1, "y": 1})).is_error
        # closing the agent's tab in the panel forgets it; the next call opens a new one
        fake.inbox.put_nowait({"op": "closed", "tab": "7"})
        await asyncio.sleep(0.01)
        assert "ses_b" not in PANEL.tabs
        fake.inbox.put_nowait(None)
        await task

    asyncio.run(go())


def test_a_newer_window_replaces_the_old_and_pending_calls_fail(panel):
    async def go():
        host = PanelHost()
        silent = FakePanel()
        silent.send_json = lambda msg: asyncio.sleep(0, silent.sent.append(msg))  # never answers
        first = asyncio.create_task(host.serve(silent))
        await asyncio.sleep(0)
        call = asyncio.create_task(host.request("shot", 5, tab="1"))
        await asyncio.sleep(0.01)
        second = FakePanel()
        task = asyncio.create_task(host.serve(second))
        await asyncio.sleep(0.01)
        with pytest.raises(Exception, match="browser panel closed"):
            await call
        assert silent.closed and host.ws is second
        silent.inbox.put_nowait(None)
        await first
        assert host.ws is second  # the old socket ending doesn't disconnect the new one
        second.inbox.put_nowait(None)
        await task
        assert host.ws is None

    asyncio.run(go())


def test_the_host_socket_needs_the_windows_own_token(panel, monkeypatch):
    from afh import api as apimod

    monkeypatch.setitem(apimod.ACCESS, "token", "t")
    monkeypatch.setitem(apimod.ACCESS, "hosts", set())
    client = TestClient(apimod.app)
    with pytest.raises(WebSocketDisconnect) as err:
        with client.websocket_connect("/api/browser/host?token=nope") as ws:
            ws.receive_json()
    assert err.value.code == 4401
    with client.websocket_connect("/api/browser/host?token=t") as ws:
        ws.send_json({"op": "handback", "sid": "x"})
