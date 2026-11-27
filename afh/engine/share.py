"""Share a provider: everything about it in one code that another AFH applies with one click.

A share code carries the provider's whole entry from providers.json: its name, address, headers,
setup fields, model list, the names, context sizes, effort levels and inputs set in Settings, the
hidden models, prices, and (unless the sharer turns them off) every account with its key or sign-in.
The logo needs nothing of its own: AFH draws it from the provider's id, name, address and models.

    AFH-PROVIDER-1:<base64url(zlib(json))>              a plain code
    AFH-PROVIDER-1L:<base64url(salt|nonce|tag|data)>   locked with a password

A locked code uses only the standard library, so the terminal app on any system can open it:
scrypt turns the password into two keys, HMAC-SHA256 in counter mode encrypts and a separate
HMAC-SHA256 over the salt, nonce and ciphertext proves the password and that nothing was changed.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
import zlib
from typing import Any
from urllib.parse import urlparse

from .. import __version__
from . import config as provcfg

FORMAT = "afh-provider"
VERSION = 1
PLAIN = "AFH-PROVIDER-1:"
LOCKED = "AFH-PROVIDER-1L:"
MAX_CODE = 4_000_000  # characters; a provider with hundreds of models is well under 100 KB

# Fields of a providers.json entry that are about this computer, not the provider.
LOCAL_ONLY = ("enabled",)
SECRET_FIELDS = ("api_key", "auth", "accounts", "active")
SECRET_HEADER = re.compile(r"auth|key|token|secret|cookie|session|password", re.I)
IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class NeedsPassword(ValueError):
    """The code is locked and no password (or the wrong one) was given."""


# ---- making a code ------------------------------------------------------------------------------


def bundle(pid: str, include_secrets: bool = True, default_model: dict | None = None) -> dict:
    """The provider as a share bundle (a plain dict; ``encode`` turns it into a code)."""
    p = provcfg.entry(pid)
    if not p:
        raise KeyError(pid)
    entry = {k: copy.deepcopy(v) for k, v in p.items() if k not in LOCAL_ONLY}
    entry["id"] = pid
    if not include_secrets:
        for k in SECRET_FIELDS:
            entry.pop(k, None)
        entry["headers"] = {k: v for k, v in (entry.get("headers") or {}).items() if not SECRET_HEADER.search(str(k))}
    out: dict[str, Any] = {"format": FORMAT, "version": VERSION, "app": __version__, "made": int(time.time()), "secrets": bool(include_secrets), "provider": entry}
    if default_model and default_model.get("providerID") == pid and default_model.get("id"):
        out["defaultModel"] = {k: default_model[k] for k in ("id", "variant") if default_model.get(k)}
    return out


def encode(data: dict, password: str = "") -> str:
    raw = zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    if not password:
        return PLAIN + _b64(raw)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    enc_key, mac_key = _keys(password, salt)
    body = _xor(raw, _stream(enc_key, nonce, len(raw)))
    tag = hmac.new(mac_key, salt + nonce + body, hashlib.sha256).digest()
    return LOCKED + _b64(salt + nonce + tag + body)


def export(pid: str, include_secrets: bool = True, password: str = "", default_model: dict | None = None) -> dict:
    data = bundle(pid, include_secrets, default_model)
    code = encode(data, password)
    return {"code": code, "chars": len(code), "locked": bool(password), "secrets": data["secrets"], **_summary(data["provider"])}


# ---- reading a code -----------------------------------------------------------------------------


def _candidates(code: str) -> list[str]:
    """The code inside pasted text, longest first. A chat app may break a long code over lines and
    put words before or after it; zlib's checksum (or the password check) tells which length is it."""
    text = str(code or "")
    if len(text) > MAX_CODE:
        raise ValueError("That share code is too long")
    lines = text.splitlines()
    for n, line in enumerate(lines):
        m = re.search(r"AFH-PROVIDER-1L?:[A-Za-z0-9_\-=]*", line.replace(" ", "") if line.strip().startswith("AFH-PROVIDER") else line)
        if not m:
            continue
        pieces = [m.group(0)]
        for more in lines[n + 1:]:
            more = more.strip()
            if not more or not re.fullmatch(r"[A-Za-z0-9_\-=]+", more):
                break
            pieces.append(more)
        return ["".join(pieces[:k]) for k in range(len(pieces), 0, -1)]
    raise ValueError("That isn't an AFH provider share code. It starts with AFH-PROVIDER-1.")


def decode(code: str, password: str = "") -> dict:
    """The bundle inside a code. ValueError when it is not one; NeedsPassword when it is locked."""
    first: Exception | None = None
    for text in _candidates(code):
        try:
            return _decode_one(text, password)
        except NeedsPassword as err:
            if not password:
                raise
            first = first or err
        except ValueError as err:
            first = first if isinstance(first, NeedsPassword) else (first or err)
    raise first or ValueError("That isn't an AFH provider share code")


