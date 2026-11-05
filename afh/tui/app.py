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
from ..cli import HOME, CliError
from . import state as S
from . import themes
from .actions import Actions
from .composer import Box, Composer, History
from .dialogs import Approval, Question
from .panels import Dock, LivePane
from .widgets import SPINNER, Row, Transcript, bar, gradient, logo

MODE_ORDER = ["ask", "full", "readonly"]
MODE_LABEL = {"ask": "ask first", "full": "full access", "readonly": "read only"}
COMPACT_AT = 80

CSS = """
Main { background: $background; }
SettingsScreen { background: $background; }
Toast { background: $panel; border-left: outer $primary; padding: 0 1; }
Toast.-error { border-left: outer $error; }
Toast.-warning { border-left: outer $warning; }
#header { height: 1; padding: 0 2; background: $background; }
#header-left { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
#header-right { width: auto; height: 1; color: $afh-text3; padding-left: 2; }
#rule { height: 1; color: $afh-border; padding: 0 1; }
#main { height: 1fr; }
#center { width: 1fr; height: 1fr; }
#activity { height: 1; padding: 0 3; color: $afh-text2; display: none; text-wrap: nowrap; text-overflow: ellipsis; }
#activity.-on { display: block; }
#status { height: 1; padding: 0 3; }
#status-left { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; color: $afh-text2; }
#status-right { width: auto; height: 1; color: $afh-text3; padding-left: 2; }
#bottom { height: auto; dock: bottom; }
"""


class Home(Vertical):
    """The start screen: the mark, where you are, recent threads and what to try."""

    DEFAULT_CSS = """
    Home { height: 100%; width: 100%; align: center middle; padding: 0 2; }
    Home > Static { width: 100%; height: auto; text-align: center; }
    Home #mark { margin: 0 0 1 0; }
    Home #facts { color: $afh-text2; text-align: center; width: 100%; }
    Home #recent-title { color: $afh-text3; margin: 1 0 0 0; }
    Home #tips { color: $afh-text3; margin: 1 0 0 0; text-align: center; width: 100%; }
    Home .recent { width: 100%; height: 1; text-wrap: nowrap; text-overflow: ellipsis; text-align: center; }
    Home .recent:hover { background: $boost; }
    """

    def __init__(self, ui: "AFH"):
        super().__init__(id="home")
        self.ui = ui

    def compose(self):
        ui = self.ui
        yield Static(logo(), id="mark")
        ref = ui.model_ref()
        model = ui.model_name(ref) or "no model yet"
        yield Static(Content.assemble((f"Agent Flow Harness {__version__}", "bold"), "\n", ui.pretty_dir(), "   ", (model, "$primary")), id="facts")
        if ui.recent:
            yield Static("Recent threads here", id="recent-title")
            for s in ui.recent[:4]:
                yield RecentRow(s)
        tips = "Type what you want done   / commands   @ files   ! shell   ? help"
        if not ref:
            tips = "No model yet. Type /connect to add one."
        yield Static(tips, id="tips")


class RecentRow(Row):
    def __init__(self, session: dict):
        super().__init__(Content.assemble(("  ", ""), S.one_line(session.get("title") or "New thread", 54), (f"  {S.ago((session.get('time') or {}).get('updated'))}", "$afh-text3")), classes="recent")
        self.session = session

    def on_click(self) -> None:
        self.app.open_thread(self.session["id"])


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

    def compose(self):
        ui = self.ui
        with Horizontal(id="header"):
            yield Static(id="header-left")
            yield Static(id="header-right")
        with Horizontal(id="main"):
            with Vertical(id="center"):
                yield ui.scroller
            yield ui.live
        with Vertical(id="bottom"):
            yield ui.dock
            yield Static(id="activity")
            yield ui.composer
            with Horizontal(id="status"):
                yield Static(id="status-left")
                yield Static(id="status-right")


