"""Configured providers (keys, endpoints, models) in ~/.afh/providers.json."""

from __future__ import annotations

import copy
import json
import threading

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
                     tools=d.get("tools", True), reasoning=d.get("reasoning", False), variants=list(d.get("variants") or []), input=list(d.get("input") or ["text"]),
                     cost=d["cost"] if isinstance(d.get("cost"), dict) else None)


OVERRIDABLE = ("context", "output", "variants", "input", "reasoning")
SELF_DESCRIBING = {"chatgpt", "antigravity"}  # providers whose model list carries context, effort levels and inputs


def models_of(p: dict, pid: str | None = None) -> list[ModelInfo]:
    """The provider's models with the best facts available, best last:
    AFH's static list < the endpoint's own list < models.dev < what the user set in Settings."""
    from . import modelsdev
    from .providers.catalog import STATIC_MODELS

    pid = pid or p.get("id") or ""
    catalog = p.get("catalog")
    listed = p.get("fetched") or []
    out: dict[str, ModelInfo] = {}
    # The endpoint's own list wins outright: guessed ids it did not list would fail when picked.
    # Without one, models.dev's list for this provider, else AFH's static one.
    known = modelsdev.provider_models(pid, catalog) if not listed else []
    if known:
        out = {m.id: m for m in known}
    elif not listed:
        for m in STATIC_MODELS.get(catalog or pid, []):
            out[m.id] = modelsdev.enrich(ModelInfo(**m.to_dict()), modelsdev.lookup(pid, catalog, m.id))
    own_facts = catalog in SELF_DESCRIBING  # their own list already has the exact facts
    for d in listed + p.get("models", []):
        try:
            out[d["id"]] = _model(d) if own_facts else modelsdev.enrich(_model(d), modelsdev.lookup(pid, catalog, d["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    for mid, ov in (p.get("overrides") or {}).items():
        m = out.get(mid)
        if m is None or not isinstance(ov, dict):
            continue
        if ov.get("context"):
            m.context = int(ov["context"])
        if ov.get("output"):
            m.output = int(ov["output"])
        if isinstance(ov.get("variants"), list):
            m.variants = [str(v) for v in ov["variants"] if str(v).strip()]
        if isinstance(ov.get("input"), list) and ov["input"]:
            m.input = [str(v) for v in ov["input"]]
        if isinstance(ov.get("reasoning"), bool):
            m.reasoning = ov["reasoning"]
    hidden = set(p.get("hidden", []))
    for m in out.values():
        m.hidden = m.id in hidden
    return list(out.values())


def provider_configs() -> list[ProviderConfig]:
    from .providers.catalog import env_key, render_url

    out = []
    for pid, p in load()["providers"].items():
        if p.get("enabled") is False:
            continue
        base = render_url(p.get("base_url", ""), p.get("params"))  # ${VAR} parts come from the setup fields or the environment
        key = p.get("api_key") or env_key(p.get("catalog"))
        out.append(ProviderConfig(id=pid, name=p.get("name") or pid, kind=p.get("kind", "openai"), base_url=base, api_key=key,
                                  headers=dict(p.get("headers") or {}), models=models_of(p, pid), fetch_models=p.get("fetch_models", True),
                                  extra=dict(p.get("extra") or {}), auth=dict(p.get("auth") or {})))
    return out


def public(p: dict) -> dict:
    """Shape for the UI: never the key itself."""
    from .providers.catalog import env_key

    key = p.get("api_key") or ""
    auth = p.get("auth") or {}
    env = "" if key else env_key(p.get("catalog"))
    out = {k: v for k, v in p.items() if k not in ("api_key", "auth")}
    return out | {"hasKey": bool(key or env), "keyHint": ("••••" + key[-4:]) if len(key) > 8 else ("••••" if key else ""), "keyFromEnv": bool(env),
                  "signedIn": bool(auth), "account": auth.get("account") or ""}
