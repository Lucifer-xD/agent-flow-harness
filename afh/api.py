"""HTTP + SSE API that the AFH UI talks to. Everything runs on the AFH Engine in this process."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, remote, skills_store, store, transfer
from .engine import agents as agentmod
from .engine import config as provcfg
from .engine import migrate
from .engine import permissions as perm
from .engine.core import engine
from .engine.providers.catalog import KNOWN, config_from_catalog, make_provider
from .engine.types import ChatMessage, ChatRequest

log = logging.getLogger("afh.api")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AFH", version=__version__)

# The API can run commands (MCP servers, shell) and write files, so only the AFH window may call it:
# a per-launch token blocks other local pages, and the Host check blocks DNS rebinding.
ACCESS = {"token": None, "hosts": set()}
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
        server = request.scope.get("server") or ("", 0)
        via_remote = remote.state["port"] and server[1] == remote.state["port"]
        if via_remote:
            if token not in remote.state["tokens"]:
                return JSONResponse({"error": "unauthorized", "remote": True}, status_code=401)
        else:
            if ACCESS["hosts"] and request.headers.get("host") not in ACCESS["hosts"]:
                return JSONResponse({"error": "forbidden host"}, status_code=403)
            if ACCESS["token"] and token != ACCESS["token"] and token not in remote.state["tokens"]:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return await call_next(request)
    except Exception as exc:  # every failure becomes a JSON error the UI can show
        return error_response(exc)


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


def model_ref(m: dict | None) -> dict | None:
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
    if agent_id in {store.LEADER_ID, "build", "plan"} or any(d.get("id") == agent_id for d in settings["delegation"].get("delegates", [])):
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
    store.save_settings({"agents": agents})
    engine.publish({"type": "agent.updated", "data": {}})
    return {"ok": True, "agents": agents_payload()}


# ---- files (for the live view) ---------------------------------------------------------


@app.get("/api/files/read")
def file_read(path: str):
    """Read a file inside one of the user's project folders (for the Live pane)."""
    target = Path(path).expanduser().resolve()
    roots = [Path(p).resolve() for p in store.load_settings().get("projects", [])]
    if not any(target == r or r in target.parents for r in roots):
        raise ValueError("That file is outside your project folders")
    if not target.is_file():
        return {"content": None, "exists": False}
    data = target.read_bytes()[:2_000_000]
    return {"content": data.decode("utf-8", "replace"), "exists": True, "size": target.stat().st_size}


# ---- sessions ------------------------------------------------------------------


@app.get("/api/sessions")
def list_sessions(directory: str, archived: bool = False):
    return engine.store.list_sessions(directory, archived=archived, limit=200)


@app.post("/api/sessions")
def create_session(body: dict = Body(...)):
    return engine.create_session(body["directory"], title=body.get("title") or None, agent=body.get("agent"), model=model_ref(body.get("model")), mode=body.get("mode"))


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return session_or_404(sid)


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
    engine.delete_session(sid)
    return {"ok": True}


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
        entry: dict[str, Any] = {"uri": path.resolve().as_uri(), "name": path.name}
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp") and path.is_file() and path.stat().st_size < 8_000_000:
            import base64
            import mimetypes

            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            entry["uri"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
            entry["mime"] = mime
        files.append(entry)
    await engine.prompt(sid, body["text"], files or None, agent=body.get("agent"), model=model_ref(body.get("model")))
    return {"ok": True}


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
    req.reply(body["decision"], body.get("message"))
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


# ---- providers -----------------------------------------------------------------------------


def _provider_view(pid: str, p: dict) -> dict:
    out = provcfg.public(p)
    out["id"] = pid
    out["models"] = sorted((m.to_dict() for m in provcfg.models_of(p)), key=lambda m: (m["hidden"], m["name"].lower()))
    out["connected"] = pid in engine.providers
    out["catalog"] = p.get("catalog") if p.get("catalog") in KNOWN else None
    return out


@app.get("/api/providers")
def providers():
    configured = provcfg.load()["providers"]
    catalog = [{"id": pid, "name": k["name"], "kind": k["kind"], "base_url": k["base_url"], "docs": k.get("docs"), "needsKey": k.get("needs_key", True),
                "env": k.get("env", []), "configured": pid in configured, "customUrl": bool(k.get("custom_url"))} for pid, k in KNOWN.items()]
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
        if catalog_id not in KNOWN:
            raise ValueError(f"Unknown provider {catalog_id}")
        k = KNOWN[catalog_id]
        patch.update(name=body.get("name") or k["name"], kind=k["kind"], base_url=(body.get("base_url") or "").strip() or k["base_url"], headers=dict(k.get("headers", {})),
                     extra=dict(k.get("extra", {})), fetch_models=k.get("fetch_models", True), catalog=catalog_id)
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
    if not entry.get("api_key") and KNOWN.get(entry.get("catalog") or "", {}).get("needs_key", True) and not entry.get("catalog") is None:
        pass  # custom endpoints may be keyless (local servers)
    engine.reload_providers()
    try:
        await engine.refresh_models(pid)
    except Exception as err:
        log.info("refresh after save: %s", err)
    engine.publish({"type": "model.updated", "data": {}})
    return _provider_view(pid, provcfg.entry(pid) or entry)


@app.post("/api/providers/{pid}/test")
async def test_provider(pid: str, body: dict = Body(default={})):
    """One tiny completion to confirm the key and endpoint work."""
    p = provcfg.entry(pid)
    if not p:
        raise KeyError(pid)
    provider = engine.providers.get(pid)
    if provider is None:
        raise ValueError("Provider is disabled or misconfigured")
    models = provcfg.models_of(p)
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
    engine.reload_providers()
    engine.publish({"type": "model.updated", "data": {}})
    return {"ok": True}


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
        if not IDENT.match(did) or did in {store.LEADER_ID, "build", "plan", "general"} or did in seen:
            raise ValueError(f"Delegate id '{did}' is invalid or reserved")
        seen.add(did)
        delegates.append({"id": did, "name": str(d.get("name") or did)[:60], "model": d.get("model") if isinstance(d.get("model"), dict) else None,
                          "job": str(d.get("job", ""))[:4000], "system": str(d.get("system", ""))[:20000], "enabled": bool(d.get("enabled", True)),
                          "readonly": bool(d.get("readonly", False)), "color": d.get("color") or None})
    store.save_settings({"delegation": {"leaderInstructions": str(body.get("leaderInstructions", ""))[:8000], "delegates": delegates}})
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


# ---- events -----------------------------------------------------------------------


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
