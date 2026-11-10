"""The sign-ins added in 1.23: xAI (Grok), MiniMax Token Plan, Poe, DigitalOcean and ChatGPT with a code."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from afh.engine import auth
from afh.engine.providers import catalog
from afh.engine.providers.anthropic import AnthropicProvider
from afh.engine.types import ChatMessage, ChatRequest, ProviderConfig

REAL_CLIENT = httpx.AsyncClient


def _jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"e30.{body}.sig"


def _form(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


@pytest.fixture
def net(monkeypatch):
    """Sends the engine's outgoing requests to ``routes`` ("METHOD url" → handler); records calls and saved providers."""
    routes: dict = {}
    calls: list[httpx.Request] = []
    saved: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        key = f"{request.method} {request.url.copy_with(query=None)}"
        if key not in routes:
            return httpx.Response(404, json={"error": "unexpected", "detail": key})
        return routes[key](request)

    mock = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: REAL_CLIENT(*a, **{**kw, "transport": mock}))
    fast = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda delay, *a: fast(0))
    monkeypatch.setattr(auth.provcfg, "upsert", lambda pid, patch: saved.update({pid: patch}))
    monkeypatch.setattr(auth.provcfg, "add_account", lambda pid, creds, base=None, label="", activate=False: saved.update({pid: (base or {}) | creds}))
    monkeypatch.setattr(auth.provcfg, "save_creds", lambda pid, aid, patch: saved.update({pid: patch}))
    return routes, calls, saved


def _finish(method: str, during=None) -> auth.Login:
    async def go():
        login = await auth.start(method)
        if during:
            await during(login)
        await login.task
        return login

    login = asyncio.run(go())
    assert login.status == "done", login.error
    return login


def test_catalog_offers_the_new_sign_ins():
    e = catalog.entries()
    assert e["xai"]["login"] == "xai" and "Grok" in e["xai"]["name"]
    for pid, method in {"poe": "poe", "digitalocean": "digitalocean", "minimax-coding-plan": "minimax", "minimax-cn-coding-plan": "minimax-cn"}.items():
        assert e[pid]["login"] == method, pid
        assert auth.PROVIDERS[method]["catalog"] == pid
    assert "login" not in e["minimax"]  # the pay-as-you-go MiniMax API stays key-only


def test_xai_device_sign_in(net):
    routes, calls, saved = net
    routes["POST https://auth.x.ai/oauth2/device/code"] = lambda r: httpx.Response(200, json={
        "device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://accounts.x.ai/device",
        "verification_uri_complete": "https://accounts.x.ai/device?user_code=ABCD-1234", "expires_in": 600, "interval": 5})
    polls = iter([httpx.Response(400, json={"error": "authorization_pending"}), httpx.Response(400, json={"error": "slow_down"}),
                  httpx.Response(200, json={"access_token": "xa", "refresh_token": "xr", "expires_in": 3600, "id_token": _jwt({"email": "me@x.test"})})])
    routes["POST https://auth.x.ai/oauth2/token"] = lambda r: next(polls)

    login = _finish("xai")
    assert login.user_code == "ABCD-1234" and login.url.endswith("user_code=ABCD-1234")
    assert login.account == "me@x.test" and login.provider_id == "xai"
    start = _form(calls[0])
    assert start["client_id"] == auth.XAI_CLIENT_ID and "grok-cli:access" in start["scope"] and "offline_access" in start["scope"]
    assert start["referrer"] == "agent-flow-harness"
    poll = _form(calls[1])
    assert poll["grant_type"] == auth.DEVICE_GRANT and poll["device_code"] == "dc"
    a = saved["xai"]["auth"]
    assert a["type"] == "xai" and a["access"] == "xa" and a["refresh"] == "xr" and a["expires"] > time.time() + 3000
    assert saved["xai"]["base_url"] == "https://api.x.ai/v1" and saved["xai"]["kind"] == "openai"


def test_xai_declined(net):
    routes, _, _ = net
    routes["POST https://auth.x.ai/oauth2/device/code"] = lambda r: httpx.Response(200, json={"device_code": "dc", "user_code": "C", "verification_uri": "https://accounts.x.ai/device"})
    routes["POST https://auth.x.ai/oauth2/token"] = lambda r: httpx.Response(400, json={"error": "access_denied"})

    async def go():
        login = await auth.start("xai")
        await login.task
        return login

    login = asyncio.run(go())
    assert login.status == "error" and "declined" in login.error


