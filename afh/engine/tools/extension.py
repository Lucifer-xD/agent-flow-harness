"""Setting up the AFH browser extension's link: Chrome's native messaging host and the extension folder.

The extension (extension/ in the repo, resources/extension in the app) has a fixed id, from the public
key in its manifest. Chrome only lets it start a native host that names that id. AFH writes the host's
manifest to ~/.afh/browser-extension-host/ and points Chrome, Edge, Brave and Chromium at it (the
registry under HKEY_CURRENT_USER on Windows; NativeMessagingHosts folders on macOS and Linux). The host
program is AFH's own backend (see afh/nativehost.py). The extension folder is copied to
~/.afh/browser-extension, so "Load unpacked" points at a path that survives updates and reinstalls.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

from afh import store

log = logging.getLogger("afh.extension")
HOST = "com.agentflowharness.bridge"
EXTENSION_ID = "cegedokahdmoaobkflhgaommndgpomio"  # from the "key" in extension/manifest.json
REG_KEYS = (r"Software\Google\Chrome\NativeMessagingHosts", r"Software\Microsoft\Edge\NativeMessagingHosts",
            r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts", r"Software\Chromium\NativeMessagingHosts")


def source_folder() -> Path | None:
    """The extension as shipped: resources/extension next to the app's backend, or extension/ in the repo."""
    here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    for p in (here.parent / "extension", here / "extension", here.parent.parent / "extension"):
        if (p / "manifest.json").is_file():
            return p
    return None


def folder() -> Path:
    """Where the user loads the extension from (Load unpacked)."""
    return store.AFH_DIR / "browser-extension"


def version_of(path: Path) -> str:
    try:
        return str(json.loads((path / "manifest.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def copy_extension() -> Path | None:
    src = source_folder()
    if src is None:
        return None
    dest = folder()
    if all((dest / f.relative_to(src)).is_file() and (dest / f.relative_to(src)).read_bytes() == f.read_bytes() for f in src.rglob("*") if f.is_file()):
        return dest
    tmp = dest.with_name(dest.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.replace(dest)
    log.info("browser extension %s copied to %s", version_of(dest), dest)
    return dest


def host_program() -> str:
    """What Chrome runs: the frozen backend itself, or (from source) a small script that runs run.py."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    run_py = Path(__file__).resolve().parents[3] / "run.py"
    base = store.AFH_DIR / "browser-extension-host"
    base.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        script = base / "afh-host.bat"
        script.write_text(f'@echo off\r\n"{sys.executable}" "{run_py}" %*\r\n', encoding="utf-8")
    else:
        script = base / "afh-host.sh"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{run_py}" "$@"\n', encoding="utf-8")
        script.chmod(0o755)
    return str(script)


def host_manifest() -> dict:
    return {"name": HOST, "description": "Agent Flow Harness: lets the AFH extension reach the AFH app", "path": host_program(),
            "type": "stdio", "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"]}


def _mac_linux_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        return [base / p / "NativeMessagingHosts" for p in ("Google/Chrome", "Microsoft Edge", "BraveSoftware/Brave-Browser", "Chromium")]
    base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return [base / p / "NativeMessagingHosts" for p in ("google-chrome", "microsoft-edge", "BraveSoftware/Brave-Browser", "chromium")]


def register() -> dict:
    """Make sure every browser can start AFH's host, and the extension folder is current. Safe to repeat."""
    manifest = host_manifest()
    text = json.dumps(manifest, indent=2)
    done = []
    if sys.platform == "win32":
        import winreg

        path = store.AFH_DIR / "browser-extension-host" / f"{HOST}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        for key in REG_KEYS:
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST}") as k:
                    if _reg_default(winreg, k) != str(path):
                        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(path))
                done.append(key.split("\\")[1])
            except OSError as err:
                log.warning("couldn't register the extension host under %s: %s", key, err)
    else:
        for d in _mac_linux_dirs():
            if not d.parent.is_dir():
                continue  # that browser isn't installed
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{HOST}.json").write_text(text, encoding="utf-8")
            done.append(str(d.parent.name))
    ext = None
    try:
        ext = copy_extension()
    except OSError as err:
        log.warning("couldn't copy the browser extension: %s", err)
    return {"host": manifest["path"], "browsers": done, "folder": str(ext) if ext else ""}


def _reg_default(winreg, key) -> str:
    try:
        return str(winreg.QueryValueEx(key, "")[0])
    except OSError:
        return ""
