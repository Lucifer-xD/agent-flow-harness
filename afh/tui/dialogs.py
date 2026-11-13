"""Sheets: everything that asks or shows rises from the deck under a line of light. Nothing floats mid-screen."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from textual import events, on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Select, Static, Switch, TextArea
from textual.widgets.option_list import Option

from . import state as S
from .look import Flowline, keys
from .widgets import diff_content, plain_block

BASE_CSS = """
Dialog, Approval, Question { align: center bottom; background: $background 62%; }
#box { width: 100%; height: auto; max-height: 84%; background: $surface; padding: 0; }
#inner { height: auto; padding: 1 3 1 3; }
#title { text-style: bold; height: auto; padding: 0 0 1 0; }
#sub { color: $afh-text2; height: auto; padding: 0 0 1 0; }
#hint { height: auto; padding: 1 0 0 0; }
#box Input { border: none; height: 1; padding: 0 1; background: $panel; margin: 0 0 1 0; }
#box Input:focus { background: $boost; border: none; }
#box OptionList { border: none; height: auto; max-height: 16; background: transparent; padding: 0; scrollbar-size-vertical: 1; text-wrap: nowrap; text-overflow: ellipsis; }
#box OptionList:focus { border: none; background-tint: transparent; }
#box OptionList > .option-list--option-highlighted { background: $primary 18%; color: $foreground; text-style: none; }
#box Button { min-width: 10; height: 1; border: none; margin: 0 1 0 0; padding: 0 2; background: $panel; color: $foreground; }
#box Button:hover, #box Button:focus { background: $primary; color: $background; text-style: bold; }
#box Button.primary { background: $primary; color: $background; text-style: bold; }
#box Button.danger { background: $error; color: $background; text-style: bold; }
#buttons { height: auto; padding: 1 0 0 0; }
.field-label { color: $afh-text2; height: 1; }
.field-help { color: $afh-text3; height: auto; padding: 0 0 1 0; }
#box TextArea { height: 8; border: none; background: $panel; margin: 0 0 1 0; }
#box Switch { border: none; height: 1; width: 2; padding: 0; margin: 0 1 0 0; background: transparent; }
#box Switch:focus { background: $primary 18%; background-tint: transparent; }
#box Select { margin: 0 0 1 0; }
"""


class Toggle(Switch):
    """The same shape as the switches in Settings."""

    def render(self) -> Content:
        return Content.styled("━●", "$primary") if self.value else Content.styled("●━", "$afh-text3")


def edge(tone: str = "") -> Flowline:
    """The line of light along a sheet's top. `tone` is `warn` when it wants your attention."""
    line = Flowline(id="edge")
    line.fill, line.tone = 1.0, tone
    return line


class Dialog(ModalScreen):
    """A sheet over the conversation. Esc closes it."""

    DEFAULT_CSS = BASE_CSS
    BINDINGS = [Binding("escape", "cancel", "Close", show=False)]

    def action_cancel(self) -> None:
        self.dismiss(None)


@dataclass
class Item:
    label: str
    value: Any = None
    hint: str = ""
    group: str = ""
    checked: bool = False
    keywords: str = ""
    style: str = ""


def fuzzy(query: str, text: str) -> int | None:
    """A score when every letter of the query appears in order, or None. Higher is better."""
    if not query:
        return 0
    q, t = query.lower(), text.lower()
    at = t.find(q)
    if at >= 0:
        return 1000 - at - (len(t) - len(q)) // 8
    score, pos, run = 0, 0, 0
    for ch in q:
        found = t.find(ch, pos)
        if found < 0:
            return None
        run = run + 1 if found == pos else 0
        score += 2 + run * 3 - min(found - pos, 6)
        pos = found + 1
    return score


