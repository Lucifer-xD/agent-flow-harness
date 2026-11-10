"""The `computer` tool: AFH sees the screen and uses the mouse and keyboard like a person, to do
things in desktop apps that have no file, shell or browser path — and can teach the user how to do
something themselves, one on-screen tooltip at a time.

It works on Windows. Every app must be approved by the user before AFH touches it (once, or always),
and some apps are off limits (AFH itself, Windows security screens, password managers). Web browsers
are view-only here — AFH has its own `browser` tool for the web — and terminals and code editors are
click-only, so typing can't run a command outside the thread's rules. The user stops a task any time
by pressing Esc (or the Stop button on the overlay).
"""
from __future__ import annotations

import asyncio

from afh.engine.computer import apps as appsmod
from afh.engine.computer import win
from afh.engine.computer.control import Controller, Shot, controller
from afh.engine.tools.files import BaseTool, ToolError, str_arg
from afh.engine.types import PermissionDenied, ToolContext, ToolResult, ToolSpec

POINTER = ("move", "click", "double_click", "triple_click", "right_click", "middle_click", "mouse_down", "mouse_up", "drag", "scroll")
ACTIONS = ("screenshot", "zoom", "apps", "request_access", "launch", "focus", "switch_display", "cursor_position", *POINTER,
           "type", "key", "hold_key", "wait", "read_clipboard", "set_clipboard", "batch", "teach")
# What a batch may contain: the input actions (each one's own screenshot is skipped; one comes at the end).
BATCHABLE = (*POINTER, "type", "key", "hold_key", "wait", "launch", "focus", "screenshot")
SETTLE = 0.45  # how long to let the screen settle before the screenshot that follows an action
GLIDE = 0.22  # seconds the pointer takes to travel to a point
PASTE_OVER = 40  # text longer than this is pasted (clipboard restored after) rather than typed key by key
CLICKS = {"click": ("left", 1), "double_click": ("left", 2), "triple_click": ("left", 3), "right_click": ("right", 1), "middle_click": ("middle", 1)}
VERBS = {"click": "Clicked", "double_click": "Double-clicked", "triple_click": "Triple-clicked", "right_click": "Right-clicked", "middle_click": "Middle-clicked"}


def _xy(input: dict, ax: str = "x", ay: str = "y") -> tuple[float, float]:
    if input.get(ax) is None or input.get(ay) is None:
        raise ToolError(f"This action needs {ax} and {ay} (a point on the latest screenshot).")
    try:
        return float(input[ax]), float(input[ay])
    except (TypeError, ValueError):
        raise ToolError(f"{ax} and {ay} must be numbers from the latest screenshot.")


def _mods(input: dict) -> list[int]:
    raw = str(input.get("modifiers") or "").strip()
    if not raw:
        return []
    try:
        return win.parse_combo(raw)
    except ValueError as e:
        raise ToolError(f"modifiers: {e}")


async def _io(fn, *args):
    """Input and capture block for a moment (the pointer glides): keep them off the event loop."""
    return await asyncio.to_thread(fn, *args)


