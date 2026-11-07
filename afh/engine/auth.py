"""Sign in to a provider instead of pasting an API key.

  openrouter  browser (OAuth PKCE); OpenRouter hands back an ordinary API key
  chatgpt     browser (OAuth PKCE, the Codex CLI client); a ChatGPT Plus/Pro/Team plan pays for
              the tokens, requests go to the Codex backend through the Responses API adapter
  chatgpt-device  the same ChatGPT plan with a code typed on any device (for SSH and headless use)
  copilot     GitHub device code; a GitHub token buys short-lived Copilot tokens
  xai         device code (xAI's shared client for coding agents); a SuperGrok or X Premium+
              subscription pays, the token works on the normal xAI API
  minimax     device code (+ PKCE); a MiniMax Token Plan pays. minimax-cn is the China site
  poe         browser (OAuth PKCE); Poe hands back an API key that may expire
  digitalocean browser (implicit grant); the access token is the key for DigitalOcean's inference API
  antigravity browser (Google OAuth with Antigravity's client); the Google account's Antigravity
              quota pays for Gemini and Claude models through Google's Cloud Code backend. Google
              may suspend Antigravity access for accounts used outside its own app.

A login runs in the background: ``start`` returns at once with the URL to open (or the code to
type), the UI polls ``get``. Tokens live in the provider's ``auth`` entry in providers.json and
``prepare`` refreshes them before a request when they are about to expire.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from . import config as provcfg
from .types import ChatRequest, ProviderConfig

log = logging.getLogger("afh.auth")

LOGIN_TIMEOUT = 10 * 60

# ---- ChatGPT (Codex) ----
CHATGPT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_AUTH = "https://auth.openai.com/oauth/authorize"
CHATGPT_TOKEN = "https://auth.openai.com/oauth/token"
CHATGPT_PORT = 1455  # the redirect URI registered for this client
CHATGPT_BASE = "https://chatgpt.com/backend-api/codex"

# ---- ChatGPT (normal chat lane) ----
# The ChatGPT web backend, reached with a browser session cookie instead of the Codex OAuth.
# Gives the normal chat models (unmetered lane) and the work-mode models; the credentials are
# imported from the user's own logged-in browser (see engine/chrome_import.py). Refreshing the
# ~10-day access token is a GET /api/auth/session with the long-lived session cookie.
CHATGPT_WEB_BASE = "https://chatgpt.com"
CHATGPT_SESSION_COOKIE = "__Secure-next-auth.session-token"

# ---- GitHub Copilot ----
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
COPILOT_BASE = "https://api.githubcopilot.com"
COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.99.0", "Editor-Plugin-Version": "copilot-chat/0.26.0",
    "Copilot-Integration-Id": "vscode-chat", "User-Agent": "GitHubCopilotChat/0.26.0",
}

# ---- Google Antigravity ----
ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
ANTIGRAVITY_CLIENT_SECRET = "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"  # an installed-app client: the secret is public
ANTIGRAVITY_SCOPES = ["https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/userinfo.email",
                      "https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/cclog",
                      "https://www.googleapis.com/auth/experimentsandconfigs"]
ANTIGRAVITY_PORT = 51121  # the redirect URI registered for this client
ANTIGRAVITY_BASE = "https://daily-cloudcode-pa.googleapis.com"
ANTIGRAVITY_VERSION = "2.24.0"
ANTIGRAVITY_UA = f"antigravity/hub/{ANTIGRAVITY_VERSION} (aidev_client; os_type=darwin; arch=arm64; cl=1000335682)"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
AFH_UA = "agent-flow-harness"

# ---- ChatGPT with a code (Codex's device sign-in) ----
CHATGPT_DEVICE = "https://auth.openai.com/api/accounts/deviceauth"
CHATGPT_DEVICE_PAGE = "https://auth.openai.com/codex/device"
CHATGPT_DEVICE_REDIRECT = "https://auth.openai.com/deviceauth/callback"

# ---- xAI (Grok) ----
# xAI opened its subscriptions to coding agents through one shared public client (the consent
# screen may say "Grok Build"). The access token is a normal Bearer token for api.x.ai.
XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_ISSUER = "https://auth.x.ai/oauth2"
XAI_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_BASE = "https://api.x.ai/v1"

# ---- MiniMax Token Plan ----
MINIMAX_CLIENT_ID = "78257093-7e40-4613-99e0-527b14b39113"  # a public client; MiniMax's page may name OpenClaw
MINIMAX_SCOPE = "group_id profile model.completion"
MINIMAX_ACCOUNTS = {"minimax": "https://account.minimax.io", "minimax-cn": "https://account.minimaxi.com"}

# ---- Poe ----
POE_CLIENT_ID = "client_728290227fc048cc9262091a1ea197ea"  # a public client; Poe's page may name OpenCode
POE_ISSUER = "https://poe.com"

# ---- DigitalOcean ----
DIGITALOCEAN_CLIENT_ID = "b1a6c5158156caac821fd1b30253ca8acb52454a48fa744420e41889cb589f82"
DIGITALOCEAN_PORT = 1456  # the redirect URI registered for this client

# Which saved provider each sign-in creates.
PROVIDERS = {
    "openrouter": {"id": "openrouter", "catalog": "openrouter"},
    "chatgpt": {"id": "chatgpt", "catalog": "chatgpt"},
    "chatgpt-device": {"id": "chatgpt", "catalog": "chatgpt"},
    "chatgpt-web": {"id": "chatgpt-chat", "catalog": "chatgpt-chat"},
    "copilot": {"id": "github-copilot", "catalog": "github-copilot"},
    "antigravity": {"id": "antigravity", "catalog": "antigravity"},
    "xai": {"id": "xai", "catalog": "xai"},
    "minimax": {"id": "minimax-coding-plan", "catalog": "minimax-coding-plan"},
    "minimax-cn": {"id": "minimax-cn-coding-plan", "catalog": "minimax-cn-coding-plan"},
    "poe": {"id": "poe", "catalog": "poe"},
    "digitalocean": {"id": "digitalocean", "catalog": "digitalocean"},
}

# Sign-ins that end in an ordinary API key (kept in api_key); the rest keep refreshable tokens.
KEY_LOGINS = {"openrouter": "OpenRouter", "poe": "Poe", "digitalocean": "DigitalOcean"}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def jwt_claims(token: str) -> dict:
    """The payload of a JWT, unverified (we only read our own account id and email from it)."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}


