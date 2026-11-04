"""Sign in to a provider instead of pasting an API key.

  openrouter  browser (OAuth PKCE); OpenRouter hands back an ordinary API key
  chatgpt     browser (OAuth PKCE, the Codex CLI client); a ChatGPT Plus/Pro/Team plan pays for
              the tokens, requests go to the Codex backend through the Responses API adapter
  copilot     GitHub device code; a GitHub token buys short-lived Copilot tokens

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

# Which saved provider each sign-in creates.
PROVIDERS = {
    "openrouter": {"id": "openrouter", "catalog": "openrouter"},
    "chatgpt": {"id": "chatgpt", "catalog": "chatgpt"},
    "chatgpt-web": {"id": "chatgpt-chat", "catalog": "chatgpt-chat"},
    "copilot": {"id": "github-copilot", "catalog": "github-copilot"},
}


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
    flow = {"openrouter": _openrouter, "chatgpt": _chatgpt, "copilot": _copilot}[method]
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


class _Callback:
    """Waits for ``GET <path>?code=...`` on localhost and answers the browser with a small page."""

    def __init__(self, path: str, port: int = 0):
        self.path, self.port = path, port
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
            while (await asyncio.wait_for(reader.readline(), 10)) not in (b"\r\n", b"\n", b""):
                pass
            target = line.split(" ")[1] if line.count(" ") >= 2 else "/"
            parts = urlsplit(target)
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
    return await _copilot_token(auth)


SIGNED_IN = ("chatgpt", "copilot", "chatgpt-web")


def signed_in(config: ProviderConfig) -> bool:
    return (config.auth or {}).get("type") in SIGNED_IN


async def prepare(config: ProviderConfig, req: ChatRequest | None = None, force: bool = False) -> tuple[str, dict[str, str]]:
    """Base URL and auth headers for one request; refreshes an expiring token first (and saves it).
    ``force`` refreshes anyway: the server just said 401 to a token we thought was fine."""
    auth = config.auth or {}
    kind = auth.get("type")
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
    h = {"authorization": f"Bearer {auth['access']}", "Openai-Intent": "conversation-edits", **COPILOT_HEADERS}
    if req is not None:
        last = req.messages[-1] if req.messages else None
        h["X-Initiator"] = "user" if last is not None and last.role == "user" else "agent"  # agent turns don't use premium requests
        if any(m.images for m in req.messages):
            h["Copilot-Vision-Request"] = "true"
    return auth.get("api") or COPILOT_BASE, h
