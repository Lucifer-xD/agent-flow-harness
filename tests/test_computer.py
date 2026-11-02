"""Computer-use engine: app resolution, tiers, key combos, screenshot scaling, approvals and
the tool's gating. UI (the overlay, the cards) is exercised by node --check in test_web.py."""
from __future__ import annotations

import sys

import pytest

from afh.engine.computer import apps as appsmod

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="computer use is Windows-only")


def test_tiers_browsers_are_view_only_editors_click_only_rest_full():
    assert appsmod.tier_for("chrome.exe") == "read"
    assert appsmod.tier_for("msedge.exe") == "read"
    assert appsmod.tier_for("chrome.exe", {"computer": {"browserControl": True}}) == "full"
    assert appsmod.tier_for("code.exe") == "click"
    assert appsmod.tier_for("windowsterminal.exe") == "click"
    assert appsmod.tier_for("notepad.exe") == "full"
    assert appsmod.tier_for("spotify.exe") == "full"


def test_afh_and_password_managers_are_never_controllable():
    assert appsmod.never("agent flow harness.exe")
    assert appsmod.never("afh-backend.exe")
    assert appsmod.never("1password.exe")
    assert appsmod.never("electron.exe", r"C:\Users\x\Desktop\AFH\desktop\node_modules\electron\dist\electron.exe")
    assert not appsmod.never("notepad.exe")
    assert not appsmod.never("electron.exe", r"C:\Apps\SomeOtherApp\electron.exe")


def test_key_combos_parse_to_virtual_keys():
    from afh.engine.computer import win

    assert win.parse_combo("ctrl+s") == [0x11, 0x53]
    assert win.parse_combo("alt+Tab") == [0x12, 0x09]
    assert win.parse_combo("Enter") == [0x0D]
    assert win.parse_combo("win+r") == [0x5B, 0x52]
    assert win.parse_combo("cmd+c") == [0x11, 0x43]  # Mac habit maps to Ctrl on Windows
    with pytest.raises(ValueError):
        win.parse_combo("ctrl+nope")


def test_shell_app_is_the_desktop_and_explorer():
    app = appsmod.shell_app()
    assert app.id == appsmod.SHELL_ID
    assert app.matches("explorer.exe")
    assert app.matches("searchhost.exe")
    assert not app.matches("notepad.exe")


def test_resolve_prefers_an_open_app_then_falls_back_to_an_alias():
    running = [appsmod.App("notepad.exe", "Notepad", ["notepad.exe"], "", r"C:\Windows\notepad.exe")]
    assert appsmod.resolve("notepad", running, [], lambda i: "").name == "Notepad"
    # not open, but a known alias:
    got = appsmod.resolve("spotify", [], [], lambda i: "")
    assert got and "spotify.exe" in got.exes
    assert appsmod.resolve("desktop", [], [], lambda i: "").id == appsmod.SHELL_ID


def test_screenshot_scaling_round_trips_coordinates():
    from afh.engine.computer.control import Shot, Controller

    ctrl = Controller.__new__(Controller)
    shot = Shot("data:,", 700, 400, 2.0, (100, 50))  # a 1400x800 region shown at half size, offset
    # model point (10, 20) on the image → physical pixel
    assert ctrl.to_physical(shot, 10, 20) == (120, 90)


def test_app_from_dict_round_trip():
    a = appsmod.App("x!app", "Store App", ["x.exe"], "x!app", r"C:\x.exe", "full")
    assert appsmod.App.from_dict(a.to_dict()).to_dict() == a.to_dict()


# ---- the tool: batch, teach, request_access, zoom (no real input is sent) -------------------------


class FakeEngine:
    def __init__(self, settings=None):
        self._settings = settings or {}
        self.events = []
        self.interrupted = []

    def settings(self):
        return self._settings

    def publish(self, ev):
        self.events.append(ev)

    def interrupt(self, sid):
        self.interrupted.append(sid)


