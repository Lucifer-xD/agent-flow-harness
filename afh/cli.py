"""The ``afh`` command: the agent in a terminal, over SSH, or in a script or CI job.

    afh                                chat in this folder
    afh run "fix the failing tests"    one task, then exit (the answer on stdout, progress on stderr)
    afh run --json "..."               the same, every event as one JSON line
    afh race "add caching" -m a/x -m b/y --check "pytest -q"     several models, you pick the winner
    afh github add owner/repo          /afh on issues and pull requests (needs the app or afh serve)
    afh threads | show | diff | models | provider | serve | status | install

It talks to AFH's local API. When the desktop app is open it uses that, so threads show up there
live. Otherwise it starts a private backend for as long as the command runs. That backend leaves
schedules and interrupted runs alone, which stay the app's job.

Only the standard library is imported here: the command should start fast, and nothing from the
server may load in this process.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

from . import __version__

HOME = Path(os.environ.get("AFH_HOME") or Path.home() / ".afh")
MODES = {"ask": "ask", "full": "full", "read": "readonly", "readonly": "readonly"}
OK, FAILED, USAGE, TIMED_OUT, INTERRUPTED = 0, 1, 2, 3, 130
NO_APPROVER = "Nobody is at the terminal to approve this. Rerun with --mode full to allow it."
HELP = """Commands:
  /new              start a new thread
  /threads          threads in this folder
  /resume <id>      continue a thread
  /model [ref]      show or change the model (provider/model)
  /mode [m]         show or change approvals: ask, full or read
  /agent [id]       show or change the agent: build, plan, delegate, redteam...
  /diff             files this thread changed
  /cost             tokens and cost of this thread
  /exit             leave
Anything else starting with / goes to the agent, like /goal or /review."""


class CliError(Exception):
    def __init__(self, message: str, code: int = FAILED):
        super().__init__(message)
        self.code = code


# ---- output ---------------------------------------------------------------------------------


def at_terminal() -> bool:
    """Is someone typing here? On Windows isatty() also says yes for an empty stdin (NUL)."""
    if not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt

    handle = ctypes.c_void_p(msvcrt.get_osfhandle(sys.stdin.fileno()))
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_ulong())))


def use_color(stream) -> bool:
    return stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if use_color(sys.stderr) else text


def dim(text: str) -> str:
    return paint("2", text)


def note(text: str = "") -> None:
    """Progress goes to stderr, so stdout holds only the answer and can be piped."""
    print(text, file=sys.stderr, flush=True)


def clip(text: Any, width: int = 100) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= width else line[: width - 1] + "…"


def tool_summary(data: dict | None) -> str:
    """The one detail that says what a tool call is doing."""
    data = data or {}
    for key in ("command", "path", "file_path", "file", "pattern", "query", "url", "action", "prompt", "name"):
        if data.get(key):
            return clip(data[key])
    return clip(next((v for v in data.values() if isinstance(v, str) and v), ""))


def ago(ms: int | float | None) -> str:
    if not ms:
        return ""
    s = max(0, time.time() - ms / 1000)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= size:
            return f"{int(s // size)}{unit} ago"
    return "just now"


def table(rows: Iterable[Iterable[Any]]) -> None:
    rows = [[str(c) for c in r] for r in rows]
    if not rows:
        return
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


# ---- talking to AFH -------------------------------------------------------------------------

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 127.0.0.1 must never go through a proxy


class Client:
    def __init__(self, url: str, key: str, backend: subprocess.Popen | None = None):
        self.url, self.key, self.backend = url.rstrip("/"), key, backend

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "Accept": "application/json"}

    def request(self, method: str, path: str, body: Any = None, params: dict | None = None, timeout: float = 60) -> Any:
        url = self.url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers())
        try:
            with OPENER.open(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read()).get("error") or e.reason
            except ValueError:
                message = e.reason
            raise CliError(str(message)) from None
        except OSError as e:
            raise CliError(f"AFH stopped answering ({e})") from None
        return json.loads(raw) if raw else None

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def close(self) -> None:
        if self.backend and self.backend.poll() is None:
            stop_process(self.backend)


def backend_argv() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "run.py")]


def stop_process(proc: subprocess.Popen) -> None:
    """The backend and whatever it started (MCP servers, background jobs)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGINT)
            proc.wait(timeout=6)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