def _decode_one(text: str, password: str) -> dict:
    locked = text.startswith(LOCKED)
    try:
        raw = _unb64(text[len(LOCKED if locked else PLAIN):])
    except (ValueError, TypeError):
        raise ValueError("The share code is incomplete. Copy all of it and try again.") from None
    if locked:
        if not password:
            raise NeedsPassword("This share code is locked with a password")
        if len(raw) < 64:
            raise ValueError("The share code is incomplete. Copy all of it and try again.")
        salt, nonce, tag, body = raw[:16], raw[16:32], raw[32:64], raw[64:]
        enc_key, mac_key = _keys(password, salt)
        if not hmac.compare_digest(tag, hmac.new(mac_key, salt + nonce + body, hashlib.sha256).digest()):
            raise NeedsPassword("Wrong password, or the code was changed")
        raw = _xor(body, _stream(enc_key, nonce, len(body)))
    try:
        data = json.loads(zlib.decompress(raw).decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, ValueError):
        raise ValueError("The share code is incomplete. Copy all of it and try again.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("provider"), dict):
        raise ValueError("That isn't an AFH provider share code")
    if int(data.get("version") or 0) > VERSION:
        raise ValueError("This share code comes from a newer AFH. Update AFH to apply it.")
    p = data["provider"]
    if not IDENT.match(str(p.get("id") or "")):
        raise ValueError("The shared provider has no usable id")
    if p.get("base_url") and not str(p["base_url"]).startswith(("http://", "https://")):
        raise ValueError("The shared provider's address isn't a web address")
    return data


def preview(code: str, password: str = "") -> dict:
    """What applying the code would do, for the dialog. Never returns a key or token."""
    try:
        data = decode(code, password)
    except NeedsPassword as err:
        return {"needsPassword": True, "wrongPassword": bool(password), "error": str(err)}
    p = data["provider"]
    pid = p["id"]
    mine = provcfg.entry(pid)
    accs = [{"label": provcfg.account_label(a), "kind": _kind(a)} for a in p.get("accounts") or []]
    sign_ins = [a for a in accs if a["kind"] == "signin"]
    default = data.get("defaultModel") or None
    out = {
        "needsPassword": False, "id": pid, "name": p.get("name") or pid, "kind": p.get("kind") or "openai", "catalog": p.get("catalog"),
        "base_url": p.get("base_url") or "", "secrets": bool(data.get("secrets")), "accounts": accs, "app": data.get("app") or "",
        "made": data.get("made"), "exists": mine is not None, "existingName": (mine or {}).get("name") or "", "copyId": _free_id(pid) if mine else pid,
        "defaultModel": default, "local": _local_host(p.get("base_url") or ""),
        "signInNote": "Sign-ins are shared as they are. Some services end the older copy when the other one renews its sign-in, so one of you may have to sign in again."
        if sign_ins else "",
        "models": _models_view(p),
        **_summary(p),
    }
    return out


def apply(code: str, password: str = "", mode: str = "replace") -> dict:
    """Add the shared provider. With one of the same id already here:
    ``replace`` puts the shared one in its place, ``accounts`` adds only its accounts to yours,
    ``copy`` keeps both (the shared one under a new id)."""
    data = decode(code, password)
    p = copy.deepcopy(data["provider"])
    pid = p["id"]
    mine = provcfg.entry(pid)
    if mine is not None and mode == "accounts":
        added = 0
        for acc in p.get("accounts") or []:
            creds = {k: acc[k] for k in provcfg.CREDS if acc.get(k)}
            if creds:
                provcfg.add_account(pid, creds, label=str(acc.get("label") or ""))
                added += 1
        return {"providerID": pid, "mode": "accounts", "added": added, "name": mine.get("name") or pid}
    done = "new"
    if mine is not None and mode == "copy":
        p["name"] = f"{p.get('name') or pid} (shared)"
        p["id"] = pid = _free_id(pid)
        done = "copy"
    elif mine is not None and mode == "replace":
        done = "replace"
    elif mine is not None:
        raise ValueError(f"Unknown way to apply: {mode}")
    p["enabled"] = True
    for acc in p.get("accounts") or []:
        acc.setdefault("id", secrets.token_hex(4))
    provcfg.replace_entry(pid, p)
    return {"providerID": pid, "mode": done, "name": p.get("name") or pid, "added": len(p.get("accounts") or [])}


# ---- helpers ------------------------------------------------------------------------------------


def _summary(p: dict) -> dict:
    models = [m for m in provcfg.models_of(p, p.get("id"))] if p else []
    efforts = sum(1 for m in models if m.variants)
    return {"modelCount": len(models), "shownCount": sum(1 for m in models if not m.hidden), "effortModels": efforts,
            "accountCount": len(p.get("accounts") or []), "custom": sorted((p.get("overrides") or {}).keys())[:50]}


def _models_view(p: dict) -> list[dict]:
    """The models the picker would show, for the logo and the list in the dialog."""
    out = []
    for m in provcfg.models_of(p, p.get("id")):
        if not m.hidden:
            out.append({"id": m.id, "name": m.name, "variants": list(m.variants or [])})
    return out[:200]


def _kind(acc: dict) -> str:
    t = (acc.get("auth") or {}).get("type")
    return "signin" if t and t not in provcfg.KEY_SIGN_INS else "key"


def _free_id(pid: str) -> str:
    have = set(provcfg.load()["providers"])
    n = 2
    while f"{pid}-{n}"[:64] in have:
        n += 1
    return f"{pid}-{n}"[:64]


def _local_host(url: str) -> str:
    """The host when the address only works on the sharer's own computer or network, else ""."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return ""
    if host in ("localhost", "0.0.0.0") or host.endswith((".local", ".lan", ".home", ".internal", ".localhost")):
        return host
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    return host if (ip.is_private or ip.is_loopback or ip.is_link_local) else ""


def _keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
    k = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
    return k[:32], k[32:]


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:n])


def _xor(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big") if a else b""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    text = text.rstrip("=")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