class Picker(Dialog):
    """A list you can type to filter. Enter picks; extra keys act on the highlighted item."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("down", "move(1)", show=False, priority=True),
        Binding("up", "move(-1)", show=False, priority=True),
        Binding("pagedown", "move(8)", show=False, priority=True),
        Binding("pageup", "move(-8)", show=False, priority=True),
        Binding("enter", "choose", show=False, priority=True),
    ]

    def __init__(self, title: str, items: Iterable[Item], *, placeholder: str = "Type to filter", sub: str = "", search: bool = True, hint: str = "",
                 actions: list[tuple[str, str, Callable[[Any], Any]]] | None = None, width: int = 76):
        super().__init__()
        self.title_text, self.items, self.placeholder, self.sub, self.search, self.hint = title, list(items), placeholder, sub, search, hint
        self.actions = actions or []
        self.box_width = width
        self.shown: list[Item | None] = []

    def compose(self):
        with Vertical(id="box"):
            yield edge()
            with Vertical(id="inner"):
                yield Static(self.title_text, id="title")
                if self.sub:
                    yield Static(self.sub, id="sub")
                if self.search:
                    yield Input(placeholder=self.placeholder, id="filter")
                yield OptionList(id="list")
                extra = "   ".join(f"{k.replace('ctrl+', 'Ctrl+').upper() if len(k) == 1 else k.replace('ctrl+', 'Ctrl+').title()} {label}" for k, label, _ in self.actions)
                yield Static(keys("   ".join(x for x in (self.hint or "↑↓ choose   Enter pick   Esc close", extra) if x)), id="hint")

    def on_mount(self) -> None:
        self.fill("")
        (self.query_one("#filter") if self.search else self.query_one("#list")).focus()

    def set_items(self, items: Iterable[Item]) -> None:
        self.items = list(items)
        self.fill(self.query_one("#filter", Input).value if self.search else "")

    def fill(self, query: str) -> None:
        ranked: list[tuple[int, int, Item]] = []
        for i, item in enumerate(self.items):
            score = fuzzy(query, f"{item.label} {item.hint} {item.keywords} {item.group}")
            if score is not None:
                ranked.append((score, i, item))
        if query:
            ranked.sort(key=lambda r: (-r[0], r[1]))
        else:
            ranked.sort(key=lambda r: r[1])
        options: list[Option] = []
        self.shown = []
        group = None
        first = None
        for _, _, item in ranked:
            if item.group != group and not query:
                group = item.group
                if group:
                    options.append(Option(Content.styled(group.upper(), "$afh-text3 bold"), disabled=True))
                    self.shown.append(None)
            mark = ("✓ ", "$primary bold") if item.checked else ("  ", "")
            label = Content.assemble(mark, (item.label, item.style), (f"   {item.hint}", "$afh-text3") if item.hint else "")
            if first is None or item.checked:
                first = len(options) if first is None or item.checked else first
            options.append(Option(label))
            self.shown.append(item)
        box = self.query_one("#list", OptionList)
        box.clear_options()
        box.add_options(options)
        if not options:
            box.add_option(Option(Content.styled("Nothing matches", "$afh-text3"), disabled=True))
            self.shown = [None]
        elif first is not None:
            box.highlighted = first

    @on(Input.Changed, "#filter")
    def filtered(self, event: Input.Changed) -> None:
        self.fill(event.value)

    def action_move(self, delta: int) -> None:
        box = self.query_one("#list", OptionList)
        if not self.shown:
            return
        at = box.highlighted if box.highlighted is not None else -1
        step = 1 if delta > 0 else -1
        for _ in range(abs(delta)):
            nxt = at + step
            while 0 <= nxt < len(self.shown) and self.shown[nxt] is None:
                nxt += step
            if not 0 <= nxt < len(self.shown):
                break
            at = nxt
        if at >= 0:
            box.highlighted = at

    def current(self) -> Item | None:
        at = self.query_one("#list", OptionList).highlighted
        return self.shown[at] if at is not None and at < len(self.shown) else None

    def action_choose(self) -> None:
        item = self.current()
        if item:
            self.dismiss(item.value)

    @on(OptionList.OptionSelected)
    def clicked(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_index < len(self.shown) and self.shown[event.option_index]:
            self.dismiss(self.shown[event.option_index].value)

    async def on_key(self, event: events.Key) -> None:
        for key, _, fn in self.actions:
            if event.key == key:
                event.stop()
                event.prevent_default()
                item = self.current()
                if item:
                    out = fn(item.value)
                    if hasattr(out, "__await__"):
                        await out
                return


class Confirm(Dialog):
    BINDINGS = [Binding("escape", "cancel", show=False), Binding("y", "yes", show=False), Binding("n", "cancel", show=False)]

    def __init__(self, title: str, body: str = "", confirm: str = "Yes", danger: bool = False):
        super().__init__()
        self.title_text, self.body, self.confirm, self.danger = title, body, confirm, danger

    def compose(self):
        with Vertical(id="box"):
            yield edge("bad" if self.danger else "")
            with Vertical(id="inner"):
                yield Static(self.title_text, id="title")
                if self.body:
                    yield Static(self.body, id="sub", markup=False)
                with Horizontal(id="buttons"):
                    yield Button(self.confirm, id="yes", classes="danger" if self.danger else "primary")
                    yield Button("Cancel", id="no")

    def on_mount(self) -> None:
        self.query_one("#yes").focus()

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class Prompt(Dialog):
    """Ask for one line, a hidden key, or a block of text."""

    BINDINGS = [Binding("escape", "cancel", show=False), Binding("ctrl+s", "save", show=False, priority=True)]

    def __init__(self, title: str, *, value: str = "", placeholder: str = "", password: bool = False, multiline: bool = False, sub: str = "", save: str = "Save", tall: bool = False):
        super().__init__()
        self.title_text, self.value, self.placeholder, self.password, self.multiline, self.sub, self.save_label, self.tall = title, value, placeholder, password, multiline, sub, save, tall

    def compose(self):
        with Vertical(id="box"):
            yield edge()
            with Vertical(id="inner"):
                yield Static(self.title_text, id="title")
                if self.sub:
                    yield Static(self.sub, id="sub", markup=False)
                if self.multiline:
                    area = TextArea(self.value, id="field", soft_wrap=True, show_line_numbers=False, tab_behavior="focus")
                    area.styles.height = 20 if self.tall else 10
                    yield area
                    yield Static(keys(f"Ctrl+S {self.save_label.lower()}   Esc cancel"), id="hint")
                else:
                    yield Input(self.value, placeholder=self.placeholder, password=self.password, id="field")
                    yield Static(keys(f"Enter {self.save_label.lower()}   Esc cancel"), id="hint")

    def on_mount(self) -> None:
        self.query_one("#field").focus()

    def action_save(self) -> None:
        field_ = self.query_one("#field")
        self.dismiss(field_.text if isinstance(field_, TextArea) else field_.value)

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text | password | area | select | switch | number
    value: Any = ""
    help: str = ""
    placeholder: str = ""
    options: list[tuple[str, Any]] = field(default_factory=list)


class Form(Dialog):
    """Several fields and a Save button. Tab moves between them."""

    BINDINGS = [Binding("escape", "cancel", show=False), Binding("ctrl+s", "save", show=False, priority=True)]

    def __init__(self, title: str, fields: list[Field], *, sub: str = "", save: str = "Save", width: int = 80):
        super().__init__()
        self.title_text, self.fields, self.sub, self.save_label, self.box_width = title, fields, sub, save, width

    def compose(self):
        with Vertical(id="box"):
            yield edge()
            with Vertical(id="inner"):
                yield Static(self.title_text, id="title")
                if self.sub:
                    yield Static(self.sub, id="sub", markup=False)
                with VerticalScroll(id="fields"):
                    for f in self.fields:
                        if f.kind == "switch":
                            with Horizontal(classes="switch-row"):
                                yield Toggle(bool(f.value), id=f"f-{f.key}")
                                yield Label(f" {f.label}")
                        else:
                            yield Label(f.label, classes="field-label")
                            if f.kind == "area":
                                yield TextArea(str(f.value or ""), id=f"f-{f.key}", soft_wrap=True, show_line_numbers=False, tab_behavior="focus")
                            elif f.kind == "select":
                                yield Select([(label, v) for label, v in f.options], value=f.value if any(v == f.value for _, v in f.options) else Select.BLANK, allow_blank=not f.options, id=f"f-{f.key}")
                            else:
                                yield Input(str(f.value if f.value is not None else ""), placeholder=f.placeholder, password=f.kind == "password", id=f"f-{f.key}",
                                            type="number" if f.kind == "number" else "text")
                        if f.help:
                            yield Static(f.help, classes="field-help", markup=False)
                with Horizontal(id="buttons"):
                    yield Button(self.save_label, id="save", classes="primary")
                    yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        fields = self.query_one("#fields")
        fields.styles.height = "auto"
        fields.styles.max_height = "64vh"
        for w in self.query(".switch-row"):
            w.styles.height = 1
            w.styles.margin = (0, 0, 1, 0)
        first = next(iter(self.query("#fields Input, #fields TextArea, #fields Select, #fields Switch")), None)
        if first:
            first.focus()

    def values(self) -> dict:
        out: dict = {}
        for f in self.fields:
            w = self.query_one(f"#f-{f.key}")
            if isinstance(w, TextArea):
                out[f.key] = w.text
            elif isinstance(w, Select):
                out[f.key] = None if w.value is Select.BLANK else w.value
            elif isinstance(w, Switch):
                out[f.key] = w.value
            else:
                out[f.key] = w.value
        return out

    def action_save(self) -> None:
        self.dismiss(self.values())

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.values() if event.button.id == "save" else None)

    @on(Input.Submitted)
    def submitted(self) -> None:
        self.dismiss(self.values())


class Viewer(Dialog):
    """Text to read: a diff, a report, a prompt."""

    BINDINGS = [Binding("escape", "cancel", show=False), Binding("q", "cancel", show=False), Binding("ctrl+y", "copy", show=False)]

    def __init__(self, title: str, body: Any = "", *, sub: str = "", hint: str = "", copy_text: str = "", actions: list[tuple[str, str, Callable[[], Any]]] | None = None):
        super().__init__()
        self.title_text, self.body, self.sub, self.hint, self.copy_text = title, body, sub, hint, copy_text
        self.actions = actions or []

    def compose(self):
        with Vertical(id="box"):
            yield edge()
            with Vertical(id="inner"):
                yield Static(self.title_text, id="title", markup=False)
                if self.sub:
                    yield Static(self.sub, id="sub", markup=False)
                with VerticalScroll(id="scroll"):
                    yield Static(self.body if isinstance(self.body, Content) else Content(str(self.body)), id="body")
                extra = "   ".join(f"{k.title() if len(k) > 1 else k.upper()} {label}" for k, label, _ in self.actions)
                base = self.hint or ("↑↓ scroll   Ctrl+Y copy   Esc close" if self.copy_text else "↑↓ scroll   Esc close")
                yield Static(keys("   ".join(x for x in (base, extra) if x)), id="hint")

    def on_mount(self) -> None:
        self.query_one("#box").styles.height = "86%"
        self.query_one("#inner").styles.height = "1fr"
        self.query_one("#scroll").styles.height = "1fr"
        self.query_one("#scroll").focus()

    def set_body(self, body: Any) -> None:
        self.query_one("#body", Static).update(body if isinstance(body, Content) else Content(str(body)))

    def action_copy(self) -> None:
        if self.copy_text:
            self.app.copy_to_clipboard(self.copy_text)
            self.app.notify("Copied")

    async def on_key(self, event: events.Key) -> None:
        for key, _, fn in self.actions:
            if event.key == key:
                event.stop()
                out = fn()
                if hasattr(out, "__await__"):
                    await out


class Approval(ModalScreen):
    """The agent wants to do something: shows the diff or command. Returns (decision, message)."""

    DEFAULT_CSS = BASE_CSS + """
    Approval #title { padding: 0; }
    Approval #sub { padding: 0; }
    Approval #scroll { height: auto; max-height: 24; margin: 1 0 0 0; background: $afh-code; }
    Approval #scroll Static { padding: 0 1; }
    Approval #scroll Static.-diff { padding: 0; text-wrap: nowrap; text-overflow: clip; }
    Approval Input { margin: 1 0 0 0; display: none; }
    Approval.-reason Input { display: block; }
    """
    BINDINGS = [
        Binding("y", "reply('once')", show=False), Binding("enter", "reply('once')", show=False),
        Binding("a", "reply('always')", show=False), Binding("n", "reason", show=False), Binding("escape", "reason", show=False),
        Binding("d", "dismiss_later", show=False),
    ]

    def __init__(self, request: dict, thread_title: str = ""):
        super().__init__()
        self.request = request
        self.thread_title = thread_title

    def compose(self):
        p = self.request
        meta = p.get("metadata") or {}
        action = p.get("action") or "tool"
        computer = action == "computer" and meta.get("kind") == "computer"
        if computer:
            apps = meta.get("apps") or [meta.get("app") or {}]
            names = ", ".join(a.get("name") or a.get("id") or "App" for a in apps)
            title = meta.get("title") or f"Let AFH use {names}?"
            sub = meta.get("reason") or f"AFH will use the mouse and keyboard in {names} while it works. Press Esc in any window to stop."
        elif action == "chrome" and meta.get("kind") == "chrome":
            title = meta.get("title") or f"Let AFH use {meta.get('site') or 'this site'} in your browser?"
            sub = meta.get("note") or "AFH will see this site the way you do, signed in as you, and can click and type there."
        elif action == "threads" and meta.get("kind") == "thread":
            t = meta.get("thread") or {}
            title = meta.get("title") or f"Let the model read the thread \"{t.get('title') or 'Untitled'}\"?"
            facts = " · ".join(x for x in (f"{t.get('messages')} messages" if t.get("messages") is not None else "", str(t.get("project") or "")) if x)
            sub = (meta.get("note") or "It gets the whole thread, word for word, from its first message.") + (f"\n{facts}" if facts else "")
        else:
            title = meta.get("title") or {"edit": "Allow file changes?", "shell": "Run this command?"}.get(action, f"Allow {action}?")
            sub = p.get("message") or ""
        with Vertical(id="box"):
            yield edge("warn")
            with Vertical(id="inner"):
                yield Static(title, id="title", markup=False)
                if sub or self.thread_title:
                    yield Static(sub or f"In {self.thread_title}", id="sub", markup=False)
                sections: list[Content] = []
                if meta.get("command"):
                    sections.append(Content.styled(str(meta["command"]), "$foreground"))
                files = meta.get("files") or []
                for f in files:
                    sections.append(Content.styled(f" {f.get('status') or 'change'} · {f.get('file')}", "bold"))
                    sections.append(diff_content(f.get("patch"), 120, path=f.get("file")))
                if not files and not meta.get("command") and p.get("resources") and meta.get("kind") != "thread":
                    sections.append(Content.styled("\n".join(str(r) for r in p["resources"]), "$afh-text2"))
                if sections:
                    with VerticalScroll(id="scroll"):
                        yield Static(Content("\n").join(sections), classes="-diff" if files else "")
                yield Input(placeholder="Tell the agent what to do instead (optional), Enter to send", id="why")
                always = "A always for this site" if action == "chrome" else "A always in this thread"
                yield Static(keys(f"Y allow once   {always}   N no   D decide later"), id="hint")

    def action_reply(self, decision: str) -> None:
        self.dismiss((decision, None))

    def action_reason(self) -> None:
        if self.has_class("-reason"):
            self.dismiss(("reject", self.query_one("#why", Input).value.strip() or None))
            return
        self.add_class("-reason")
        self.query_one("#why").focus()

    def action_dismiss_later(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def said_why(self, event: Input.Submitted) -> None:
        self.dismiss(("reject", event.value.strip() or None))


class Question(ModalScreen):
    """The agent paused to ask: one question at a time, options or your own answer."""

    DEFAULT_CSS = BASE_CSS + """
    Question #title { padding: 0; color: $afh-text3; }
    Question #qtext { height: auto; padding: 1 0; text-style: bold; }
    Question #box OptionList { max-height: 12; }
    Question Input { margin: 1 0 0 0; }
    """
    BINDINGS = [Binding("escape", "skip", show=False), Binding("ctrl+b", "back", show=False)]

    def __init__(self, request: dict):
        super().__init__()
        self.questions = (request.get("metadata") or {}).get("questions") or []
        self.answers: list[dict] = [{"selected": [], "other": ""} for _ in self.questions]
        self.at = 0

    def compose(self):
        with Vertical(id="box"):
            yield edge()
            with Vertical(id="inner"):
                yield Static("", id="title")
                yield Static("", id="qtext", markup=False)
                yield OptionList(id="opts")
                yield Input(placeholder="Or type your own answer", id="other")
                yield Static("", id="hint")

    def on_mount(self) -> None:
        self.draw()

    def draw(self) -> None:
        q = self.questions[self.at]
        a = self.answers[self.at]
        many = len(self.questions) > 1
        self.query_one("#title", Static).update(Content.assemble("The agent has a question", (f"   {self.at + 1} of {len(self.questions)}", "$afh-text3") if many else ""))
        self.query_one("#qtext", Static).update(q.get("question") or "")
        box = self.query_one("#opts", OptionList)
        at = box.highlighted
        box.clear_options()
        for o in q.get("options") or []:
            on_ = o.get("label") in a["selected"]
            box.add_option(Option(Content.assemble(("● " if on_ else "○ ", "$primary" if on_ else "$afh-text3"), o.get("label") or "", (f"   {o.get('description')}", "$afh-text3") if o.get("description") else "")))
        box.highlighted = at if at is not None and at < box.option_count else (0 if box.option_count else None)
        other = self.query_one("#other", Input)
        other.value = a["other"]
        last = self.at == len(self.questions) - 1
        pick = "Space pick   Enter pick" if q.get("multiple") else "Enter pick"
        self.query_one("#hint", Static).update(keys(f"{pick}   Tab your own answer   Ctrl+N {'submit' if last else 'next'}   {'Ctrl+B back   ' if self.at else ''}Esc skip"))
        (box if box.option_count else other).focus()

    def toggle(self, index: int) -> None:
        q = self.questions[self.at]
        a = self.answers[self.at]
        label = (q.get("options") or [])[index].get("label")
        if q.get("multiple"):
            a["selected"] = [x for x in a["selected"] if x != label] if label in a["selected"] else [*a["selected"], label]
            self.draw()
        else:
            a["selected"] = [label]
            self.advance()

    def advance(self) -> None:
        self.answers[self.at]["other"] = self.query_one("#other", Input).value
        if self.at < len(self.questions) - 1:
            self.at += 1
            self.draw()
        else:
            self.dismiss(("answer", self.answers))

    @on(OptionList.OptionSelected)
    def picked(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.toggle(event.option_index)

    @on(Input.Submitted)
    def typed(self) -> None:
        self.advance()

    async def on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+n":
            event.stop()
            self.advance()
        elif event.key == "space" and isinstance(self.focused, OptionList) and self.focused.highlighted is not None:
            event.stop()
            self.toggle(self.focused.highlighted)

    def action_skip(self) -> None:
        self.dismiss(("dismiss", None))

    def action_back(self) -> None:
        if self.at:
            self.at -= 1
            self.draw()


Runner = Callable[..., Awaitable[Any]]
__all__ = ["Dialog", "Item", "Picker", "Confirm", "Prompt", "Field", "Form", "Viewer", "Approval", "Question", "fuzzy", "S", "plain_block"]
