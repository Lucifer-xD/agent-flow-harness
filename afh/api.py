"""HTTP + SSE API that the AFH UI talks to. Everything runs on the AFH Engine in this process."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.responses import Response as FastResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, cloud, devapi, remote, skills_store, store, transfer
from .engine import agents as agentmod
from .engine import memory as memmod
from .engine import config as provcfg
from .engine import migrate
from .engine.core import engine
from .engine.providers.catalog import STATIC_MODELS, entries as catalog_entries
from .engine.types import ChatMessage, ChatRequest

log = logging.getLogger("afh.api")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Agent Flow Harness API", version=__version__, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
              description="The local API of Agent Flow Harness. Authenticate with an API key from Settings → Developer: `Authorization: Bearer afh_…`.")

# The API can run commands (MCP servers, shell) and write files, so only the AFH window may call it:
# a per-launch token blocks other local pages, and the Host check blocks DNS rebinding.
ACCESS = {"token": None, "hosts": set(), "port": None}
PUBLIC_PATHS = {"/api/remote/login", "/api/remote/ping"}
IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


@app.on_event("startup")
async def _startup() -> None:
    if engine.loop is None:  # the remote listener shares the app; only the first loop owns the engine
        asyncio.create_task(engine.start())


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in PUBLIC_PATHS:
        token = request.headers.get("x-afh-token") or request.query_params.get("token")
        auth = request.headers.get("authorization") or ""
        if not token and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        server = request.scope.get("server") or ("", 0)
        via_remote = remote.state["port"] and server[1] == remote.state["port"]
        if via_remote:
            if token not in remote.state["tokens"]:
                return JSONResponse({"error": "unauthorized", "remote": True}, status_code=401)
        else:
            if ACCESS["hosts"] and request.headers.get("host") not in ACCESS["hosts"]:
                return JSONResponse({"error": "forbidden host"}, status_code=403)
            if ACCESS["token"] and token != ACCESS["token"] and token not in remote.state["tokens"] and not devapi.check(token):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        response = await call_next(request)
    except Exception as exc:  # every failure becomes a JSON error the UI can show
        return error_response(exc)
    if not request.url.path.startswith("/api/"):
        # The UI files: always revalidate (cheap on localhost), so an update is never hidden by a cached copy.
        response.headers["Cache-Control"] = "no-cache"
    return response


def error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, skills_store.SkillsError):
        status = exc.status or 502
    elif isinstance(exc, KeyError):
        status = 404
    elif isinstance(exc, ValueError):
        status = 400
    elif not engine.ready.is_set():
        return JSONResponse({"error": "The engine is restarting — try again in a moment"}, status_code=503)
    else:
        status = 500
        log.exception("request failed")
    message = f"Not found: {exc}" if isinstance(exc, KeyError) else str(exc).split("\n")[0][:500]
    return JSONResponse({"error": message}, status_code=status)


def restart_soon() -> dict:
    asyncio.run_coroutine_threadsafe(engine.restart(), engine.loop)
    return {"ok": True, "restarting": True}


def model_ref(m: dict | str | None) -> dict | None:
    if isinstance(m, str):  # "provider/model" (scripts and the SDKs)
        pid, _, mid = m.partition("/")
        m = {"providerID": pid, "id": mid} if mid else None
    if not m or not m.get("id") or not m.get("providerID"):
        return None
    out = {"id": m["id"], "providerID": m["providerID"]}
    if m.get("variant"):
        out["variant"] = m["variant"]
    return out


def session_or_404(sid: str) -> dict:
    s = engine.store.get_session(sid)
    if not s:
        raise KeyError(sid)
    return s


# ---- app state -------------------------------------------------------------


def models_payload() -> dict:
    names = {pid: p.get("name") or pid for pid, p in provcfg.load()["providers"].items()}
    return {"models": engine.list_models(), "defaultModel": engine.default_model(), "providerNames": names}


def agents_payload() -> list[dict]:
    return [a.to_dict() for a in agentmod.all_agents()]


@app.get("/api/bootstrap")
async def bootstrap():
    settings = store.load_settings()
    out: dict[str, Any] = {"version": __version__, "settings": settings, "ready": engine.ready.is_set(), "error": engine.error, "engine": "afh"}
    for _ in range(600):  # the engine starts in the background; wait up to a minute
        if engine.ready.is_set():
            break
        await asyncio.sleep(0.1)
    out.update(models_payload(), agents=agents_payload(), ready=engine.ready.is_set(), error=engine.error)
    out["providersConfigured"] = bool(provcfg.load()["providers"])
    out["migration"] = {**migrate.available(), "done": bool(((settings.get("migration") or {}).get("opencode") or {}).get("done"))}
    return out


@app.get("/api/settings")
def get_settings():
    return store.load_settings()


@app.put("/api/settings")
def put_settings(patch: dict = Body(...)):
    return store.save_settings(patch)


# ---- projects ----------------------------------------------------------------


@app.post("/api/projects")
def add_project(body: dict = Body(...)):
    path = Path(body["path"]).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Not a folder: {path}")
    settings = store.load_settings()
    projects = [p for p in settings["projects"] if p != str(path)]
    projects.insert(0, str(path))
    return store.save_settings({"projects": projects, "lastProject": str(path)})


@app.delete("/api/projects")
def remove_project(body: dict = Body(...)):
    settings = store.load_settings()
    projects = [p for p in settings["projects"] if p != body["path"]]
    last = settings["lastProject"] if settings["lastProject"] in projects else (projects[0] if projects else None)
    return store.save_settings({"projects": projects, "lastProject": last})


# ---- models & agents -----------------------------------------------------------


@app.get("/api/models")
def get_models():
    return models_payload()


@app.post("/api/models/visibility")
def model_visibility(body: dict = Body(...)):
    """Hide or show models in the picker. No restart: the engine re-reads its config."""
    provcfg.set_hidden(body.get("changes") or [])
    engine.reload_providers()
    engine.publish({"type": "model.updated", "data": {}})
    return {"ok": True}


@app.post("/api/models/refresh")
async def models_refresh():
    from .engine import modelsdev

    await modelsdev.refresh(force=True)
    await engine.refresh_models()
    return models_payload()


@app.get("/api/agents")
def get_agents():
    return agents_payload()


@app.post("/api/agents")
def save_agent(body: dict = Body(...)):
    agent_id = body["id"].strip().lower()
    if not IDENT.match(agent_id):
        raise ValueError("Agent id must be lowercase letters, numbers, - or _")
    settings = store.load_settings()
    if agent_id in {store.LEADER_ID, "build", "plan", "redteam"} or any(d.get("id") == agent_id for d in settings["delegation"].get("delegates", [])):
        raise ValueError("That id is taken by a built-in mode or a delegate")
    entry: dict[str, Any] = {"mode": body.get("mode", "primary"), "name": body.get("name") or agent_id.title()}
    for key in ("description", "system", "color"):
        if body.get(key):
            entry[key] = body[key]
    if body.get("model"):
        entry["model"] = body["model"]  # "provider/model" or a ref
    if body.get("readonly"):
        entry["readonly"] = True
    agents = dict(settings.get("agents") or {})
    agents[agent_id] = entry
    store.save_settings({"agents": agents})
    engine.publish({"type": "agent.updated", "data": {}})
    return {"ok": True, "agents": agents_payload()}


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str):
    settings = store.load_settings()
    agents = {k: v for k, v in (settings.get("agents") or {}).items() if k != agent_id}
    store.replace_setting("agents", agents)
    engine.publish({"type": "agent.updated", "data": {}})
    return {"ok": True, "agents": agents_payload()}


# ---- files (for the live view) ---------------------------------------------------------


@app.get("/api/files/read")
def file_read(path: str):
    """Read a file inside one of the user's project folders (for the Live pane)."""
    target = Path(path).expanduser().resolve()
    roots = [Path(p).resolve() for p in store.load_settings().get("projects", [])] + [(store.AFH_DIR / "worktrees").resolve()]
    if not any(target == r or r in target.parents for r in roots):
        raise ValueError("That file is outside your project folders")
    if not target.is_file():
        return {"content": None, "exists": False}
    data = target.read_bytes()[:2_000_000]
    return {"content": data.decode("utf-8", "replace"), "exists": True, "size": target.stat().st_size}


