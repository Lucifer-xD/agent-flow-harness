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
        moved = [_migrate(p) for p in data["providers"].values() if isinstance(p, dict)]
        if any(moved):  # saved at once, so the new account ids stay the same on the next read
            save(data)
        return data


# ---- accounts ---------------------------------------------------------------------------------
# A provider can hold several accounts: each one a sign-in (``auth``) or an API key. The account in
# use is ``active``; its credentials are also kept in the provider's own ``api_key``/``auth`` so
# everything that reads one provider keeps working. engine/accounts.py switches between them.

CREDS = ("api_key", "auth")
KEY_SIGN_INS = ("openrouter", "poe", "digitalocean")  # sign-ins that end in a plain API key


def _new_id() -> str:
    import secrets

    return secrets.token_hex(4)


def account_label(acc: dict) -> str:
    auth = acc.get("auth") or {}
    if acc.get("label"):
        return acc["label"]
    if auth.get("account"):
        return str(auth["account"])
    key = acc.get("api_key") or ""
    return ("Key ••••" + key[-4:]) if len(key) > 8 else ("Key" if key else "Account")


def _migrate(p: dict) -> bool:
    """Older files kept one key or sign-in per provider: that becomes Account 1. True if it changed."""
    if isinstance(p.get("accounts"), list):
        return False
    if not (p.get("api_key") or p.get("auth")):
        p["accounts"], p["active"] = [], ""
        return True
    acc = {"id": _new_id(), "enabled": True, **{k: copy.deepcopy(p[k]) for k in CREDS if p.get(k)}}
    p["accounts"], p["active"] = [acc], acc["id"]
    return True


def _mirror(p: dict) -> None:
    """Copy the active account's credentials to the provider (or clear them when none is left)."""
    acc = next((a for a in p.get("accounts") or [] if a.get("id") == p.get("active")), None)
    for k in CREDS:
        if acc and acc.get(k):
            p[k] = copy.deepcopy(acc[k])
        else:
            p.pop(k, None)


def _same(a: dict, b: dict) -> bool:
    """Two credentials for the same account: the same key, or a sign-in to the same account."""
    if a.get("api_key") and a.get("api_key") == b.get("api_key"):
        return True
    x, y = a.get("auth") or {}, b.get("auth") or {}
    if not x or not y or x.get("type") != y.get("type"):
        return False
    if x.get("type") in KEY_SIGN_INS:  # one account per provider: signing in again replaces it
        return True
    for k in ("account", "email", "user_id", "account_id"):
        if x.get(k) and y.get(k):
            return str(x[k]).lower() == str(y[k]).lower()
    return False


def accounts(pid: str) -> list[dict]:
    p = entry(pid) or {}
    return copy.deepcopy(p.get("accounts") or [])


def add_account(pid: str, creds: dict, base: dict | None = None, label: str = "", activate: bool = False) -> str:
    """Add a key or sign-in to the provider (made from ``base`` when new). The same account again
    updates it instead. Returns the account id."""
    with _lock:
        data = load()
        p = data["providers"].get(pid)
        if p is None:
            p = data["providers"][pid] = {"id": pid, "enabled": True, "models": [], "fetched": [], "hidden": [], "headers": {}, "extra": {}, "accounts": [], "active": ""}
        for k, v in (base or {}).items():
            if k not in CREDS:
                p[k] = v
        new = {k: copy.deepcopy(creds[k]) for k in CREDS if creds.get(k)}
        if not new:
            raise ValueError("Nothing to add: no key and no sign-in")
        found = next((a for a in p["accounts"] if _same(a, new)), None)
        if found:
            for k in CREDS:
                found.pop(k, None)
            found.update(new)
            found["enabled"] = True
            if label:
                found["label"] = label
            aid = found["id"]
        else:
            aid = _new_id()
            p["accounts"].append({"id": aid, "enabled": True, **({"label": label} if label else {}), **new})
        if activate or not any(a.get("id") == p.get("active") for a in p["accounts"]):
            p["active"] = aid
        _mirror(p)
        save(data)
        return aid


def save_creds(pid: str, account_id: str, patch: dict) -> None:
    """New credentials for one account (a refreshed token); the provider's copy follows if it is in use."""
    with _lock:
        data = load()
        p = data["providers"].get(pid)
        if not p:
            return
        acc = next((a for a in p["accounts"] if a.get("id") == account_id), None) if account_id else None
        if acc is None and not account_id:
            acc = next((a for a in p["accounts"] if a.get("id") == p.get("active")), None)
        if acc is None:
            return
        acc.update({k: copy.deepcopy(v) for k, v in patch.items() if k in CREDS})
        _mirror(p)
        save(data)


def update_account(pid: str, account_id: str, patch: dict) -> None:
    """Rename, turn on/off, move (``move``: -1 up, +1 down) or start using (``active``) one account."""
    with _lock:
        data = load()
        p = data["providers"].get(pid)
        accs = (p or {}).get("accounts") or []
        i = next((n for n, a in enumerate(accs) if a.get("id") == account_id), None)
        if i is None:
            raise KeyError(account_id)
        acc = accs[i]
        if "label" in patch:
            label = str(patch["label"] or "").strip()[:80]
            if label:
                acc["label"] = label
            else:
                acc.pop("label", None)
        if "enabled" in patch:
            acc["enabled"] = bool(patch["enabled"])
        if patch.get("move"):
            j = max(0, min(len(accs) - 1, i + (1 if int(patch["move"]) > 0 else -1)))
            accs[i], accs[j] = accs[j], accs[i]
        if patch.get("active"):
            acc["enabled"] = True
            p["active"] = account_id
        if p.get("active") == account_id and acc.get("enabled") is False:
            nxt = next((a for a in accs if a.get("enabled", True) and a.get("id") != account_id), None)
            if nxt:
                p["active"] = nxt["id"]
        _mirror(p)
        save(data)


