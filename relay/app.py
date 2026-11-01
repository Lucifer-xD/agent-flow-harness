"""AFH relay: accounts for remote access, and the pipe between a phone and the user's computer.

A computer running AFH keeps a WebSocket open to /relay/agent. A phone signed in to the same
account opens https://<site>/r/<computer>/ and every HTTP request there goes down that socket, is
answered by the computer's own AFH (its full UI and API) and streams back. The relay stores
accounts, sign-in sessions and the list of computers - never threads, files or keys; the rest only
passes through.

Run: uvicorn app:app --host 127.0.0.1 --port 8840 (nginx in front, see deploy/afh-website.nginx).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html as htmllib
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

log = logging.getLogger("afh.relay")
DB_PATH = Path(os.environ.get("AFH_RELAY_DB", "/var/lib/afh-relay/relay.db"))
STATIC = Path(__file__).parent / "static"
COOKIE = "afh_s"
DEV = os.environ.get("AFH_RELAY_DEV") == "1"  # local testing over plain http (an emulator can't keep Secure cookies there)
SESSION_DAYS = 90
MAX_BODY = 25 * 1024 * 1024
FIRST_BYTE_TIMEOUT = 90  # seconds for the computer to start answering
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
# what a phone's request may carry to the computer, and what comes back
FORWARD_REQUEST = {"content-type", "accept", "last-event-id", "accept-language", "range"}
FORWARD_RESPONSE = {"content-type", "cache-control", "content-disposition", "content-range", "accept-ranges", "last-modified", "etag"}
# settings that decide who can reach the computer stay on the computer
BLOCKED = ("api/cloud", "api/remote")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
# The Android and iPhone apps run their own pages (https://localhost, capacitor://localhost) and call
# the API with a bearer token; no cookies cross origins, so nothing here works for other sites.
APP_ORIGINS = ["https://localhost", "capacitor://localhost", "ionic://localhost"] + (["http://localhost", "http://localhost:5173"] if DEV else [])
app.add_middleware(CORSMiddleware, allow_origins=APP_ORIGINS, allow_credentials=False, allow_methods=["*"],
                   allow_headers=["authorization", "content-type", "last-event-id", "accept"], max_age=86400)


# ---- storage --------------------------------------------------------------------------------


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS computers (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL, token TEXT UNIQUE NOT NULL, created REAL NOT NULL,
                last_seen REAL, version TEXT);
        """)


