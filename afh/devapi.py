"""Developer access to AFH's local API: long-lived API keys and the discovery file.

The AFH window talks to the backend with a token that changes every launch. Scripts, the SDKs
and other tools use API keys instead: created in Settings → Developer, shown once, stored here
only as SHA-256 hashes. Keys work on this machine only (never through Remote access).

While AFH runs, ``~/.afh/api.json`` says where the API is ({url, version, pid}); the SDKs read it,
so a script needs no port number.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from . import store

KEYS_FILE = "api-keys.json"
DISCOVERY_FILE = "api.json"
PREFIX = "afh_"
_lock = threading.Lock()
_last_used_saved: dict[str, float] = {}


def _path(name: str) -> Path:
    return store.AFH_DIR / name


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def list_keys() -> list[dict]:
    try:
        data = json.loads(_path(KEYS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(keys: list[dict]) -> None:
    p = _path(KEYS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def public(k: dict) -> dict:
    return {key: k.get(key) for key in ("id", "name", "prefix", "created", "lastUsed")}


def create_key(name: str) -> tuple[dict, str]:
    """A new key. Returns (its public record, the key itself — shown to the user once)."""
    raw = PREFIX + secrets.token_urlsafe(32)
    rec = {"id": secrets.token_hex(6), "name": (name or "API key").strip()[:60], "prefix": raw[:10], "hash": _hash(raw),
           "created": int(time.time() * 1000), "lastUsed": None}
    with _lock:
        keys = list_keys()
        keys.append(rec)
        _save(keys)
    return public(rec), raw


def delete_key(key_id: str) -> bool:
    with _lock:
        keys = list_keys()
        kept = [k for k in keys if k.get("id") != key_id]
        if len(kept) == len(keys):
            return False
        _save(kept)
    return True


def check(token: str | None) -> bool:
    """True when `token` is one of the API keys (constant-time compare)."""
    if not token or not token.startswith(PREFIX):
        return False
    h = _hash(token)
    for k in list_keys():
        if hmac.compare_digest(h, str(k.get("hash", ""))):
            _touch(k["id"])
            return True
    return False


def _touch(key_id: str) -> None:
    now = time.time()
    if now - _last_used_saved.get(key_id, 0) < 60:  # at most one write a minute per key
        return
    _last_used_saved[key_id] = now
    with _lock:
        keys = list_keys()
        for k in keys:
            if k.get("id") == key_id:
                k["lastUsed"] = int(now * 1000)
        _save(keys)


# ---- discovery ------------------------------------------------------------------------------


def write_discovery(port: int, version: str) -> None:
    p = _path(DISCOVERY_FILE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": f"http://127.0.0.1:{port}", "version": version, "pid": os.getpid(),
                                 "started": int(time.time() * 1000)}, indent=2), encoding="utf-8")
    except OSError:
        pass


def clear_discovery() -> None:
    p = _path(DISCOVERY_FILE)
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("pid") == os.getpid():
            p.unlink()
    except (OSError, ValueError):
        pass
