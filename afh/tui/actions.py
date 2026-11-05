"""Everything you can ask the terminal app to do: slash commands, keys, pickers and thread tools."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import subprocess
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any

from textual.content import Content

from .. import __version__
from ..cli import CliError
from . import state as S
from . import themes
from .commands import COMMANDS, LOCAL
from .dialogs import Confirm, Field, Form, Item, Picker, Prompt, Viewer
from .panels import all_done
from .widgets import bar, diff_content

SIGN_INS = [
    {"method": "chatgpt", "provider": "chatgpt", "name": "ChatGPT (Codex)", "sub": "Use your Plus, Pro or Team plan, no API key"},
    {"method": "chatgpt-web", "provider": "chatgpt-chat", "name": "ChatGPT (chat)", "sub": "The normal chat models from your browser login", "custom": True},
    {"method": "copilot", "provider": "github-copilot", "name": "GitHub Copilot", "sub": "Claude, GPT and Gemini through your Copilot plan"},
    {"method": "antigravity", "provider": "antigravity", "name": "Google Antigravity", "sub": "Gemini and Claude on your Google account's Antigravity quota",
     "warning": "Google has suspended Antigravity access for some accounts that signed in through apps other than Antigravity itself (OpenCode, OpenClaw). AFH signs in the same way, so your Google "
                "account's Antigravity access could be suspended. Your other Google services were not reported affected. Use an account you can afford to lose Antigravity on."},
    {"method": "openrouter", "provider": "openrouter", "name": "OpenRouter", "sub": "Hundreds of models on one account; creates a key for you"},
]
FEATURED = ["openai", "anthropic", "gemini", "openrouter", "deepseek", "xai", "mistral", "groq", "kimi", "zai-coding", "azure", "amazon-bedrock", "ollama", "lmstudio"]
TYPES = {"user": "You", "assistant": "Model", "system": "System notice", "idle": "Run ended", "compaction": "Compaction summary", "shell": "Shell", "synthetic": "Injected", "skill": "Skill"}
HELP_KEYS = [
    ("Enter", "send"), ("Ctrl+J, Alt+Enter", "new line"), ("Up, Down", "earlier messages you sent"), ("Ctrl+R", "search what you've sent"), ("Ctrl+G", "write in your editor"),
    ("Esc", "stop the run"), ("Esc Esc", "undo, on an empty box"), ("Tab", "next agent: Build, Plan, Delegate, Red Team…"), ("Shift+Tab", "approvals: ask, full, read only"),
    ("Ctrl+P", "command palette"), ("Ctrl+K", "threads"), ("Ctrl+N", "new thread"), ("F2", "settings"), ("Ctrl+O", "open or close tool details"), ("Ctrl+T", "fold the to-do list"),
    ("Ctrl+B", "live panel"), ("Ctrl+Y", "copy the last answer"), ("Alt+V", "paste an image"), ("PgUp, PgDn", "scroll"), ("Ctrl+L", "redraw"), ("Ctrl+C", "clear the box, twice to quit"),
]


def open_path(path: str) -> None:
    """The default program for a file or folder."""
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Actions:
    """Mixed into the App: it reads and changes the app's state through the helpers there."""

    # ---- keys ---------------------------------------------------------------------------------

    def action_ctrl_c(self) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.screen.clear_selection()
            self.say("Copied", 1.5)
            return
        if self.screen is not self.main_screen:
            self.screen.dismiss(None)
            return
        now = time.time()
        if self.composer.text:
            self.composer.clear()
            self.last_ctrl_c = 0
        elif now - self.last_ctrl_c < 1.5:
            self.exit()
        else:
            self.last_ctrl_c = now
            self.say("Press Ctrl+C again to quit", 1.5)

    def action_quit_now(self) -> None:
        self.exit()

    def action_escape(self) -> None:
        t = self.thread
        if t and t.busy:
            self.run_worker(self.stop(), group="stop", exclusive=True)
            return
        now = time.time()
        if not self.composer.text and now - self.last_esc < 0.7:
            self.last_esc = 0
            self.action_command("undo")
        else:
            self.last_esc = now

    async def stop(self) -> None:
        try:
            await self.api("POST", f"/api/sessions/{self.thread.id}/interrupt")
            self.say("Stopping…", 1.5)
        except CliError as err:
            self.fail(err)

    def action_next_agent(self) -> None:
        if self.composer.menu_open():
            self.composer.menu_pick(run=False)
            return
        agents = [a["id"] for a in self.main_agents()]
        if agents:
            now = self.agent_id()
            nxt = agents[(agents.index(now) + 1) % len(agents)] if now in agents else agents[0]
            self.run_worker(self.set_agent(nxt), group="agent", exclusive=True)

    def action_next_mode(self) -> None:
        from .app import MODE_ORDER

        now = self.mode_id()
        nxt = MODE_ORDER[(MODE_ORDER.index(now) + 1) % len(MODE_ORDER)] if now in MODE_ORDER else "ask"
        self.run_worker(self.set_mode(nxt), group="mode", exclusive=True)

    async def set_agent(self, aid: str) -> None:
        if self.thread:
            try:
                fresh = await self.api("PATCH", f"/api/sessions/{self.thread.id}", {"agent": aid})
                self.thread.session.update(fresh or {"agent": aid})
            except CliError as err:
                return self.fail(err)
        else:
            self.draft["agent"] = aid
        self.draw_status()

    async def set_mode(self, mode: str) -> None:
        if self.thread:
            try:
                fresh = await self.api("PATCH", f"/api/sessions/{self.thread.id}", {"mode": mode})
                self.thread.session.update(fresh or {})
            except CliError as err:
                return self.fail(err)
        else:
            self.draft["mode"] = mode
        self.draw_status()

    async def set_model(self, ref: dict) -> None:
        if self.thread:
            try:
                fresh = await self.api("PATCH", f"/api/sessions/{self.thread.id}", {"model": ref})
                self.thread.session.update(fresh or {"model": ref})
            except CliError as err:
                return self.fail(err)
        else:
            self.draft["model"] = ref
        self.draw_status()

    def action_palette(self) -> None:
        self.run_worker(self.palette(), group="dialog", exclusive=True)

    def action_command(self, name: str) -> None:
        self.run_worker(self.run_command(name, ""), group="dialog", exclusive=True)

    def action_toggle_details(self) -> None:
        self.scroller.set_details(not self.scroller.show_details)

    def action_toggle_todos(self) -> None:
        self.dock.toggle()

    def action_toggle_live(self) -> None:
        self.live.toggle()

    def action_redraw(self) -> None:
        self.refresh(layout=True, repaint=True)
        self.screen.refresh(layout=True, repaint=True)

    def action_history_search(self) -> None:
        self.run_worker(self.history_search(), group="dialog", exclusive=True)

    def action_copy_last(self) -> None:
        text = self.thread.last_text() if self.thread else ""
        if text:
            self.copy_to_clipboard(text)
            self.say("Copied the last answer", 1.5)

    def action_drop_attachment(self) -> None:
        if self.composer.files:
            self.composer.files.pop()
            self.composer.draw_chips()
        else:
            self.composer.box.action_cut()

    def action_paste_image(self) -> None:
        self.run_worker(self.paste_image(), group="image", exclusive=True)

    def action_scroll(self, direction: int) -> None:
        box = self.scroller
        box.scroll_to(y=box.scroll_y + direction * max(4, box.size.height - 3), animate=False)

    def action_scroll_to(self, where: int) -> None:
        self.scroller.scroll_end(animate=False) if where else self.scroller.scroll_home(animate=False)

    async def paste_image(self) -> None:
        """An image on the clipboard goes through /api/uploads, as a paste does in the app."""
        data = await asyncio.to_thread(clipboard_image)
        if not data:
            self.say("No image on the clipboard", 2)
            return
        try:
            out = await asyncio.to_thread(self.upload, data, "pasted.png")
            self.composer.attach(out["path"])
        except (OSError, ValueError, KeyError) as err:
            self.fail(err)

    def upload(self, data: bytes, name: str) -> dict:
        import urllib.parse
        import urllib.request

        from ..cli import OPENER

        req = urllib.request.Request(self.client.url + "/api/uploads", data=data, method="POST", headers={"Authorization": f"Bearer {self.client.key}", "x-filename": urllib.parse.quote(name), "Content-Type": "application/octet-stream"})
        with OPENER.open(req, timeout=60) as r:
            return json.loads(r.read())

    # ---- running commands ---------------------------------------------------------------------

    def command_list(self) -> list[dict]:
        """What the / menu shows: the terminal's own commands, then the engine's and yours."""
        seen = {c["name"] for c in COMMANDS}
        extra = [c for c in self.commands_cache if c.get("name") not in seen]
        return [*COMMANDS, *extra]

    def is_local(self, name: str, args: str) -> bool:
        if name == "goal" and args:
            return False  # the engine sets it and starts working
        return name in LOCAL

    async def run_command(self, name: str, args: str) -> None:
        handler = getattr(self, f"cmd_{name.replace('-', '_')}", None)
        if handler is None:
            await self.send_prompt(f"/{name} {args}".strip())
            return
        try:
            await handler(args)
        except CliError as err:
            self.fail(err)

    def need_thread(self) -> bool:
        if self.thread:
            return True
        self.say("Start a thread first", 2)
        return False

    async def cmd_help(self, args: str) -> None:
        lines: list[Any] = [("Keys", "bold")]
        for key, what in HELP_KEYS:
            lines += ["\n", (f"{key:<20}", "$primary"), what]
        lines += ["\n\n", ("Commands", "bold")]
        for c in self.command_list():
            lines += ["\n", (f"/{c['name']:<14}", "$primary"), (c.get("description") or "", "$afh-text2")]
        lines += ["\n\n", ("Typing", "bold"), "\n", ("@", "$primary"), " picks a file   ", ("!", "$primary"), " runs a shell command and adds it to the thread   ", ("/", "$primary"), " opens commands"]
        await self.push_screen_wait(Viewer("Help", Content.assemble(*lines)))

    async def cmd_exit(self, args: str) -> None:
        self.exit()

    cmd_quit = cmd_exit

    async def cmd_new(self, args: str) -> None:
        self.draft = {"model": None, "agent": None, "mode": None, "goal": None, "worktree": False}
        self.recent = await self.get("/api/sessions", directory=self.dir, limit=8) or []
        await self.show_home()
        self.composer.box.focus()

    async def cmd_clear(self, args: str) -> None:
        await self.cmd_new(args)

    async def cmd_status(self, args: str) -> None:
        ref = self.model_ref()
        backend = "this terminal's own backend" if self.client.backend else f"the running app at {self.client.url}"
        rows = [("AFH", __version__), ("Backend", backend), ("Folder", self.dir), ("Model", f"{ref['providerID']}/{ref['id']}" if ref else "none"), ("Models available", str(len(self.models))),
                ("Agent", self.agent_name(self.agent_id())), ("Approvals", self.mode_id())]
        await self.push_screen_wait(Viewer("Status", Content("\n").join(Content.assemble((f"{k:<18}", "$afh-text2"), v) for k, v in rows if v)))

    # ---- models, agents, modes ----------------------------------------------------------------

    def model_items(self) -> list[Item]:
        ref = self.model_ref() or {}
        recent = ((self.settings.get("tui") or {}).get("recentModels")) or []
        rows = []
        for r in recent:
            m = self.find_model(r)
            if m:
                rows.append(Item(m.get("name") or m["id"], {"id": m["id"], "providerID": m["providerID"]}, self.provider_name(m["providerID"]), "Recent", m["id"] == ref.get("id") and m["providerID"] == ref.get("providerID"), m["id"]))
        for m in sorted(self.models, key=lambda x: self.provider_name(x["providerID"]).lower()):
            bits = [S.fmt_tokens(m["context"]) + " context"] if m.get("context") else []
            if m.get("variants"):
                bits.append("effort " + "/".join(m["variants"]))
            if m.get("tools") is False:
                bits.append("no tools")
            rows.append(Item(m.get("name") or m["id"], {"id": m["id"], "providerID": m["providerID"]}, " · ".join(bits), self.provider_name(m["providerID"]),
                             m["id"] == ref.get("id") and m["providerID"] == ref.get("providerID"), f"{m['id']} {m['providerID']}"))
        rows.append(Item("Add or manage providers…", "connect", "", "More"))
        return rows

    async def cmd_model(self, args: str) -> None:
        if args:
            pid, _, mid = args.partition("/")
            ref = {"providerID": pid, "id": mid}
            if not self.find_model(ref):
                self.fail(f"No model {args}. /model lists them.")
                return
            await self.choose_model(ref)
            return
        picked = await self.push_screen_wait(Picker("Model", self.model_items(), placeholder="Search models", hint="↑↓ choose   Enter use it   Esc close"))
        if picked == "connect":
            await self.cmd_connect("")
        elif picked:
            await self.choose_model(picked)

    async def choose_model(self, ref: dict) -> None:
        model = self.find_model(ref) or {}
        if model.get("variants"):
            variants = ["default", *[v for v in model["variants"] if v != "default"]]
            current = (self.model_ref() or {}).get("variant") or "default"
            picked = await self.push_screen_wait(Picker(f"Effort for {model.get('name')}", [Item(v, v, checked=v == current) for v in variants], search=False))
            if picked and picked != "default":
                ref = {**ref, "variant": picked}
        await self.set_model(ref)
        recent = [ref, *[r for r in ((self.settings.get("tui") or {}).get("recentModels") or []) if (r.get("id"), r.get("providerID")) != (ref["id"], ref["providerID"])]][:5]
        await self.save_settings({"tui": {"recentModels": recent}})

    async def save_settings(self, patch: dict) -> dict:
        self.settings = await self.api("PUT", "/api/settings", patch) or self.settings
        return self.settings

    async def cmd_agent(self, args: str) -> None:
        if args:
            match = next((a for a in self.main_agents() if args.lower() in (a["id"].lower(), (a.get("name") or "").lower())), None)
            if not match:
                self.fail(f"No agent {args}. /agent lists them.")
                return
            await self.set_agent(match["id"])
            return
        items = [Item(a.get("name") or a["id"], a["id"], a.get("description") or "", checked=a["id"] == self.agent_id()) for a in self.main_agents()]
        items.append(Item("Create or edit agents…", "__edit__", "", "More"))
        picked = await self.push_screen_wait(Picker("Agent", items, search=len(items) > 8))
        if picked == "__edit__":
            await self.cmd_settings("prompts")
        elif picked:
            await self.set_agent(picked)

    async def cmd_mode(self, args: str) -> None:
        names = {"ask": "ask", "full": "full", "read": "readonly", "readonly": "readonly"}
        if args:
            if args.lower() not in names:
                self.fail("Approvals are ask, full or read")
                return
            await self.set_mode(names[args.lower()])
            return
        rows = [("Ask first", "ask", "Approve file edits and commands"), ("Full access", "full", "Edit files and run commands freely"), ("Read only", "readonly", "Can read and search, never edit or run")]
        picked = await self.push_screen_wait(Picker("Approvals", [Item(a, b, c, checked=b == self.mode_id()) for a, b, c in rows], search=False))
        if picked:
            await self.set_mode(picked)

    # ---- providers ----------------------------------------------------------------------------

    async def cmd_connect(self, args: str) -> None:
        data = await self.get("/api/providers")
        have = {p["id"]: p for p in data.get("configured") or []}
        catalog = [c for c in data.get("catalog") or [] if not c.get("configured")]
        items = []
        for x in SIGN_INS:
            p = have.get(x["provider"])
            signed = p and (p.get("signedIn") or (x["method"] == "openrouter" and p.get("hasKey")))
            items.append(Item(x["name"], ("signin", x), ("Signed in" + (f" as {p['account']}" if p.get("account") else "")) if signed else x["sub"], "Sign in with your plan", bool(signed)))
        items.append(Item("Scan this computer", ("scan", None), "Ollama, LM Studio, vLLM, llama.cpp, Jan", "On this computer"))
        catalog.sort(key=lambda c: ((FEATURED.index(c["id"]) if c["id"] in FEATURED else 99), c.get("name", "").lower()))
        for c in catalog:
            items.append(Item(c.get("name") or c["id"], ("key", c), "sign in or key" if c.get("login") and c.get("needsKey") else "sign in" if c.get("login") else "API key" if c.get("needsKey") else "no key needed", "API key", False, c["id"]))
        items.append(Item("Custom endpoint…", ("custom", None), "Any OpenAI, Anthropic or Gemini compatible address", "More"))
        picked = await self.push_screen_wait(Picker("Connect a provider", items, placeholder=f"Search {len(items)} providers"))
        if not picked:
            return
        kind, value = picked
        if kind == "signin":
            await self.sign_in(value)
        elif kind == "scan":
            await self.scan_local()
        elif kind == "key":
            if value.get("login") and not value.get("needsKey"):
                await self.sign_in({"method": value["login"], "name": value.get("name")})
            else:
                await self.key_form(value)
        else:
            await self.key_form(None)

    async def sign_in(self, x: dict) -> None:
        if x.get("warning") and not await self.push_screen_wait(Confirm(f"Sign in to {x['name']}?", x["warning"], "I understand, sign in", danger=True)):
            return
        if x.get("custom"):
            await self.connect_chatgpt_web()
            return
        login = await self.api("POST", "/api/auth/login", {"method": x["method"]})
        if login.get("url"):
            webbrowser.open(login["url"])
        body = f"Enter this code on GitHub:\n\n    {login['userCode']}\n\n{login.get('url') or ''}" if login.get("userCode") else f"Finish signing in in your browser. AFH continues on its own.\n\n{login.get('url') or ''}"
        waiting = Viewer(f"Sign in to {x['name']}", body, hint="Esc cancels", copy_text=login.get("userCode") or "")
        task = asyncio.ensure_future(self.push_screen_wait(waiting))
        while not task.done():
            await asyncio.sleep(1.5)
            state = await self.get(f"/api/auth/login/{login['id']}")
            if state.get("status") == "done":
                waiting.dismiss(None)
                await task
                self.say(f"Signed in to {x['name']}" + (f" as {state['account']}" if state.get("account") else ""), 4)
                await self.load_catalog()
                self.draw_status()
                return
            if state.get("status") == "error":
                waiting.dismiss(None)
                await task
                self.fail(state.get("error") or "Sign-in failed")
                return
        await self.api("DELETE", f"/api/auth/login/{login['id']}")

    async def connect_chatgpt_web(self) -> None:
        out = await self.api("POST", "/api/chatgpt-web/connect", {"mode": "chrome"}, timeout=120)
        if not out.get("ok"):
            text = await self.push_screen_wait(Prompt("Connect ChatGPT (chat)", password=True, placeholder="__Secure-next-auth.session-token", save="Connect",
                                                      sub="AFH couldn't read your browser login. On chatgpt.com open DevTools, Application, Cookies, and copy __Secure-next-auth.session-token here."))
            if not text:
                return
            out = await self.api("POST", "/api/chatgpt-web/connect", {"mode": "paste", "text": text}, timeout=120)
        if out.get("ok"):
            self.say("Connected ChatGPT chat", 4)
            await self.load_catalog()
            self.draw_status()
        else:
            self.fail(out.get("error") or "Couldn't connect")

    async def scan_local(self) -> None:
        found = await self.get("/api/providers/detect-local") or []
        if not found:
            self.say("No local model server is running. Start Ollama, LM Studio, vLLM, llama.cpp or Jan, then scan again.", 6)
            return
        items = [Item(s["name"], s, f"{len(s['models'])} models · {s['base_url']}", checked=bool(s.get("configured"))) for s in found]
        srv = await self.push_screen_wait(Picker("Models on this computer", items, search=False))
        if srv and not srv.get("configured"):
            body = {"catalog": srv["catalog"], "id": srv["catalog"]} if srv.get("catalog") else {"id": srv["id"], "name": srv["name"], "kind": "openai", "base_url": srv["base_url"]}
            await self.api("POST", "/api/providers", body, timeout=120)
            self.say(f"{srv['name']} added", 3)
            await self.load_catalog()
            self.draw_status()

    async def key_form(self, known: dict | None, existing: dict | None = None) -> None:
        custom = not known and not (existing and existing.get("catalog"))
        fields: list[Field] = []
        if custom:
            fields.append(Field("kind", "API format", "select", (existing or {}).get("kind") or "openai", options=[("OpenAI-compatible", "openai"), ("Anthropic", "anthropic"), ("Gemini", "gemini")]))
            if not existing:
                fields.append(Field("id", "Provider id", placeholder="my-gateway", help="lowercase, letters and dashes"))
            fields.append(Field("name", "Display name", value=(existing or {}).get("name") or ""))
        for x in (known or {}).get("params") or []:
            fields.append(Field(f"param_{x['name']}", x.get("label") or x["name"], value=((existing or {}).get("params") or {}).get(x["name"]) or x.get("default") or "", help=f"Also read from {x['name']}."))
        fields.append(Field("base_url", "Base URL", value=(existing or {}).get("base_url") or ("" if (known or {}).get("params") else (known or {}).get("base_url") or ""), placeholder=(known or {}).get("base_url") or "http://localhost:11434/v1"))
        hint = (existing or {}).get("keyHint")
        fields.append(Field("api_key", "API key", "password", placeholder=f"unchanged ({hint})" if (existing or {}).get("hasKey") else "Paste API key", help=f"Also read from {known['env'][0]} if set." if (known or {}).get("env") else "Stored only on this computer, in ~/.afh/providers.json"))
        fields.append(Field("models", "Model ids", value=", ".join(m["id"] for m in (existing or {}).get("models") or [] if not m.get("fetched")), help="Comma-separated. Leave empty to use the list the endpoint reports."))
        title = f"Edit {existing['name']}" if existing else f"Connect {known['name']}" if known else "Custom endpoint"
        out = await self.push_screen_wait(Form(title, fields, sub=(known or {}).get("hint") or "", save="Save" if existing else "Connect"))
        if not out:
            return
        catalog_id = (known or {}).get("id") or (existing or {}).get("catalog")
        params = {k[6:]: v.strip() for k, v in out.items() if k.startswith("param_")}
        body = {"id": (existing or {}).get("id") or out.get("id", "").strip() or catalog_id, "catalog": None if custom else catalog_id, "kind": out.get("kind") or (existing or known or {}).get("kind") or "openai",
                "name": out.get("name") or (existing or known or {}).get("name") or "", "base_url": out.get("base_url") or "", "api_key": out.get("api_key") or "", "models": out.get("models") or "", "params": params}
        saved = await self.api("POST", "/api/providers", body, timeout=120)
        self.say(f"{saved.get('name') or body['id']} saved", 3)
        await self.load_catalog()
        self.draw_status()

    # ---- themes -------------------------------------------------------------------------------

    async def cmd_theme(self, args: str) -> None:
        before = self.theme
        if args:
            match = next((tid for tid, row in themes.PRESETS.items() if args.lower() in (tid, row[0].lower())), None)
            if not match:
                self.fail(f"No theme {args}. /theme lists them.")
                return
            await self.use_theme(match)
            return
        current = before.removeprefix("afh-")
        items = [Item(row[0], tid, "", "Dark" if row[2] else "Light", tid == current, tid) for tid, row in sorted(themes.PRESETS.items(), key=lambda r: not r[1][2])]
        picker = ThemePicker("Theme", items, placeholder=f"Search {len(items)} themes", hint="↑↓ preview   Enter keep   Esc back")
        picked = await self.push_screen_wait(picker)
        if picked:
            await self.use_theme(picked)
        else:
            self.theme = before

    async def use_theme(self, tid: str) -> None:
        row = themes.PRESETS[tid]
        self.theme = f"afh-{tid}"
        await self.save_settings({"tui": {"theme": tid}, "ui": {"preset": tid, "accentOverride": False, "bg": row[3][0], "text": row[3][7], "accent": row[1], "theme": "dark" if row[2] else "light", "darkPreset" if row[2] else "lightPreset": tid}})

    # ---- toggles ------------------------------------------------------------------------------

    async def cmd_thinking(self, args: str) -> None:
        on = not self.setting("showReasoning", True)
        await self.save_settings({"ui": {"showReasoning": on}})
        self.say(f"Thinking {'shown' if on else 'hidden'}", 2)
        await self.reload_thread()

    async def cmd_details(self, args: str) -> None:
        self.action_toggle_details()

    async def cmd_live(self, args: str) -> None:
        self.live.toggle()

    # ---- threads ------------------------------------------------------------------------------

    async def cmd_threads(self, args: str) -> None:
        await self.thread_picker(all_projects=False)

    cmd_resume = cmd_threads
    cmd_sessions = cmd_threads

    async def thread_items(self, all_projects: bool) -> list[Item]:
        rows = await self.get("/api/sessions", limit=200) if all_projects else await self.get("/api/sessions", directory=self.dir, limit=200)
        items = []
        current = self.thread.id if self.thread else None
        for s in rows or []:
            if s.get("parentID"):
                continue
            where = ((s.get("location") or {}).get("project") or (s.get("location") or {}).get("directory") or "")
            hint = S.ago((s.get("time") or {}).get("updated"))
            if s.get("running"):
                hint = "working · " + hint
            items.append(Item(s.get("title") or "New thread", s, hint, S.base_name(where) if all_projects else "", s["id"] == current))
        if all_projects:
            items.sort(key=lambda i: i.group.lower())
        return items

    async def thread_picker(self, all_projects: bool) -> None:
        items = await self.thread_items(all_projects)
        state = {"all": all_projects}

        async def act(fn, value) -> None:
            await fn(value)
            picker.set_items(await self.thread_items(state["all"]))

        async def toggle(_: Any) -> None:
            state["all"] = not state["all"]
            picker.set_items(await self.thread_items(state["all"]))

        actions = [
            ("ctrl+r", "rename", lambda s: self.bg(act(self.rename_thread, s))), ("ctrl+f", "fork", lambda s: self.bg(self.fork_thread(s, picker))),
            ("ctrl+e", "export", lambda s: self.bg(self.export_thread(s))), ("ctrl+a", "archive", lambda s: self.bg(act(self.archive_thread, s))),
            ("ctrl+d", "delete", lambda s: self.bg(act(self.delete_thread, s))), ("ctrl+t", "all projects", lambda s: self.bg(toggle(s))),
        ]
        sub = "" if items else "No threads in this folder yet. Ctrl+T shows every project."
        picker = Picker("Threads", items, placeholder="Search threads", sub=sub, actions=actions, width=92, hint="Enter open   Esc close")
        picked = await self.push_screen_wait(picker)
        if picked:
            await self.switch_to(picked)

    def bg(self, coro: Any) -> None:
        self.run_worker(self.guarded(coro), group="side", exclusive=False)

    async def guarded(self, coro: Any) -> None:
        try:
            await coro
        except CliError as err:
            self.fail(err)

    async def switch_to(self, session: dict) -> None:
        where = ((session.get("location") or {}).get("project") or (session.get("location") or {}).get("directory"))
        if where and Path(where).is_dir():
            self.dir = where
            await self.load_commands()
            self.composer.file_cache = None
        await self.show_thread(session["id"])

    async def rename_thread(self, s: dict) -> None:
        title = await self.push_screen_wait(Prompt("Rename thread", value=s.get("title") or ""))
        if title and title.strip():
            fresh = await self.api("PATCH", f"/api/sessions/{s['id']}", {"title": title.strip()})
            if self.thread and self.thread.id == s["id"]:
                self.thread.session.update(fresh or {})
                self.draw_status()

    async def archive_thread(self, s: dict) -> None:
        await self.api("PATCH", f"/api/sessions/{s['id']}", {"archived": True})
        self.say("Thread archived", 2)
        if self.thread and self.thread.id == s["id"]:
            await self.cmd_new("")

    async def delete_thread(self, s: dict) -> None:
        confirm = self.setting("confirmDelete", True)
        if confirm and not await self.push_screen_wait(Confirm("Delete thread?", f'"{s.get("title") or "New thread"}" and its history will be deleted. Files it changed are not reverted.', "Delete", danger=True)):
            return
        out = await self.api("DELETE", f"/api/sessions/{s['id']}")
        kept = [w for w in (out or {}).get("worktrees") or [] if w.get("kept")]
        if kept:
            self.say(f"Its worktree has unmerged work, so it was kept: {kept[0].get('path')}", 9)
        self.threads.pop(s["id"], None)
        if self.thread and self.thread.id == s["id"]:
            await self.cmd_new("")

    async def fork_thread(self, s: dict, picker: Any = None) -> None:
        fresh = await self.api("POST", f"/api/sessions/{s['id']}/fork", {})
        self.say("Forked into a new thread", 2)
        if picker:
            picker.dismiss(fresh)
        else:
            await self.switch_to(fresh)

    async def export_thread(self, s: dict) -> None:
        payload = await self.get(f"/api/sessions/{s['id']}/export")
        name = "".join(c if c.isalnum() or c in "-_." else "-" for c in (s.get("title") or s["id"]))[:60]
        path = Path(self.dir) / f"{name}.afh-session.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.say(f"Exported {path.name}", 4)

    async def cmd_rename(self, args: str) -> None:
        if not self.need_thread():
            return
        if args:
            self.thread.session.update(await self.api("PATCH", f"/api/sessions/{self.thread.id}", {"title": args}) or {})
            self.draw_status()
        else:
            await self.rename_thread(self.thread.session)

    async def cmd_fork(self, args: str) -> None:
        if self.need_thread():
            await self.fork_thread(self.thread.session)

    async def cmd_archive(self, args: str) -> None:
        if self.need_thread():
            await self.archive_thread(self.thread.session)

    async def cmd_delete(self, args: str) -> None:
        if self.need_thread():
            await self.delete_thread(self.thread.session)

    async def cmd_export(self, args: str) -> None:
        if self.need_thread():
            await self.export_thread(self.thread.session)

    async def cmd_copy(self, args: str) -> None:
        if self.need_thread():
            self.copy_to_clipboard(self.thread.as_markdown())
            self.say("Thread copied as Markdown", 2)

    async def cmd_import(self, args: str) -> None:
        path = args or await self.push_screen_wait(Prompt("Import a thread", placeholder="Path to an .afh-session.json, OpenCode export or Zadloop file", save="Import", sub="Also takes a Zadloop / DeepSeek Harness .zip or .json."))
        if not path:
            return
        session = await self.api("POST", "/api/import/file", {"path": path.strip().strip('"'), "directory": self.dir}, timeout=120)
        self.say(f"Imported {session.get('title') or 'thread'}", 3)
        await self.show_thread(session["id"])

    async def cmd_open(self, args: str) -> None:
        path = args or await self.push_screen_wait(Prompt("Open a folder", value=self.dir, save="Open"))
        if not path:
            return
        folder = Path(path.strip().strip('"')).expanduser().resolve()
        await self.api("POST", "/api/projects", {"path": str(folder)})
        self.dir = str(folder)
        self.composer.file_cache = None
        await self.load_commands()
        await self.cmd_new("")

    async def cmd_reveal(self, args: str) -> None:
        await asyncio.to_thread(open_path, self.directory())

    # ---- undo ---------------------------------------------------------------------------------

    async def cmd_undo(self, args: str) -> None:
        if not self.need_thread():
            return
        t = self.thread
        if t.busy:
            self.say("Stop the run first (Esc)", 2)
            return
        users = [m for m in t.messages if m.get("type") == "user"]
        if not users:
            self.say("Nothing to undo", 2)
            return
        items = [Item(S.one_line(m.get("text"), 80), m, S.ago((m.get("time") or {}).get("created"))) for m in reversed(users)]
        picked = await self.push_screen_wait(Picker("Undo to before…", items, sub="Rewinds the thread and the files to just before this message. /redo puts it all back.", placeholder="Search your messages"))
        if not picked:
            return
        staged = await self.api("POST", f"/api/sessions/{t.id}/revert", {"messageId": picked["id"], "files": True}, timeout=120)
        count = len((staged or {}).get("files") or [])
        await self.reload_thread()
        self.say(f"Rewound{f', {count} files restored' if count else ''}. Send something to keep it, or /redo.", 6)
        if picked.get("text"):
            self.composer.set_text(picked["text"])

    async def cmd_redo(self, args: str) -> None:
        if self.need_thread():
            await self.api("POST", f"/api/sessions/{self.thread.id}/revert/clear")
            await self.reload_thread()
            self.say("Put back", 2)

    # ---- what the thread did ------------------------------------------------------------------

    async def cmd_diff(self, args: str) -> None:
        if not self.need_thread():
            return
        files = await self.get(f"/api/sessions/{self.thread.id}/diff") or []
        if not files:
            self.say("No files changed in this thread", 2)
            return
        pieces: list[Content] = []
        added = sum(f.get("additions") or 0 for f in files)
        removed = sum(f.get("deletions") or 0 for f in files)
        for f in files:
            pieces.append(Content.assemble((f.get("file") or "", "bold"), "  ", (f"+{f.get('additions') or 0}", "$success"), " ", (f"−{f.get('deletions') or 0}", "$error"), (f"  {f.get('status') or ''}", "$afh-text3")))
            pieces.append(diff_content(f.get("patch"), 2000))
            pieces.append(Content(""))
        text = "\n".join(f.get("patch") or "" for f in files)
        await self.push_screen_wait(Viewer(f"Changes: {len(files)} files, +{added} −{removed}", Content("\n").join(pieces), copy_text=text))

    async def cmd_cost(self, args: str) -> None:
        if not self.need_thread():
            return
        u = await self.get(f"/api/sessions/{self.thread.id}/usage")
        await self.push_screen_wait(Viewer("Context and cost", self.usage_body(u), actions=[("c", "compact now", lambda: self.bg(self.close_then(self.cmd_compact("")))), ("e", "context editor", lambda: self.bg(self.close_then(self.cmd_context(""))))]))

    async def close_then(self, coro: Any) -> None:
        self.pop_screen()
        await coro

    def usage_body(self, u: dict) -> Content:
        limit = u.get("contextLimit") or 0
        used = u.get("lastInput") or 0
        tot = u.get("totals") or {}
        cache = tot.get("cache") or {}
        msgs = u.get("messages") or {}
        row = lambda k, v: Content.assemble((f"{k:<24}", "$afh-text2"), v)  # noqa: E731
        lines = [row("In the window now", f"{S.fmt_tokens(used)}" + (f" / {S.fmt_tokens(limit)}" if limit else ""))]
        if limit:
            lines.append(Content.assemble(" " * 24, bar(used / limit, 30), f" {round(100 * used / limit)}%"))
        lines += [row("Model", u.get("modelName") or "-"), row("Mode", u.get("agent") or "build"), row("Messages", f"{msgs.get('user', 0)} you · {msgs.get('assistant', 0)} model · {msgs.get('tools', 0)} tools"),
                  row("Tokens this thread", f"{S.fmt_tokens((tot.get('input') or 0) + (cache.get('read') or 0) + (cache.get('write') or 0))} in · {S.fmt_tokens(tot.get('output'))} out")]
        if cache.get("read"):
            share = round(100 * cache["read"] / max(1, (tot.get("input") or 0) + cache["read"] + (cache.get("write") or 0)))
            lines.append(row("From the prompt cache", f"{S.fmt_tokens(cache['read'])} ({share}%)"))
        lines.append(row("Cost", "plan (no per-token cost)" if u.get("plan") else S.fmt_cost(u.get("cost")) if u.get("cost") else "$0" if u.get("price") else "price not set"))
        return Content("\n").join(lines)

    async def cmd_compact(self, args: str) -> None:
        if not self.need_thread():
            return
        self.say("Compacting…", 1.5)
        out = await self.api("POST", f"/api/sessions/{self.thread.id}/compact", timeout=300)
        self.say("Older messages summarised" if (out or {}).get("ok") else "Nothing to compact yet", 3)
        if (out or {}).get("ok"):
            await self.reload_thread()

    async def cmd_prompt(self, args: str) -> None:
        if not self.need_thread():
            return
        h = await self.get(f"/api/sessions/{self.thread.id}/harness")
        sec = lambda title, text, empty="": [Content.styled(title, "bold"), Content.styled(text.strip() if text and text.strip() else empty, "$afh-text2"), Content("")]  # noqa: E731
        ref = h.get("model") or {}
        lines = [*sec("Agent and model", f"{h.get('agent')}  {ref.get('providerID', '')}/{ref.get('id', '')}"), *sec("System prompt (exactly as sent)", h.get("systemPrompt"), "Empty."),
                 *sec("Tools available", ", ".join(h.get("tools") or [])), *sec("Personalization", h.get("personalization"), "Nothing set."), *sec("Global AGENTS.md", h.get("globalInstructions"), "Empty."),
                 *sec("Project AGENTS.md", h.get("projectInstructions"), "No AGENTS.md in this project."), *sec("Project memory", h.get("memory"), "Nothing remembered yet.")]
        for m in h.get("systemMessages") or []:
            lines += sec("Injected: " + ", ".join(m.get("sources") or []), m.get("text"))
        rules = "\n".join(f"{r.get('effect', ''):<5}  {r.get('action')}  {r.get('resource')}" for r in h.get("permissions") or [])
        lines += sec("Thread permissions", rules, "inherited")
        await self.push_screen_wait(Viewer("What the model is told", Content("\n").join(lines), copy_text=h.get("systemPrompt") or ""))

    async def cmd_context(self, args: str) -> None:
        """Everything the model sees, message by message: read it, edit it, or remove it."""
        if not self.need_thread():
            return
        t = self.thread
        messages = await self.get(f"/api/sessions/{t.id}/context") or []
        start = max((i for i, m in enumerate(messages) if m.get("type") == "compaction"), default=0)
        before, work = messages[:start], [dict(m) for m in messages[start:]]

        def preview(m: dict) -> str:
            if m.get("type") == "assistant":
                parts = [p.get("text") or f"[{p.get('name')}]" for p in m.get("content") or [] if p.get("type") in ("text", "tool")]
                return S.one_line(" ".join(parts), 90)
            return S.one_line(m.get("text") or json.dumps({k: v for k, v in m.items() if k not in ("id", "type", "time")})[:90], 90)

        def items() -> list[Item]:
            return [Item(preview(m), i, TYPES.get(m.get("type"), m.get("type") or "")) for i, m in enumerate(work)]

        dirty = {"yes": False}

        async def edit(i: int) -> None:
            m = work[i]
            if m.get("type") == "assistant":
                text = await self.push_screen_wait(Prompt("Edit this message (JSON)", value=json.dumps(m.get("content") or [], indent=2, ensure_ascii=False), multiline=True, tall=True))
                if text is None:
                    return
                try:
                    m["content"] = json.loads(text)
                except ValueError:
                    self.fail("That isn't valid JSON")
                    return
            else:
                text = await self.push_screen_wait(Prompt("Edit this message", value=m.get("text") or "", multiline=True, tall=True))
                if text is None:
                    return
                m["text"] = text
            dirty["yes"] = True
            picker.set_items(items())

        def remove(i: int) -> None:
            del work[i]
            dirty["yes"] = True
            picker.set_items(items())

        hint = f"{len(before)} earlier messages are summarised by the compaction at the top. " if before else ""
        picker = Picker("Context", items(), sub=f"{hint}What the model sees, in order. Saving rewrites history; files on disk are not touched.", hint="Enter edit   Esc finish",
                        actions=[("ctrl+d", "remove", remove), ("ctrl+e", "edit", lambda i: self.bg(edit(i)))], placeholder="Search messages", width=100)
        while True:
            picked = await self.push_screen_wait(picker_copy(picker))
            if picked is None:
                break
            await edit(picked)
        if not dirty["yes"]:
            return
        if not any(m.get("type") == "user" for m in [*before, *work]):
            self.fail("Keep at least one of your messages")
            return
        if await self.push_screen_wait(Confirm("Rewrite this thread's history?", "The model will see the edited version from the next message on. This can't be undone.", "Save & apply")):
            fresh = await self.api("PUT", f"/api/sessions/{t.id}/messages", {"messages": [*before, *work], "directory": self.dir})
            self.say("Context updated", 2)
            await self.show_thread((fresh or {}).get("id") or t.id)

    async def cmd_images(self, args: str) -> None:
        """Screenshots and pasted images open in the default viewer: a terminal can't draw them."""
        if not self.need_thread():
            return
        shots = []
        for m in self.thread.messages:
            for f in m.get("files") or []:
                if str(f.get("uri", "")).startswith("data:image/"):
                    shots.append((f.get("name") or "image", f["uri"]))
            for p in m.get("content") or []:
                for c in (p.get("state") or {}).get("content") or [] if p.get("type") == "tool" else []:
                    if c.get("type") == "image" and c.get("uri"):
                        shots.append((f"{S.tool_verb(p, False)} {S.one_line(S.tool_target(p), 50)}", c["uri"]))
        if not shots:
            self.say("No images in this thread", 2)
            return
        picked = await self.push_screen_wait(Picker("Images", [Item(name, uri) for name, uri in reversed(shots)], search=len(shots) > 8))
        if picked:
            head, _, data = picked.partition(",")
            ext = "jpg" if "jpeg" in head else head.split("/")[-1].split(";")[0] or "png"
            path = Path(tempfile.gettempdir()) / f"afh-image-{int(time.time())}.{ext}"
            path.write_bytes(base64.b64decode(data))
            await asyncio.to_thread(open_path, str(path))

    # ---- goal, to-dos, memory, jobs -----------------------------------------------------------

    async def cmd_goal(self, args: str) -> None:
        t = self.thread
        g = (t.goal if t else self.draft.get("goal")) or {}
        if g and t:
            rows = []
            st = g.get("status")
            if st != "achieved":
                rows.append(Item("Mark achieved", {"status": "achieved"}))
            if st in ("achieved", "blocked", "paused"):
                rows.append(Item("Reopen goal", {"status": "active"}, "Back to active, fresh autopilot budget"))
            if st == "active":
                rows.append(Item("Pause goal", {"status": "paused"}))
                rows.append(Item("Turn autopilot " + ("off" if g.get("autopilot") else "on"), {"autopilot": not g.get("autopilot")}))
            rows += [Item("Edit…", "edit"), Item("History", "history"), Item("Remove goal", "remove", style="$error")]
            picked = await self.push_screen_wait(Picker(f"Goal: {S.one_line(g.get('text'), 60)}", rows, search=False, sub=f"Done when: {g['criteria']}" if g.get("criteria") else ""))
            if picked is None:
                return
            if isinstance(picked, dict):
                t.goal = await self.api("PATCH", f"/api/sessions/{t.id}/goal", picked)
                self.dock.draw()
                return
            if picked == "remove":
                if await self.push_screen_wait(Confirm("Remove the goal?", "The thread keeps its messages and to-do list; the agent stops working toward the goal.", "Remove", danger=True)):
                    await self.api("DELETE", f"/api/sessions/{t.id}/goal")
                    t.goal = None
                    self.dock.draw()
                return
            if picked == "history":
                await self.goal_history()
                return
        agent = self.settings.get("goals") or {}
        fields = [Field("text", "Goal", "area", g.get("text") or "", placeholder="What done looks like", help="The agent plans the steps, works through them, verifies the result, and reports it achieved or blocked."),
                  Field("criteria", "Done when", value=g.get("criteria") or "", placeholder="Optional: how to check it"), Field("autopilot", "Autopilot: keep working until it's achieved", "switch", g.get("autopilot", agent.get("autopilot", True))),
                  Field("maxTurns", "Continuations per message", "number", g.get("maxTurns") or agent.get("maxTurns") or 3)]
        busy = bool(t and t.busy)
        out = await self.push_screen_wait(Form("Edit the goal" if g else "Set a goal", fields, save="Save" if busy else "Save & start"))
        if not out:
            return
        if not (out.get("text") or "").strip():
            self.say("Describe the goal first", 2)
            return
        value = {"text": out["text"].strip(), "criteria": (out.get("criteria") or "").strip(), "autopilot": out.get("autopilot"), "maxTurns": max(1, min(100, int(out.get("maxTurns") or 3)))}
        if t:
            t.goal = await self.api("PUT", f"/api/sessions/{t.id}/goal", {**value, "start": not busy})
            self.dock.draw()
            self.say("Goal saved", 2)
        else:
            self.draft["goal"] = value
            await self.send_prompt(f"Work toward the goal of this thread:\n\n{value['text']}")

    async def goal_history(self) -> None:
        afh = (await self.get(f"/api/sessions/{self.thread.id}")).get("metadata", {}).get("afh", {})
        lines: list[Content] = [Content.styled("Achieved goals", "bold")]
        for g in reversed(afh.get("goalHistory") or []):
            lines.append(Content.assemble(("✓ ", "$success"), g.get("text") or "", (f"  {g.get('summary') or ''}", "$afh-text3")))
        lines.append(Content.styled("Completed lists", "bold"))
        for x in reversed(afh.get("todoHistory") or []):
            todos = x.get("todos") or []
            lines.append(Content.assemble(("✓ ", "$success"), (todos[0].get("content") if todos else "To-do list"), (f"  {sum(1 for y in todos if y.get('status') == 'completed')}/{len(todos)}", "$afh-text3")))
        await self.push_screen_wait(Viewer("Goals and lists", Content("\n").join(lines)))

    async def cmd_todo(self, args: str) -> None:
        if not self.need_thread():
            return
        t = self.thread
        if t.todos and all_done(t.todos):
            t.todos = []

        def items() -> list[Item]:
            rows = [Item(f"{ {'completed': '✓', 'cancelled': '✗', 'in_progress': '▸'}.get(x.get('status'), '○')} {x.get('content')}", i) for i, x in enumerate(t.todos)]
            rows.append(Item("Add a step…", "add"))
            return rows

        async def save() -> None:
            t.todos = await self.api("PUT", f"/api/sessions/{t.id}/todos", {"todos": t.todos}) or t.todos
            self.dock.draw()

        while True:
            actions = [("ctrl+d", "remove", lambda i: self.bg(drop(i))), ("ctrl+e", "edit", lambda i: self.bg(change(i))), ("ctrl+r", "in progress", lambda i: self.bg(running(i)))]

            async def drop(i: Any) -> None:
                if isinstance(i, int):
                    del t.todos[i]
                    await save()
                    picker.set_items(items())

            async def change(i: Any) -> None:
                if isinstance(i, int):
                    text = await self.push_screen_wait(Prompt("Edit step", value=t.todos[i].get("content") or ""))
                    if text:
                        t.todos[i] = {**t.todos[i], "content": text, "activeForm": None}
                        await save()
                        picker.set_items(items())

            async def running(i: Any) -> None:
                if isinstance(i, int):
                    st = t.todos[i].get("status")
                    t.todos[i] = {**t.todos[i], "status": "pending" if st == "in_progress" else "in_progress"}
                    await save()
                    picker.set_items(items())

            picker = Picker("To-do", items(), search=False, actions=actions, hint="Enter tick or untick   Esc close", width=84)
            picked = await self.push_screen_wait(picker)
            if picked is None:
                return
            if picked == "add":
                text = await self.push_screen_wait(Prompt("Add a step", save="Add"))
                if text and text.strip():
                    t.todos = [*t.todos, {"content": text.strip(), "status": "pending"}]
                    await save()
            else:
                x = t.todos[picked]
                t.todos[picked] = {**x, "status": "pending" if x.get("status") == "completed" else "completed"}
                await save()

    async def cmd_memory(self, args: str) -> None:
        memory = await self.get("/api/projects/memory", directory=self.directory())
        text = await self.push_screen_wait(Prompt("Project memory", value=(memory or {}).get("text") or "", multiline=True, tall=True, sub="What the agent knows about this project, kept between threads. One fact per line."))
        if text is not None and text != (memory or {}).get("text"):
            await self.api("PUT", "/api/projects/memory", {"directory": self.directory(), "text": text})
            self.say("Saved. The agent sees it from its next step.", 3)

    async def cmd_remember(self, args: str) -> None:
        if not args:
            await self.cmd_memory("")
            return
        memory = await self.get("/api/projects/memory", directory=self.directory())
        facts = [*((memory or {}).get("items") or []), *[x.strip() for x in args.split("\n") if x.strip()]]
        await self.api("PUT", "/api/projects/memory", {"directory": self.directory(), "facts": facts})
        self.say("Remembered", 2)

    async def cmd_jobs(self, args: str) -> None:
        if not self.need_thread():
            return
        t = self.thread
        t.jobs = await self.get(f"/api/sessions/{t.id}/jobs") or []

        def state_of(j: dict) -> str:
            if j.get("running"):
                return f"running {S.fmt_dur(S.now_ms() - (j.get('started') or S.now_ms()))}"
            return "stopped" if j.get("stopped") else f"exited {j.get('exitCode', '?')}"

        async def stop(j: dict) -> None:
            if j.get("running"):
                await self.api("POST", f"/api/jobs/{j['id']}/stop")
            else:
                await self.api("DELETE", f"/api/jobs/{j['id']}")
            t.jobs = await self.get(f"/api/sessions/{t.id}/jobs") or []
            picker.set_items([Item(S.one_line(x.get("command"), 60), x, state_of(x)) for x in t.jobs])

        items = [Item(S.one_line(j.get("command"), 60), j, state_of(j)) for j in t.jobs]
        picker = Picker("Background jobs", items, search=False, sub="" if items else "No background jobs in this thread.", actions=[("ctrl+d", "stop or dismiss", lambda j: self.bg(stop(j)))], hint="Enter output   Esc close", width=90)
        picked = await self.push_screen_wait(picker)
        if picked:
            j = await self.get(f"/api/jobs/{picked['id']}", tail=200000)
            await self.push_screen_wait(Viewer(S.one_line(j.get("command"), 70), j.get("tail") or "(no output yet)", sub=state_of(j)))

    async def cmd_helpers(self, args: str) -> None:
        """Every helper this thread started: what it was asked, and watch it work."""
        if not self.need_thread():
            return
        t = self.thread
        rows = []
        for m in t.messages:
            for p in m.get("content") or []:
                if p.get("type") == "tool" and (p.get("name") or "").lower() == "subagent":
                    given = S.tool_input(p)
                    status = (p.get("state") or {}).get("status") or "streaming"
                    word = "working" if status in ("streaming", "running") else "failed" if status == "error" else "done"
                    rows.append(Item(S.one_line(given.get("description"), 60), p, f"{self.agent_name(given.get('agent') or 'helper')} · {word}"))
        if not rows:
            self.say("No helpers in this thread yet", 2)
            return
        picked = await self.push_screen_wait(Picker("Helpers", list(reversed(rows)), search=len(rows) > 8, hint="Enter watch   Esc close"))
        if picked:
            child = self.child_of(t, picked)
            if not child:
                self.say("Its thread isn't available", 2)
                return
            await self.show_thread(child.id)
            self.say("You're in the helper's thread. /back returns.", 4)

    async def cmd_back(self, args: str) -> None:
        parent = (self.thread.session.get("parentID") if self.thread else None)
        if parent:
            await self.show_thread(parent)

    async def cmd_approvals(self, args: str) -> None:
        self.asking.clear()
        self.pump_permissions()

    # ---- worktrees ----------------------------------------------------------------------------

    async def cmd_worktree(self, args: str) -> None:
        t = self.thread
        if not t:
            ok = (await self.get("/api/git/check", directory=self.dir) or {}).get("repo")
            if not ok:
                self.say("This folder isn't a git repository", 3)
                return
            self.draft["worktree"] = not self.draft.get("worktree")
            self.say("The next thread gets its own worktree" if self.draft["worktree"] else "No worktree", 3)
            return
        wt = ((t.session.get("metadata") or {}).get("afh") or {}).get("worktree")
        if not wt:
            self.say("This thread isn't in a worktree. Use /worktree on a new thread.", 3)
            return
        st = await self.get(f"/api/sessions/{t.id}/worktree")
        dirty = st.get("dirty") or []
        changes = f"{len(dirty)} uncommitted · {st.get('ahead')} commits{' · merged' if st.get('merged') else ''}" if st.get("exists") else "folder is gone"
        rows = []
        if st.get("exists") and (dirty or (st.get("ahead") and not st.get("merged"))):
            rows.append(Item(f"Merge into {st.get('base') or 'the main branch'}", "merge"))
        rows += [Item("Copy folder path", "copy"), Item("Open the folder", "open"), Item("Remove worktree…", "remove", style="$error")]
        picked = await self.push_screen_wait(Picker(f"Worktree {st.get('branch')}", rows, search=False, sub=f"Made from {st.get('base') or '-'}. {changes}.\n{st.get('path')}"))
        if picked == "merge":
            if await self.push_screen_wait(Confirm("Merge this thread's branch?", "AFH commits any uncommitted changes in the worktree, then merges its branch into the branch your project folder is on. If there are conflicts nothing is changed.", "Merge")):
                out = await self.api("POST", f"/api/sessions/{t.id}/worktree/merge", timeout=120)
                self.say(f"Merged into {out.get('into')}", 5)
        elif picked == "copy":
            self.copy_to_clipboard(st.get("path") or "")
            self.say("Path copied", 2)
        elif picked == "open":
            await self.api("POST", "/api/reveal", {"path": st.get("path")})
        elif picked == "remove":
            unsaved = dirty or (st.get("ahead") and not st.get("merged"))
            body = f"It still has {len(dirty)} uncommitted files and {st.get('ahead')} unmerged commits. They will be lost. The thread stays." if unsaved else "The folder and its branch are deleted. The thread stays."
            if await self.push_screen_wait(Confirm("Remove the worktree?", body, "Remove", danger=True)):
                await self.api("POST", f"/api/sessions/{t.id}/worktree/remove", {"force": True})
                self.say("Worktree removed", 2)

    # ---- shell, editor, history ---------------------------------------------------------------

    async def shell(self, command: str) -> None:
        if not self.thread:
            ref = self.model_ref()
            if not ref:
                self.fail("Add a provider first: /connect")
                return
            self.thread = await self.create_thread(command)
        out = await self.api("POST", f"/api/sessions/{self.thread.id}/shell", {"command": command}, timeout=600)
        self.thread.add(out)
        await self.scroller.add_new()

    async def cmd_editor(self, args: str) -> None:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
        path = Path(tempfile.gettempdir()) / f"afh-message-{os.getpid()}.md"
        path.write_text(self.composer.text, encoding="utf-8")
        try:
            with self.suspend():
                subprocess.run([*shlex.split(editor, posix=os.name != "nt"), str(path)], check=False)
            self.composer.set_text(path.read_text(encoding="utf-8").rstrip("\n"))
        except Exception:  # no suspend here (a test, or an odd terminal): the built-in box does the same job
            text = await self.push_screen_wait(Prompt("Write your message", value=self.composer.text, multiline=True, tall=True, save="Done"))
            if text is not None:
                self.composer.set_text(text)
        finally:
            path.unlink(missing_ok=True)
        self.composer.box.focus()

    async def history_search(self) -> None:
        items = [Item(S.one_line(x, 90), x) for x in reversed(self.history.items)]
        picked = await self.push_screen_wait(Picker("Search what you've sent", items, placeholder="Type to search", width=96))
        if picked:
            self.composer.set_text(picked)

    # ---- palette ------------------------------------------------------------------------------

    async def palette(self) -> None:
        from .settings import TABS

        items = [Item(c.get("label") or f"/{c['name']}", ("cmd", c["name"]), c.get("description") or "", "Actions", False, c["name"]) for c in COMMANDS]
        items += [Item(label, ("settings", tid), "", "Settings", False, "settings") for tid, label in TABS]
        try:
            for s in await self.get("/api/sessions", directory=self.dir, limit=40) or []:
                items.append(Item(s.get("title") or "New thread", ("thread", s), S.ago((s.get("time") or {}).get("updated")), "Threads"))
        except CliError:
            pass
        ref = self.model_ref() or {}
        items += [Item(m.get("name") or m["id"], ("model", {"id": m["id"], "providerID": m["providerID"]}), self.provider_name(m["providerID"]), "Models", False, m["id"]) for m in self.models]
        items += [Item(row[0], ("theme", tid), "dark" if row[2] else "light", "Themes", False, "theme color") for tid, row in themes.PRESETS.items()]
        picked = await self.push_screen_wait(Picker("Command palette", items, placeholder="Search actions, settings, threads, models, themes", width=90))
        if not picked:
            return
        kind, value = picked
        if kind == "cmd":
            await self.run_command(value, "")
        elif kind == "settings":
            await self.cmd_settings(value)
        elif kind == "thread":
            await self.switch_to(value)
        elif kind == "model":
            await self.choose_model(value)
        elif kind == "theme":
            await self.use_theme(value)

    # ---- settings and the rest ----------------------------------------------------------------

    async def cmd_settings(self, args: str) -> None:
        from .settings import SettingsScreen

        await self.push_screen_wait(SettingsScreen(self, args or "general"))
        await self.load_catalog()
        self.apply_look()
        await self.reload_thread() if self.thread else None
        self.draw_status()

    async def cmd_usage(self, args: str) -> None:
        await self.cmd_settings("usage")

    async def cmd_remote(self, args: str) -> None:
        await self.cmd_settings("remote")

    async def cmd_skills(self, args: str) -> None:
        await self.cmd_settings("skills")

    async def cmd_mcp(self, args: str) -> None:
        await self.cmd_settings("mcp")

    async def cmd_schedules(self, args: str) -> None:
        await self.cmd_settings("schedules")

    async def cmd_github(self, args: str) -> None:
        await self.cmd_settings("github")

    async def cmd_bug(self, args: str) -> None:
        await self.cmd_settings("bug")

    async def cmd_account(self, args: str) -> None:
        await self.cmd_settings("remote")

    async def cmd_race(self, args: str) -> None:
        from .settings import race_dialog

        await race_dialog(self, args)

    async def cmd_update(self, args: str) -> None:
        from . import update

        await update.run(self)

    def check_for_update(self) -> None:
        from . import update

        self.run_worker(update.notice(self), group="update", exclusive=True)

    def show_design(self, t: S.Thread, p: dict, done: Any) -> None:
        """Design options: listed here, Ctrl+O opens an option's screens in the browser."""
        self.run_worker(self.pick_design(t, p, done), group="design", exclusive=True)

    async def pick_design(self, t: S.Thread, p: dict, done: Any) -> None:
        design = (p.get("metadata") or {}).get("design") or {}
        options = design.get("options") or []

        def preview(option: Any) -> None:
            if isinstance(option, dict):
                for screen in option.get("screens") or []:
                    if screen.get("path"):
                        webbrowser.open(Path(screen["path"]).as_uri())

        rows = [Item(f"{o.get('letter')}  {o.get('name') or o.get('title') or ''}", o, S.one_line(o.get("summary") or o.get("notes") or "", 60)) for o in options]
        rows += [Item("None of these: make new options", "again"), Item("Skip", "skip")]
        picked = await self.push_screen_wait(Picker(design.get("title") or "Pick a design", rows, search=False, width=90, sub=S.one_line(design.get("brief") or design.get("summary") or "", 200),
                                                    actions=[("ctrl+o", "open in browser", preview)], hint="Enter choose   Esc decide later"))
        if picked is None:
            done(None)
        elif picked == "skip":
            done(("dismiss", None))
        elif picked == "again":
            notes = await self.push_screen_wait(Prompt("What should change?", save="Send"))
            done(("design", {"decision": "answer", "answers": [{"choice": "", "notes": notes or ""}]}))
        else:
            notes = await self.push_screen_wait(Prompt(f"Anything to change in {picked.get('letter')}?", save="Choose", placeholder="Optional"))
            done(("design", {"decision": "answer", "answers": [{"choice": picked.get("letter"), "notes": notes or ""}]}))


