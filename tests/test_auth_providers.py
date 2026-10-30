"""Provider catalog from models.dev, sign-in plumbing and the Responses API adapter."""

from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx

from afh.engine import auth
from afh.engine.providers import catalog
from afh.engine.providers.openai_responses import OpenAIResponsesProvider
from afh.engine.types import ChatMessage, ChatRequest, ProviderConfig, ToolCall, ToolSpec


def test_catalog_covers_models_dev():
    e = catalog.entries()
    assert len(e) > 150
    assert e["openai"]["source"] == "afh" and e["chatgpt"]["login"] == "chatgpt"
    assert "google" not in e and "togetherai" not in e  # aliases of KNOWN entries
    assert e["minimax"]["kind"] == "anthropic"
    az = e["azure"]
    assert [p["name"] for p in az["params"]] == ["AZURE_RESOURCE_NAME"] and az["extra"]["auth_header"] == "api-key"
    assert catalog.param_label("CLOUDFLARE_ACCOUNT_ID", "cloudflare-workers-ai") == "Account ID"
    assert "qvac" not in e and "watsonx" not in e


def test_render_url_and_env_key(monkeypatch):
    tpl = catalog.entries()["azure"]["base_url"]
    assert catalog.render_url(tpl, {"AZURE_RESOURCE_NAME": "acme"}) == "https://acme.openai.azure.com/openai/v1"
    monkeypatch.setenv("AZURE_RESOURCE_NAME", "fromenv")
    assert catalog.render_url(tpl, {}) == "https://fromenv.openai.azure.com/openai/v1"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert catalog.env_key("groq") == "gsk_test"


def test_azure_auth_header():
    from afh.engine.providers.openai_compat import OpenAICompatProvider

    cfg = catalog.config_from_catalog("azure", api_key="k", params={"AZURE_RESOURCE_NAME": "acme"})
    h = OpenAICompatProvider(cfg).headers()
    assert h["api-key"] == "k" and "authorization" not in h


def _jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def test_chatgpt_tokens_and_pkce():
    verifier, challenge = auth.pkce()
    assert len(verifier) >= 43 and "=" not in challenge
    tok = _jwt({"email": "a@b.c", "https://api.openai.com/auth": {"chatgpt_account_id": "acc_1", "chatgpt_plan_type": "plus"}})
    a = auth._chatgpt_auth({"id_token": tok, "access_token": "at", "refresh_token": "rt", "expires_in": 100}, {})
    assert a["account_id"] == "acc_1" and a["account"] == "a@b.c" and a["plan"] == "plus" and a["expires"] > time.time()


def test_prepare_refreshes_and_builds_headers(monkeypatch):
    saved = {}
    monkeypatch.setattr(auth.provcfg, "upsert", lambda pid, patch: saved.update({pid: patch}))

    async def fake_refresh(cfg):
        return cfg.auth | {"access": "new", "expires": time.time() + 3600}

    monkeypatch.setattr(auth, "_refresh", fake_refresh)
    cfg = ProviderConfig(id="github-copilot", name="Copilot", kind="openai", base_url="https://api.githubcopilot.com",
                         auth={"type": "copilot", "github": "gh", "access": "old", "expires": time.time() - 5, "api": "https://api.business.githubcopilot.com"})
    req = ChatRequest(model="m", system="", messages=[ChatMessage("user", "hi")])
    base, h = asyncio.run(auth.prepare(cfg, req))
    assert base == "https://api.business.githubcopilot.com" and h["authorization"] == "Bearer new" and h["X-Initiator"] == "user"
    assert saved["github-copilot"]["auth"]["access"] == "new"
    plain = ProviderConfig(id="x", name="x", kind="openai", base_url="https://x/v1")
    assert asyncio.run(auth.prepare(plain)) == ("https://x/v1", {})


def test_callback_server_receives_code():
    async def go():
        async with auth._Callback("/callback") as cb:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"http://127.0.0.1:{cb.port}/callback?code=abc&state=s")
            assert r.status_code == 200 and "Signed in" in r.text
            return await cb.result

    assert asyncio.run(go()) == {"code": "abc", "state": "s"}