class AFH(Actions, App):
    TITLE = "AFH"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS
    ALLOW_SELECT = True
    BINDINGS = [Binding("ctrl+c", "ctrl_c", show=False, priority=False), Binding("ctrl+q", "quit_now", show=False)]

    def __init__(self, client: Any, events: Any, directory: str, *, model: str | None = None, agent: str | None = None, mode: str | None = None,
                 thread: str | None = None, resume: bool = False, home: Path | None = None):
        super().__init__()
        self.client, self.events = client, events
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
        self.composer = Composer(self, self.history, id="composer")
        self.dock = Dock(self, id="dock")
        self.live = LivePane(self, id="live")
        self.main_screen = Main(self)
        self.asking: set[str] = set()
        self.perm_open = False
        self.tick = 0
        self.last_esc = 0.0
        self.last_ctrl_c = 0.0
        self.compact_at = COMPACT_AT
        self.notice = ""
        self.update_notice = ""

    # ---- talking to the backend ---------------------------------------------------------------

    async def api(self, method: str, path: str, body: Any = None, params: dict | None = None, timeout: float = 60) -> Any:
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
        self.set_interval(1 / 30, self.pump)
        self.set_interval(0.1, self.spin)
        self.begin()

    @work(exclusive=True, group="begin")
    async def begin(self) -> None:
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
        if wanted:
            await self.show_thread(wanted)
        else:
            await self.show_home()
        self.check_for_update()

    async def load_catalog(self) -> None:
        boot = await self.get("/api/bootstrap")
        self.boot = boot
        self.settings = boot.get("settings") or {}
        self.models = boot.get("models") or []
        self.agents = boot.get("agents") or []
        self.provider_names = boot.get("providerNames") or {}
        self.composer.send_key = (self.settings.get("ui") or {}).get("sendKey") or "enter"
        agent = self.settings.get("agent") or {}
        self.compact_at = agent.get("compactAt") or COMPACT_AT
        await self.load_commands()

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
        await self.scroller.mount(Home(self))
        self.dock.draw()
        self.draw_status()

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
            self.dock.draw()
            self.draw_status()
            self.pump_permissions()
        except CliError as err:
            self.fail(err)

    async def reload_thread(self) -> None:
        if self.thread:
            await self.show_thread(self.thread.id)

    # ---- events -------------------------------------------------------------------------------

    def pump(self) -> None:
        """Up to 400 events a tick, on the app's own thread."""
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
            self.run_worker(self.refresh_catalog(), group="catalog", exclusive=True)
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
            self.run_worker(self.reload_thread(), group="reload", exclusive=True)
            return
        if change.all:
            self.run_worker(self.scroller.add_new(), group="add", exclusive=False)
        if change.msg:
            self.scroller.touch(change.msg)
        if change.perm:
            self.pump_permissions()
        if change.status:
            self.dock.draw()
            self.draw_status()
        if kind in ("session.execution.succeeded", "session.execution.failed"):
            self.bell_when_done(kind)

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
        if text:
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
        return t

    # ---- the bars -----------------------------------------------------------------------------

    def spin(self) -> None:
        self.tick += 1
        t = self.thread
        if t and (t.busy or t.compacting or t.retry):
            self.draw_activity()
        elif self.is_running:
            self.hide_activity()

    def hide_activity(self) -> None:
        if self.screen is self.main_screen or self.main_screen.is_attached:
            try:
                self.main_screen.query_one("#activity").remove_class("-on")
            except Exception:
                pass

    def draw_activity(self) -> None:
        t = self.thread
        if not t:
            return
        spinner = SPINNER[self.tick % len(SPINNER)]
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
        row = self.main_screen.query_one("#activity", Static)
        row.add_class("-on")
        row.update(Content.assemble((spinner, "$primary"), f" {label}  ", (secs, "$afh-text3"), (rate, "$afh-text3"), ("   Esc stops", "$afh-text3")))

    def draw_status(self) -> None:
        if not self.main_screen.is_attached:
            return
        screen = self.main_screen
        t = self.thread
        title = (t.session.get("title") if t else "") or ("New thread" if t else "")
        left: list[Any] = [gradient("AFH"), "  "]
        if title:
            left += [(S.one_line(title, 80), "$foreground"), ("  ·  ", "$afh-text3"), (S.base_name(self.dir), "$afh-text2")]
        else:
            left.append((self.pretty_dir(), "$afh-text2"))
        wt = ((t.session.get("metadata") or {}).get("afh") or {}).get("worktree") if t else None
        if wt:
            left += [("  ", ""), (f"⎇ {str(wt.get('branch')).replace('afh/', '')}", "$primary")]
        screen.query_one("#header-left", Static).update(Content.assemble(*left))
        ref = self.model_ref()
        variant = f" · {ref['variant']}" if ref and ref.get("variant") and ref["variant"] != "default" else ""
        screen.query_one("#header-right", Static).update(Content.assemble((self.model_name(ref) or "no model", "$afh-text2"), variant))
        agent = self.agent_name(self.agent_id())
        mode = self.mode_id()
        bits: list[Any] = [(agent, "$primary bold"), "  ", (MODE_LABEL.get(mode, mode), {"full": "$warning", "readonly": "$afh-text2"}.get(mode, "$afh-text2"))]
        limit = (self.find_model(ref) or {}).get("context")
        if t and t.tokens:
            used = S.context_used(t.tokens)
            if limit:
                pct = round(100 * used / limit)
                colour = "$error" if pct >= self.compact_at else "$warning" if pct >= self.compact_at * 0.75 else "$afh-text2"
                bits += ["  ", (f"{pct}% context", colour)]
            bits += ["  ", (f"{S.fmt_tokens(used + (t.tokens.get('output') or 0))} tokens", "$afh-text3")]
        if t and t.session.get("cost"):
            bits += ["  ", (S.fmt_cost(t.session.get("cost")), "$afh-text2")]
        if t and t.jobs and any(j.get("running") for j in t.jobs):
            bits += ["  ", (f"{sum(1 for j in t.jobs if j.get('running'))} running", "$success")]
        if self.update_notice:
            bits += ["  ", (self.update_notice, "$primary")]
        screen.query_one("#status-left", Static).update(Content.assemble(*bits))
        wide = self.size.width >= 100
        screen.query_one("#status-right", Static).update("/ commands  @ files  ? help" if wide else "? help")


__all__ = ["AFH", "MODE_ORDER", "MODE_LABEL", "bar", "os", "time", "VerticalScroll", "Callable"]
