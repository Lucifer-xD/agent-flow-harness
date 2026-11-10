"""What a provider's refusal means, for switching accounts (engine/accounts.py).

  used_up     this account hit a plan, quota, credit or rate limit: another account can carry on
  overloaded  the provider's servers are busy: every account would get the same answer, so AFH
              keeps the account and retries after a pause, as before
  other       anything else (a bad request, an expired sign-in, a model the plan lacks)

``classify`` also says until when the account should rest, from the retry headers or the reset
time the provider wrote in the error, else a default for the kind of limit.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

# Busy servers, not this account's limit (Gemini, Claude 529, Kimi, Z.ai 1305, Codex, OpenAI).
_OVERLOAD = ("overloaded", "capacity", "server_is_overloaded", "engine_overloaded", "temporarily unavailable",
             "high demand", "try again later", "service unavailable", "\"code\":\"1305\"", "\"code\": \"1305\"", "\"code\":1305", "\"code\": 1305")

# This account's limit.
_PLAN = ("usage_limit_reached", "usage limit", "quota", "insufficient_quota", "exceeded_current_quota", "credits", "insufficient balance",
         "limit reached", "limit has been reached", "reached your", "resource_exhausted", "exhausted",
         "\"code\":\"1308\"", "\"code\": \"1308\"", "\"code\":1308", "\"code\": 1308", "\"code\":\"1310\"", "\"code\":1310", "\"code\": 1310",
         "plan limit", "weekly limit", "5-hour", "daily limit", "monthly limit")
_RATE = ("rate limit", "rate_limit", "ratelimit", "too many requests", "requests per", "tokens per", "rpm", "tpm")

PLAN_REST = 3600  # a used-up plan with no reset time given: check again in an hour
RATE_REST = 60  # a per-minute rate limit with no reset time given


def classify(ev: dict) -> tuple[str, float]:
    """(kind, rest until as epoch seconds) for a provider error event."""
    status = ev.get("status")
    text = f"{ev.get('message', '')} {ev.get('response', '')}".lower()
    if ev.get("kind") == "network":
        return "other", 0.0
    if status in (529, 503) or (any(w in text for w in _OVERLOAD) and not _plan_words(text)):
        return "overloaded", 0.0
    plan = _plan_words(text)
    rate = any(w in text for w in _RATE)
    if status in (429, 402) or (status in (400, 403) and plan) or (status is None and (plan or rate)):
        if status == 400 and not plan:
            return "other", 0.0
        until = reset_time(ev)
        if not until:
            until = time.time() + (RATE_REST if rate and not plan else PLAN_REST)
        return "used_up", until
    return "other", 0.0


def _plan_words(text: str) -> bool:
    # "capacity exhausted" is Google's overload, not a quota
    if "capacity" in text and "quota" not in text:
        return False
    return any(w in text for w in _PLAN)


_SECONDS = re.compile(r"(?:resets?_in_seconds|reset_after_seconds|retry_after(?:_seconds)?)\D{0,4}(\d+(?:\.\d+)?)", re.I)
_EPOCH = re.compile(r"(?:resets?_at|reset_time|resettime|nextresettime)\D{0,4}(\d{10,13})", re.I)
_ISO = re.compile(r"(?:resets?_at|reset_time|resettime|nextresettime|resets at)\W{0,5}(\d{4}-\d\d-\d\dt\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:z|[+-]\d\d:?\d\d)?)", re.I)
_DELAY = re.compile(r"retrydelay\W{0,5}(\d+(?:\.\d+)?)s", re.I)
_TRY_IN = re.compile(r"try again in\s+(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?\s*(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?)?", re.I)


def reset_time(ev: dict) -> float:
    """When the provider says the limit lifts (epoch seconds), or 0."""
    now = time.time()
    h = {str(k).lower(): v for k, v in (ev.get("headers") or {}).items()}
    for name in ("x-codex-primary-reset-at", "x-codex-secondary-reset-at"):
        v = _num(h.get(name))
        if v and v > now:
            return v / 1000 if v > 1e12 else v
    v = _num(h.get("retry-after"))
    if v:
        return now + v
    body = f"{ev.get('response', '')} {ev.get('message', '')}"
    if m := _SECONDS.search(body):
        return now + float(m.group(1))
    if m := _EPOCH.search(body):
        n = float(m.group(1))
        return n / 1000 if n > 1e12 else n
    if m := _ISO.search(body):
        import datetime as dt

        try:
            text = m.group(1).upper().replace("Z", "+00:00")
            stamp = dt.datetime.fromisoformat(text)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=dt.timezone.utc)
            return stamp.timestamp()
        except ValueError:
            pass
    if m := _DELAY.search(body.replace('"', "").replace(" ", "")):
        return now + float(m.group(1))
    if (m := _TRY_IN.search(body)) and any(m.groups()):
        hrs, mins, secs = (float(x) if x else 0.0 for x in m.groups())
        return now + hrs * 3600 + mins * 60 + secs
    for name in ("anthropic-ratelimit-tokens-reset", "anthropic-ratelimit-requests-reset", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        if h.get(name):
            from .usage import _ms

            ms = _ms(h[name])
            if ms:
                return ms / 1000
    return 0.0


def _num(v: Any) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def short_reason(ev: dict) -> str:
    """A few words on why, for the note in the chat."""
    msg = str(ev.get("message") or "")
    try:
        data = json.loads(ev.get("response") or "{}")
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and err.get("message"):
            msg = str(err["message"])
    except ValueError:
        pass
    msg = " ".join(msg.split())
    return (msg[:117] + "…") if len(msg) > 120 else msg
