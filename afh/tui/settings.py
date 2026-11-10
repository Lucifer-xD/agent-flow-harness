"""Settings: the same sections as the desktop app, on the same API, as lists you move through."""
from __future__ import annotations

import asyncio
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .. import __version__
from ..cli import CliError
from . import state as S
from . import themes
from .actions import SIGN_INS, ThemePicker
from .dialogs import Confirm, Field, Form, Item, Picker, Prompt, Viewer
from .look import keys
from .widgets import bar, gradient

SPEEDS = (0.5, 1.0, 1.5, 2.0)
TABS = [("general", "General"), ("appearance", "Appearance"), ("personalization", "Personalization"), ("agent", "Agent"), ("delegation", "Delegation"), ("models", "Models & providers"),
        ("usage", "Usage & cost"), ("skills", "Skills"), ("mcp", "MCP servers"), ("prompts", "Prompts & agents"), ("commands", "Commands"), ("hooks", "Hooks"), ("schedules", "Schedules"),
        ("github", "GitHub"), ("developer", "Developer"), ("remote", "Remote control"), ("bug", "Report a bug"), ("about", "About")]
HOOK_EVENTS = [("Before a tool runs", "pre_tool"), ("After a tool ran", "post_tool"), ("When a run ends", "stop")]
WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
RECOMMENDED_MCP = [
    ("chrome-devtools", "Control and inspect Chrome", ["npx", "-y", "chrome-devtools-mcp@latest"]), ("filesystem", "Read and write files outside the project", ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]),
    ("github", "Issues, pull requests, code search", ["npx", "-y", "@modelcontextprotocol/server-github"]), ("playwright", "Drive a browser", ["npx", "-y", "@playwright/mcp@latest"]),
    ("context7", "Up-to-date library docs", ["npx", "-y", "@upstash/context7-mcp"]),
]


@dataclass
class R:
    """One line of a settings section."""

    kind: str  # head | note | toggle | choice | text | area | secret | number | button | item
    label: str
    value: Any = None
    hint: str = ""
    run: Callable[..., Awaitable[Any]] | None = None
    options: list[tuple[str, Any]] = field(default_factory=list)
    danger: bool = False


def head(text: str) -> R:
    return R("head", text)


def note(text: str) -> R:
    return R("note", text)


def qr_lines(text: str) -> str:
    """A QR code in half blocks: two rows of modules per line of text."""
    try:
        import qrcode
    except ImportError:
        return ""
    code = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    code.add_data(text)
    code.make(fit=True)
    m = code.get_matrix()
    lines = []
    for y in range(0, len(m), 2):
        top, low = m[y], m[y + 1] if y + 1 < len(m) else [False] * len(m[y])
        lines.append("".join(" " if a and b else "▄" if a else "▀" if b else "█" for a, b in zip(top, low)))
    return "\n".join(lines)


def describe_schedule(j: dict) -> str:
    every = j.get("every") or "daily"
    at = j.get("time") or "09:00"
    if every == "interval":
        return f"every {j.get('minutes') or 60} minutes"
    if every == "hourly":
        return "every hour"
    if every == "weekdays":
        return f"Monday to Friday at {at}"
    if every == "weekly":
        return f"{WEEK[int(j.get('weekday') or 0) % 7]}s at {at}"
    return f"every day at {at}"


