"""A thread as the terminal app sees it: the same model the web app keeps in web/js/chat.js.

History from /messages and live events share one shape, so one renderer draws both. Nothing here
touches the screen, which keeps it easy to test.
"""
from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

LIVE_LINES = 14  # lines of a running command's output shown under its row


def now_ms() -> int:
    return int(time.time() * 1000)


def pick(obj: Any, *keys: str) -> Any:
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if obj.get(key) not in (None, ""):
            return obj[key]
    return None


def fmt_tokens(n: float | None) -> str:
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(int(n))


def fmt_cost(usd: float | None) -> str:
    usd = usd or 0
    if not usd:
        return "$0"
    if usd >= 100:
        return f"${usd:.0f}"
    if usd >= 1:
        return f"${usd:.2f}"
    if usd >= 0.01:
        return f"${usd:.3f}"
    return f"${usd:.4f}"


def fmt_dur(ms: float | None) -> str:
    secs = int((ms or 0) / 1000)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {secs % 3600 // 60:02d}m"


def ago(ms: float | None) -> str:
    if not ms:
        return ""
    s = max(0, time.time() - ms / 1000)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= size:
            return f"{int(s // size)}{unit} ago"
    return "just now"


def base_name(path: str | None) -> str:
    return re.split(r"[\\/]", str(path or "").rstrip("\\/"))[-1]


def one_line(text: Any, width: int = 200) -> str:
    line = " ".join(str(text if text is not None else "").split())
    return line if len(line) <= width else line[: width - 1] + "…"


@dataclass
class Change:
    """What an event changed, so the screen redraws only that."""
    all: bool = False
    msg: str | None = None
    stream: bool = False
    status: bool = False
    perm: bool = False
    reload: bool = False


@dataclass
class Thread:
    id: str
    session: dict
    messages: list[dict] = field(default_factory=list)
    by_id: dict[str, dict] = field(default_factory=dict)
    permissions: dict[str, dict] = field(default_factory=dict)
    busy: bool = False
    phase: str | None = None
    error: Any = None
    retry: dict | None = None
    run_start: int | None = None
    tokens: dict | None = None
    compacting: Any = False
    live_tps: float = 0
    tps: float = 0
    todos: list[dict] = field(default_factory=list)
    goal: dict | None = None
    jobs: list[dict] = field(default_factory=list)
    children: dict[str, dict] = field(default_factory=dict)  # child session id -> {title, agent, model, tool}

    def load(self, messages: list[dict], permissions: list[dict], fresh: dict | None) -> None:
        if fresh:
            self.session = {**self.session, **fresh}
        self.messages, self.by_id = [], {}
        for m in messages:
            self.add(m)
        self.permissions = {p["id"]: p for p in permissions or []}
        self.busy = bool(self.session.get("running"))
        if not self.busy:
            self.run_start, self.phase = None, None
        self.tokens = self.session.get("tokens") or self.tokens

    def add(self, m: dict) -> dict:
        if m.get("id") in self.by_id:
            return self.by_id[m["id"]]
        self.by_id[m["id"]] = m
        self.messages.append(m)
        return m

    def assistant(self, mid: str, data: dict | None = None) -> dict:
        m = self.by_id.get(mid)
        if not m:
            data = data or {}
            m = self.add({"id": mid, "type": "assistant", "content": [], "time": {"created": now_ms()}, "agent": data.get("agent"), "model": data.get("model"), "live": True})
        return m

    def finish_live(self) -> None:
        for m in self.messages:
            if m.get("type") != "assistant":
                continue
            m["live"] = False
            for p in m.get("content") or []:
                p["live"] = False
        last = next((m for m in reversed(self.messages) if m.get("type") == "assistant"), None)
        if last and self.run_start:
            last["turnMs"] = now_ms() - self.run_start
        self.run_start = None
        self.live_tps = 0

    def last_text(self) -> str:
        """The answer of the last turn, for copying."""
        for m in reversed(self.messages):
            if m.get("type") == "assistant":
                text = "\n\n".join(p.get("text", "") for p in m.get("content") or [] if p.get("type") == "text").strip()
                if text:
                    return text
        return ""

    def as_markdown(self) -> str:
        lines = []
        for m in self.messages:
            if m.get("type") == "user":
                lines.append(f"## You\n\n{m.get('text', '')}")
            elif m.get("type") == "assistant":
                text = "\n\n".join(p.get("text", "") for p in m.get("content") or [] if p.get("type") == "text")
                if text:
                    lines.append(f"## Assistant\n\n{text}")
        return "\n\n".join(lines)


def part(m: dict, kind: str, ordinal: Any) -> dict:
    for p in m["content"]:
        if p.get("type") == kind and p.get("ordinal") == ordinal:
            return p
    p = {"type": kind, "ordinal": ordinal, "text": "", "live": True, "started": now_ms()}
    m["content"].append(p)
    return p


def tool_part(m: dict, tid: str, name: str | None = None) -> dict:
    for p in m["content"]:
        if p.get("type") == "tool" and p.get("id") == tid:
            if name:
                p["name"] = name
            return p
    p = {"type": "tool", "id": tid, "name": name or "tool", "state": {"status": "streaming", "input": ""}}
    m["content"].append(p)
    return p


def is_stop(err: Any) -> bool:
    if not isinstance(err, dict):
        err = {"message": str(err or "")}
    return bool(re.search(r"interrupt|abort|cancel", f"{err.get('type') or ''} {err.get('message') or ''}", re.I))


def apply_event(t: Thread, ev: dict) -> Change | None:
    """Apply one engine event to the thread. Returns what changed, or None."""
    kind, d = ev.get("type", ""), ev.get("data") or {}
    created = ev.get("created") or now_ms()
    if kind == "session.inbox.enqueued":
        item = d.get("item") or {}
        if item.get("type") == "user" and d.get("inboxID") not in t.by_id:
            payload = item.get("payload") or {}
            t.add({"id": d.get("inboxID"), "type": "user", "text": payload.get("text") or "", "files": payload.get("files"), "time": {"created": created}, "pending": True})
            return Change(all=True)
        return None
    if kind == "session.inbox.delivered":
        m = t.by_id.get(d.get("inboxID"))
        if m:
            m["pending"] = False
        t.phase = "delivered"
        return Change(status=True, msg=m.get("id") if m else None)
    if kind == "session.execution.started":
        t.busy, t.error = True, None
        t.run_start = t.run_start or now_ms()
        if t.phase != "working":
            t.phase = "delivered"
        return Change(status=True)
    if kind in ("session.execution.succeeded", "session.execution.interrupted"):
        t.busy, t.retry = False, None
        t.finish_live()
        return Change(status=True, all=True)
    if kind == "session.execution.failed":
        t.busy, t.retry = False, None
        t.error = d.get("error") or {"message": "The run failed"}
        t.finish_live()
        return Change(status=True, all=True)
    if kind == "session.retry.scheduled":
        if not d.get("assistantMessageID"):
            t.retry = d
            return Change(status=True)
        m = t.assistant(d["assistantMessageID"])
        m["retries"] = [x for x in m.get("retries") or [] if x.get("attempt") != d.get("attempt")] + [{"attempt": d.get("attempt"), "error": d.get("error"), "time": created}]
        m["retrying"] = True
        m["content"] = []
        return Change(msg=m["id"])
    if kind == "session.step.started":
        m = t.assistant(d.get("assistantMessageID"), d)
        m["startedAt"] = d.get("started") or now_ms()
        t.phase = "working"
        return Change(all=True, status=True)
    if kind == "session.served":
        m = t.assistant(d.get("assistantMessageID"))
        m["served"] = {"slug": d.get("slug"), "experience": d.get("experience")}
        return Change(msg=m["id"])
    if kind == "session.step.failed":
        m = t.assistant(d.get("assistantMessageID"))
        m["retrying"] = False
        if is_stop(d.get("error")):
            m["stopped"] = True
        else:
            m["error"] = (d.get("error") or {}).get("message")
        return Change(msg=m["id"])
    if kind == "session.step.ended":
        m = t.assistant(d.get("assistantMessageID"))
        m["retrying"] = False
        m["tokens"] = d.get("tokens")
        if d.get("cost") is not None:
            m["cost"] = d["cost"]
        m["finish"] = d.get("finish")
        m["endedAt"] = now_ms()
        m["durationMs"] = m["endedAt"] - (m.get("startedAt") or (m.get("time") or {}).get("created") or m["endedAt"])
        if m.get("firstDelta"):
            secs = (m["endedAt"] - m["firstDelta"]) / 1000
            tokens = d.get("tokens") or {}
            out = (tokens.get("output") or 0) + (tokens.get("reasoning") or 0)
            if secs > 0.1 and out > 0:
                m["tps"] = t.tps = out / secs
        t.live_tps = 0
        return Change(msg=m["id"], status=True)
    if kind in ("session.reasoning.started", "session.text.started"):
        m = t.assistant(d.get("assistantMessageID"))
        m["retrying"] = False
        part(m, "reasoning" if "reasoning" in kind else "text", d.get("ordinal"))
        return Change(msg=m["id"])
    if kind in ("session.reasoning.delta", "session.text.delta"):
        m = t.assistant(d.get("assistantMessageID"))
        p = part(m, "reasoning" if "reasoning" in kind else "text", d.get("ordinal"))
        p["text"] = (p.get("text") or "") + (d.get("delta") or "")
        now = now_ms()
        m["firstDelta"] = m.get("firstDelta") or now
        m["liveChars"] = (m.get("liveChars") or 0) + len(d.get("delta") or "")
        secs = (now - m["firstDelta"]) / 1000
        if secs > 0.5:
            t.live_tps = m["liveChars"] / 4 / secs  # rough, until the step reports real counts
        return Change(msg=m["id"], stream=True)
    if kind in ("session.reasoning.ended", "session.text.ended"):
        m = t.assistant(d.get("assistantMessageID"))
        p = part(m, "reasoning" if "reasoning" in kind else "text", d.get("ordinal"))
        if d.get("text") is not None:
            p["text"] = d["text"]
        p["live"] = False
        p["ended"] = now_ms()
        return Change(msg=m["id"])
    if kind == "session.tool.input.started":
        m = t.assistant(d.get("assistantMessageID"))
        m["retrying"] = False
        tool_part(m, d.get("id"), d.get("name"))
        return Change(msg=m["id"])
    if kind == "session.tool.input.delta":
        m = t.assistant(d.get("assistantMessageID"))
        p = tool_part(m, d.get("id"))
        if isinstance(p["state"].get("input"), str):
            p["state"]["input"] += d.get("delta") or ""
        return Change(msg=m["id"], stream=True)
    if kind == "session.tool.called":
        m = t.assistant(d.get("assistantMessageID"))
        p = tool_part(m, d.get("id"))
        p["state"] = {"status": "running", "input": d.get("input") or {}, "metadata": {}}
        return Change(msg=m["id"])
    if kind == "session.tool.progress":
        m = t.assistant(d.get("assistantMessageID"))
        p = tool_part(m, d.get("id"))
        p["state"]["metadata"] = {**(p["state"].get("metadata") or {}), **(d.get("metadata") or {})}
        if d.get("content"):
            p["state"]["content"] = d["content"]
        return Change(msg=m["id"], stream=True)
    if kind in ("session.tool.success", "session.tool.failed"):
        m = t.assistant(d.get("assistantMessageID"))
        p = tool_part(m, d.get("id"))
        given = p["state"].get("input")
        given = given if isinstance(given, dict) else {}
        if kind.endswith("success"):
            p["state"] = {"status": "completed", "input": given, "content": d.get("content") or [], "metadata": d.get("metadata")}
        else:
            p["state"] = {"status": "error", "input": given, "error": d.get("error"), "content": d.get("content"), "metadata": d.get("metadata")}
        return Change(msg=m["id"])
    if kind == "session.usage.updated":
        t.tokens = d.get("tokens")
        if d.get("cost") is not None:
            t.session["cost"] = d["cost"]
        return Change(status=True)
    if kind == "session.notice":
        m = d.get("message") or {"id": ev.get("id"), "type": "synthetic", "text": "", "metadata": {"notice": d.get("kind"), "label": d.get("label")}}
        m["time"] = m.get("time") or {"created": created}
        t.add(m)
        return Change(all=True)
    if kind == "session.compaction.started":
        t.compacting = {"done": 0, "total": 0, "messages": d.get("messages")}
        return Change(status=True)
    if kind == "session.compaction.progress":
        t.compacting = {**(t.compacting or {}), "done": d.get("done"), "total": d.get("total")}
        return Change(status=True)
    if kind == "session.compaction.ended":
        t.compacting = False
        return Change(status=True, reload=not d.get("skipped"))
    if kind == "permission.asked":
        t.permissions[d.get("id")] = d
        return Change(perm=True)
    if kind == "permission.replied":
        t.permissions.pop(d.get("id") or d.get("permissionID") or d.get("requestID"), None)
        return Change(perm=True)
    if kind in ("session.model.selected", "session.agent.selected"):
        if d.get("model"):
            t.session["model"] = d["model"]
        if d.get("agent"):
            t.session["agent"] = d["agent"]
        return Change(status=True)
    if kind == "session.todos.updated":
        t.todos = d.get("todos") or []
        return Change(status=True)
    if kind == "session.goal.updated":
        t.goal = d.get("goal")
        return Change(status=True)
    if kind == "session.jobs.updated":
        t.jobs = d.get("jobs") or []
        return Change(status=True)
    if kind == "session.renamed":
        t.session["title"] = d.get("title") or t.session.get("title")
        return Change(status=True)
    return None


# ---- how a tool call reads ------------------------------------------------------------------

HARNESS_VERBS = {
    "list": ("Checked what's installed", "Checking what's installed"), "install_skill": ("Installed skill", "Installing skill"), "remove_skill": ("Removed skill", "Removing skill"),
    "add_mcp": ("Added MCP server", "Adding MCP server"), "remove_mcp": ("Removed MCP server", "Removing MCP server"), "add_command": ("Added command", "Adding command"),
    "remove_command": ("Removed command", "Removing command"), "add_hook": ("Added hook", "Adding hook"), "remove_hook": ("Removed hook", "Removing hook"),
    "add_agent": ("Added agent", "Adding agent"), "remove_agent": ("Removed agent", "Removing agent"),
}
VERBS = {
    "write": ("Wrote", "Writing"), "edit": ("Edited", "Editing"), "multiedit": ("Edited", "Editing"), "patch": ("Patched", "Patching"), "apply_patch": ("Patched", "Patching"),
    "shell": ("Ran", "Running"), "bash": ("Ran", "Running"), "execute": ("Ran code", "Running code"), "read": ("Read", "Reading"), "glob": ("Found files", "Finding files"),
    "grep": ("Searched", "Searching"), "list": ("Listed", "Listing"), "ls": ("Listed", "Listing"), "webfetch": ("Fetched", "Fetching"), "websearch": ("Searched the web", "Searching the web"),
    "skill": ("Loaded skill", "Loading skill"), "question": ("Asked", "Asking"), "design": ("Showed design options", "Preparing design options"), "todowrite": ("Planned", "Planning"),
    "todoread": ("Checked plan", "Checking plan"), "memory": ("Updated project memory", "Updating project memory"),
}
MEMORY_VERBS = {"add": ("Remembered", "Remembering"), "remove": ("Forgot", "Forgetting"), "replace": ("Corrected memory", "Correcting memory"), "list": ("Checked memory", "Checking memory")}
BROWSER_VERBS = {
    "open": ("Opened in browser", "Opening in browser"), "screenshot": ("Took a screenshot", "Taking a screenshot"), "text": ("Read the page", "Reading the page"),
    "click": ("Clicked", "Clicking"), "type": ("Typed into", "Typing into"), "press": ("Pressed", "Pressing"), "scroll": ("Scrolled", "Scrolling"),
    "double_click": ("Double-clicked", "Double-clicking"), "hover": ("Pointed at", "Pointing at"), "drag": ("Dragged", "Dragging"), "back": ("Went back", "Going back"),
    "forward": ("Went forward", "Going forward"), "reload": ("Reloaded", "Reloading"), "evaluate": ("Ran JavaScript", "Running JavaScript"), "console": ("Read the console", "Reading the console"),
    "close": ("Closed the browser tab", "Closing the browser tab"), "network": ("Checked the network", "Checking the network"),
    "sources": ("Read the page's files", "Reading the page's files"),
}
THREADS_VERBS = {"list": ("Looked through your threads", "Looking through your threads"), "read": ("Read the thread", "Reading the thread"),
                 "outline": ("Listed the thread's messages", "Listing the thread's messages"), "search": ("Searched the thread", "Searching the thread")}
CHROME_VERBS = {**BROWSER_VERBS, "open": ("Opened in your browser", "Opening in your browser"), "tabs": ("Listed your tabs", "Listing your tabs"),
                "switch_tab": ("Switched to your tab", "Switching to your tab"), "close": ("Left the tab", "Leaving the tab")}
COMPUTER_VERBS = {
    "screenshot": ("Looked at the screen", "Looking at the screen"), "zoom": ("Looked closer", "Looking closer"), "apps": ("Listed apps", "Listing apps"),
    "request_access": ("Asked to use apps", "Asking to use apps"), "launch": ("Opened an app", "Opening an app"), "focus": ("Switched app", "Switching app"),
    "click": ("Clicked", "Clicking"), "double_click": ("Double-clicked", "Double-clicking"), "right_click": ("Right-clicked", "Right-clicking"), "drag": ("Dragged", "Dragging"),
    "scroll": ("Scrolled", "Scrolling"), "type": ("Typed", "Typing"), "key": ("Pressed keys", "Pressing keys"), "wait": ("Waited", "Waiting"),
    "batch": ("Did several steps", "Doing several steps"), "teach": ("Showed you a step", "Showing you a step"),
}


def tool_input(p: dict) -> dict:
    given = (p.get("state") or {}).get("input")
    return given if isinstance(given, dict) else {}


def kind_of(name: str) -> str:
    if re.fullmatch(r"write|edit|multiedit|patch|apply_patch", name):
        return "edit"
    if re.fullmatch(r"shell|bash|execute|exec|command", name):
        return "run"
    if re.fullmatch(r"read|glob|grep|list|ls", name):
        return "read"
    return "web" if re.search(r"web|fetch", name) else "other"


def short_path(path: Any) -> str:
    return re.sub(r"^.*[\\/](?=[^\\/]+[\\/][^\\/]+$)", "…/", str(path)) if path else ""


def tool_target(p: dict) -> str:
    name = (p.get("name") or "tool").lower()
    given = tool_input(p)
    path = pick(given, "path", "filePath", "file_path", "file")
    if kind_of(name) == "edit" or name == "read":
        return short_path(path)
    if kind_of(name) == "run":
        return str(pick(given, "command", "cmd") or "")
    if re.fullmatch(r"grep|glob|search|find|list|ls", name):
        return str(pick(given, "pattern", "query", "path") or "")
    if name == "browser":
        return str(pick(given, "url", "target", "key", "script", "direction") or "")
    if name == "chrome":
        return str(pick(given, "url", "tab", "target", "key", "script", "direction") or "")
    if re.search(r"web|fetch|browse", name):
        return str(pick(given, "url", "query") or "")
    if re.search(r"task|agent", name):
        return str(pick(given, "description", "prompt") or "")
    if name == "memory":
        return str(pick(given, "text", "old") or "")
    if name == "threads":
        meta = (p.get("state") or {}).get("metadata") or {}
        return str((meta.get("thread") or {}).get("title") or re.sub(r"^ses_\w+$", "", str(pick(given, "thread", "query") or "")))
    if name == "harness":
        return str(pick(given, "source", "name", "id", "url") or "")
    if name == "computer":
        return str(pick(given, "intent", "title", "app", "key", "text", "direction") or "")
    if name == "jobs":
        return str(given.get("id") or "")
    if name == "design":
        return str(given.get("title") or "")
    return next((v for v in given.values() if isinstance(v, str)), "")


def tool_verb(p: dict, live: bool) -> str:
    name = (p.get("name") or "tool").lower()
    given = tool_input(p)
    action = given.get("action")
    if name == "computer":
        pair = COMPUTER_VERBS.get(action, ("Used the computer", "Using the computer"))
    elif name == "browser":
        pair = BROWSER_VERBS.get(action, ("Used the browser", "Using the browser"))
    elif name == "chrome":
        pair = CHROME_VERBS.get(action, ("Used your browser", "Using your browser"))
    elif name == "shell" and given.get("background"):
        pair = ("Started in background", "Starting in background")
    elif name == "jobs":
        pair = {"stop": ("Stopped job", "Stopping job"), "list": ("Listed jobs", "Listing jobs")}.get(action, ("Read job output", "Waiting for job output"))
    elif name == "harness":
        pair = HARNESS_VERBS.get(action, ("Changed AFH setup", "Changing AFH setup"))
    elif name == "memory":
        pair = MEMORY_VERBS.get(action, VERBS["memory"])
    elif name == "threads":
        pair = THREADS_VERBS.get(action or ("read" if given.get("thread") else "list"), THREADS_VERBS["read"])
    else:
        pair = VERBS.get(name, (p.get("name") or "tool", p.get("name") or "tool"))
    return pair[1] if live else pair[0]


def patch_from_strings(old: str, new: str) -> str:
    return "\n".join(list(difflib.unified_diff(str(old).splitlines(), str(new).splitlines(), lineterm="", n=2))[2:])


def tool_patches(p: dict) -> list[dict]:
    """File patches a tool produced: from metadata.files when present, else rebuilt from its input."""
    given = tool_input(p)
    meta = (p.get("state") or {}).get("metadata") or {}
    if isinstance(meta.get("files"), list) and meta["files"]:
        return [{k: f.get(k) for k in ("file", "patch", "additions", "deletions", "status")} for f in meta["files"]]
    file = pick(given, "path", "filePath", "file_path")
    name = (p.get("name") or "").lower()
    direct = pick(given, "patch", "patchText", "diff")
    if direct:
        return [{"file": file or "patch", "patch": direct}]
    if name == "write" and isinstance(given.get("content"), str):
        return [{"file": file, "patch": patch_from_strings("", given["content"]), "status": "added"}]
    old, new = pick(given, "oldString", "old_string", "old"), pick(given, "newString", "new_string", "new")
    if new is not None:
        return [{"file": file, "patch": patch_from_strings(old or "", new), "status": "modified"}]
    if isinstance(given.get("edits"), list):
        return [{"file": file, "patch": patch_from_strings(pick(e, "oldString", "old_string") or "", pick(e, "newString", "new_string") or ""), "status": "modified"} for e in given["edits"]]
    return []


def count_patch(patch: str | None) -> tuple[int, int]:
    added = removed = 0
    for line in (patch or "").split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def tool_text(content: Any) -> str:
    out = []
    for c in content or []:
        if c.get("type") == "text":
            out.append(c.get("text") or "")
        elif c.get("type") == "file":
            out.append(f"[file] {c.get('name') or c.get('uri') or ''}")
    return "\n".join(out).strip()


def live_tail(p: dict) -> str:
    state = p.get("state") or {}
    out = tool_text(state.get("content")) if (state.get("metadata") or {}).get("live") else ""
    return "\n".join(out.rstrip().split("\n")[-LIVE_LINES:]) if out else ""


def input_text(p: dict) -> str:
    given = (p.get("state") or {}).get("input")
    if isinstance(given, str):
        return given
    if not given:
        return ""
    if kind_of((p.get("name") or "").lower()) == "run":
        return str(pick(given, "command", "cmd") or "")
    return json.dumps(given, indent=2, ensure_ascii=False)


def explain_error(err: Any) -> dict:
    """A readable error: what went wrong, why it probably happened, and what to do."""
    e = {"message": err} if isinstance(err, str) else (err or {})
    msg = str(e.get("message") or e.get("type") or "Something went wrong")
    text = f"{e.get('type') or ''} {msg} {e.get('status') or ''}"
    kind = e.get("type") or ""
    title = kind if kind and not re.search(r"error$", kind, re.I) else "The run failed"
    hint = ""
    rules = [
        (r"ConnectionRefused|ECONNREFUSED|ENOTFOUND|fetch failed|unable to connect|network", "Couldn't reach the provider",
         "The model's endpoint didn't answer. If it's a local server, make sure it's running; otherwise check the provider's address in /settings, Models & accounts."),
        (r"\b401\b|unauthori[sz]ed|invalid api key|authentication", "The provider rejected the credentials", "The API key or sign-in for this provider isn't accepted. Reconnect it with /connect."),
        (r"\b429\b|rate ?limit|too many requests", "Rate limited", "The provider is throttling requests. Wait a moment and retry, or switch model with /model."),
        (r"\b402\b|quota|billing|insufficient|credit|subscription plan", "Plan or credit limit", "Your plan doesn't allow this model or has run out of credits. Pick another model or top up with the provider."),
        (r"timeout|timed out|\b504\b", "The provider timed out", "The model took too long to answer. Retry, or try a faster model."),
        (r"context|too long|maximum.*tokens|\b413\b", "The conversation is too long for this model", "Use /compact, /context to trim messages, start a fresh thread, or pick a model with a bigger context window."),
        (r"\b5\d\d\b|internal server|overloaded|unavailable", "The provider had a problem", "That's on their side. Retry in a bit or switch models."),
    ]
    for pattern, heading, advice in rules:
        if re.search(pattern, text, re.I):
            title, hint = heading, advice
            break
    return {"title": title, "message": msg, "hint": hint, "status": e.get("status")}


def context_used(tokens: dict | None) -> int:
    """Tokens the model saw on its last call."""
    t = tokens or {}
    cache = t.get("cache") or {}
    return (t.get("input") or 0) + (cache.get("read") or 0) + (cache.get("write") or 0)
