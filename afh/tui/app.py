"""The terminal app: AFH full screen, as a client of the same local API the desktop window uses."""
from __future__ import annotations

import asyncio
import os
import queue
import re
import time
from pathlib import Path
from typing import Any, Callable

from textual import work
from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Static

from .. import __version__
from ..cli import HOME, CliError, Events
from . import state as S
from . import themes
from .actions import Actions
from .composer import Box, Composer, History
from .dialogs import Approval, Question
from .look import SPINE_X, Palette, Spine, keys, shimmer, unless_gone
from .mark import STRANDS, Mark
from .panels import RAIL_WIDTH, Dock, LivePane, Rail
from .widgets import MARKDOWN_CSS, SPINNER, Row, Transcript, bar, gradient

MODE_ORDER = ["ask", "full", "readonly"]
MODE_LABEL = {"ask": "Ask first", "full": "Full access", "readonly": "Read only"}
COMPACT_AT = 80
STRAND_ENDS = [s[2] for s in STRANDS]
TIGHT_HEIGHT = 20  # rows under which the deck gives up its mark
TIGHT_WIDTH = 56  # and columns
TABS = [("Goal", "goal", 0), ("Memory", "memory", 92), ("Live", "live", 74), ("Changes", "diff", 0), ("Context", "cost", 84), ("Prompt", "prompt", 100)]

CSS = """
Main { background: $background; }
SettingsScreen { background: $background; }
ToastRack { align: right top; margin: 1 1 0 0; }
Toast { background: $panel; border-left: none; padding: 0 2; width: auto; max-width: 60; }
Toast.-error { background: $error 22%; }
Toast.-warning { background: $warning 18%; }
#app { height: 1fr; }
#center { width: 1fr; height: 1fr; }
#top { height: 1; padding: 0 2 0 1; margin: 0 0 1 0; }
#top-left { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
#flow { height: 1fr; }
Main.-boot #rail, Main.-boot #top, Main.-boot #composer, Main.-boot #dock { display: none; }
"""


class Boot(Vertical):
    """What the app shows while it opens: the mark, flowing, as the app's own boot screen has it."""

    DEFAULT_CSS = """
    Boot { height: 100%; width: 100%; align: center middle; }
    Boot Mark { margin: 0 0 1 0; }
    Boot #boot-text { width: 39; text-align: center; color: $afh-text3; }
    """

    def compose(self):
        yield Mark(13, working=True)
        yield Static("Starting AFH", id="boot-text")


class Tab(Static):
    """A word in the top bar, like the tabs along the top of the app."""

    DEFAULT_CSS = """
    Tab { width: auto; height: 1; padding: 0 1; color: $afh-text3; }
    Tab:hover { color: $foreground; background: $boost; }
    Tab.-off { display: none; }
    """

    def __init__(self, label: str, command: str, needs: int):
        super().__init__(label)
        self.label, self.command, self.needs = label, command, needs

    def on_click(self) -> None:
        self.app.action_command(self.command)

    def show(self, count: int = 0) -> None:
        self.update(Content.assemble(self.label, (f" {count}", "$primary bold") if count else ""))


class Fact(Vertical):
    """Where one of the mark's strands leads on the start screen."""

    DEFAULT_CSS = """
    Fact { height: 2; width: auto; }
    Fact:hover .fact-top { background: $boost; }
    Fact Static { height: 1; width: auto; max-width: 64; text-wrap: nowrap; text-overflow: ellipsis; }
    """

    def __init__(self, strand: int, top: Any, sub: Any, fn: Any, lead: int = 6, **kw: Any):
        super().__init__(**kw)
        self.strand, self.top, self.sub, self.fn, self.lead = strand, top, sub, fn, lead

    def compose(self):
        colour = STRAND_ENDS[self.strand]
        strand = Content.assemble(*[("━", themes.mix(colour, "#000000", i / self.lead * 0.25)) for i in range(self.lead)])
        yield Static(Content.assemble(strand, "  ", self.top), classes="fact-top")
        yield Static(Content.assemble(" " * (self.lead + 2), self.sub))

    def on_click(self) -> None:
        self.fn()


