"""Standalone installs update themselves: new version next to the old one, then the launcher moves over."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .. import __version__
from ..cli import HOME, CliError

SITE = "https://agentflowharness.com"
RELEASES = "https://github.com/Lucifer-xD/agent-flow-harness/releases"
ROOT = HOME / "cli"
CHECK_EVERY = 24 * 3600


def standalone() -> bool:
    """True when this copy of afh is the one the install command put in ~/.afh/cli."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        Path(sys.executable).resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def newer(a: str, b: str) -> bool:
    def parts(v: str) -> tuple:
        return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))

    return parts(a) > parts(b)


def fetch(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"afh/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest() -> dict:
    return json.loads(fetch(f"{SITE}/cli.json"))


def asset_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "afh-windows-x64.zip"
    if sys.platform == "darwin":
        return "afh-macos-arm64.tar.gz" if machine in ("arm64", "aarch64") else "afh-macos-x64.tar.gz"
    return "afh-linux-x64.tar.gz"


def shim_path() -> Path:
    return HOME / "bin" / ("afh.cmd" if os.name == "nt" else "afh")


def write_shim(exe: Path) -> None:
    path = shim_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path.write_text(f'@echo off\r\n"{exe}" %*\r\n', encoding="utf-8")
    else:
        path.write_text(f'#!/bin/sh\nexec "{exe}" "$@"\n', encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def unpack(archive: Path, dest: Path) -> None:
    root = dest.resolve()

    def safe(name: str) -> None:
        if not (root / name).resolve().is_relative_to(root):
            raise CliError(f"The download has a bad path in it: {name}")

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                safe(name)
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            for name in t.getnames():
                safe(name)
            t.extractall(dest, filter="tar")


def install_version(info: dict, say: Any = print) -> Path:
    """Download, check, unpack, and move the launcher. Returns the new executable."""
    version = info["version"]
    name = asset_name()
    want = (info.get("sha256") or {}).get(name)
    if not want:
        raise CliError(f"The update has no checksum for {name}")
    say(f"Downloading AFH {version}…")
    with tempfile.TemporaryDirectory(prefix="afh-update-") as tmp:
        archive = Path(tmp) / name
        data = fetch(f"{RELEASES}/download/v{version}/{name}", 600)
        if hashlib.sha256(data).hexdigest() != want:
            raise CliError("The download didn't match its checksum, so nothing was changed")
        archive.write_bytes(data)
        target = ROOT / "versions" / version
        staging = ROOT / "versions" / f".{version}-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        unpack(archive, staging)
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    exe = target / "afh" / ("afh.exe" if os.name == "nt" else "afh")
    if os.name != "nt":
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    write_shim(exe)
    prune(version)
    return exe


def prune(keep: str) -> None:
    """Old versions go once nothing runs from them. Windows refuses while one is open, which is fine."""
    versions = ROOT / "versions"
    mine = Path(sys.executable).resolve()
    for folder in versions.iterdir() if versions.is_dir() else []:
        if folder.name != keep and not mine.is_relative_to(folder.resolve()):
            shutil.rmtree(folder, ignore_errors=True)


def check_due() -> bool:
    mark = HOME / "cli-update-check"
    try:
        if time.time() - mark.stat().st_mtime < CHECK_EVERY:
            return False
    except OSError:
        pass
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()
    except OSError:
        pass
    return True


async def notice(ui: Any) -> None:
    """Once a day: a word in the status bar if there is something newer. Nothing is installed."""
    if os.environ.get("AFH_NO_UPDATE_CHECK") or ui.is_headless or not check_due():
        return
    try:
        info = await asyncio.to_thread(latest)
    except (OSError, ValueError):
        return
    if newer(str(info.get("version") or "0"), __version__):
        ui.update_notice = f"{info['version']} is out: /update"
        ui.draw_status()


async def run(ui: Any) -> None:
    """/update in the app."""
    try:
        info = await asyncio.to_thread(latest)
    except (OSError, ValueError) as err:
        ui.fail(f"Couldn't reach the update server: {err}")
        return
    version = str(info.get("version") or "")
    if not newer(version, __version__):
        ui.say(f"You're on the newest version, {__version__}", 4)
        return
    if not standalone():
        ui.say(f"AFH {version} is out. The desktop app updates by itself; from source, pull the repository.", 8)
        return
    try:
        await asyncio.to_thread(install_version, info, lambda text: None)
        ui.update_notice = ""
        ui.draw_status()
        ui.say(f"AFH {version} installed. It starts next time you run afh.", 8)
    except (CliError, OSError, ValueError) as err:
        ui.fail(err)


def cmd_update(_: Any = None) -> int:
    """afh update."""
    info = latest()
    version = str(info.get("version") or "")
    if not newer(version, __version__):
        print(f"You're on the newest version, {__version__}.")
        return 0
    if not standalone():
        print(f"AFH {version} is out. The desktop app updates by itself; from source, pull the repository.")
        return 0
    install_version(info)
    print(f"AFH {version} is installed.")
    return 0


def remove_from_path() -> None:
    folder = str(HOME / "bin")
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                value, kind = winreg.QueryValueEx(key, "Path")
            except OSError:
                return
            kept = [p for p in value.split(";") if p and p.rstrip("\\").lower() != folder.lower()]
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(kept))
        return
    for name in (".profile", ".bashrc", ".zshrc", ".bash_profile", ".zprofile"):
        path = Path.home() / name
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            kept = [x for x in lines if ".afh/bin" not in x and "added by AFH" not in x]
            if len(kept) != len(lines):
                path.write_text("".join(kept), encoding="utf-8")


def cmd_uninstall(_: Any = None) -> int:
    """afh uninstall: the program goes, your threads, settings and keys stay in ~/.afh."""
    remove_from_path()
    if os.name == "nt":
        # Neither the running program nor the afh.cmd that started it can go yet, so a small helper finishes after we exit.
        subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & del /q "{shim_path()}" & rmdir /s /q "{ROOT}"', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        shim_path().unlink(missing_ok=True)
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"AFH's terminal app is removed. Your threads, settings and keys are still in {HOME}.")
    return 0
