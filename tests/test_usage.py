"""Usage meter (engine/usage.py) and the Antigravity sign-in adapter, all offline."""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from afh.engine import auth, usage
from afh.engine.providers import catalog
from afh.engine.providers.antigravity import AntigravityProvider
from afh.engine.types import ChatMessage, ChatRequest, ProviderConfig, ToolCall, ToolSpec


def _sse(events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run(coro_fn, handler, cfg):
    async def go():
        async with _client(handler) as c:
            return await coro_fn(cfg, c)
    return asyncio.run(go())


def _ag_config(**auth_extra):
    return ProviderConfig(id="antigravity", name="Google Antigravity", kind="antigravity", base_url="https://cc.example.com",
                          auth={"type": "antigravity", "access": "tok", "refresh": "r", "expires": time.time() + 3600,
                                "account": "me@example.com", "project": "proj-1", **auth_extra})


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
    assert usage.live_source(_ag_config()) is usage._antigravity
    plain = ProviderConfig(id="x", name="x", kind="openai", base_url="https://api.example.com/v1", api_key="k")
    assert usage.live_source(plain) is None
    assert usage.live_source(ProviderConfig(id="ds", name="ds", kind="openai", base_url="https://api.deepseek.com", api_key="k")) is usage._deepseek
    assert usage.live_source(ProviderConfig(id="no-key", name="n", kind="openai", base_url="https://openrouter.ai/api/v1")) is None


def test_antigravity_quota_groups_by_family(monkeypatch):
    async def available(self):
        return {"models": {
            "claude-sonnet-4-6": {"quotaInfo": {"remainingFraction": 0.8, "resetTime": "2030-01-01T00:00:00Z"}},
            "claude-opus-4-6-thinking": {"quotaInfo": {"remainingFraction": 0.4, "resetTime": "2030-01-02T00:00:00Z"}},
            "gemini-3-flash": {"quotaInfo": {"remainingFraction": 1}},
            "gemini-3.1-pro-high": {"quotaInfo": {}},  # no fraction left = exhausted
            "gemini-3-pro-image": {"quotaInfo": {"remainingFraction": 0.1}},
        }}

    monkeypatch.setattr(AntigravityProvider, "available", available)
    out = asyncio.run(usage._antigravity(_ag_config(), None))
    got = {w["label"]: (w["usedPercent"], w["resetsAt"]) for w in out["windows"]}
    assert got == {"Claude": (60.0, 1_893_542_400_000), "Gemini Flash": (0.0, None), "Gemini Pro": (100.0, None)}


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


# ---- the Antigravity adapter -----------------------------------------------------------------------


def test_antigravity_catalog_entry_is_sign_in_only():
    e = catalog.entries()["antigravity"]
    assert e["login"] == "antigravity" and e["needs_key"] is False and e["kind"] == "antigravity"
    assert "antigravity" in auth.PROVIDERS and auth.signed_in(_ag_config())


def test_antigravity_wraps_claude_requests_and_unwraps_the_stream():
    seen = {}
    events = [
        {"response": {"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]}},
        {"response": {"candidates": [{"content": {"parts": [{"functionCall": {"id": "c1", "name": "read", "args": {"path": "a"}}}]},
                                      "finishReason": "STOP"}],
                      "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}},
    ]

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        seen["ua"], seen["body"] = request.headers.get("user-agent"), json.loads(request.content)
        return httpx.Response(200, content=_sse(events), headers={"content-type": "text/event-stream", "x-ratelimit-limit-requests": "10",
                                                                  "x-ratelimit-remaining-requests": "9"})

    p = AntigravityProvider(_ag_config(), transport=httpx.MockTransport(handler))
    req = ChatRequest(model="claude-opus-4-6-thinking", system="sys", reasoning=True, variant="high",
                      tools=[ToolSpec("read", "Read", {"type": "object", "properties": {"path": {"type": "string"}}}), ToolSpec("noop", "Nothing", {"type": "object"})],
                      messages=[ChatMessage("user", "go"), ChatMessage("assistant", "", tool_calls=[ToolCall("c0", "read", {"path": "b"})]),
                                ChatMessage("tool", "content", tool_call_id="c0")])

    async def collect():
        return [ev async for ev in p.stream(req)]

    out = asyncio.run(collect())
    assert seen["url"] == "https://cc.example.com/v1internal:streamGenerateContent?alt=sse"
    assert seen["auth"] == "Bearer tok" and seen["ua"].startswith("antigravity/")
    body = seen["body"]
    assert body["project"] == "proj-1" and body["model"] == "claude-opus-4-6-thinking" and body["requestId"].startswith("agent-")
    inner = body["request"]
    assert inner["toolConfig"] == {"functionCallingConfig": {"mode": "VALIDATED"}}
    decls = inner["tools"][0]["functionDeclarations"]
    assert all("parameters" in d for d in decls)
    think = inner["generationConfig"]["thinkingConfig"]
    assert think["include_thoughts"] is True and inner["generationConfig"]["maxOutputTokens"] >= think["thinking_budget"] + 8192
    parts = [p for c in inner["contents"] for p in c["parts"]]
    assert next(p for p in parts if "functionCall" in p)["functionCall"]["id"] == "c0"
    assert next(p for p in parts if "functionResponse" in p)["functionResponse"]["id"] == "c0"
    types = [e["type"] for e in out]
    assert "text.delta" in types and "tool.end" in types and types[-1] == "finish"
    assert next(e for e in out if e["type"] == "tool.end")["input"] == {"path": "a"}
    assert usage._headers["antigravity"][1]["x-ratelimit-remaining-requests"] == "9"
    usage._headers.pop("antigravity", None)


def test_antigravity_lists_only_visible_chat_models():
    def handler(request):
        assert request.url.path.endswith("fetchAvailableModels") and json.loads(request.content) == {"project": "proj-1"}
        return httpx.Response(200, json={
            "models": {
                "gemini-3-flash": {"displayName": "Gemini 3 Flash", "maxTokens": 1048576, "maxOutputTokens": 65536, "supportsThinking": True},
                "claude-opus-4-6-thinking": {"displayName": "Claude Opus 4.6 (Thinking)", "maxTokens": 200000, "supportsThinking": True},
                "gemini-3-pro-image": {"displayName": "Image"},
                "chat_20706": {"displayName": "internal"},
                "gemini-2.5-pro": {"displayName": "hidden", "disabled": True},
                "gpt-oss-120b-medium": {"displayName": "GPT-OSS"},
            },
            "agentModelSorts": [{"groups": [{"modelIds": ["gemini-3-flash", "claude-opus-4-6-thinking"]}]}],
        })

    p = AntigravityProvider(_ag_config(), transport=httpx.MockTransport(handler))
    models = {m.id: m for m in asyncio.run(p.list_models())}
    assert "gemini-3-flash" in models and "claude-opus-4-6-thinking" in models
    assert not {"gemini-3-pro-image", "chat_20706", "gemini-2.5-pro", "gpt-oss-120b-medium"} & set(models)
    assert models["claude-opus-4-6-thinking"].variants == ["low", "high", "max"]
    assert models["gemini-3-flash"].context == 1048576


def test_antigravity_project_from_load_or_onboarding(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(auth.asyncio, "sleep", no_sleep)

    def loaded(request):
        return httpx.Response(200, json={"cloudaicompanionProject": {"id": " p-1 "}})

    async def go(handler):
        async with _client(handler) as c:
            return await auth._antigravity_project(c, "tok")

    assert asyncio.run(go(loaded)) == "p-1"
    polls = []

    def onboard(request):
        if request.url.path.endswith("loadCodeAssist"):
            return httpx.Response(200, json={"allowedTiers": [{"id": "standard-tier"}, {"id": "free-tier", "isDefault": True}]})
        body = json.loads(request.content)
        assert body["tier_id"] == "free-tier"
        polls.append(1)
        if len(polls) < 2:
            return httpx.Response(200, json={"done": False})
        return httpx.Response(200, json={"done": True, "response": {"cloudaicompanionProject": {"id": "p-new"}}})

    assert asyncio.run(go(onboard)) == "p-new" and len(polls) == 2

    def refused(request):
        return httpx.Response(403, json={"error": {"message": "This account is not eligible"}})

    try:
        asyncio.run(go(refused))
    except RuntimeError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("expected a refusal")