def start_backend(full: bool = False) -> Client:
    """Light for one command. `full` is the terminal app's: schedules, remote control and the rest, as in the desktop app."""
    env = {**os.environ, "AFH_CLI_BACKEND": "2" if full else "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    # Its own process group: Ctrl+C in the terminal stops the run, not the backend under it.
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen([*backend_argv(), "--headless"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # stdin: it stops when we go
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **group)
    lines: "queue.Queue[str | None]" = queue.Queue()

    def drain() -> None:  # keep reading, or the backend blocks once the pipe fills
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=drain, daemon=True).start()
    seen: list[str] = []
    end = time.time() + 60
    while time.time() < end:
        try:
            line = lines.get(timeout=end - time.time())
        except queue.Empty:
            break
        if line is None:
            break
        seen.append(line.strip())
        m = re.search(r"(http://127\.0\.0\.1:\d+)/#token=(\S+)", line)
        if m:
            return Client(m.group(1), m.group(2), proc)
    stop_process(proc)
    raise CliError("AFH's backend didn't start:\n" + "\n".join(seen[-8:]))


def connect(full: bool = False) -> Client:
    """AFH_URL with AFH_API_KEY when set, else the running app, else a private backend."""
    if os.environ.get("AFH_URL"):
        return Client(os.environ["AFH_URL"], os.environ.get("AFH_API_KEY", ""))
    try:
        found = json.loads((HOME / "api.json").read_text(encoding="utf-8"))
        client = Client(found["url"], found["key"])
        client.request("GET", "/api/sessions", params={"limit": 1}, timeout=4)
        return client
    except (OSError, ValueError, KeyError, CliError):
        return start_backend(full)  # no app, or api.json was left behind by a crash


class Events:
    """The live event stream, read on its own thread so the main one can wait for input."""

    def __init__(self, client: Client):
        self.client = client
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.ready = threading.Event()
        threading.Thread(target=self.read, daemon=True, name="afh-events").start()
        if not self.ready.wait(20):
            raise CliError("Couldn't open AFH's event stream")

    def read(self) -> None:
        while True:
            req = urllib.request.Request(self.client.url + "/api/events", headers=self.client.headers())
            try:
                with OPENER.open(req, timeout=45) as r:  # the server sends a ping every 15 seconds
                    self.ready.set()
                    for raw in r:
                        if raw.startswith(b"data: "):
                            self.queue.put(json.loads(raw[6:]))
            except (OSError, ValueError):
                time.sleep(1)


# ---- following a run ------------------------------------------------------------------------


class Turn:
    """Show one run as it happens, answer what it asks, and report how it ended."""

    def __init__(self, client: Client, events: Events, sid: str, *, as_json: bool = False, quiet: bool = False,
                 thinking: bool = False, interactive: bool | None = None):
        self.client, self.events, self.sid = client, events, sid
        self.as_json, self.quiet, self.thinking = as_json, quiet, thinking
        self.interactive = at_terminal() if interactive is None else interactive
        self.threads = {sid}  # this thread and its helpers
        self.names: dict[str, str] = {}  # tool call id -> tool name
        self.ended = False
        self.error: str | None = None
        self.interrupted = False
        self.at_line_start = True

    def say(self, text: str) -> None:
        if self.as_json or self.quiet:
            return
        sys.stdout.write(text)
        sys.stdout.flush()
        self.at_line_start = text.endswith("\n")

    def status(self, text: str) -> None:
        if self.as_json or self.quiet:
            return
        if not self.at_line_start:
            self.say("\n")
        note(text)

    def handle(self, ev: dict) -> None:
        kind, d = ev.get("type", ""), ev.get("data") or {}
        if kind == "session.created" and d.get("parentID") in self.threads:
            self.threads.add(d.get("sessionID"))
        if d.get("sessionID") not in self.threads:
            return
        if self.as_json:
            print(json.dumps(ev, ensure_ascii=False), flush=True)
        own = d.get("sessionID") == self.sid
        if kind == "session.text.delta" and own:
            self.say(d.get("delta", ""))
        elif kind == "session.text.ended" and own:
            if not self.at_line_start:
                self.say("\n")
        elif kind == "session.reasoning.delta" and own and self.thinking:
            if not (self.as_json or self.quiet):
                sys.stderr.write(dim(d.get("delta", "")))
                sys.stderr.flush()
        elif kind == "session.tool.input.started":
            self.names[d.get("id", "")] = d.get("name", "tool")
        elif kind == "session.tool.called":
            name = self.names.get(d.get("id", ""), "tool")
            self.status(f"{paint('36', '●')} {paint('1', name)} {dim(tool_summary(d.get('input')))}")
        elif kind == "session.tool.failed":
            self.status(paint("31", f"  ✗ {clip(d.get('error') or 'failed', 160)}"))
        elif kind == "session.notice":
            self.status(dim(f"  {clip(d.get('message') or d.get('label') or '', 160)}"))
        elif kind == "session.retry.scheduled":
            self.status(dim(f"  retrying in {d.get('delay', '?')}s"))
        elif kind == "permission.asked":
            self.reply(d)
        elif kind == "session.execution.failed" and own:
            error = d.get("error") or {}
            self.error = error.get("message") or error.get("type") or "The run failed"
            self.ended = True
        elif kind == "session.execution.interrupted" and own:
            self.interrupted = self.ended = True
        elif kind == "session.execution.succeeded" and own:
            self.ended = True

    def reply(self, d: dict) -> None:
        path = f"/api/sessions/{d['sessionID']}/permissions/{d['id']}"
        if d.get("action") == "question":
            self.request_answers(d, path)
        elif not self.interactive:
            self.status(paint("33", f"  refused {d.get('action')}: nobody here to approve it (see --mode)"))
            self.client.request("POST", path, {"decision": "reject", "message": NO_APPROVER})
        else:
            self.ask_approval(d, path)

    def ask_approval(self, d: dict, path: str) -> None:
        what = ", ".join(clip(r, 80) for r in (d.get("resources") or [])[:3])
        self.status(paint("33", f"? Allow {d.get('action')}") + (f" {what}" if what else ""))
        while True:
            answer = input("  [y]es once, [a]lways in this thread, [n]o: ").strip().lower()
            if answer in ("y", "yes"):
                decision, message = "once", None
            elif answer in ("a", "always"):
                decision, message = "always", None
            elif answer in ("n", "no"):
                decision, message = "reject", input("  Tell the agent why (optional): ").strip() or None
            else:
                continue
            self.client.request("POST", path, {"decision": decision, "message": message})
            return

    def request_answers(self, d: dict, path: str) -> None:
        questions = (d.get("metadata") or {}).get("questions") or []
        if not self.interactive:
            self.client.request("POST", path, {"decision": "dismiss", "message": "Nobody is at the terminal. Use your own judgement and say what you assumed."})
            return
        answers = []
        for q in questions:
            self.status(paint("33", f"? {q.get('question')}"))
            options = q.get("options") or []
            for i, o in enumerate(options, 1):
                note(f"  {i}. {o.get('label')}" + (dim(f"  {o['description']}") if o.get("description") else ""))
            raw = input("  Pick a number" + (" or several (1,3)" if q.get("multiple") else "") + ", or type your own answer: ").strip()
            picks = [int(x) for x in re.split(r"[,\s]+", raw) if x.isdigit()] if re.fullmatch(r"[\d,\s]+", raw or "x") else []
            selected = [options[i - 1]["label"] for i in picks if 0 < i <= len(options)]
            answers.append({"selected": selected, "other": "" if selected else raw})
        self.client.request("POST", path, {"decision": "answer", "answers": answers})

    def running(self) -> bool:
        return bool(self.client.get(f"/api/v1/sessions/{self.sid}/reply").get("running"))

    def follow(self, timeout: float | None = None) -> int:
        """Until the run and any autopilot turns after it are over. Ctrl+C stops the run."""
        end = time.time() + timeout if timeout else None
        last_check = time.time()
        while True:
            try:
                try:
                    self.handle(self.events.queue.get(timeout=0.25))
                except queue.Empty:
                    pass
                now = time.time()
                if end and now > end:
                    self.client.request("POST", f"/api/sessions/{self.sid}/interrupt", {})
                    return TIMED_OUT
                if now - last_check > (1 if self.ended else 5):
                    last_check = now
                    if self.events.queue.empty() and not self.running():
                        return FAILED if self.error else INTERRUPTED if self.interrupted else OK
                    self.ended = False if self.ended and not self.error else self.ended
            except KeyboardInterrupt:
                self.status(dim("  stopping..."))
                self.client.request("POST", f"/api/sessions/{self.sid}/interrupt", {})


def result_of(client: Client, sid: str) -> dict:
    s = client.get(f"/api/sessions/{sid}")
    return {"sessionID": sid, "title": s.get("title"), "directory": (s.get("location") or {}).get("directory"),
            "reply": client.get(f"/api/v1/sessions/{sid}/reply").get("reply", ""), "cost": s.get("cost") or 0,
            "tokens": s.get("tokens") or {}, "changedFiles": [f.get("path") or f.get("file") for f in client.get(f"/api/sessions/{sid}/diff") or []]}


def model_of(ref: str | None) -> str | None:
    if ref and "/" not in ref:
        raise CliError('Write the model as provider/model, for example "openrouter/gpt-5". See: afh models', USAGE)
    return ref


def mode_of(name: str | None) -> str | None:
    if name is None:
        return None
    if name not in MODES:
        raise CliError("--mode is ask, full or read", USAGE)
    return MODES[name]


def need_model(client: Client) -> None:
    info = client.get("/api/models")
    if not info.get("models"):
        raise CliError("No model is set up yet. Add one in the AFH app, or with: afh provider add <provider>", USAGE)


# ---- commands -------------------------------------------------------------------------------


def latest_thread(client: Client, directory: str) -> str | None:
    found = client.get("/api/sessions", directory=directory, limit=1)
    return found[0]["id"] if found else None


def cmd_run(client: Client, a: argparse.Namespace) -> int:
    text = " ".join(a.prompt).strip()
    if not at_terminal():
        piped = sys.stdin.read().strip()
        text = f"{text}\n\n{piped}".strip() if piped else text
    if not text:
        raise CliError('Say what to do: afh run "fix the failing tests"', USAGE)
    directory = str(Path(a.dir).resolve())
    if not Path(directory).is_dir():
        raise CliError(f"No such folder: {directory}", USAGE)
    need_model(client)
    if a.goal:
        text = f"/goal {text}"
    sid = a.thread or (latest_thread(client, directory) if a.resume else None)
    model = model_of(a.model)
    # With nobody to answer, "ask" refuses what needs approval instead of hanging.
    mode = mode_of(a.mode)
    if not sid:
        body = {"directory": directory, "agent": a.agent, "model": model, "mode": mode}
        if a.worktree is not None:
            body.update(worktree=True, worktreeName=a.worktree or None)
        sid = client.request("POST", "/api/sessions", body)["id"]
    elif mode:
        client.request("PATCH", f"/api/sessions/{sid}", {"mode": mode})
    events = Events(client)
    turn = Turn(client, events, sid, as_json=a.json, quiet=a.quiet, thinking=a.thinking)
    client.request("POST", f"/api/sessions/{sid}/prompt", {"text": text, "agent": a.agent, "model": model})
    code = turn.follow(a.timeout)
    out = result_of(client, sid)
    if a.json:
        print(json.dumps({"type": "result", "ok": code == OK, "exitCode": code, "error": turn.error, **out}, ensure_ascii=False), flush=True)
    elif a.quiet:
        print(out["reply"])
    if turn.error and not a.json:
        note(paint("31", f"Failed: {turn.error}"))
    if code == TIMED_OUT and not a.json:
        note(paint("33", f"Stopped after {a.timeout:g} seconds."))
    if not (a.json or a.quiet):
        note(dim(f"{sid} · {len(out['changedFiles'])} files changed · ${out['cost']:.4f}"))
    return code


class Chat:
    def __init__(self, client: Client, a: argparse.Namespace):
        self.client, self.a = client, a
        self.directory = str(Path(a.dir).resolve())
        self.sid: str | None = a.thread or (latest_thread(client, self.directory) if a.resume else None)
        self.model, self.agent, self.mode = model_of(a.model), a.agent, mode_of(a.mode)
        self.events = Events(client)

    def thread(self) -> str:
        if not self.sid:
            self.sid = self.client.request("POST", "/api/sessions", {"directory": self.directory, "agent": self.agent, "model": self.model, "mode": self.mode})["id"]
        return self.sid

    def show_model(self) -> str:
        if self.model:
            return self.model
        if self.sid:
            m = self.client.get(f"/api/sessions/{self.sid}").get("model") or {}
            if m.get("id"):
                return f"{m.get('providerID')}/{m['id']}"
        m = self.client.get("/api/models").get("defaultModel") or {}
        return f"{m.get('providerID')}/{m.get('id')}" if m.get("id") else "none"

    def local(self, line: str) -> bool:
        """True when this was one of the terminal's own commands."""
        name, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        if name in ("exit", "quit"):
            raise EOFError
        if name == "help":
            note(HELP)
        elif name == "new":
            self.sid = None
            note(dim("New thread."))
        elif name == "threads":
            cmd_threads(self.client, argparse.Namespace(all=False, dir=self.directory, limit=15, json=False))
        elif name == "resume":
            if not arg:
                note("Which one? /resume <id>, see /threads")
            else:
                self.sid = self.client.get(f"/api/sessions/{arg}")["id"]
                note(dim(f"Back in {self.sid}."))
        elif name == "model":
            if arg:
                self.model = model_of(arg)
                if self.sid:
                    self.client.request("PATCH", f"/api/sessions/{self.sid}", {"model": arg})
            note(dim(f"Model: {self.show_model()}"))
        elif name == "mode":
            if arg:
                self.mode = mode_of(arg)
                if self.sid:
                    self.client.request("PATCH", f"/api/sessions/{self.sid}", {"mode": self.mode})
            note(dim(f"Approvals: {self.mode or 'the default from settings'}"))
        elif name == "agent":
            if arg:
                self.agent = arg
            note(dim(f"Agent: {self.agent or 'the default from settings'}"))
        elif name == "diff":
            show_diff(self.client, self.sid) if self.sid else note("Nothing yet.")
        elif name == "cost":
            if self.sid:
                s = self.client.get(f"/api/sessions/{self.sid}")
                note(f"${s.get('cost') or 0:.4f}, tokens {json.dumps(s.get('tokens') or {})}")
            else:
                note("Nothing yet.")
        else:
            return False
        return True

    def send(self, text: str) -> None:
        sid = self.thread()
        turn = Turn(self.client, self.events, sid, thinking=self.a.thinking, interactive=True)
        self.client.request("POST", f"/api/sessions/{sid}/prompt", {"text": text, "agent": self.agent, "model": self.model})
        code = turn.follow()
        if turn.error:
            note(paint("31", f"Failed: {turn.error}"))
        elif code == INTERRUPTED:
            note(dim("Stopped."))

    def loop(self) -> int:
        need_model(self.client)
        note(f"{paint('1', 'AFH')} {__version__} {dim('·')} {self.directory} {dim('·')} {self.show_model()}")
        note(dim("Type a task. /help for commands, /exit to leave. Ctrl+C stops a run."))
        while True:
            try:
                line = input("\n› ").strip()
                if not line:
                    continue
                if line.startswith("/") and self.local(line):
                    continue
                self.send(line)
            except CliError as err:
                note(paint("31", str(err)))
            except KeyboardInterrupt:
                note()
                return OK
            except EOFError:
                note()
                return OK


def show_diff(client: Client, sid: str) -> None:
    files = client.get(f"/api/sessions/{sid}/diff") or []
    if not files:
        print("No files changed.")
    for f in files:
        print(f.get("path") or f.get("file"))
        patch = f.get("patch") or f.get("diff")
        if patch:
            print(patch)


def cmd_threads(client: Client, a: argparse.Namespace) -> int:
    params: dict = {"limit": a.limit}
    if not a.all:
        params["directory"] = str(Path(a.dir).resolve())
    found = client.get("/api/sessions", **params)
    if a.json:
        print(json.dumps(found, ensure_ascii=False))
    elif not found:
        print("No threads here yet." + ("" if a.all else " See all of them with --all."))
    else:
        table([s["id"], ago((s.get("time") or {}).get("updated")), clip(s.get("title") or "Untitled", 60)] for s in found)
    return OK


def cmd_show(client: Client, a: argparse.Namespace) -> int:
    for m in client.get(f"/api/sessions/{a.id}/messages"):
        if m.get("type") == "user":
            print(f"\n› {m.get('text', '')}")
        elif m.get("type") == "assistant":
            for part in m.get("content") or []:
                if part.get("type") == "text":
                    print(part.get("text", ""))
                elif part.get("type") == "tool":
                    print(f"  ● {part.get('name')} {tool_summary((part.get('state') or {}).get('input'))}")
    return OK


def cmd_diff(client: Client, a: argparse.Namespace) -> int:
    sid = a.id or latest_thread(client, str(Path.cwd()))
    if not sid:
        raise CliError("No thread in this folder yet")
    show_diff(client, sid)
    return OK


def cmd_models(client: Client, a: argparse.Namespace) -> int:
    info = client.get("/api/models")
    if a.json:
        print(json.dumps(info, ensure_ascii=False))
        return OK
    default = info.get("defaultModel") or {}
    table([f"{m.get('providerID')}/{m.get('id')}", "default" if (m.get("id"), m.get("providerID")) == (default.get("id"), default.get("providerID")) else ""]
          for m in info.get("models") or [])
    return OK


def cmd_providers(client: Client, a: argparse.Namespace) -> int:
    info = client.get("/api/providers")
    if a.action == "add":
        if not a.name:
            raise CliError("Which provider? afh provider add openrouter", USAGE)
        key = os.environ.get("AFH_PROVIDER_KEY") or getpass.getpass(f"API key for {a.name} (hidden): ").strip()
        client.request("POST", "/api/providers", {"catalog": a.name, "id": a.name, "api_key": key, "params": {}})
        print(json.dumps(client.request("POST", f"/api/providers/{a.name}/test", {}), ensure_ascii=False))
        return OK
    rows = info.get("configured") or []
    if not rows:
        print("No providers yet. Add one: afh provider add openrouter")
    table([p.get("id"), p.get("name") or ""] for p in rows)
    return OK


def show_race(race: dict) -> None:
    def outcome(e: dict) -> str:
        if e.get("error"):
            return f"error: {clip(e['error'], 40)}"
        if not e.get("changed"):
            return "no changes"
        return {True: "check passed", False: "check failed", None: "not checked"}[e.get("passed")]

    table([[str(i), e["model"], outcome(e), f"{e.get('files', 0)} files", f"{e.get('lines', 0)} lines", f"${e.get('cost') or 0:.4f}", f"{e.get('seconds', 0)}s"]
          for i, e in enumerate(race["entries"], 1)])


def cmd_race(client: Client, a: argparse.Namespace) -> int:
    if a.prompt[:1] in (["pick"], ["discard"], ["show"]):
        return race_action(client, a)
    text = " ".join(a.prompt).strip()
    if not text or len(a.model or []) < 2:
        raise CliError('Say what to do and name two or more models: afh race "add caching" -m a/x -m b/y', USAGE)
    race = client.request("POST", "/api/races", {"directory": str(Path(a.dir).resolve()), "prompt": text, "models": a.model, "check": a.check or "", "mode": mode_of(a.mode) or "full"}, timeout=120)
    note(f"Racing {len(race['entries'])} models." + ("" if client.backend else f" Ctrl+C leaves them running: afh race show {race['id']}"))
    done: set[str] = set()
    while race["status"] == "running":
        time.sleep(1.5)
        race = client.get(f"/api/races/{race['id']}")
        for e in race["entries"]:
            if e["status"] == "finished" and e["session"] not in done:
                done.add(e["session"])
                note(dim(f"  {e['model']} finished"))
    if a.json:
        print(json.dumps(race, ensure_ascii=False))
        return OK
    show_race(race)
    if not at_terminal():
        print(f"\nMerge one: afh race pick {race['id']} <number>   Throw them away: afh race discard {race['id']}")
        return OK
    answer = input("\nMerge which one? Number, or Enter to decide later: ").strip()
    if answer.isdigit():
        pick_entry(client, race, int(answer))
    return OK


def pick_entry(client: Client, race: dict, number: int) -> None:
    if not 0 < number <= len(race["entries"]):
        raise CliError(f"Pick a number from 1 to {len(race['entries'])}", USAGE)
    entry = race["entries"][number - 1]
    done = client.request("POST", f"/api/races/{race['id']}/pick", {"session": entry["session"]}, timeout=120)
    print(f"Merged {entry['model']} into {done['merged']['into']}.")


def race_action(client: Client, a: argparse.Namespace) -> int:
    action, *rest = a.prompt
    if not rest:
        raise CliError(f"Which race? afh race {action} <id>", USAGE)
    race = client.get(f"/api/races/{rest[0]}")
    if action == "show":
        print(f"{race['status']}: {clip(race['prompt'], 80)}")
        show_race(race)
    elif action == "discard":
        client.request("POST", f"/api/races/{race['id']}/discard", {})
        print("Thrown away. Your checkout is unchanged.")
    elif len(rest) < 2 or not rest[1].isdigit():
        raise CliError(f"Which one? afh race pick {race['id']} <number>", USAGE)
    else:
        pick_entry(client, race, int(rest[1]))
    return OK


def cmd_github(client: Client, a: argparse.Namespace) -> int:
    info = client.get("/api/github")
    repos = list(info.get("repos") or [])
    change: dict[str, Any] = {}
    if a.action in ("on", "off"):
        change["enabled"] = a.action == "on"
    elif a.action == "add":
        if not a.values:
            raise CliError("Which repository? afh github add owner/name [--path folder]", USAGE)
        change["repos"] = [r for r in repos if r["repo"] != a.values[0]] + [{"repo": a.values[0], "path": str(Path(a.path).resolve())}]
        change["enabled"] = True
    elif a.action == "remove":
        change["repos"] = [r for r in repos if r["repo"] not in a.values]
    elif a.action == "allow":
        change["allowed"] = a.values
    elif a.action == "mode":
        change["mode"] = a.values[0] if a.values else "ask"
    if change:
        info = client.request("PUT", "/api/github", change)
    print(f"GitHub agent: {'on' if info.get('enabled') else 'off'}, approvals: {info.get('mode')}")
    if info.get("problem"):
        print(f"Problem: {info['problem']}")
    print("Who can start work: " + (", ".join(info.get("who") or []) or "nobody yet"))
    for r in info.get("repos") or []:
        print(f"  {r['repo']}  {r['path']}")
    for t in (info.get("recent") or [])[:8]:
        print(f"  {ago(t.get('time'))}  {t.get('repo')}#{t.get('number')}  {t.get('status')}  {t.get('link') or ''}".rstrip())
    if client.backend and info.get("enabled"):
        note(dim("It watches while the AFH app or afh serve is running."))
    return OK


def cmd_status(client: Client, a: argparse.Namespace) -> int:
    info = client.get("/api/models")
    print(f"AFH {__version__}")
    print("Backend: " + ("private, for this command" if client.backend else f"the running app at {client.url}"))
    print(f"Models: {len(info.get('models') or [])}")
    default = info.get("defaultModel") or {}
    print(f"Default model: {default.get('providerID')}/{default.get('id')}" if default.get("id") else "Default model: none")
    return OK


def cmd_serve(a: argparse.Namespace) -> int:
    return subprocess.call([*backend_argv(), "--headless", *(["--port", str(a.port)] if a.port else [])])


# ---- putting `afh` on the PATH --------------------------------------------------------------


def launcher() -> str:
    """The command a shim runs, quoted."""
    return " ".join(f'"{p}"' for p in backend_argv()) + " cli"


def standalone_installed() -> bool:
    shim = HOME / "bin" / ("afh.cmd" if os.name == "nt" else "afh")
    try:
        return "versions" in shim.read_text(encoding="utf-8") and str(HOME / "cli") in shim.read_text(encoding="utf-8")
    except OSError:
        return False


def install_shim() -> dict:
    """Write ~/.afh/bin/afh and add that folder to the user's PATH (their account only, no admin)."""
    folder = HOME / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    if standalone_installed() and "cli" + os.sep + "versions" not in launcher():
        return {"folder": str(folder), "pathChanged": False, "kept": True}  # the terminal download updates itself: leave it in charge
    if os.name == "nt":
        (folder / "afh.cmd").write_bytes(f"@{launcher()} %*\r\n".encode("utf-8"))
        added = add_to_windows_path(str(folder))
    else:
        shim = folder / "afh"
        shim.write_text(f'#!/bin/sh\nexec {launcher()} "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        added = add_to_shell_profiles(folder)
    return {"folder": str(folder), "pathChanged": added}


def add_to_windows_path(folder: str) -> bool:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        if folder.lower() in [p.strip().lower() for p in current.split(";")]:
            return False
        winreg.SetValueEx(key, "Path", 0, kind, f"{current.rstrip(';')};{folder}".lstrip(";"))
    # Tell Windows the environment changed, so new terminals see it without signing out.
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 2000, None)
    return True


def add_to_shell_profiles(folder: Path) -> bool:
    line = f'export PATH="{folder}:$PATH"  # added by AFH\n'
    changed = False
    for name in (".zprofile", ".bash_profile"):
        profile = Path.home() / name
        text = profile.read_text(encoding="utf-8", errors="replace") if profile.exists() else ""
        if str(folder) not in text:
            with profile.open("a", encoding="utf-8") as f:
                f.write(("" if not text or text.endswith("\n") else "\n") + line)
            changed = True
    return changed


def cmd_update(a: argparse.Namespace) -> int:
    from .tui import update

    return update.cmd_update(a)


def cmd_uninstall(a: argparse.Namespace) -> int:
    from .tui import update

    return update.cmd_uninstall(a)


def tui_ready() -> bool:
    from . import tui

    return tui.available()


def cmd_install(a: argparse.Namespace) -> int:
    done = install_shim()
    print(f"Installed in {done['folder']}. " + ("Open a new terminal and type afh." if done["pathChanged"] else "It's already on your PATH."))
    return OK


# ---- entry ----------------------------------------------------------------------------------


def run_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("-m", "--model", help="provider/model")
    p.add_argument("-d", "--dir", default=".", help="project folder (default: here)")
    p.add_argument("--mode", help="approvals: ask, full or read")
    p.add_argument("--agent", help="build, plan, delegate, redteam or your own")
    p.add_argument("-c", "--continue", dest="resume", action="store_true", help="continue the latest thread in this folder")
    p.add_argument("-t", "--thread", help="continue this thread")
    p.add_argument("--thinking", action="store_true", help="show the model's reasoning")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="afh", description="Agent Flow Harness in your terminal. With no command, chat in this folder.")
    p.add_argument("-v", "--version", action="version", version=f"afh {__version__}")
    p.add_argument("--plain", action="store_true", help="the simple line chat instead of the full-screen app")
    p.add_argument("--tui-check", action="store_true", help=argparse.SUPPRESS)
    run_flags(p)
    sub = p.add_subparsers(dest="command")
    r = sub.add_parser("run", help="do one task, then exit")
    r.add_argument("prompt", nargs="*", help="the task; text piped in is added to it")
    run_flags(r)
    r.add_argument("--json", action="store_true", help="every event as a JSON line, ending with a result line")
    r.add_argument("-q", "--quiet", action="store_true", help="print only the final answer")
    r.add_argument("--goal", action="store_true", help="keep working until the goal is met or blocked")
    r.add_argument("--worktree", nargs="?", const="", help="work in a new git worktree (optionally named)")
    r.add_argument("--timeout", type=float, help="stop after this many seconds")
    t = sub.add_parser("threads", help="list threads in this folder")
    t.add_argument("-a", "--all", action="store_true", help="every project")
    t.add_argument("-d", "--dir", default=".")
    t.add_argument("-n", "--limit", type=int, default=20)
    t.add_argument("--json", action="store_true")
    s = sub.add_parser("show", help="print a thread")
    s.add_argument("id")
    d = sub.add_parser("diff", help="files a thread changed (default: the latest here)")
    d.add_argument("id", nargs="?")
    m = sub.add_parser("models", help="list models")
    m.add_argument("--json", action="store_true")
    sub.add_parser("status", help="what AFH is connected to")
    pr = sub.add_parser("provider", help="list providers, or add one with an API key")
    pr.add_argument("action", nargs="?", choices=["list", "add"], default="list")
    pr.add_argument("name", nargs="?")
    rc = sub.add_parser("race", help="several models on one task, you pick the winner (also: pick, show, discard)")
    rc.add_argument("prompt", nargs="*")
    rc.add_argument("-m", "--model", action="append", help="provider/model, twice or more")
    rc.add_argument("-d", "--dir", default=".")
    rc.add_argument("--check", help="a command that scores each result, like \"pytest -q\"")
    rc.add_argument("--mode", help="approvals for the models: full (default), ask or read")
    rc.add_argument("--json", action="store_true")
    g = sub.add_parser("github", help="work from /afh comments on issues and pull requests")
    g.add_argument("action", nargs="?", choices=["status", "on", "off", "add", "remove", "allow", "mode"], default="status")
    g.add_argument("values", nargs="*", help="owner/repo, logins, or ask/full")
    g.add_argument("--path", default=".", help="the local clone (default: here)")
    sv = sub.add_parser("serve", help="run the backend in this terminal, for SSH or a server")
    sv.add_argument("--port", type=int)
    sub.add_parser("install", help="put the afh command on your PATH")
    sub.add_parser("update", help="install the newest version")
    sub.add_parser("uninstall", help="remove the terminal app; your threads, settings and keys stay")
    return p


