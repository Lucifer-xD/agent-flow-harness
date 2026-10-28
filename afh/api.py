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

from . import __version__, builtin_prompts, remote, skills_store, store, transfer
from .engine import dump, engine

log = logging.getLogger("afh.api")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AFH", version=__version__)

# The API can run commands (MCP servers) and write files, so only the AFH window may call it:
# a per-launch token blocks other local pages, and the Host check blocks DNS rebinding.
ACCESS = {"token": None, "hosts": set()}


PUBLIC_PATHS = {"/api/remote/login", "/api/remote/ping"}


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in PUBLIC_PATHS:
        token = request.headers.get("x-afh-token") or request.query_params.get("token")
        server = request.scope.get("server") or ("", 0)
        via_remote = remote.state["port"] and server[1] == remote.state["port"]
        if via_remote:
            # LAN/tunnel listener: only a token issued by /api/remote/login (password) is accepted.
            if token not in remote.state["tokens"]:
                return JSONResponse({"error": "unauthorized", "remote": True}, status_code=401)
        else:
            if ACCESS["hosts"] and request.headers.get("host") not in ACCESS["hosts"]:
                return JSONResponse({"error": "forbidden host"}, status_code=403)
            if ACCESS["token"] and token != ACCESS["token"] and token not in remote.state["tokens"]:
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
    elif isinstance(exc, skills_store.SkillsError):
        status = exc.status or 502
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
    if engine.error:  # the engine failed to start (e.g. OpenCode missing): answer at once so the UI can help
        return out
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
    pids = {m["providerID"] for m in slim}
    try:
        names = {i["id"]: i.get("name", i["id"]) for i in dump(client.integration.list().data) if i["id"] in pids}
    except Exception:
        names = {}
    for pid, cfg in store.load_overlay().get("providers", {}).items():
        if pid in pids and cfg.get("name"):
            names[pid] = cfg["name"]
    return {"models": slim, "defaultModel": default and {"id": default["id"], "providerID": default["providerID"]}, "providerNames": names}


@app.get("/api/models")
def get_models():
    return models_payload()