# ---- login flows -----------------------------------------------------------------------------


@dataclass
class Login:
    method: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "pending"  # pending | done | error | cancelled
    url: str = ""  # browser flows: the page to open
    user_code: str = ""  # device flow: the code to type at ``url``
    error: str = ""
    provider_id: str = ""
    account: str = ""
    started: float = field(default_factory=time.time)
    task: asyncio.Task | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)  # set once url/user_code are known

    def view(self) -> dict:
        return {"id": self.id, "method": self.method, "status": self.status, "url": self.url, "userCode": self.user_code,
                "error": self.error, "providerID": self.provider_id, "account": self.account}


_logins: dict[str, Login] = {}
OnDone = Callable[[str], Awaitable[None]]


async def start(method: str, on_done: OnDone | None = None) -> Login:
    if method not in PROVIDERS:
        raise ValueError(f"No sign-in for {method!r}")
    for old in list(_logins.values()):  # one login per method at a time (ChatGPT's port is fixed)
        if old.method == method and old.status == "pending":
            cancel(old.id)
    login = Login(method)
    _logins[login.id] = login
    flow = {"openrouter": _openrouter, "chatgpt": _chatgpt, "chatgpt-device": _chatgpt_device, "copilot": _copilot, "antigravity": _antigravity,
            "xai": _xai, "minimax": _minimax, "minimax-cn": _minimax, "poe": _poe, "digitalocean": _digitalocean}[method]
    login.task = asyncio.create_task(_run(login, flow, on_done))
    try:
        await asyncio.wait_for(login.ready.wait(), 20)
    except asyncio.TimeoutError:
        pass
    return login


def get(login_id: str) -> Login | None:
    return _logins.get(login_id)


def cancel(login_id: str) -> None:
    login = _logins.get(login_id)
    if login and login.status == "pending":
        login.status = "cancelled"
        if login.task:
            login.task.cancel()


async def _run(login: Login, flow: Callable[[Login], Awaitable[None]], on_done: OnDone | None) -> None:
    try:
        await asyncio.wait_for(flow(login), LOGIN_TIMEOUT)
        login.status = "done"
        if on_done:
            await on_done(login.provider_id)
    except asyncio.CancelledError:
        login.status = "cancelled"
    except asyncio.TimeoutError:
        login.status, login.error = "error", "The sign-in timed out. Try again."
    except Exception as err:  # shown in the sign-in dialog
        log.info("sign-in %s failed: %s", login.method, err)
        login.status, login.error = "error", str(err) or err.__class__.__name__
    finally:
        login.ready.set()
        for lid, old in list(_logins.items()):  # forget finished logins after a while
            if old.status != "pending" and time.time() - old.started > 3600:
                _logins.pop(lid, None)


def _save(method: str, patch: dict) -> str:
    from .providers.catalog import entries

    target = PROVIDERS[method]
    cat = entries()[target["catalog"]]
    base = {"name": cat["name"], "kind": cat["kind"], "base_url": cat["base_url"], "headers": dict(cat.get("headers", {})),
            "extra": dict(cat.get("extra", {})), "fetch_models": cat.get("fetch_models", True), "catalog": target["catalog"], "enabled": True}
    provcfg.upsert(target["id"], base | patch)
    return target["id"]


# ---- one-shot local HTTP server for browser redirects ----


_DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>AFH</title>
<body style="font:15px system-ui;background:#0e0d0d;color:#f2efec;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><h2 style="margin:0 0 8px">{title}</h2><p style="opacity:.7">{text}</p></div>"""


_FRAGMENT_PAGE = """<!doctype html><meta charset="utf-8"><title>AFH</title>
<body style="font:15px system-ui;background:#0e0d0d;color:#f2efec;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><h2 id="t" style="margin:0 0 8px">Finishing sign-in</h2><p id="p" style="opacity:.7"></p></div>
<script>
const q = Object.fromEntries(new URLSearchParams(location.hash.slice(1) || location.search.slice(1)));
history.replaceState(null, "", location.pathname);
fetch("__POST__", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(q) })
  .then((r) => r.ok, () => false)
  .then((ok) => {
    const good = ok && q.access_token;
    document.getElementById("t").textContent = good ? "Signed in" : "Sign-in failed";
    document.getElementById("p").textContent = good ? "You can close this tab and go back to AFH." : (q.error_description || q.error || "No token was returned.");
  });
</script>"""