def remove_account(pid: str, account_id: str) -> None:
    with _lock:
        data = load()
        p = data["providers"].get(pid)
        if not p or not any(a.get("id") == account_id for a in p["accounts"]):
            raise KeyError(account_id)
        p["accounts"] = [a for a in p["accounts"] if a.get("id") != account_id]
        if p.get("active") == account_id:
            nxt = next((a for a in p["accounts"] if a.get("enabled", True)), None) or (p["accounts"][0] if p["accounts"] else None)
            p["active"] = nxt["id"] if nxt else ""
        _mirror(p)
        save(data)


def set_rotation(pid: str, on: bool) -> None:
    upsert(pid, {"rotation": bool(on)})


def account_config(pid: str, account_id: str) -> ProviderConfig | None:
    """The provider as if this account were in use (for its usage meter)."""
    for cfg in _configs(account=account_id, only=pid, all_=True):
        return cfg if cfg.account_id == account_id else None
    return None


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
        _migrate(cur)
        for k, v in patch.items():
            if v is None and k in ("api_key",):
                continue
            cur[k] = v
        if any(patch.get(k) for k in CREDS):  # a key typed in Settings belongs to the account in use
            acc = next((a for a in cur["accounts"] if a.get("id") == cur.get("active")), None)
            if acc is None:
                acc = {"id": _new_id(), "enabled": True}
                cur["accounts"].append(acc)
                cur["active"] = acc["id"]
            acc.update({k: copy.deepcopy(patch[k]) for k in CREDS if patch.get(k)})
            _mirror(cur)
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


OVERRIDABLE = ("name", "context", "output", "variants", "input", "reasoning")
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
        if isinstance(ov.get("name"), str) and ov["name"].strip():
            m.name = ov["name"].strip()
        if ov.get("context"):
            m.context = int(ov["context"])
        if ov.get("output"):
            m.output = int(ov["output"])
        if isinstance(ov.get("variants"), list):
            m.variants = [str(v) for v in ov["variants"] if str(v).strip()]
            # An effort is only sent to a model that reasons. An endpoint that lists its models
            # without saying so (a custom or local server) left the levels you typed doing nothing.
            if m.variants:
                m.reasoning = True
        if isinstance(ov.get("input"), list) and ov["input"]:
            m.input = [str(v) for v in ov["input"]]
        if isinstance(ov.get("reasoning"), bool):
            m.reasoning = ov["reasoning"]
    hidden = set(p.get("hidden", []))
    for m in out.values():
        m.hidden = m.id in hidden
    return list(out.values())


def provider_configs() -> list[ProviderConfig]:
    return _configs()


def provider_config(pid: str) -> ProviderConfig | None:
    for cfg in _configs(only=pid):
        return cfg
    return None


def _configs(account: str = "", only: str = "", all_: bool = False) -> list[ProviderConfig]:
    from .providers.catalog import env_key, render_url

    out = []
    for pid, p in load()["providers"].items():
        if only and pid != only:
            continue
        if p.get("enabled") is False and not all_:
            continue
        aid = account or p.get("active") or ""
        acc = next((a for a in p.get("accounts") or [] if a.get("id") == aid), None)
        src = acc if acc is not None else p
        base = render_url(p.get("base_url", ""), p.get("params"))  # ${VAR} parts come from the setup fields or the environment
        key = src.get("api_key") or env_key(p.get("catalog"))
        out.append(ProviderConfig(id=pid, name=p.get("name") or pid, kind=p.get("kind", "openai"), base_url=base, api_key=key,
                                  headers=dict(p.get("headers") or {}), models=models_of(p, pid), fetch_models=p.get("fetch_models", True),
                                  extra=dict(p.get("extra") or {}), auth=dict(src.get("auth") or {}), account_id=acc["id"] if acc else "",
                                  account_label=account_label(acc) if acc else ""))
    return out


def public(p: dict) -> dict:
    """Shape for the UI: never the key itself."""
    from .providers.catalog import env_key

    key = p.get("api_key") or ""
    auth = p.get("auth") or {}
    env = "" if key else env_key(p.get("catalog"))
    out = {k: v for k, v in p.items() if k not in ("api_key", "auth", "accounts")}
    accs = [{"id": a["id"], "label": account_label(a), "named": bool(a.get("label")), "enabled": a.get("enabled", True) is not False,
             "kind": "signin" if (a.get("auth") or {}).get("type") and (a.get("auth") or {}).get("type") not in KEY_SIGN_INS else "key",
             "keyHint": ("••••" + a["api_key"][-4:]) if len(a.get("api_key") or "") > 8 else "", "active": a["id"] == p.get("active")}
            for a in p.get("accounts") or []]
    return out | {"hasKey": bool(key or env), "keyHint": ("••••" + key[-4:]) if len(key) > 8 else ("••••" if key else ""), "keyFromEnv": bool(env),
                  "signedIn": bool(auth), "account": auth.get("account") or "", "accounts": accs, "rotation": p.get("rotation", True) is not False}