def agents_payload() -> list[dict]:
    overlay = store.load_overlay().get("agents", {})
    settings = store.load_settings()
    delegates = {d["id"]: d for d in settings["delegation"].get("delegates", [])}
    custom = set(settings.get("customAgents", []))
    agents = []
    for a in dump(c().agent.list().data):
        aid = a["id"]
        agents.append(
            {
                "id": aid,
                "name": "Delegate" if aid == store.LEADER_ID else (delegates.get(aid, {}).get("name") or a.get("name", aid)),
                "description": a.get("description", ""),
                "mode": a.get("mode", "primary"),
                "hidden": a.get("hidden", False),
                "system": (overlay.get(aid) or {}).get("system", ""),
                "custom": aid in custom,
                "delegate": aid in delegates,
                "leader": aid == store.LEADER_ID,
                "model": a.get("model"),
                "color": a.get("color"),
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
    return [dump(s) for s in islice(page, 200) if not s.parent_id]  # children belong to their delegation card


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


@app.get("/api/sessions/{sid}/usage")
def session_usage(sid: str):
    """Numbers for the context popover: tokens, cost, context window, message counts."""
    client = c()
    session = dump(client.session.get(sid))
    msgs = [dump(m) for m in islice(client.message.list(sid, order="asc", limit=200), 5000)]
    last = next((m for m in reversed(msgs) if m.get("type") == "assistant" and m.get("tokens")), None)
    ref = session.get("model") or {}
    model = next((m for m in dump(client.model.list().data) if m["id"] == ref.get("id") and m["providerID"] == ref.get("providerID")), None)
    tools = sum(1 for m in msgs if m.get("type") == "assistant" for p in m.get("content", []) if p.get("type") == "tool")
    return {
        "model": ref,
        "modelName": (model or {}).get("name"),
        "contextLimit": ((model or {}).get("limit") or {}).get("context"),
        "outputLimit": ((model or {}).get("limit") or {}).get("output"),
        "lastInput": ((last or {}).get("tokens") or {}).get("input", 0) + (((last or {}).get("tokens") or {}).get("cache") or {}).get("read", 0),
        "totals": session.get("tokens"),
        "cost": session.get("cost"),
        "messages": {"user": sum(1 for m in msgs if m.get("type") == "user"), "assistant": sum(1 for m in msgs if m.get("type") == "assistant"), "system": sum(1 for m in msgs if m.get("type") == "system"), "tools": tools},
        "agent": session.get("agent"),
        "created": (session.get("time") or {}).get("created"),
    }


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
    settings = store.load_settings()
    prompts = settings.get("prompts", {})
    prompts["system"] = "" if text == store.DEFAULT_SYSTEM_PROMPT.strip() else text
    store.save_settings({"prompts": prompts})
    return restart_soon()


@app.put("/api/prompts/agent/{agent_id}")
def set_agent_prompt(agent_id: str, body: dict = Body(...)):
    """Replace one mode's prompt entirely (empty = back to the harness prompt)."""
    text = (body.get("system") or "").strip()
    settings = store.load_settings()
    prompts = settings.get("prompts", {})
    agents = dict(prompts.get("agents", {}))
    if text:
        agents[agent_id] = text
    else:
        agents.pop(agent_id, None)
    prompts["agents"] = agents
    store.save_settings({"prompts": prompts})
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
    if agent_id == store.LEADER_ID or agent_id in store.load_settings()["delegation"].get("managed", []):
        raise ValueError("That id is used by Delegate mode — edit it in Settings → Delegation")
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


def is_custom_provider(cfg: dict) -> bool:
    return bool(cfg.get("package") or cfg.get("settings") or cfg.get("name"))


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
    overlay_providers = store.load_overlay().get("providers", {})
    # Models per provider: the ones OpenCode offers plus the ones Astra hid through the overlay.
    groups: dict[str, list] = {}
    for m in dump(client.model.list().data):
        groups.setdefault(m["providerID"], []).append(
            {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "family": m.get("family"),
                "context": (m.get("limit") or {}).get("context"),
                "variants": [v["id"] for v in m.get("variants", [])],
                "tools": (m.get("capabilities") or {}).get("tools", True),
                "status": m.get("status"),
                "hidden": False,
            }
        )
    for pid, cfg in overlay_providers.items():
        for mid, mcfg in (cfg.get("models") or {}).items():
            if (mcfg or {}).get("disabled") and not any(x["id"] == mid for x in groups.get(pid, [])):
                groups.setdefault(pid, []).append({"id": mid, "name": (mcfg or {}).get("name") or mid, "hidden": True, "variants": []})
    for lst in groups.values():
        lst.sort(key=lambda x: (x["hidden"], x["name"].lower()))
    integrations = []
    for i in dump(client.integration.list().data):
        methods = i.get("methods", [])
        integrations.append(
            {
                "id": i["id"],
                "name": i.get("name", i["id"]),
                "methods": [m.get("type") for m in methods],
                "oauth": [{"id": m.get("id"), "label": m.get("label"), "form": m.get("form")} for m in methods if m.get("type") == "oauth"],
                "env": [n for m in methods for n in m.get("names", [])],
                "credentials": by_integration.get(i["id"], []),
                "models": groups.get(i["id"], []),
                "connected": bool(by_integration.get(i["id"])) or i["id"] in groups,
            }
        )
    known = {i["id"] for i in integrations}
    for pid, models in groups.items():  # providers with models but no integration entry (custom endpoints, plugins)
        if pid not in known:
            integrations.append({"id": pid, "name": (overlay_providers.get(pid) or {}).get("name") or pid, "methods": [], "oauth": [], "env": [], "credentials": [], "models": models, "connected": True, "custom": pid in overlay_providers and is_custom_provider(overlay_providers[pid])})
    integrations.sort(key=lambda i: (not i["connected"], i["name"].lower()))
    custom = {pid: mask(cfg) for pid, cfg in overlay_providers.items() if is_custom_provider(cfg)}
    names = {i["id"]: i["name"] for i in integrations}
    hidden = [{"id": pid, "name": names.get(pid, pid)} for pid in store.load_settings().get("hiddenProviders", [])]
    return {"integrations": integrations, "custom": custom, "hidden": hidden}


@app.post("/api/models/visibility")
def model_visibility(body: dict = Body(...)):
    """Hide or show models in the picker. Batched: one restart for many toggles."""
    changes = body.get("changes") or []

    def apply(cfg: dict) -> None:
        providers = cfg.setdefault("providers", {})
        for ch in changes:
            pid, mid = str(ch["providerID"]), str(ch["id"])
            p = providers.setdefault(pid, {})
            models = p.setdefault("models", {})
            entry = models.setdefault(mid, {})
            if ch.get("hidden"):
                entry["disabled"] = True
            else:
                entry.pop("disabled", None)
            if not entry and not is_custom_provider(p):
                models.pop(mid, None)
            if not models and not is_custom_provider(p):
                providers.pop(pid, None)

    store.update_overlay(apply)
    return restart_soon()


@app.post("/api/models/refresh")
def models_refresh():
    c().location.reload()
    return models_payload()


@app.get("/api/integrations/{iid}")
def integration_get(iid: str):
    return dump(c().integration.get(iid).data)


@app.post("/api/integrations/{iid}/oauth")
def oauth_start(iid: str, body: dict = Body(...)):
    kwargs: dict[str, Any] = {"method_id": body["methodId"]}
    if body.get("answer"):
        kwargs["answer"] = body["answer"]
    if body.get("label"):
        kwargs["label"] = body["label"]
    return dump(c().integration.oauth.connect(iid, **kwargs).data)


@app.get("/api/integrations/{iid}/oauth/{aid}")
def oauth_status(iid: str, aid: str):
    return dump(c().integration.oauth.status(iid, aid).data)


@app.post("/api/integrations/{iid}/oauth/{aid}/complete")
def oauth_complete(iid: str, aid: str, body: dict = Body(default={})):
    kwargs = {"code": body["code"].strip()} if body.get("code") else {}
    c().integration.oauth.complete(iid, aid, **kwargs)
    return {"ok": True}


@app.delete("/api/integrations/{iid}/oauth/{aid}")
def oauth_cancel(iid: str, aid: str):
    c().integration.oauth.cancel(iid, aid)
    return {"ok": True}


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


@app.post("/api/providers/{pid}/remove")
def provider_remove(pid: str):
    """Remove a provider from AFH entirely (deny policy), whatever config it came from."""
    hidden = sorted(set(store.load_settings().get("hiddenProviders", [])) | {pid})
    store.save_settings({"hiddenProviders": hidden})
    return restart_soon()


@app.post("/api/providers/{pid}/restore")
def provider_restore(pid: str):
    hidden = [p for p in store.load_settings().get("hiddenProviders", []) if p != pid]
    store.save_settings({"hiddenProviders": hidden})
    return restart_soon()


@app.delete("/api/credentials/by-integration/{iid}")
def disconnect_integration(iid: str):
    """Remove every credential of a provider (the Disconnect button)."""
    client = c()
    removed = 0
    for cred in dump(client.credential.list()):
        if cred.get("integrationID") == iid:
            client.credential.remove(cred["id"])
            removed += 1
    return {"ok": True, "removed": removed}


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
    out = skills_store.install(body["source"], body["slug"], scope=scope, project_dir=body.get("directory"))
    try:
        c().location.reload()
    except Exception:
        pass
    return out


@app.delete("/api/skills")
def skills_uninstall(body: dict = Body(...)):
    scope = "project" if body.get("scope") == "project" else "global"
    ok = skills_store.uninstall(body["slug"], scope=scope, project_dir=body.get("directory"))
    try:
        c().location.reload()
    except Exception:
        pass
    return {"ok": ok}


@app.post("/api/skills/check-updates")
def skills_check_updates(body: dict = Body(default={})):
    return skills_store.check_updates(project_dir=body.get("directory"))


# ---- built-in prompts --------------------------------------------------------------------


@app.get("/api/prompts/builtin")
def prompts_builtin(providerID: str | None = None, modelID: str | None = None, force: bool = False):
    data = builtin_prompts.get_prompts(force=force)
    out = {
        "fetchedAt": data.get("fetchedAt"),
        "source": data.get("source"),
        "stale": data.get("stale", False),
        "error": data.get("error"),
        "harness": builtin_prompts.render(data.get("harness", ""), tools=("shell", "write", "edit")),
        "providers": data.get("providers", {}),
        "selectionRules": data.get("selection_rules", []),
    }
    if modelID:
        model = next((m for m in dump(c().model.list().data) if m["id"] == modelID and (not providerID or m["providerID"] == providerID)), None)
        out["forModel"] = builtin_prompts.compose_for_model(providerID or (model or {}).get("providerID", ""), modelID, family=(model or {}).get("family"), model_name=(model or {}).get("name"), prompts=data)
    return out


# ---- session transfer ----------------------------------------------------------------------


@app.get("/api/sessions/{sid}/export")
def session_export(sid: str):
    payload = transfer.export_session(c(), sid)
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
    return transfer.import_session(c(), payload, body["directory"])


@app.get("/api/import/zadloop")
def zadloop_list():
    return transfer.list_zadloop_sessions()


@app.post("/api/import/zadloop")
def zadloop_import(body: dict = Body(...)):
    payload = transfer.load_zadloop(body["path"])
    if body.get("preview"):
        return transfer.summarize(payload)
    return transfer.import_session(c(), payload, body["directory"])


# ---- first-run setup ------------------------------------------------------------------------


@app.get("/api/setup")
def setup_status():
    import shutil

    return {
        "opencode": shutil.which("opencode"),
        "npm": shutil.which("npm"),
        "node": shutil.which("node"),
        "ready": engine.ready.is_set(),
        "error": engine.error,
    }


@app.post("/api/setup/install-opencode")
def setup_install_opencode():
    """Install the OpenCode CLI with npm (the only piece AFH can't bundle)."""
    import shutil
    import subprocess
    import sys

    npm = shutil.which("npm")
    if not npm:
        raise ValueError("Node.js is not installed. Install the LTS version from https://nodejs.org, then click Install again.")
    cmd = ["cmd.exe", "/d", "/c", npm, "install", "-g", "@opencode/cli"] if sys.platform == "win32" else [npm, "install", "-g", "@opencode/cli"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "npm failed").strip()[-600:])
    if not shutil.which("opencode"):
        raise RuntimeError("npm finished but 'opencode' is still not on PATH — restart AFH and try again.")
    restart_soon()
    return {"ok": True, "output": result.stdout.strip()[-300:]}


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


# ---- context editing & undo ---------------------------------------------------------------


@app.get("/api/sessions/{sid}/context")
def session_context(sid: str):
    """Everything the model sees for this thread, including system messages."""
    page = c().message.list(sid, order="asc", limit=200)
    return [dump(m) for m in islice(page, 5000)]


@app.put("/api/sessions/{sid}/messages")
def replace_messages(sid: str, body: dict = Body(...)):
    """Rewrite the thread's history (the context editor). Keeps the session id when it can."""
    client = c()
    payload = transfer.export_session(client, sid)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Nothing left in the thread")
    payload["messages"] = messages
    client.session.remove(sid)  # frees the ids so the import can keep them
    try:
        return transfer.import_session(client, payload, body.get("directory") or (payload.get("info") or {}).get("location", {}).get("directory") or str(Path.home()))
    except Exception as exc:
        log.exception("context edit import failed; re-importing with fresh ids")
        for m in payload["messages"]:
            m.pop("id", None)
        return transfer.import_session(client, payload, body.get("directory") or str(Path.home()))


@app.post("/api/sessions/{sid}/revert")
def revert_stage(sid: str, body: dict = Body(...)):
    """Undo: rewind the thread (and optionally the files) to just before a message."""
    return dump(c().session.revert.stage(sid, message_id=body["messageId"], files=bool(body.get("files", True))))


@app.post("/api/sessions/{sid}/revert/commit")
def revert_commit(sid: str):
    c().session.revert.commit(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/revert/clear")
def revert_clear(sid: str):
    c().session.revert.clear(sid)
    return {"ok": True}


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
        if not AGENT_ID.match(did) or did in {store.LEADER_ID, "build", "plan", "general"} or did in seen:
            raise ValueError(f"Delegate id '{did}' is invalid or reserved")
        seen.add(did)
        delegates.append(
            {
                "id": did,
                "name": str(d.get("name") or did)[:60],
                "model": d.get("model") if isinstance(d.get("model"), dict) else None,
                "job": str(d.get("job", ""))[:4000],
                "system": str(d.get("system", ""))[:20000],
                "enabled": bool(d.get("enabled", True)),
                "readonly": bool(d.get("readonly", False)),
                "color": d.get("color") or None,
            }
        )
    current = store.load_settings()["delegation"]
    settings = store.save_settings(
        {"delegation": {"leaderInstructions": str(body.get("leaderInstructions", ""))[:8000], "delegates": delegates, "managed": current.get("managed", [])}}
    )
    store.apply_delegation(settings)
    return restart_soon()


@app.get("/api/sessions/{sid}/children")
def session_children(sid: str):
    return [dump(s) for s in islice(c().session.list(parent_id=sid, limit=50, order="desc"), 50)]


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
