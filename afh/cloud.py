"""AFH account: keeps this computer reachable from the user's phone through the relay at
agentflowharness.com (relay/app.py). The computer opens one outgoing WebSocket; each request a
signed-in phone makes arrives on it, is answered by this AFH's own API on 127.0.0.1 and streams
back. Nothing listens on the network, and only the account that added the computer can reach it."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import threading
import time

import httpx

from . import __version__, store

log = logging.getLogger("afh.cloud")

RELAY = (os.environ.get("AFH_RELAY") or "https://agentflowharness.com").rstrip("/")
CONFIG = store.AFH_DIR / "cloud.json"
CHUNK = 192 * 1024
ONE_FRAME = 512 * 1024  # answers smaller than this go back in a single frame
# what a phone may not change from afar: who can reach this computer
LOCAL_ONLY = ("/api/cloud", "/api/remote")
PASS_HEADERS = {"content-type", "accept", "last-event-id", "accept-language", "range"}

state: dict = {"task": None, "status": "off", "error": None, "since": None}
# a sign-in waiting for the user in their browser: {code, url, expires, error}
link: dict = {"pending": None, "error": None, "stop": None}


def load() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    store.AFH_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass


def relay_url(cfg: dict | None = None) -> str:
    return ((cfg or {}).get("relay") or RELAY).rstrip("/")


def status() -> dict:
    cfg = load()
    comp = cfg.get("computer") or {}
    return {"signedIn": bool(comp.get("token")), "email": cfg.get("email") or "", "computer": {"id": comp.get("id"), "name": comp.get("name")} if comp else None,
            "enabled": bool(cfg.get("enabled")), "state": state["status"], "error": state["error"], "since": state["since"],
            "relay": relay_url(cfg), "accountUrl": relay_url(cfg) + "/account",
            "link": link["pending"], "linkError": link["error"]}


def _error(r: httpx.Response) -> str:
    try:
        return r.json().get("error") or f"{r.status_code}"
    except ValueError:
        return f"The AFH server answered {r.status_code}"


def link_start(name: str = "") -> dict:
    """Begin signing in through the website: AFH never sees the password. The relay hands back a
    short code and a page on agentflowharness.com; the user signs in (or creates the account)
    there and approves this computer, and a background poll picks up the computer's token."""
    link_cancel()
    base = relay_url(load())
    name = name.strip() or platform.node() or "My computer"
    try:
        r = httpx.post(f"{base}/relay/api/link/start", json={"name": name}, timeout=20)
    except httpx.HTTPError as exc:
        raise ValueError(f"Couldn't reach {base}: {exc}") from exc
    if r.status_code >= 400:
        raise ValueError(_error(r))
    got = r.json()
    stop_ev = threading.Event()
    link.update(pending={"code": got["code"], "url": got["url"], "expires": time.time() + got.get("expires", 900)}, error=None, stop=stop_ev)
    threading.Thread(target=_link_poll, args=(base, got["poll"], stop_ev), name="afh-cloud-link", daemon=True).start()
    return status()


def link_cancel() -> dict:
    if link["stop"]:
        link["stop"].set()
    link.update(pending=None, stop=None)
    return status()


def _link_poll(base: str, poll: str, stop_ev: threading.Event) -> None:
    misses = 0
    while not stop_ev.wait(2):
        try:
            r = httpx.get(f"{base}/relay/api/link/poll", params={"poll": poll}, timeout=15)
        except httpx.HTTPError:
            misses += 1
            if misses < 30:
                continue
            r = None
        if stop_ev.is_set():
            return
        if r is not None and r.status_code == 202:
            misses = 0
            continue
        link.update(pending=None, stop=None)
        if r is None or r.status_code >= 400:
            link["error"] = _error(r) if r is not None else f"Lost touch with {base}"
            return
        got = r.json()
        cfg = load()
        cfg.update(email=got["email"], computer=got["computer"], enabled=True)
        save(cfg)
        link["error"] = None
        try:
            restart()
        except RuntimeError as exc:
            state.update(status="retrying", error=str(exc))
        return


def sign_out() -> dict:
    cfg = load()
    token = (cfg.get("computer") or {}).get("token")
    stop()
    if token:
        try:  # take it off the account too; if the server can't be reached it stays listed as offline
            httpx.post(f"{relay_url(cfg)}/relay/api/computer/forget", headers={"authorization": f"Bearer {token}"}, timeout=10)
        except httpx.HTTPError:
            pass
    save({k: v for k, v in cfg.items() if k == "relay"})
    state.update(status="off", error=None, since=None)
    return status()


def set_enabled(on: bool) -> dict:
    cfg = load()
    if on and not (cfg.get("computer") or {}).get("token"):
        raise ValueError("Sign in to your AFH account first")
    cfg["enabled"] = bool(on)
    save(cfg)
    restart() if on else stop()
    return status()


# ---- the connection ---------------------------------------------------------------------------


def _loop():
    from .engine.core import engine

    return engine.loop