class FakeGate:
    def __init__(self, decision="once"):
        self.decision = decision
        self.asked = []

    async def ask_user(self, action, metadata):
        self.asked.append((action, metadata))
        return self.decision, None, None


def _ctx(engine, gate=None):
    from afh.engine.types import ToolContext

    return ToolContext(session_id="s1", message_id="m1", directory=".", permissions=gate or FakeGate(), snapshots=None,
                       emit=lambda t, d: None, engine=engine)


def _tool(monkeypatch, steps=None, fail_at=None):
    from afh.engine.tools import computer as comp
    from afh.engine.types import ToolResult

    tool = comp.ComputerTool()
    done = [] if steps is None else steps

    async def act(self, ctrl, ctx, action, input, intent):
        if fail_at is not None and len(done) == fail_at:
            raise comp.ToolError("boom")
        done.append(action)
        return f"did {action}"

    async def shot(self, ctrl, ctx, summary, app=None):
        return ToolResult(text=summary)

    monkeypatch.setattr(comp.ComputerTool, "_act", act)
    monkeypatch.setattr(comp.ComputerTool, "_shot", shot)
    monkeypatch.setattr(comp, "SETTLE", 0)
    return tool, done


def test_batch_runs_steps_in_order_with_one_screenshot_and_stops_at_the_first_error(monkeypatch):
    import asyncio

    tool, done = _tool(monkeypatch, fail_at=2)
    eng = FakeEngine()
    res = asyncio.run(tool.run(_ctx(eng), {"action": "batch", "actions": [
        {"action": "click", "x": 1, "y": 2}, {"action": "type", "text": "hi"}, {"action": "key", "key": "enter"}, {"action": "click", "x": 3, "y": 4}]}))
    assert done == ["click", "type"]
    assert "Did 2 of 4 steps" in res.text and "Step 3 (key) failed: boom" in res.text
    assert not res.is_error  # some steps ran: the model sees the screen and carries on
    bad = asyncio.run(tool.run(_ctx(eng), {"action": "batch", "actions": [{"action": "teach", "text": "x"}]}))
    assert "can't go in a batch" in bad.text
    assert any(e["type"] == "computer.active" and e["data"]["active"] for e in eng.events)


def test_teach_waits_for_next_or_exit(monkeypatch):
    import asyncio

    from afh.engine.computer.control import controller

    tool, done = _tool(monkeypatch)
    eng = FakeEngine()

    async def lesson(choice):
        task = asyncio.create_task(tool.run(_ctx(eng), {"action": "teach", "text": "Click File", "step": 1, "total": 3,
                                                        "actions": [{"action": "click", "x": 5, "y": 5}]}))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if controller(eng).lessons:
                break
        key = next(iter(controller(eng).lessons))
        shown = [e for e in eng.events if e["type"] == "computer.teach" and e["data"].get("id") == key][0]["data"]
        assert shown["text"] == "Click File" and shown["total"] == 3
        assert controller(eng).lesson_reply(key, choice)
        return await task

    res = asyncio.run(lesson("next"))
    assert "clicked Next" in res.text and done == ["click"]
    done.clear()
    res = asyncio.run(lesson("exit"))
    assert "ended the lesson" in res.text and done == []