def test_xai_refresh_and_headers(net):
    routes, calls, saved = net
    routes["POST https://auth.x.ai/oauth2/token"] = lambda r: httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    cfg = ProviderConfig(id="xai", name="xAI", kind="openai", base_url="https://api.x.ai/v1", api_key="old-key",
                         auth={"type": "xai", "access": "old", "refresh": "xr", "expires": time.time() - 1, "account": "me@x.test"})
    base, h = asyncio.run(auth.prepare(cfg))
    assert base == "https://cli-chat-proxy.grok.com/v1"  # the plan pays only on Grok's coding endpoint
    assert h["authorization"] == "Bearer new" and h["x-grok-client-version"] == auth.GROK_CLI_VERSION and h["x-grok-req-id"]
    assert _form(calls[0])["grant_type"] == "refresh_token"
    kept = saved["xai"]["auth"]
    assert kept["refresh"] == "xr" and kept["account"] == "me@x.test"  # a refresh answer without a new refresh token keeps the old one


def test_minimax_device_sign_in(net):
    routes, calls, saved = net

    def device(r):
        f = _form(r)
        assert f["code_challenge_method"] == "S256" and f["client_id"] == auth.MINIMAX_CLIENT_ID and f["scope"] == auth.MINIMAX_SCOPE
        return httpx.Response(200, json={"user_code": "MM-1", "verification_uri": "https://www.minimax.io/oauth/device?user_code=MM-1",
                                         "expired_in": int(time.time() * 1000) + 600_000, "interval": 2000, "state": f["state"]})

    routes["POST https://account.minimax.io/oauth2/device/code"] = device
    polls = iter([{"status": "pending"}, {"status": "success", "access_token": "ma", "refresh_token": "mr", "expired_in": 7200}])
    routes["POST https://account.minimax.io/oauth2/token"] = lambda r: httpx.Response(200, json=next(polls))

    login = _finish("minimax")
    assert login.user_code == "MM-1" and login.provider_id == "minimax-coding-plan"
    poll = _form(calls[-1])
    assert poll["grant_type"] == "urn:ietf:params:oauth:grant-type:user_code" and poll["user_code"] == "MM-1" and len(poll["code_verifier"]) >= 43
    a = saved["minimax-coding-plan"]["auth"]
    assert a["type"] == "minimax" and a["access"] == "ma" and a["token_url"] == "https://account.minimax.io/oauth2/token"
    assert time.time() + 7000 < a["expires"] < time.time() + 7300
    assert saved["minimax-coding-plan"]["kind"] == "anthropic"


def test_minimax_rejects_a_mismatched_answer(net):
    routes, _, saved = net
    routes["POST https://account.minimaxi.com/oauth2/device/code"] = lambda r: httpx.Response(200, json={"user_code": "X", "verification_uri": "https://x", "state": "other"})

    async def go():
        login = await auth.start("minimax-cn")
        await login.task
        return login

    login = asyncio.run(go())
    assert login.status == "error" and "did not match" in login.error and not saved


def test_minimax_refresh_only_goes_back_to_minimax(net):
    cfg = ProviderConfig(id="minimax-coding-plan", name="MiniMax", kind="anthropic", base_url="https://api.minimax.io/anthropic/v1",
                         auth={"type": "minimax", "access": "a", "refresh": "r", "expires": 0, "token_url": "https://evil.test/token"})
    with pytest.raises(RuntimeError, match="Sign in again"):
        asyncio.run(auth.prepare(cfg))


def test_anthropic_adapter_uses_the_minimax_sign_in(monkeypatch):
    monkeypatch.setattr(auth.provcfg, "upsert", lambda pid, patch: None)
    monkeypatch.setattr(auth.provcfg, "add_account", lambda *a, **k: "acc")
    monkeypatch.setattr(auth.provcfg, "save_creds", lambda *a, **k: None)
    seen: list[httpx.Request] = []
    sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in [
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 3, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
        {"type": "message_stop"}]).encode()

    def handler(r):
        seen.append(r)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    cfg = ProviderConfig(id="minimax-coding-plan", name="MiniMax", kind="anthropic", base_url="https://api.minimax.io/anthropic/v1", api_key="stale",
                         auth={"type": "minimax", "access": "ma", "refresh": "mr", "expires": time.time() + 3600, "token_url": "https://account.minimax.io/oauth2/token"})
    p = AnthropicProvider(cfg, transport=httpx.MockTransport(handler))
    req = ChatRequest(model="MiniMax-M2", system="", messages=[ChatMessage("user", "hi")])

    async def go():
        return [e async for e in p.stream(req)]

    events = asyncio.run(go())
    assert str(seen[0].url) == "https://api.minimax.io/anthropic/v1/messages"
    assert seen[0].headers["authorization"] == "Bearer ma" and "x-api-key" not in seen[0].headers
    assert not [e for e in events if e.get("type") == "error"]
    plain = AnthropicProvider(ProviderConfig(id="anthropic", name="A", kind="anthropic", base_url="https://api.anthropic.com", api_key="k"))
    assert plain._signed_headers({})["x-api-key"] == "k"  # API-key providers are unchanged


