"""HTTP + SSE API that the AFH UI talks to. Every OpenCode call goes through the SDK."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from itertools import islice
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from opencode import APIConnectionError, APIStatusError
from opencode.types import ModelRef

from . import __version__, store
from .engine import dump, engine

log = logging.getLogger("afh.api")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AFH", version=__version__)

# The API can run commands (MCP servers) and write files, so only the AFH window may call it:
# a per-launch token blocks other local pages, and the Host check blocks DNS rebinding.
ACCESS = {"token": None, "hosts": set()}


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        token = request.headers.get("x-afh-token") or request.query_params.get("token")
        if ACCESS["hosts"] and request.headers.get("host") not in ACCESS["hosts"]:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        if ACCESS["token"] and token != ACCESS["token"]:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return await call_next(request)
    except Exception as exc:  # turn every failure into a JSON error the UI can show
        return error_response(exc)


def error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, APIStatusError):
        status = exc.status_code
    elif (isinstance(exc, (APIConnectionError, RuntimeError)) and not engine.ready.is_set()) or "client has been closed" in str(exc):
        # A request raced an engine restart; the UI retries 503s.
        return JSONResponse({"error": "OpenCode is restarting — try again in a moment"}, status_code=503)
    elif isinstance(exc, (ValueError, KeyError)):
        status = 400
    else:
        status = 500
        log.exception("request failed")
    message = f"Missing field: {exc}" if isinstance(exc, KeyError) else str(exc).split("\n")[0][:500]
    return JSONResponse({"error": message}, status_code=status)

# Approval modes, applied as session permission rules (the last matching rule wins).
# Forms can't be answered through the SDK yet, so agents ask questions in chat instead.
NO_FORMS = {"action": "question", "resource": "*", "effect": "deny"}
MODES: dict[str, list[dict]] = {
    "full": [{"action": "*", "resource": "*", "effect": "allow"}],
    "ask": [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "ask"},
        {"action": "shell", "resource": "*", "effect": "ask"},
    ],
    "readonly": [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "deny"},
        {"action": "shell", "resource": "*", "effect": "deny"},
    ],
}
SECRET_KEY = re.compile(r"key|token|secret|password|authorization", re.I)


def rules_for(mode: str) -> list[dict]:
    return [*MODES.get(mode, MODES["ask"]), NO_FORMS]


def mask(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, key) for v in value]
    if isinstance(value, str) and SECRET_KEY.search(key) and value:
        return "••••" + value.strip()[-4:] if len(value.strip()) > 8 else "••••"
    return value


def model_ref(m: dict | None) -> ModelRef | None:
    if not m or not m.get("id") or not m.get("providerID"):
        return None
    data = {"id": m["id"], "providerID": m["providerID"]}
    if m.get("variant"):
        data["variant"] = m["variant"]
    return ModelRef.model_validate(data)


def restart_soon() -> dict:
    threading.Thread(target=engine.restart, daemon=True).start()
    return {"ok": True, "restarting": True}


def c():
    return engine.require()


# ---- app state -------------------------------------------------------------


@app.get("/api/bootstrap")
def bootstrap():
    settings = store.load_settings()
    out = {"version": __version__, "settings": settings, "ready": engine.ready.is_set(), "error": engine.error}
    if engine.ready.wait(timeout=60):
        out.update(models_payload(), agents=agents_payload(), ready=True)
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


def models_payload() -> dict:
    client = c()
    models = [m for m in dump(client.model.list().data) if m.get("enabled", True) and m.get("status") != "deprecated"]
    try:
        default = dump(client.model.default().data)
    except Exception:
        default = None
    slim = [
        {
            "id": m["id"],
            "providerID": m["providerID"],
            "name": m.get("name", m["id"]),
            "family": m.get("family"),
            "variants": [v["id"] for v in m.get("variants", [])],
            "context": (m.get("limit") or {}).get("context"),
            "input": (m.get("capabilities") or {}).get("input", []),
            "tools": (m.get("capabilities") or {}).get("tools", True),
        }
        for m in models
    ]
    return {"models": slim, "defaultModel": default and {"id": default["id"], "providerID": default["providerID"]}}


@app.get("/api/models")
def get_models():
    return models_payload()


def agents_payload() -> list[dict]:
    overlay = store.load_overlay().get("agents", {})
    agents = []
    for a in dump(c().agent.list().data):
        agents.append(
            {
                "id": a["id"],
                "name": a.get("name", a["id"]),
                "description": a.get("description", ""),
                "mode": a.get("mode", "primary"),
                "hidden": a.get("hidden", False),
                "system": (overlay.get(a["id"]) or {}).get("system", ""),
                "custom": a["id"] in overlay and bool((overlay[a["id"]] or {}).get("afhCustom")),
            }
        )
    return agents


@app.get("/api/agents")
def get_agents():
    return agents_payload()


# ---- sessions ------------------------------------------------------------------


@app.get("/api/sessions")
def list_sessions(directory: str, archived: bool = False):
    page = c().session.list(directory=directory, limit=80, order="desc", archived=archived)
    return [dump(s) for s in islice(page, 200)]


@app.post("/api/sessions")
def create_session(body: dict = Body(...)):
    mode = body.get("mode") or store.load_settings()["defaultMode"]
    kwargs: dict[str, Any] = {
        "title": body.get("title") or None,
        "location": {"directory": body["directory"]},
        "permissions": rules_for(mode),
        "metadata": {"afh": {"mode": mode}},
    }
    if ref := model_ref(body.get("model")):
        kwargs["model"] = ref
    if body.get("agent"):
        kwargs["agent"] = body["agent"]
    return dump(c().session.create(**{k: v for k, v in kwargs.items() if v is not None}))


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return dump(c().session.get(sid))


@app.patch("/api/sessions/{sid}")
def update_session(sid: str, body: dict = Body(...)):
    client = c()
    kwargs: dict[str, Any] = {}
    if "title" in body:
        kwargs["title"] = body["title"]
    if "archived" in body:
        kwargs["archived"] = bool(body["archived"])
    if "mode" in body:
        kwargs["permissions"] = rules_for(body["mode"])
        kwargs["metadata"] = {"afh": {"mode": body["mode"]}}
    if kwargs:
        client.session.update(sid, **kwargs)
    if ref := model_ref(body.get("model")):
        client.session.switch_model(sid, model=ref)
    if body.get("agent"):
        client.session.switch_agent(sid, agent=body["agent"])
    return dump(client.session.get(sid))


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    c().session.remove(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/fork")
def fork_session(sid: str, body: dict = Body(default={})):
    kwargs = {"before": body["before"]} if body.get("before") else {}
    return dump(c().session.fork(sid, **kwargs))


@app.get("/api/sessions/{sid}/messages")
def get_messages(sid: str):
    page = c().message.list(sid, order="asc", limit=200)
    return [dump(m) for m in islice(page, 2000)]


@app.post("/api/sessions/{sid}/prompt")
def prompt(sid: str, body: dict = Body(...)):
    client = c()
    if ref := model_ref(body.get("model")):
        client.session.switch_model(sid, model=ref)
    if body.get("agent"):
        client.session.switch_agent(sid, agent=body["agent"])
    kwargs: dict[str, Any] = {"text": body["text"]}
    files = [{"uri": Path(p).resolve().as_uri(), "name": Path(p).name} for p in body.get("files", [])]
    if files:
        kwargs["files"] = files
    client.session.prompt(sid, **kwargs)
    return {"ok": True}


@app.post("/api/sessions/{sid}/interrupt")
def interrupt(sid: str):
    c().session.interrupt(sid)
    return {"ok": True}


@app.get("/api/sessions/{sid}/diff")
def session_diff(sid: str):
    return [dump(d) for d in c().session.diff(sid)]


@app.get("/api/sessions/{sid}/permissions")
def pending_permissions(sid: str):
    return [dump(p) for p in c().permission.list(sid)]


@app.post("/api/sessions/{sid}/permissions/{rid}")
def reply_permission(sid: str, rid: str, body: dict = Body(...)):
    kwargs = {"message": body["message"]} if body.get("message") else {}
    c().permission.reply(sid, rid, decision=body["decision"], **kwargs)
    return {"ok": True}


@app.get("/api/sessions/{sid}/harness")
def harness(sid: str):
    """What the model is told: the agent prompt override plus every injected system/instruction message."""
    client = c()
    session = dump(client.session.get(sid))
    agent_id = session.get("agent") or store.load_settings()["defaultAgent"]
    overlay_agent = store.load_overlay().get("agents", {}).get(agent_id, {})
    system_messages = [
        {"text": m.get("text", ""), "sources": (m.get("metadata") or {}).get("instructionSources", [])}
        for m in (dump(x) for x in islice(client.message.list(sid, order="asc", type="system", limit=200), 500))
    ]
    directory = (session.get("location") or {}).get("directory")
    return {
        "agent": agent_id,
        "model": session.get("model"),
        "systemPrompt": overlay_agent.get("system", ""),
        "globalInstructions": store.read_text(store.GLOBAL_AGENTS_MD),
        "projectInstructions": store.read_text(Path(directory) / "AGENTS.md") if directory else "",
        "personalization": store.read_text(store.PERSONALIZATION_PATH),
        "systemMessages": system_messages,
        "permissions": session.get("permissions"),
    }


# ---- prompts & agents (overlay) -----------------------------------------------


@app.get("/api/prompts")
def get_prompts(directory: str | None = None):
    return {
        "agents": agents_payload(),
        "globalInstructions": store.read_text(store.GLOBAL_AGENTS_MD),
        "globalInstructionsPath": str(store.GLOBAL_AGENTS_MD),
        "projectInstructions": store.read_text(Path(directory) / "AGENTS.md") if directory else "",
        "projectInstructionsPath": str(Path(directory) / "AGENTS.md") if directory else None,
    }


@app.put("/api/prompts/agent/{agent_id}")
def set_agent_prompt(agent_id: str, body: dict = Body(...)):
    text = (body.get("system") or "").strip()

    def apply(cfg: dict) -> None:
        agents = cfg.setdefault("agents", {})
        entry = agents.setdefault(agent_id, {})
        if text:
            entry["system"] = text
        else:
            entry.pop("system", None)
            if not entry:
                agents.pop(agent_id)

    store.update_overlay(apply)
    return restart_soon()


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


AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


@app.post("/api/agents")
def save_agent(body: dict = Body(...)):
    agent_id = body["id"].strip().lower()
    if not AGENT_ID.match(agent_id):
        raise ValueError("Agent id must be lowercase letters, numbers, - or _")
    entry: dict[str, Any] = {"mode": body.get("mode", "primary")}
    for key in ("description", "system", "color"):
        if body.get(key):
            entry[key] = body[key]
    if body.get("model"):
        entry["model"] = body["model"]  # "provider/model" string
    if body.get("readonly"):
        entry["permissions"] = [
            {"action": "edit", "resource": "*", "effect": "deny"},
            {"action": "shell", "resource": "*", "effect": "deny"},
        ]

    def apply(cfg: dict) -> None:
        cfg.setdefault("agents", {})[agent_id] = entry

    store.update_overlay(apply)
    settings = store.load_settings()
    custom = sorted(set(settings.get("customAgents", [])) | {agent_id})
    store.save_settings({"customAgents": custom})
    return restart_soon()


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str):
    store.update_overlay(lambda cfg: cfg.get("agents", {}).pop(agent_id, None))
    settings = store.load_settings()
    store.save_settings({"customAgents": [a for a in settings.get("customAgents", []) if a != agent_id]})
    return restart_soon()


# ---- providers & credentials -----------------------------------------------------


@app.get("/api/providers")
def providers():
    client = c()
    creds = dump(client.credential.list())
    by_integration: dict[str, list] = {}
    for cred in creds:
        value = cred.get("value") or {}
        by_integration.setdefault(cred["integrationID"], []).append(
            {
                "id": cred["id"],
                "label": cred.get("label", ""),
                "active": cred.get("active", False),
                "type": value.get("type"),
                "hint": mask(value.get("key", ""), "key") if value.get("type") == "key" else "",
            }
        )
    integrations = []
    for i in dump(client.integration.list().data):
        integrations.append(
            {
                "id": i["id"],
                "name": i.get("name", i["id"]),
                "methods": [m.get("type") for m in i.get("methods", [])],
                "env": [n for m in i.get("methods", []) for n in m.get("names", [])],
                "credentials": by_integration.get(i["id"], []),
            }
        )
    integrations.sort(key=lambda i: (not i["credentials"], i["name"].lower()))
    custom = mask(store.load_overlay().get("providers", {}))
    return {"integrations": integrations, "custom": custom}


@app.post("/api/credentials")
def add_credential(body: dict = Body(...)):
    key = (body.get("key") or "").strip()
    if not key:
        raise ValueError("API key is required")
    cred = c().credential.create(
        integration_id=body["integrationID"],
        value={"type": "key", "key": key},
        label=body.get("label") or "API key (AFH)",
        activate=True,
    )
    return {"ok": True, "id": dump(cred)["id"]}


@app.delete("/api/credentials/{cid}")
def remove_credential(cid: str):
    c().credential.remove(cid)
    return {"ok": True}


@app.post("/api/credentials/{cid}/activate")
def activate_credential(cid: str):
    c().credential.activate(cid)
    return {"ok": True}


PACKAGES = {"openai": "aisdk:@ai-sdk/openai-compatible", "anthropic": "aisdk:@ai-sdk/anthropic"}


@app.post("/api/providers/custom")
def save_custom_provider(body: dict = Body(...)):
    pid = body["id"].strip().lower()
    if not AGENT_ID.match(pid):
        raise ValueError("Provider id must be lowercase letters, numbers, - or _")
    models = [m.strip() for m in body.get("models", "").split(",") if m.strip()]
    if not body.get("baseURL") or not models:
        raise ValueError("Base URL and at least one model are required")
    settings = {"baseURL": body["baseURL"].strip()}
    if body.get("apiKey"):
        settings["apiKey"] = body["apiKey"].strip()
    entry = {
        "name": body.get("name") or pid,
        "package": PACKAGES.get(body.get("kind", "openai"), PACKAGES["openai"]),
        "settings": settings,
        "models": {m: {"name": m} for m in models},
    }

    def apply(cfg: dict) -> None:
        old = cfg.setdefault("providers", {}).get(pid, {})
        if "apiKey" not in settings and (old.get("settings") or {}).get("apiKey"):
            settings["apiKey"] = old["settings"]["apiKey"]
        cfg["providers"][pid] = entry

    store.update_overlay(apply)
    return restart_soon()


@app.delete("/api/providers/custom/{pid}")
def delete_custom_provider(pid: str):
    store.update_overlay(lambda cfg: cfg.get("providers", {}).pop(pid, None))
    return restart_soon()


# ---- MCP servers -----------------------------------------------------------------


def configured_mcp() -> dict[str, dict]:
    """Servers from the global config plus AFH's overlay, keyed by name."""
    found: dict[str, dict] = {}
    for doc in dump(c().config.get()):
        if doc.get("type") != "document" or not doc.get("path"):
            continue
        for name, cfg in ((doc.get("info") or {}).get("mcp") or {}).get("servers", {}).items():
            found[name] = {"source": "global", "config": cfg}
    shadows = set(store.load_settings().get("mcpShadows", []))
    for name, cfg in (store.load_overlay().get("mcp") or {}).get("servers", {}).items():
        found[name] = {"source": "global" if name in shadows else "afh", "config": cfg}
    return found