class Home(Vertical):
    """The start screen: the mark, with its three strands running on to where you are, who's working and what's next."""

    DEFAULT_CSS = """
    Home { height: 100%; width: 100%; align: center middle; padding: 0 2; }
    Home > * { width: auto; }
    Home #hero { height: auto; width: auto; }
    Home #facts { height: auto; width: auto; offset: -1 0; }
    Home #slot-1 { margin: 2 0 0 0; }
    Home #slot-2, Home #slot-3 { margin: 2 0 0 0; }
    Home #greeting { height: auto; margin: 0 0 2 0; }
    Home #tips { height: auto; margin: 2 0 0 0; }
    Home.-small #slot-1, Home.-small #slot-2, Home.-small #slot-3 { margin: 1 0 0 0; }
    """

    def __init__(self, ui: "AFH"):
        super().__init__(id="home")
        self.ui = ui

    def small(self) -> bool:
        return self.ui.middle < 96 or self.ui.size.height < 30

    def fit(self) -> None:
        small = self.small()
        self.set_class(small, "-small")
        self.query_one("#home-mark", Mark).resize(8 if small else 13)

    def compose(self):
        ui = self.ui
        small = self.small()
        self.set_class(small, "-small")
        ref = ui.model_ref()
        model = ui.model_name(ref)
        folder = S.base_name(ui.dir) or ui.dir
        last = ui.recent[0] if ui.recent else None
        yield Static(Content.assemble(gradient("Agent Flow Harness"), (f"   {__version__}", "$afh-text3")), id="greeting")
        with Horizontal(id="hero"):
            yield Mark(8 if small else 13, id="home-mark")
            with Vertical(id="facts"):
                yield Fact(0, (folder, "bold"), (ui.pretty_dir(), "$afh-text3"), lambda: ui.action_command("open"), id="slot-1")
                who = f"{ui.agent_name(ui.agent_id())} · {MODE_LABEL.get(ui.mode_id(), ui.mode_id())}"
                yield Fact(1, (model or "No model yet", "bold"), (who if ref else "/connect adds one", "$afh-text3"), lambda: ui.action_command("model" if ref else "connect"), id="slot-2")
                if last:
                    yield Fact(2, Content.assemble(("Continue  ", "$afh-text3"), (S.one_line(last.get("title") or "New thread", 70), "bold")),
                               (f"{S.ago((last.get('time') or {}).get('updated'))} · Ctrl K for all of them", "$afh-text3"), lambda: ui.open_thread(last["id"]), id="slot-3")
                else:
                    yield Fact(2, ("Start something", "bold"), ("Say what you want done", "$afh-text3"), lambda: ui.composer.box.focus(), id="slot-3")
        yield Static(keys("/ commands   @ files   ! shell   ? help"), id="tips")


class Main(Screen):
    """The conversation screen. Its keys are priority keys, so the message box never swallows them."""

    BINDINGS = [
        Binding("ctrl+c", "app.ctrl_c", "Clear / exit", priority=True, show=False),
        Binding("escape", "app.escape", "Stop", show=False),
        Binding("tab", "app.next_agent", "Agent", priority=True, show=False),
        Binding("shift+tab", "app.next_mode", "Approvals", priority=True, show=False),
        Binding("ctrl+p", "app.palette", "Palette", priority=True, show=False),
        Binding("ctrl+k", "app.command('threads')", "Threads", priority=True, show=False),
        Binding("ctrl+n", "app.command('new')", "New thread", priority=True, show=False),
        Binding("ctrl+o", "app.toggle_details", "Details", priority=True, show=False),
        Binding("ctrl+t", "app.toggle_todos", "To-dos", priority=True, show=False),
        Binding("ctrl+b", "app.toggle_live", "Live panel", priority=True, show=False),
        Binding("f3", "app.toggle_rail", "Threads rail", priority=True, show=False),
        Binding("ctrl+l", "app.redraw", "Redraw", priority=True, show=False),
        Binding("ctrl+r", "app.history_search", "History", priority=True, show=False),
        Binding("ctrl+g", "app.command('editor')", "Editor", priority=True, show=False),
        Binding("ctrl+y", "app.copy_last", "Copy", priority=True, show=False),
        Binding("ctrl+x", "app.drop_attachment", "Remove file", priority=True, show=False),
        Binding("alt+v", "app.paste_image", "Paste image", priority=True, show=False),
        Binding("f1", "app.command('help')", "Help", priority=True, show=False),
        Binding("f2", "app.command('settings')", "Settings", priority=True, show=False),
        Binding("pageup", "app.scroll(-1)", show=False, priority=True),
        Binding("pagedown", "app.scroll(1)", show=False, priority=True),
        Binding("ctrl+home", "app.scroll_to(0)", show=False, priority=True),
        Binding("ctrl+end", "app.scroll_to(1)", show=False, priority=True),
    ]

    def __init__(self, ui: "AFH"):
        super().__init__()
        self.ui = ui

    def on_mount(self) -> None:
        self.ui.begin()

    def compose(self):
        ui = self.ui
        with Horizontal(id="app"):
            yield ui.rail
            with Vertical(id="center"):
                with Horizontal(id="top"):
                    yield Static(id="top-left")
                    yield from ui.tabs
                with Horizontal(id="flow"):
                    yield ui.spine
                    yield ui.scroller
                yield ui.dock
                yield ui.composer
            yield ui.live


