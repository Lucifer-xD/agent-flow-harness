"""Usage meter (engine/usage.py), all offline."""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from afh.engine import auth, usage
from afh.engine.types import ProviderConfig


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run(coro_fn, handler, cfg):
    async def go():
        async with _client(handler) as c:
            return await coro_fn(cfg, c)
    return asyncio.run(go())


# ---- parsing ----------------------------------------------------------------------------------------


def test_reset_times_parse_every_shape():
    now = time.time() * 1000
    assert usage._ms(1_800_000_000) == 1_800_000_000_000
    assert usage._ms("1800000000000") == 1_800_000_000_000
    assert abs(usage._ms(60) - (now + 60_000)) < 2000
    assert abs(usage._ms("6m0s") - (now + 360_000)) < 2000
    assert abs(usage._ms("1h2m3.5s") - (now + 3_723_500)) < 2000
    assert usage._ms("2030-01-01T00:00:00Z") == 1_893_456_000_000
    assert usage._ms(None) is None and usage._ms("soon") is None


def test_headers_give_codex_windows_and_rate_limits():
    usage.observe("p", {"X-Codex-Primary-Used-Percent": "42", "x-codex-primary-window-minutes": "300", "x-codex-primary-reset-after-seconds": "600",
                        "x-codex-secondary-used-percent": "7.5", "x-codex-secondary-window-minutes": "10080",
                        "x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "75", "x-ratelimit-reset-requests": "6m0s",
                        "anthropic-ratelimit-tokens-limit": "1000", "anthropic-ratelimit-tokens-remaining": "100",
                        "content-type": "text/event-stream"})
    when, kept = usage._headers["p"]
    assert "content-type" not in kept and "x-codex-primary-used-percent" in kept
    windows, rates = usage.from_headers(kept)
    assert [(w["id"], w["label"], w["usedPercent"]) for w in windows] == [("5h", "5-hour", 42.0), ("week", "Weekly", 7.5)]
    assert windows[0]["resetsAt"] > time.time() * 1000
    assert {(r["label"], r["usedPercent"]) for r in rates} == {("Requests", 25.0), ("Tokens", 90.0)}
    usage.observe("broken", None)  # never raises
    usage._headers.pop("p")


# ---- live readers -----------------------------------------------------------------------------------


def test_chatgpt_reads_the_five_hour_and_weekly_windows():
    cfg = ProviderConfig(id="chatgpt", name="ChatGPT", kind="responses", base_url="https://chatgpt.com/backend-api/codex",
                         auth={"type": "chatgpt", "access": "a", "expires": time.time() + 3600, "account_id": "acc", "plan": "plus"})
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, json={"plan_type": "pro", "rate_limit": {
            "primary_window": {"used_percent": 63, "limit_window_seconds": 18000, "reset_after_seconds": 1200},
            "secondary_window": {"used_percent": 21, "limit_window_seconds": 604800, "reset_at": 1_900_000_000}}})

    out = _run(usage._chatgpt, handler, cfg)
    assert seen == {"url": "https://chatgpt.com/backend-api/wham/usage", "auth": "Bearer a"}
    assert [(w["id"], w["usedPercent"]) for w in out["windows"]] == [("5h", 63.0), ("week", 21.0)]
    assert out["windows"][1]["resetsAt"] == 1_900_000_000_000 and out["plan"] == "pro" and "limited" not in out


def test_copilot_reads_premium_requests():
    cfg = ProviderConfig(id="copilot", name="Copilot", kind="openai", base_url="", auth={"type": "copilot", "github": "gho_x"})

    def handler(request):
        assert request.headers["authorization"] == "token gho_x"
        return httpx.Response(200, json={"copilot_plan": "individual", "quota_reset_date": "2026-12-01",
                                         "quota_snapshots": {"premium_interactions": {"entitlement": 300, "remaining": 225, "percent_remaining": 75},
                                                             "chat": {"unlimited": True}}})

    out = _run(usage._copilot, handler, cfg)
    (w,) = out["windows"]
    assert (w["id"], w["usedPercent"], w["used"], w["limit"]) == ("month", 25.0, 75.0, 300) and w["resetsAt"]