@app.get("/api/mcp")
def list_mcp():
    status = {s["name"]: s.get("status", {}) for s in dump(c().mcp.list().data)}
    servers = []
    for name, info in configured_mcp().items():
        cfg = info["config"]
        servers.append(
            {
                "name": name,
                "source": info["source"],
                "type": cfg.get("type", "local"),
                "command": cfg.get("command"),
                "url": cfg.get("url"),
                "disabled": bool(cfg.get("disabled")),
                "environment": mask(cfg.get("environment") or {}, "key"),
                "headers": mask(cfg.get("headers") or {}, "key"),
                "status": status.get(name, {"status": "disabled" if cfg.get("disabled") else "unknown"}),
            }
        )
    for name, st in status.items():
        if not any(s["name"] == name for s in servers):
            servers.append({"name": name, "source": "plugin", "type": "?", "disabled": False, "status": st})
    return servers


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


@app.post("/api/mcp")
def add_mcp(body: dict = Body(...)):
    name = body["name"].strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$", name):
        raise ValueError("Server name may use letters, numbers, - _ .")
    if body.get("type") == "remote":
        if not str(body.get("url", "")).startswith(("http://", "https://")):
            raise ValueError("Remote servers need an http(s) URL")
        entry: dict[str, Any] = {"type": "remote", "url": body["url"].strip()}
        if headers := _kv(body.get("headers")):
            entry["headers"] = headers
    else:
        command = body.get("command")
        if isinstance(command, str):
            import shlex

            command = shlex.split(command, posix=False)
        command = [str(part).strip('"') for part in command or [] if str(part).strip()]
        if not command:
            raise ValueError("Local servers need a command")
        entry = {"type": "local", "command": command}
        if env := _kv(body.get("environment")):
            entry["environment"] = env

    store.update_overlay(lambda cfg: cfg.setdefault("mcp", {}).setdefault("servers", {}).__setitem__(name, entry))
    return restart_soon()


