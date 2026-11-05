"""Bug reports: one zip with what's needed to understand a problem, and no secrets.

It holds your description, the app version and system, your settings with every key, token,
password and personal text removed, the providers you use (names and models, never keys), and
the end of the backend log with anything that looks like a key masked. It is saved to your
Downloads folder and sent nowhere: you choose whom to give it to.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__, store

SECRET_KEY = re.compile(r"key|token|secret|password|passwd|auth|cookie|credential", re.I)
PRIVATE = {"personalization"}  # what you wrote about yourself
SECRET_TEXT = [
    (re.compile(r"\bafh_[A-Za-z0-9_\-]{16,}"), "afh_•••"),
    (re.compile(r"\b(sk|pk|rk|gsk|xai|AIza)[-_][A-Za-z0-9_\-]{12,}"), r"\1-•••"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"), r"\1•••"),
    (re.compile(r"(?i)([?&](?:token|key|api_key)=)[^&\s\"']+"), r"\1•••"),
    (re.compile(r"(?i)(x-afh-token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._\-]+"), r"\1•••"),
]
LOG_TAIL = 1_500_000


def scrub(text: str) -> str:
    for pattern, repl in SECRET_TEXT:
        text = pattern.sub(repl, text)
    return text


def redact(value: Any, key: str = "") -> Any:
    if key in PRIVATE:
        return "(removed)"
    if isinstance(value, dict):
        return {k: ("•••" if SECRET_KEY.search(k) and isinstance(v, str) and v else redact(v, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return scrub(value)
    return value


def system_info() -> dict:
    from .engine.tools.browser import find_browsers

    info = {
        "app": __version__, "os": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)), "time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "browsers": [Path(b).name for b in find_browsers(store.load_settings())],
    }
    try:
        from .engine.core import engine

        info["engine"] = {"ready": engine.ready.is_set(), "error": engine.error, "running": len(getattr(engine, "runs", {}) or {})}
    except Exception as err:
        info["engine"] = {"error": f"unavailable: {err}"}
    return info


def providers_info() -> list[dict]:
    from .engine import config as provcfg

    out = []
    for pid, p in provcfg.load()["providers"].items():
        base = str(p.get("base_url") or "")
        out.append({"id": pid, "name": p.get("name") or pid, "kind": p.get("kind"), "host": re.sub(r"^\w+://([^/]+).*$", r"\1", base),
                    "hasKey": bool(p.get("api_key")), "models": len(p.get("models") or [])})
    return out


def log_tail(pattern: str = "afh-backend.log*") -> str:
    folder = store.AFH_DIR / "logs"
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime) if folder.is_dir() else []
    data = b""
    for f in reversed(files):  # newest first, until the budget is used
        try:
            data = f.read_bytes()[-(LOG_TAIL - len(data)):] + data
        except OSError:
            continue
        if len(data) >= LOG_TAIL:
            break
    return scrub(data.decode("utf-8", errors="replace"))


def problems(log: str) -> list[str]:
    """The warnings and errors in the log, newest last, for a quick look."""
    lines = [ln for ln in log.splitlines() if " ERROR " in ln or " WARNING " in ln or "Traceback" in ln]
    return lines[-60:]


def preview() -> dict:
    log = log_tail()
    return {"system": system_info(), "providers": providers_info(), "logBytes": len(log.encode()), "problems": problems(log)[-8:]}


def _target_folder() -> Path:
    downloads = Path.home() / "Downloads"
    folder = downloads if downloads.is_dir() else store.AFH_DIR / "bug-reports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def build(description: str, include_log: bool = True) -> Path:
    path = _target_folder() / f"AFH-bug-report-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    log = log_tail() if include_log else ""
    info = system_info()
    readme = "\n".join([
        "# Agent Flow Harness bug report", "",
        f"Version {info['app']} on {info['os']} · {info['time']}", "",
        "## What happened", "", description.strip() or "(no description)", "",
        "## Recent warnings and errors", "", "```", *(problems(log) or ["(none in the log)"]), "```", "",
        "Keys, tokens and passwords were removed before this file was made.",
    ])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", readme)
        z.writestr("system.json", json.dumps(info, indent=2, ensure_ascii=False, default=str))
        z.writestr("settings.json", json.dumps(redact(store.load_settings()), indent=2, ensure_ascii=False))
        z.writestr("providers.json", json.dumps(providers_info(), indent=2, ensure_ascii=False))
        if include_log:
            z.writestr("afh-backend.log", log)
            z.writestr("updates.log", log_tail("updates.log*"))
    return path
