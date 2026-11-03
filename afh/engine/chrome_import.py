"""Import a ChatGPT web session from a locally installed Chromium browser (Chrome / Edge / Brave).

Two ways in, both "use your own browser login":
* ``read_browser_session`` — decrypt the ``__Secure-next-auth.session-token`` cookie straight from
  the browser's cookie store. Works when the browser is CLOSED and the cookie uses the classic
  ``v10`` (DPAPI + AES-256-GCM) encryption. Newer Chrome writes ``v20`` app-bound cookies, which a
  normal process cannot decrypt, and a running browser locks the file — in those cases this raises
  and the caller falls back to paste.
* ``parse_paste`` — the reliable path: the user copies their session token (or a session-export
  JSON, or the ``/api/auth/session`` reply) from the browser and pastes it in.

Nothing here contacts the network; validating the session is done by the caller via auth.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass

SESSION_COOKIE = "__Secure-next-auth.session-token"
DEVICE_COOKIE = "oai-did"


@dataclass
class ImportError_(Exception):  # noqa: N818 - paired with a `reason` the UI switches on
    reason: str   # locked | app_bound | not_found | no_browser | decrypt_failed
    message: str

    def __str__(self) -> str:
        return self.message


# Chromium browsers and their User Data directories on Windows.
def _browsers() -> list[tuple[str, str]]:
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    out = []
    for name, path in (("Chrome", rf"{local}\Google\Chrome\User Data"),
                       ("Edge", rf"{local}\Microsoft\Edge\User Data"),
                       ("Brave", rf"{local}\BraveSoftware\Brave-Browser\User Data"),
                       ("Chrome Beta", rf"{local}\Google\Chrome Beta\User Data"),
                       ("Opera", rf"{roaming}\Opera Software\Opera Stable")):
        if path and os.path.isdir(path):
            out.append((name, path))
    return out


def _aes_key(user_data_dir: str) -> bytes:
    """The v10 AES key: DPAPI-decrypt os_crypt.encrypted_key from Local State (current user only)."""
    import win32crypt  # pywin32; present in the backend

    state = json.load(open(os.path.join(user_data_dir, "Local State"), encoding="utf-8"))
    blob = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if blob[:5] != b"DPAPI":
        raise ImportError_("decrypt_failed", "Unexpected key format in the browser profile")
    return win32crypt.CryptUnprotectData(blob[5:], None, None, None, 0)[1]


def _decrypt(enc: bytes, key: bytes) -> str:
    """Decrypt one cookie value. v10 = AES-256-GCM; v20 = app-bound (not supported from here)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if enc[:3] == b"v20":
        raise ImportError_("app_bound", "This browser encrypts cookies with app-bound encryption (v20). Paste the token instead.")
    if enc[:3] in (b"v10", b"v11"):
        nonce, body = enc[3:15], enc[15:]
        return AESGCM(key).decrypt(nonce, body, None).decode("utf-8", "replace")
    # very old cookies: DPAPI-encrypted directly
    import win32crypt

    return win32crypt.CryptUnprotectData(enc, None, None, None, 0)[1].decode("utf-8", "replace")


def _copy_locked(path: str) -> str:
    """Copy a (possibly WAL-backed) sqlite DB to a temp file; raise `locked` when the browser holds it."""
    dst = os.path.join(tempfile.gettempdir(), f"afh_ck_{uuid.uuid4().hex}.db")
    try:
        shutil.copy2(path, dst)
        for ext in ("-wal", "-shm"):
            if os.path.exists(path + ext):
                shutil.copy2(path + ext, dst + ext)
    except PermissionError as exc:  # WinError 32 — the browser is open
        raise ImportError_("locked", "Close the browser once so AFH can read its login, then try again — or paste the token.") from exc
    return dst


def _cleanup(dst: str) -> None:
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(dst + ext)
        except OSError:
            pass