def _sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def test_responses_adapter_streams_text_reasoning_and_tools():
    seen = {}
    events = [
        {"type": "response.reasoning_summary_part.added"},
        {"type": "response.reasoning_summary_text.delta", "delta": "think"},
        {"type": "response.output_text.delta", "delta": "Hi"},
        {"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "delta": '{"path":'},
        {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "delta": '"a.txt"}'},
        {"type": "response.output_item.done", "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read", "arguments": '{"path":"a.txt"}'}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 4}}}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(events), headers={"content-type": "text/event-stream"})

    cfg = ProviderConfig(id="r", name="r", kind="responses", base_url="https://api.example.com/v1", api_key="k")
    p = OpenAIResponsesProvider(cfg, transport=httpx.MockTransport(handler))
    req = ChatRequest(model="gpt-x", system="sys", variant="high", tools=[ToolSpec("read", "Read", {"type": "object"})], messages=[
        ChatMessage("user", "go"), ChatMessage("assistant", "ok", tool_calls=[ToolCall("call_0", "read", {"path": "b"})]),
        ChatMessage("tool", "content", tool_call_id="call_0")])

    async def collect():
        return [ev async for ev in p.stream(req)]

    out = asyncio.run(collect())
    assert seen["url"] == "https://api.example.com/v1/responses"
    body = seen["body"]
    assert body["instructions"] == "sys" and body["store"] is False and body["reasoning"]["effort"] == "high"
    assert [i.get("type", i.get("role")) for i in body["input"]] == ["user", "message", "function_call", "function_call_output"]
    types = [e["type"] for e in out]
    assert types == ["reasoning.delta", "text.delta", "tool.start", "tool.delta", "tool.delta", "tool.end", "usage", "finish"]
    end = next(e for e in out if e["type"] == "tool.end")
    assert end["input"] == {"path": "a.txt"} and end["id"] == "call_1"
    usage = next(e for e in out if e["type"] == "usage")
    assert usage["input"] == 6 and usage["cache_read"] == 4
    assert out[-1]["reason"] == "tool_calls"


def test_chatgpt_body_skips_unsupported_fields():
    cfg = ProviderConfig(id="chatgpt", name="c", kind="responses", base_url=auth.CHATGPT_BASE, auth={"type": "chatgpt"})
    body = OpenAIResponsesProvider(cfg).build_body(ChatRequest(model="m", system="s", messages=[ChatMessage("user", "x")], max_tokens=100, temperature=0.2))
    assert "max_output_tokens" not in body and "temperature" not in body


def test_401_refreshes_the_token_and_retries(monkeypatch):
    from afh.engine.providers.openai_compat import OpenAICompatProvider

    monkeypatch.setattr(auth.provcfg, "upsert", lambda pid, patch: None)
    tokens = iter(["second"])

    async def fake_refresh(cfg):
        return cfg.auth | {"access": next(tokens), "expires": time.time() + 3600}

    monkeypatch.setattr(auth, "_refresh", fake_refresh)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer first":
            return httpx.Response(401, json={"error": {"message": "token expired"}})
        chunk = {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
        return httpx.Response(200, content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode(), headers={"content-type": "text/event-stream"})

    cfg = ProviderConfig(id="github-copilot", name="Copilot", kind="openai", base_url="https://api.githubcopilot.com",
                         auth={"type": "copilot", "github": "gh", "access": "first", "expires": time.time() + 3600, "api": "https://api.githubcopilot.com"})
    p = OpenAICompatProvider(cfg, transport=httpx.MockTransport(handler))

    async def collect():
        return [ev async for ev in p.stream(ChatRequest(model="gpt-x", system="", messages=[ChatMessage("user", "hi")]))]

    out = asyncio.run(collect())
    assert seen == ["Bearer first", "Bearer second"]
    assert [e["type"] for e in out] == ["text.delta", "finish"]


def test_chatgpt_model_list_uses_current_client_version():
    from afh.engine.providers.openai_responses import CODEX_CLIENT_VERSION, chatgpt_model

    seen = {}
    models = [
        {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "visibility": "list", "supported_in_api": True, "context_window": 500000,
         "input_modalities": ["text", "image"], "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}, {"effort": "ultra"}]},
        {"slug": "codex-auto-review", "visibility": "hide", "supported_in_api": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"models": models})

    cfg = ProviderConfig(id="chatgpt", name="c", kind="responses", base_url=auth.CHATGPT_BASE,
                         auth={"type": "chatgpt", "access": "t", "account_id": "a", "expires": time.time() + 3600})
    out = asyncio.run(OpenAIResponsesProvider(cfg, transport=httpx.MockTransport(handler)).list_models())
    assert seen["params"]["client_version"] == CODEX_CLIENT_VERSION
    assert [m.id for m in out] == ["gpt-6.1-sol"]
    m = out[0]
    assert m.name == "GPT-6.1-Sol" and m.context == 500000 and m.variants == ["low", "high"] and "image" in m.input
    assert chatgpt_model({"slug": "x", "visibility": "hide"}) is None