class _Callback:
    """Waits for ``GET <path>?code=...`` on localhost and answers the browser with a small page.
    With ``post_path`` the GET serves a page that posts the URL fragment back (implicit grant)."""

    def __init__(self, path: str, port: int = 0, post_path: str = ""):
        self.path, self.port, self.post_path = path, port, post_path
        self.result: asyncio.Future = asyncio.get_running_loop().create_future()
        self.servers: list[asyncio.AbstractServer] = []

    async def __aenter__(self) -> "_Callback":
        try:
            first = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        except OSError as err:
            raise RuntimeError(f"Port {self.port} is busy (is another sign-in, or the Codex CLI, waiting on it?)") from err
        self.servers.append(first)
        self.port = first.sockets[0].getsockname()[1]
        try:  # browsers may resolve "localhost" to ::1 first
            self.servers.append(await asyncio.start_server(self._handle, "::1", self.port))
        except OSError:
            pass
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for s in self.servers:
            s.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1")
            length = 0
            while (header := await asyncio.wait_for(reader.readline(), 10)) not in (b"\r\n", b"\n", b""):
                name, _, value = header.decode("latin-1").partition(":")
                if name.strip().lower() == "content-length":
                    length = min(int(value.strip() or 0), 65536)
            verb = line.split(" ")[0]
            target = line.split(" ")[1] if line.count(" ") >= 2 else "/"
            parts = urlsplit(target)
            if self.post_path and verb == "POST" and parts.path == self.post_path:
                raw = await asyncio.wait_for(reader.readexactly(length), 10) if length else b""
                try:
                    posted = json.loads(raw or b"{}")
                except ValueError:
                    posted = {}
                ok = isinstance(posted, dict)
                writer.write(b"HTTP/1.1 " + (b"200 OK" if ok else b"400 Bad Request") + b"\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: 2\r\n\r\n{}")
                if ok and not self.result.done():
                    self.result.set_result({str(k): str(v) for k, v in posted.items()})
                return
            if self.post_path and parts.path == self.path:
                body = _FRAGMENT_PAGE.replace("__POST__", self.post_path).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
                return
            if parts.path != self.path:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            ok = "code" in query
            page = _DONE_PAGE.format(title="Signed in" if ok else "Sign-in failed",
                                     text="You can close this tab and go back to AFH." if ok else (query.get("error_description") or query.get("error") or "No code was returned."))
            body = page.encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            if not self.result.done():
                self.result.set_result(query)
        except Exception:
            pass
        finally:
            try:
                await writer.drain()
                writer.close()
            except Exception:
                pass


async def _openrouter(login: Login) -> None:
    verifier, challenge = pkce()
    async with _Callback("/callback") as cb:
        login.url = "https://openrouter.ai/auth?" + urlencode({"callback_url": f"http://localhost:{cb.port}/callback", "code_challenge": challenge, "code_challenge_method": "S256"})
        login.ready.set()
        query = await cb.result
    if not query.get("code"):
        raise RuntimeError(query.get("error_description") or query.get("error") or "OpenRouter returned no code")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://openrouter.ai/api/v1/auth/keys", json={"code": query["code"], "code_verifier": verifier, "code_challenge_method": "S256"})
    if resp.status_code >= 300:
        raise RuntimeError(f"OpenRouter refused the code ({resp.status_code}): {resp.text[:200]}")
    key = resp.json().get("key")
    if not key:
        raise RuntimeError("OpenRouter returned no key")
    login.account = "OpenRouter account"
    login.provider_id = _save("openrouter", {"api_key": key, "auth": {"type": "openrouter", "account": login.account}})


async def _chatgpt(login: Login) -> None:
    verifier, challenge = pkce()
    state = _b64url(secrets.token_bytes(24))
    redirect = f"http://localhost:{CHATGPT_PORT}/auth/callback"
    async with _Callback("/auth/callback", CHATGPT_PORT) as cb:
        login.url = CHATGPT_AUTH + "?" + urlencode({
            "response_type": "code", "client_id": CHATGPT_CLIENT_ID, "redirect_uri": redirect, "scope": "openid profile email offline_access",
            "code_challenge": challenge, "code_challenge_method": "S256", "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true", "state": state, "originator": "codex_cli_rs",
        })
        login.ready.set()
        query = await cb.result
    if query.get("state") != state:
        raise RuntimeError("The sign-in answer did not match this request. Try again.")
    if not query.get("code"):
        raise RuntimeError(query.get("error_description") or "OpenAI returned no code")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(CHATGPT_TOKEN, data={"grant_type": "authorization_code", "code": query["code"], "redirect_uri": redirect,
                                                      "client_id": CHATGPT_CLIENT_ID, "code_verifier": verifier})
    if resp.status_code >= 300:
        raise RuntimeError(f"OpenAI refused the code ({resp.status_code}): {resp.text[:200]}")
    auth = _chatgpt_auth(resp.json(), {})
    if not auth.get("account_id"):
        raise RuntimeError("This OpenAI account has no ChatGPT plan attached")
    login.account = auth.get("account", "")
    login.provider_id = _save("chatgpt", {"auth": auth})


