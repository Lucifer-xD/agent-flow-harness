"""The AFH browser extension's link: the native messaging helper Chrome starts, the socket it reaches AFH
on, the chrome tool driving tabs through it, and the setup AFH writes for the browsers."""

from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from afh import nativehost, store
from afh.engine.tools import chrome as chrome_mod
from afh.engine.tools import extension
from afh.engine.tools.chrome import CHROME, EXTENSION, ChromeTool, ExtensionHost

from tests.test_tools import FakeGate, FakeSnapshots
from afh.engine.types import ToolContext


# ---- the helper's framing --------------------------------------------------------------------


def test_frames_round_trip_and_the_launch_is_recognised():
    out, lock = io.BytesIO(), threading.Lock()
    nativehost.write_frame(out, {"id": 1, "method": "Page.navigate", "params": {"url": "https://example.test/ü"}}, lock)
    out.seek(0)
    assert nativehost.read_frame(out) == {"id": 1, "method": "Page.navigate", "params": {"url": "https://example.test/ü"}}
    assert nativehost.read_frame(io.BytesIO(b"\x01")) is None  # Chrome closed the pipe
    assert nativehost.is_native_launch(["afh-backend.exe", "chrome-extension://abc/", "--parent-window=0"])
    assert not nativehost.is_native_launch(["afh-backend.exe", "--headless"])


def test_find_afh_reads_the_discovery_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AFH_HOME", str(tmp_path))
    assert nativehost.find_afh() is None
    (tmp_path / "api.json").write_text(json.dumps({"url": "http://127.0.0.1:4567", "key": "afh_k"}), encoding="utf-8")
    assert nativehost.find_afh() == ("ws://127.0.0.1:4567/api/extension/host", "afh_k")
    (tmp_path / "api.json").write_text(json.dumps({"url": "http://evil.test:1", "key": "afh_k"}), encoding="utf-8")
    assert nativehost.find_afh() is None  # only this computer