# ---- sessions ------------------------------------------------------------------


def with_running(s: dict) -> dict:
    return {**s, "running": engine.is_running(s["id"])}


@app.get("/api/sessions")
def list_sessions(directory: str = "", archived: bool = False, limit: int = 200):
    # no directory: the newest threads across every project (the phone app's home list)
    return [with_running(s) for s in engine.store.list_sessions(directory or None, archived=archived, limit=max(1, min(limit, 500)))]


@app.post("/api/sessions")
async def create_session(body: dict = Body(...)):
    kw = dict(title=body.get("title") or None, agent=body.get("agent"), model=model_ref(body.get("model")), mode=body.get("mode"))
    if body.get("worktree"):
        from .engine import worktree as wtmod

        try:
            return await engine.create_worktree_session(body["directory"], name=str(body.get("worktreeName") or "")[:60] or None, **kw)
        except wtmod.GitError as err:
            raise ValueError(str(err)) from None
    return engine.create_session(body["directory"], **kw)


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return with_running(session_or_404(sid))


@app.patch("/api/sessions/{sid}")
def update_session(sid: str, body: dict = Body(...)):
    session_or_404(sid)
    fields: dict[str, Any] = {}
    if "title" in body:
        fields["title"] = body["title"]
    if "archived" in body:
        fields["archived"] = bool(body["archived"])
    if "mode" in body:
        fields["mode"] = body["mode"]
    if ref := model_ref(body.get("model")):
        fields["model"] = ref
    if body.get("agent"):
        fields["agent"] = body["agent"]
    return engine.update_session(sid, **fields) if fields else session_or_404(sid)


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    return engine.delete_session(sid)


@app.post("/api/sessions/{sid}/fork")
def fork_session(sid: str, body: dict = Body(default={})):
    return engine.fork_session(sid, before=body.get("before"))


@app.get("/api/sessions/{sid}/messages")
def get_messages(sid: str):
    session_or_404(sid)
    return engine.store.list_messages(sid)


@app.post("/api/sessions/{sid}/prompt")
async def prompt(sid: str, body: dict = Body(...)):
    files = []
    for p in body.get("files", []):
        path = Path(p)
        entry: dict[str, Any] = {"uri": path.resolve().as_uri(), "name": re.sub(r"^\d{8}-\d{6}-[0-9a-f]{6}-", "", path.name)}
        if path.suffix.lower() in IMAGE_TYPES and path.is_file() and path.stat().st_size < 8_000_000:
            import base64

            mime = IMAGE_TYPES[path.suffix.lower()]
            entry["uri"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
            entry["mime"] = mime
        files.append(entry)
    out = await engine.prompt(sid, body["text"], files or None, agent=body.get("agent"), model=model_ref(body.get("model")))
    return {"ok": True, **({"command": out["command"]} if isinstance(out, dict) and isinstance(out.get("command"), str) else {})}


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
UPLOAD_LIMIT = 25_000_000


def _uploads_dir() -> Path:
    d = store.AFH_DIR / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.post("/api/uploads")
async def upload(request: Request):
    """Save a pasted or dropped file (an image from the clipboard has no path) and return its path."""
    import secrets
    import time

    data = await request.body()
    if not data:
        raise ValueError("Empty upload")
    if len(data) > UPLOAD_LIMIT:
        raise ValueError("That file is over 25 MB")
    from urllib.parse import unquote

    name = re.sub(r"[^\w.\- ]+", "_", unquote(request.headers.get("x-filename") or "pasted.png")).strip(" .")[:80] or "pasted.png"
    folder = _uploads_dir()
    cutoff = time.time() - 30 * 86400  # uploads only matter while you're writing the message: keep a month
    for old in folder.iterdir():
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}-{name}"
    path.write_bytes(data)
    return {"path": str(path), "name": name, "size": len(data)}


@app.get("/api/image")
def image(path: str):
    """An image file for attachment thumbnails."""
    p = Path(path)
    mime = IMAGE_TYPES.get(p.suffix.lower())
    if not mime or not p.is_file():
        raise KeyError(path)
    return FileResponse(p, media_type=mime)


@app.get("/api/design/file")
def design_file(path: str):
    """A design mockup for the picker card: only HTML under a project's .afh/designs folder."""
    p = Path(path).resolve()
    parts = [x.lower() for x in p.parts]
    inside = any(parts[i] == ".afh" and parts[i + 1] == "designs" for i in range(len(parts) - 2))
    if p.suffix.lower() not in (".html", ".htm") or not inside or not p.is_file() or p.stat().st_size > 3 * 1024 * 1024:
        raise KeyError(path)
    return {"html": p.read_text(encoding="utf-8", errors="replace")}


@app.post("/api/transcribe")
async def transcribe(request: Request):
    """Speech to text for the mic button, through a Whisper-style endpoint of a provider you set up."""
    from .engine import voice

    data = await request.body()
    if not data:
        raise ValueError("No audio recorded")
    return {"text": await voice.transcribe(data, request.headers.get("content-type") or "audio/webm", store.load_settings())}


@app.post("/api/sessions/{sid}/interrupt")
async def interrupt(sid: str):
    engine.interrupt(sid)
    return {"ok": True}


@app.get("/api/sessions/{sid}/diff")
def session_diff(sid: str):
    session_or_404(sid)
    return engine.diff(sid)


@app.get("/api/sessions/{sid}/usage")
def session_usage(sid: str):
    session_or_404(sid)
    return engine.usage(sid)


@app.get("/api/sessions/{sid}/permissions")
def pending_permissions(sid: str):
    return [r.to_dict() for r in engine.pending.values() if r.session_id == sid]


@app.post("/api/sessions/{sid}/permissions/{rid}")
async def reply_permission(sid: str, rid: str, body: dict = Body(...)):
    req = engine.pending.get(rid)
    if not req:
        raise KeyError(rid)
    req.reply(body["decision"], body.get("message"), body.get("answers"))
    return {"ok": True}


@app.get("/api/sessions/{sid}/harness")
def harness(sid: str):
    """Exactly what the model is told in this thread."""
    session = session_or_404(sid)
    agent = engine.agent_for(session)
    directory = session["location"]["directory"]
    system_messages = [{"text": m.get("text", ""), "sources": (m.get("metadata") or {}).get("instructionSources", [])}
                       for m in engine.store.list_messages(sid) if m.get("type") in ("system", "synthetic")]
    tools = []
    try:
        tools = [t.spec.name for t in engine.tools_for(session, agent)]
    except Exception as err:
        log.info("tools for harness: %s", err)
    return {
        "agent": agent.id,
        "model": session.get("model"),
        "systemPrompt": engine.system_prompt_for(session, agent),
        "agentPrompt": agent.system,
        "globalInstructions": store.read_text(store.GLOBAL_AGENTS_MD),
        "projectInstructions": store.read_text(Path(directory) / "AGENTS.md"),
        "memory": engine.read_memory(engine.memory_project(sid)),
        "memoryPath": str(memmod.path_for(engine.memory_project(sid))),
        "personalization": store.read_text(store.PERSONALIZATION_PATH),
        "systemMessages": system_messages,
        "permissions": session.get("permissions"),
        "tools": tools,
    }


@app.get("/api/sessions/{sid}/children")
def session_children(sid: str):
    return engine.store.list_sessions(parent_id=sid, limit=50)