async def _chatgpt_device(login: Login) -> None:
    """The ChatGPT plan with a code typed on any device: no local port, so it works over SSH."""
    async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json", "user-agent": AFH_UA}) as client:
        resp = await client.post(f"{CHATGPT_DEVICE}/usercode", json={"client_id": CHATGPT_CLIENT_ID})
        if resp.status_code >= 300:
            raise RuntimeError(f"OpenAI refused the sign-in ({resp.status_code}): {resp.text[:200]}")
        dev = resp.json()
        login.url, login.user_code = CHATGPT_DEVICE_PAGE, dev.get("user_code") or dev.get("usercode") or ""
        login.ready.set()
        interval = max(int(dev.get("interval") or 5), 1)
        while True:
            await asyncio.sleep(interval + 1)
            poll = await client.post(f"{CHATGPT_DEVICE}/token", json={"device_auth_id": dev["device_auth_id"], "user_code": login.user_code})
            if poll.status_code < 300:
                grant = poll.json()
                break
            if poll.status_code not in (403, 404):  # 403/404 = not approved yet
                raise RuntimeError(f"OpenAI device sign-in failed ({poll.status_code}): {poll.text[:200]}")
        resp = await client.post(CHATGPT_TOKEN, data={"grant_type": "authorization_code", "code": grant["authorization_code"], "redirect_uri": CHATGPT_DEVICE_REDIRECT,
                                                      "client_id": CHATGPT_CLIENT_ID, "code_verifier": grant["code_verifier"]})
    if resp.status_code >= 300:
        raise RuntimeError(f"OpenAI refused the code ({resp.status_code}): {resp.text[:200]}")
    auth = _chatgpt_auth(resp.json(), {})
    if not auth.get("account_id"):
        raise RuntimeError("This OpenAI account has no ChatGPT plan attached")
    login.account = auth.get("account", "")
    login.provider_id = _save("chatgpt-device", {"auth": auth})


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _poll_device(client: httpx.AsyncClient, url: str, form: dict, interval: float, lifetime: float) -> dict:
    """Asks an RFC 8628 token endpoint until the person approves the code (or it runs out)."""
    deadline = time.time() + lifetime
    while time.time() < deadline:
        await asyncio.sleep(interval)
        resp = await client.post(url, data=form)
        data = _json(resp)
        if resp.status_code < 300 and data.get("access_token"):
            return data
        err = data.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err in ("access_denied", "authorization_denied"):
            raise RuntimeError("The sign-in was declined.")
        if err == "expired_token":
            break
        raise RuntimeError(data.get("error_description") or err or f"The sign-in failed ({resp.status_code})")
    raise RuntimeError("The code expired before it was approved. Start the sign-in again.")


def _expiry(tokens: dict, field: str = "expires_in") -> float:
    """Epoch seconds: from a lifetime in seconds, an epoch in seconds or milliseconds, or the JWT's exp."""
    value = tokens.get(field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if number > 1e12:
        return number / 1000
    if number > 1e9:
        return number
    if number > 0:
        return time.time() + number
    exp = jwt_claims(str(tokens.get("access_token") or "")).get("exp")
    return float(exp) if isinstance(exp, (int, float)) and exp > 1e9 else time.time() + 3600


async def _xai(login: Login) -> None:
    async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json", "user-agent": AFH_UA}) as client:
        resp = await client.post(f"{XAI_ISSUER}/device/code", data={"client_id": XAI_CLIENT_ID, "scope": XAI_SCOPE, "referrer": AFH_UA})
        if resp.status_code >= 300:
            raise RuntimeError(f"xAI refused the sign-in ({resp.status_code}): {resp.text[:200]}")
        dev = resp.json()
        login.url = dev.get("verification_uri_complete") or dev.get("verification_uri") or "https://accounts.x.ai/oauth2/device"
        login.user_code = dev.get("user_code", "")
        login.ready.set()
        tokens = await _poll_device(client, f"{XAI_ISSUER}/token", {"grant_type": DEVICE_GRANT, "client_id": XAI_CLIENT_ID, "device_code": dev["device_code"]},
                                    max(float(dev.get("interval") or 5), 1), float(dev.get("expires_in") or 900))
        if not tokens.get("refresh_token"):
            raise RuntimeError("xAI returned no refresh token. Try again.")
        login.account = jwt_claims(tokens.get("id_token") or "").get("email") or ""
        if not login.account:
            info = await client.get(f"{XAI_ISSUER}/userinfo", headers={"authorization": f"Bearer {tokens['access_token']}"})
            login.account = _json(info).get("email", "") if info.status_code < 300 else ""
    login.provider_id = _save("xai", {"auth": _xai_auth(tokens, {"account": login.account})})


def _xai_auth(tokens: dict, old: dict) -> dict:
    return {"type": "xai", "access": tokens.get("access_token") or old.get("access", ""), "refresh": tokens.get("refresh_token") or old.get("refresh", ""),
            "expires": _expiry(tokens), "account": old.get("account", "")}


def _minimax_error(data: dict, resp: httpx.Response) -> str:
    return (data.get("base_resp") or {}).get("status_msg") or data.get("error_description") or data.get("error") or resp.text[:200] or str(resp.status_code)


async def _minimax(login: Login) -> None:
    site = MINIMAX_ACCOUNTS[login.method]
    verifier, challenge = pkce()
    state = _b64url(secrets.token_bytes(16))
    async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json", "user-agent": AFH_UA}) as client:
        resp = await client.post(f"{site}/oauth2/device/code", headers={"x-request-id": str(uuid.uuid4())}, data={
            "response_type": "code", "client_id": MINIMAX_CLIENT_ID, "scope": MINIMAX_SCOPE, "code_challenge": challenge, "code_challenge_method": "S256", "state": state})
        dev = _json(resp)
        if resp.status_code >= 300 or not dev.get("user_code"):
            raise RuntimeError(f"MiniMax refused the sign-in: {_minimax_error(dev, resp)}")
        if dev.get("state") != state:
            raise RuntimeError("The sign-in answer did not match this request. Try again.")
        login.url, login.user_code = dev.get("verification_uri") or "", dev["user_code"]
        login.ready.set()
        deadline = _expiry(dev, "expired_in") if dev.get("expired_in") else time.time() + 600
        interval = max(float(dev.get("interval") or 2000) / 1000, 2)
        while True:
            if time.time() >= deadline:
                raise RuntimeError("The code expired before it was approved. Start the sign-in again.")
            await asyncio.sleep(interval)
            poll = await client.post(f"{site}/oauth2/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:user_code", "client_id": MINIMAX_CLIENT_ID,
                                                                   "user_code": dev["user_code"], "code_verifier": verifier})
            tokens = _json(poll)
            if poll.status_code >= 300 or tokens.get("status") == "error":
                raise RuntimeError(f"MiniMax sign-in failed: {_minimax_error(tokens, poll)}")
            if tokens.get("status") == "success":
                break
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("MiniMax returned an incomplete sign-in. Try again.")
    login.account = "MiniMax account"
    login.provider_id = _save(login.method, {"auth": _minimax_auth(tokens, {"account": login.account, "token_url": f"{site}/oauth2/token"})})