def digest(token: str) -> str:
    """Tokens are stored hashed: a copy of the database can't sign anyone in."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).split("$")[2], h)
    except ValueError:
        return False


# ---- rate limits ------------------------------------------------------------------------------

ATTEMPTS: dict[str, list[float]] = {}


def limited(key: str, most: int, window: float) -> bool:
    now = time.time()
    hits = [t for t in ATTEMPTS.get(key, []) if now - t < window]
    hits.append(now)
    ATTEMPTS[key] = hits
    if len(ATTEMPTS) > 20000:  # forget idle keys
        for k in [k for k, v in ATTEMPTS.items() if now - v[-1] > 3600]:
            ATTEMPTS.pop(k, None)
    return len(hits) > most


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# ---- accounts ------------------------------------------------------------------------------


def new_session(con: sqlite3.Connection, user_id: str, kind: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (digest(token), user_id, kind, now, now + SESSION_DAYS * 86400))
    return token


def session_token(request: Request, cookie_only: bool = False) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer ") and not cookie_only:
        return auth[7:].strip()
    return request.cookies.get(COOKIE) or ""


def current_user(request: Request, cookie_only: bool = False) -> sqlite3.Row | None:
    token = session_token(request, cookie_only)
    if not token:
        return None
    with db() as con:
        row = con.execute("SELECT u.*, s.expires, s.token AS sid FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
                          (digest(token),)).fetchone()
        if not row:
            return None
        if row["expires"] < time.time():
            con.execute("DELETE FROM sessions WHERE token = ?", (row["sid"],))
            return None
        if row["expires"] - time.time() < (SESSION_DAYS - 1) * 86400:  # slide: in use means signed in
            con.execute("UPDATE sessions SET expires = ? WHERE token = ?", (time.time() + SESSION_DAYS * 86400, row["sid"]))
        return row


def signed_in(user: sqlite3.Row, token: str, kind: str) -> JSONResponse:
    res = JSONResponse({"user": {"id": user["id"], "email": user["email"]}, **({"token": token} if kind != "web" else {})})
    if kind == "web":  # the website keeps it in an HttpOnly cookie, out of reach of page scripts
        res.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, secure=not DEV, samesite="lax", path="/")
    return res


def credentials(body: dict) -> tuple[str, str, str]:
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    kind = body.get("kind") if body.get("kind") in ("desktop", "app") else "web"
    return email, password, kind


@app.post("/relay/api/signup")
def signup(request: Request, body: dict = Body(...)):
    email, password, kind = credentials(body)
    if limited("signup:" + client_ip(request), 8, 3600):
        return err("Too many new accounts from here - try again later", 429)
    if not EMAIL.match(email) or len(email) > 254:
        return err("Enter a valid email address")
    if len(password) < 8:
        return err("Use a password of at least 8 characters")
    if len(password) > 256:
        return err("That password is too long")
    with db() as con:
        if con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return err("There's already an account with that email - sign in instead", 409)
        uid = "u_" + secrets.token_hex(8)
        con.execute("INSERT INTO users VALUES (?,?,?,?)", (uid, email, hash_password(password), time.time()))
        token = new_session(con, uid, kind)
        user = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    log.info("signup %s", uid)
    return signed_in(user, token, kind)


@app.post("/relay/api/signin")
def signin(request: Request, body: dict = Body(...)):
    email, password, kind = credentials(body)
    if limited("signin:" + client_ip(request), 20, 600) or limited("signin:" + email, 10, 900):
        return err("Too many attempts - wait a few minutes", 429)
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not check_password(password, user["pw"]):
            return err("Wrong email or password", 401)
        token = new_session(con, user["id"], kind)
    return signed_in(user, token, kind)


@app.post("/relay/api/signout")
def signout(request: Request):
    token = session_token(request)
    if token:
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token = ?", (digest(token),))
    res = JSONResponse({"ok": True})
    res.delete_cookie(COOKIE, path="/")
    return res


def computer_view(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "online": row["id"] in LINKS, "lastSeen": row["last_seen"], "version": row["version"]}


@app.get("/relay/api/me")
def me(request: Request):
    user = current_user(request)
    if not user:
        return err("Not signed in", 401)
    with db() as con:
        rows = con.execute("SELECT * FROM computers WHERE user_id = ? ORDER BY created", (user["id"],)).fetchall()
    return {"user": {"id": user["id"], "email": user["email"]}, "computers": [computer_view(r) for r in rows]}


@app.post("/relay/api/password")
def change_password(request: Request, body: dict = Body(...)):
    user = current_user(request)
    if not user:
        return err("Not signed in", 401)
    if limited("password:" + user["id"], 10, 900):
        return err("Too many attempts - wait a few minutes", 429)
    if not check_password(str(body.get("old") or ""), user["pw"]):
        return err("Your current password is wrong", 401)
    new = str(body.get("new") or "")
    if not 8 <= len(new) <= 256:
        return err("Use a password of at least 8 characters")
    with db() as con:
        con.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_password(new), user["id"]))
        # every other sign-in ends; this one stays
        con.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?", (user["id"], user["sid"]))
    return {"ok": True}


@app.post("/relay/api/account/delete")
async def delete_account(request: Request, body: dict = Body(...)):
    user = current_user(request)
    if not user:
        return err("Not signed in", 401)
    if not check_password(str(body.get("password") or ""), user["pw"]):
        return err("Wrong password", 401)
    with db() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM computers WHERE user_id = ?", (user["id"],))]
        con.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    for cid in ids:
        await drop_link(cid)
    log.info("account deleted %s", user["id"])
    res = JSONResponse({"ok": True})
    res.delete_cookie(COOKIE, path="/")
    return res


# ---- computers ---------------------------------------------------------------------------------


@app.post("/relay/api/computers")
def add_computer(request: Request, body: dict = Body(...)):
    """A desktop signs in once, then registers itself; its own token is what keeps it connected."""
    user = current_user(request)
    if not user:
        return err("Not signed in", 401)
    name = " ".join(str(body.get("name") or "My computer").split())[:60] or "My computer"
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM computers WHERE user_id = ?", (user["id"],)).fetchone()[0] >= 20:
            return err("This account already has 20 computers - remove one first")
        cid = "c_" + secrets.token_hex(6)
        token = "afhc_" + secrets.token_urlsafe(32)
        con.execute("INSERT INTO computers (id, user_id, name, token, created) VALUES (?,?,?,?,?)", (cid, user["id"], name, digest(token), time.time()))
    return {"id": cid, "name": name, "token": token}


def owned(con: sqlite3.Connection, user: sqlite3.Row, cid: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM computers WHERE id = ? AND user_id = ?", (cid, user["id"])).fetchone()


@app.patch("/relay/api/computers/{cid}")
def rename_computer(cid: str, request: Request, body: dict = Body(...)):
    user = current_user(request)
    if not user:
        return err("Not signed in", 401)
    name = " ".join(str(body.get("name") or "").split())[:60]
    with db() as con:
        if not owned(con, user, cid):
            return err("No such computer", 404)
        if name:
            con.execute("UPDATE computers SET name = ? WHERE id = ?", (name, cid))
        return computer_view(con.execute("SELECT * FROM computers WHERE id = ?", (cid,)).fetchone())


@app.delete("/relay/api/computers/{cid}")
async def remove_computer(cid: str, request: Request):
    user = current_user(request)
    if not user:
        return err("Not signed in", 401)
    with db() as con:
        if not owned(con, user, cid):
            return err("No such computer", 404)
        con.execute("DELETE FROM computers WHERE id = ?", (cid,))
    await drop_link(cid)
    return {"ok": True}


@app.post("/relay/api/computer/forget")
async def forget_computer(request: Request):
    """A computer signing out of its account takes itself off the list (it only has its own token)."""
    token = session_token(request)
    with db() as con:
        comp = con.execute("SELECT id FROM computers WHERE token = ?", (digest(token),)).fetchone() if token else None
        if not comp:
            return err("Unknown computer", 401)
        con.execute("DELETE FROM computers WHERE id = ?", (comp["id"],))
    await drop_link(comp["id"])
    return {"ok": True}


# ---- linking a computer from the website -----------------------------------------------------------
# The desktop app never asks for the password: it starts a link, opens the website, the user signs in
# (or creates the account) there and approves, and the app picks up its computer token.

PAIRINGS: dict[str, dict] = {}
PAIR_SECONDS = 15 * 60
PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def pairing(code: str) -> dict | None:
    now = time.time()
    for k in [k for k, v in PAIRINGS.items() if now - v["created"] > PAIR_SECONDS]:
        PAIRINGS.pop(k, None)
    return PAIRINGS.get(code.strip().upper())


@app.post("/relay/api/link/start")
def link_start(request: Request, body: dict = Body(default={})):
    if limited("link:" + client_ip(request), 30, 3600):
        return err("Too many sign-in attempts from here - try again later", 429)
    code = "-".join("".join(secrets.choice(PAIR_ALPHABET) for _ in range(4)) for _ in range(2))
    poll = secrets.token_urlsafe(24)
    name = " ".join(str(body.get("name") or "My computer").split())[:60] or "My computer"
    PAIRINGS[code] = {"poll": poll, "name": name, "created": time.time(), "state": "waiting", "result": None}
    base = str(request.base_url).rstrip("/") if DEV else "https://" + (request.headers.get("host") or "agentflowharness.com")
    return {"code": code, "poll": poll, "url": f"{base}/account?link={code}", "expires": PAIR_SECONDS}


@app.get("/relay/api/link/poll")
def link_poll(poll: str):
    for code, p in list(PAIRINGS.items()):
        if hmac.compare_digest(p["poll"], poll):
            if time.time() - p["created"] > PAIR_SECONDS:
                PAIRINGS.pop(code, None)
                return err("The sign-in link expired - start again", 410)
            if p["state"] == "denied":
                PAIRINGS.pop(code, None)
                return err("Sign-in was cancelled in the browser", 410)
            if p["state"] == "approved":
                PAIRINGS.pop(code, None)  # the computer token is handed out once
                return p["result"]
            return JSONResponse({"waiting": True}, status_code=202)
    return err("Unknown or expired sign-in - start again", 410)


@app.get("/relay/api/link/{code}")
def link_info(code: str, request: Request):
    p = pairing(code)
    if not p or p["state"] != "waiting":
        return err("This link has expired. Start again from AFH on your computer.", 410)
    return {"name": p["name"], "expires": int(p["created"] + PAIR_SECONDS)}


@app.post("/relay/api/link/{code}/approve")
def link_approve(code: str, request: Request):
    user = current_user(request)
    if not user:
        return err("Sign in first", 401)
    p = pairing(code)
    if not p or p["state"] != "waiting":
        return err("This link has expired. Start again from AFH on your computer.", 410)
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM computers WHERE user_id = ?", (user["id"],)).fetchone()[0] >= 20:
            return err("This account already has 20 computers - remove one first")
        cid = "c_" + secrets.token_hex(6)
        token = "afhc_" + secrets.token_urlsafe(32)
        con.execute("INSERT INTO computers (id, user_id, name, token, created) VALUES (?,?,?,?,?)", (cid, user["id"], p["name"], digest(token), time.time()))
    p.update(state="approved", result={"email": user["email"], "computer": {"id": cid, "name": p["name"], "token": token}})
    log.info("computer linked %s", cid)
    return {"ok": True, "computer": {"id": cid, "name": p["name"]}}


@app.post("/relay/api/link/{code}/deny")
def link_deny(code: str):
    p = pairing(code)
    if p and p["state"] == "waiting":
        p["state"] = "denied"
    return {"ok": True}


@app.get("/relay/api/health")
def health():
    return {"ok": True, "online": len(LINKS)}


# ---- the pipe: computer side ---------------------------------------------------------------


class Link:
    """One computer's open socket, and the requests waiting on it."""

    def __init__(self, ws: WebSocket, cid: str):
        self.ws, self.cid = ws, cid
        self.pending: dict[int, asyncio.Queue] = {}
        self.counter = 0
        self.lock = asyncio.Lock()

    def open(self) -> tuple[int, asyncio.Queue]:
        self.counter += 1
        q: asyncio.Queue = asyncio.Queue()
        self.pending[self.counter] = q
        return self.counter, q

    async def send(self, msg: dict) -> None:
        async with self.lock:
            await self.ws.send_text(json.dumps(msg, separators=(",", ":")))


