"""Session import/export: AFH JSON files, OpenCode exports, and Zadloop (DeepSeek Harness) logs.

Everything lands in AFH's own session store. Imported messages get fresh ids; the message
shapes are the ones the UI renders (user / assistant with text, reasoning and tool parts).
"""

from __future__ import annotations

import json
import random
import string
import time
from datetime import datetime, timezone
import base64
import io
import zipfile
from pathlib import Path
from typing import Any, Callable

FORMAT = "afh-session"
VERSION = 1
APP = "agent-flow-harness"
DSH_HOME = Path.home() / ".dsh"

# How much image data to embed when importing a Zadloop export (the rest become text markers).
TOTAL_IMAGE_BUDGET = 12_000_000
SINGLE_IMAGE_MAX = 3_000_000

ZERO_TOKENS = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
# Fields the server recomputes or rejects on import.
DROP_INFO = {"parentID", "fork", "revert", "projectID", "location"}
_B62 = string.digits + string.ascii_letters


# ---- ids & time ------------------------------------------------------------


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(ms: float | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


def new_id(prefix: str, ms: float | None = None, counter: int = 0) -> str:
    """OpenCode-style id: prefix + 12 hex chars of (ms * 4096 + counter) + 14 random chars.

    Session ids count down (newest first in listings); everything else counts up.
    """
    n = (int(ms if ms is not None else now_ms()) * 0x1000 + counter) & 0xFFFFFFFFFFFF
    if prefix == "ses":
        n = ~n & 0xFFFFFFFFFFFF
    return f"{prefix}_{n:012x}" + "".join(random.choice(_B62) for _ in range(14))


# ---- OpenCode export / import --------------------------------------------------


def export_session(engine, session_id: str) -> dict:
    """The afh-session envelope for one thread (info + messages, verbatim)."""
    payload = engine.export_session(session_id)
    return {"format": FORMAT, "version": VERSION, "exportedAt": iso(now_ms()), "app": APP, "info": payload["info"], "messages": payload["messages"]}


def unpack(payload: dict) -> tuple[dict, list[dict]]:
    """Accept the afh-session envelope or a raw OpenCode `{info, messages}` export."""
    if not isinstance(payload, dict) or not isinstance(payload.get("info"), dict):
        raise ValueError("Not a session export: expected an object with info and messages")
    if payload.get("format") not in (None, FORMAT):
        raise ValueError(f"Unsupported export format: {payload.get('format')}")
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    return dict(payload["info"]), [dict(m) for m in messages]


def clean_info(info: dict, directory: str) -> dict:
    out = {k: v for k, v in info.items() if k not in DROP_INFO}
    if not str(out.get("id", "")).startswith("ses_"):
        out["id"] = new_id("ses")
    out.setdefault("cost", 0)
    out.setdefault("tokens", ZERO_TOKENS)
    t = dict(out.get("time") or {})
    t.setdefault("created", now_ms())
    t.setdefault("updated", t["created"])
    out["time"] = t
    out["projectID"] = directory
    out["location"] = {"directory": directory}
    return out


def clean_message(m: dict) -> dict:
    out = dict(m)
    t = dict(out.get("time") or {})
    t.setdefault("created", now_ms())
    if out.get("type") == "assistant":
        out.setdefault("agent", "build")
        t.setdefault("completed", t["created"])
        parts = []
        for part in out.get("content") or []:
            part = dict(part)
            if part.get("type") == "tool":
                part.setdefault("time", {"created": t["created"]})
                state = dict(part.get("state") or {})
                if state.get("status") == "completed" and not state.get("content"):
                    state["content"] = [{"type": "text", "text": "(no output)"}]
                if state.get("status") in ("streaming", "pending", "running"):
                    state["status"] = "error"
                    state.setdefault("error", {"type": "aborted", "message": "Interrupted"})
                if not isinstance(state.get("input"), dict):
                    state["input"] = {}
                part["state"] = state
            parts.append(part)
        out["content"] = parts
    out["time"] = t
    return out


def renumber(messages: list[dict]) -> list[dict]:
    """Fresh, monotonic message ids."""
    base = now_ms()
    return [dict(m, id=new_id("msg", base, i)) for i, m in enumerate(messages)]


def import_session(engine, payload: dict, directory: str) -> dict:
    """Import an afh-session, OpenCode or Zadloop payload into `directory`; returns the new session."""
    raw_info, raw_messages = unpack(payload)
    info = clean_info(raw_info, directory)
    messages = renumber([clean_message(m) for m in raw_messages])
    model = info.get("model") if isinstance(info.get("model"), dict) and info["model"].get("id") else None
    meta = dict(info.get("metadata") or {})
    meta.setdefault("afh", {})
    meta["afh"].setdefault("importedFrom", payload.get("app") or "export")
    meta["afh"].setdefault("mode", "ask")
    session = engine.store.create_session(directory, title=info.get("title") or None, agent=info.get("agent") if info.get("agent") in ("build", "plan", "delegate") else "build",
                                          model=model, permissions=info.get("permissions") or None, metadata=meta)
    if not session.get("permissions"):
        from .engine import permissions as perm

        engine.store.update_session(session["id"], permissions=perm.rules_for_mode("ask"))
    for m in messages:
        engine.store.add_message(session["id"], m)
    engine.store.update_session(session["id"], tokens=info.get("tokens") or ZERO_TOKENS, cost=info.get("cost") or 0)
    engine.publish({"type": "session.created", "data": {"sessionID": session["id"], "title": session.get("title")}})
    return engine.store.get_session(session["id"])


# ---- preview -------------------------------------------------------------------


def summarize(payload: dict) -> dict:
    info, messages = unpack(payload)
    first = next((m.get("text", "") for m in messages if m.get("type") == "user"), "")
    created = (info.get("time") or {}).get("created")
    return {
        "title": info.get("title") or "",
        "messages": sum(1 for m in messages if m.get("type") in ("user", "assistant")),
        "firstUserText": first[:500],
        "created": iso(created),
        "model": info.get("model"),
        "source": ((info.get("metadata") or {}).get("afh") or {}).get("importedFrom") or payload.get("app") or "opencode",
    }


# ---- Zadloop (DeepSeek Harness, ~/.dsh) -----------------------------------------


def _parse_jsonl(text: str) -> list[dict]:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # a torn trailing line from a crashed writer
    return records


def _unzstd(data: bytes) -> str:
    import zstandard

    return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read().decode("utf-8", errors="replace")


def read_zadloop(path: str | Path) -> list[dict]:
    """Records of a session.v4.jsonl.zstd log, in file order (multi-frame zstd)."""
    return _parse_jsonl(_unzstd(Path(path).read_bytes()))


MediaResolver = Callable[[str], "bytes | None"]


def zadloop_source(source: str | Path) -> tuple[list[dict], MediaResolver | None]:
    """Read a Zadloop session from a .zip export, a .jsonl.zstd or .jsonl file, or a session
    folder. Returns (records, media_resolver); the resolver maps an attachmentId to image bytes."""
    path = Path(source)
    if path.is_dir():
        for name in ("session.v4.jsonl.zstd", "session.v4.jsonl"):
            if (path / name).is_file():
                return zadloop_source(path / name)
        raise ValueError("That folder has no session.v4.jsonl")
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(str(path)):
        return _zadloop_from_zip(path)
    name = path.name.lower()
    if name.endswith(".zstd"):
        return read_zadloop(path), None
    if name.endswith((".jsonl", ".json")):
        return _parse_jsonl(path.read_text(encoding="utf-8", errors="replace")), None
    # Unknown extension: sniff the first bytes for the zstd magic.
    head = path.read_bytes()[:4]
    if head[:4] == b"\x28\xb5\x2f\xfd":
        return read_zadloop(path), None
    return _parse_jsonl(path.read_text(encoding="utf-8", errors="replace")), None


def _zadloop_from_zip(path: Path) -> tuple[list[dict], MediaResolver | None]:
    z = zipfile.ZipFile(str(path))
    names = z.namelist()
    main = [n for n in names if n.rsplit("/", 1)[-1] in ("session.v4.jsonl", "session.v4.jsonl.zstd") and not n.startswith("subagents/")]
    if not main:
        raise ValueError("That zip is not a Zadloop export (no session.v4.jsonl inside)")
    entry = min(main, key=lambda n: (n.count("/"), len(n)))  # the top-level session log
    data = z.read(entry)
    text = _unzstd(data) if entry.endswith(".zstd") else data.decode("utf-8", errors="replace")
    records = _parse_jsonl(text)
    media = {}
    for n in names:
        if n.startswith("media/"):
            media[n.rsplit("/", 1)[-1].rsplit(".", 1)[0]] = n  # media/<attachmentId>.png -> attachmentId

    def resolver(attachment_id: str) -> "bytes | None":
        n = media.get(attachment_id)
        try:
            return z.read(n) if n else None
        except Exception:
            return None

    return records, resolver


def _images(content: Any, resolver: MediaResolver | None, budget: list[int]) -> tuple[list[dict], list[str]]:
    """Image blocks of a user message → (files as data URLs within budget, text markers for the rest)."""
    files, markers = [], []
    for b in content or []:
        if not isinstance(b, dict) or b.get("type") != "image":
            continue
        att = b.get("attachment") or {}
        name = att.get("name") or "image.png"
        data = resolver(att.get("attachmentId")) if (resolver and att.get("attachmentId")) else None
        if data and len(data) <= SINGLE_IMAGE_MAX and budget[0] - len(data) >= 0:
            budget[0] -= len(data)
            mime = att.get("mediaType") or "image/png"
            files.append({"uri": f"data:{mime};base64,{base64.b64encode(data).decode()}", "name": name})
        else:
            markers.append(f"[Image: {name}]")
    return files, markers


def _text(blocks: Any) -> str:
    if isinstance(blocks, str):
        return blocks
    return "\n".join(b.get("text", "") for b in blocks or [] if isinstance(b, dict) and b.get("type") == "text")


def _is_user(record: dict) -> bool:
    data = record.get("data") or {}
    return ((data.get("source") or {}).get("kind") or "user") == "user"  # skip runtime-context, skill-catalog…


def zadloop_workspaces(home: Path | None = None) -> dict[str, dict]:
    """Workspace registry keyed by session id: {path, title}."""
    path = (home or DSH_HOME) / "storages" / "workspace.json"
    try:
        tables = json.loads(path.read_text(encoding="utf-8")).get("tables", {}).get("workspaces", {})
    except (OSError, ValueError):
        return {}
    out = {}
    for ws in tables.values():
        for sid in ws.get("sessionIds", []):
            out[sid] = {"path": ws.get("path"), "title": ws.get("title")}
    return out


def list_zadloop_sessions(home: Path | None = None) -> list[dict]:
    root = (home or DSH_HOME) / "sessions"
    workspaces = zadloop_workspaces(home)
    out = []
    for path in sorted(root.glob("*/session-*/session.v4.jsonl.zstd")) if root.is_dir() else []:
        try:
            records = read_zadloop(path)
        except Exception:
            continue
        head = next((r for r in records if r.get("type") == "session"), {})
        sid = head.get("id") or path.parent.name
        titles = [r["data"].get("title") for r in records if r.get("type") == "session/title" and r.get("data")]
        count = sum(
            1 for r in records if r.get("type") == "assistant/message" or (r.get("type") == "user/message" and _is_user(r))
        )
        out.append(
            {
                "id": sid,
                "title": (titles[-1] if titles else None) or _first_user_text(records)[:60] or sid,
                "cwd": head.get("cwd") or (workspaces.get(sid) or {}).get("path"),
                "workspace": (workspaces.get(sid) or {}).get("title"),
                "createdAt": head.get("createdAt") or (records[0].get("time") if records else None),
                "updatedAt": max((r.get("time") or 0 for r in records), default=None),
                "path": str(path),
                "messages": count,
            }
        )
    out.sort(key=lambda s: s.get("createdAt") or 0, reverse=True)
    return out


def _first_user_text(records: list[dict]) -> str:
    for r in records:
        if r.get("type") == "user/message" and _is_user(r):
            return _text((r.get("data") or {}).get("content"))
    return ""


def zadloop_to_opencode(source: str | Path) -> tuple[dict, list[dict]]:
    """Convert a Zadloop log (zip export, .jsonl, .jsonl.zstd, or a session folder) into (info, messages)."""
    path = Path(source)
    records, media_resolver = zadloop_source(source)
    image_budget = [TOTAL_IMAGE_BUDGET]
    head = next((r for r in records if r.get("type") == "session"), {})
    created = head.get("createdAt") or (records[0].get("time") if records else None) or now_ms()
    results = {}  # tool callId -> tool/result record
    for r in records:
        if r.get("type") == "tool/result":
            msg = (r.get("data") or {}).get("message") or {}
            if msg.get("toolCallId"):
                results[msg["toolCallId"]] = r

    messages: list[dict] = []
    model = {"id": "unknown", "providerID": "unknown"}
    title = None
    seen_users: set[str] = set()
    seen_system: set[str] = set()
    tokens = dict(ZERO_TOKENS, cache=dict(ZERO_TOKENS["cache"]))
    counter = 0

    def mid(ms: float) -> str:
        nonlocal counter
        counter += 1
        return new_id("msg", ms, counter)

    for r in records:
        kind, data, ms = r.get("type"), r.get("data") or {}, r.get("time") or created
        if kind == "session/title" and data.get("title"):
            title = data["title"]
        elif kind in ("request/context", "model/selection") and data.get("model"):
            model = {"id": data["model"], "providerID": data.get("provider") or "unknown"}
        elif kind == "system/message":
            text = _text((data.get("message") or {}).get("content"))
            if text and text not in seen_system:
                seen_system.add(text)
                messages.append({"id": mid(ms), "type": "system", "text": text, "time": {"created": ms}})
        elif kind == "user/message" and _is_user(r):
            if data.get("id") in seen_users:
                continue
            seen_users.add(data.get("id"))
            text = _text(data.get("content"))
            files, markers = _images(data.get("content"), media_resolver, image_budget)
            if markers:
                text = (text + ("\n\n" if text else "") + "\n".join(markers)).strip()
            msg = {"id": mid(ms), "type": "user", "text": text, "time": {"created": ms}}
            if files:
                msg["files"] = files
            messages.append(msg)
        elif kind == "assistant/message":
            msg = data.get("message") or {}
            src = msg.get("source") or {}
            if src.get("model"):
                model = {"id": src["model"], "providerID": src.get("provider") or "unknown"}
            usage = data.get("usage") or {}
            content, completed = [], ms
            for block in msg.get("content") or []:
                btype = block.get("type")
                if btype == "text" and block.get("text"):
                    content.append({"type": "text", "text": block["text"]})
                elif btype in ("reasoning", "thinking") and block.get("text"):
                    content.append({"type": "reasoning", "text": block["text"]})
                elif btype == "tool-call":
                    part, done = _tool_part(block, results.get(block.get("id")), ms)
                    content.append(part)
                    completed = max(completed, done)
            if not content:
                continue
            has_tools = any(p["type"] == "tool" for p in content)
            msg_tokens = {
                "input": usage.get("inputTokens") or 0,
                "output": usage.get("outputTokens") or 0,
                "reasoning": usage.get("reasoningTokens") or 0,
                "cache": {"read": usage.get("cacheReadTokens") or 0, "write": usage.get("cacheWriteTokens") or 0},
            }
            for k in ("input", "output", "reasoning"):
                tokens[k] += msg_tokens[k]
            for k in ("read", "write"):
                tokens["cache"][k] += msg_tokens["cache"][k]
            messages.append(
                {
                    "id": mid(ms),
                    "type": "assistant",
                    "agent": "build",
                    "model": dict(model),
                    "content": content,
                    "time": {"created": ms, "completed": completed},
                    "finish": "tool-calls" if has_tools else "stop",
                    "cost": 0,
                    "tokens": msg_tokens,
                }
            )

    updated = max((r.get("time") or 0 for r in records), default=created) or created
    info = {
        "id": new_id("ses", created),
        "projectID": "zadloop",  # replaced by the server from `location`
        "agent": "build",
        "model": dict(model),
        "cost": 0,
        "tokens": tokens,
        "time": {"created": created, "updated": updated},
        "title": (title if title and len(title.strip()) >= 4 else None) or _first_user_text(records)[:60].strip() or (title or "").strip() or head.get("id") or path.stem,
        "metadata": {
            "afh": {
                "importedFrom": "zadloop",
                "sourcePath": str(path),
                "sourceId": head.get("id") or path.parent.name,
                "sourceCwd": head.get("cwd"),
            }
        },
        "location": {"directory": head.get("cwd") or str(Path.home())},
    }
    return info, messages


def _tool_part(block: dict, result: dict | None, created: float) -> tuple[dict, float]:
    args = block.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            args = {"arguments": args}
    if not isinstance(args, dict):
        args = {"arguments": args}
    part = {"id": block.get("id") or new_id("call"), "name": block.get("name") or "tool", "type": "tool"}
    done = created
    if result is None:
        state = {"status": "completed", "input": args, "content": [{"type": "text", "text": "(no result recorded)"}]}
    else:
        msg = (result.get("data") or {}).get("message") or {}
        text = _text(msg.get("content")) or "(empty result)"
        done = max(created, result.get("time") or created)
        if msg.get("isError"):
            state = {"status": "error", "input": args, "error": {"type": "ToolError", "message": text}}
        else:
            state = {"status": "completed", "input": args, "content": [{"type": "text", "text": text}]}
        meta = (result.get("data") or {}).get("meta")
        if isinstance(meta, dict) and meta and state["status"] == "completed":
            state["metadata"] = meta
    part["state"] = state
    part["time"] = {"created": created, "completed": done}
    return part, done


def load_zadloop(path: str | Path) -> dict:
    """A Zadloop log as an afh-session payload, ready for summarize()/import_session()."""
    info, messages = zadloop_to_opencode(path)
    return {
        "format": FORMAT,
        "version": VERSION,
        "exportedAt": iso(now_ms()),
        "app": "zadloop",
        "info": info,
        "messages": messages,
    }
