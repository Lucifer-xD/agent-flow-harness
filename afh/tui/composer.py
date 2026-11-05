"""The message box: multi-line input with the / menu, the @ file picker, history and paste chips."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from textual import events
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.message import Message
from textual.widgets import OptionList, Static, TextArea
from textual.widgets.option_list import Option

from .dialogs import fuzzy

HISTORY_MAX = 300
PASTE_LINES, PASTE_CHARS = 12, 1200  # longer than this and a paste becomes a chip
IGNORED = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target", ".idea", ".vscode"}
IMAGE = re.compile(r"\.(png|jpe?g|gif|webp)$", re.I)
CHIP = re.compile(r"\[Pasted text #(\d+)[^\]]*\]")


def list_files(directory: str, limit: int = 20000) -> list[str]:
    """The project's files: what git knows, else a walk that skips the usual build folders."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=directory, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.splitlines()[:limit]
    except (OSError, subprocess.SubprocessError):
        pass
    found: list[str] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in IGNORED and not d.startswith(".")]
        for f in files:
            found.append(os.path.relpath(os.path.join(root, f), directory).replace("\\", "/"))
            if len(found) >= limit:
                return found
    return found


class History:
    """What you've sent, newest last, kept between runs."""

    def __init__(self, path: Path):
        self.path = path
        self.items: list[str] = []
        try:
            self.items = [str(x) for x in json.loads(path.read_text(encoding="utf-8"))][-HISTORY_MAX:]
        except (OSError, ValueError, TypeError):
            pass
        self.at: int | None = None
        self.draft = ""

    def add(self, text: str) -> None:
        self.items = [x for x in self.items if x != text] + [text]
        self.items = self.items[-HISTORY_MAX:]
        self.at = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def older(self, current: str) -> str | None:
        if not self.items:
            return None
        if self.at is None:
            self.draft, self.at = current, len(self.items)
        if self.at == 0:
            return None
        self.at -= 1
        return self.items[self.at]

    def newer(self) -> str | None:
        if self.at is None:
            return None
        self.at += 1
        if self.at >= len(self.items):
            self.at = None
            return self.draft
        return self.items[self.at]


class Box(TextArea):
    """The text area itself. Keys it doesn't want go on up to the app."""

    DEFAULT_CSS = """
    Box { height: auto; max-height: 12; min-height: 1; border: none; padding: 0; background: transparent; width: 1fr; }
    Box:focus { border: none; }
    """

    class Sent(Message):
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    def __init__(self, composer: "Composer"):
        super().__init__("", soft_wrap=True, show_line_numbers=False, tab_behavior="focus", highlight_cursor_line=False, compact=True, placeholder="Ask anything   /  commands   @  files   !  shell")
        self.composer = composer

    async def _on_key(self, event: events.Key) -> None:
        c = self.composer
        key = event.key
        if c.menu_open():
            if key in ("up", "down"):
                return self.swallow(event, c.menu_move(-1 if key == "up" else 1))
            if key in ("tab", "enter"):
                return self.swallow(event, c.menu_pick(run=key == "enter"))
            if key == "escape":
                return self.swallow(event, c.menu_close())
        if key == "enter":
            if c.send_key == "ctrl-enter":
                return self.swallow(event, self.insert("\n"))
            return self.swallow(event, c.submit())
        if key in ("ctrl+enter", "ctrl+m") and c.send_key == "ctrl-enter":
            return self.swallow(event, c.submit())
        if key in ("ctrl+j", "alt+enter", "shift+enter", "ctrl+enter"):
            return self.swallow(event, self.insert("\n"))
        if key == "up" and self.cursor_location[0] == 0:
            older = c.history.older(self.text)
            if older is not None:
                return self.swallow(event, c.set_text(older))
        if key == "down" and self.cursor_location[0] == self.document.line_count - 1:
            newer = c.history.newer()
            if newer is not None:
                return self.swallow(event, c.set_text(newer))
        if key == "tab" or key == "shift+tab":
            return  # the app's keys: cycle agents and approvals
        await super()._on_key(event)

    def swallow(self, event: events.Key, _: Any = None) -> None:
        event.stop()
        event.prevent_default()

    async def _on_paste(self, event: events.Paste) -> None:
        text = event.text.replace("\r\n", "\n").replace("\r", "\n")
        path = text.strip().strip('"')
        if "\n" not in path and IMAGE.search(path) and os.path.isfile(path):
            self.composer.attach(path)
            event.stop()
            event.prevent_default()
            return
        if text.count("\n") >= PASTE_LINES or len(text) >= PASTE_CHARS:
            self.insert(self.composer.chip_for(text))
            event.stop()
            event.prevent_default()
            return
        await super()._on_paste(event)


