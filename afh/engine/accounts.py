"""Several accounts per provider, switched between steps so a running task never stops.

A provider's accounts (keys and sign-ins) live in providers.json (engine/config.py). Before every
model step the runner asks ``before_step`` which account to use:

* the account in use stays until its plan reaches the threshold (90% by default) in any window
  that counts for the model, or until it is resting after a refusal;
* then the next account in the user's order that is under the threshold (or the least used one,
  with order "least");
* when every account is over the threshold, the least used one carries on until it is refused;
* when every account is resting, AFH waits for the first one to come back and continues by itself
  (or stops, with "whenAllUsed": "stop").

A refusal the provider gives anyway (``limits.classify`` says "used_up") makes the account rest
until its reset time; the runner then runs the same step again and ``before_step`` moves on.

Each switch leaves a note in the thread. The note has no text for the model, so the model never
sees it. Rests are kept in ~/.afh/account-state.json so the desktop app, the terminal app and the
CLI agree on them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from .. import store as afhstore
from . import config as provcfg
from . import limits, usage

if TYPE_CHECKING:
    from .core import Engine

log = logging.getLogger("afh.accounts")

STATE = afhstore.AFH_DIR / "account-state.json"
DEFAULTS = {"threshold": 90, "order": "fill", "whenAllUsed": "wait"}
USED_UP = 99.5  # a window at 100% is as good as a refusal
_file_lock = threading.RLock()
_switch_locks: dict[str, asyncio.Lock] = {}


# ---- rests (shared between AFH processes) -------------------------------------------------------


def _read() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _write(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def rest(pid: str, aid: str, until: float, why: str = "") -> None:
    """The account is used up until ``until`` (epoch seconds)."""
    with _file_lock:
        data = _read()
        data.setdefault(pid, {})[aid] = {"until": float(until), "why": why[:200], "at": time.time()}
        _write(data)


def clear_rest(pid: str, aid: str) -> None:
    with _file_lock:
        data = _read()
        if data.get(pid, {}).pop(aid, None) is not None:
            _write(data)


def resting(pid: str, aid: str) -> dict | None:
    r = _read().get(pid, {}).get(aid)
    return r if isinstance(r, dict) and float(r.get("until") or 0) > time.time() else None


def prefs(settings: dict | None) -> dict:
    got = (settings or {}).get("accounts") if isinstance((settings or {}).get("accounts"), dict) else {}
    out = dict(DEFAULTS)
    try:
        out["threshold"] = max(10, min(100, int(got.get("threshold", DEFAULTS["threshold"]))))
    except (TypeError, ValueError):
        pass
    if got.get("order") in ("fill", "least"):
        out["order"] = got["order"]
    if got.get("whenAllUsed") in ("wait", "stop"):
        out["whenAllUsed"] = got["whenAllUsed"]
    return out


# ---- usage of one account -------------------------------------------------------------------------

_FAMILY_IDS = {"claude": "claude", "flash": "gemini-flash", "gemini": "gemini-pro", "gpt-oss": "gpt-oss"}


def _family(model_id: str) -> str:
    low = (model_id or "").lower()
    return next((fid for key, fid in _FAMILY_IDS.items() if key in low), "")


def used(report: dict | None, model_id: str = "") -> tuple[float | None, float, str]:
    """(highest used percent of the windows that count for this model, when that window resets
    (epoch seconds, 0 if unknown), its label). Antigravity reports a quota per model family; only
    the family of the model in use counts there."""
    if not report:
        return None, 0.0, ""
    windows = [w for w in report.get("windows") or [] if isinstance(w, dict) and w.get("usedPercent") is not None]
    fam = _family(model_id)
    if fam and any(w.get("id") == fam for w in windows):
        windows = [w for w in windows if w.get("id") == fam]
    elif windows and all(w.get("id") in _FAMILY_IDS.values() for w in windows):
        windows = []  # families, none of them this model's
    if report.get("limited"):
        return 100.0, 0.0, "plan"
    if not windows:
        return None, 0.0, ""
    top = max(windows, key=lambda w: float(w["usedPercent"]))
    return float(top["usedPercent"]), float(top.get("resetsAt") or 0) / 1000, str(top.get("label") or "")


def known(cfg: Any) -> dict | None:
    """What is known about the account's limits without waiting on the network. A stale or missing
    live answer is fetched in the background for next time."""
    k = usage.key(cfg)
    hit = usage._cache.get(k)
    if usage.live_source(cfg) and (hit is None or time.time() - hit[0] >= usage.TTL):
        try:
            asyncio.get_running_loop().create_task(_refresh(cfg))
        except RuntimeError:
            pass
    out: dict = {"windows": []}
    if hit and isinstance(hit[1], dict):
        out.update({key: v for key, v in hit[1].items() if key in ("windows", "limited")})
    seen = usage._headers.get(k)
    if seen:
        windows, _ = usage.from_headers(seen[1])
        if windows and (not out["windows"] or seen[0] > (hit[0] if hit else 0)):
            out["windows"] = windows
    return out


_refreshing: set[str] = set()


async def _refresh(cfg: Any) -> None:
    k = usage.key(cfg)
    if k in _refreshing:
        return
    _refreshing.add(k)
    try:
        await asyncio.wait_for(usage.report(cfg, None, force=True), 20)
    except Exception as err:
        log.info("usage for %s: %s", k, err)
    finally:
        _refreshing.discard(k)


# ---- picking -------------------------------------------------------------------------------------


def _when(ts: float) -> str:
    if not ts:
        return "later"
    fmt = "%H:%M" if ts - time.time() < 20 * 3600 else "%a %H:%M"
    return time.strftime(fmt, time.localtime(ts))


def pool(pid: str) -> tuple[dict, list[dict]]:
    """(provider entry, its accounts that are switched on), or ({}, []) when rotation is off."""
    p = provcfg.entry(pid) or {}
    if p.get("rotation") is False:
        return p, []
    accs = [a for a in p.get("accounts") or [] if a.get("enabled", True) is not False and (a.get("api_key") or a.get("auth"))]
    return p, accs


async def before_step(engine: "Engine", run: Any, provider: Any, model_id: str) -> Any:
    """The provider to use for the next step: the same one, or the same provider on another account."""
    cfg = provider.config
    pid = cfg.id
    p, accs = pool(pid)
    if len(accs) < 2:
        return provider
    lock = _switch_locks.setdefault(pid, asyncio.Lock())
    async with lock:
        # Another AFH window (or a run here) may have switched already: follow providers.json.
        if p.get("active") and p["active"] != cfg.account_id:
            provider = engine.use_account(pid) or provider
            cfg = provider.config
        while True:
            choice = _pick(engine, pid, accs, cfg, model_id)
            if choice is None:
                return provider
            kind, target, why, until = choice
            if kind == "switch":
                provcfg.update_account(pid, target["id"], {"active": True})
                new = engine.use_account(pid) or provider
                _note(engine, run, f"Account switched: {cfg.name}, from {cfg.account_label or 'account'} to {provcfg.account_label(target)}. {why}",
                      {"provider": pid, "from": cfg.account_id, "to": target["id"]})
                return new
            # every account is resting
            if prefs(engine.settings())["whenAllUsed"] == "stop":
                from .runner import ProviderError

                raise ProviderError({"type": "error", "kind": "limit", "status": None,
                                     "message": f"All {len(accs)} {cfg.name} accounts are used up. The first one is free again at {_when(until)}."})
            _note(engine, run, f"All {len(accs)} {cfg.name} accounts are used up. Waiting until {_when(until)}, then continuing.",
                  {"provider": pid, "waitUntil": int(until * 1000)})
            await _wait(run, until)
            p, accs = pool(pid)
            if len(accs) < 2:
                return engine.use_account(pid) or provider
            cfg = provider.config


def _pick(engine: "Engine", pid: str, accs: list[dict], cfg: Any, model_id: str) -> tuple[str, dict, str, float] | None:
    """None to stay; ("switch", account, why, 0); or ("wait", {}, "", until) when all are resting."""
    opts = prefs(engine.settings())
    threshold = float(opts["threshold"])
    cur = next((a for a in accs if a["id"] == cfg.account_id), None)
    cur_rest = resting(pid, cfg.account_id) if cur else {"until": 0, "why": "switched off"}
    cur_pct, cur_reset, cur_win = used(known(cfg), model_id) if cur else (None, 0.0, "")
    if cur is not None and not cur_rest and (cur_pct is None or cur_pct < threshold):
        return None
    if cur is not None and not cur_rest and cur_pct is not None and cur_pct >= USED_UP:
        rest(pid, cur["id"], cur_reset or time.time() + limits.PLAN_REST, f"{cur_win or 'plan'} limit used up")
        cur_rest = resting(pid, cur["id"])
    # the others, in the user's order starting after the one in use
    i = next((n for n, a in enumerate(accs) if cur is not None and a["id"] == cur["id"]), -1)
    order = accs[i + 1:] + accs[:i + 1] if i >= 0 else list(accs)
    free: list[tuple[dict, float | None]] = []
    soonest = 0.0
    for a in order:
        r = resting(pid, a["id"])
        if r:
            soonest = min(soonest or r["until"], r["until"])
            continue
        acfg = cfg if cur is not None and a["id"] == cur["id"] else provcfg.account_config(pid, a["id"])
        pct, reset, win = used(known(acfg), model_id) if acfg else (None, 0.0, "")
        if pct is not None and pct >= USED_UP:
            rest(pid, a["id"], reset or time.time() + limits.PLAN_REST, f"{win or 'plan'} limit used up")
            soonest = min(soonest or (reset or time.time() + limits.PLAN_REST), reset or time.time() + limits.PLAN_REST)
            continue
        free.append((a, pct))
    if not free:
        return "wait", {}, "", soonest or time.time() + limits.RATE_REST
    under = [(a, pct) for a, pct in free if pct is None or pct < threshold]
    if under:
        best = min(under, key=lambda x: x[1] or 0.0)[0] if opts["order"] == "least" else under[0][0]
    else:  # all over the threshold: the least used carries on until it is refused
        best = min(free, key=lambda x: x[1] or 0.0)[0]
    if cur is not None and best["id"] == cur["id"]:
        return None
    if cur_rest:
        why = f"{cfg.account_label or 'It'} hit its limit ({cur_rest.get('why') or 'refused'}); it is free again at {_when(float(cur_rest.get('until') or 0))}."
    elif cur is None:
        why = f"{cfg.account_label or 'That account'} is switched off."
    else:
        why = f"{cfg.account_label} is at {round(cur_pct or 0)}% of its {cur_win or 'plan'} limit" + (f" (resets {_when(cur_reset)})." if cur_reset else ".")
    return "switch", best, why, 0.0


def on_refusal(provider: Any, ev: dict) -> bool:
    """A step was refused. True when it was this account's limit and another account can take
    over: the account rests and the caller runs the step again."""
    cfg = provider.config
    kind, until = limits.classify(ev)
    if kind != "used_up" or not cfg.account_id:
        return False
    _, accs = pool(cfg.id)
    if len(accs) < 2 or not any(a["id"] == cfg.account_id for a in accs):
        return False
    rest(cfg.id, cfg.account_id, until, limits.short_reason(ev) or "limit reached")
    log.info("%s account %s rests until %s", cfg.id, cfg.account_id, _when(until))
    return True


async def _wait(run: Any, until: float) -> None:
    from .runner import Interrupted

    while time.time() < until:
        if run is not None and run.abort.is_set():
            raise Interrupted()
        left = until - time.time()
        if run is None:
            await asyncio.sleep(min(left, 30))
            continue
        try:
            await asyncio.wait_for(run.abort.wait(), timeout=min(left, 30))
        except asyncio.TimeoutError:
            pass
    if run is not None and run.abort.is_set():
        raise Interrupted()


def _note(engine: "Engine", run: Any, label: str, meta: dict) -> None:
    """A line in the thread. It has no text, so it never reaches the model."""
    from .types import new_id, now_ms

    if run is None:
        log.info(label)
        return
    note = {"id": new_id("msg"), "type": "synthetic", "text": "", "time": {"created": now_ms()},
            "metadata": {"notice": "account", "label": label, **meta}}
    engine.store.add_message(run.sid, note)
    run.emit("session.notice", kind="account", label=label, message=note)
    engine.publish({"type": "provider.account.changed", "data": {"providerID": meta.get("provider"), "account": meta.get("to")}})


# ---- for Settings ----------------------------------------------------------------------------------


async def overview(engine: "Engine", pid: str, force: bool = False) -> list[dict]:
    """Every account of the provider with its usage and state."""
    p = provcfg.entry(pid) or {}
    view = {a["id"]: a for a in provcfg.public(p).get("accounts", [])}
    out = []

    async def one(a: dict) -> dict:
        cfg = provcfg.account_config(pid, a["id"])
        rep: dict = {}
        if cfg is not None and (cfg.api_key or cfg.auth):
            try:
                rep = await asyncio.wait_for(usage.report(cfg, None, force), 20)
            except Exception as err:
                rep = {"error": str(err) or err.__class__.__name__}
        r = resting(pid, a["id"])
        state = "off" if not view[a["id"]]["enabled"] else "resting" if r else "active" if view[a["id"]]["active"] else "ready"
        return view[a["id"]] | {"state": state, "restUntil": int(float(r["until"]) * 1000) if r else None, "restWhy": (r or {}).get("why", ""),
                                "windows": rep.get("windows") or [], "plan": rep.get("plan") or "", "balance": rep.get("balance"),
                                "usageError": rep.get("error") or ""}

    out = await asyncio.gather(*(one(a) for a in p.get("accounts") or []))
    return list(out)