def test_the_helper_relays_both_ways_and_says_when_afh_is_there():
    """Chrome's pipe ↔ a websocket server standing in for AFH."""
    import websockets

    async def go():
        got, tokens = [], []

        async def afh(ws):
            tokens.append(ws.request.headers.get("x-afh-token"))
            got.append(json.loads(await ws.recv()))  # the extension's hello, replayed on connect
            await ws.send(json.dumps({"id": 1, "method": "Browser.getVersion"}))
            got.append(json.loads(await ws.recv()))  # the extension's answer
            await ws.close()

        server = await websockets.serve(afh, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        r_in, w_in = os.pipe()
        r_out, w_out = os.pipe()
        stdin, chrome_in = os.fdopen(r_in, "rb", buffering=0), os.fdopen(w_in, "wb", buffering=0)
        stdout, chrome_out = os.fdopen(w_out, "wb", buffering=0), os.fdopen(r_out, "rb", buffering=0)
        relay = nativehost.Relay(stdin, stdout)
        lock = threading.Lock()
        nativehost.write_frame(chrome_in, {"hello": {"browser": "Chrome", "extension": "1.0.0"}}, lock)
        task = asyncio.create_task(relay.run(lambda: (f"ws://127.0.0.1:{port}/api/extension/host", "afh_key")))
        seen = []
        loop = asyncio.get_running_loop()
        while len(seen) < 3:
            seen.append(await loop.run_in_executor(None, nativehost.read_frame, chrome_out))
            if seen[-1].get("id") == 1:
                nativehost.write_frame(chrome_in, {"id": 1, "result": {"product": "Chrome/140"}}, lock)
        assert seen[0] == {"afh": "connected"} and seen[1]["method"] == "Browser.getVersion"
        assert seen[2] == {"afh": "waiting"}  # AFH closed: the helper waits for it again
        assert tokens == ["afh_key"] and got[0]["hello"]["browser"] == "Chrome" and got[1]["result"]["product"] == "Chrome/140"
        chrome_in.close()  # Chrome closes the pipe: the helper ends
        await asyncio.wait_for(task, 10)
        server.close()

    asyncio.run(go())


# ---- AFH's end ---------------------------------------------------------------------------------


def test_the_extension_socket_needs_a_local_key(monkeypatch):
    from afh import api as apimod
    from afh import devapi

    monkeypatch.setitem(apimod.ACCESS, "token", "t")
    monkeypatch.setitem(apimod.ACCESS, "hosts", set())
    client = TestClient(apimod.app)
    with pytest.raises(WebSocketDisconnect) as err:
        with client.websocket_connect("/api/extension/host", headers={"x-afh-token": "afh_wrong"}) as ws:
            ws.receive_text()
    assert err.value.code == 4401
    with client.websocket_connect("/api/extension/host", headers={"x-afh-token": devapi.LOCAL_KEY}) as ws:
        ws.send_text(json.dumps({"hello": {"browser": "Edge", "extension": "1.0.0"}}))
        first = json.loads(ws.receive_text())
        assert first["method"] == "Target.setDiscoverTargets"


class FakeExtension:
    """A socket whose other end answers like background.js: tabs as targets, CDP into attached tabs."""

    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.tabs = {"5": {"title": "Mail", "url": "https://mail.example.test/"}}
        self.next = 6
        self.attached: set[str] = set()

    async def accept(self):
        self.inbox.put_nowait(json.dumps({"hello": {"browser": "Brave", "version": "140", "extension": "1.0.0"}}))

    async def receive_text(self):
        msg = await self.inbox.get()
        if msg is None:
            raise WebSocketDisconnect(1000)
        return msg

    async def send_text(self, text):
        msg = json.loads(text)
        self.sent.append(msg)
        if "id" in msg:
            self.inbox.put_nowait(json.dumps({"id": msg["id"], "result": self.answer(msg)}))
            if msg["method"] == "Page.navigate":
                tid = msg["sessionId"][1:]
                self.tabs[tid]["url"] = msg["params"]["url"]
                self.inbox.put_nowait(json.dumps({"method": "Target.targetInfoChanged", "params": {"targetInfo": {"targetId": tid, "type": "page", **self.tabs[tid]}}}))
                self.inbox.put_nowait(json.dumps({"method": "Page.loadEventFired", "params": {}, "sessionId": msg["sessionId"]}))

    async def close(self):
        self.inbox.put_nowait(None)

    def answer(self, msg):
        m, p = msg["method"], msg.get("params") or {}
        if m == "Browser.getVersion":
            return {"product": "Brave/140"}
        if m == "Target.getTargets":
            return {"targetInfos": [{"targetId": k, "type": "page", **v} for k, v in self.tabs.items()]}
        if m == "Target.createTarget":
            tid = str(self.next)
            self.next += 1
            self.tabs[tid] = {"title": "", "url": "about:blank"}
            self.inbox.put_nowait(json.dumps({"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": tid, "type": "page", **self.tabs[tid]}}}))
            return {"targetId": tid}
        if m == "Target.attachToTarget":
            self.attached.add(p["targetId"])
            return {"sessionId": "t" + p["targetId"]}
        if m == "Runtime.evaluate":
            tab = self.tabs[msg["sessionId"][1:]]
            expr = p["expression"]
            if "document.title" in expr:
                return {"result": {"value": {"t": tab["title"], "u": tab["url"]}}}
            if expr == "location.href":
                return {"result": {"value": tab["url"]}}
            return {"result": {"value": "hello from the page"}}
        if m == "Page.captureScreenshot":
            return {"data": _JPEG}
        if m == "Page.getLayoutMetrics":
            return {"cssVisualViewport": {"clientWidth": 64, "clientHeight": 48}}
        return {}


def _jpeg() -> str:
    import base64

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


_JPEG = _jpeg()


