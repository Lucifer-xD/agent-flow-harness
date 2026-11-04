"""Read a ChatGPT web session the user pasted in: a session token, a session-export JSON, or the
``/api/auth/session`` reply.

Nothing here contacts the network; validating the session is done by the caller via auth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ImportError_(Exception):  # noqa: N818 - paired with a `reason` the UI shows
    reason: str
    message: str

    def __str__(self) -> str:
        return self.message


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