class SettingsScreen(Screen):
    """Sections on the left, their lines on the right. Tab moves between the two."""

    DEFAULT_CSS = """
    SettingsScreen { background: $background; }
    SettingsScreen #panes { height: 1fr; }
    SettingsScreen #side { width: 30; height: 1fr; background: $afh-side; }
    SettingsScreen #s-top { height: 1; padding: 0 2; margin: 1 0 1 0; }
    SettingsScreen #nav { height: 1fr; border: none; background: transparent; padding: 0; scrollbar-size-vertical: 1; }
    SettingsScreen #nav:focus { background-tint: transparent; }
    SettingsScreen #nav > .option-list--option { padding: 0 2; color: $afh-text2; }
    SettingsScreen #nav > .option-list--option-highlighted { padding: 0 2; background: $panel; color: $foreground; text-style: bold; }
    SettingsScreen #nav:focus > .option-list--option-highlighted { background: $primary 18%; }
    SettingsScreen #right { width: 1fr; height: 1fr; padding: 1 3 0 3; }
    SettingsScreen #heading { height: auto; text-style: bold; padding: 0 0 1 0; }
    SettingsScreen #rows { height: 1fr; border: none; background: transparent; scrollbar-size-vertical: 1; }
    SettingsScreen #rows:focus { background-tint: transparent; }
    SettingsScreen #rows > .option-list--option-highlighted { background: $primary 14%; color: $foreground; text-style: none; }
    SettingsScreen #keys { height: 1; margin: 1 0 1 0; }
    """
    BINDINGS = [Binding("escape", "leave", show=False), Binding("tab", "swap", show=False, priority=True), Binding("shift+tab", "swap", show=False, priority=True),
                Binding("left", "to_nav", show=False), Binding("right", "to_rows", show=False)]

    def __init__(self, ui: Any, tab: str = "general"):
        super().__init__()
        self.ui = ui
        self.tab = tab if tab in dict(TABS) else "general"
        self.rows: list[R] = []
        self.busy = False

    def compose(self):
        with Horizontal(id="panes"):
            with Vertical(id="side"):
                yield Static(gradient("Settings"), id="s-top")
                yield OptionList(*[Option(label, id=tid) for tid, label in TABS], id="nav")
            with Vertical(id="right"):
                yield Static("", id="heading")
                yield OptionList(id="rows")
                yield Static(keys("↑↓ move   Enter change   Tab sections   Esc back"), id="keys")

    def on_mount(self) -> None:
        nav = self.query_one("#nav", OptionList)
        nav.highlighted = [t for t, _ in TABS].index(self.tab)
        self.query_one("#rows").focus()
        self.load()

    def action_leave(self) -> None:
        self.dismiss(None)

    def action_swap(self) -> None:
        nav, rows = self.query_one("#nav"), self.query_one("#rows")
        (rows if nav.has_focus else nav).focus()

    def action_to_nav(self) -> None:
        self.query_one("#nav").focus()

    def action_to_rows(self) -> None:
        self.query_one("#rows").focus()

    @on(OptionList.OptionHighlighted, "#nav")
    def section(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id != self.tab:
            self.tab = event.option.id
            self.load()

    @on(OptionList.OptionSelected, "#nav")
    def enter_section(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.query_one("#rows").focus()

    @on(OptionList.OptionSelected, "#rows")
    def chosen(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_index < len(self.rows):
            self.ui.run_worker(self.activate(self.rows[event.option_index]), group="settings-row", exclusive=False)

    def load(self) -> None:
        self.ui.run_worker(self.draw(), group="settings-draw", exclusive=True)

    async def draw(self, keep: int | None = None) -> None:
        tab = self.tab
        self.query_one("#heading", Static).update(dict(TABS)[tab])
        try:
            rows = await getattr(Panes(self), f"pane_{tab}")()
        except CliError as err:
            rows = [note(f"Couldn't load this section: {err}")]
        if tab != self.tab:
            return
        self.rows = rows
        box = self.query_one("#rows", OptionList)
        box.clear_options()
        box.add_options([self.option(r) for r in rows])
        first = next((i for i, r in enumerate(rows) if r.kind not in ("head", "note")), None)
        box.highlighted = keep if keep is not None and keep < len(rows) and rows[keep].kind not in ("head", "note") else first

    def option(self, r: R) -> Option:
        if r.kind == "head":
            return Option(Content.assemble("\n", (r.label.upper(), "$afh-text3 bold")), disabled=True)
        if r.kind == "note":
            return Option(Content.styled(r.label, "$afh-text2"), disabled=True)
        hint = Content.assemble("\n    ", (r.hint, "$afh-text3")) if r.hint else Content("")
        style = "$error" if r.danger else ""
        if r.kind == "toggle":
            return Option(Content.assemble(("━● " if r.value else "●━ ", "$primary" if r.value else "$afh-text3"), " ", r.label, hint))
        if r.kind in ("button", "item"):
            right = (f"  {r.value}", "$afh-text2") if r.value not in (None, "") else ""
            return Option(Content.assemble(("›   " if r.kind == "button" else "    ", "$primary"), (r.label, style), right, hint))
        value = r.value
        if r.kind == "choice":
            value = next((a for a, b in r.options if b == r.value), r.value)
        if r.kind == "secret":
            value = "set" if r.value else "not set"
        shown = S.one_line(str(value if value not in (None, "") else "not set"), 60)
        return Option(Content.assemble("    ", r.label.ljust(30), ("  ", ""), (shown, "$primary" if value not in (None, "") else "$afh-text3"), hint))

    async def activate(self, r: R) -> None:
        if self.busy or r.run is None:
            return
        self.busy = True
        at = self.query_one("#rows", OptionList).highlighted
        ui = self.ui
        try:
            if r.kind == "toggle":
                await r.run(not r.value)
            elif r.kind == "choice":
                picked = await ui.push_screen_wait(Picker(r.label, [Item(a, (b,), checked=b == r.value) for a, b in r.options], search=len(r.options) > 8))
                if picked is not None:
                    await r.run(picked[0])
            elif r.kind in ("text", "secret"):
                got = await ui.push_screen_wait(Prompt(r.label, value="" if r.kind == "secret" else str(r.value or ""), password=r.kind == "secret", sub=r.hint))
                if got is not None:
                    await r.run(got.strip())
            elif r.kind == "area":
                got = await ui.push_screen_wait(Prompt(r.label, value=str(r.value or ""), multiline=True, tall=True, sub=r.hint))
                if got is not None:
                    await r.run(got)
            elif r.kind == "number":
                got = await ui.push_screen_wait(Prompt(r.label, value=str(r.value if r.value is not None else ""), sub=r.hint))
                if got is not None:
                    try:
                        await r.run(float(got) if "." in got else int(got or 0))
                    except ValueError:
                        ui.fail("That isn't a number")
            else:
                await r.run()
        except CliError as err:
            ui.fail(err)
        finally:
            self.busy = False
        if self.is_attached and self.is_current:
            await self.draw(at)


class Panes:
    """One method per section. Each returns its lines; changing one saves at once."""

    def __init__(self, screen: SettingsScreen):
        self.screen = screen
        self.ui = screen.ui
        self.s = screen.ui.settings

    # helpers

    async def wait(self, dialog: Any) -> Any:
        return await self.ui.push_screen_wait(dialog)

    def saver(self, group: str | None, key: str) -> Callable[[Any], Awaitable[None]]:
        async def save(value: Any) -> None:
            await self.ui.save_settings({group: {key: value}} if group else {key: value})

        return save

    def toggle(self, group: str, key: str, label: str, hint: str = "", default: bool = True) -> R:
        value = (self.s.get(group) or {}).get(key)
        return R("toggle", label, default if value is None else value, hint, self.saver(group, key))

    def agents(self) -> list[tuple[str, str]]:
        return [(a.get("name") or a["id"], a["id"]) for a in self.ui.main_agents()]

    # general

    async def pane_general(self) -> list[R]:
        u = self.s.get("ui") or {}
        return [
            head("Starting a thread"),
            R("choice", "Default mode", self.s.get("defaultAgent") or "build", "", self.saver(None, "defaultAgent"), self.agents()),
            R("choice", "Default approvals", self.s.get("defaultMode") or "ask", "", self.saver(None, "defaultMode"), [("Ask first", "ask"), ("Full access", "full"), ("Read only", "readonly")]),
            self.toggle("ui", "reopenLast", "Reopen the last thread when the desktop app starts"),
            self.toggle("agent", "resumeOnRestart", "Resume runs a restart interrupted", "When AFH starts again, it continues what it was doing"),
            head("Conversation"),
            self.toggle("ui", "showReasoning", "Show the model's thinking"),
            self.toggle("ui", "showMeta", "Show model, tokens and time under replies"),
            R("choice", "Send key", u.get("sendKey") or "enter", "Ctrl+J always adds a new line", self.send_key, [("Enter", "enter"), ("Ctrl+Enter", "ctrl-enter")]),
            self.toggle("ui", "confirmDelete", "Ask before deleting a thread"),
            self.toggle("ui", "liveFiles", "Open the live panel while files are written", "When the terminal has room for it; Ctrl+B opens it anywhere"),
            head("Alerts"),
            self.toggle("ui", "sounds", "Ring the terminal bell when a run ends"),
            self.toggle("ui", "notify", "Desktop notifications from the app"),
            head("Language"),
            note("The conversation follows whatever language you write in. The terminal app's own text is English; Arabic and right-to-left are in the desktop app."),
        ]

    async def send_key(self, value: str) -> None:
        await self.ui.save_settings({"ui": {"sendKey": value}})
        self.ui.composer.send_key = value

    # appearance

    async def pane_appearance(self) -> list[R]:
        u = self.s.get("ui") or {}
        current = self.ui.theme.removeprefix("afh-")
        name = themes.PRESETS[current][0] if current in themes.PRESETS else "Custom"
        return [
            head("Theme"), R("button", "Pick a theme", name, f"{len(themes.PRESETS)} themes, the same ones as the desktop app", self.pick_theme),
            R("choice", "Dark or light", "dark" if current in themes.PRESETS and themes.PRESETS[current][2] else "light", "Switches to your favourite theme of that kind", self.dark_light, [("Dark", "dark"), ("Light", "light")]),
            head("Your own colors"),
            R("text", "Background", u.get("bg") or "", "A color like #101014", self.custom("bg")), R("text", "Text", u.get("text") or "", "", self.custom("text")), R("text", "Accent", u.get("accent") or "", "", self.custom("accent")),
            head("Motion"), self.toggle("ui", "logoAnim", "Logo flows while a model works"),
            R("choice", "Animation speed", str(min(SPEEDS, key=lambda v: abs(v - float(u.get("animSpeed") or 1)))), "", self.anim_speed, [(f"{v:g}×", str(v)) for v in SPEEDS]),
            head("Everything else"), note("Font, font size and window transparency come from your terminal. Corners, glass and custom CSS only exist in the desktop app; your choices there are kept."),
        ]

    async def anim_speed(self, value: str) -> None:
        await self.ui.save_settings({"ui": {"animSpeed": float(value)}})

    async def pick_theme(self) -> None:
        await self.ui.cmd_theme("")

    async def dark_light(self, value: str) -> None:
        u = self.s.get("ui") or {}
        tid = u.get("darkPreset" if value == "dark" else "lightPreset") or ("sunset" if value == "dark" else "paper")
        await self.ui.use_theme(tid if tid in themes.PRESETS else themes.FALLBACK)

    def custom(self, key: str) -> Callable[[str], Awaitable[None]]:
        async def save(value: str) -> None:
            if value and not (value.startswith("#") and len(value) in (4, 7)):
                self.ui.fail("Use a color like #101014")
                return
            await self.ui.save_settings({"tui": {"theme": "custom"}, "ui": {key: value, "preset": "custom"}})
            self.ui.apply_look()

        return save

    # personalization

    async def pane_personalization(self) -> list[R]:
        p = self.s.get("personalization") or {}

        def text(key: str, label: str, hint: str = "", kind: str = "text") -> R:
            return R(kind, label, p.get(key) or "", hint, self.saver("personalization", key))

        return [
            note("Added to every thread's system prompt, so the agent knows who it works with."),
            self.toggle("personalization", "enabled", "Use this in every thread"),
            text("name", "Your name"), text("role", "What you do"), text("about", "About you", "", "area"),
            R("choice", "Response style", p.get("style") or "balanced", "", self.saver("personalization", "style"), [("Concise", "concise"), ("Balanced", "balanced"), ("Detailed", "detailed")]),
            text("tone", "Tone"), text("instructions", "Custom instructions", "", "area"),
        ]

    # agent

    async def pane_agent(self) -> list[R]:
        a = self.s.get("agent") or {}
        g = self.s.get("goals") or {}
        b = self.s.get("browser") or {}
        d = self.s.get("diagnostics") or {}
        v = self.s.get("voice") or {}
        c = self.s.get("computer") or {}
        ch = self.s.get("chrome") or {}
        rows = [
            head("The agent loop"),
            R("number", "Steps per run", a.get("maxSteps") or 200, "10 to 1000", self.max_steps),
            R("choice", "Compact at", a.get("compactAt") or 80, "How full the context gets before older messages are summarised", self.saver("agent", "compactAt"), [("40% of the window", 40), ("60% of the window", 60), ("80% of the window", 80)]),
            self.toggle("agent", "todoNudge", "Send it back once if the to-do list isn't finished"),
            head("Goals"),
            self.toggle("goals", "auto", "Treat every first message as a goal", default=False), self.toggle("goals", "autopilot", "Autopilot on new goals"),
            R("number", "Continuations per message", g.get("maxTurns") or 3, "", self.saver("goals", "maxTurns")),
            head("Error checks after edits"),
            self.toggle("diagnostics", "enabled", "Check files after the agent edits them"), self.toggle("diagnostics", "typescript", "TypeScript"), self.toggle("diagnostics", "ruff", "Ruff (Python)"),
            R("button", "Your own checks", f"{len(d.get('commands') or [])} set", "", self.checks),
            head("Browser tool"),
            self.toggle("browser", "enabled", "Let the agent use a browser"),
            R("choice", "Where it opens", b.get("where") or "panel", "The panel is part of the desktop app; here it always opens as a window", self.saver("browser", "where"), [("In the app's panel", "panel"), ("Its own window", "external")]),
            self.toggle("browser", "visible", "Show its window", default=False), R("text", "Browser path", b.get("path") or "", "Empty finds Chrome or Edge", self.saver("browser", "path")),
            head("Your Chrome"),
            note("Your own browser, with your sign-ins and tabs. It asks you to click Allow each time AFH connects."),
            self.toggle("chrome", "enabled", "Let the agent use your own browser", "AFH asks you about each new site"),
            R("choice", "Which browser", ch.get("browser") or "auto", "", self.saver("chrome", "browser"), [("The first one that is ready", "auto"), ("Chrome", "chrome"), ("Edge", "edge"), ("Brave", "brave")]),
            self.toggle("chrome", "background", "Open its tabs in the background", default=False),
            R("button", "Connect to your browser", "", "Shows the steps if your browser isn't ready yet", self.chrome_connect) if ch.get("enabled", True) is not False else None,
            R("button", "Sites it may use", f"{len(ch.get('allowed') or [])} allowed", "", self.chrome_sites) if ch.get("enabled", True) is not False else None,
            head("Computer use"),
            self.toggle("computer", "enabled", "Let the agent use your mouse and keyboard", "It asks before each app, and Esc stops it", default=False),
            self.toggle("computer", "browserControl", "Let it control your browser too", default=False), self.toggle("computer", "hideWindow", "Hide AFH while it works", default=False), self.toggle("computer", "effects", "Show its cursor effects"),
            R("button", "Apps it may use", "", "", self.apps) if c.get("enabled") else None,
            head("Voice"),
            note("The mic is in the desktop app and phone apps. These settings apply there."),
            R("text", "Transcription provider", v.get("provider") or "", "Empty uses Groq, then OpenAI", self.saver("voice", "provider")),
            R("text", "Transcription model", v.get("model") or "", "", self.saver("voice", "model")), R("text", "Spoken language", v.get("language") or "", "Like en or ar", self.saver("voice", "language")),
        ]
        return [r for r in rows if r]

    async def max_steps(self, value: int) -> None:
        await self.ui.save_settings({"agent": {"maxSteps": max(10, min(1000, int(value)))}})

    async def checks(self) -> None:
        commands = list((self.s.get("diagnostics") or {}).get("commands") or [])
        items = [Item(c.get("name") or c.get("command"), i, f"{c.get('glob') or ''} · {'on' if c.get('enabled', True) else 'off'}") for i, c in enumerate(commands)]
        items.append(Item("Add a check…", "add"))
        picked = await self.wait(Picker("Your own checks", items, search=False, sub="A command AFH runs after an edit to files that match. A failure goes back to the agent."))
        if picked is None:
            return
        now = commands[picked] if isinstance(picked, int) else {}
        out = await self.wait(Form("Check", [Field("name", "Name", value=now.get("name") or ""), Field("glob", "Files", value=now.get("glob") or "", placeholder="*.go"), Field("command", "Command", value=now.get("command") or "", placeholder="go vet ./..."),
                                             Field("enabled", "On", "switch", now.get("enabled", True)), Field("remove", "Remove this check", "switch", False)]))
        if not out:
            return
        keep = out.pop("remove")
        if isinstance(picked, int):
            commands[picked:picked + 1] = [] if keep else [{**now, **out}]
        elif not keep:
            commands.append(out)
        await self.ui.save_settings({"diagnostics": {"commands": commands}})

    async def apps(self) -> None:
        data = await self.ui.get("/api/computer/apps")
        if not data.get("supported"):
            self.ui.say("Computer use isn't available on this system", 4)
            return
        allowed = data.get("allowed") or []
        ids = {a.get("id") for a in allowed}
        items = [Item(a.get("name") or a.get("id"), ("forget", a), "allowed", "Allowed", True) for a in allowed]
        items += [Item(a.get("name") or a.get("id"), ("allow", a), "", "Running now") for a in data.get("running") or [] if a.get("id") not in ids]
        picked = await self.wait(Picker("Apps it may use", items, sub="Enter allows or forgets an app."))
        if picked:
            action, app = picked
            await self.ui.api("POST", "/api/computer/allow" if action == "allow" else "/api/computer/forget", {"app": app} if action == "allow" else {"id": app.get("id")})

    async def chrome_connect(self) -> None:
        data = await self.ui.get("/api/chrome")
        ready = next((b for b in data.get("browsers") or [] if b.get("ready")), None)
        if data.get("connected"):
            self.ui.say(f"Already connected to {data.get('connectedTo')}", 4)
        elif ready:
            self.ui.say(f"Switch to {ready['name']} and click Allow", 8)
            await self.ui.api("POST", "/api/chrome/connect", {}, timeout=150)
            self.ui.say(f"Connected to {ready['name']}", 4)
        elif any(b.get("installed") for b in data.get("browsers") or []):
            name = next(b["name"] for b in data["browsers"] if b.get("installed"))
            await self.ui.api("POST", "/api/chrome/setup", {})
            self.ui.say(f"In {name}: tick “Allow remote debugging for this browser instance” on the page that opened ({data.get('setupPage')}), then connect again", 12)
        else:
            self.ui.say("No Chrome, Edge or Brave was found on this computer", 5)

    async def chrome_sites(self) -> None:
        data = await self.ui.get("/api/chrome")
        allowed = data.get("allowed") or []
        if not allowed:
            self.ui.say("No sites yet. AFH asks you when the agent first needs one", 5)
            return
        picked = await self.wait(Picker("Sites it may use", [Item(site, site, "allowed", "Allowed", True) for site in allowed], sub="Enter forgets a site."))
        if picked:
            await self.ui.api("POST", "/api/chrome/sites", {"forget": picked})

    # delegation

    async def pane_delegation(self) -> list[R]:
        data = await self.ui.get("/api/delegation")
        delegates = data.get("delegates") or []

        async def save(**patch: Any) -> None:
            await self.ui.api("PUT", "/api/delegation", {"builtinHelper": data.get("builtinHelper") is not False, "leaderInstructions": data.get("leaderInstructions") or "", "delegates": delegates, **patch})
            await self.ui.load_catalog()

        async def helper(value: bool) -> None:
            await save(builtinHelper=value)

        async def leader(value: str) -> None:
            await save(leaderInstructions=value)

        def edit(i: int | None) -> Callable[[], Awaitable[None]]:
            async def run() -> None:
                d = delegates[i] if i is not None else {}
                ref = d.get("model") or {}
                models = [("Use the thread's model", "")] + [(f"{m.get('name')} · {self.ui.provider_name(m['providerID'])}", f"{m['providerID']}/{m['id']}") for m in self.ui.models]
                fields = [Field("name", "Name", value=d.get("name") or "", placeholder="Coder"), Field("model", "Model", "select", f"{ref['providerID']}/{ref['id']}" if ref else "", options=models),
                          Field("variant", "Effort", value=ref.get("variant") or "", placeholder="default"), Field("job", "Its job: when should the leader delegate to it?", "area", d.get("job") or "", help="The leader reads this to decide. Be concrete: what it's good at, what to send it, what not to."),
                          Field("system", "Extra system prompt", "area", d.get("system") or ""), Field("enabled", "Enabled", "switch", d.get("enabled", True)), Field("readonly", "Read only: never edits or runs commands", "switch", bool(d.get("readonly")))]
                if i is not None:
                    fields.append(Field("remove", "Remove this delegate", "switch", False))
                out = await self.wait(Form(d.get("name") or "New delegate", fields))
                if not out:
                    return
                if out.get("remove"):
                    del delegates[i]
                    await save()
                    return
                if not out["name"].strip() or not out["job"].strip():
                    self.ui.fail("Every delegate needs a name and a job description")
                    return
                pid, _, mid = (out.get("model") or "").partition("/")
                model = {"providerID": pid, "id": mid, **({"variant": out["variant"].strip()} if out.get("variant", "").strip() else {})} if pid else None
                slug = "".join(c if c.isalnum() else "-" for c in out["name"].lower()).strip("-")[:32] or "delegate"
                row = {**d, "id": d.get("id") or slug, "name": out["name"].strip(), "model": model, "job": out["job"].strip(), "system": out["system"], "enabled": out["enabled"], "readonly": out["readonly"]}
                if i is None:
                    delegates.append(row)
                else:
                    delegates[i] = row
                ids = [x["id"] for x in delegates]
                if len(set(ids)) != len(ids):
                    self.ui.fail("Two delegates have the same id, so give them different names")
                    delegates[:] = [x for x in delegates if x is not row] if i is None else delegates
                    return
                await save()

            return run

        rows = [note("Delegate mode makes the thread's model the leader: it plans and reviews, and hands tasks to these delegates."),
                R("toggle", "Built-in Helper", data.get("builtinHelper") is not False, "A subagent on the thread's own model, ready in every mode", helper), head(f"Delegates ({len(delegates)})")]
        rows += [R("item", d.get("name") or d.get("id"), self.ui.model_name(d.get("model")) or "thread's model", S.one_line(d.get("job"), 90), edit(i)) for i, d in enumerate(delegates)]
        rows += [R("button", "Add a delegate", "", "", edit(None)), head("Leader"), R("area", "Leader instructions", data.get("leaderInstructions") or "", "Extra rules for the leader", leader)]
        return rows

    # models

    async def pane_models(self) -> list[R]:
        ui = self.ui
        data = await ui.get("/api/providers")
        rows = [
            R("button", "Add a provider", "", "Sign in with your plan, paste a key, or scan this computer", self.connect),
            R("choice", "Default model", self.default_ref(), "New threads start on this", self.set_default, [(f"{m.get('name')} · {ui.provider_name(m['providerID'])}", f"{m['providerID']}/{m['id']}") for m in ui.models]),
            R("button", "Refresh model lists", "", "", self.refresh), R("button", "Show or hide models", "", "Pick which ones the model picker lists", self.visibility),
        ]
        migration = ui.boot.get("migration") or {}
        if migration.get("db") and not migration.get("done"):
            rows.append(R("button", "Import from OpenCode", "", "Your providers and threads", self.opencode))
        rows.append(head(f"Connected ({len(data.get('configured') or [])})"))
        for p in data.get("configured") or []:
            state = "off" if p.get("enabled") is False else p.get("account") or ("signed in" if p.get("signedIn") else f"key {p.get('keyHint')}" if p.get("hasKey") else "key from environment" if p.get("keyFromEnv") else "no key needed")
            rows.append(R("item", p.get("name") or p["id"], state, f"{sum(1 for m in p.get('models') or [] if not m.get('hidden'))} models", self.provider(p, data)))
        if not data.get("configured"):
            rows.append(note("No providers yet."))
        return rows

    def default_ref(self) -> str:
        ref = self.s.get("defaultModel") or {}
        return f"{ref.get('providerID')}/{ref.get('id')}" if ref else ""

    async def connect(self) -> None:
        await self.ui.cmd_connect("")

    async def set_default(self, value: str) -> None:
        pid, _, mid = value.partition("/")
        await self.ui.save_settings({"defaultModel": {"providerID": pid, "id": mid}})

    async def refresh(self) -> None:
        await self.ui.api("POST", "/api/models/refresh", timeout=120)
        await self.ui.load_catalog()
        self.ui.say("Model lists refreshed", 2)

    async def opencode(self) -> None:
        await self.ui.api("POST", "/api/migrate/opencode", {"sessions": True}, timeout=300)
        await self.ui.load_catalog()
        self.ui.say("Imported from OpenCode", 3)

    async def visibility(self) -> None:
        data = await self.ui.get("/api/providers")
        models = [(p, m) for p in data.get("configured") or [] for m in p.get("models") or []]
        items = lambda: [Item(m.get("name") or m["id"], (p["id"], m), "", p.get("name") or p["id"], not m.get("hidden"), m["id"]) for p, m in models]  # noqa: E731

        async def flip(value: tuple) -> None:
            pid, m = value
            m["hidden"] = not m.get("hidden")
            await self.ui.api("POST", "/api/models/visibility", {"changes": [{"providerID": pid, "id": m["id"], "hidden": m["hidden"]}]})
            picker.set_items(items())

        picker = Picker("Show or hide models", items(), actions=[("ctrl+d", "show or hide", flip)], hint="● shown   Esc done", width=84)
        await self.wait(picker)
        await self.ui.load_catalog()

    def provider(self, p: dict, data: dict) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            ui = self.ui
            on_ = p.get("enabled") is not False
            items = [Item("Test the connection", "test"), Item("Turn off" if on_ else "Turn on", "enabled"), Item("Refresh its models", "refresh"), Item("Edit model limits…", "limits"), Item("Prices…", "prices")]
            if p.get("login") and p.get("signedIn"):
                items.append(Item("Sign out", "logout"))
            elif p.get("login"):
                items.append(Item("Sign in", "login"))
            if p.get("kind") != "login" or p.get("hasKey"):
                items.append(Item("Edit key and address…", "edit"))
            items.append(Item("Remove", "remove", style="$error"))
            picked = await self.wait(Picker(p.get("name") or p["id"], items, search=False))
            pid = p["id"]
            if picked == "test":
                ui.say("Testing…", 1.5)
                r = await ui.api("POST", f"/api/providers/{pid}/test", {}, timeout=60)
                ui.say(f"Works with {r.get('model')}", 4) if r.get("ok") else ui.fail(r.get("error") or "It didn't answer")
            elif picked == "enabled":
                await ui.api("POST", f"/api/providers/{pid}/enabled", {"enabled": not on_})
            elif picked == "refresh":
                await ui.api("POST", f"/api/providers/{pid}/refresh", {}, timeout=120)
            elif picked == "logout":
                await ui.api("POST", f"/api/providers/{pid}/logout", {})
            elif picked == "login":
                await ui.sign_in(next((x for x in SIGN_INS if x["provider"] == pid), {"method": p.get("login"), "name": p.get("name")}))
            elif picked == "edit":
                await ui.key_form(next((c for c in data.get("catalog") or [] if c["id"] == p.get("catalog")), None), p)
            elif picked == "limits":
                await self.limits(p)
            elif picked == "prices":
                await self.prices(p)
            elif picked == "remove":
                if await self.wait(Confirm(f"Remove {p.get('name')}?", "Its key and sign-in are deleted from this computer. Threads stay.", "Remove", danger=True)):
                    await ui.api("DELETE", f"/api/providers/{pid}")
            await ui.load_catalog()

        return run

    async def limits(self, p: dict) -> None:
        m = await self.wait(Picker("Which model?", [Item(x.get("name") or x["id"], x, S.fmt_tokens(x.get("context")) if x.get("context") else "") for x in p.get("models") or []]))
        if not m:
            return
        out = await self.wait(Form(m.get("name") or m["id"], [Field("context", "Context window (tokens)", "number", m.get("context") or ""), Field("output", "Output limit (tokens)", "number", m.get("output") or ""),
                                                              Field("variants", "Effort levels", value=", ".join(m.get("variants") or []), help="Comma-separated, like low, medium, high"), Field("input", "Takes images", "switch", "image" in (m.get("input") or []))]))
        if out:
            body = {"context": int(out["context"] or 0) or None, "output": int(out["output"] or 0) or None, "variants": [x.strip() for x in out["variants"].split(",") if x.strip()], "input": ["text", "image"] if out["input"] else ["text"]}
            await self.ui.api("PUT", f"/api/providers/{p['id']}/models/{m['id']}", body)

    async def prices(self, p: dict) -> None:
        m = await self.wait(Picker("Which model?", [Item(x.get("name") or x["id"], x) for x in p.get("models") or []]))
        if not m:
            return
        out = await self.wait(Form(f"Price of {m.get('name') or m['id']}", [Field("input", "Input, $ per million tokens", value=""), Field("output", "Output, $ per million tokens", value=""), Field("cacheRead", "Cached input, $ per million tokens", value="")], sub="Empty fields go back to the catalog's price."))
        if out:
            given = {k: float(v) for k, v in out.items() if v.strip()}
            await self.ui.api("PUT", f"/api/providers/{p['id']}/prices", {"model": m["id"], "price": given or None})

    # usage

    async def pane_usage(self) -> list[R]:
        u = await self.ui.get("/api/usage/summary", days=30)
        total, today, budget = u.get("total") or {}, u.get("today") or {}, u.get("budget") or {}
        rows = [head("Last 30 days"), R("item", "Spent", S.fmt_cost(total.get("cost")) or "$0"), R("item", "Today", S.fmt_cost(today.get("cost")) or "$0"),
                R("item", "Tokens", f"{S.fmt_tokens(total.get('input'))} in · {S.fmt_tokens(total.get('output'))} out"), head("Limits"),
                R("number", "Per thread, $", budget.get("perThread") or 0, "0 means none. A run stops when it reaches this.", self.saver("budget", "perThread")), R("number", "Per day, $", budget.get("perDay") or 0, "", self.saver("budget", "perDay")), head("By model")]
        models = u.get("models") or []
        most = max([m.get("cost") or 0 for m in models] or [0]) or 1
        for m in models:
            cost = "plan" if m.get("plan") else "no price" if m.get("unpriced") else S.fmt_cost(m.get("cost")) or "$0"
            rows.append(R("item", m.get("name") or m.get("id"), cost, f"{m.get('steps') or 0} steps · {S.fmt_tokens(m.get('input'))} in · {S.fmt_tokens(m.get('output'))} out"))
        if not models:
            rows.append(note("Nothing spent yet."))
        days = [d for d in u.get("days") or [] if d.get("cost") or d.get("steps")]
        if days:
            rows.append(head("By day"))
            top = max([d.get("cost") or 0 for d in days] or [0]) or 1
            rows += [note(str(Content.assemble(f"{d.get('day')}  ", bar((d.get("cost") or 0) / top, 24), f"  {S.fmt_cost(d.get('cost')) or '$0'}"))) for d in days[-14:]]
        del most
        return rows

    # skills

    async def pane_skills(self) -> list[R]:
        d = self.ui.directory()
        installed = await self.ui.get("/api/skills/installed", directory=d) or []
        rows = [R("button", "Find skills", "", "Search skills.sh, or see what's trending", self.find_skills), R("button", "Check for updates", "", "", self.skill_updates), head(f"Installed ({len(installed)})")]
        for s in installed:
            word = ("update available · " if s.get("updateAvailable") else "") + (s.get("scope") or "")
            rows.append(R("item", s.get("name") or s.get("slug"), word, S.one_line(s.get("description"), 100), self.skill_menu(s)))
        return rows

    def skill_menu(self, s: dict) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            rows = [Item("Open the folder", "open")] if s.get("path") else []
            if s.get("managed"):
                rows.append(Item("Update", "update")) if s.get("updateAvailable") else None
                rows.append(Item("Remove", "remove", style="$error"))
            picked = await self.wait(Picker(s.get("name") or s.get("slug"), rows, search=False, sub=s.get("description") or ""))
            if picked == "open":
                await self.ui.api("POST", "/api/reveal", {"path": s["path"]})
            elif picked == "update":
                await self.ui.api("POST", "/api/skills/install", {"source": s.get("source"), "slug": s.get("slug"), "scope": s.get("scope"), "directory": self.ui.directory()}, timeout=120)
            elif picked == "remove" and await self.wait(Confirm(f"Remove {s.get('name')}?", "", "Remove", danger=True)):
                await self.ui.api("DELETE", "/api/skills", params={"slug": s.get("slug"), "scope": s.get("scope"), "directory": self.ui.directory()})

        return run

    async def skill_updates(self) -> None:
        out = await self.ui.api("POST", "/api/skills/check-updates", {"directory": self.ui.directory()}, timeout=60)
        self.ui.say(f"{len(out) if isinstance(out, list) else 0} updates" if isinstance(out, list) else "Checked", 3)

    async def find_skills(self) -> None:
        q = await self.wait(Prompt("Find skills", placeholder="Search, or leave empty for trending", save="Search"))
        if q is None:
            return
        got = await self.ui.get("/api/skills/search", q=q, limit=40) if q.strip() else await self.ui.get("/api/skills/browse", view="trending", page=0)
        found = (got or {}).get("data") or []
        if not found:
            self.ui.say("Nothing found", 2)
            return
        picked = await self.wait(Picker("Skills", [Item(x.get("name") or x.get("slug"), x, f"{x.get('source') or ''} · {x.get('installs') or 0} installs") for x in found], width=90))
        if not picked:
            return
        detail = await self.ui.get("/api/skills/detail", source=picked.get("source"), slug=picked.get("slug"))
        files = (detail.get("detail") or {}).get("files") or []
        audit = (detail.get("audit") or {}).get("audits") or []
        body = "\n\n".join(f"--- {f.get('path')}\n{f.get('contents') or ''}" for f in files[:4])
        warn = "\n".join(f"{a.get('provider') or a.get('name')}: {a.get('risk') or a.get('status') or a.get('verdict') or ''}" for a in audit if isinstance(a, dict))
        chosen = await self.wait(Picker(f"Install {picked.get('name') or picked.get('slug')}?", [Item("Read it first", "read"), Item("Install for this project", "project"), Item("Install for all projects", "global")], search=False, sub=warn))
        if chosen == "read":
            await self.wait(Viewer(picked.get("name") or "", body))
            chosen = await self.wait(Picker("Install it?", [Item("Install for this project", "project"), Item("Install for all projects", "global")], search=False))
        if chosen in ("project", "global"):
            await self.ui.api("POST", "/api/skills/install", {"source": picked.get("source"), "slug": picked.get("slug"), "scope": chosen, "directory": self.ui.directory()}, timeout=120)
            self.ui.say("Installed", 2)

    # mcp

    async def pane_mcp(self) -> list[R]:
        servers = await self.ui.get("/api/mcp") or []
        rows = [R("button", "Add a server", "", "", self.mcp_add), head(f"Servers ({len(servers)})")]
        for s in servers:
            st = (s.get("status") or {})
            word = "off" if s.get("disabled") else st.get("status") or "not started"
            rows.append(R("item", s.get("name"), word, st.get("error") or " ".join(s.get("command") or []) or s.get("url") or "", self.mcp_menu(s)))
        have = {s.get("name") for s in servers}
        spare = [x for x in RECOMMENDED_MCP if x[0] not in have]
        if spare:
            rows.append(head("Recommended"))
            rows += [R("item", name, "add", what, self.mcp_quick(name, cmd)) for name, what, cmd in spare]
        return rows

    def mcp_quick(self, name: str, command: list[str]) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            await self.ui.api("POST", "/api/mcp", {"name": name, "type": "local", "command": command, "environment": {}}, timeout=60)

        return run

    async def mcp_add(self) -> None:
        out = await self.wait(Form("Add an MCP server", [Field("name", "Name"), Field("type", "Kind", "select", "local", options=[("A command on this computer", "local"), ("A URL", "remote")]), Field("target", "Command or URL", placeholder="npx -y some-server"),
                                                         Field("env", "Environment or headers", "area", help="One KEY=value per line")]))
        if not out or not out["name"].strip():
            return
        pairs = dict(line.split("=", 1) for line in out["env"].splitlines() if "=" in line)
        if out["type"] == "local":
            await self.ui.api("POST", "/api/mcp", {"name": out["name"].strip(), "type": "local", "command": out["target"].split(), "environment": pairs}, timeout=60)
        else:
            await self.ui.api("POST", "/api/mcp", {"name": out["name"].strip(), "type": "remote", "url": out["target"].strip(), "headers": pairs}, timeout=60)

    def mcp_menu(self, s: dict) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            name = s.get("name")
            picked = await self.wait(Picker(name, [Item("Turn on" if s.get("disabled") else "Turn off", "toggle"), Item("Reconnect", "reconnect"), Item("Remove", "remove", style="$error")], search=False))
            if picked == "toggle":
                await self.ui.api("POST", f"/api/mcp/{name}/enabled", {"enabled": bool(s.get("disabled"))}, timeout=60)
            elif picked == "reconnect":
                await self.ui.api("POST", f"/api/mcp/{name}/reconnect", {}, timeout=60)
            elif picked == "remove" and await self.wait(Confirm(f"Remove {name}?", "", "Remove", danger=True)):
                await self.ui.api("DELETE", f"/api/mcp/{name}")

        return run

    # prompts

    async def pane_prompts(self) -> list[R]:
        ui = self.ui
        p = await ui.get("/api/prompts", directory=ui.directory())

        def put(path: str, key: str, extra: dict | None = None) -> Callable[[str], Awaitable[None]]:
            async def save(value: str) -> None:
                await ui.api("PUT", path, {key: value, **(extra or {})})

            return save

        rows = [head("Instructions"),
                R("area", "System prompt", p.get("system") or "", "Empty goes back to AFH's own", put("/api/prompts/system", "text")),
                R("area", "Global AGENTS.md", p.get("globalInstructions") or "", p.get("globalInstructionsPath") or "", put("/api/prompts/global", "text")),
                R("area", "This project's AGENTS.md", p.get("projectInstructions") or "", p.get("projectInstructionsPath") or "", put("/api/prompts/project", "text", {"directory": ui.directory()})), head("Agents")]
        overrides = p.get("agentOverrides") or {}
        for a in ui.agents:
            if a.get("hidden") and a.get("id") not in overrides:
                continue
            aid = a["id"]
            rows.append(R("area", a.get("name") or aid, overrides.get(aid) or next((x.get("system") or x.get("prompt") or "" for x in p.get("agents") or [] if x.get("id") == aid), ""), a.get("description") or "", put(f"/api/prompts/agent/{aid}", "system")))
        rows += [R("button", "Create an agent", "", "It appears next to Build and Plan", self.new_agent), R("button", "Delete an agent", "", "", self.drop_agent)]
        return rows

    async def new_agent(self) -> None:
        out = await self.wait(Form("New agent", [Field("id", "Name", placeholder="reviewer"), Field("description", "What it's for"), Field("system", "Its instructions", "area"), Field("mode", "Where it shows", "select", "primary", options=[("With Build and Plan", "primary"), ("Only as a subagent", "subagent")]),
                                                 Field("readonly", "Read only", "switch", False)]))
        if out and out["id"].strip():
            await self.ui.api("POST", "/api/agents", {**out, "id": out["id"].strip()})
            await self.ui.load_catalog()

    async def drop_agent(self) -> None:
        mine = list((self.s.get("agents") or {}).keys())
        if not mine:
            self.ui.say("No agents of your own yet", 2)
            return
        picked = await self.wait(Picker("Delete an agent", [Item(x, x) for x in mine], search=False))
        if picked and await self.wait(Confirm(f"Delete {picked}?", "", "Delete", danger=True)):
            await self.ui.api("DELETE", f"/api/agents/{picked}")
            await self.ui.load_catalog()

    # commands

    async def pane_commands(self) -> list[R]:
        d = self.ui.directory()
        commands = await self.ui.get("/api/commands", directory=d) or []
        rows = [note("A command is a saved prompt. Type /name in the message box and it runs, with $ARGUMENTS replaced by what follows."), R("button", "New command", "", "", self.command_form(None, commands))]
        for src, title in (("settings", "Yours"), ("project", "This project"), ("global", "Global"), ("builtin", "Built in")):
            mine = [c for c in commands if c.get("source") == src]
            if mine:
                rows.append(head(title))
                rows += [R("item", f"/{c.get('name')}", "", S.one_line(c.get("description"), 100), self.command_form(c, commands) if src == "settings" else None) for c in mine]
        return rows

    def command_form(self, c: dict | None, commands: list[dict]) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            fields = [Field("name", "Name", value=(c or {}).get("name") or ""), Field("description", "Description", value=(c or {}).get("description") or ""), Field("prompt", "Prompt", "area", (c or {}).get("prompt") or "")]
            if c:
                fields.append(Field("remove", "Remove this command", "switch", False))
            out = await self.wait(Form("Command", fields))
            if not out:
                return
            mine = [x for x in commands if x.get("source") == "settings" and x is not c]
            if not out.get("remove") and out["name"].strip():
                mine.append({"name": out["name"].strip().lstrip("/"), "description": out["description"], "prompt": out["prompt"]})
            await self.ui.api("PUT", "/api/commands", {"commands": [{k: x.get(k) for k in ("name", "description", "prompt")} for x in mine], "directory": self.ui.directory()})
            await self.ui.load_commands()

        return run

    # hooks

    async def pane_hooks(self) -> list[R]:
        hooks = list(self.s.get("hooks") or [])
        rows = [note("Commands AFH runs around the agent's tools. A hook before a tool can block it by exiting with an error."), R("button", "Add a hook", "", "", self.hook_form(None, hooks)), head(f"Hooks ({len(hooks)})")]
        rows += [R("item", h.get("name") or h.get("command"), "on" if h.get("enabled", True) else "off", f"{dict((b, a) for a, b in HOOK_EVENTS).get(h.get('event'), '')} · {h.get('matcher') or 'every tool'}", self.hook_form(i, hooks)) for i, h in enumerate(hooks)]
        return rows

    def hook_form(self, i: int | None, hooks: list[dict]) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            h = hooks[i] if i is not None else {}
            fields = [Field("name", "Name", value=h.get("name") or ""), Field("event", "When", "select", h.get("event") or "pre_tool", options=HOOK_EVENTS), Field("matcher", "Tools", value=h.get("matcher") or "", placeholder="shell, edit, or empty for all"),
                      Field("command", "Command", "area", h.get("command") or ""), Field("timeout", "Timeout, seconds", "number", h.get("timeout") or 30), Field("enabled", "On", "switch", h.get("enabled", True))]
            if i is not None:
                fields.append(Field("remove", "Remove this hook", "switch", False))
            out = await self.wait(Form("Hook", fields))
            if not out:
                return
            gone = out.pop("remove", False)
            out["timeout"] = int(out.get("timeout") or 30)
            if i is None:
                hooks.append({"id": f"hook-{int(time.time() * 1000)}", **out})
            elif gone:
                del hooks[i]
            else:
                hooks[i] = {**h, **out}
            await self.ui.save_settings({"hooks": hooks})

        return run

    # schedules

    async def pane_schedules(self) -> list[R]:
        jobs = await self.ui.get("/api/schedules") or []
        rows = [note("A prompt that runs on a timetable, while AFH is open."), R("button", "New schedule", "", "", self.schedule_form(None)), head(f"Schedules ({len(jobs)})")]
        for j in jobs:
            nxt = time.strftime("%a %H:%M", time.localtime(j["nextRun"] / 1000)) if j.get("nextRun") and j.get("enabled", True) else "off"
            rows.append(R("item", j.get("name") or S.one_line(j.get("prompt"), 50), f"next {nxt}", f"{describe_schedule(j)} · {S.base_name(j.get('directory') or '')}" + (f" · last run {j['lastStatus']}" if j.get("lastStatus") else ""), self.schedule_menu(j)))
        return rows

    def schedule_menu(self, j: dict) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            rows = [Item("Run now", "run"), Item("Edit…", "edit"), Item("Turn off" if j.get("enabled", True) else "Turn on", "toggle")]
            if j.get("lastSession"):
                rows.append(Item("Open the last run", "open"))
            rows.append(Item("Delete", "delete", style="$error"))
            picked = await self.wait(Picker(j.get("name") or "Schedule", rows, search=False))
            if picked == "run":
                out = await self.ui.api("POST", f"/api/schedules/{j['id']}/run", {})
                self.ui.say("Started", 2)
                if out.get("sessionID"):
                    self.screen.dismiss(None)
                    await self.ui.show_thread(out["sessionID"])
            elif picked == "edit":
                await self.schedule_form(j)()
            elif picked == "toggle":
                await self.ui.api("PUT", f"/api/schedules/{j['id']}", {**j, "enabled": not j.get("enabled", True)})
            elif picked == "open":
                self.screen.dismiss(None)
                await self.ui.show_thread(j["lastSession"])
            elif picked == "delete" and await self.wait(Confirm("Delete this schedule?", "", "Delete", danger=True)):
                await self.ui.api("DELETE", f"/api/schedules/{j['id']}")

        return run

    def schedule_form(self, j: dict | None) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            now = j or {}
            models = [("Default model", "")] + [(m.get("name") or m["id"], f"{m['providerID']}/{m['id']}") for m in self.ui.models]
            ref = now.get("model") or {}
            fields = [Field("name", "Name", value=now.get("name") or ""), Field("directory", "Folder", value=now.get("directory") or self.ui.directory()), Field("prompt", "Prompt", "area", now.get("prompt") or ""),
                      Field("every", "How often", "select", now.get("every") or "daily", options=[("Every N minutes", "interval"), ("Every hour", "hourly"), ("Every day", "daily"), ("Monday to Friday", "weekdays"), ("Once a week", "weekly")]),
                      Field("time", "At", value=now.get("time") or "09:00", placeholder="09:00"), Field("minutes", "Minutes between runs", "number", now.get("minutes") or 60), Field("weekday", "Day", "select", int(now.get("weekday") or 0), options=[(d, i) for i, d in enumerate(WEEK)]),
                      Field("mode", "Approvals", "select", now.get("mode") or "full", options=[("Full access", "full"), ("Build, asking first", "build"), ("Plan only", "plan")]), Field("model", "Model", "select", f"{ref['providerID']}/{ref['id']}" if ref else "", options=models)]
            out = await self.wait(Form("Schedule", fields))
            if not out:
                return
            pid, _, mid = (out.pop("model") or "").partition("/")
            body = {**now, **out, "minutes": int(out.get("minutes") or 60), "model": {"providerID": pid, "id": mid} if pid else None, "enabled": now.get("enabled", True)}
            if j:
                await self.ui.api("PUT", f"/api/schedules/{j['id']}", body)
            else:
                await self.ui.api("POST", "/api/schedules", body)

        return run

    # github

    async def pane_github(self) -> list[R]:
        ui = self.ui
        g = await ui.get("/api/github")

        def put(key: str) -> Callable[[Any], Awaitable[None]]:
            async def save(value: Any) -> None:
                await ui.api("PUT", "/api/github", {key: value})

            return save

        async def allowed(value: str) -> None:
            await put("allowed")([x.strip() for x in value.split(",") if x.strip()])

        rows = [note("AFH watches your repositories for /afh comments on issues and pull requests, works on them in a worktree, and replies."),
                R("toggle", "On", bool(g.get("enabled")), g.get("problem") or (f"As {g['who']}" if g.get("who") else ""), put("enabled")), R("text", "Who may ask", ", ".join(g.get("allowed") or []), "GitHub logins, comma-separated", allowed),
                R("choice", "Approvals", g.get("mode") or "ask", "", put("mode"), [("Ask first", "ask"), ("Full access", "full")]), R("number", "Check every, seconds", g.get("interval") or 60, "", put("interval")), head("Repositories")]

        def drop(i: int) -> Callable[[], Awaitable[None]]:
            async def run() -> None:
                if await self.wait(Confirm(f"Stop watching {g['repos'][i].get('repo')}?", "", "Remove", danger=True)):
                    await put("repos")([r for k, r in enumerate(g["repos"]) if k != i])

            return run

        async def add() -> None:
            out = await self.wait(Form("Add a repository", [Field("repo", "Repository", placeholder="owner/name"), Field("path", "Local clone", value=ui.directory())]))
            if out and out["repo"].strip():
                await put("repos")([*(g.get("repos") or []), {"repo": out["repo"].strip(), "path": out["path"].strip()}])

        rows += [R("item", r.get("repo"), "", r.get("path") or "", drop(i)) for i, r in enumerate(g.get("repos") or [])]
        rows.append(R("button", "Add a repository", "", "", add))
        recent = g.get("recent") or []
        if recent:
            rows.append(head("Recent"))
            rows += [note(f"{r.get('repo')}#{r.get('number')}  {r.get('status')}  {r.get('author') or ''}  {S.one_line(r.get('detail'), 60)}") for r in recent[:10]]
        return rows

    # developer

    async def pane_developer(self) -> list[R]:
        ui = self.ui
        d = await ui.get("/api/developer")

        async def new_key() -> None:
            name = await self.wait(Prompt("Name this key", placeholder="my script", save="Create"))
            if name:
                out = await ui.api("POST", "/api/developer/keys", {"name": name})
                await self.wait(Viewer("Your new key", f"{out.get('key')}\n\nCopy it now. AFH keeps only a hash and can't show it again.", copy_text=out.get("key") or ""))

        def drop(k: dict) -> Callable[[], Awaitable[None]]:
            async def run() -> None:
                if await self.wait(Confirm(f"Delete {k.get('name')}?", "Anything using this key stops working.", "Delete", danger=True)):
                    await ui.api("DELETE", f"/api/developer/keys/{k['id']}")

            return run

        async def port(value: int) -> None:
            await ui.save_settings({"developer": {"port": int(value)}})

        async def install() -> None:
            out = await ui.api("POST", "/api/cli/install", {})
            ui.say("Installed. Open a new terminal to use afh." if out.get("pathChanged") else "Installed", 4)

        rows = [note("A local API for your own scripts: the same one this terminal app and the desktop window use. See agentflowharness.com/api."),
                R("number", "Port", d.get("port") or 0, "0 picks a free port. Takes effect after a restart.", port), R("item", "Discovery file", d.get("discovery") or ""),
                R("button", "Put afh on your PATH", "", "", install), R("button", "New API key", "", "", new_key), head(f"Keys ({len(d.get('keys') or [])})")]
        rows += [R("item", k.get("name"), k.get("prefix") or "", f"Last used {S.ago(k['lastUsed'])}" if k.get("lastUsed") else "Not used yet", drop(k)) for k in d.get("keys") or []]
        return rows

    # remote

    async def pane_remote(self) -> list[R]:
        ui = self.ui
        r, c = await asyncio.gather(ui.get("/api/remote"), ui.get("/api/cloud"))

        def put(key: str) -> Callable[[Any], Awaitable[None]]:
            async def save(value: Any) -> None:
                await ui.api("PUT", "/api/remote", {key: value}, timeout=60)

            return save

        async def password(value: str) -> None:
            if value:
                await put("password")(value)

        async def show_qr() -> None:
            url = r.get("tunnelUrl") or (r.get("lanUrls") or [""])[0]
            await self.wait(Viewer("Scan with your phone", f"{qr_lines(url)}\n\n{url}", copy_text=url))

        async def out_all() -> None:
            await ui.api("POST", "/api/remote/disconnect-all", {})
            ui.say("Everyone is signed out", 2)

        async def cloud_link() -> None:
            link = await ui.api("POST", "/api/cloud/link", {})
            if link.get("url"):
                webbrowser.open(link["url"])
            await self.wait(Viewer("Link this computer", f"Approve it in your browser.\n\nCode: {link.get('code') or ''}\n{link.get('url') or ''}"))

        async def cloud_out() -> None:
            await ui.api("POST", "/api/cloud/signout", {})

        async def cloud_on(value: bool) -> None:
            await ui.api("PUT", "/api/cloud", {"enabled": value})

        rows = [head("From your phone or another computer"),
                R("toggle", "Remote control", bool(r.get("running")), r.get("tunnelError") or "Only while AFH runs on this computer", put("enabled")), R("secret", "Password", r.get("passwordSet"), "At least 6 characters", password),
                R("choice", "Reach it from anywhere", r.get("tunnel") or ("cloudflare" if r.get("tunnelUrl") else "none"), "A Cloudflare quick tunnel" if r.get("cloudflared") else "cloudflared isn't installed, so only this network works", put("tunnel"), [("This network only", "none"), ("Through Cloudflare", "cloudflare")])]
        if r.get("running") and (r.get("tunnelUrl") or r.get("lanUrls")):
            rows.append(R("button", "Show the QR code", r.get("tunnelUrl") or r["lanUrls"][0], "", show_qr))
            rows.append(R("button", "Sign everyone out", "", "", out_all))
        rows.append(head("AFH account"))
        if c.get("signedIn"):
            rows += [R("item", "Signed in", c.get("email") or "", (c.get("computer") or {}).get("name") or ""), R("toggle", "Reach this computer through your account", bool(c.get("enabled")), c.get("error") or c.get("state") or "", cloud_on), R("button", "Sign out", "", "", cloud_out)]
        else:
            rows.append(R("button", "Link this computer", "", "Reach it from the phone apps with your account", cloud_link))
        return rows

    # bug

    async def pane_bug(self) -> list[R]:
        info = await self.ui.get("/api/bugreport")

        async def make() -> None:
            out = await self.wait(Form("Report a bug", [Field("description", "What happened?", "area"), Field("includeLog", "Add the log", "switch", True, help="It stays on this computer until you send the file.")], save="Make the report"))
            if out:
                r = await self.ui.api("POST", "/api/bugreport", out, timeout=60)
                await self.wait(Viewer("Report saved", f"{r.get('path')}\n\nAttach this file to a new issue:\nhttps://github.com/Lucifer-xD/agent-flow-harness/issues/new/choose\n\nRead it first if you like: nothing leaves this computer unless you send it.", copy_text=r.get("path") or ""))

        rows = [R("button", "Make a report", "", "A file with your system, providers (no keys) and the log", make), head("This computer"), R("item", "System", info.get("system") or ""), R("item", "Log", S.fmt_tokens(info.get("logBytes") or 0) + " bytes")]
        for p in info.get("problems") or []:
            rows.append(note(str(p)))
        return rows

    # about

    async def pane_about(self) -> list[R]:
        from . import update

        ui = self.ui

        async def restart() -> None:
            if await self.wait(Confirm("Restart the backend?", "Threads and running jobs are kept; a run in progress resumes.", "Restart")):
                await ui.api("POST", "/api/restart", {})

        async def check() -> None:
            await update.run(ui)

        async def open_home() -> None:
            webbrowser.open("https://agentflowharness.com")

        return [R("item", "Agent Flow Harness", __version__, "Your agent, your models, on your computer"), R("item", "Models", str(len(ui.models))), R("button", "Check for updates", "", "", check), self.toggle("updates", "auto", "Download desktop updates by itself"),
                R("button", "Restart the backend", "", "", restart), R("button", "Website", "agentflowharness.com", "", open_home), head("Where things live"), note("Settings, threads, keys and logs are in .afh in your home folder. The desktop app and this terminal app share them.")]


async def race_dialog(ui: Any, task: str) -> None:
    """Start a race, or look at the last ones."""
    races = await ui.get("/api/races") or []
    if not task and races:
        rows = [Item("New race…", "new")] + [Item(S.one_line(r.get("prompt"), 60), r, r.get("status") or "") for r in races[:10]]
        picked = await ui.push_screen_wait(Picker("Model races", rows, search=False))
        if picked is None:
            return
        if picked != "new":
            await race_result(ui, picked["id"])
            return
    models = [Item(m.get("name") or m["id"], f"{m['providerID']}/{m['id']}", ui.provider_name(m["providerID"]), keywords=m["id"]) for m in ui.models]
    chosen: list[str] = []

    def pick(value: str) -> None:
        chosen.remove(value) if value in chosen else chosen.append(value)
        for item in picker.items:
            item.checked = item.value in chosen
        picker.set_items(picker.items)
        ui.say(f"{len(chosen)} models", 1)

    picker = Picker("Pick two or more models", models, actions=[("ctrl+d", "add or remove", pick)], hint="Ctrl+D adds   Enter go", width=84)
    last = await ui.push_screen_wait(picker)
    if last and last not in chosen:
        chosen.append(last)
    if len(chosen) < 2:
        ui.say("A race needs at least two models", 3)
        return
    out = await ui.push_screen_wait(Form("Race", [Field("prompt", "Task", "area", task), Field("check", "Check command", placeholder="pytest -q", help="Scores each result. Optional."),
                                                  Field("mode", "Approvals", "select", "full", options=[("Full access", "full"), ("Ask first", "ask"), ("Read only", "readonly")])], save="Start"))
    if not out or not out["prompt"].strip():
        return
    race = await ui.api("POST", "/api/races", {"directory": ui.dir, "prompt": out["prompt"].strip(), "models": chosen, "check": out["check"], "mode": out["mode"]}, timeout=120)
    ui.say(f"Racing {len(race['entries'])} models. /race shows them.", 5)


async def race_result(ui: Any, rid: str) -> None:
    race = await ui.get(f"/api/races/{rid}")
    rows = []
    for e in race.get("entries") or []:
        bits = [e.get("status") or ""]
        if e.get("passed") is not None:
            bits.append("check passed" if e["passed"] else "check failed")
        if e.get("files") is not None:
            bits.append(f"{e['files']} files")
        if e.get("seconds"):
            bits.append(S.fmt_dur(e["seconds"] * 1000))
        if e.get("cost"):
            bits.append(S.fmt_cost(e["cost"]))
        rows.append(Item(e.get("model") or "", e, " · ".join(x for x in bits if x)))
    rows.append(Item("Throw all of them away", "discard", style="$error"))
    picked = await ui.push_screen_wait(Picker(S.one_line(race.get("prompt"), 70), rows, search=False, sub=f"{race.get('status')}. Pick one to see it or merge it.", width=90))
    if picked == "discard":
        if await ui.push_screen_wait(Confirm("Throw away this race?", "Their worktrees go. Your checkout is unchanged.", "Throw away", danger=True)):
            await ui.api("POST", f"/api/races/{rid}/discard", {})
    elif picked:
        action = await ui.push_screen_wait(Picker(picked.get("model") or "", [Item("Open its thread", "open"), Item("Merge this one", "merge")], search=False))
        if action == "open":
            await ui.show_thread(picked["session"])
        elif action == "merge":
            done = await ui.api("POST", f"/api/races/{rid}/pick", {"session": picked["session"]}, timeout=120)
            ui.say(f"Merged into {(done.get('merged') or {}).get('into')}", 5)


__all__ = ["TABS", "SettingsScreen", "race_dialog", "ThemePicker"]