def test_poe_sign_in_saves_the_key(net):
    routes, calls, saved = net
    routes["POST https://api.poe.com/token"] = lambda r: httpx.Response(200, json={"api_key": "poe-key", "api_key_expires_in": 86400})

    async def browser(login):
        q = {k: v[0] for k, v in parse_qs(urlsplit(login.url).query).items()}
        assert login.url.startswith("https://poe.com/oauth/authorize?")
        assert q["scope"] == "apikey:create" and q["code_challenge_method"] == "S256" and q["client_id"] == auth.POE_CLIENT_ID
        async with REAL_CLIENT() as c:
            r = await c.get(f"{q['redirect_uri']}?code=pc&state={q['state']}")
        assert "Signed in" in r.text

    login = _finish("poe", browser)
    assert login.provider_id == "poe"
    exchange = _form(calls[-1])
    assert exchange["grant_type"] == "authorization_code" and exchange["code"] == "pc" and exchange["code_verifier"]
    assert saved["poe"]["api_key"] == "poe-key" and saved["poe"]["auth"]["type"] == "poe"
    assert time.time() + 86000 < saved["poe"]["auth"]["expires"] < time.time() + 86500


def test_key_sign_ins_expire():
    old = ProviderConfig(id="poe", name="Poe", kind="openai", base_url="https://api.poe.com/v1", api_key="k", auth={"type": "poe", "expires": time.time() - 5})
    with pytest.raises(RuntimeError, match="Poe sign-in expired"):
        asyncio.run(auth.prepare(old))
    forever = ProviderConfig(id="poe", name="Poe", kind="openai", base_url="https://api.poe.com/v1", api_key="k", auth={"type": "poe", "expires": 0})
    assert asyncio.run(auth.prepare(forever)) == ("https://api.poe.com/v1", {})


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@pytest.mark.skipif(not _port_free(auth.DIGITALOCEAN_PORT), reason="port 1456 is in use on this machine")
def test_digitalocean_sign_in_reads_the_fragment(net):
    _, _, saved = net

    async def browser(login):
        q = {k: v[0] for k, v in parse_qs(urlsplit(login.url).query).items()}
        assert q["response_type"] == "token" and q["redirect_uri"] == "http://localhost:1456/auth/callback"
        base = f"http://127.0.0.1:{auth.DIGITALOCEAN_PORT}"
        async with REAL_CLIENT() as c:
            page = await c.get(f"{base}/auth/callback")
            assert "location.hash" in page.text and "/auth/token" in page.text
            assert (await c.options(f"{base}/auth/token")).status_code == 404  # no CORS preflight, so other sites can't post here
            r = await c.post(f"{base}/auth/token", json={"access_token": "do-tok", "token_type": "bearer", "expires_in": "2592000", "state": q["state"]})
            assert r.status_code == 200

    login = _finish("digitalocean", browser)
    assert login.provider_id == "digitalocean"
    assert saved["digitalocean"]["api_key"] == "do-tok" and saved["digitalocean"]["auth"]["type"] == "digitalocean"
    assert saved["digitalocean"]["auth"]["expires"] > time.time() + 2_500_000


def test_chatgpt_with_a_code(net):
    routes, calls, saved = net
    routes["POST https://auth.openai.com/api/accounts/deviceauth/usercode"] = lambda r: httpx.Response(200, json={"device_auth_id": "da", "user_code": "OPEN-1", "interval": "5"})
    polls = iter([httpx.Response(403, json={}), httpx.Response(404, json={}), httpx.Response(200, json={"authorization_code": "ac", "code_verifier": "cv", "code_challenge": "cc"})])
    routes["POST https://auth.openai.com/api/accounts/deviceauth/token"] = lambda r: next(polls)
    tok = _jwt({"email": "me@openai.test", "https://api.openai.com/auth": {"chatgpt_account_id": "acc", "chatgpt_plan_type": "plus"}})
    routes[f"POST {auth.CHATGPT_TOKEN}"] = lambda r: httpx.Response(200, json={"id_token": tok, "access_token": "at", "refresh_token": "rt", "expires_in": 3600})

    login = _finish("chatgpt-device")
    assert login.user_code == "OPEN-1" and login.url == auth.CHATGPT_DEVICE_PAGE
    assert login.provider_id == "chatgpt" and login.account == "me@openai.test"
    assert json.loads(calls[0].content) == {"client_id": auth.CHATGPT_CLIENT_ID}
    exchange = _form(calls[-1])
    assert exchange["code"] == "ac" and exchange["code_verifier"] == "cv" and exchange["redirect_uri"] == auth.CHATGPT_DEVICE_REDIRECT
    a = saved["chatgpt"]["auth"]
    assert a["type"] == "chatgpt" and a["account_id"] == "acc" and a["refresh"] == "rt"
    assert saved["chatgpt"]["kind"] == "responses"