def prepare_terminal() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        os.system("")  # turns on ANSI colours in the Windows console


def main(argv: list[str] | None = None) -> int:
    prepare_terminal()
    a = parser().parse_args(argv)
    if a.tui_check:
        from . import tui

        return tui.check()
    offline: dict[str, Callable] = {"serve": cmd_serve, "install": cmd_install, "update": cmd_update, "uninstall": cmd_uninstall}
    if a.command in offline:
        try:
            return offline[a.command](a)
        except (CliError, OSError, ValueError) as err:
            note(paint("31", str(err)))
            return FAILED
    commands: dict[str, Callable] = {"run": cmd_run, "threads": cmd_threads, "show": cmd_show, "diff": cmd_diff, "models": cmd_models,
                                     "provider": cmd_providers, "status": cmd_status, "race": cmd_race, "github": cmd_github}
    client = None
    try:
        if a.command:
            client = connect()
            return commands[a.command](client, a)
        if not a.plain and tui_ready():
            from . import tui

            return tui.run(lambda: connect(True), a)
        client = connect()
        return Chat(client, a).loop()
    except CliError as err:
        note(paint("31", str(err)))
        return err.code
    except KeyboardInterrupt:
        return INTERRUPTED
    except BrokenPipeError:
        return OK
    finally:
        if client:
            client.close()