def test_kimi_and_zai_coding_plans():
    kimi = ProviderConfig(id="kimi", name="Kimi", kind="anthropic", base_url="https://api.kimi.com/coding/v1", api_key="k")

    def kimi_handler(request):
        assert str(request.url) == "https://api.kimi.com/coding/v1/usages"
        return httpx.Response(200, json={"limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                                                     "detail": {"limit": "100", "remaining": "40", "resetTime": "2030-01-01T00:00:00Z"}}],
                                         "usage": {"limit": "1000", "used": "100"}})

    out = _run(usage._kimi, kimi_handler, kimi)
    assert [(w["id"], w["usedPercent"]) for w in out["windows"]] == [("5h", 60.0), ("week", 10.0)]
    assert usage.live_source(kimi) is usage._kimi

    zai = ProviderConfig(id="zai-coding", name="Z.AI", kind="anthropic", base_url="https://api.z.ai/api/anthropic", api_key="z")

    def zai_handler(request):
        assert request.url.host == "api.z.ai"
        return httpx.Response(200, json={"data": {"level": "pro", "limits": [
            {"type": "TOKENS_LIMIT", "percentage": 12, "nextResetTime": 1_900_000_000_000},
            {"type": "TIME_LIMIT", "usage": 100, "currentValue": 5, "remaining": 95}]}})

    out = _run(usage._zai, zai_handler, zai)
    assert [(w["id"], w["usedPercent"]) for w in out["windows"]] == [("5h", 12.0), ("time_limit", 5.0)] and out["plan"] == "pro"
    assert usage.live_source(zai) is usage._zai


def test_kimi_named_windows_and_zai_without_a_plan():
    kimi = ProviderConfig(id="kimi", name="Kimi", kind="anthropic", base_url="https://api.kimi.com/coding/v1", api_key="k")

    def handler(request):
        return httpx.Response(200, json={"limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"}, "detail": {"limit": "100", "remaining": "100"}}],
                                         "usages": {"limit_5h": {"used_ratio": 0.25, "reset_time": "2030-01-01T00:00:00Z"},
                                                    "limit_month_total": {"used_ratio": 0.2064, "reset_time": "2030-01-27T00:00:00Z"},
                                                    "limit_month_code": {"used_ratio": 0.1894, "reset_time": "2030-01-27T00:00:00Z"}}})

    out = _run(usage._kimi, handler, kimi)
    assert [(w["id"], w["label"], w["usedPercent"]) for w in out["windows"]] == [
        ("5h", "5-hour", 25.0), ("month", "Monthly", 20.6), ("month-code", "Monthly (code)", 18.9)]

    zai = ProviderConfig(id="zai-coding", name="Z.AI", kind="openai", base_url="https://api.z.ai/api/coding/paas/v4", api_key="z")

    def no_plan(request):
        return httpx.Response(200, json={"code": 500, "msg": "当前用户不存在coding plan", "success": False})

    try:
        _run(usage._zai, no_plan, zai)
    except RuntimeError as exc:
        assert str(exc) == "this key has no active coding plan"
    else:
        raise AssertionError("expected an error")