def test_grok_asks_for_a_newer_client_and_gets_it(monkeypatch):
    from afh.engine.providers.openai_compat import OpenAICompatProvider

    saved = {}
    monkeypatch.setattr(auth.provcfg, "upsert", lambda pid, patch: saved.update({pid: patch}))
    monkeypatch.setattr(auth.provcfg, "add_account", lambda pid, creds, base=None, label="", activate=False: saved.update({pid: (base or {}) | creds}))
    monkeypatch.setattr(auth.provcfg, "save_creds", lambda pid, aid, patch: saved.update({pid: patch}))
    seen = []

    def handler(r):
        seen.append(r.headers["x-grok-client-version"])
        if r.headers["x-grok-client-version"] != "1.2.0":
            return httpx.Response(426, json={"error": "Your Grok CLI version (1.0.13) is outdated. Please update to version 1.2.0 or later via `grok update`."})
        body = 'data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\n\ndata: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    cfg = ProviderConfig(id="xai", name="xAI", kind="openai", base_url="https://api.x.ai/v1",
                         auth={"type": "xai", "access": "a", "refresh": "r", "expires": time.time() + 3600})
    p = OpenAICompatProvider(cfg, transport=httpx.MockTransport(handler))
    req = ChatRequest(model="grok-4.7", system="", messages=[ChatMessage("user", "hi")])

    async def go():
        return [e async for e in p.stream(req)]

    events = asyncio.run(go())
    assert seen == ["1.0.13", "1.2.0"] and not [e for e in events if e.get("type") == "error"]
    assert saved["xai"]["auth"]["client_version"] == "1.2.0"
    assert not auth.outdated_client(cfg, 426, "update to version 1.2.0 or later")  # the same answer twice is a real failure


# ---- TLS failures the user fixes on their own computer ------------------------------------------


def _cert_error(reason: str) -> httpx.ConnectError:
    import ssl
    try:
        try:
            raise ssl.SSLCertVerificationError(1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {reason} (_ssl.c:1010)")
        except ssl.SSLError as inner:
            raise httpx.ConnectError(str(inner)) from inner
    except httpx.ConnectError as outer:
        return outer


def test_a_wrong_clock_is_explained_in_plain_words():
    from afh.engine.providers.sse import network_error, tls_advice
    for reason in ("certificate is not yet valid", "certificate has expired"):
        lines = tls_advice(_cert_error(reason))
        assert lines and lines[0].startswith("This computer's date, time or time zone is wrong")
        assert lines[1].startswith("The computer's clock says ")
        assert "CERTIFICATE_VERIFY_FAILED" not in " ".join(lines)
    msg = network_error(_cert_error("certificate is not yet valid"), "https://daily-cloudcode-pa.googleapis.com/v1internal")["message"]
    assert msg.startswith("Couldn't connect securely to https://daily-cloudcode-pa.googleapis.com. This computer's date")
    assert tls_advice(_cert_error("self-signed certificate in certificate chain"))[0].startswith("Something on this computer or network is intercepting")
    assert tls_advice(_cert_error("unable to get local issuer certificate"))
    assert tls_advice(httpx.ConnectError("[Errno 11001] getaddrinfo failed")) is None


def test_sign_in_shows_the_clock_fix_instead_of_the_ssl_error():
    async def flow(login):
        raise _cert_error("certificate is not yet valid")

    login = auth.Login("antigravity")
    asyncio.run(auth._run(login, flow, None))
    assert login.status == "error"
    lines = login.error.split("\n")
    assert lines[0] == "This computer's date, time or time zone is wrong, so secure connections fail."
    assert lines[-1] == "Then try again."
    assert "_ssl.c" not in login.error