def test_request_access_asks_once_for_every_app(monkeypatch):
    import asyncio

    from afh.engine.computer.control import Controller

    apps = {"notepad": appsmod.App("notepad.exe", "Notepad", ["notepad.exe"], "", r"C:\Windows\notepad.exe"),
            "paint": appsmod.App("mspaint.exe", "Paint", ["mspaint.exe"], "", "")}
    monkeypatch.setattr(Controller, "resolve_app", lambda self, q: apps.get(q.lower()))
    from afh.engine.tools import computer as comp

    eng, gate = FakeEngine(), FakeGate("once")
    res = asyncio.run(comp.ComputerTool().run(_ctx(eng, gate), {"action": "request_access", "apps": ["Notepad", "Paint", "Nope"], "reason": "draw"}))
    assert len(gate.asked) == 1
    meta = gate.asked[0][1]
    assert [a["name"] for a in meta["apps"]] == ["Notepad", "Paint"] and meta["reason"] == "draw"
    assert "Allowed: Notepad" in res.text and "Not found: Nope" in res.text
    # approved once for this run: asking again doesn't prompt
    asyncio.run(comp.ComputerTool().run(_ctx(eng, gate), {"action": "request_access", "apps": ["Paint"]}))
    assert len(gate.asked) == 1
    from afh.engine.types import PermissionDenied

    gate2 = FakeGate("reject")
    with pytest.raises(PermissionDenied):  # a refusal reaches the model through the runner
        asyncio.run(comp.ComputerTool().run(_ctx(FakeEngine(), gate2), {"action": "request_access", "apps": ["Notepad"]}))
    assert gate2.asked


def test_pointer_actions_and_zoom_need_a_screenshot_first(monkeypatch):
    import asyncio

    from afh.engine.tools import computer as comp

    eng = FakeEngine()
    for inp in ({"action": "click", "x": 1, "y": 1}, {"action": "zoom", "x": 0, "y": 0, "x2": 50, "y2": 50}):
        res = asyncio.run(comp.ComputerTool().run(_ctx(eng), inp))
        assert res.is_error and "screenshot first" in res.text.lower()


def test_esc_watch_ignores_afh_own_esc_and_reacts_to_the_user(monkeypatch):
    import time

    from afh.engine.computer import win

    down = {"v": False}
    monkeypatch.setattr(win, "escape_pressed", lambda: down["v"])
    hits = []
    w = win.EscWatch(lambda: hits.append(1))
    w.start()
    time.sleep(0.08)
    win._injected_esc_until = time.time() + 5  # AFH just pressed Esc itself
    down["v"] = True
    time.sleep(0.1)
    down["v"] = False
    time.sleep(0.08)
    assert hits == []
    win._injected_esc_until = 0.0
    down["v"] = True  # the user's own press
    time.sleep(0.1)
    w.stop()
    assert hits == [1]


def test_zoom_and_shot_coordinates_map_back_to_the_screenshot():
    from afh.engine.computer.control import Controller, Shot

    ctrl = Controller.__new__(Controller)
    shot = Shot("data:,", 1400, 875, 2560 / 1400, (0, 0))
    px, py = ctrl.to_physical(shot, 700, 437.5)
    assert (px, py) == (1280, 800)
    assert ctrl.to_shot(shot, px, py) == (700, 438)


def test_long_text_is_pasted_and_short_text_typed(monkeypatch):
    import asyncio

    from afh.engine.computer import win
    from afh.engine.computer.control import Controller, Shot
    from afh.engine.tools import computer as comp

    calls = []
    monkeypatch.setattr(win, "paste_text", lambda t: calls.append(("paste", t)) or True)
    monkeypatch.setattr(win, "type_text", lambda t: calls.append(("type", t)))
    monkeypatch.setattr(win, "foreground", lambda: object())
    monkeypatch.setattr(win, "cursor_pos", lambda: (0, 0))
    app = appsmod.App("notepad.exe", "Notepad", ["notepad.exe"])

    async def require(self, ctrl, ctx, w, typing=False):
        return app

    monkeypatch.setattr(comp.ComputerTool, "_require", require)
    eng = FakeEngine()
    tool = comp.ComputerTool()

    async def go():
        ctrl = Controller(eng)
        ctx = _ctx(eng)
        short = await tool._act(ctrl, ctx, "type", {"text": "hello"}, "")
        long = await tool._act(ctrl, ctx, "type", {"text": "x" * 60}, "")
        lines = await tool._act(ctrl, ctx, "type", {"text": "a\nb"}, "")
        return short, long, lines

    short, long, lines = asyncio.run(go())
    assert calls == [("type", "hello"), ("paste", "x" * 60), ("paste", "a\nb")]
    assert short.startswith("Typed") and long.startswith("Pasted")