LINKS: dict[str, Link] = {}


async def drop_link(cid: str) -> None:
    link = LINKS.pop(cid, None)
    if link:
        for q in link.pending.values():
            q.put_nowait({"t": "gone"})
        try:
            await link.ws.close(code=4403)
        except Exception:
            pass


@app.websocket("/relay/agent")
async def agent(ws: WebSocket):
    auth = ws.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    with db() as con:
        comp = con.execute("SELECT * FROM computers WHERE token = ?", (digest(token),)).fetchone() if token else None
        if comp:
            version = (ws.headers.get("x-afh-version") or "")[:20]
            con.execute("UPDATE computers SET last_seen = ?, version = ? WHERE id = ?", (time.time(), version, comp["id"]))
    if not comp:
        await ws.close(code=4401)
        return
    await ws.accept()
    cid = comp["id"]
    old = LINKS.get(cid)
    if old:  # the same computer reconnected: the new socket wins
        await drop_link(cid)
    link = Link(ws, cid)
    LINKS[cid] = link
    log.info("computer online %s", cid)
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("t")
            if kind == "ping":
                await link.send({"t": "pong"})
                continue
            q = link.pending.get(msg.get("id"))
            if q is not None:
                q.put_nowait(msg)
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        pass
    finally:
        if LINKS.get(cid) is link:
            del LINKS[cid]
        for q in link.pending.values():
            q.put_nowait({"t": "gone"})
        with db() as con:
            con.execute("UPDATE computers SET last_seen = ? WHERE id = ?", (time.time(), cid))
        log.info("computer offline %s", cid)


