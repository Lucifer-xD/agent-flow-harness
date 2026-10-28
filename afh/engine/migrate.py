"""Bring an OpenCode install into AFH: API keys, custom providers, MCP servers and threads.

Reads ``~/.local/share/opencode/opencode.db`` and ``~/.config/opencode/opencode.json``;
never writes to either. Runs once (recorded in settings) and can be re-run from Settings.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from .. import store as appstore
from . import config as provcfg
from . import permissions as perm
from .types import new_id, now_ms

if TYPE_CHECKING:
    from .core import Engine

log = logging.getLogger("afh.migrate")

HOME = Path.home()
OPENCODE_DB = Path(os.environ.get("OPENCODE_DB") or (Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "opencode" / "opencode.db"))
OPENCODE_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "opencode" / "opencode.json"
NPM_KIND = {"@ai-sdk/anthropic": "anthropic", "@ai-sdk/google": "gemini", "@ai-sdk/openai": "openai", "@ai-sdk/openai-compatible": "openai"}


def available() -> dict:
    return {"db": OPENCODE_DB.is_file(), "config": OPENCODE_CONFIG.is_file(), "dbPath": str(OPENCODE_DB), "configPath": str(OPENCODE_CONFIG)}


def _config() -> dict:
    try:
        return json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _db() -> sqlite3.Connection | None:
    if not OPENCODE_DB.is_file():
        return None
    con = sqlite3.connect(f"file:{OPENCODE_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---- providers -------------------------------------------------------------------------


def _models_from(oc: dict) -> list[dict]:
    out = []
    for mid, m in (oc.get("models") or {}).items():
        m = m or {}
        lim = m.get("limit") or {}
        out.append({"id": mid, "name": m.get("name") or mid, "context": lim.get("context") or 128_000, "output": lim.get("output") or 16_384,
                    "tools": m.get("tool_call", True), "reasoning": bool(m.get("reasoning")), "input": ["text", "image"] if m.get("attachment") else ["text"]})
    return out


def migrate_providers() -> dict:
    """API keys from the credential table + provider entries from opencode.json -> providers.json."""
    from .providers.catalog import KNOWN, OPENCODE_TO_AFH

    added: list[str] = []
    skipped: list[str] = []
    cfg = _config()
    oc_providers = cfg.get("provider") or {}
    keys: dict[str, str] = {}
    con = _db()
    if con:
        try:
            for r in con.execute("SELECT integration_id, value, active FROM credential ORDER BY active DESC, time_updated DESC"):
                try:
                    v = json.loads(r["value"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if v.get("type") == "key" and v.get("key") and r["integration_id"] and r["integration_id"] not in keys:
                    keys[r["integration_id"]] = v["key"]
        finally:
            con.close()
    for pid, p in oc_providers.items():
        key = ((p.get("options") or {}).get("apiKey") or "").strip()
        if key:
            keys.setdefault(pid, key)
    existing = provcfg.load()["providers"]
    for oc_id, key in keys.items():
        afh_id = OPENCODE_TO_AFH.get(oc_id, oc_id)
        if afh_id is None:
            skipped.append(oc_id)
            continue
        oc = oc_providers.get(oc_id) or {}
        if afh_id in KNOWN:
            known = KNOWN[afh_id]
            entry = {"name": known["name"], "kind": known["kind"], "base_url": (oc.get("options") or {}).get("baseURL") or known["base_url"],
                     "headers": dict(known.get("headers", {})), "extra": dict(known.get("extra", {})), "fetch_models": known.get("fetch_models", True), "catalog": afh_id}
        else:
            base = (oc.get("options") or {}).get("baseURL")
            if not base:
                skipped.append(oc_id)
                continue
            entry = {"name": oc.get("name") or oc_id, "kind": NPM_KIND.get(oc.get("npm", ""), "openai"), "base_url": base, "headers": {}, "extra": {}, "fetch_models": True}
        entry["models"] = _models_from(oc)
        if afh_id in existing and existing[afh_id].get("api_key"):
            continue  # the user already set this one up in AFH
        entry["api_key"] = key
        entry["migratedFrom"] = oc_id
        provcfg.upsert(afh_id, entry)
        added.append(afh_id)
    for oc_id, oc in oc_providers.items():  # custom endpoints without a key (local servers)
        afh_id = OPENCODE_TO_AFH.get(oc_id, oc_id)
        base = (oc.get("options") or {}).get("baseURL")
        if afh_id is None or afh_id in added or afh_id in existing or oc_id in keys:
            continue
        if not base and afh_id not in KNOWN:
            continue
        known = KNOWN.get(afh_id, {})
        provcfg.upsert(afh_id, {"name": oc.get("name") or known.get("name") or oc_id, "kind": NPM_KIND.get(oc.get("npm", ""), known.get("kind", "openai")),
                                "base_url": base or known.get("base_url", ""), "headers": dict(known.get("headers", {})), "extra": dict(known.get("extra", {})),
                                "fetch_models": known.get("fetch_models", True), "models": _models_from(oc), "migratedFrom": oc_id})
        added.append(afh_id)
    default = None
    if (m := cfg.get("model")) and "/" in m:
        pid, mid = m.split("/", 1)
        afh_id = OPENCODE_TO_AFH.get(pid, pid)
        if afh_id:
            default = {"providerID": afh_id, "id": mid.partition("#")[0]}
    return {"added": added, "skipped": skipped, "defaultModel": default}


# ---- MCP servers -----------------------------------------------------------------------------


def migrate_mcp() -> list[str]:
    servers = (_config().get("mcp") or {}).get("servers") or {}
    settings = appstore.load_settings()
    current = list((settings.get("mcp") or {}).get("servers") or [])
    names = {s.get("name") for s in current}
    added = []
    for name, cfg in servers.items():
        if name in names or not isinstance(cfg, dict):
            continue
        entry = {"name": name, "type": "remote" if cfg.get("type") == "remote" else "local", "disabled": bool(cfg.get("disabled") or cfg.get("enabled") is False)}
        if entry["type"] == "remote":
            entry["url"] = cfg.get("url", "")
            if cfg.get("headers"):
                entry["headers"] = dict(cfg["headers"])
        else:
            entry["command"] = list(cfg.get("command") or [])
            if cfg.get("environment"):
                entry["environment"] = dict(cfg["environment"])
        current.append(entry)
        added.append(name)
    if added:
        appstore.save_settings({"mcp": {"servers": current}})
    return added


# ---- sessions --------------------------------------------------------------------------------


def list_sessions(limit: int = 500) -> list[dict]:
    con = _db()
    if not con:
        return []
    try:
        rows = con.execute("SELECT id, directory, title, parent_id, agent, model, time_created, time_updated, time_archived FROM session_v2 WHERE parent_id IS NULL ORDER BY time_updated DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            n = con.execute("SELECT COUNT(*) FROM session_message WHERE session_id=? AND type IN ('user','assistant')", (r["id"],)).fetchone()[0]
            out.append({"id": r["id"], "directory": r["directory"], "title": r["title"] or "", "agent": r["agent"], "model": json.loads(r["model"]) if r["model"] else None,
                        "created": r["time_created"], "updated": r["time_updated"], "archived": bool(r["time_archived"]), "messages": n})
        return out
    finally:
        con.close()


def _load_session(con: sqlite3.Connection, sid: str) -> tuple[dict, list[dict]]:
    r = con.execute("SELECT * FROM session_v2 WHERE id=?", (sid,)).fetchone()
    if not r:
        raise KeyError(sid)
    msgs = []
    for m in con.execute("SELECT id, type, data FROM session_message WHERE session_id=? ORDER BY seq", (sid,)):
        try:
            data = json.loads(m["data"])
        except (TypeError, json.JSONDecodeError):
            continue
        if m["type"] not in ("user", "assistant", "system", "synthetic", "compaction"):
            continue
        data = dict(data)
        data["id"] = m["id"]
        data["type"] = m["type"]
        if m["type"] == "user":  # inline images are huge; keep the text and a note of the files
            files = data.pop("files", None) or []
            if files:
                data["files"] = [{"name": f.get("name") or f.get("filename") or "image", "mime": f.get("mime") or f.get("mimeType")} for f in files]
        msgs.append(data)
    info = {"id": r["id"], "title": r["title"], "agent": r["agent"], "model": json.loads(r["model"]) if r["model"] else None, "directory": r["directory"],
            "tokens": {"input": r["tokens_input"] or 0, "output": r["tokens_output"] or 0, "reasoning": r["tokens_reasoning"] or 0,
                       "cache": {"read": r["tokens_cache_read"] or 0, "write": r["tokens_cache_write"] or 0}},
            "cost": r["cost"] or 0, "created": r["time_created"], "updated": r["time_updated"], "archived": bool(r["time_archived"])}
    return info, msgs


def migrate_sessions(engine: "Engine", ids: list[str] | None = None, *, directory_map: dict[str, str] | None = None) -> dict:
    """Copy threads (and their delegation children) into AFH's database. Skips ones already imported."""
    from .providers.catalog import OPENCODE_TO_AFH

    con = _db()
    if not con:
        return {"imported": 0, "skipped": 0}
    imported = skipped = 0
    try:
        if ids is None:
            ids = [r[0] for r in con.execute("SELECT id FROM session_v2 WHERE parent_id IS NULL ORDER BY time_created")]
        done = set()
        for archived in (False, True):
            for s in engine.store.list_sessions(limit=100_000, archived=archived):
                done.add(((s.get("metadata") or {}).get("afh") or {}).get("importedId"))

        def copy_one(sid: str, parent_new: str | None) -> str | None:
            if sid in done:
                return None
            info, msgs = _load_session(con, sid)
            if not msgs and parent_new is None:
                return None
            model = info["model"]
            if model and model.get("providerID"):
                afh_pid = OPENCODE_TO_AFH.get(model["providerID"], model["providerID"])
                model = {"providerID": afh_pid, "id": model.get("id"), **({"variant": model["variant"]} if model.get("variant") else {})} if afh_pid else None
            directory = (directory_map or {}).get(info["directory"], info["directory"])
            agent = info["agent"] if info["agent"] in ("build", "plan", "delegate") else "build"
            s = engine.store.create_session(directory, title=info["title"] or None, agent=agent, model=model, permissions=perm.rules_for_mode("ask"),
                                            metadata={"afh": {"mode": "ask", "importedFrom": "opencode", "importedId": sid}}, parent_id=parent_new)
            for m in msgs:
                m["id"] = new_id("msg")
                if m.get("type") == "assistant":
                    t = m.setdefault("time", {})
                    t.setdefault("completed", t.get("created") or now_ms())
                    for p in m.get("content") or []:
                        if p.get("type") == "tool":
                            st = p.setdefault("state", {})
                            if st.get("status") in ("streaming", "pending", "running"):
                                st["status"] = "error"
                                st.setdefault("error", {"type": "aborted", "message": "Interrupted before migration"})
                            if not isinstance(st.get("input"), dict):
                                st["input"] = {}
                engine.store.add_message(s["id"], m)
            engine.store.update_session(s["id"], tokens=info["tokens"], cost=info["cost"], archived=info["archived"], created=info["created"], updated=info["updated"])
            for child in con.execute("SELECT id FROM session_v2 WHERE parent_id=? ORDER BY time_created", (sid,)):
                copy_one(child[0], s["id"])
            return s["id"]

        for sid in ids:
            try:
                new = copy_one(sid, None)
            except Exception as err:
                log.warning("session %s not migrated: %s", sid, err)
                skipped += 1
                continue
            if new:
                imported += 1
            else:
                skipped += 1
    finally:
        con.close()
    return {"imported": imported, "skipped": skipped}


def migrate_all(engine: "Engine", *, sessions: bool = True) -> dict:
    out: dict = {"available": available()}
    try:
        out["providers"] = migrate_providers()
    except Exception as err:
        log.exception("providers")
        out["providers"] = {"error": str(err)}
    try:
        out["mcp"] = migrate_mcp()
    except Exception as err:
        log.exception("mcp")
        out["mcp"] = {"error": str(err)}
    if sessions:
        try:
            out["sessions"] = migrate_sessions(engine)
        except Exception as err:
            log.exception("sessions")
            out["sessions"] = {"error": str(err)}
    patch: dict = {"migration": {"opencode": {"done": True, "at": now_ms()}}}
    dm = (out.get("providers") or {}).get("defaultModel")
    if dm and not appstore.load_settings().get("defaultModel"):
        patch["defaultModel"] = dm
    appstore.save_settings(patch)
    return out