def test_openrouter_spend_limit_and_balance():
    cfg = ProviderConfig(id="openrouter", name="OpenRouter", kind="openai", base_url="https://openrouter.ai/api/v1", api_key="sk-or")

    def handler(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage": 2.5, "limit": 10, "usage_daily": 0.5, "usage_weekly": 2, "is_free_tier": False}})
        return httpx.Response(200, json={"data": {"total_credits": 20, "total_usage": 7.25}})

    out = _run(usage._openrouter, handler, cfg)
    assert out["windows"][0]["usedPercent"] == 25.0 and out["spend"] == {"daily": 0.5, "weekly": 2}
    assert out["balance"] == {"amount": 12.75, "currency": "USD"}


def test_live_source_picks_by_sign_in_then_host():
    plain = ProviderConfig(id="x", name="x", kind="openai", base_url="https://api.example.com/v1", api_key="k")
    assert usage.live_source(plain) is None
    assert usage.live_source(ProviderConfig(id="ds", name="ds", kind="openai", base_url="https://api.deepseek.com", api_key="k")) is usage._deepseek
    assert usage.live_source(ProviderConfig(id="no-key", name="n", kind="openai", base_url="https://openrouter.ai/api/v1")) is None


# ---- local tracking and the report ------------------------------------------------------------------


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def usage_rows(self, since):
        return [r for r in self.rows if r["created"] >= since]


def _row(provider, hours_ago, tokens=10, cost=0.01):
    return {"created": int((time.time() - hours_ago * 3600) * 1000), "provider": provider, "model": "m",
            "input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "cost": cost}


def test_local_counts_five_hours_and_a_week():
    store = FakeStore([_row("a", 1), _row("a", 4.5, 5), _row("a", 30), _row("b", 1), _row("a", 24 * 9)])
    out = usage.local(store, "a")
    assert out["5h"]["steps"] == 2 and out["5h"]["tokens"] == 15
    assert out["week"]["steps"] == 3 and round(out["week"]["cost"], 2) == 0.03


def test_report_caches_live_answers_and_falls_back_to_headers(monkeypatch):
    calls = []

    async def reader(config, client):
        calls.append(1)
        return {"windows": [usage._window("5h", "5-hour", 30, None)], "plan": "pro"}

    cfg = ProviderConfig(id="live-p", name="Live", kind="openai", base_url="https://x", api_key="k")
    monkeypatch.setattr(usage, "live_source", lambda c: reader if c.id == "live-p" else None)
    usage._cache.pop("live-p", None)
    a = asyncio.run(usage.report(cfg))
    b = asyncio.run(usage.report(cfg))
    assert len(calls) == 1 and a["source"] == b["source"] == "live" and a["plan"] == "pro"
    asyncio.run(usage.report(cfg, force=True))
    assert len(calls) == 2

    async def broken(config, client):
        raise RuntimeError("401 from x")

    monkeypatch.setattr(usage, "live_source", lambda c: broken)
    usage._cache.pop("live-p", None)
    usage.observe("live-p", {"x-ratelimit-limit-tokens": "100", "x-ratelimit-remaining-tokens": "50"})
    out = asyncio.run(usage.report(cfg, store=FakeStore([_row("live-p", 1)])))
    assert out["error"] == "401 from x" and out["source"] == "local" and out["rates"][0]["usedPercent"] == 50.0
    assert out["local"]["5h"]["steps"] == 1
    usage._cache.pop("live-p", None)
    usage._headers.pop("live-p", None)


# ---- Gemini tool schemas -------------------------------------------------------------------------


def test_gemini_schemas_keep_only_what_google_accepts():
    from afh.engine.providers.gemini import clean_schema

    schema = {"type": "object", "additionalProperties": False, "$schema": "x", "properties": {
        "count": {"type": "integer", "exclusiveMinimum": 0, "description": "How many"},
        "mode": {"const": "fast"},
        "name": {"type": ["string", "null"], "minLength": 1, "format": "uri", "title": "Name"},
        "level": {"type": "integer", "enum": [1, 2, 3]},
        "tags": {"type": "array", "items": {"type": "string", "exclusiveMaximum": 9}, "uniqueItems": True},
    }, "required": ["count"]}
    out = clean_schema(schema)
    props = out["properties"]
    assert set(out) == {"type", "properties", "required"}
    assert props["count"] == {"type": "integer", "minimum": 0, "description": "How many"}
    assert props["mode"] == {"enum": ["fast"]}
    assert props["name"] == {"type": "string", "nullable": True, "minLength": 1}
    assert props["level"] == {"type": "integer", "description": "(one of: 1, 2, 3)"}
    assert props["tags"] == {"type": "array", "items": {"type": "string", "maximum": 9}}
    strict = clean_schema(schema, strict=True)["properties"]
    assert strict["name"] == {"type": "string", "nullable": True, "description": "(minLength: 1)"}
    assert strict["count"]["minimum"] == 0