# ---- context editing & undo ---------------------------------------------------------------


@app.get("/api/sessions/{sid}/context")
def session_context(sid: str):
    session_or_404(sid)
    return engine.context(sid)


@app.put("/api/sessions/{sid}/messages")
def replace_messages(sid: str, body: dict = Body(...)):
    """Rewrite the thread's history (the context editor). The session keeps its id."""
    session_or_404(sid)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Nothing left in the thread")
    return engine.replace_messages(sid, messages)


@app.post("/api/sessions/{sid}/revert")
def revert_stage(sid: str, body: dict = Body(...)):
    session_or_404(sid)
    return engine.revert_stage(sid, body["messageId"], files=bool(body.get("files", True)))


@app.post("/api/sessions/{sid}/revert/commit")
def revert_commit(sid: str):
    engine.revert_commit(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/revert/clear")
def revert_clear(sid: str):
    engine.revert_clear(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/shell")
async def shell(sid: str, body: dict = Body(...)):
    session_or_404(sid)
    command = str(body.get("command") or "").strip()
    if not command:
        raise ValueError("Say what to run")
    return await engine.run_shell(sid, command)


@app.post("/api/sessions/{sid}/compact")
async def compact(sid: str):
    session_or_404(sid)
    return {"ok": await engine.compact_now(sid)}


# ---- to-do list & goal ------------------------------------------------------------------------


@app.get("/api/sessions/{sid}/todos")
def get_todos(sid: str):
    session_or_404(sid)
    return engine.todos(sid)


@app.put("/api/sessions/{sid}/todos")
def put_todos(sid: str, body: dict = Body(...)):
    """The user edited the list: the model is told on its next call."""
    session_or_404(sid)
    todos = body.get("todos")
    if not isinstance(todos, list):
        raise ValueError("todos must be a list")
    return engine.set_todos(sid, todos, by="user")


@app.get("/api/sessions/{sid}/goal")
def get_goal(sid: str):
    session_or_404(sid)
    return engine.goal(sid)


@app.put("/api/sessions/{sid}/goal")
async def put_goal(sid: str, body: dict = Body(...)):
    """Set (or replace) the thread's goal; `start` also sends the first message toward it."""
    session_or_404(sid)
    goal = engine.set_goal(sid, str(body.get("text") or ""), str(body.get("criteria") or ""), bool(body.get("autopilot", True)), body.get("maxTurns"))
    if body.get("start") and not engine.is_running(sid):
        text = str(body.get("message") or "").strip() or f"Work toward the goal of this thread:\n\n{goal['text']}"
        await engine.prompt(sid, text)
    return goal


@app.patch("/api/sessions/{sid}/goal")
def patch_goal(sid: str, body: dict = Body(...)):
    session_or_404(sid)
    if not engine.goal(sid):
        raise KeyError("goal")
    fields: dict[str, Any] = {}
    if "autopilot" in body:
        fields["autopilot"] = bool(body["autopilot"])
        fields["exhausted"] = False
    if "maxTurns" in body:
        fields["maxTurns"] = max(1, min(100, int(body["maxTurns"] or 10)))
    status = body.get("status") if body.get("status") in ("active", "achieved", "blocked", "paused") else None
    if status == "active":
        fields.update(turns=0, exhausted=False)
    return engine.update_goal(sid, status=status, **fields)


@app.delete("/api/sessions/{sid}/goal")
def delete_goal(sid: str):
    session_or_404(sid)
    engine.clear_goal(sid)
    return {"ok": True}


# ---- background jobs ------------------------------------------------------------------------------


@app.get("/api/sessions/{sid}/jobs")
def session_jobs(sid: str):
    return [j.to_dict(tail=300) for j in engine.jobs.for_session(sid)]


@app.get("/api/jobs/{jid}")
def job_output(jid: str, tail: int = 20000):
    job = engine.jobs.jobs.get(jid)
    if not job:
        raise KeyError(jid)
    return job.to_dict(tail=max(100, min(tail, 200_000)))


@app.post("/api/jobs/{jid}/stop")
async def job_stop(jid: str):
    job = engine.jobs.jobs.get(jid)
    if not job:
        raise KeyError(jid)
    await engine.jobs.stop(job)
    return job.to_dict(tail=2000)


@app.delete("/api/jobs/{jid}")
def job_forget(jid: str):
    engine.jobs.remove(jid)
    return {"ok": True}


# ---- worktrees --------------------------------------------------------------------------------------


def _worktree_of(sid: str) -> dict:
    session_or_404(sid)
    wt = engine._afh(sid).get("worktree")
    if not wt:
        raise ValueError("This thread does not use a worktree")
    return wt


@app.get("/api/bugreport")
def bugreport_preview():
    from . import bugreport

    return bugreport.preview()


@app.post("/api/bugreport")
def bugreport_create(body: dict = Body(default={})):
    """Make the zip in Downloads and show it in the file manager."""
    import subprocess
    import sys

    from . import bugreport

    path = bugreport.build(str(body.get("description") or ""), include_log=body.get("includeLog", True) is not False)
    if body.get("reveal", True):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    return {"path": str(path), "size": path.stat().st_size}


@app.post("/api/reveal")
def reveal(body: dict = Body(...)):
    """Open a project or worktree folder in the system file manager."""
    import subprocess
    import sys

    target = Path(str(body.get("path") or "")).expanduser().resolve()
    roots = [Path(p).resolve() for p in store.load_settings().get("projects", [])] + [(store.AFH_DIR / "worktrees").resolve()]
    if not any(target == r or r in target.parents for r in roots):
        raise ValueError("That folder is outside your projects")
    if not target.exists():
        raise ValueError(f"{target} does not exist")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True}


@app.get("/api/git/check")
async def git_check(directory: str):
    from .engine import worktree as wtmod

    root = await wtmod.repo_root(directory)
    return {"repo": bool(root), "root": root}


@app.get("/api/sessions/{sid}/worktree")
async def worktree_status(sid: str):
    from .engine import worktree as wtmod

    wt = _worktree_of(sid)
    return {**wt, **await wtmod.status(wt)}


@app.post("/api/sessions/{sid}/worktree/merge")
async def worktree_merge(sid: str):
    from .engine import worktree as wtmod

    wt = _worktree_of(sid)
    if engine.is_running(sid):
        raise ValueError("Wait for the thread to finish before merging")
    title = (session_or_404(sid).get("title") or "AFH thread").strip()
    try:
        return await wtmod.merge(wt, title)
    except wtmod.GitError as err:
        raise ValueError(str(err)) from None


@app.post("/api/sessions/{sid}/worktree/remove")
async def worktree_remove(sid: str, body: dict = Body(default={})):
    from .engine import worktree as wtmod

    wt = _worktree_of(sid)
    st = await wtmod.status(wt)
    if (st["dirty"] or (st["ahead"] and not st["merged"])) and not body.get("force"):
        raise ValueError(f"The worktree has {len(st['dirty'])} changed file(s) and {st['ahead']} unmerged commit(s). Merge first, or remove anyway.")
    await wtmod.remove(wt, delete_branch=True)
    return {"ok": True}


# ---- slash commands --------------------------------------------------------------------------------


@app.get("/api/commands")
def list_commands(directory: str | None = None):
    from .engine import commands as cmdmod

    return cmdmod.all_commands(directory)


@app.put("/api/commands")
def save_commands(body: dict = Body(...)):
    from .engine import commands as cmdmod

    out = []
    for c in body.get("commands") or []:
        name = str(c.get("name") or "").strip().lstrip("/").lower()
        if not cmdmod.NAME.match(name):
            raise ValueError(f"Command name '{name}' must be lowercase letters, numbers, - or _")
        if any(b["name"] == name for b in cmdmod.BUILTINS):
            raise ValueError(f"/{name} is built in")
        if not str(c.get("prompt") or "").strip():
            raise ValueError(f"/{name} needs a prompt")
        out.append({"name": name, "description": str(c.get("description") or "").strip(), "prompt": str(c["prompt"]).strip()})
    store.save_settings({"commands": out})
    return cmdmod.all_commands(body.get("directory"))


# ---- usage & cost ------------------------------------------------------------------------------------


@app.get("/api/usage/summary")
def usage_summary(days: int = 30):
    import datetime as dt

    days = max(1, min(days, 365))
    start = int(dt.datetime.combine(dt.date.today() - dt.timedelta(days=days - 1), dt.time()).timestamp() * 1000)
    by_day: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    zero = lambda: {"steps": 0, "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0, "unpriced": 0}  # noqa: E731
    for r in engine.store.usage_rows(start):
        day = dt.date.fromtimestamp(r["created"] / 1000).isoformat()
        key = f"{r['provider']}/{r['model']}"
        for bucket in (by_day.setdefault(day, zero()), by_model.setdefault(key, {**zero(), "providerID": r["provider"], "id": r["model"]})):
            bucket["steps"] += 1
            bucket["input"] += r["input"] or 0
            bucket["output"] += r["output"] or 0
            bucket["cacheRead"] += r["cache_read"] or 0
            bucket["cacheWrite"] += r["cache_write"] or 0
            if r["cost"] is None:
                bucket["unpriced"] += 1
            else:
                bucket["cost"] += r["cost"]
    models = sorted(by_model.values(), key=lambda m: (-m["cost"], -m["steps"]))
    for m in models:
        ref = {"providerID": m["providerID"], "id": m["id"]}
        m["price"] = engine.price_for(ref)
        m["plan"] = pricing_is_plan(m["providerID"])
        found = engine.find_model(ref)
        m["name"] = found.name if found else m["id"]
    total = sum(m["cost"] for m in models)
    return {"days": [{"day": d, **v} for d, v in sorted(by_day.items())], "models": models, "total": total, "since": start,
            "today": engine.store.cost_since(int(dt.datetime.combine(dt.date.today(), dt.time()).timestamp() * 1000)), "budget": store.load_settings().get("budget")}


@app.get("/api/usage/limits")
async def usage_limits(provider: str = "", force: bool = False):
    """Plan limits, balances and rate limits per provider (engine/usage.py): one provider, or all of them."""
    from .engine import usage as usagemod

    ids = [provider] if provider else list(engine.providers)
    if provider and provider not in engine.providers:
        raise KeyError(provider)
    reports = await asyncio.gather(*(usagemod.report(engine.providers[pid].config, engine.store, force) for pid in ids))
    return reports[0] if provider else {"providers": list(reports)}


def pricing_is_plan(pid: str) -> bool:
    from .engine import pricing

    return pricing.is_plan(provcfg.entry(pid or "") or {}, pid or "")


@app.put("/api/providers/{pid}/prices")
def set_price(pid: str, body: dict = Body(...)):
    """Set (or clear, with price=null) the USD-per-1M-token price of one model."""
    from .engine import pricing

    p = provcfg.entry(pid)
    if not p:
        raise KeyError(pid)
    mid = str(body.get("model") or "")
    if not mid:
        raise ValueError("model is required")
    prices = dict(p.get("prices") or {})
    price = pricing.clean_price(body.get("price"))
    if price:
        prices[mid] = price
    else:
        prices.pop(mid, None)
    patch: dict[str, Any] = {"prices": prices}
    if "plan" in body:
        patch["plan"] = bool(body["plan"])
    provcfg.upsert(pid, patch)
    return {"ok": True, "prices": prices}


# ---- prompts ------------------------------------------------------------------------------


@app.get("/api/prompts")
def get_prompts(directory: str | None = None):
    settings = store.load_settings()
    return {
        "system": store.system_prompt(settings),
        "systemIsDefault": not (settings.get("prompts", {}).get("system") or "").strip(),
        "defaultSystem": store.DEFAULT_SYSTEM_PROMPT,
        "planRules": store.PLAN_RULES.strip(),
        "agentOverrides": settings.get("prompts", {}).get("agents", {}),
        "agents": agents_payload(),
        "globalInstructions": store.read_text(store.GLOBAL_AGENTS_MD),
        "globalInstructionsPath": str(store.GLOBAL_AGENTS_MD),
        "projectInstructions": store.read_text(Path(directory) / "AGENTS.md") if directory else "",
        "projectInstructionsPath": str(Path(directory) / "AGENTS.md") if directory else None,
    }


@app.put("/api/prompts/system")
def set_system_prompt(body: dict = Body(...)):
    """The harness prompt every model gets. Empty text restores the built-in default."""
    text = (body.get("text") or "").strip()
    prompts = store.load_settings().get("prompts", {})
    prompts["system"] = "" if text == store.DEFAULT_SYSTEM_PROMPT.strip() else text
    store.save_settings({"prompts": prompts})
    engine.publish({"type": "agent.updated", "data": {}})
    return {"ok": True}


@app.put("/api/prompts/agent/{agent_id}")
def set_agent_prompt(agent_id: str, body: dict = Body(...)):
    """Replace one mode's prompt entirely (empty = back to the harness prompt)."""
    text = (body.get("system") or "").strip()
    prompts = store.load_settings().get("prompts", {})
    agents = dict(prompts.get("agents", {}))
    if text:
        agents[agent_id] = text
    else:
        agents.pop(agent_id, None)
    prompts["agents"] = agents
    store.save_settings({"prompts": prompts})
    engine.publish({"type": "agent.updated", "data": {}})
    return {"ok": True}


@app.put("/api/prompts/global")
def set_global_instructions(body: dict = Body(...)):
    store.write_text_with_backup(store.GLOBAL_AGENTS_MD, body.get("text", ""))
    return {"ok": True}


@app.put("/api/prompts/project")
def set_project_instructions(body: dict = Body(...)):
    directory = Path(body["directory"])
    if not directory.is_dir():
        raise ValueError("Project folder not found")
    store.write_text_with_backup(directory / "AGENTS.md", body.get("text", ""))
    return {"ok": True}


# ---- project memory ---------------------------------------------------------------------------


def memory_payload(directory: str) -> dict:
    text = engine.read_memory(directory)
    return {"text": text, "facts": len(memmod.facts(text)), "items": memmod.facts(text), "notes": memmod.notes(text),
            "path": str(memmod.path_for(directory)), "inGit": memmod.keep_out_of_git(directory)}


@app.get("/api/projects/memory")
def get_memory(directory: str):
    """The facts the agent keeps about a project (<project>/.afh/memory.md)."""
    return memory_payload(directory)


@app.put("/api/projects/memory")
def set_memory(body: dict = Body(...)):
    directory = str(body["directory"])
    if not Path(directory).is_dir():
        raise ValueError("Project folder not found")
    if isinstance(body.get("facts"), list):  # the Memory dialog's list: facts change, the user's notes stay
        items = [" ".join(str(f).split()) for f in body["facts"]]
        engine.set_memory_facts(directory, [f for f in items if f], by="user")
    else:
        engine.save_memory(directory, body.get("text", ""), by="user")
    return memory_payload(directory)


# ---- computer control ----------------------------------------------------------------------


@app.get("/api/computer/apps")
def computer_apps():
    """What the computer tool can see: whether it's supported and on, and the apps open now / already allowed."""
    from .engine.computer import win as cwin
    from .engine.computer.control import controller

    if not cwin.is_supported():
        return {"supported": False, "enabled": False, "running": [], "allowed": []}
    ctrl = controller(engine)
    cfg = engine.settings().get("computer") or {}
    return {
        "supported": True,
        "enabled": cfg.get("enabled", True) is not False,
        "browserControl": bool(cfg.get("browserControl")),
        "running": [a.to_dict() for a in ctrl.running_apps()],
        "allowed": [a.to_dict() for a in ctrl.allowed_apps()],
    }


@app.post("/api/computer/allow")
def computer_allow(body: dict = Body(...)):
    from .engine.computer.apps import App
    from .engine.computer.control import controller

    ctrl = controller(engine)
    if body.get("app"):
        ctrl.allow_app(App.from_dict(body["app"]))
    elif body.get("query"):
        app = ctrl.resolve_app(str(body["query"]))
        if app:
            ctrl.allow_app(app)
    return {"ok": True}


@app.post("/api/computer/forget")
def computer_forget(body: dict = Body(...)):
    from .engine.computer.control import controller

    controller(engine).forget_app(str(body.get("id", "")))
    return {"ok": True}


@app.get("/api/computer/icon")
def computer_icon(path: str = "", size: int = 64):
    """An app's own icon (from its .exe) for the approval cards; 404 when it has none."""
    from .engine.computer import win as cwin

    png = cwin.exe_icon_png(path, max(16, min(256, size))) if cwin.is_supported() and path.lower().endswith(".exe") else None
    if not png:
        raise KeyError("icon")
    return FastResponse(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/computer/teach")
def computer_teach(body: dict = Body(...)):
    """The user clicked Next or Exit on a lesson tooltip."""
    from .engine.computer.control import controller

    return {"ok": controller(engine).lesson_reply(str(body.get("id", "")), str(body.get("choice", "next")))}


# ---- providers -----------------------------------------------------------------------------


def _provider_view(pid: str, p: dict) -> dict:
    out = provcfg.public(p)
    out["id"] = pid
    out["models"] = sorted((m.to_dict() | {"overridden": m.id in (p.get("overrides") or {})} for m in provcfg.models_of(p, pid)), key=lambda m: (m["hidden"], m["name"].lower()))
    out["connected"] = pid in engine.providers
    cat = catalog_entries().get(p.get("catalog") or "")
    out["catalog"] = p.get("catalog") if cat else None
    out["params"] = p.get("params") or {}
    out["paramFields"] = (cat or {}).get("params", [])
    out["login"] = (cat or {}).get("login")
    return out


@app.get("/api/providers")
def providers():
    configured = provcfg.load()["providers"]
    catalog = [{"id": pid, "name": k["name"], "kind": k["kind"], "base_url": k["base_url"], "docs": k.get("docs"), "needsKey": k.get("needs_key", True),
                "env": k.get("env", []), "configured": pid in configured, "customUrl": bool(k.get("custom_url")), "params": k.get("params", []),
                "hint": k.get("hint"), "login": k.get("login"), "source": k.get("source"), "models": k.get("models_count") or len(STATIC_MODELS.get(pid, []))}
               for pid, k in catalog_entries().items()]
    return {"catalog": catalog, "configured": sorted((_provider_view(pid, p) for pid, p in configured.items()), key=lambda p: p["name"].lower())}


def _parse_models(value: Any) -> list[dict]:
    if isinstance(value, str):
        value = [m.strip() for m in re.split(r"[,\n]", value) if m.strip()]
    out = []
    for m in value or []:
        if isinstance(m, str):
            out.append({"id": m, "name": m})
        elif isinstance(m, dict) and m.get("id"):
            out.append({k: v for k, v in m.items() if k in ("id", "name", "context", "output", "tools", "reasoning", "variants", "input")})
    return out


@app.post("/api/providers")
async def save_provider(body: dict = Body(...)):
    """Add or update a provider: a catalog one (just the key) or a custom endpoint."""
    catalog_id = body.get("catalog")
    pid = (body.get("id") or catalog_id or "").strip().lower()
    if not IDENT.match(pid):
        raise ValueError("Provider id must be lowercase letters, numbers, - or _")
    patch: dict[str, Any] = {}
    if catalog_id:
        k = catalog_entries().get(catalog_id)
        if not k:
            raise ValueError(f"Unknown provider {catalog_id}")
        patch.update(name=body.get("name") or k["name"], kind=k["kind"], base_url=(body.get("base_url") or "").strip() or k["base_url"], headers=dict(k.get("headers", {})),
                     extra=dict(k.get("extra", {})), fetch_models=k.get("fetch_models", True), catalog=catalog_id)
        if k.get("params"):  # account details the endpoint URL is built from (resource name, region, ...)
            given = body.get("params") if isinstance(body.get("params"), dict) else {}
            params = {f["name"]: str(given.get(f["name"]) or f.get("default") or "").strip() for f in k["params"]}
            missing = [f["label"] for f in k["params"] if not params[f["name"]] and not os.environ.get(f["name"])]
            if missing:
                raise ValueError("Fill in " + ", ".join(missing))
            patch["params"] = params
    else:
        base = (body.get("base_url") or "").strip()
        if not base.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        kind = body.get("kind") if body.get("kind") in ("openai", "anthropic", "gemini") else "openai"
        patch.update(name=(body.get("name") or pid).strip(), kind=kind, base_url=base.rstrip("/"), fetch_models=bool(body.get("fetch_models", True)))
        if isinstance(body.get("headers"), dict):
            patch["headers"] = {str(k): str(v) for k, v in body["headers"].items()}
    key = (body.get("api_key") or "").strip()
    if key:
        patch["api_key"] = key
    if "models" in body:
        patch["models"] = _parse_models(body["models"])
    patch["enabled"] = True
    entry = provcfg.upsert(pid, patch)
    engine.reload_providers()
    try:
        await engine.refresh_models(pid)
    except Exception as err:
        log.info("refresh after save: %s", err)
    engine.publish({"type": "model.updated", "data": {}})
    return _provider_view(pid, provcfg.entry(pid) or entry)


LOCAL_SERVERS = [
    {"catalog": "ollama", "name": "Ollama", "base_url": "http://localhost:11434/v1"},
    {"catalog": "lmstudio", "name": "LM Studio", "base_url": "http://localhost:1234/v1"},
    {"catalog": "vllm", "name": "vLLM", "base_url": "http://localhost:8000/v1"},
    {"catalog": None, "id": "llamacpp", "name": "llama.cpp server", "base_url": "http://localhost:8080/v1"},
    {"catalog": None, "id": "jan", "name": "Jan", "base_url": "http://localhost:1337/v1"},
]


@app.get("/api/providers/detect-local")
async def detect_local():
    """Look for model servers running on this computer and list their models."""
    import httpx

    configured = provcfg.load()["providers"]

    async def probe(client: httpx.AsyncClient, srv: dict) -> dict | None:
        try:
            r = await client.get(srv["base_url"] + "/models")
            if r.status_code >= 300:
                return None
            data = r.json()
        except Exception:
            return None
        items = data.get("data") if isinstance(data, dict) else data
        models = [str(m.get("id") if isinstance(m, dict) else m) for m in items or [] if (m.get("id") if isinstance(m, dict) else m)]
        pid = srv.get("catalog") or srv["id"]
        known = next((k for k, p in configured.items() if (p.get("base_url") or "").rstrip("/") == srv["base_url"]), None)
        return {**srv, "id": pid, "models": models, "configured": bool(known), "providerID": known}

    async with httpx.AsyncClient(timeout=1.5) as client:
        found = await asyncio.gather(*(probe(client, s) for s in LOCAL_SERVERS))
    return [f for f in found if f]


@app.post("/api/providers/{pid}/test")
async def test_provider(pid: str, body: dict = Body(default={})):
    """One tiny completion to confirm the key and endpoint work."""
    p = provcfg.entry(pid)
    if not p:
        raise KeyError(pid)
    provider = engine.providers.get(pid)
    if provider is None:
        raise ValueError("Provider is disabled or misconfigured")
    models = provcfg.models_of(p, pid)
    mid = body.get("model") or (models[0].id if models else None)
    if not mid:
        try:
            fetched = await provider.list_models()
        except Exception as err:
            return {"ok": False, "error": f"Could not list models: {err}"}
        if not fetched:
            return {"ok": False, "error": "The endpoint lists no models"}
        mid = fetched[0].id
    req = ChatRequest(model=mid, system="Reply with the single word OK.", messages=[ChatMessage("user", "ping")], max_tokens=16, reasoning=False)
    text = []
    try:
        async for ev in provider.stream(req):
            if ev["type"] == "text.delta":
                text.append(ev["text"])
            elif ev["type"] == "error":
                return {"ok": False, "error": ev.get("message"), "status": ev.get("status"), "model": mid}
    except Exception as err:
        return {"ok": False, "error": str(err), "model": mid}
    return {"ok": True, "model": mid, "reply": "".join(text)[:80]}


@app.put("/api/providers/{pid}/models/{mid:path}")
def override_model(pid: str, mid: str, body: dict = Body(...)):
    """Correct a model's facts by hand (context, output, effort levels, inputs). An empty body resets it."""
    p = provcfg.entry(pid)
    if not p:
        raise KeyError(pid)
    overrides = dict(p.get("overrides") or {})
    clean = {k: body[k] for k in provcfg.OVERRIDABLE if k in body and body[k] not in (None, "", [])}
    if "variants" in body and isinstance(body["variants"], list):
        clean["variants"] = [str(v).strip().lower() for v in body["variants"] if str(v).strip()]
    if clean:
        overrides[mid] = clean
    else:
        overrides.pop(mid, None)
    provcfg.upsert(pid, {"overrides": overrides})
    engine.reload_providers()
    engine.publish({"type": "model.updated", "data": {}})
    return _provider_view(pid, provcfg.entry(pid))


@app.post("/api/providers/{pid}/refresh")
async def refresh_provider(pid: str):
    if not provcfg.entry(pid):
        raise KeyError(pid)
    await engine.refresh_models(pid)
    return _provider_view(pid, provcfg.entry(pid))


@app.post("/api/providers/{pid}/enabled")
def provider_enabled(pid: str, body: dict = Body(...)):
    if not provcfg.entry(pid):
        raise KeyError(pid)
    provcfg.upsert(pid, {"enabled": bool(body.get("enabled", True))})
    engine.reload_providers()
    engine.publish({"type": "model.updated", "data": {}})
    return _provider_view(pid, provcfg.entry(pid))


@app.delete("/api/providers/{pid}")
def delete_provider(pid: str):
    provcfg.remove(pid)
    _forget_default(pid)
    engine.reload_providers()
    engine.publish({"type": "model.updated", "data": {}})
    return {"ok": True}


# ---- provider sign-in (engine/auth.py) ----


@app.post("/api/auth/login")
async def auth_login(body: dict = Body(...)):
    """Start a sign-in: returns the page to open (or the device code to type), then poll its status."""
    from .engine import auth as provider_auth

    async def done(pid: str) -> None:
        engine.reload_providers()
        try:
            await engine.refresh_models(pid)
        except Exception as err:
            log.info("refresh after sign-in: %s", err)
        engine.publish({"type": "model.updated", "data": {}})

    login = await provider_auth.start(str(body.get("method") or ""), done)
    return login.view()


@app.get("/api/auth/login/{lid}")
def auth_login_status(lid: str):
    from .engine import auth as provider_auth

    login = provider_auth.get(lid)
    if not login:
        raise KeyError(lid)
    return login.view()


@app.delete("/api/auth/login/{lid}")
def auth_login_cancel(lid: str):
    from .engine import auth as provider_auth

    provider_auth.cancel(lid)
    return {"ok": True}


@app.post("/api/chatgpt-web/connect")
async def chatgpt_web_connect(body: dict = Body(...)):
    """Connect the ChatGPT normal-chat lane. mode "chrome" imports the session from the browser's
    cookie store; mode "paste" takes {text} (a session token or export). Returns {ok, account, plan,
    source} or {ok:false, reason, error} so the UI can offer paste when auto-import can't work."""
    from .engine import auth as provider_auth
    from .engine import chrome_import

    mode = str(body.get("mode") or "chrome")
    try:
        creds = chrome_import.parse_paste(str(body.get("text") or "")) if mode == "paste" else chrome_import.read_browser_session(body.get("browser"))
        info = await provider_auth.import_chatgpt_web(creds)
    except chrome_import.ImportError_ as exc:
        return {"ok": False, "reason": exc.reason, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": "failed", "error": str(exc)}
    engine.reload_providers()
    try:
        await engine.refresh_models("chatgpt-chat")
    except Exception as err:
        log.info("refresh after chatgpt-web connect: %s", err)
    engine.publish({"type": "model.updated", "data": {}})
    return {"ok": True, **info, "source": creds.get("source", "")}


@app.post("/api/providers/{pid}/logout")
def provider_logout(pid: str):
    """Forget a sign-in. Subscription providers (ChatGPT, Copilot) go away; OpenRouter keeps nothing either."""
    p = provcfg.entry(pid)
    if not p:
        raise KeyError(pid)
    provcfg.remove(pid)
    _forget_default(pid)
    engine.reload_providers()
    engine.publish({"type": "model.updated", "data": {}})
    return {"ok": True}


def _forget_default(pid: str) -> None:
    """A removed provider can't stay the default model; the picker falls back to the first one left."""
    ref = engine.settings().get("defaultModel")
    if isinstance(ref, dict) and ref.get("providerID") == pid:
        store.replace_setting("defaultModel", None)


# ---- MCP servers -----------------------------------------------------------------


def _kv(text: str | dict | None) -> dict[str, str]:
    if isinstance(text, dict):
        return {str(k): str(v) for k, v in text.items()}
    out = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
        elif ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _mcp_servers() -> list[dict]:
    return [s for s in (store.load_settings().get("mcp") or {}).get("servers", []) if isinstance(s, dict) and s.get("name")]


def _save_mcp(servers: list[dict]) -> None:
    store.save_settings({"mcp": {"servers": servers}})


@app.get("/api/mcp")
def list_mcp():
    status = {s["name"]: s for s in (engine.mcp.status() if engine.mcp else [])}
    out = []
    for s in _mcp_servers():
        st = status.get(s["name"], {})
        out.append({"name": s["name"], "source": "afh", "type": s.get("type", "local"), "command": s.get("command"), "url": s.get("url"), "disabled": bool(s.get("disabled")),
                    "environment": {k: "••••" for k in (s.get("environment") or {})}, "headers": {k: "••••" for k in (s.get("headers") or {})},
                    "status": {"status": "disabled" if s.get("disabled") else st.get("status", "pending"), "error": st.get("error"), "tools": st.get("tools", 0)}})
    return out


@app.post("/api/mcp")
def add_mcp(body: dict = Body(...)):
    name = body["name"].strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$", name):
        raise ValueError("Server name may use letters, numbers, - _ .")
    if body.get("type") == "remote":
        if not str(body.get("url", "")).startswith(("http://", "https://")):
            raise ValueError("Remote servers need an http(s) URL")
        entry: dict[str, Any] = {"name": name, "type": "remote", "url": body["url"].strip()}
        if headers := _kv(body.get("headers")):
            entry["headers"] = headers
    else:
        command = body.get("command")
        if isinstance(command, str):
            command = shlex.split(command, posix=False)
        command = [str(part).strip('"') for part in command or [] if str(part).strip()]
        if not command:
            raise ValueError("Local servers need a command")
        entry = {"name": name, "type": "local", "command": command}
        if env := _kv(body.get("environment")):
            entry["environment"] = env
    servers = [s for s in _mcp_servers() if s["name"] != name] + [entry]
    _save_mcp(servers)
    return restart_soon()


@app.post("/api/mcp/{name}/enabled")
def toggle_mcp(name: str, body: dict = Body(...)):
    servers = _mcp_servers()
    for s in servers:
        if s["name"] == name:
            s["disabled"] = not bool(body["enabled"])
            break
    else:
        raise KeyError(name)
    _save_mcp(servers)
    return restart_soon()


@app.delete("/api/mcp/{name}")
def remove_mcp(name: str):
    _save_mcp([s for s in _mcp_servers() if s["name"] != name])
    return restart_soon()


@app.post("/api/mcp/{name}/reconnect")
async def reconnect_mcp(name: str):
    if not engine.mcp:
        raise ValueError("MCP is not running")
    ok = await engine.mcp.reconnect(name)
    engine.publish({"type": "mcp.status.changed", "data": {}})
    return {"ok": ok}


@app.post("/api/restart")
def restart():
    return restart_soon()


# ---- skills store --------------------------------------------------------------------


@app.get("/api/skills/search")
def skills_search(q: str, limit: int = 30):
    return skills_store.search(q, limit=min(max(limit, 1), 100))


@app.get("/api/skills/browse")
def skills_browse(view: str = "trending", page: int = 0):
    return skills_store.browse(view=view, page=max(page, 0), per_page=40)


@app.get("/api/skills/curated")
def skills_curated():
    return skills_store.curated()


@app.get("/api/skills/detail")
def skills_detail(source: str, slug: str):
    detail = skills_store.detail(source, slug)
    try:
        audit = skills_store.audit(source, slug)
    except Exception:
        audit = None
    return {"detail": detail, "audit": audit}


@app.get("/api/skills/installed")
def skills_installed(directory: str | None = None):
    return skills_store.installed(project_dir=directory)


@app.post("/api/skills/install")
def skills_install(body: dict = Body(...)):
    scope = "project" if body.get("scope") == "project" else "global"
    return skills_store.install(body["source"], body["slug"], scope=scope, project_dir=body.get("directory"))


@app.delete("/api/skills")
def skills_uninstall(body: dict = Body(...)):
    scope = "project" if body.get("scope") == "project" else "global"
    return {"ok": skills_store.uninstall(body["slug"], scope=scope, project_dir=body.get("directory"))}


@app.post("/api/skills/check-updates")
def skills_check_updates(body: dict = Body(default={})):
    return skills_store.check_updates(project_dir=body.get("directory"))


# ---- session transfer ----------------------------------------------------------------------


@app.get("/api/sessions/{sid}/export")
def session_export(sid: str):
    payload = engine.export_session(sid)
    title = re.sub(r"[^A-Za-z0-9._-]+", "-", (payload.get("info") or {}).get("title") or sid)[:60].strip("-") or sid
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{title}.afh-session.json"'})


@app.post("/api/sessions/import")
def session_import(body: dict = Body(...)):
    """Import an .afh-session.json / OpenCode export, given inline or as a file path."""
    payload = body.get("payload")
    if not payload and body.get("path"):
        payload = json.loads(Path(body["path"]).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Nothing to import")
    if body.get("preview"):
        return transfer.summarize(payload)
    return transfer.import_session(engine, payload, body["directory"])


@app.get("/api/import/zadloop")
def zadloop_list():
    return transfer.list_zadloop_sessions()


@app.post("/api/import/zadloop")
def zadloop_import(body: dict = Body(...)):
    payload = transfer.load_zadloop(body["path"])
    if body.get("preview"):
        return transfer.summarize(payload)
    return transfer.import_session(engine, payload, body["directory"])


@app.post("/api/import/file")
def import_file(body: dict = Body(...)):
    """Import any supported file the user picked: an AFH/OpenCode export (.json), or a Zadloop /
    DeepSeek Harness session (a .zip export, a .jsonl / .jsonl.zstd log, or a session folder)."""
    path = Path(body["path"])
    if not path.exists():
        raise ValueError(f"File not found: {path}")
    if path.suffix.lower() == ".json" and not zipfile_is(path):
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = transfer.load_zadloop(str(path))  # zip / jsonl / zstd / folder
    if body.get("preview"):
        return transfer.summarize(payload)
    return transfer.import_session(engine, payload, body["directory"])


def zipfile_is(path: Path) -> bool:
    import zipfile

    try:
        return path.is_file() and zipfile.is_zipfile(str(path))
    except OSError:
        return False


# ---- OpenCode migration ------------------------------------------------------------------------


@app.get("/api/migrate/opencode")
def migrate_status():
    settings = store.load_settings()
    out = {**migrate.available(), "done": bool(((settings.get("migration") or {}).get("opencode") or {}).get("done"))}
    if out["db"]:
        try:
            out["sessions"] = len(migrate.list_sessions())
        except Exception as err:
            out["error"] = str(err)
    return out


@app.post("/api/migrate/opencode")
def migrate_run(body: dict = Body(default={})):
    result = migrate.migrate_all(engine, sessions=bool(body.get("sessions", True)))
    engine.reload_providers()
    restart_soon()
    return result


# ---- delegation --------------------------------------------------------------------


@app.get("/api/delegation")
def get_delegation():
    return store.load_settings()["delegation"]


@app.put("/api/delegation")
def put_delegation(body: dict = Body(...)):
    delegates = []
    seen = set()
    for d in body.get("delegates", []):
        did = str(d.get("id", "")).strip().lower()
        if not IDENT.match(did) or did in {store.LEADER_ID, "build", "plan", "redteam", "general"} or did in seen:
            raise ValueError(f"Delegate id '{did}' is invalid or reserved")
        seen.add(did)
        delegates.append({"id": did, "name": str(d.get("name") or did)[:60], "model": d.get("model") if isinstance(d.get("model"), dict) else None,
                          "job": str(d.get("job", ""))[:4000], "system": str(d.get("system", ""))[:20000], "enabled": bool(d.get("enabled", True)),
                          "readonly": bool(d.get("readonly", False)), "color": d.get("color") or None})
    store.save_settings({"delegation": {"leaderInstructions": str(body.get("leaderInstructions", ""))[:8000], "delegates": delegates,
                                        "builtinHelper": bool(body.get("builtinHelper", True))}})
    engine.publish({"type": "agent.updated", "data": {}})
    return {"ok": True}


# ---- remote control ------------------------------------------------------------------------


@app.get("/api/remote/ping")
def remote_ping():
    return {"app": "agent-flow-harness", "version": __version__, "remote": bool(remote.state["server"])}


@app.post("/api/remote/login")
def remote_login(body: dict = Body(...)):
    try:
        token = remote.login(str(body.get("password", "")))
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=429)
    if not token:
        return JSONResponse({"error": "Wrong password"}, status_code=401)
    return {"token": token}


@app.get("/api/remote")
def remote_status():
    return remote.status()


@app.put("/api/remote")
def remote_update(body: dict = Body(...)):
    current = store.load_settings().get("remote") or {}
    patch: dict[str, Any] = {}
    if "enabled" in body:
        patch["enabled"] = bool(body["enabled"])
    if body.get("password"):
        if len(str(body["password"])) < 6:
            raise ValueError("Use a password of at least 6 characters")
        patch["passwordHash"] = remote.hash_password(str(body["password"]))
    if "tunnel" in body:
        patch["tunnel"] = "cloudflare" if body["tunnel"] == "cloudflare" else "none"
    if body.get("port"):
        patch["port"] = int(body["port"])
    elif not current.get("port"):
        patch["port"] = remote.free_port()
    store.save_settings({"remote": patch})
    s = remote.settings()
    if s["enabled"] and not s["passwordHash"]:
        raise ValueError("Set a password before turning remote control on")
    remote.apply(s)
    return remote.status()


@app.post("/api/remote/disconnect-all")
def remote_disconnect_all():
    remote.state["tokens"].clear()
    return {"ok": True}


# ---- AFH account (remote access from the phone apps, through agentflowharness.com) ----------------


@app.get("/api/cloud")
def cloud_status():
    return cloud.status()


@app.post("/api/cloud/link")
def cloud_link(body: dict = Body(default={})):
    # signing in happens on the website; this only starts it and returns the page to open
    return cloud.link_start(str(body.get("name") or ""))


@app.post("/api/cloud/link/cancel")
def cloud_link_cancel():
    return cloud.link_cancel()


@app.post("/api/cloud/signout")
def cloud_signout():
    return cloud.sign_out()


@app.put("/api/cloud")
def cloud_update(body: dict = Body(...)):
    return cloud.set_enabled(bool(body.get("enabled")))


# ---- events -----------------------------------------------------------------------


# ---- scheduled jobs ----------------------------------------------------------------------------


@app.get("/api/schedules")
def schedules_list():
    from .engine import schedules

    return schedules.list_jobs()


@app.post("/api/schedules")
def schedules_create(body: dict = Body(...)):
    from .engine import schedules

    return schedules.upsert({k: v for k, v in body.items() if k != "id"})


@app.put("/api/schedules/{job_id}")
def schedules_update(job_id: str, body: dict = Body(...)):
    from .engine import schedules

    if not any(j["id"] == job_id for j in schedules.load()):
        raise KeyError(job_id)
    return schedules.upsert({**body, "id": job_id})


@app.delete("/api/schedules/{job_id}")
def schedules_delete(job_id: str):
    from .engine import schedules

    if not schedules.delete(job_id):
        raise KeyError(job_id)
    return {"ok": True}


@app.post("/api/schedules/{job_id}/run")
async def schedules_run(job_id: str):
    from .engine import schedules

    job = next((j for j in schedules.load() if j["id"] == job_id), None)
    if not job:
        raise KeyError(job_id)
    sid = await engine.scheduler.run(job)
    if not sid:
        raise ValueError("This job is already starting")
    return {"sessionID": sid}


# ---- developer API: keys, info and one-call runs ---------------------------------------------------


@app.get("/api/developer")
def developer_info():
    dev = store.load_settings().get("developer") or {}
    return {"version": __version__, "keys": [devapi.public(k) for k in devapi.list_keys()], "port": int(dev.get("port") or 0),
            "discovery": str(store.AFH_DIR / devapi.DISCOVERY_FILE)}


@app.post("/api/cli/install")
def cli_install():
    """Put the afh command on this user's PATH."""
    from . import cli

    return cli.install_shim()


@app.get("/api/races")
def races_list():
    return engine.races.read()


@app.post("/api/races")
async def race_start(body: dict = Body(...)):
    directory = str(body.get("directory") or "")
    if not Path(directory).is_dir():
        raise ValueError("directory must be an existing folder")
    from .engine import worktree as wtmod

    try:
        return await engine.races.start(directory, str(body.get("prompt") or ""), list(body.get("models") or []),
                                        str(body.get("check") or ""), body.get("mode") or "full")
    except wtmod.GitError as err:
        raise ValueError(str(err)) from None


@app.get("/api/races/{rid}")
def race_get(rid: str):
    return engine.races.get(rid)


@app.post("/api/races/{rid}/pick")
async def race_pick(rid: str, body: dict = Body(...)):
    from .engine import worktree as wtmod

    try:
        return await engine.races.pick(rid, str(body.get("session") or ""))
    except wtmod.GitError as err:
        raise ValueError(str(err)) from None


@app.post("/api/races/{rid}/discard")
async def race_discard(rid: str):
    return await engine.races.discard(rid)


@app.get("/api/github")
async def github_status():
    return await engine.github.status()


@app.put("/api/github")
async def github_save(body: dict = Body(...)):
    keep = {k: body[k] for k in ("enabled", "repos", "allowed", "mode", "model", "interval") if k in body}
    for entry in keep.get("repos", []):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", str(entry.get("repo"))):
            raise ValueError("Write the repository as owner/name")
        if not Path(str(entry.get("path"))).is_dir():
            raise ValueError(f"No such folder: {entry.get('path')}")
    if keep.get("mode", "ask") not in ("ask", "full"):
        raise ValueError("mode is ask or full")
    saved = store.save_settings({"github": {**(store.load_settings().get("github") or {}), **keep}})
    if saved["github"].get("enabled"):
        await engine.github.mark_start()
    return await engine.github.status()


@app.post("/api/developer/keys")
def developer_create_key(body: dict = Body(default={})):
    rec, raw = devapi.create_key(str(body.get("name") or "API key"))
    return {**rec, "key": raw}


@app.delete("/api/developer/keys/{key_id}")
def developer_delete_key(key_id: str):
    if not devapi.delete_key(key_id):
        raise KeyError(key_id)
    return {"ok": True}


def reply_of(sid: str) -> str:
    """The text of the newest assistant reply in a thread."""
    for m in reversed(engine.store.list_messages(sid)):
        if m.get("type") == "assistant":
            text = "".join(p.get("text", "") for p in m.get("content") or [] if p.get("type") == "text").strip()
            if text:
                return text
    return ""


async def wait_idle(sid: str, timeout: float) -> bool:
    """Wait until the thread's run (with any autopilot turns) is over. False on timeout."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    await asyncio.sleep(0.3)
    while engine.is_running(sid):
        if loop.time() > end:
            return False
        await asyncio.sleep(0.3)
    return True


@app.post("/api/v1/run")
async def run_task(body: dict = Body(...)):
    """One call for scripts: start a thread (or continue `sessionID`), send the prompt, wait for the
    answer. With `wait: false` it returns right away with the thread id."""
    text = str(body.get("prompt") or "").strip()
    if not text:
        raise ValueError("prompt is required")
    sid = body.get("sessionID")
    if sid:
        session_or_404(sid)
    else:
        directory = str(body.get("directory") or "").strip()
        if not directory or not Path(directory).is_dir():
            raise ValueError("directory must be an existing folder")
        sid = engine.create_session(directory, title=body.get("title") or None, agent=body.get("agent"),
                                    model=model_ref(body.get("model")), mode=body.get("mode") or "full")["id"]
    await engine.prompt(sid, text, None, agent=body.get("agent"), model=model_ref(body.get("model")))
    if body.get("wait") is False:
        return {"sessionID": sid, "done": False}
    done = await wait_idle(sid, float(body.get("timeout") or 1800))
    s = engine.store.get_session(sid) or {}
    afh = (s.get("metadata") or {}).get("afh") or {}
    return {"sessionID": sid, "done": done, "reply": reply_of(sid), "todos": afh.get("todos") or [], "goal": afh.get("goal"),
            "cost": s.get("cost") or 0, "title": s.get("title")}


@app.get("/api/v1/sessions/{sid}/reply")
def last_reply(sid: str):
    session_or_404(sid)
    return {"sessionID": sid, "running": engine.is_running(sid), "reply": reply_of(sid)}


@app.websocket("/api/browser/host")
async def browser_host(ws: WebSocket):
    """The AFH window's browser panel connects here so the agent's browser tool can drive its tabs.
    Only the local window may: its per-launch token, the expected Host, never the remote listener."""
    from afh.engine.tools.browser import PANEL

    server = ws.scope.get("server") or ("", 0)
    via_remote = remote.state["port"] and server[1] == remote.state["port"]
    bad_host = ACCESS["hosts"] and ws.headers.get("host") not in ACCESS["hosts"]
    if via_remote or bad_host or not ACCESS["token"] or ws.query_params.get("token") != ACCESS["token"]:
        await ws.close(code=4401)
        return
    await PANEL.serve(ws)


@app.get("/api/events")
async def events(request: Request):
    queue = engine.subscribe()

    async def stream():
        try:
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(ev, separators=(',', ':'))}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            engine.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---- static UI -----------------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