# ---- the pipe: phone side --------------------------------------------------------------------


def page(title: str, text: str, status: int) -> HTMLResponse:
    html = (STATIC / "m" / "notice.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{title}}", htmllib.escape(title)).replace("{{text}}", htmllib.escape(text)), status_code=status)


@app.api_route("/r/{cid}", methods=["GET"])
def computer_root(cid: str):
    return RedirectResponse(f"/r/{cid}/", status_code=307)


@app.api_route("/r/{cid}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(cid: str, path: str, request: Request):
    navigating = request.method == "GET" and not path.startswith("api/") and "text/html" in (request.headers.get("accept") or "")
    user = current_user(request)
    if not user:
        return RedirectResponse("/account", status_code=303) if navigating else err("Sign in again", 401)
    with db() as con:
        comp = owned(con, user, cid)
    if not comp:
        return page("Not found", "This computer isn't on your account.", 404) if navigating else err("No such computer", 404)
    if path.startswith(BLOCKED) and request.method != "GET":
        return err("Change remote access settings on the computer itself", 403)
    link = LINKS.get(cid)
    if not link:
        if navigating:
            return page(f"{comp['name']} is offline", "Open AFH on that computer and keep it signed in under Settings → Remote control. This page reconnects by itself.", 503)
        return err(f"{comp['name']} is offline", 503)
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return err("That upload is too large", 413)
    body = await request.body()
    if len(body) > MAX_BODY:
        return err("That upload is too large", 413)
    rid, q = link.open()
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQUEST}
    try:
        await link.send({"t": "req", "id": rid, "method": request.method, "path": "/" + path, "query": request.url.query,
                         "headers": headers, "body": base64.b64encode(body).decode() if body else ""})
        first = await asyncio.wait_for(q.get(), FIRST_BYTE_TIMEOUT)
    except (asyncio.TimeoutError, RuntimeError, WebSocketDisconnect):
        link.pending.pop(rid, None)
        return err(f"{comp['name']} didn't answer", 504)
    if first.get("t") != "res":
        link.pending.pop(rid, None)
        return err(f"{comp['name']} went offline", 502)
    out_headers = {k: v for k, v in (first.get("headers") or {}).items() if k.lower() in FORWARD_RESPONSE}
    if "event-stream" in out_headers.get("content-type", ""):
        out_headers["X-Accel-Buffering"] = "no"  # nginx: pass events through as they come
    if first.get("end"):  # small answers come in one frame
        link.pending.pop(rid, None)
        return Response(base64.b64decode(first.get("body") or ""), status_code=int(first.get("status") or 502), headers=out_headers)

    async def stream():
        done = False
        try:
            while True:
                msg = await q.get()
                if msg.get("t") == "chunk":
                    yield base64.b64decode(msg.get("data") or "")
                elif msg.get("t") in ("end", "gone"):
                    done = True
                    break
        finally:
            link.pending.pop(rid, None)
            if not done and LINKS.get(cid) is link:  # the phone went away: stop the computer's side too
                try:
                    await link.send({"t": "cancel", "id": rid})
                except Exception:
                    pass

    return StreamingResponse(stream(), status_code=int(first.get("status") or 502), headers=out_headers)