class AFH(Actions, App):
    TITLE = "AFH"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS + MARKDOWN_CSS
    ALLOW_SELECT = True
    BINDINGS = [Binding("ctrl+c", "ctrl_c", show=False, priority=False), Binding("ctrl+q", "quit_now", show=False)]

    def __init__(self, client: Any, events: Any, directory: str, *, model: str | None = None, agent: str | None = None, mode: str | None = None,
                 thread: str | None = None, resume: bool = False, home: Path | None = None, opener: Callable[[], Any] | None = None):
        super().__init__()
        self.client, self.events = client, events
        self.opener = opener  # connects while the boot screen shows, when there's no client yet
        self.dir = directory
        self.home_dir = home or HOME
        self.boot: dict = {}
        self.settings: dict = {}
        self.models: list[dict] = []
        self.agents: list[dict] = []
        self.provider_names: dict = {}
        self.commands_cache: list[dict] = []
        self.recent: list[dict] = []
        self.thread: S.Thread | None = None
        self.threads: dict[str, S.Thread] = {}  # every thread open in this run, helpers included
        self.draft: dict = {"model": None, "agent": agent, "mode": mode, "goal": None, "worktree": False}
        self.wanted = {"model": model, "thread": thread, "resume": resume}
        self.history = History(self.home_dir / "tui-history.json")
        self.scroller = Transcript(self, id="transcript")
        self.spine = Spine(self.scroller, id="spine")
        self.rail = Rail(self, id="rail")
        self.tabs = [Tab(*t) for t in TABS]
        self.composer = Composer(self, self.history, id="composer")
        self.dock = Dock(self, id="dock")
        self.live = LivePane(self, id="live")
        self.main_screen = Main(self)
        self.asking: set[str] = set()
        self.perm_open = False
        self.tick = 0
        self.flowing = False
        self.last_esc = 0.0
        self.last_ctrl_c = 0.0
        self.compact_at = COMPACT_AT
        self.notice = ""
        self.update_notice = ""
        self.connected = asyncio.Event()  # what's asked for during boot waits here
        if client:
            self.connected.set()
        self.marks: set[Mark] = set()
        self.drawing: Any = None  # the update on its way to the terminal

    # ---- talking to the backend ---------------------------------------------------------------

    async def api(self, method: str, path: str, body: Any = None, params: dict | None = None, timeout: float = 60) -> Any:
        await self.connected.wait()
        return await asyncio.to_thread(self.client.request, method, path, body, params, timeout)

    async def get(self, path: str, **params: Any) -> Any:
        return await self.api("GET", path, params=params or None)

    def fail(self, err: Any) -> None:
        self.notify(str(err), severity="error", timeout=8, markup=False)

    def say(self, text: str, timeout: float = 3) -> None:
        self.notify(text, timeout=timeout, markup=False)

    # ---- start --------------------------------------------------------------------------------

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return {"afh-side": "#121010", "afh-panel3": "#292524", "afh-border": "#2a2625", "afh-border2": "#3a3533", "afh-text2": "#b4ada6", "afh-text3": "#7e776f", "afh-code": "#0b0a0a"}

    def on_mount(self) -> None:
        for theme in themes.all_themes():
            self.register_theme(theme)
        self.theme = "afh-sunset"
        self.push_screen(self.main_screen)
        self.main_screen.add_class("-boot")
        self.set_interval(1 / 30, self.pump)
        self.set_interval(0.1, self.spin)

    @work(exclusive=True, group="begin")
    async def begin(self) -> None:
        with unless_gone(self.scroller):
            await self.scroller.mount(Boot())
        self.strand(False)
        try:
            if self.client is None:
                self.client = await asyncio.to_thread(self.opener)
                self.events = await asyncio.to_thread(Events, self.client)
                self.connected.set()
        except CliError as err:
            self.exit(return_code=err.code, message=str(err))
            return
        try:
            await self.load_catalog()
            await self.api("POST", "/api/projects", {"path": self.dir})
        except CliError as err:
            self.fail(err)
        self.apply_look()
        self.draw_status()
        if self.wanted.get("model"):
            pid, _, mid = str(self.wanted["model"]).partition("/")
            self.draft["model"] = {"providerID": pid, "id": mid}
        try:
            self.recent = await self.get("/api/sessions", directory=self.dir, limit=8) or []
        except CliError:
            self.recent = []
        wanted = self.wanted.get("thread") or (self.recent[0]["id"] if self.wanted.get("resume") and self.recent else None)
        self.main_screen.remove_class("-boot")
        self.fit()
        if wanted:
            await self.show_thread(wanted)
        else:
            await self.show_home()
        self.composer.box.focus()
        self.check_for_update()

    async def load_catalog(self) -> None:
        boot = await self.get("/api/bootstrap")
        self.boot = boot
        self.warn_if_app_is_older(str(boot.get("version") or ""))
        self.settings = boot.get("settings") or {}
        self.models = boot.get("models") or []
        self.agents = boot.get("agents") or []
        self.provider_names = boot.get("providerNames") or {}
        self.composer.send_key = (self.settings.get("ui") or {}).get("sendKey") or "enter"
        agent = self.settings.get("agent") or {}
        self.compact_at = agent.get("compactAt") or COMPACT_AT
        await self.load_commands()

    def warn_if_app_is_older(self, version: str) -> None:
        """Attached to a desktop app that hasn't updated yet: some things here won't work until it does."""
        from .update import newer

        if version and not self.client.backend and newer(__version__, version):
            self.say(f"The AFH app running on this PC is {version}, older than this terminal ({__version__}). Update the app, or some things here won't work.", 12)

    async def load_commands(self) -> None:
        try:
            self.commands_cache = await self.get("/api/commands", directory=self.dir) or []
        except CliError:
            self.commands_cache = []

    def apply_look(self) -> None:
        ui = self.settings.get("ui") or {}
        chosen = (self.settings.get("tui") or {}).get("theme") or themes.preset_for(ui)
        if chosen == "custom":
            custom = themes.custom_theme(ui.get("bg") or "#0f0d0c", ui.get("text") or "#f1ede9", ui.get("accent") or "#ff6a2a")
            self.register_theme(custom)
        elif chosen not in themes.PRESETS:
            chosen = themes.FALLBACK
        self.theme = f"afh-{chosen}"

    # ---- what the widgets ask for -------------------------------------------------------------

    def setting(self, key: str, default: Any = None) -> Any:
        value = (self.settings.get("ui") or {}).get(key)
        return default if value is None else value

    def directory(self) -> str:
        t = self.thread
        return ((t.session.get("location") or {}).get("directory") if t else None) or self.dir

    def pretty_dir(self) -> str:
        path = self.dir
        home = str(Path.home())
        return "~" + path[len(home):] if path.lower().startswith(home.lower()) else path

    def find_model(self, ref: Any) -> dict | None:
        if not isinstance(ref, dict):
            return None
        return next((m for m in self.models if m.get("id") == ref.get("id") and m.get("providerID") == ref.get("providerID")), None)

    def model_ref(self) -> dict | None:
        t = self.thread
        for ref in ((t.session.get("model") if t else None), self.draft.get("model"), self.settings.get("defaultModel"), self.boot.get("defaultModel")):
            if self.find_model(ref):
                return ref
        return None

    def model_name(self, ref: Any) -> str:
        m = self.find_model(ref)
        if m:
            return m.get("name") or m.get("id") or ""
        return (ref or {}).get("id") or "" if isinstance(ref, dict) else ""

    def provider_name(self, pid: str) -> str:
        return self.provider_names.get(pid) or pid.replace("-", " ").replace("_", " ").title()

    def agent_id(self) -> str:
        t = self.thread
        return (t.session.get("agent") if t else None) or self.draft.get("agent") or self.settings.get("defaultAgent") or "build"

    def agent_name(self, aid: str) -> str:
        delegates = (self.settings.get("delegation") or {}).get("delegates") or []
        found = next((d for d in delegates if d.get("id") == aid), None) or next((a for a in self.agents if a.get("id") == aid), None)
        return (found or {}).get("name") or aid

    def mode_id(self) -> str:
        t = self.thread
        meta = ((t.session.get("metadata") or {}).get("afh") or {}) if t else {}
        return meta.get("mode") or self.draft.get("mode") or self.settings.get("defaultMode") or "ask"

    def main_agents(self) -> list[dict]:
        return [a for a in self.agents if not a.get("hidden") and a.get("mode") != "subagent"]

    def child_of(self, thread: S.Thread, tool: dict) -> S.Thread | None:
        given = S.tool_input(tool)
        cid = given.get("sessionID") or ((tool.get("state") or {}).get("metadata") or {}).get("sessionID")
        if not cid:
            cid = next((k for k, v in thread.children.items() if v.get("tool") == tool.get("id")), None)
        if not cid:
            cid = next((k for k, v in thread.children.items() if v.get("title") == given.get("description")), None)
        return self.threads.setdefault(cid, S.Thread(cid, {"id": cid})) if cid else None

    # ---- opening threads ----------------------------------------------------------------------

    async def show_home(self) -> None:
        self.thread = None
        await self.scroller.show(None)
        self.strand(False)
        with unless_gone(self.scroller):
            await self.scroller.mount(Home(self))
        self.dock.draw()
        self.draw_status()
        self.rail.reload()

    def strand(self, on: bool) -> None:
        """A thread has a strand, and it runs down into the deck."""
        self.spine.set_class(not on, "-off")
        self.land_strand()

    def land_strand(self) -> None:
        """The strand lands on the mark's top left point. With no mark, it meets the line."""
        line = self.composer.line
        join = SPINE_X if self.composer.has_class("-tight") and not self.spine.has_class("-off") else None
        if join != line.join:
            line.join = join
            line.refresh()

    def fit(self) -> None:
        """What the terminal has room for."""
        if self.main_screen.has_class("-boot") or not self.main_screen.is_attached:
            return
        self.live.fit()
        self.rail.fit()
        middle = self.middle
        self.composer.set_class(self.size.height < TIGHT_HEIGHT or middle < TIGHT_WIDTH, "-tight")
        self.land_strand()
        for tab in self.tabs:
            tab.set_class(middle < tab.needs, "-off")
        for home in self.scroller.query(Home):
            home.fit()
        self.draw_status()

    @property
    def middle(self) -> int:
        """Columns the conversation gets, between the rail and the live panel."""
        return self.size.width - self.live.taken() - (RAIL_WIDTH if self.rail.shown() else 0)

    def overlay(self, x: int, y: int, image: str) -> None:
        """An image straight to the terminal, over the cells at x, y. The cursor stays where the app left it."""
        if self._driver is None:
            return
        alone = self.drawing is None  # part of an update, it shows with that update
        if alone:
            self._begin_update()
        self._driver.write(f"\x1b7\x1b[{y + 1};{x + 1}H{image}\x1b8")
        if alone:
            self._end_update()

    def _display(self, screen: Any, renderable: Any) -> None:
        self.drawing = renderable
        try:
            super()._display(screen, renderable)
        finally:
            self.drawing = None

    def _end_update(self) -> None:
        """Text wipes an image, so one that an update wrote over goes back before the terminal shows the result."""
        if self.drawing is not None:
            for mark in tuple(self.marks):
                if mark.touched(self.drawing):
                    mark.paint()
        super()._end_update()

    def on_resize(self) -> None:
        self.call_next(self.fit)  # this handler runs before Textual has stored the new size

    def open_thread(self, sid: str) -> None:
        self.run_worker(self.show_thread(sid), group="open", exclusive=True)

    async def show_thread(self, sid: str) -> None:
        try:
            t = self.threads.get(sid) or S.Thread(sid, {"id": sid})
            messages, permissions, fresh = await asyncio.gather(self.get(f"/api/sessions/{sid}/messages"), self.get(f"/api/sessions/{sid}/permissions"), self.get(f"/api/sessions/{sid}"))
            t.load(messages or [], permissions or [], fresh)
            afh = (t.session.get("metadata") or {}).get("afh") or {}
            t.todos, t.goal = afh.get("todos") or [], afh.get("goal")
            self.threads[sid] = t
            self.thread = t
            try:
                t.jobs = await self.get(f"/api/sessions/{sid}/jobs") or []
                kids = await self.get(f"/api/sessions/{sid}/children") or []
            except CliError:
                kids = []
            for s in kids:
                t.children.setdefault(s["id"], {"title": s.get("title"), "agent": s.get("agent"), "model": s.get("model")})
                self.threads.setdefault(s["id"], S.Thread(s["id"], s))
            await self.scroller.show(t)
            self.strand(True)
            self.dock.draw()
            self.draw_status()
            self.pump_permissions()
            self.rail.reload()
        except CliError as err:
            self.fail(err)

    async def reload_thread(self) -> None:
        if self.thread:
            await self.show_thread(self.thread.id)

    # ---- events -------------------------------------------------------------------------------

    def pump(self) -> None:
        """Up to 400 events a tick, on the app's own thread."""
        if self.events is None:
            return
        for _ in range(400):
            try:
                ev = self.events.queue.get_nowait()
            except queue.Empty:
                return
            self.handle(ev)

    def handle(self, ev: dict) -> None:
        kind, d = ev.get("type", ""), ev.get("data") or {}
        sid = d.get("sessionID")
        if kind in ("afh.ready", "model.updated", "agent.updated"):
            self.run_worker(self.refresh_catalog, group="catalog", exclusive=True)
            return
        if kind == "session.created" and d.get("parentID") in self.threads:
            parent = self.threads[d["parentID"]]
            tool = next((p.get("id") for m in reversed(parent.messages) for p in reversed(m.get("content") or [])
                         if p.get("type") == "tool" and (p.get("name") or "").lower() == "subagent" and (p.get("state") or {}).get("status") in ("running", "streaming")
                         and p.get("id") not in {c.get("tool") for c in parent.children.values()}), None)
            parent.children[sid] = {"title": d.get("title"), "agent": d.get("agent"), "model": d.get("model"), "tool": tool}
            self.threads.setdefault(sid, S.Thread(sid, {"id": sid, "title": d.get("title"), "agent": d.get("agent"), "model": d.get("model"), "parentID": d["parentID"]}))
            return
        t = self.threads.get(sid)
        if t is None:
            return
        change = S.apply_event(t, ev)
        self.live.feed(ev, t)
        if t is not self.thread:
            if t.session.get("parentID") == (self.thread.id if self.thread else None):
                self.touch_delegate(t)
            if change and change.perm:
                self.pump_permissions()
            return
        if change is None:
            return
        if change.reload:
            self.run_worker(self.reload_thread, group="reload", exclusive=True)
            return
        if change.all:
            self.run_worker(self.scroller.add_new, group="add", exclusive=False)
        if change.msg:
            self.scroller.touch(change.msg)
        if change.perm:
            self.pump_permissions()
        if change.status:
            self.dock.draw()
            self.draw_status()
        if kind in ("session.execution.succeeded", "session.execution.failed"):
            self.bell_when_done(kind)
            self.rail.reload()

    def touch_delegate(self, child: S.Thread) -> None:
        t = self.thread
        if not t:
            return
        tool = t.children.get(child.id, {}).get("tool")
        for m in reversed(t.messages):
            if any(p.get("id") == tool for p in m.get("content") or []):
                self.scroller.touch(m["id"])
                return

    def bell_when_done(self, kind: str) -> None:
        if self.setting("sounds", True) and not self.is_headless:
            self.bell()

    @property
    def is_headless(self) -> bool:
        return bool(getattr(self, "_driver", None) and self._driver.is_headless)

    async def refresh_catalog(self) -> None:
        try:
            await self.load_catalog()
            self.draw_status()
        except CliError:
            pass

    # ---- approvals and questions --------------------------------------------------------------

    def pump_permissions(self) -> None:
        if self.perm_open:
            return
        for t in self.threads.values():
            for p in t.permissions.values():
                if p.get("id") not in self.asking:
                    self.ask(t, p)
                    return

    def ask(self, t: S.Thread, p: dict) -> None:
        self.perm_open = True
        self.asking.add(p["id"])
        question = p.get("action") == "question" and isinstance((p.get("metadata") or {}).get("questions"), list)
        design = p.get("action") == "design" and (p.get("metadata") or {}).get("design")

        def replied(result: Any) -> None:
            self.perm_open = False
            if result is None:
                self.say("It's waiting for you. /approvals shows it again.", 5)
                self.pump_permissions()
                return
            self.run_worker(self.answer(t, p, *result), group="answer", exclusive=False)

        if design:
            self.show_design(t, p, replied)
        elif question:
            self.push_screen(Question(p), replied)
        else:
            title = t.session.get("title") if t is not self.thread else ""
            self.push_screen(Approval(p, title or ""), replied)

    async def answer(self, t: S.Thread, p: dict, decision: str, extra: Any) -> None:
        body: dict = extra if decision == "design" else {"decision": decision}
        if decision == "answer":
            body["answers"] = extra
        elif extra and decision != "design":
            body["message"] = extra
        try:
            await self.api("POST", f"/api/sessions/{t.id}/permissions/{p['id']}", body)
        except CliError as err:
            self.fail(err)
        t.permissions.pop(p["id"], None)
        self.pump_permissions()

    # ---- sending ------------------------------------------------------------------------------

    def on_box_sent(self, message: Box.Sent) -> None:
        text = message.text.strip()
        if text and not self.main_screen.has_class("-boot"):  # typed during boot: it stays in the box for when it opens
            self.run_worker(self.send(text), group="send", exclusive=False)

    async def send(self, text: str) -> None:
        composer = self.composer
        if text == "?":
            composer.clear()
            await self.run_command("help", "")
            return
        if text.startswith("!") and len(text) > 1:
            composer.clear()
            self.history.add(text)
            await self.shell(text[1:].strip())
            return
        slash = re.fullmatch(r"/([a-z0-9][a-z0-9_:-]*)(?:\s+([\s\S]*))?", text, re.I)
        if slash:
            name, args = slash.group(1).lower(), (slash.group(2) or "").strip()
            if self.is_local(name, args):
                composer.clear()
                self.history.add(text)
                await self.run_command(name, args)
                return
        ref = self.model_ref()
        if not ref:
            self.say("Add a provider first", 4)
            await self.run_command("connect", "")
            return
        files = list(composer.files)
        composer.clear()
        self.history.add(text)
        await self.send_prompt(text, files)

    async def send_prompt(self, text: str, files: list[str] | None = None) -> None:
        try:
            t = self.thread
            if t is None:
                t = await self.create_thread(text)
            t.error = None
            t.busy = True
            t.run_start = S.now_ms()
            t.phase = "sending"
            t.live_tps = 0
            self.draw_status()
            await self.scroller.draw_error()
            self.scroller.anchor()
            await self.api("POST", f"/api/sessions/{t.id}/prompt", {"text": text, "files": files or []}, timeout=120)
        except CliError as err:
            self.fail(err)
            if self.thread:
                self.thread.busy = False
            self.composer.set_text(text)
            self.draw_status()

    async def create_thread(self, text: str) -> S.Thread:
        worktree = bool(self.draft.get("worktree"))
        body = {"directory": self.dir, "model": self.model_ref(), "agent": self.agent_id(), "mode": self.mode_id(), "worktree": worktree}
        if worktree:
            self.say("Creating a worktree…")
            body["worktreeName"] = " ".join(re.sub(r"^/\S+\s*", "", text).split()[:5])
        session = await self.api("POST", "/api/sessions", body, timeout=120)
        goal = self.draft.get("goal")
        if goal:
            await self.api("PUT", f"/api/sessions/{session['id']}/goal", goal)
        t = S.Thread(session["id"], session)
        if goal:
            t.goal = goal
        self.threads[t.id] = t
        self.thread = t
        self.draft = {"model": None, "agent": None, "mode": None, "goal": None, "worktree": False}
        await self.scroller.show(t)
        self.strand(True)
        self.rail.reload()
        return t

    # ---- the bars -----------------------------------------------------------------------------

    def spin(self) -> None:
        self.tick += 1
        t = self.thread
        busy = bool(t and (t.busy or t.compacting or t.retry))
        if busy != self.flowing and self.main_screen.is_attached:
            self.flowing = busy
            self.composer.mark.flow(busy and self.setting("logoAnim", True), float(self.setting("animSpeed", 1) or 1))
            self.composer.line.run(busy)
            self.spine.run(busy)
            if not busy:
                self.live.rest()
                self.fit()
        if busy:
            self.draw_activity()

    def draw_activity(self) -> None:
        """What's happening, in the deck, with light going through the words."""
        t = self.thread
        if not t:
            return
        model = self.model_name(t.session.get("model")) or "the model"
        secs = S.fmt_dur(S.now_ms() - t.run_start) if t.run_start else ""
        if t.compacting:
            c = t.compacting if isinstance(t.compacting, dict) else {}
            label = f"Summarising {c.get('messages') or 'older'} messages to free up context"
            if (c.get("total") or 0) > 1:
                label += f" {min(c.get('done') or 0, c['total'])}/{c['total']}"
        elif t.retry:
            label = f"Provider error, retrying{(' (attempt ' + str(t.retry.get('attempt')) + ')') if t.retry.get('attempt') else ''}"
        elif t.phase == "sending":
            label = "Sending your message"
        elif t.phase == "delivered":
            label = f"Waiting for {model}"
        else:
            label = f"{model} is working"
        rate = f"  {round(t.live_tps)} tok/s" if t.live_tps else ""
        p = Palette.of(self)
        self.composer.right.update(Content.assemble(shimmer(label, p.ramp, self.tick / 26, p.text2), (f"  {secs}{rate}", "$afh-text3"), ("   Esc stops", "$afh-text3")))

    def draw_line(self, shell: bool = False) -> None:
        """The line over the deck: how much of the model's context this thread has used."""
        t = self.thread
        limit = (self.find_model(self.model_ref()) or {}).get("context")
        used = S.context_used(t.tokens) if t and t.tokens else 0
        pct = 100 * used / limit if limit else 0
        tone = "warn" if shell else "bad" if pct >= self.compact_at else ""
        self.composer.line.set_fill(pct / 100, tone)

    def draw_status(self) -> None:
        screen = self.main_screen
        if not screen.is_attached or screen.has_class("-boot") or not screen.query("#top-left"):  # not up yet, or closing
            return
        t = self.thread
        title = (t.session.get("title") if t else "") or ("New thread" if t else "")
        left: list[Any] = []
        if not self.rail.shown():
            left += [gradient("AFH"), "   "]
        if title:
            left += [(S.one_line(title, 80), "$foreground bold"), "   ", (S.base_name(self.dir), "$afh-text3")]
        else:
            left.append((self.pretty_dir(), "$afh-text3"))
        wt = ((t.session.get("metadata") or {}).get("afh") or {}).get("worktree") if t else None
        if wt:
            left += ["   ", (f"⎇ {str(wt.get('branch')).replace('afh/', '')}", "$primary")]
        screen.query_one("#top-left", Static).update(Content.assemble(*left))
        changed = len({x.get("file") for m in (t.messages if t else []) for p in m.get("content") or [] if p.get("type") == "tool" for x in S.tool_patches(p)})
        for tab in self.tabs:
            tab.show(changed if tab.command == "diff" else 0)

        c = self.composer
        ref = self.model_ref()
        variant = f" · {ref['variant']}" if ref and ref.get("variant") and ref["variant"] != "default" else ""
        mode = self.mode_id()
        c.agent_chip.show(self.agent_name(self.agent_id()), "$foreground")
        c.mode_chip.show(MODE_LABEL.get(mode, mode), {"full": "$warning"}.get(mode, "$afh-text2"))
        deck = 3 if c.has_class("-tight") else c.mark.cols + 4
        room = self.middle - deck - len(self.agent_name(self.agent_id())) - len(MODE_LABEL.get(mode, mode)) - 16
        c.model_chip.show(S.one_line((self.model_name(ref) or "No model") + variant, max(8, room)), "$foreground" if ref else "$error")
        self.draw_line()
        if t and (t.busy or t.compacting or t.retry):
            return
        bits: list[Any] = []
        limit = (self.find_model(ref) or {}).get("context")
        used = S.context_used(t.tokens) if t and t.tokens else 0
        if used:
            if limit:
                pct = round(100 * used / limit)
                colour = "$error" if pct >= self.compact_at else "$warning" if pct >= self.compact_at * 0.75 else "$afh-text2"
                bits += [(f"{pct}% context", colour), "   "]
            bits += [(f"{S.fmt_tokens(used + (t.tokens.get('output') or 0))} tokens", "$afh-text3"), "   "]
        if t and t.session.get("cost"):
            bits += [(S.fmt_cost(t.session.get("cost")), "$afh-text2"), "   "]
        if t and t.jobs and any(j.get("running") for j in t.jobs):
            bits += [(f"{sum(1 for j in t.jobs if j.get('running'))} running", "$success"), "   "]
        if self.update_notice:
            bits += [(self.update_notice, "$primary"), "   "]
        if not bits and self.middle >= 84:
            bits.append(("/ commands   ? help", "$afh-text3"))
        c.right.update(Content.assemble(*bits))


__all__ = ["AFH", "MODE_ORDER", "MODE_LABEL", "bar", "os", "time", "VerticalScroll", "Callable", "Row", "SPINNER"]