def start() -> None:
    """Called at startup: connect if the user left it on."""
    cfg = load()
    if cfg.get("enabled") and (cfg.get("computer") or {}).get("token"):
        restart()


def restart() -> None:
    stop()
    loop = _loop()
    if loop is None:
        raise RuntimeError("The engine is not running yet")
    state.update(status="connecting", error=None)
    state["task"] = asyncio.run_coroutine_threadsafe(_run(), loop)


def stop() -> None:
    fut = state.get("task")
    if fut:
        fut.cancel()
    state.update(task=None, status="off", since=None)


async def _run() -> None:
    import websockets

    delay = 2
    while True:
        cfg = load()
        comp = cfg.get("computer") or {}
        if not cfg.get("enabled") or not comp.get("token"):
            state.update(status="off")
            return
        url = relay_url(cfg).replace("https://", "wss://").replace("http://", "ws://") + "/relay/agent"
        state.update(status="connecting")
        try:
            async with websockets.connect(url, additional_headers={"authorization": f"Bearer {comp['token']}", "x-afh-version": __version__},
                                          ping_interval=25, ping_timeout=40, max_size=None, open_timeout=20) as ws:
                state.update(status="online", error=None, since=time.time())
                log.info("connected to %s as %s", relay_url(cfg), comp.get("id"))
                delay = 2
                await _serve(ws)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (401, 403):  # removed from the account (on the phone, or the account was deleted)
                cfg = load()
                cfg.pop("computer", None)
                cfg["enabled"] = False
                save(cfg)
                state.update(status="off", error="This computer was removed from your AFH account. Sign in again to add it back.", since=None)
                log.info("relay refused this computer: signed out")
                return
            state.update(status="retrying", error=f"Can't reach the AFH server ({type(exc).__name__}). Retrying…", since=None)
            log.info("relay connection failed: %s", exc)
        else:
            state.update(status="retrying", error=None, since=None)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


async def _serve(ws) -> None:
    from . import api

    port = api.ACCESS.get("port")
    lock = asyncio.Lock()
    tasks: dict[int, asyncio.Task] = {}

    async def send(msg: dict) -> None:
        async with lock:
            await ws.send(json.dumps(msg, separators=(",", ":")))

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=httpx.Timeout(None, connect=10)) as client:

        async def answer(req: dict) -> None:
            rid = req["id"]
            method, path = req.get("method") or "GET", req.get("path") or "/"
            try:
                if method != "GET" and path.startswith(LOCAL_ONLY):
                    body = json.dumps({"error": "Change remote access settings on the computer itself"}).encode()
                    await send({"t": "res", "id": rid, "status": 403, "headers": {"content-type": "application/json"}, "body": base64.b64encode(body).decode(), "end": True})
                    return
                headers = {k: v for k, v in (req.get("headers") or {}).items() if k.lower() in PASS_HEADERS}
                headers["x-afh-token"] = api.ACCESS["token"] or ""
                headers["x-afh-via"] = "relay"
                url = path + (f"?{req['query']}" if req.get("query") else "")
                body = base64.b64decode(req.get("body") or "")
                async with client.stream(method, url, headers=headers, content=body or None) as r:
                    head = {"t": "res", "id": rid, "status": r.status_code, "headers": {k: v for k, v in r.headers.items() if k.lower() not in ("content-length", "content-encoding", "transfer-encoding", "connection")}}
                    if "event-stream" in r.headers.get("content-type", ""):
                        await send(head)
                        async for chunk in r.aiter_bytes():
                            await send({"t": "chunk", "id": rid, "data": base64.b64encode(chunk).decode()})
                    else:
                        buf, sent = bytearray(), False
                        async for chunk in r.aiter_bytes():
                            buf += chunk
                            if len(buf) > ONE_FRAME or sent:
                                if not sent:
                                    await send(head)
                                    sent = True
                                while len(buf) >= CHUNK:
                                    await send({"t": "chunk", "id": rid, "data": base64.b64encode(bytes(buf[:CHUNK])).decode()})
                                    del buf[:CHUNK]
                        if not sent:
                            await send({**head, "body": base64.b64encode(bytes(buf)).decode(), "end": True})
                            return
                        if buf:
                            await send({"t": "chunk", "id": rid, "data": base64.b64encode(bytes(buf)).decode()})
                    await send({"t": "end", "id": rid})
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning("relay request %s %s failed: %s", method, path, exc)
                try:
                    body = json.dumps({"error": f"AFH on this computer couldn't answer: {exc}"}).encode()
                    await send({"t": "res", "id": rid, "status": 502, "headers": {"content-type": "application/json"}, "body": base64.b64encode(body).decode(), "end": True})
                    await send({"t": "end", "id": rid})  # in case the answer had already started
                except Exception:
                    pass
            finally:
                tasks.pop(rid, None)

        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("t") == "req":
                    tasks[msg["id"]] = asyncio.create_task(answer(msg))
                elif msg.get("t") == "cancel":
                    t = tasks.pop(msg.get("id"), None)
                    if t:
                        t.cancel()
        finally:
            for t in list(tasks.values()):
                t.cancel()
