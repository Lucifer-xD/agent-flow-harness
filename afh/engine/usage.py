"""Plan limits and balances for each provider, for the usage meter by the message box.

Three sources, best first:

* **live**: the provider's own usage endpoint. Sign-ins: ChatGPT (``/wham/usage``: the 5-hour
  and weekly windows), Copilot (``copilot_internal/user``: monthly premium requests), Antigravity
  (``fetchAvailableModels``: quota left per model family). API keys: OpenRouter (credits and
  daily/weekly/monthly spend), Kimi coding plan (5-hour and monthly), Z.AI coding plan (5-hour
  and weekly/monthly), DeepSeek and Moonshot (balance).
* **headers**: rate-limit headers the provider sent on the last answer (``x-ratelimit-*``,
  ``anthropic-ratelimit-*``, ``x-codex-*``), recorded by the adapters through ``observe``.
* **local**: what AFH itself sent through this provider in the last 5 hours and 7 days.

Every report has the same shape (see ``Report``); a provider can have any mix of the three.
Live answers are cached for ``TTL`` seconds so an open meter does not hammer the endpoints.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any

import httpx

from . import auth
from .types import ProviderConfig

TTL = 60
FIVE_HOURS = 5 * 3600
WEEK = 7 * 86400

_cache: dict[str, tuple[float, dict]] = {}
_headers: dict[str, tuple[float, dict]] = {}  # provider id -> (when, rate-limit headers of the last answer)
_locks: dict[str, asyncio.Lock] = {}

_RATE_PREFIXES = ("x-ratelimit-", "anthropic-ratelimit-", "x-codex-", "ratelimit-")


# ---- recording headers -------------------------------------------------------------------------


def key(config: ProviderConfig) -> str:
    """Usage is kept per account: "provider#account" (just the provider when it has no accounts)."""
    return f"{config.id}#{config.account_id}" if config.account_id else config.id


def observe(provider_id: str, headers: Any) -> None:
    """Keep the rate-limit headers of a model answer (called by the adapters; cheap, never raises)."""
    try:
        kept = {k.lower(): v for k, v in headers.items() if k.lower().startswith(_RATE_PREFIXES)}
    except Exception:
        return
    if kept:
        _headers[provider_id] = (time.time(), kept)


def _ms(value: Any) -> int | None:
    """A reset time as epoch ms, from epoch seconds/ms, an ISO date, or seconds-from-now."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace(".", "", 1).isdigit()):
        n = float(value)
        if n > 1e12:
            return int(n)
        if n > 1e9:
            return int(n * 1000)
        return int((time.time() + n) * 1000)
    if isinstance(value, str):
        text = value.strip()
        try:  # "1s", "6m0s", "1h2m3.5s" (OpenAI reset durations)
            if text[-1] in "smh" and not text[0].isalpha():
                total, num = 0.0, ""
                for ch in text:
                    if ch.isdigit() or ch == ".":
                        num += ch
                    elif ch in "hms" and num:
                        total += float(num) * {"h": 3600, "m": 60, "s": 1}[ch]
                        num = ""
                    elif ch != "m":
                        raise ValueError
                return int((time.time() + total) * 1000)
        except (ValueError, IndexError):
            pass
        try:
            return int(dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _window(id: str, label: str, used_pct: float | None = None, resets: Any = None, **extra: Any) -> dict:
    w = {"id": id, "label": label, "usedPercent": None if used_pct is None else round(max(0.0, min(100.0, float(used_pct))), 1),
         "resetsAt": _ms(resets)}
    w.update({k: v for k, v in extra.items() if v is not None})
    return w


def _label_for_minutes(minutes: float | None, fallback: str) -> tuple[str, str]:
    if not minutes:
        return fallback.lower().replace(" ", "-"), fallback
    if minutes <= 6 * 60:
        return "5h", f"{round(minutes / 60)}-hour" if minutes % 60 == 0 else f"{int(minutes)}-minute"
    if minutes <= 2 * 1440:
        return "day", "Daily"
    if minutes <= 8 * 1440:
        return "week", "Weekly"
    return "month", "Monthly"


def from_headers(h: dict) -> tuple[list[dict], list[dict]]:
    """(plan windows, rate limits) from recorded headers."""
    windows: list[dict] = []
    for slot, name in (("primary", "Primary"), ("secondary", "Secondary")):
        pct = h.get(f"x-codex-{slot}-used-percent")
        if pct is None:
            continue
        minutes = float(h.get(f"x-codex-{slot}-window-minutes") or 0) or None
        wid, label = _label_for_minutes(minutes, name)
        windows.append(_window(wid, label, float(pct), h.get(f"x-codex-{slot}-reset-at") or h.get(f"x-codex-{slot}-reset-after-seconds")))
    rates: list[dict] = []
    for kind, label in (("requests", "Requests"), ("tokens", "Tokens"), ("input-tokens", "Input tokens"), ("output-tokens", "Output tokens")):
        for prefix, order in (("anthropic-ratelimit-", "kind-first"), ("x-ratelimit-", "field-first")):
            if order == "kind-first":
                lim, rem, reset = (h.get(f"{prefix}{kind}-limit"), h.get(f"{prefix}{kind}-remaining"), h.get(f"{prefix}{kind}-reset"))
            else:
                lim, rem, reset = (h.get(f"{prefix}limit-{kind}"), h.get(f"{prefix}remaining-{kind}"), h.get(f"{prefix}reset-{kind}"))
            if lim is None or rem is None:
                continue
            try:
                lim_n, rem_n = float(lim), float(rem)
            except ValueError:
                continue
            if lim_n <= 0:
                continue
            rates.append({"label": label, "limit": lim_n, "remaining": rem_n, "usedPercent": round(100 * (1 - rem_n / lim_n), 1), "resetsAt": _ms(reset)})
    return windows, rates


# ---- live endpoints ------------------------------------------------------------------------------


async def _get(client: httpx.AsyncClient, url: str, **kw: Any) -> dict:
    resp = await client.get(url, **kw)
    if resp.status_code >= 300:
        raise RuntimeError(f"{resp.status_code} from {httpx.URL(url).host}")
    return resp.json()


async def _chatgpt(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    base, h = await auth.prepare(config)
    origin = base.split("/backend-api")[0] if "/backend-api" in base else "https://chatgpt.com"
    data = await _get(client, f"{origin}/backend-api/wham/usage", headers=h)
    rl = data.get("rate_limit") or {}
    windows = []
    for slot, name in (("primary_window", "Primary"), ("secondary_window", "Secondary")):
        w = rl.get(slot)
        if not isinstance(w, dict):
            continue
        secs = w.get("limit_window_seconds")
        wid, label = _label_for_minutes((float(secs) / 60) if secs else None, name)
        windows.append(_window(wid, label, w.get("used_percent"), w.get("reset_at") or w.get("reset_after_seconds")))
    out: dict = {"windows": windows, "plan": data.get("plan_type") or config.auth.get("plan") or ""}
    if rl.get("limit_reached"):
        out["limited"] = True
    credits = data.get("credits")
    if isinstance(credits, dict) and credits.get("has_credits") and credits.get("balance") not in (None, ""):
        out["balance"] = {"amount": float(credits["balance"]), "currency": "credits"}
    return out


async def _copilot(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    gh = (config.auth or {}).get("github", "")
    data = await _get(client, "https://api.github.com/copilot_internal/user",
                      headers={"authorization": f"token {gh}", "accept": "application/json", **auth.COPILOT_HEADERS})
    windows = []
    snaps = data.get("quota_snapshots") or {}
    for key, label in (("premium_interactions", "Premium requests"), ("chat", "Chat"), ("completions", "Completions")):
        q = snaps.get(key)
        if not isinstance(q, dict) or q.get("unlimited"):
            continue
        pct_left = q.get("percent_remaining")
        if pct_left is None and q.get("entitlement"):
            pct_left = 100 * float(q.get("remaining") or 0) / float(q["entitlement"])
        ent = q.get("entitlement")
        used = (float(ent) - float(q.get("remaining") or 0)) if ent is not None else None
        windows.append(_window("month" if key == "premium_interactions" else key, label, None if pct_left is None else 100 - float(pct_left),
                               data.get("quota_reset_date"), used=used, limit=ent, unit="requests"))
    return {"windows": windows, "plan": data.get("copilot_plan") or ""}


_FAMILIES = (("claude", "Claude"), ("flash", "Gemini Flash"), ("gemini", "Gemini Pro"), ("gpt-oss", "GPT-OSS"))


async def _antigravity(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    from .providers.antigravity import AntigravityProvider

    data = await AntigravityProvider(config).available()
    groups: dict[str, dict] = {}
    for mid, m in (data.get("models") or {}).items():
        q = (m or {}).get("quotaInfo") if isinstance(m, dict) else None
        if not isinstance(q, dict) or m.get("disabled") or any(x in mid for x in ("image", "imagen", "chat_", "tab_")):
            continue
        family = next((label for key, label in _FAMILIES if key in mid.lower()), None)
        if not family:
            continue
        left = q.get("remainingFraction")
        left = 0.0 if not isinstance(left, (int, float)) else max(0.0, min(1.0, float(left)))
        g = groups.setdefault(family, {"left": 1.0, "reset": None})
        if left <= g["left"]:
            g["left"], g["reset"] = left, q.get("resetTime") or g["reset"]
    windows = [_window(label.lower().replace(" ", "-"), label, 100 * (1 - g["left"]), g["reset"]) for label, g in groups.items()]
    return {"windows": windows}


async def _openrouter(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    data = (await _get(client, "https://openrouter.ai/api/v1/key", headers={"authorization": f"Bearer {config.api_key}"})).get("data") or {}
    out: dict = {"windows": [], "spend": {k: data.get(f"usage_{k}") for k in ("daily", "weekly", "monthly") if data.get(f"usage_{k}") is not None}}
    if data.get("limit"):
        used = float(data.get("usage") or 0)
        out["windows"].append(_window("credits", "Key limit", 100 * used / float(data["limit"]), data.get("limit_reset"), used=used,
                                      limit=float(data["limit"]), unit="USD"))
    try:
        credits = (await _get(client, "https://openrouter.ai/api/v1/credits", headers={"authorization": f"Bearer {config.api_key}"})).get("data") or {}
        if credits.get("total_credits") is not None:
            out["balance"] = {"amount": float(credits["total_credits"]) - float(credits.get("total_usage") or 0), "currency": "USD"}
    except Exception:
        pass
    if data.get("is_free_tier"):
        out["plan"] = "Free tier"
    return out


async def _kimi(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    data = await _get(client, config.base_url.rstrip("/") + "/usages", headers={"authorization": f"Bearer {config.api_key}"})
    windows = []
    named = data.get("usages")  # {"limit_5h": {"used_ratio", "reset_time"}, "limit_month_total": ..., ...}
    if isinstance(named, dict) and named:
        for key, w in named.items():
            if not isinstance(w, dict) or _num(w.get("used_ratio")) is None:
                continue
            span = key.removeprefix("limit_")
            wid, label = next(((i, l) for p, i, l in _KIMI_SPANS if span.startswith(p)), (span, span.replace("_", " ").capitalize()))
            if span.endswith("_code"):
                wid, label = f"{wid}-code", f"{label} (code)"
            windows.append(_window(wid, label, 100 * _num(w["used_ratio"]), w.get("reset_time")))
        return {"windows": windows}
    for item in data.get("limits") or []:
        win = item.get("window") or {}
        unit = str(win.get("timeUnit") or "").upper()
        minutes = float(win.get("duration") or 0) * {"TIME_UNIT_MINUTE": 1, "TIME_UNIT_HOUR": 60, "TIME_UNIT_DAY": 1440}.get(unit, 1)
        d = item.get("detail") or item
        wid, label = _label_for_minutes(minutes or None, "Window")
        windows.append(_pct_window(wid, label, d))
    week = data.get("usage")
    if isinstance(week, dict):
        windows.append(_pct_window("week", "Weekly", week))
    return {"windows": windows}


_KIMI_SPANS = (("5h", "5h", "5-hour"), ("day", "day", "Daily"), ("week", "week", "Weekly"), ("month", "month", "Monthly"))


def _pct_window(wid: str, label: str, d: dict) -> dict:
    lim = _num(d.get("limit"))
    used = _num(d.get("used"))
    if used is None and lim is not None and _num(d.get("remaining")) is not None:
        used = lim - _num(d.get("remaining"))
    pct = _num(d.get("percentage"))
    if pct is None and lim:
        pct = 100 * (used or 0) / lim
    return _window(wid, label, pct, d.get("resetTime") or d.get("nextResetTime") or d.get("reset_at"), used=used, limit=lim)


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


_ZAI_ERRORS = {"当前用户不存在coding plan": "this key has no active coding plan"}


async def _zai(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    origin = "https://open.bigmodel.cn" if "bigmodel.cn" in config.base_url else "https://api.z.ai"
    data = await _get(client, f"{origin}/api/monitor/usage/quota/limit", headers={"authorization": f"Bearer {config.api_key}"})
    if data.get("success") is False:  # HTTP 200 with {"code": 500, "msg": "...no coding plan"} for keys without a plan
        raise RuntimeError(_ZAI_ERRORS.get(str(data.get("msg") or ""), data.get("msg") or f"Z.AI error {data.get('code')}"))
    windows = []
    for item in (data.get("data") or {}).get("limits") or []:
        kind = str(item.get("type") or "")
        label = {"TOKENS_LIMIT": "5-hour", "TIME_LIMIT": "Monthly tools"}.get(kind, kind.replace("_", " ").title())
        windows.append(_pct_window("5h" if kind == "TOKENS_LIMIT" else kind.lower(), label,
                                   {"limit": item.get("usage"), "used": item.get("currentValue"), "remaining": item.get("remaining"),
                                    "percentage": item.get("percentage"), "nextResetTime": item.get("nextResetTime")}))
    return {"windows": windows, "plan": (data.get("data") or {}).get("level") or ""}


async def _deepseek(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    data = await _get(client, "https://api.deepseek.com/user/balance", headers={"authorization": f"Bearer {config.api_key}"})
    info = (data.get("balance_infos") or [{}])[0]
    return {"windows": [], "balance": {"amount": float(info.get("total_balance") or 0), "currency": info.get("currency") or "USD"}}


async def _moonshot(config: ProviderConfig, client: httpx.AsyncClient) -> dict:
    data = await _get(client, config.base_url.rstrip("/") + "/users/me/balance", headers={"authorization": f"Bearer {config.api_key}"})
    d = data.get("data") or {}
    return {"windows": [], "balance": {"amount": float(d.get("available_balance") or 0), "currency": "CNY" if ".cn" in config.base_url else "USD"}}


def live_source(config: ProviderConfig):
    """The live usage reader for this provider, or None."""
    kind = (config.auth or {}).get("type")
    if kind == "chatgpt":
        return _chatgpt
    if kind == "copilot":
        return _copilot
    if kind == "antigravity":
        return _antigravity
    if not config.api_key:
        return None
    cat = config.id
    host = config.base_url
    if "openrouter.ai" in host:
        return _openrouter
    if cat == "kimi" or ("/coding/v1" in host and "kimi" in host):
        return _kimi
    if cat == "zai-coding" or "/api/coding/paas" in host:
        return _zai
    if "api.deepseek.com" in host:
        return _deepseek
    if "api.moonshot." in host:
        return _moonshot
    return None


# ---- local tracking ------------------------------------------------------------------------------


def local(store: Any, provider_id: str) -> dict:
    """What AFH sent through the provider: steps, tokens and cost in the last 5 hours and 7 days."""
    now = time.time() * 1000
    out = {"5h": {"steps": 0, "tokens": 0, "cost": 0.0}, "week": {"steps": 0, "tokens": 0, "cost": 0.0}}
    try:
        rows = store.usage_rows(int(now - WEEK * 1000))
    except Exception:
        return out
    for r in rows:
        if r["provider"] != provider_id:
            continue
        tokens = (r["input"] or 0) + (r["output"] or 0) + (r["cache_read"] or 0) + (r["cache_write"] or 0)
        for key, span in (("5h", FIVE_HOURS), ("week", WEEK)):
            if r["created"] >= now - span * 1000:
                b = out[key]
                b["steps"] += 1
                b["tokens"] += tokens
                b["cost"] += r["cost"] or 0.0
    return out


# ---- the report --------------------------------------------------------------------------------


async def report(config: ProviderConfig, store: Any = None, force: bool = False) -> dict:
    """Everything known about a provider's limits right now (live answer cached for TTL seconds)."""
    k = key(config)
    out: dict = {"providerID": config.id, "name": config.name, "account": (config.auth or {}).get("account", "") or config.account_label,
                 "accountID": config.account_id,
                 "signedIn": auth.signed_in(config), "windows": [], "rates": [], "source": "local", "updated": int(time.time() * 1000)}
    reader = live_source(config)
    if reader:
        lock = _locks.setdefault(k, asyncio.Lock())
        async with lock:
            hit = _cache.get(k)
            if hit and not force and time.time() - hit[0] < TTL:
                live = hit[1]
            else:
                try:
                    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                        live = await reader(config, client)
                except Exception as exc:
                    live = {"error": str(exc) or exc.__class__.__name__}
                _cache[k] = (time.time(), live)
        out.update({k: v for k, v in live.items() if v not in (None, "", [], {})})
        if live.get("windows") or live.get("balance"):
            out["source"] = "live"
    seen = _headers.get(k)
    if seen:
        windows, rates = from_headers(seen[1])
        if windows and not out["windows"]:
            out["windows"], out["source"] = windows, "headers"
        if rates:
            out["rates"] = rates
            out["ratesAt"] = int(seen[0] * 1000)
    if store is not None:
        out["local"] = local(store, config.id)
    return out
