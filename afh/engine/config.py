"""Configured providers (keys, endpoints, models) in ~/.afh/providers.json."""

from __future__ import annotations

import copy
import json
import threading
from typing import Any

from .. import store
from .types import ModelInfo, ProviderConfig

PATH = store.AFH_DIR / "providers.json"
_lock = threading.RLock()


def load() -> dict:
    with _lock:
        try:
            data = json.loads(PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.setdefault("providers", {})
        return data


def save(data: dict) -> None:
    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PATH)


def entry(pid: str) -> dict | None:
    return load()["providers"].get(pid)


def upsert(pid: str, patch: dict) -> dict:
    with _lock:
        data = load()
        cur = data["providers"].setdefault(pid, {"id": pid, "enabled": True, "models": [], "fetched": [], "hidden": [], "headers": {}, "extra": {}})
        for k, v in patch.items():
            if v is None and k in ("api_key",):
                continue
            cur[k] = v
        save(data)
        return copy.deepcopy(cur)


def remove(pid: str) -> None:
    with _lock:
        data = load()
        data["providers"].pop(pid, None)
        save(data)


def set_hidden(changes: list[dict]) -> None:
    """[{providerID, id, hidden}] — which models stay out of the picker."""
    with _lock:
        data = load()
        for ch in changes:
            p = data["providers"].get(ch["providerID"])
            if not p:
                continue
            hidden = set(p.get("hidden", []))
            (hidden.add if ch.get("hidden") else hidden.discard)(ch["id"])
            p["hidden"] = sorted(hidden)
        save(data)


def _model(d: dict) -> ModelInfo:
    return ModelInfo(id=d["id"], name=d.get("name") or d["id"], context=int(d.get("context") or 128_000), output=int(d.get("output") or 16_384),
                     tools=d.get("tools", True), reasoning=d.get("reasoning", False), variants=list(d.get("variants") or []), input=list(d.get("input") or ["text"]))


def models_of(p: dict) -> list[ModelInfo]:
    """Catalog models, then fetched, then manual ones win on the same id; hidden flag applied."""
    from .providers.catalog import STATIC_MODELS

    out: dict[str, ModelInfo] = {m.id: ModelInfo(**m.to_dict()) for m in STATIC_MODELS.get(p.get("catalog") or p.get("id") or "", [])}
    for d in p.get("fetched", []) + p.get("models", []):
        try:
            out[d["id"]] = _model(d)
        except (KeyError, TypeError, ValueError):
            continue
    hidden = set(p.get("hidden", []))
    for m in out.values():
        m.hidden = m.id in hidden
    return list(out.values())


def provider_configs() -> list[ProviderConfig]:
    out = []
    for pid, p in load()["providers"].items():
        if p.get("enabled") is False:
            continue
        out.append(ProviderConfig(id=pid, name=p.get("name") or pid, kind=p.get("kind", "openai"), base_url=p.get("base_url", ""), api_key=p.get("api_key", ""),
                                  headers=dict(p.get("headers") or {}), models=models_of(p), fetch_models=p.get("fetch_models", True), extra=dict(p.get("extra") or {})))
    return out


def public(p: dict) -> dict:
    """Shape for the UI: never the key itself."""
    key = p.get("api_key") or ""
    return {k: v for k, v in p.items() if k != "api_key"} | {"hasKey": bool(key), "keyHint": ("••••" + key[-4:]) if len(key) > 8 else ("••••" if key else "")}
