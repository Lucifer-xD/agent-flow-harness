"""Remote control: a second listener on the LAN (and optionally a Cloudflare quick tunnel) that
serves the same UI, protected by a password the user sets. Phones and other computers use it."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import logging
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import uvicorn

from . import store

log = logging.getLogger("afh.remote")

CLOUDFLARED_CANDIDATES = [
    "cloudflared",
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
]

state = {
    "server": None,  # uvicorn.Server for the LAN listener
    "thread": None,
    "port": None,
    "tunnel": None,  # subprocess.Popen of cloudflared
    "tunnel_url": None,
    "tunnel_error": None,
    "tokens": set(),  # issued remote tokens (process lifetime)
    "attempts": [],  # login attempt timestamps for rate limiting
}


def settings() -> dict:
    s = store.load_settings().get("remote") or {}
    return {"enabled": bool(s.get("enabled")), "port": int(s.get("port") or 0), "passwordHash": s.get("passwordHash") or "", "tunnel": s.get("tunnel") or "none"}


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt).split("$", 1)[1], digest)


def lan_addresses() -> list[str]:
    """IPv4 addresses other devices can reach, best effort."""
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except socket.gaierror:
        pass
    try:  # the interface that routes to the internet is usually the right one
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
            if ip not in found:
                found.insert(0, ip)
            elif found[0] != ip:
                found.remove(ip)
                found.insert(0, ip)
    except OSError:
        pass
    return found


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


# ---- listener -----------------------------------------------------------------------


def start_listener(port: int) -> None:
    if state["server"] and state["port"] == port:
        return
    stop_listener()
    from .api import app  # late import: api imports this module

    from .engine.core import engine

    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    if engine.loop is None:
        raise RuntimeError("The engine is not running yet")
    future = asyncio.run_coroutine_threadsafe(server.serve(), engine.loop)
    deadline = time.time() + 10
    while not server.started and not future.done() and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError(f"Could not listen on port {port} (is it in use?)")
    state.update(server=server, thread=future, port=port)
    log.info("remote listener on 0.0.0.0:%s", port)


def stop_listener() -> None:
    server = state["server"]
    if server:
        server.should_exit = True
        try:
            state["thread"].result(timeout=5)
        except Exception:
            pass
    state.update(server=None, thread=None, port=None)
    state["tokens"].clear()


# ---- cloudflare quick tunnel ------------------------------------------------------------


def find_cloudflared() -> str | None:
    for candidate in CLOUDFLARED_CANDIDATES:
        path = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if path:
            return path
    return None


def start_tunnel(port: int) -> None:
    stop_tunnel()
    exe = find_cloudflared()
    if not exe:
        state["tunnel_error"] = "cloudflared is not installed. Get it from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
        return
    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    state.update(tunnel=proc, tunnel_url=None, tunnel_error=None)

    def pump() -> None:
        for line in proc.stdout or []:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not state["tunnel_url"]:
                state["tunnel_url"] = m.group(0)
                log.info("tunnel url %s", state["tunnel_url"])
            if "error" in line.lower() and not state["tunnel_url"]:
                state["tunnel_error"] = line.strip()[:300]
        if state["tunnel"] is proc:
            state.update(tunnel=None, tunnel_url=None)

    threading.Thread(target=pump, daemon=True, name="afh-tunnel").start()


def stop_tunnel() -> None:
    proc = state["tunnel"]
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    state.update(tunnel=None, tunnel_url=None)


# ---- public API used by api.py ---------------------------------------------------------------


def apply(s: dict) -> None:
    """Bring listener and tunnel in line with the saved settings."""
    if s["enabled"] and s["passwordHash"]:
        start_listener(s["port"])
        if s["tunnel"] == "cloudflare":
            if not state["tunnel"]:
                start_tunnel(s["port"])
        else:
            stop_tunnel()
    else:
        stop_tunnel()
        stop_listener()


def login(password: str) -> str | None:
    now = time.time()
    state["attempts"] = [t for t in state["attempts"] if now - t < 60]
    if len(state["attempts"]) >= 6:
        raise PermissionError("Too many attempts — wait a minute")
    state["attempts"].append(now)
    if not check_password(password, settings()["passwordHash"]):
        return None
    token = secrets.token_urlsafe(32)
    state["tokens"].add(token)
    return token


def qr_svg(text: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg

        img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return ""


def status() -> dict:
    s = settings()
    port = state["port"] or s["port"]
    urls = [f"http://{ip}:{port}" for ip in lan_addresses()] if state["server"] else []
    tunnel_url = state["tunnel_url"]
    primary = tunnel_url or (urls[0] if urls else None)
    return {
        "enabled": s["enabled"],
        "running": bool(state["server"]),
        "port": port,
        "passwordSet": bool(s["passwordHash"]),
        "tunnel": s["tunnel"],
        "tunnelUrl": tunnel_url,
        "tunnelError": state["tunnel_error"],
        "cloudflared": bool(find_cloudflared()),
        "lanUrls": urls,
        "qr": qr_svg(primary) if primary else "",
        "connected": len(state["tokens"]),
    }