class ComputerTool(BaseTool):
    spec = ToolSpec(
        name="computer",
        description=(
            "See the screen and use the mouse and keyboard in desktop apps, for things with no file, shell or web path "
            "(native apps, settings, GUI-only tools) — or teach the user to do something themselves. Windows only. The user "
            "approves each app (ask for several up front with `request_access`); web browsers are view-only (use `browser`), "
            "terminals and code editors click-only (use `shell`/`edit`). Coordinates are pixels on the LATEST screenshot "
            "(its size is stated with it); screenshot first, act, look at the result, repeat.\n"
            "Actions: `screenshot` (app:\"Notepad\" for one window), `zoom` (x,y,x2,y2: a region at full detail, for small "
            "text — coordinates still refer to the last screenshot), `apps` (open + approved apps), `request_access` "
            "(apps: [names], reason), `launch`/`focus` (app), `switch_display` (display: 0,1… when there are several "
            "monitors), `cursor_position`, `move`, `click`, `double_click`, `triple_click`, `right_click`, `middle_click` "
            "(x,y; modifiers like \"shift\" or \"ctrl+shift\"), `mouse_down`/`mouse_up` (x,y optional), `drag` (x,y → x2,y2), "
            "`scroll` (x,y, direction, amount notches), `type` (text into the focused field), `key` (\"ctrl+s\", \"alt+Tab\", "
            "\"Enter\"), `hold_key` (key, amount seconds), `wait` (amount seconds), `read_clipboard`, `set_clipboard` (text), "
            "`batch` (actions: a list of these steps as objects, run in order, stopping at the first error, ONE screenshot "
            "at the end — use it whenever you can predict 2+ steps), `teach` (text: what to explain, optional x,y to point "
            "at, title, step/total, actions to run after the user clicks Next — shows a tooltip on screen and waits for "
            "Next or Exit). Set `intent` to a few words; AFH's on-screen cursor shows it. Never change the user's own open "
            "documents or tabs unless asked — start a new document (ctrl+n) for your own work."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS), "description": "What to do (see the list above)."},
                "app": {"type": "string", "description": "For launch/focus/screenshot: an app name (\"Notepad\", \"Spotify\") or a full .exe path."},
                "apps": {"type": "array", "items": {"type": "string"}, "description": "For request_access: the app names to ask for."},
                "reason": {"type": "string", "description": "For request_access: one line on why (shown to the user)."},
                "x": {"type": "number", "description": "X pixel on the latest screenshot."},
                "y": {"type": "number", "description": "Y pixel on the latest screenshot."},
                "x2": {"type": "number", "description": "For drag/zoom: the second X pixel."},
                "y2": {"type": "number", "description": "For drag/zoom: the second Y pixel."},
                "text": {"type": "string", "description": "For type / set_clipboard: the text. For teach: the explanation shown to the user."},
                "title": {"type": "string", "description": "For teach: a short heading for the tooltip."},
                "key": {"type": "string", "description": "For key/hold_key: a combo such as ctrl+s, alt+Tab, Enter, Escape, win+r, f5, shift."},
                "modifiers": {"type": "string", "description": "For clicks/scroll: keys held during it, e.g. \"shift\", \"ctrl\", \"ctrl+shift\"."},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "For scroll."},
                "amount": {"type": "number", "description": "For scroll: notches (default 3). For wait/hold_key: seconds (default 1)."},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "For click/drag/mouse_down/mouse_up (default left)."},
                "display": {"type": "number", "description": "For switch_display: the display number (0 is the main one)."},
                "step": {"type": "number", "description": "For teach: this step's number (shown as step/total)."},
                "total": {"type": "number", "description": "For teach: how many steps the lesson has."},
                "actions": {"type": "array", "items": {"type": "object"},
                            "description": "For batch (and teach, after Next): steps like {\"action\":\"click\",\"x\":10,\"y\":20,\"intent\":\"Open File\"}."},
                "intent": {"type": "string", "description": "A few words on what this does, e.g. \"Save the file\" — shown by AFH's on-screen cursor."},
            },
            "required": ["action"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        if not win.is_supported():
            raise ToolError("The computer tool works on Windows only.")
        if ctx.engine is None:
            raise ToolError("Computer control isn't available in this context.")
        ctrl = controller(ctx.engine)
        if not ctrl.enabled():
            raise ToolError("Computer control is turned off in Settings → Agent → Computer control.")
        action = str_arg(input, "action").strip().lower()
        if action not in ACTIONS:
            raise ToolError(f"Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}.")
        intent = str(input.get("intent") or "").strip()

        if action == "apps":
            return self._apps(ctrl)
        if action == "read_clipboard":
            return ToolResult(text=win.read_clipboard() or "(the clipboard is empty)")
        if action == "set_clipboard":
            win.write_clipboard(str(input.get("text", "")))
            return ToolResult(text="Put the text on the clipboard.")
        if action == "cursor_position":
            shot = ctrl.last_shot.get(ctx.session_id)
            x, y = ctrl.to_shot(shot, *win.cursor_pos())
            return ToolResult(text=f"The pointer is at x={x}, y={y} on the latest screenshot." if shot else
                              f"The pointer is at x={x}, y={y} (desktop pixels; take a screenshot to work in its coordinates).")
        if action == "switch_display":
            return self._switch_display(ctrl, ctx, input)
        if action == "request_access":
            return await self._request_access(ctrl, ctx, input)

        token = ctrl.begin_step(ctx.session_id, intent or self._status(action, input))
        try:
            if action == "teach":
                return await self._teach(ctrl, ctx, input)
            if action == "batch":
                return await self._batch(ctrl, ctx, input)
            if action == "zoom":
                return await self._zoom(ctrl, ctx, input)
            if action == "screenshot":
                return await self._shot(ctrl, ctx, "Screenshot", app=input.get("app"))
            summary = await self._act(ctrl, ctx, action, input, intent)
            await asyncio.sleep(SETTLE)
            return await self._shot(ctrl, ctx, summary)
        finally:
            ctrl.end_step(ctx.session_id, token, asyncio.get_running_loop())

    @staticmethod
    def _status(action: str, input: dict) -> str:
        if action == "batch":
            return f"Doing {len(input.get('actions') or [])} steps"
        if action == "teach":
            return "Showing you how"
        return {"screenshot": "Looking at the screen", "zoom": "Looking closer", "type": "Typing", "key": "Pressing keys",
                "launch": "Opening an app", "wait": "Waiting"}.get(action, action.replace("_", " ").capitalize())

    # ---- one input action (no screenshot): returns what happened ----------------------------

    async def _act(self, ctrl: Controller, ctx: ToolContext, action: str, input: dict, intent: str) -> str:
        sid = ctx.session_id
        if action == "launch":
            return await self._launch(ctrl, ctx, input)
        if action == "focus":
            return await self._focus(ctrl, ctx, input)
        if action == "wait":
            secs = min(30.0, max(0.1, float(input.get("amount", 1) or 1)))
            ctrl.fx(sid, "wait", secs=secs, label=intent or f"Waiting {secs:g}s")
            await asyncio.sleep(secs)
            return f"Waited {secs:g}s"
        if action == "screenshot":
            return "Looked at the screen"

        if action in POINTER:
            shot = ctrl.last_shot.get(sid)
            if not shot:
                raise ToolError("Take a screenshot first — coordinates are pixels on the latest screenshot.")
            if action in ("mouse_down", "mouse_up") and input.get("x") is None:
                px, py = win.cursor_pos()
            else:
                px, py = ctrl.to_physical(shot, *_xy(input))
            app = await self._require(ctrl, ctx, win.window_at(px, py))
            return await self._pointer(ctrl, ctx, action, input, px, py, shot, app, intent)

        if action in ("type", "key", "hold_key"):
            app = await self._require(ctrl, ctx, win.foreground(), typing=True)
            cx, cy = win.cursor_pos()
            if action == "type":
                text = str(input.get("text", ""))
                if not text:
                    raise ToolError("type needs text.")
                ctrl.fx(sid, "type", x=cx, y=cy, text=text[:80], label=intent or f"Typing into {app.name}")
                # long or multi-line text goes in as one paste (fast, and exact in every app); short text is typed
                if (len(text) > PASTE_OVER or "\n" in text) and await _io(win.paste_text, text):
                    return f"Pasted {len(text)} characters into {app.name} (the clipboard was put back)"
                await _io(win.type_text, text)
                return f"Typed {len(text)} characters into {app.name}"
            combo = str_arg(input, "key")
            try:
                vks = win.parse_combo(combo)
            except ValueError as e:
                raise ToolError(str(e))
            if action == "key":
                ctrl.fx(sid, "key", x=cx, y=cy, keys=combo, label=intent)
                await _io(win.press_combo, vks)
                return f"Pressed {combo} in {app.name}"
            secs = min(10.0, max(0.05, float(input.get("amount", 1) or 1)))
            ctrl.fx(sid, "key", x=cx, y=cy, keys=combo, hold=secs, label=intent or f"Holding {combo}")
            win.keys_down(vks)
            try:
                await asyncio.sleep(secs)
            finally:
                win.keys_up(vks)
            return f"Held {combo} for {secs:g}s in {app.name}"
        raise ToolError(f"{action} can't be used here.")

    async def _pointer(self, ctrl, ctx, action, input, px, py, shot: Shot, app, intent) -> str:
        sid = ctx.session_id
        label = intent or action.replace("_", " ").capitalize()
        btn = str(input.get("button") or "left").lower()
        if btn not in win.BUTTONS:
            btn = "left"
        mods = _mods(input)
        if action not in ("mouse_down", "mouse_up") or input.get("x") is not None:
            ctrl.fx(sid, "move", x=px, y=py, label=label, ms=int(GLIDE * 1000))
            await _io(win.glide_to, px, py, GLIDE)

        if action == "move":
            return f"Moved the pointer in {app.name}"
        if action == "scroll":
            n = max(1, min(30, int(input.get("amount", 3) or 3)))
            d = str(input.get("direction") or "down").lower()
            ctrl.fx(sid, "scroll", x=px, y=py, direction=d, amount=n, label=label)
            if mods:
                win.keys_down(mods)
            try:
                win.wheel({"left": -n, "right": n}.get(d, 0), {"up": n, "down": -n}.get(d, 0))
            finally:
                if mods:
                    win.keys_up(mods)
            return f"Scrolled {d} {n} in {app.name}"
        if action in ("mouse_down", "mouse_up"):
            down = action == "mouse_down"
            ctrl.fx(sid, "press" if down else "release", x=px, y=py, button=btn, label=label)
            win.button(btn, down)
            return f"{'Pressed' if down else 'Released'} the {btn} button in {app.name}"
        if action == "drag":
            qx, qy = ctrl.to_physical(shot, *_xy(input, "x2", "y2"))
            ctrl.fx(sid, "drag", x=px, y=py, x2=qx, y2=qy, label=label, ms=450)
            if mods:
                win.keys_down(mods)
            try:
                win.button(btn, True)
                await asyncio.sleep(0.08)
                await _io(win.glide_to, qx, qy, 0.45)
                await asyncio.sleep(0.06)
                win.button(btn, False)
            finally:
                if mods:
                    win.keys_up(mods)
            return f"Dragged in {app.name}"
        name, count = CLICKS[action]
        if action == "click":
            name = btn
        ctrl.fx(sid, "click", x=px, y=py, button=name, count=count, label=label, mods=str(input.get("modifiers") or ""))
        await _io(win.click, name, count, mods)
        return f"{VERBS[action]} in {app.name}"

    async def _launch(self, ctrl, ctx, input) -> str:
        name = str_arg(input, "app")
        app = ctrl.resolve_app(name)
        if not app:
            raise ToolError(f"Couldn't find an app called {name!r}. Use `apps` to see what's open, or give the full path to its .exe.")
        self._guard(app)
        await self._approve(ctrl, ctx, app)
        ctrl.fx(ctx.session_id, "launch", label=f"Opening {app.name}", app=app.name)
        before = {w.hwnd for w in win.windows()}
        was_open = ctrl.window_of(app) is not None
        try:
            win.launch(app.aumid, app.path if app.path and not app.aumid else "")
        except Exception as e:
            raise ToolError(f"Couldn't start {app.name}: {e}")
        target = None
        for _ in range(20):
            await asyncio.sleep(0.4)
            target = next((w for w in win.windows() if not w.tool and w.hwnd not in before and app.matches(w.exe_name, w.aumid)), None)
            if target:
                break
        if target:
            win.focus_window(target.hwnd)
            ctrl.follow(ctx.session_id, target)
            return f"Launched {app.name} in a new window"
        target = ctrl.window_of(app)
        ctrl.follow(ctx.session_id, target)
        if was_open:
            # Apps like the Windows 11 Notepad reuse their open window (and the user's open documents).
            return (f"{app.name} was already open, so Windows brought its existing window forward — it may hold the user's own "
                    f"documents or tabs. Don't change those: look at the screenshot and start a new document first (e.g. ctrl+n "
                    f"or a new tab) unless the user asked you to edit what is open.")
        return f"Launched {app.name}" if target else f"Asked Windows to start {app.name} (no window yet — wait, then screenshot)"

    async def _focus(self, ctrl, ctx, input) -> str:
        name = str_arg(input, "app")
        app = ctrl.resolve_app(name)
        target = ctrl.window_of(app) if app else None
        if not app or not target:
            raise ToolError(f"{name!r} doesn't seem to be open. Launch it first, or check `apps`.")
        self._guard(app)
        await self._approve(ctrl, ctx, app)
        win.focus_window(target.hwnd)
        ctrl.follow(ctx.session_id, target)
        ctrl.fx(ctx.session_id, "focus", label=f"Switched to {app.name}", rect=list(target.rect))
        return f"Brought {app.name} to the front"

    # ---- batch and teach --------------------------------------------------------------------

    async def _run_steps(self, ctrl, ctx, steps: list) -> tuple[list[str], str | None]:
        done: list[str] = []
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):
                return done, f"Step {i + 1} isn't an object like {{\"action\": \"click\", \"x\": 10, \"y\": 20}}."
            act = str(raw.get("action") or "").strip().lower()
            if act not in BATCHABLE:
                return done, f"Step {i + 1}: {act or '(no action)'} can't go in a batch (allowed: {', '.join(BATCHABLE)})."
            try:
                done.append(await self._act(ctrl, ctx, act, raw, str(raw.get("intent") or "").strip()))
            except (ToolError, PermissionDenied, OSError) as e:
                return done, f"Step {i + 1} ({act}) failed: {e}"
            await asyncio.sleep(0.12)
        return done, None

    async def _batch(self, ctrl, ctx, input) -> ToolResult:
        steps = input.get("actions")
        if not isinstance(steps, list) or not steps:
            raise ToolError("batch needs `actions`: a list of steps like {\"action\": \"click\", \"x\": 10, \"y\": 20}.")
        if len(steps) > 40:
            raise ToolError("A batch can hold at most 40 steps.")
        done, err = await self._run_steps(ctrl, ctx, steps)
        await asyncio.sleep(SETTLE)
        lines = [f"{i + 1}. {d}" for i, d in enumerate(done)]
        summary = f"Did {len(done)} of {len(steps)} steps" + (":\n" + "\n".join(lines) if lines else "")
        if err:
            summary += f"\nStopped: {err}"
        result = await self._shot(ctrl, ctx, summary)
        result.is_error = bool(err) and not done
        return result

    async def _teach(self, ctrl, ctx, input) -> ToolResult:
        text = str(input.get("text") or "").strip()
        if not text:
            raise ToolError("teach needs `text`: what to tell the user at this step.")
        step: dict = {"text": text, "title": str(input.get("title") or "").strip()}
        for k in ("step", "total"):
            if input.get(k) is not None:
                try:
                    step[k] = int(input[k])
                except (TypeError, ValueError):
                    pass
        shot = ctrl.last_shot.get(ctx.session_id)
        if input.get("x") is not None and input.get("y") is not None:
            if not shot:
                raise ToolError("Take a screenshot first, so x,y can point at something on it.")
            step["x"], step["y"] = ctrl.to_physical(shot, *_xy(input))
        rect = ctrl.display_rect(ctx.session_id)
        step["display"] = list(rect)
        choice = await ctrl.lesson_step(ctx.session_id, step)
        if choice == "exit":
            return ToolResult(text="The user ended the lesson. Stop teaching and ask if they need anything else.")
        steps = input.get("actions")
        note = "The user clicked Next."
        if isinstance(steps, list) and steps:
            done, err = await self._run_steps(ctrl, ctx, steps)
            note += f" Then did {len(done)} of {len(steps)} steps." + (f" Stopped: {err}" if err else "")
        await asyncio.sleep(SETTLE)
        return await self._shot(ctrl, ctx, note)

    # ---- access, approvals and guards ------------------------------------------------------

    def _guard(self, app: appsmod.App) -> None:
        exe = app.exes[0] if app.exes else ""
        if app.id in appsmod.NEVER or appsmod.never(exe, app.path):
            raise ToolError(f"{app.name} can't be controlled (AFH itself, a Windows security screen, or a password manager).")

    async def _require(self, ctrl, ctx, w, typing=False):
        if not w:
            raise ToolError("Nothing is there to act on — take a screenshot and aim at a window.")
        app = ctrl.app_of_window(w)
        if not app:
            raise ToolError("Couldn't tell which app that is.")
        self._guard(app)
        if self._full_access(ctx):  # Full access: no prompts and no view-only/click-only limits
            return app
        if app.tier == "read":
            raise ToolError(f"{app.name} is view-only for the computer tool (it's a web browser — use the `browser` tool for the web, or the `chrome` tool for the user's own browser, "
                            f"or turn on browser control in Settings → Agent → Computer control).")
        if typing and app.tier == "click":
            raise ToolError(f"{app.name} is click-only (a terminal or code editor): AFH can click in it but not type, so a command can't "
                            f"run outside this thread's rules. Use the `shell` or `edit` tool for its text.")
        await self._approve(ctrl, ctx, app)
        return app

    @staticmethod
    def _tier_note(tier: str) -> str:
        return {"full": "see it, click and type in it", "click": "see it and click in it", "read": "see it"}.get(tier, "use it")

    @staticmethod
    def _full_access(ctx: ToolContext) -> bool:
        """Full access threads never stop to ask about an app and aren't held to view-only/click-only
        tiers; the never-list (AFH, security screens, password managers) still holds. Ask and read-only modes keep their ask/deny rule for edits and shell even after the user
        allows edits, so a thread counts only when no such rule is there."""
        rules = getattr(ctx.permissions, "rules", None)
        return bool(rules) and not any(r.get("effect") in ("ask", "deny") and r.get("action") in ("*", "edit", "shell", "computer")
                                       for r in rules)

    async def _approve(self, ctrl: Controller, ctx: ToolContext, app: appsmod.App) -> None:
        if ctrl.is_allowed(app) or self._full_access(ctx):
            return
        once = ctrl.asked_once.setdefault(ctx.session_id, set())
        if app.id in once:
            return
        decision, message, _ = await ctx.permissions.ask_user("computer", {
            "title": f"Let AFH use {app.name}?",
            "app": app.to_dict(),
            "apps": [app.to_dict()],
            "tierNote": self._tier_note(app.tier),
            "kind": "computer",
        })
        if decision == "always":
            ctrl.allow_app(app)
        elif decision in ("once", "approve", "accept"):
            once.add(app.id)
        else:
            raise PermissionDenied(message or f"You didn't allow AFH to use {app.name}.")

    async def _request_access(self, ctrl: Controller, ctx: ToolContext, input: dict) -> ToolResult:
        names = input.get("apps")
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",")]
        if not isinstance(names, list) or not [n for n in names if str(n).strip()]:
            raise ToolError("request_access needs `apps`: a list of app names, e.g. [\"Notepad\", \"Paint\"].")
        found: list[appsmod.App] = []
        missing: list[str] = []
        blocked: list[str] = []
        for n in [str(n).strip() for n in names if str(n).strip()][:12]:
            app = ctrl.resolve_app(n)
            if not app:
                missing.append(n)
                continue
            exe = app.exes[0] if app.exes else ""
            if app.id in appsmod.NEVER or appsmod.never(exe, app.path):
                blocked.append(app.name)
            elif all(a.id != app.id for a in found):
                found.append(app)
        once = ctrl.asked_once.setdefault(ctx.session_id, set())
        need = [a for a in found if not ctrl.is_allowed(a) and a.id not in once]
        if need and not self._full_access(ctx):
            reason = str(input.get("reason") or "").strip()
            title = f"Let AFH use {need[0].name}?" if len(need) == 1 else f"Let AFH use these {len(need)} apps?"
            decision, message, _ = await ctx.permissions.ask_user("computer", {
                "title": title, "reason": reason, "kind": "computer",
                "app": need[0].to_dict(), "apps": [dict(a.to_dict(), tierNote=self._tier_note(a.tier)) for a in need],
                "tierNote": self._tier_note(need[0].tier),
            })
            if decision == "always":
                for a in need:
                    ctrl.allow_app(a)
            elif decision in ("once", "approve", "accept"):
                once.update(a.id for a in need)
            else:
                raise PermissionDenied(message or "You didn't allow AFH to use those apps.")
        tiers = {"full": "full control", "click": "click only", "read": "view only"}
        full = self._full_access(ctx)
        shown = ", ".join(f"{a.name} ({tiers.get('full' if full else a.tier, a.tier)})" for a in found)
        lines = [f"Allowed: {shown}" if found else "Nothing was allowed."]
        if missing:
            lines.append(f"Not found: {', '.join(missing)} (use `apps`, or a full .exe path)")
        if blocked:
            lines.append(f"Never available: {', '.join(blocked)}")
        return ToolResult(text="\n".join(lines))

    # ---- displays, screenshots and listings -------------------------------------------------

    def _switch_display(self, ctrl: Controller, ctx: ToolContext, input: dict) -> ToolResult:
        ds = win.displays()
        try:
            i = int(input.get("display", 0))
        except (TypeError, ValueError):
            i = -1
        if not 0 <= i < len(ds):
            raise ToolError(f"There {'is' if len(ds) == 1 else 'are'} {len(ds)} display(s): use 0" + (f"–{len(ds) - 1}." if len(ds) > 1 else "."))
        ctrl.display[ctx.session_id] = i
        ctrl.last_shot.pop(ctx.session_id, None)
        d = ds[i]
        return ToolResult(text=f"Now looking at display {i} ({d.width}×{d.height}{', main' if d.primary else ''}). Take a screenshot.")

    async def _shot(self, ctrl: Controller, ctx: ToolContext, summary: str, app: str | None = None) -> ToolResult:
        sid = ctx.session_id
        rect = None
        if app:
            resolved = ctrl.resolve_app(app)
            target = ctrl.window_of(resolved) if resolved else None
            if target:
                rect = target.rect
                ctrl.follow(sid, target)
        rect = rect or ctrl.display_rect(sid)
        shot = await _io(ctrl.screenshot, rect)
        ctrl.fx(sid, "shot", rect=list(rect))
        ctrl.last_shot[sid] = shot
        note = f"{summary}. The screenshot is {shot.width}×{shot.height} pixels — give x,y within that."
        ds = win.displays()
        if len(ds) > 1:
            note += f" (Display {ctrl.display.get(sid, 0)} of {len(ds)}; `switch_display` to look at another.)"
        return ToolResult(text=note, images=[shot.data_uri],
                          metadata={"screenshot": True, "shot": {"w": shot.width, "h": shot.height}})

    async def _zoom(self, ctrl: Controller, ctx: ToolContext, input: dict) -> ToolResult:
        shot = ctrl.last_shot.get(ctx.session_id)
        if not shot:
            raise ToolError("Take a screenshot first — zoom's x,y,x2,y2 are pixels on it.")
        x1, y1 = ctrl.to_physical(shot, *_xy(input))
        x2, y2 = ctrl.to_physical(shot, *_xy(input, "x2", "y2"))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if right - left < 4 or bottom - top < 4:
            raise ToolError("The zoom region is too small: give two opposite corners (x,y and x2,y2).")
        rect = (left, top, right, bottom)
        ctrl.fx(ctx.session_id, "zoom", rect=list(rect))
        z = await _io(ctrl.screenshot, rect)
        return ToolResult(text=f"A close-up of ({input['x']:g},{input['y']:g})–({input['x2']:g},{input['y2']:g}) on the last screenshot, "
                               f"shown at {z.width}×{z.height}. Keep using the full screenshot's coordinates for clicks.",
                          images=[z.data_uri], metadata={"screenshot": True, "zoom": True})

    def _apps(self, ctrl: Controller) -> ToolResult:
        running = ctrl.running_apps()
        allowed = {a.id for a in ctrl.allowed_apps()}
        lines = ["Open apps you can use (✓ = already approved; ● full control, ◐ click-only, ○ view-only):"]
        for a in running:
            if a.id in appsmod.NEVER:
                continue
            mark = "✓" if a.id in allowed else " "
            tier = {"full": "●", "click": "◐", "read": "○"}.get(a.tier, "●")
            lines.append(f"  {mark} {tier} {a.name}")
        if len(lines) == 1:
            lines.append("  (nothing controllable is open — use `launch` to open an app)")
        extra = [a.name for a in ctrl.allowed_apps() if a.id not in {r.id for r in running}]
        if extra:
            lines.append("Approved but not open: " + ", ".join(extra))
        ds = win.displays()
        if len(ds) > 1:
            lines.append("Displays: " + ", ".join(f"{d.index}: {d.width}×{d.height}{' (main)' if d.primary else ''}" for d in ds))
        return ToolResult(text="\n".join(lines))