@pytest.fixture
def fresh(monkeypatch):
    host = ExtensionHost()
    monkeypatch.setattr(chrome_mod, "EXTENSION", host)
    monkeypatch.setattr(chrome_mod, "candidates", lambda settings=None: [])  # no remote-debugging browser here
    CHROME.link = None
    CHROME.tabs.clear()
    CHROME.once.clear()
    yield host
    CHROME.link = None
    CHROME.tabs.clear()


def _ctx() -> ToolContext:
    return ToolContext(session_id="ext-thread", message_id="m", directory=".", permissions=FakeGate(), snapshots=FakeSnapshots(),
                       emit=lambda *_: None, settings={})


def test_the_chrome_tool_works_through_the_extension_with_no_debugging_switch(fresh):
    async def go():
        fake = FakeExtension()
        serving = asyncio.create_task(fresh.serve(fake))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if fresh.connected and fresh.link.version:
                break
        assert fresh.connected and fresh.link.name == "Brave" and fresh.link.via == "extension"
        tool = ChromeTool()
        res = await tool.run(_ctx(), {"action": "tabs"})
        assert "Mail — https://mail.example.test/" in res.text and "Brave" in res.text
        res = await tool.run(_ctx(), {"action": "open", "url": "https://shop.example.test/"})
        assert not res.is_error and res.images, res.text
        assert any(m.get("method") == "Page.navigate" and m.get("sessionId") == "t6" for m in fake.sent)
        res = await tool.run(_ctx(), {"action": "evaluate", "script": "1+1"})
        assert res.text == "hello from the page"
        st = chrome_mod.status({})
        assert st["connected"] and st["via"] == "extension" and st["extension"]["connected"] and st["extension"]["browser"] == "Brave"
        # AFH's "disconnect" only lets go of the tabs: the extension stays connected
        await CHROME.shutdown()
        assert fresh.connected
        await fake.close()
        await asyncio.wait_for(serving, 5)
        assert not fresh.connected

    asyncio.run(go())


def test_without_the_extension_the_tool_says_how_to_add_it(fresh, monkeypatch):
    monkeypatch.setattr(chrome_mod, "candidates", lambda settings=None: [{"id": "chrome", "name": "Chrome", "scheme": "chrome", "installed": True,
                                                                         "ready": False, "ws": ""}])
    res = asyncio.run(ChromeTool().run(_ctx(), {"action": "tabs"}))
    assert res.is_error and "AFH extension" in res.text and "Add the AFH extension" in res.text


# ---- the setup AFH writes ---------------------------------------------------------------------


def test_the_host_manifest_names_only_the_afh_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AFH_DIR", tmp_path)
    m = extension.host_manifest()
    assert m["name"] == "com.agentflowharness.bridge" and m["type"] == "stdio"
    assert m["allowed_origins"] == [f"chrome-extension://{extension.EXTENSION_ID}/"]
    assert os.path.isfile(m["path"])  # from source: a small script that runs run.py


def test_the_extension_id_matches_its_key():
    import base64
    import hashlib

    manifest = json.loads((extension.source_folder() / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(c, 16)) for c in digest) == extension.EXTENSION_ID
    assert {"debugger", "nativeMessaging", "tabs"} <= set(manifest["permissions"])


def test_the_extension_is_copied_where_the_user_loads_it_from(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AFH_DIR", tmp_path)
    dest = extension.copy_extension()
    assert dest == tmp_path / "browser-extension" and (dest / "background.js").is_file()
    (dest / "background.js").write_text("old", encoding="utf-8")
    extension.copy_extension()  # a changed file is put back
    assert (dest / "background.js").read_text(encoding="utf-8") != "old"


def test_frames_have_a_little_endian_length():
    out = io.BytesIO()
    nativehost.write_frame(out, {"a": 1}, threading.Lock())
    assert struct.unpack("<I", out.getvalue()[:4])[0] == len(b'{"a":1}')
