"""The controller behind the `computer` tool: screenshots, approvals, the overlay and the stop watch.

One Controller lives per engine. It keeps the user's always-allowed apps (in settings), tells the
desktop shell what to draw on its overlay while a task runs (the glow, AFH's cursor, click ripples,
keycaps, lesson tooltips), and watches for the user pressing Esc so a task stops at once.
"""
from __future__ import annotations

import asyncio
import base64
import io
from dataclasses import dataclass

from . import apps as appsmod
from . import win

# Long edge the screenshot is scaled to before it goes to the model: plenty for reading UI, and
# small enough to keep the token cost down. Coordinates the model gives back are scaled up again.
SHOT_LONG_EDGE = 1400
JPEG_QUALITY = 72


@dataclass
class Shot:
    data_uri: str
    width: int   # scaled image size the model sees
    height: int
    scale: float  # physical pixels per model pixel
    origin: tuple[int, int]  # physical (left, top) the image starts at


class Controller:
    def __init__(self, engine):
        self.engine = engine
        self.active: dict[str, int] = {}  # session id -> a step token (drives the overlay; latest wins)
        self.last_shot: dict[str, Shot] = {}  # session id -> the screenshot the model last saw (for scaling its x,y)
        self.asked_once: dict[str, set] = {}  # session id -> app ids approved once this run
        self.display: dict[str, int] = {}  # session id -> the display it is looking at
        self.lessons: dict[str, asyncio.Future] = {}  # teach step id -> waits for Next / Exit
        self._tick = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._esc = win.EscWatch(self._on_escape) if win.is_supported() else None

    # ---- settings: the user's always-allowed apps -------------------------------------------

    def _cfg(self) -> dict:
        return self.engine.settings().get("computer") or {}

    def enabled(self) -> bool:
        return win.is_supported() and self._cfg().get("enabled", True) is not False

    def allowed_apps(self) -> list[appsmod.App]:
        return [appsmod.App.from_dict(a) for a in self._cfg().get("allowed", []) if isinstance(a, dict)]

    def is_allowed(self, app: appsmod.App) -> bool:
        return any(a.id == app.id or (app.exes and set(a.exes) & set(app.exes)) or (app.aumid and a.aumid == app.aumid) for a in self.allowed_apps())

    def allow_app(self, app: appsmod.App) -> None:
        allowed = [a for a in self.allowed_apps() if a.id != app.id]
        allowed.append(app)
        self._save([a.to_dict() for a in allowed])

    def forget_app(self, app_id: str) -> None:
        self._save([a.to_dict() for a in self.allowed_apps() if a.id != app_id])

    def _save(self, allowed: list[dict]) -> None:
        from afh import store

        cfg = dict(self._cfg())
        cfg["allowed"] = allowed
        store.replace_setting("computer", cfg)
        self.engine.publish({"type": "computer.apps.changed", "data": {}})

    # ---- resolving which app a window / name is ---------------------------------------------

    def app_of_window(self, w: win.Window | None) -> appsmod.App | None:
        if not w:
            return None
        app = appsmod.app_for_window(w, win.file_description)
        app.tier = appsmod.tier_for(w.exe_name, self.engine.settings())
        return app

    def running_apps(self) -> list[appsmod.App]:
        seen: dict[str, appsmod.App] = {}
        for w in win.windows():
            if w.tool or appsmod.never(w.exe_name, w.exe):
                continue
            app = self.app_of_window(w)
            if app and app.id not in seen:
                seen[app.id] = app
        return list(seen.values())

    def resolve_app(self, query: str) -> appsmod.App | None:
        app = appsmod.resolve(query, self.running_apps(), win.start_apps(), win.start_app_exe)
        if app:
            exe = app.exes[0] if app.exes else ""
            app.tier = appsmod.tier_for(exe, self.engine.settings())
        return app

    def window_of(self, app: appsmod.App) -> win.Window | None:
        return next((w for w in win.windows() if not w.tool and app.matches(w.exe_name, w.aumid)), None)

    # ---- the overlay the desktop shell draws ------------------------------------------------

    def begin_step(self, sid: str, status: str = "") -> int:
        """Show the overlay for this session's task and return a token for this step."""
        self._tick += 1
        self.active[sid] = self._tick
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        if self._esc:
            self._esc.start()
        cfg = self._cfg()
        self.engine.publish({"type": "computer.active", "data": {
            "sessionID": sid, "active": True, "status": status, "busy": True,
            "hideWindow": cfg.get("hideWindow", True) is not False, "effects": cfg.get("effects", True) is not False}})
        return self._tick

    def end_step(self, sid: str, token: int, loop) -> None:
        """Between steps the overlay stays up ("Thinking…"); a while after the last one it goes."""
        if self.active.get(sid) == token:
            self.engine.publish({"type": "computer.active", "data": {"sessionID": sid, "active": True, "status": "", "busy": False}})

        def off():
            if self.active.get(sid) == token:
                self.clear(sid)
        loop.call_later(20.0, off)

    def clear(self, sid: str) -> None:
        if self.active.pop(sid, None) is not None:
            self.engine.publish({"type": "computer.active", "data": {"sessionID": sid, "active": False, "status": ""}})
        self.last_shot.pop(sid, None)
        self.asked_once.pop(sid, None)
        self.display.pop(sid, None)
        for key in [k for k in self.lessons if k.startswith(sid + ":")]:
            fut = self.lessons.pop(key)
            if not fut.done():
                fut.set_result("exit")
        if not self.active and self._esc:
            self._esc.stop()

    def fx(self, sid: str, kind: str, **data) -> None:
        """Something for the overlay to show: AFH's cursor moving or clicking, keys, a scroll, a
        screenshot flash... Points are PHYSICAL desktop pixels; the shell converts them."""
        self.engine.publish({"type": "computer.fx", "data": {"sessionID": sid, "kind": kind, **data}})

    def cursor(self, sid: str, x: int, y: int, label: str, kind: str = "move") -> None:
        self.fx(sid, kind, x=x, y=y, label=label)

    # ---- the user stopping it -------------------------------------------------------------------

    def _on_escape(self) -> None:
        """Called from the Esc watch thread: stop every computer task, on the engine's loop."""
        if self._loop and self.active:
            self._loop.call_soon_threadsafe(self._stop_all)

    def _stop_all(self) -> None:
        for sid in list(self.active):
            self.fx(sid, "stopped", label="Stopped — you pressed Esc")
            try:
                self.engine.interrupt(sid)
            except Exception:
                pass
            self.clear(sid)

    # ---- teach mode: a tooltip on screen, waiting for Next ------------------------------------

    async def lesson_step(self, sid: str, step: dict) -> str:
        """Show one lesson tooltip and wait until the user clicks Next ("next") or Exit ("exit")."""
        self._tick += 1
        key = f"{sid}:{self._tick}"
        fut = asyncio.get_running_loop().create_future()
        self.lessons[key] = fut
        self.engine.publish({"type": "computer.teach", "data": {"sessionID": sid, "id": key, **step}})
        try:
            return await fut
        finally:
            self.lessons.pop(key, None)
            self.engine.publish({"type": "computer.teach", "data": {"sessionID": sid, "id": key, "done": True}})

    def lesson_reply(self, key: str, choice: str) -> bool:
        fut = self.lessons.get(key)
        if not fut or fut.done():
            return False
        fut.set_result("exit" if choice == "exit" else "next")
        return True

    # ---- screenshots ------------------------------------------------------------------------

    def display_rect(self, sid: str) -> tuple[int, int, int, int]:
        ds = win.displays()
        if not ds:
            vx, vy, vw, vh = win.virtual_screen()
            return (vx, vy, vx + vw, vy + vh)
        i = self.display.get(sid, 0)
        return ds[i].rect if 0 <= i < len(ds) else ds[0].rect

    def follow(self, sid: str, w: win.Window | None) -> None:
        """Look at the display an app's window is on (when it moves to another monitor)."""
        if not w:
            return
        cx, cy = (w.rect[0] + w.rect[2]) // 2, (w.rect[1] + w.rect[3]) // 2
        d = win.display_at(cx, cy)
        if d:
            self.display[sid] = d.index

    def screenshot(self, rect: tuple[int, int, int, int], long_edge: int = SHOT_LONG_EDGE) -> Shot:
        img = win.capture(rect)
        w, h = img.size
        scale = max(w, h) / long_edge if max(w, h) > long_edge else 1.0
        if scale > 1.0:
            img = img.resize((max(1, round(w / scale)), max(1, round(h / scale))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        return Shot(uri, img.size[0], img.size[1], scale, (rect[0], rect[1]))

    def to_physical(self, shot: Shot, x: float, y: float) -> tuple[int, int]:
        """A point the model gave (in the screenshot it saw) → a physical desktop pixel."""
        return round(shot.origin[0] + x * shot.scale), round(shot.origin[1] + y * shot.scale)

    def to_shot(self, shot: Shot | None, px: int, py: int) -> tuple[int, int]:
        if not shot:
            return px, py
        return round((px - shot.origin[0]) / shot.scale), round((py - shot.origin[1]) / shot.scale)


def controller(engine) -> Controller:
    if not getattr(engine, "_computer", None):
        engine._computer = Controller(engine)
    return engine._computer