# ---- chat on the website: a pass-through to model providers and the web ------------------------
#
# Browsers can't call most model APIs (no CORS) or read other sites, so the web chat sends those
# requests here with the target in X-AFH-Target. The relay forwards them as they are and streams the
# answer back; keys and messages pass through and are never stored or logged. Only for signed-in
# accounts, only to public https addresses.

FWD_DROP = {"host", "cookie", "origin", "referer", "content-length", "connection", "accept-encoding", "user-agent", "te",
            "upgrade", "priority", "x-real-ip", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-afh-target", "x-afh-ua"}
FWD_RESPONSE = {"content-type", "cache-control", "retry-after", "x-request-id", "location"}
FWD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_fwd_client = None


def fwd_client():
    global _fwd_client
    if _fwd_client is None:
        import httpx
        _fwd_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=300, write=60, pool=20), follow_redirects=False,
                                        limits=httpx.Limits(max_connections=200, max_keepalive_connections=40))
    return _fwd_client


async def public_host(host: str, port: int) -> bool:
    """Every address the name resolves to is on the public internet (not this server or a private network)."""
    import ipaddress
    import socket
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addrs = {ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos}
    return bool(addrs) and all(a.is_global for a in addrs)


@app.api_route("/relay/api/fwd", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def forward(request: Request):
    from urllib.parse import urlsplit
    user = current_user(request, cookie_only=True)  # Authorization here is the provider's key, not ours
    if not user:
        return err("Sign in again", 401)
    if limited(f"fwd:{user['id']}", 1500, 3600):
        return err("Too many requests through AFH this hour. Try again later.", 429)
    target = request.headers.get("x-afh-target") or ""
    u = urlsplit(target)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        return err("Only https addresses can be reached", 400)
    if not await public_host(u.hostname, u.port or 443):
        return err(f"{u.hostname} can't be reached from AFH", 400)
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return err("That request is too large", 413)
    body = await request.body()
    if len(body) > MAX_BODY:
        return err("That request is too large", 413)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in FWD_DROP and not k.lower().startswith("sec-")}
    headers["user-agent"] = request.headers.get("x-afh-ua") or FWD_UA
    headers["accept-encoding"] = "identity"  # bytes go straight through, so ask for them plain
    client = fwd_client()
    import httpx
    try:
        req = client.build_request(request.method, target, headers=headers, content=body or None)
        res = await client.send(req, stream=True)
    except httpx.TimeoutException:
        return err(f"{u.hostname} didn't answer in time", 504)
    except httpx.HTTPError:
        return err(f"Couldn't reach {u.hostname}", 502)
    out = {k: v for k, v in res.headers.items() if k.lower() in FWD_RESPONSE}
    out["X-Accel-Buffering"] = "no"
    out["Cache-Control"] = "no-store"
    out["X-AFH-Fwd"] = "1"  # the provider's own answer, not the relay's

    async def stream():
        try:
            async for chunk in res.aiter_raw():
                yield chunk
        except httpx.HTTPError:
            pass
        finally:
            await res.aclose()

    return StreamingResponse(stream(), status_code=res.status_code, headers=out)


# ---- assets for the notice pages; accounts themselves live on the website (/account) ------------


@app.get("/m")
@app.get("/m/")
def mobile_index():
    return RedirectResponse("/account", status_code=301)


@app.get("/m/{name}")
def mobile_file(name: str):
    f = STATIC / "m" / name
    if not re.fullmatch(r"[\w.-]+", name) or not f.is_file() or name == "notice.html":
        return err("Not found", 404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


init_db()