def _minimax_auth(tokens: dict, old: dict) -> dict:
    return {"type": "minimax", "access": tokens.get("access_token") or old.get("access", ""), "refresh": tokens.get("refresh_token") or old.get("refresh", ""),
            "expires": _expiry(tokens, "expired_in"), "token_url": old.get("token_url", ""), "account": old.get("account", "")}


async def _poe(login: Login) -> None:
    verifier, challenge = pkce()
    state = _b64url(secrets.token_bytes(24))
    async with _Callback("/callback") as cb:
        redirect = f"http://127.0.0.1:{cb.port}/callback"
        login.url = f"{POE_ISSUER}/oauth/authorize?" + urlencode({"response_type": "code", "client_id": POE_CLIENT_ID, "redirect_uri": redirect, "scope": "apikey:create",
                                                                 "code_challenge": challenge, "code_challenge_method": "S256", "state": state})
        login.ready.set()
        query = await cb.result
    if query.get("error") and query.get("state") == state:
        raise RuntimeError(query.get("error_description") or query["error"])
    if query.get("state") != state or ("iss" in query and query["iss"] != POE_ISSUER):
        raise RuntimeError("The sign-in answer did not match this request. Try again.")
    if not query.get("code"):
        raise RuntimeError(query.get("error_description") or query.get("error") or "Poe returned no code")
    async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json"}) as client:
        resp = await client.post("https://api.poe.com/token", data={"grant_type": "authorization_code", "client_id": POE_CLIENT_ID, "code": query["code"],
                                                                     "redirect_uri": redirect, "code_verifier": verifier})
    data = _json(resp)
    key = str(data.get("api_key") or "").strip()
    if resp.status_code >= 300 or not key:
        raise RuntimeError(f"Poe refused the code: {data.get('error_description') or data.get('error') or resp.status_code}")
    lifetime = data.get("api_key_expires_in")
    login.account = "Poe account"
    login.provider_id = _save("poe", {"api_key": key, "auth": {"type": "poe", "account": login.account,
                                                               "expires": time.time() + float(lifetime) if lifetime else 0}})


async def _digitalocean(login: Login) -> None:
    state = _b64url(secrets.token_bytes(24))
    redirect = f"http://localhost:{DIGITALOCEAN_PORT}/auth/callback"
    async with _Callback("/auth/callback", DIGITALOCEAN_PORT, post_path="/auth/token") as cb:
        login.url = "https://cloud.digitalocean.com/v1/oauth/authorize?" + urlencode({"response_type": "token", "client_id": DIGITALOCEAN_CLIENT_ID, "redirect_uri": redirect,
                                                                                    "scope": "genai:read inference:query", "state": state})
        login.ready.set()
        data = await cb.result
    if data.get("error"):
        raise RuntimeError(data.get("error_description") or data["error"])
    if data.get("state") != state:
        raise RuntimeError("The sign-in answer did not match this request. Try again.")
    if not data.get("access_token"):
        raise RuntimeError("DigitalOcean returned no token")
    login.account = "DigitalOcean account"
    login.provider_id = _save("digitalocean", {"api_key": data["access_token"], "auth": {
        "type": "digitalocean", "account": login.account, "expires": time.time() + (float(data.get("expires_in") or 0) or 30 * 86400)}})


