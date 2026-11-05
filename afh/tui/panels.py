"""What sits around the conversation: the goal and to-do dock, and the live file panel."""
from __future__ import annotations

import json
import re
from typing import Any

from textual.containers import VerticalScroll
from textual.content import Content
from textual.widgets import Static

from . import state as S
from .widgets import TODO_MARK, bar

MAX_TODOS = 7


def all_done(todos: list[dict]) -> bool:
    return bool(todos) and all(x.get("status") in ("completed", "cancelled") for x in todos) and any(x.get("status") == "completed" for x in todos)


class Dock(Static):
    """A thread's goal and to-do list, above the message box."""

    DEFAULT_CSS = """
    Dock { height: auto; margin: 0 1; padding: 0 1; border: round $afh-border; display: none; color: $foreground; }
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
        return Content.assemble((f"{label}  ", "$warning bold" if st == "blocked" else "$primary bold"), S.one_line(goal.get("text"), 160), (auto, "$afh-text3"))

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
            lines.append(Content.styled(f"{TODO_MARK.get(st, '○')} {S.one_line(text, 200)}", style))
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
    LivePane { width: 45%; height: 1fr; border-left: solid $afh-border; padding: 0 1; display: none; background: $background; scrollbar-size-vertical: 1; }
    LivePane.-on { display: block; }
    LivePane #live-title { height: auto; color: $afh-text2; text-style: bold; }
    LivePane #live-body { height: auto; color: $foreground; }
    """
    can_focus = False
    AUTO_WIDTH = 120

    def __init__(self, ui: Any, **kw: Any):
        super().__init__(**kw)
        self.ui = ui
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
        self.toggle_class("-on")

    def wanted(self) -> bool:
        return self.ui.setting("liveFiles", True) and not self.closed_by_hand and self.ui.size.width >= self.AUTO_WIDTH

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
                if self.wanted():
                    self.add_class("-on")
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