def read_browser_session(browser: str | None = None) -> dict:
    """Return {session_token, device_id, source} from the first browser/profile that has a ChatGPT login.

    Raises ImportError_ with a reason the UI can act on (locked / app_bound / not_found / no_browser)."""
    browsers = [b for b in _browsers() if browser is None or b[0].lower() == browser.lower()]
    if not browsers:
        raise ImportError_("no_browser", "No supported browser found. Paste the token instead.")
    saw_locked = saw_app_bound = False
    for name, ud in browsers:
        try:
            key = _aes_key(ud)
        except ImportError_:
            continue
        except Exception:
            continue
        for db in glob.glob(os.path.join(ud, "*", "Network", "Cookies")) + glob.glob(os.path.join(ud, "Network", "Cookies")):
            try:
                tmp = _copy_locked(db)
            except ImportError_ as exc:
                saw_locked = saw_locked or exc.reason == "locked"
                continue
            try:
                con = sqlite3.connect(tmp)
                rows = {r[0]: r[1] for r in con.execute(
                    "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%chatgpt.com%' AND (name = ? OR name LIKE ? OR name = ?)",
                    (SESSION_COOKIE, SESSION_COOKIE + ".%", DEVICE_COOKIE))}
                con.close()
            except sqlite3.Error:
                continue
            finally:
                _cleanup(tmp)
            # the session cookie may be split into .0, .1, … chunks (each separately encrypted)
            if SESSION_COOKIE in rows:
                chunks = [rows[SESSION_COOKIE]]
            else:
                names = sorted((n for n in rows if n.startswith(SESSION_COOKIE + ".")),
                               key=lambda n: int(n.rsplit(".", 1)[1]) if n.rsplit(".", 1)[1].isdigit() else 0)
                chunks = [rows[n] for n in names]
            if not chunks:
                continue
            try:
                token = "".join(_decrypt(c, key) for c in chunks)
                device = _decrypt(rows[DEVICE_COOKIE], key) if rows.get(DEVICE_COOKIE) else ""
            except ImportError_ as exc:
                saw_app_bound = saw_app_bound or exc.reason == "app_bound"
                continue
            if token and len(token) > 20:
                prof = os.path.relpath(os.path.dirname(os.path.dirname(db)), ud)
                return {"session_token": token, "device_id": device or "", "source": f"{name} ({prof})"}
    if saw_locked:
        raise ImportError_("locked", "Your browser is open, so AFH can't read its login. Close it once and retry, or paste the token.")
    if saw_app_bound:
        raise ImportError_("app_bound", "Your browser encrypts cookies with app-bound encryption, which AFH won't bypass. "
                           "Paste instead: open chatgpt.com/api/auth/session in your browser, copy the JSON, and paste it here.")
    raise ImportError_("not_found", "No ChatGPT login found in your browser. Sign in to chatgpt.com first, or paste the token.")


def parse_paste(text: str) -> dict:
    """Accept a raw session token, a session-export JSON, or an /api/auth/session reply.
    Returns {session_token?, access?, expires?, device_id?, ua?} — at least one of session_token/access."""
    text = (text or "").strip()
    if not text:
        raise ImportError_("not_found", "Paste your ChatGPT session token (or a session export).")
    if text[:1] in "{[":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ImportError_("not_found", "That doesn't look like a valid token or JSON export.") from exc
        if isinstance(data, list):
            data = next((d for d in data if isinstance(d, dict)), {})
        if not isinstance(data, dict):
            raise ImportError_("not_found", "That JSON doesn't contain a session.")
        session = _first(data, "session_token", "sessionToken", "token", "__Secure-next-auth.session-token", "value")
        access = _first(data, "accessToken", "access_token", "access")
        out: dict = {}
        if session and len(str(session)) > 20:
            out["session_token"] = str(session)
        if access and len(str(access)) > 20:
            out["access"] = str(access)
            out["expires"] = _first(data, "expires", "expiresAt", "expire")
        if not out:
            raise ImportError_("not_found", "That JSON has no session token or access token.")
        dev = _first(data, "device_id", "deviceId", "oai-did", "oai_device_id")
        if dev:
            out["device_id"] = str(dev)
        ua = _first(data, "user_agent", "userAgent", "ua")
        if ua:
            out["ua"] = str(ua)
        return out
    # a bare token string
    if len(text) < 20 or " " in text or "\n" in text:
        raise ImportError_("not_found", "That doesn't look like a session token.")
    return {"session_token": text}


def _first(data: dict, *keys: str):
    for k in keys:
        if data.get(k):
            return data[k]
    return None