async def import_chatgpt_web(creds: dict) -> dict:
    """Validate a ChatGPT web session (from Chrome or a paste) and save it as the chatgpt-chat
    provider. ``creds`` has a ``session_token`` (preferred, refreshable) and/or an ``access`` token,
    plus optional ``device_id``/``ua``. Returns {account, plan}."""
    from .providers.pow import DEFAULT_UA

    device_id = creds.get("device_id") or uuid.uuid4().hex
    ua = creds.get("ua") or DEFAULT_UA
    session_token = creds.get("session_token", "")
    async with httpx.AsyncClient(timeout=30) as client:
        if session_token:
            resp = await client.get(f"{CHATGPT_WEB_BASE}/api/auth/session",
                                    headers={"user-agent": ua, "accept": "*/*", "cookie": f"{CHATGPT_SESSION_COOKIE}={session_token}", "oai-device-id": device_id})
            if resp.status_code != 200:
                raise RuntimeError(f"ChatGPT did not accept that session ({resp.status_code}). Sign in to chatgpt.com again and re-copy the token.")
            data = resp.json() if resp.content else {}
            access = data.get("accessToken") or ""
            if len(access) < 20:
                raise RuntimeError("That session is not signed in to ChatGPT. Sign in at chatgpt.com, then copy the token again.")
        else:
            access = creds.get("access", "")
            if len(access) < 20:
                raise RuntimeError("No session token or access token found.")
            resp = await client.get(f"{CHATGPT_WEB_BASE}/backend-api/me",
                                    headers={"authorization": f"Bearer {access}", "user-agent": ua, "oai-device-id": device_id, "oai-language": "en-US"})
            if resp.status_code != 200:
                raise RuntimeError(f"ChatGPT did not accept that access token ({resp.status_code}). Paste a fresh one.")
            data = {"user": resp.json() if resp.content else {}, "expires": creds.get("expires")}
    account = data.get("account") or {}
    account_id = account.get("id") if account.get("structure") == "workspace" and account.get("id") else ""
    user = data.get("user") or {}
    auth = {"type": "chatgpt-web", "session_token": session_token, "device_id": device_id, "ua": ua,
            "access": access, "expires": _chatgpt_web_expiry(data.get("expires")), "account_id": account_id,
            "account": user.get("email") or "", "plan": (account.get("plan") or {}).get("type") if isinstance(account, dict) else ""}
    _save("chatgpt-web", {"auth": auth})
    return {"account": auth["account"], "plan": auth.get("plan") or ""}


def _chatgpt_auth(tokens: dict, old: dict) -> dict:
    claims = jwt_claims(tokens.get("id_token") or "") or jwt_claims(tokens.get("access_token") or "")
    info = claims.get("https://api.openai.com/auth") or {}
    return {
        "type": "chatgpt", "access": tokens.get("access_token") or old.get("access", ""), "refresh": tokens.get("refresh_token") or old.get("refresh", ""),
        "id_token": tokens.get("id_token") or old.get("id_token", ""), "expires": time.time() + int(tokens.get("expires_in") or 3600),
        "account_id": info.get("chatgpt_account_id") or old.get("account_id", ""), "plan": info.get("chatgpt_plan_type") or old.get("plan", ""),
        "account": claims.get("email") or old.get("account", ""),
    }