class Composer(Vertical):
    """The rounded box at the bottom, with its menu above it."""

    DEFAULT_CSS = """
    Composer { height: auto; padding: 0 1; }
    Composer #menu { height: auto; max-height: 11; border: none; background: $surface; display: none; padding: 0 1; scrollbar-size-vertical: 1; }
    Composer #menu:focus { border: none; }
    Composer.-menu #menu { display: block; }
    Composer #chips { height: auto; color: $afh-text2; padding: 0 2; display: none; }
    Composer.-chips #chips { display: block; }
    Composer #frame { height: auto; border: round $afh-border2; padding: 0 1; background: $background; }
    Composer #frame:focus-within { border: round $primary; }
    Composer.-shell #frame { border: round $warning; }
    Composer #mark { width: 2; height: 1; color: $primary; text-style: bold; }
    Composer.-shell #mark { color: $warning; }
    """

    def __init__(self, ui: Any, history: History, **kw: Any):
        super().__init__(**kw)
        self.ui = ui
        self.history = history
        self.box = Box(self)
        self.menu = OptionList(id="menu")
        self.menu.can_focus = False
        self.chips = Static(id="chips")
        self.mark = Static("›", id="mark")
        self.send_key = "enter"
        self.pastes: dict[int, str] = {}
        self.files: list[str] = []
        self.items: list[dict] = []
        self.menu_kind = ""
        self.file_cache: tuple[str, list[str]] | None = None

    def compose(self):
        yield self.menu
        yield self.chips
        with Horizontal(id="frame"):
            yield self.mark
            yield self.box

    def on_mount(self) -> None:
        self.query_one("#frame").styles.height = "auto"
        self.box.focus()

    # text
    @property
    def text(self) -> str:
        return self.box.text

    def set_text(self, text: str) -> None:
        self.box.text = text
        self.box.move_cursor(self.box.document.end)

    def clear(self) -> None:
        self.box.text = ""
        self.pastes.clear()
        self.files.clear()
        self.history.at = None
        self.draw_chips()

    def expanded(self) -> str:
        """The text with paste chips swapped back for what was pasted."""
        return CHIP.sub(lambda m: self.pastes.get(int(m.group(1)), m.group(0)), self.box.text)

    def chip_for(self, text: str) -> str:
        n = max(self.pastes, default=0) + 1
        self.pastes[n] = text
        lines = text.count("\n") + 1
        return f"[Pasted text #{n}: {lines} lines]"

    def attach(self, path: str) -> None:
        if path not in self.files:
            self.files.append(path)
        self.draw_chips()

    def draw_chips(self) -> None:
        self.set_class(bool(self.files), "-chips")
        if self.files:
            self.chips.update(Content.assemble(*[(f"[{os.path.basename(f)}] ", "$primary") for f in self.files], ("Ctrl+X removes", "$afh-text3")))

    def submit(self) -> None:
        self.menu_close()
        self.post_message(Box.Sent(self.expanded()))

    # the / and @ menus
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        event.stop()
        text = self.box.text
        self.set_class(text.startswith("!"), "-shell")
        self.mark.update("!" if text.startswith("!") else "›")
        slash = re.fullmatch(r"/([a-z0-9_:-]*)", text, re.I)
        if slash:
            return self.fill_commands(slash.group(1).lower())
        at = self.at_word()
        if at is not None:
            return self.fill_files(at)
        self.menu_close()

    def at_word(self) -> str | None:
        row, col = self.box.cursor_location
        line = self.box.document.get_line(row)[:col]
        m = re.search(r"(?:^|\s)@([^\s@]*)$", line)
        return m.group(1) if m else None

    def fill_commands(self, q: str) -> None:
        ranked = []
        for c in self.ui.command_list():
            name, desc = c["name"], c.get("description") or ""
            if q and not (q in name or q in desc.lower()):
                continue
            ranked.append((not name.startswith(q), c))
        ranked.sort(key=lambda r: r[0])
        self.show_menu("slash", [c for _, c in ranked][:30], lambda c: Content.assemble((f"/{c['name']}", "$primary bold"), (f" {c.get('args')}", "$afh-text3") if c.get("args") else "", "  ", (c.get("description") or "", "$afh-text2")))

    def fill_files(self, q: str) -> None:
        directory = self.ui.directory()
        if not self.file_cache or self.file_cache[0] != directory:
            self.file_cache = (directory, list_files(directory))
        ranked = []
        for f in self.file_cache[1]:
            score = fuzzy(q, f)
            if score is not None:
                ranked.append((-score, len(f), f))
        ranked.sort()
        self.show_menu("file", [{"path": f} for _, _, f in ranked[:30]], lambda x: Content.styled(x["path"], "$foreground"))

    def show_menu(self, kind: str, items: list[dict], label: Any) -> None:
        self.items, self.menu_kind = items, kind
        self.menu.clear_options()
        if not items:
            return self.menu_close()
        self.menu.add_options([Option(label(x)) for x in items])
        self.menu.highlighted = 0
        self.add_class("-menu")

    def menu_open(self) -> bool:
        return self.has_class("-menu")

    def menu_move(self, delta: int) -> None:
        count = len(self.items)
        self.menu.highlighted = ((self.menu.highlighted or 0) + delta) % count

    def menu_close(self) -> None:
        self.remove_class("-menu")

    def menu_pick(self, run: bool) -> None:
        at = self.menu.highlighted or 0
        if at >= len(self.items):
            return self.menu_close()
        item = self.items[at]
        if self.menu_kind == "slash":
            self.menu_close()
            needs_text = str(item.get("args") or "").startswith("<") or "$ARGUMENTS" in str(item.get("prompt") or "")
            if run and not needs_text:
                self.set_text(f"/{item['name']}")
                self.submit()
            else:
                self.set_text(f"/{item['name']} ")
            return
        row, col = self.box.cursor_location
        line = self.box.document.get_line(row)
        start = line[:col].rfind("@")
        self.box.replace(f"@{item['path']} ", (row, start), (row, col))
        if IMAGE.search(item["path"]):
            self.attach(os.path.join(self.ui.directory(), item["path"]))
        self.menu_close()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.menu.highlighted = event.option_index
        self.menu_pick(run=True)
        self.box.focus()