@app.post("/api/mcp/{name}/enabled")
def toggle_mcp(name: str, body: dict = Body(...)):
    enabled = bool(body["enabled"])
    info = configured_mcp().get(name)
    if not info:
        raise ValueError(f"Unknown MCP server {name}")
    settings = store.load_settings()
    shadows = set(settings.get("mcpShadows", []))
    cfg = dict(info["config"])

    def apply(overlay: dict) -> None:
        servers = overlay.setdefault("mcp", {}).setdefault("servers", {})
        if info["source"] == "global" and enabled and name in shadows:
            servers.pop(name, None)  # drop the shadow copy; the global entry applies again
            shadows.discard(name)
            return
        if enabled:
            cfg.pop("disabled", None)
        else:
            cfg["disabled"] = True
        servers[name] = cfg  # a full copy: OpenCode rejects partial server entries
        if info["source"] == "global":
            shadows.add(name)

    store.update_overlay(apply)
    store.save_settings({"mcpShadows": sorted(shadows)})
    return restart_soon()


@app.delete("/api/mcp/{name}")
def remove_mcp(name: str):
    store.update_overlay(lambda cfg: (cfg.get("mcp") or {}).get("servers", {}).pop(name, None))
    return restart_soon()


@app.post("/api/mcp/{name}/reconnect")
def reconnect_mcp(name: str):
    client = c()
    try:
        client.mcp.disconnect(name)
    except Exception:
        pass
    client.mcp.connect(name)
    return {"ok": True}