async def _copilot(login: Login) -> None:
    async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json"}) as client:
        resp = await client.post("https://github.com/login/device/code", json={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"})
        if resp.status_code >= 300:
            raise RuntimeError(f"GitHub refused the sign-in ({resp.status_code})")
        dev = resp.json()
        login.url = dev.get("verification_uri") or "https://github.com/login/device"
        login.user_code = dev.get("user_code", "")
        login.ready.set()
        interval = int(dev.get("interval") or 5)
        while True:
            await asyncio.sleep(interval)
            r = await client.post("https://github.com/login/oauth/access_token", json={
                "client_id": COPILOT_CLIENT_ID, "device_code": dev["device_code"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            data = r.json() if r.content else {}
            if data.get("access_token"):
                gh = data["access_token"]
                break
            err = data.get("error")
            if err == "slow_down":
                interval += 5
            elif err != "authorization_pending":
                raise RuntimeError(data.get("error_description") or err or "GitHub sign-in failed")
        user = await client.get("https://api.github.com/user", headers={"authorization": f"token {gh}"})
        login.account = (user.json() or {}).get("login", "") if user.status_code < 300 else ""
    auth = {"type": "copilot", "github": gh, "account": login.account}
    auth = await _copilot_token(auth)  # fails here (not on the first message) when the account has no Copilot
    login.provider_id = _save("copilot", {"auth": auth})


async def _copilot_token(auth: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get("https://api.github.com/copilot_internal/v2/token", headers={"authorization": f"token {auth['github']}", "accept": "application/json", **COPILOT_HEADERS})
    if resp.status_code == 401:
        raise RuntimeError("GitHub sign-in expired. Sign in to Copilot again in Settings → Models.")
    if resp.status_code >= 300:
        raise RuntimeError(f"No Copilot access for this GitHub account ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return auth | {"access": data.get("token", ""), "expires": float(data.get("expires_at") or time.time() + 1500),
                   "api": ((data.get("endpoints") or {}).get("api") or COPILOT_BASE).rstrip("/")}


async def _antigravity(login: Login) -> None:
    verifier, challenge = pkce()
    state = _b64url(secrets.token_bytes(24))
    redirect = f"http://localhost:{ANTIGRAVITY_PORT}/oauth-callback"
    async with _Callback("/oauth-callback", ANTIGRAVITY_PORT) as cb:
        login.url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": ANTIGRAVITY_CLIENT_ID, "response_type": "code", "redirect_uri": redirect, "scope": " ".join(ANTIGRAVITY_SCOPES),
            "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "access_type": "offline", "prompt": "consent",
        })
        login.ready.set()
        query = await cb.result
    if query.get("state") != state:
        raise RuntimeError("The sign-in answer did not match this request. Try again.")
    if not query.get("code"):
        raise RuntimeError(query.get("error_description") or query.get("error") or "Google returned no code")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GOOGLE_TOKEN, data={"client_id": ANTIGRAVITY_CLIENT_ID, "client_secret": ANTIGRAVITY_CLIENT_SECRET, "code": query["code"],
                                                     "grant_type": "authorization_code", "redirect_uri": redirect, "code_verifier": verifier})
        if resp.status_code >= 300:
            raise RuntimeError(f"Google refused the code ({resp.status_code}): {resp.text[:200]}")
        tokens = resp.json()
        if not tokens.get("refresh_token"):
            raise RuntimeError("Google returned no refresh token. Try again.")
        access = tokens["access_token"]
        info = await client.get("https://www.googleapis.com/oauth2/v1/userinfo?alt=json", headers={"authorization": f"Bearer {access}"})
        login.account = (info.json() or {}).get("email", "") if info.status_code < 300 else ""
        project = await _antigravity_project(client, access)
    auth = {"type": "antigravity", "access": access, "refresh": tokens["refresh_token"], "expires": time.time() + int(tokens.get("expires_in") or 3600),
            "account": login.account, "project": project}
    login.provider_id = _save("antigravity", {"auth": auth})


async def _antigravity_project(client: httpx.AsyncClient, access: str) -> str:
    """The Cloud Code project the account's quota lives in: from loadCodeAssist, or made by onboardUser
    for an account that never opened Antigravity."""
    h = {"authorization": f"Bearer {access}", "content-type": "application/json", "user-agent": ANTIGRAVITY_UA}
    resp = await client.post(f"{ANTIGRAVITY_BASE}/v1internal:loadCodeAssist", headers=h, json={"metadata": {"ideType": "ANTIGRAVITY"}})
    if resp.status_code == 403:
        raise RuntimeError(f"Google refused Antigravity for this account: {_google_error(resp)}")
    data = resp.json() if resp.status_code < 300 else {}
    project = _project_id(data.get("cloudaicompanionProject"))
    if project:
        return project
    tiers = data.get("allowedTiers") or []
    tier = (next((t.get("id") for t in tiers if t.get("isDefault") and t.get("id")), None) or (tiers[0].get("id") if tiers else None)
            or (data.get("currentTier") or {}).get("id") or "free-tier")
    body = {"tier_id": tier, "metadata": {"ide_type": "ANTIGRAVITY", "ide_version": ANTIGRAVITY_VERSION, "ide_name": "antigravity"}}
    for _ in range(10):
        r = await client.post(f"{ANTIGRAVITY_BASE}/v1internal:onboardUser", headers=h, json=body)
        if r.status_code >= 300:
            raise RuntimeError(f"Google could not set up Antigravity for this account: {_google_error(r)}")
        payload = r.json()
        if payload.get("done"):
            project = _project_id((payload.get("response") or {}).get("cloudaicompanionProject"))
            if project:
                return project
            break
        await asyncio.sleep(3)
    raise RuntimeError("Google did not finish setting up Antigravity for this account. Open Antigravity once, then sign in again.")


def _project_id(value: Any) -> str:
    pid = value.get("id") if isinstance(value, dict) else value
    return pid.strip() if isinstance(pid, str) else ""


def _google_error(resp: httpx.Response) -> str:
    try:
        return (resp.json().get("error") or {}).get("message") or resp.text[:200]
    except ValueError:
        return resp.text[:200] or str(resp.status_code)


# ---- using the credentials -------------------------------------------------------------------

_locks: dict[str, asyncio.Lock] = {}


def _chatgpt_web_expiry(expires: Any) -> float:
    """Epoch seconds for the access token; the session reply gives an ISO date, else assume ~9 days."""
    if isinstance(expires, str) and expires:
        try:
            return datetime.fromisoformat(expires.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time() + 9 * 86400


async def _refresh(config: ProviderConfig) -> dict:
    auth = config.auth
    if auth.get("type") == "chatgpt-web":
        base = (config.base_url or CHATGPT_WEB_BASE).split("/backend-api")[0]
        headers = {"user-agent": auth.get("ua") or "", "accept": "*/*",
                   "cookie": f"{CHATGPT_SESSION_COOKIE}={auth.get('session_token', '')}", "oai-device-id": auth.get("device_id", "")}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{base}/api/auth/session", headers=headers)
        if resp.status_code != 200:
            raise RuntimeError("ChatGPT session expired. Import your ChatGPT login from Chrome again in Settings → Models.")
        data = resp.json() if resp.content else {}
        access = data.get("accessToken") or ""
        if len(access) < 20:
            raise RuntimeError("ChatGPT session expired. Import your ChatGPT login from Chrome again in Settings → Models.")
        account = data.get("account") or {}
        account_id = account.get("id") if account.get("structure") == "workspace" and account.get("id") else auth.get("account_id", "")
        return auth | {"access": access, "expires": _chatgpt_web_expiry(data.get("expires")),
                       "account_id": account_id or "", "account": (data.get("user") or {}).get("email") or auth.get("account", "")}
    if auth.get("type") == "chatgpt":
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(CHATGPT_TOKEN, json={"client_id": CHATGPT_CLIENT_ID, "grant_type": "refresh_token",
                                                          "refresh_token": auth.get("refresh", ""), "scope": "openid profile email"})
        if resp.status_code >= 300:
            raise RuntimeError("ChatGPT sign-in expired. Sign in again in Settings → Models.")
        return _chatgpt_auth(resp.json(), auth)
    if auth.get("type") == "xai":
        async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json", "user-agent": AFH_UA}) as client:
            resp = await client.post(f"{XAI_ISSUER}/token", data={"grant_type": "refresh_token", "refresh_token": auth.get("refresh", ""), "client_id": XAI_CLIENT_ID})
        if resp.status_code >= 300:
            raise RuntimeError("xAI sign-in expired. Sign in again in Settings → Models.")
        return _xai_auth(resp.json(), auth)
    if auth.get("type") == "minimax":
        if not auth.get("token_url", "").startswith(tuple(MINIMAX_ACCOUNTS.values())):  # the refresh token only goes back where it came from
            raise RuntimeError("MiniMax sign-in expired. Sign in again in Settings → Models.")
        async with httpx.AsyncClient(timeout=30, headers={"accept": "application/json", "user-agent": AFH_UA}) as client:
            resp = await client.post(auth["token_url"], data={"grant_type": "refresh_token", "client_id": MINIMAX_CLIENT_ID, "refresh_token": auth.get("refresh", "")})
        data = _json(resp)
        if resp.status_code >= 300 or data.get("status") not in (None, "success") or not data.get("access_token"):
            raise RuntimeError("MiniMax sign-in expired. Sign in again in Settings → Models.")
        return _minimax_auth(data, auth)
    if auth.get("type") == "antigravity":
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(GOOGLE_TOKEN, data={"client_id": ANTIGRAVITY_CLIENT_ID, "client_secret": ANTIGRAVITY_CLIENT_SECRET,
                                                         "grant_type": "refresh_token", "refresh_token": auth.get("refresh", "")})
        if resp.status_code >= 300:
            raise RuntimeError("Antigravity sign-in expired. Sign in again in Settings → Models.")
        data = resp.json()
        return auth | {"access": data.get("access_token", ""), "expires": time.time() + int(data.get("expires_in") or 3600),
                       "refresh": data.get("refresh_token") or auth.get("refresh", "")}
    return await _copilot_token(auth)


SIGNED_IN = ("chatgpt", "copilot", "antigravity", "chatgpt-web", "xai", "minimax")


def signed_in(config: ProviderConfig) -> bool:
    return (config.auth or {}).get("type") in SIGNED_IN


async def prepare(config: ProviderConfig, req: ChatRequest | None = None, force: bool = False) -> tuple[str, dict[str, str]]:
    """Base URL and auth headers for one request; refreshes an expiring token first (and saves it).
    ``force`` refreshes anyway: the server just said 401 to a token we thought was fine."""
    auth = config.auth or {}
    kind = auth.get("type")
    if kind in KEY_LOGINS and float(auth.get("expires") or 0) and float(auth["expires"]) < time.time():
        raise RuntimeError(f"Your {KEY_LOGINS[kind]} sign-in expired. Sign in again in Settings → Models.")
    if kind not in SIGNED_IN:
        return config.base_url, {}
    lock = _locks.setdefault(config.id, asyncio.Lock())
    async with lock:
        if force or not auth.get("access") or float(auth.get("expires") or 0) < time.time() + 120:
            fresh = await _refresh(config)
            config.auth = fresh
            provcfg.upsert(config.id, {"auth": fresh})
            auth = fresh
    if kind == "chatgpt-web":
        base = (config.base_url or CHATGPT_WEB_BASE).split("/backend-api")[0]
        h = {"authorization": f"Bearer {auth['access']}", "oai-device-id": auth.get("device_id", ""), "user-agent": auth.get("ua", ""),
             "oai-language": "en-US", "origin": base, "referer": f"{base}/"}
        if auth.get("account_id"):
            h["chatgpt-account-id"] = auth["account_id"]
        return base, h
    if kind == "chatgpt":
        return config.base_url or CHATGPT_BASE, {"authorization": f"Bearer {auth['access']}", "chatgpt-account-id": auth.get("account_id", ""),
                                                 "OpenAI-Beta": "responses=experimental", "originator": "codex_cli_rs"}
    if kind == "antigravity":
        return config.base_url or ANTIGRAVITY_BASE, {"authorization": f"Bearer {auth['access']}", "user-agent": ANTIGRAVITY_UA}
    if kind == "xai":
        return config.base_url or XAI_BASE, {"authorization": f"Bearer {auth['access']}"}
    if kind == "minimax":  # Bearer on MiniMax's Anthropic-style endpoint, in place of x-api-key
        return config.base_url, {"authorization": f"Bearer {auth['access']}"}
    h = {"authorization": f"Bearer {auth['access']}", "Openai-Intent": "conversation-edits", **COPILOT_HEADERS}
    if req is not None:
        last = req.messages[-1] if req.messages else None
        h["X-Initiator"] = "user" if last is not None and last.role == "user" else "agent"  # agent turns don't use premium requests
        if any(m.images for m in req.messages):
            h["Copilot-Vision-Request"] = "true"
    return auth.get("api") or COPILOT_BASE, h