class ThemePicker(Picker):
    """Colours change as you move through the list."""

    def on_option_list_option_highlighted(self, event: Any) -> None:
        item = self.shown[event.option_index] if event.option_index < len(self.shown) else None
        if item:
            self.app.theme = f"afh-{item.value}"


def picker_copy(picker: Picker) -> Picker:
    """A screen can only be shown once, so showing the same list again takes a fresh one."""
    fresh = Picker(picker.title_text, picker.items, placeholder=picker.placeholder, sub=picker.sub, search=picker.search, hint=picker.hint, actions=picker.actions, width=picker.box_width)
    return fresh


def clipboard_image() -> bytes | None:
    """PNG bytes of the image on the clipboard, on Windows and Mac."""
    if os.name == "nt":
        script = ("Add-Type -AssemblyName System.Windows.Forms;Add-Type -AssemblyName System.Drawing;$i=[Windows.Forms.Clipboard]::GetImage();"
                  "if($i){$m=New-Object IO.MemoryStream;$i.Save($m,[Drawing.Imaging.ImageFormat]::Png);[Convert]::ToBase64String($m.ToArray())}")
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return base64.b64decode(out.stdout.strip()) if out.stdout.strip() else None
    if os.uname().sysname == "Darwin":
        path = Path(tempfile.gettempdir()) / f"afh-clip-{os.getpid()}.png"
        script = f'try\nset d to the clipboard as «class PNGf»\nset f to open for access POSIX file "{path}" with write permission\nwrite d to f\nclose access f\nend try'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=15)
        if path.exists():
            data = path.read_bytes()
            path.unlink()
            return data
    return None