# ---- plugins & skills ---------------------------------------------------------------


@app.get("/api/plugins")
def list_plugins():
    overlay = store.load_overlay().get("plugins", [])
    disabled = {p[1:] for p in overlay if isinstance(p, str) and p.startswith("-")}
    added = [p for p in overlay if not (isinstance(p, str) and p.startswith("-"))]
    loaded = dump(c().plugin.list().data)
    try:
        skills = [
            {"id": s["id"], "name": s.get("name", s["id"]), "description": s.get("description", ""), "path": s.get("path")}
            for s in dump(c().skill.list().data)
        ]
    except Exception:
        skills = []
    return {"loaded": loaded, "added": added, "disabled": sorted(disabled), "skills": skills}


@app.post("/api/plugins")
def add_plugin(body: dict = Body(...)):
    spec = body["spec"].strip()
    if not spec or spec.startswith("-"):
        raise ValueError("Enter an npm package name or a local folder path")
    local = Path(spec).expanduser()
    if local.is_absolute() and not local.is_dir():
        raise ValueError("Local plugins must be folders")

    def apply(cfg: dict) -> None:
        plugins = cfg.setdefault("plugins", [])
        if spec not in plugins:
            plugins.append(spec)

    store.update_overlay(apply)
    return restart_soon()


@app.delete("/api/plugins")
def remove_plugin(body: dict = Body(...)):
    spec = body["spec"]
    store.update_overlay(lambda cfg: cfg.__setitem__("plugins", [p for p in cfg.get("plugins", []) if p != spec]))
    return restart_soon()


@app.post("/api/plugins/enabled")
def toggle_plugin(body: dict = Body(...)):
    pid, enabled = body["id"], bool(body["enabled"])

    def apply(cfg: dict) -> None:
        plugins = [p for p in cfg.get("plugins", []) if p != f"-{pid}"]
        if not enabled:
            plugins.append(f"-{pid}")
        cfg["plugins"] = plugins

    store.update_overlay(apply)
    return restart_soon()


@app.post("/api/restart")
def restart():
    return restart_soon()


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
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
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
