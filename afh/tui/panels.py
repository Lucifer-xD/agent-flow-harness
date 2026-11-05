"""What sits around the conversation: the rail of threads, the goal and to-do tray, and the live panel."""
from __future__ import annotations

import json
import re
from typing import Any

import time

from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from .. import __version__
from ..cli import CliError
from . import state as S
from .look import chip, unless_gone
from .widgets import TODO_MARK, Row, bar, gradient

MAX_TODOS = 7
LIVE_SHARE = 0.42
RAIL_WIDTH = 30
RAIL_FROM = 112  # columns before the rail opens by itself
MIDDLE_MIN = 72  # columns the conversation keeps: under this the rail gives way to the live panel


def all_done(todos: list[dict]) -> bool:
    return bool(todos) and all(x.get("status") in ("completed", "cancelled") for x in todos) and any(x.get("status") == "completed" for x in todos)


class Dock(Static):
    """A thread's goal and to-do list: a tray on the deck."""

    DEFAULT_CSS = """
    Dock { height: auto; padding: 0 2 0 4; background: $afh-side; display: none; color: $foreground; }
    Dock.-on { display: block; }
    """

    def __init__(self, ui: Any, **kw: Any):
        super().__init__(**kw)
        self.ui = ui
        self.folded = False
        self.forced = False

    def draw(self) -> None:
        t = self.ui.thread
        lines: list[Content] = []
        goal = t.goal if t else None
        if goal and goal.get("status") != "achieved":
            lines.append(self.goal_line(goal))
        todos = (t.todos if t else []) or []
        show_todos = bool(todos) and (not all_done(todos) or self.forced)
        if show_todos:
            lines += self.todo_lines(todos, bool(t and t.busy))
        self.set_class(bool(lines), "-on")
        if lines:
            self.update(Content("\n").join(lines))

    def goal_line(self, goal: dict) -> Content:
        st = goal.get("status") or "active"
        label = {"blocked": "Goal blocked", "paused": "Goal paused"}.get(st, "Goal")
        auto = ""
        if goal.get("autopilot") and st == "active":
            auto = "  autopilot paused" if goal.get("exhausted") else f"  autopilot {goal.get('turns') or 0}/{goal.get('maxTurns') or 3}"
        return Content.assemble(chip(label, "$warning" if st == "blocked" else "$primary"), "  ", S.one_line(goal.get("text"), 160), (auto, "$afh-text3"))

    def todo_lines(self, todos: list[dict], busy: bool) -> list[Content]:
        done = sum(1 for x in todos if x.get("status") == "completed")
        total = sum(1 for x in todos if x.get("status") != "cancelled")
        now = next((x for x in todos if x.get("status") == "in_progress"), None)
        head: list[Any] = [("To-do ", "bold"), (f"{done}/{total}  ", "$afh-text2"), bar(done / total if total else 0, 12)]
        if self.folded and now:
            head += ["  ", (S.one_line(now.get("activeForm") or now.get("content"), 80), "$primary")]
        lines = [Content.assemble(*head)]
        if self.folded:
            return lines
        # The list around what's being worked on, when it's too long to show all of it.
        start = 0
        if len(todos) > MAX_TODOS and now:
            start = max(0, min(todos.index(now) - 2, len(todos) - MAX_TODOS))
        for x in todos[start:start + MAX_TODOS]:
            st = x.get("status") or "pending"
            text = x.get("activeForm") if st == "in_progress" and x.get("activeForm") else x.get("content")
            style = {"completed": "$afh-text3", "cancelled": "$afh-text3 strike", "in_progress": "$primary" if busy else "$foreground"}.get(st, "$foreground")
            lines.append(Content.assemble((f"{TODO_MARK.get(st, '○')} ", {"completed": "$success", "in_progress": "$primary"}.get(st, "$afh-text3")), (S.one_line(text, 200), style)))
        if len(todos) > MAX_TODOS:
            lines.append(Content.styled(f"  {len(todos)} steps in all. /todo edits them.", "$afh-text3"))
        return lines

    def toggle(self) -> None:
        self.folded = not self.folded
        self.forced = True
        self.draw()


FIELD = re.compile(r'"(?:content|newString|new_string|new)"\s*:\s*"((?:[^"\\]|\\.)*)', re.S)
PATH = re.compile(r'"(?:path|filePath|file_path)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def partial_field(raw: str, pattern: re.Pattern) -> str:
    """A string field out of JSON that's still arriving."""
    m = pattern.search(raw)
    if not m:
        return ""
    text = m.group(1).rstrip("\\")
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t").replace("\\\\", "\\")


class LivePane(VerticalScroll):
    """The file being written or the command being run, as it happens. Ctrl+B shows or hides it."""

    DEFAULT_CSS = """
    LivePane { width: 42%; height: 1fr; padding: 1 2; display: none; background: $afh-side; scrollbar-size-vertical: 1; }
    LivePane.-on { display: block; }
    LivePane #live-title { height: auto; color: $afh-text2; text-style: bold; margin: 0 0 1 0; }
    LivePane #live-body { height: auto; color: $foreground; }
    """
    can_focus = False

    def __init__(self, ui: Any, **kw: Any):
        super().__init__(**kw)
        self.ui = ui
        self.auto = False  # opened by itself, so it closes by itself
        self.title_row = Static("Live", id="live-title")
        self.body = Static(Content.styled("Nothing yet. Files and commands show here as the agent works on them.", "$afh-text3"), id="live-body")
        self.tool: str | None = None
        self.kind = ""
        self.raw = ""
        self.names: dict[str, str] = {}
        self.closed_by_hand = False
        self.dirty = False

    def compose(self):
        yield self.title_row
        yield self.body

    def on_mount(self) -> None:
        self.anchor()
        self.set_interval(1 / 10, self.flush)

    def toggle(self) -> None:
        self.closed_by_hand = self.has_class("-on")
        self.auto = False
        self.toggle_class("-on")
        self.ui.fit()

    def wanted(self) -> bool:
        room = self.ui.size.width * (1 - LIVE_SHARE) - (RAIL_WIDTH if self.ui.rail.shown() else 0)
        return self.ui.setting("liveFiles", True) and not self.closed_by_hand and room >= MIDDLE_MIN

    def rest(self) -> None:
        if self.auto:
            self.auto = False
            self.remove_class("-on")

    def fit(self) -> None:
        if self.auto and not self.wanted():
            self.rest()

    def taken(self) -> int:
        return round(self.ui.size.width * LIVE_SHARE) if self.has_class("-on") else 0

    def feed(self, ev: dict, t: S.Thread) -> None:
        if t is not self.ui.thread:
            return
        kind, d = ev.get("type", ""), ev.get("data") or {}
        if kind == "session.tool.input.started":
            name = (d.get("name") or "").lower()
            self.names[d.get("id")] = name
            if name in ("write", "edit", "multiedit"):
                self.tool, self.kind, self.raw = d.get("id"), name, ""
                self.title_row.update("Writing…")
                self.body.update("")
                if self.wanted() and not self.has_class("-on"):
                    self.add_class("-on")
                    self.auto = True
                    self.ui.fit()
        elif kind == "session.tool.input.delta" and d.get("id") == self.tool:
            self.raw += d.get("delta") or ""
            self.dirty = True
        elif kind == "session.tool.called":
            given = d.get("input") or {}
            if self.names.get(d.get("id")) == "shell" and not given.get("background"):
                self.tool, self.kind, self.raw = d.get("id"), "run", ""
                self.title_row.update(f"$ {S.one_line(given.get('command'), 200)}")
                self.body.update("")
        elif kind == "session.tool.progress" and d.get("id") == self.tool and self.kind == "run":
            content = d.get("content") or []
            if content and content[0].get("text") is not None:
                self.raw = content[0]["text"]
                self.dirty = True
        elif kind in ("session.tool.success", "session.tool.failed") and d.get("id") == self.tool:
            self.flush()
            word = "Failed" if kind.endswith("failed") else "Done"
            path = partial_field(self.raw, PATH)
            self.title_row.update(f"{word}  {S.base_name(path)}" if path else word)

    def flush(self) -> None:
        if not self.dirty:
            return
        self.dirty = False
        if self.kind == "run":
            self.body.update(Content(self.raw[-20000:]))
            return
        path = partial_field(self.raw, PATH)
        if path:
            self.title_row.update(f"Writing {S.base_name(path)}")
        self.body.update(Content(partial_field(self.raw, FIELD)[-20000:]))


def age_group(ms: Any) -> str:
    """The app's headings: Today, Yesterday, This week, Older."""
    if not ms:
        return "OLDER"
    now = time.localtime()
    midnight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
    seconds = float(ms) / 1000
    return "TODAY" if seconds >= midnight else "YESTERDAY" if seconds >= midnight - 86400 else "THIS WEEK" if seconds >= midnight - 6 * 86400 else "OLDER"


class RailRow(Row):
    """Something in the rail that does something when clicked."""

    DEFAULT_CSS = """
    RailRow { padding: 0 2; }
    RailRow:hover { background: $boost; }
    RailRow.-here { background: $panel; }
    """

    def __init__(self, content: Any, fn: Any, **kw: Any):
        super().__init__(content, **kw)
        self.fn = fn

    def on_click(self) -> None:
        self.fn()


class Rail(Vertical):
    """Threads down the side, like the app. It opens on wide terminals; F3 shows or hides it."""

    DEFAULT_CSS = """
    Rail { width: 30; height: 1fr; background: $afh-side; display: none; }
    Rail.-on { display: block; }
    Rail #rail-brand { height: 1; padding: 0 2; margin: 1 0 1 0; }
    Rail #rail-list { height: 1fr; scrollbar-size-vertical: 1; background: transparent; }
    Rail .rail-head { height: 1; padding: 0 2; margin: 1 0 0 0; color: $afh-text3; text-style: bold; }
    Rail #rail-foot { height: 1; margin: 1 0; }
    """

    def __init__(self, ui: Any, **kw: Any):
        super().__init__(**kw)
        self.ui = ui
        self.closed_by_hand: bool | None = None
        self.sessions: list[dict] = []
        self.list = VerticalScroll(id="rail-list")
        self.list.can_focus = False
        self.brand = Static(id="rail-brand")
        self.drawn: Any = None

    def compose(self):
        yield self.brand
        yield RailRow(Content.assemble(("+ ", "$primary bold"), "New thread", ("  Ctrl N", "$afh-text3")), lambda: self.app.action_command("new"))
        yield RailRow(Content.assemble(("  ", ""), ("Find a thread", "$afh-text2"), ("  Ctrl K", "$afh-text3")), lambda: self.app.action_command("threads"))
        yield self.list
        yield RailRow(Content.assemble(("Settings", "$afh-text2"), ("  F2", "$afh-text3")), lambda: self.app.action_command("settings"), id="rail-foot")

    def on_mount(self) -> None:
        self.brand.update(Content.assemble(gradient("AFH"), (f"  {__version__}", "$afh-text3")))
        self.set_interval(20, self.reload)

    def shown(self) -> bool:
        return self.has_class("-on")

    def fit(self) -> None:
        """Wide enough, or asked for."""
        width = self.ui.size.width
        wanted = width >= RAIL_FROM and width - self.ui.live.taken() - RAIL_WIDTH >= MIDDLE_MIN if self.closed_by_hand is None else not self.closed_by_hand
        self.set_class(wanted, "-on")
        if wanted:
            self.reload()

    def toggle(self) -> None:
        self.closed_by_hand = self.shown()
        self.fit()

    def reload(self) -> None:
        if self.shown():
            self.ui.run_worker(self.load, group="rail", exclusive=True)

    async def load(self) -> None:
        try:
            self.sessions = await self.ui.get("/api/sessions", directory=self.ui.dir, limit=40) or []
        except CliError:
            return
        await self.draw()

    async def draw(self) -> None:
        here = self.ui.thread.id if self.ui.thread else None
        busy = {t.id for t in self.ui.threads.values() if t.busy}
        now = (here, tuple(busy), tuple((s.get("id"), s.get("title"), (s.get("time") or {}).get("updated")) for s in self.sessions))
        if now == self.drawn:
            return
        self.drawn = now
        rows: list[Any] = []
        group = None
        for s in self.sessions:
            when = (s.get("time") or {}).get("updated")
            heading = age_group(when)
            if heading != group:
                group = heading
                rows.append(Static(heading, classes="rail-head"))
            sid = s["id"]
            mark = ("● ", "$primary") if sid in busy else ("  ", "")
            title = S.one_line(s.get("title") or "New thread", 40)
            row = RailRow(Content.assemble(mark, (title, "$foreground" if sid == here else "$afh-text2")), lambda sid=sid: self.ui.open_thread(sid))
            row.set_class(sid == here, "-here")
            rows.append(row)
        await self.list.remove_children()
        if rows:
            with unless_gone(self.list):
                await self.list.mount_all(rows)
