"""Launch AFH: the API server with the AFH Engine, and the desktop window.

    python run.py            desktop window
    python run.py --browser  open in your default browser instead
    python run.py --headless only print the URL (for development / Electron)
    python run.py cli ...    the afh command (see afh/cli.py)
"""

from __future__ import annotations

import sys

if __name__ == "__main__" and sys.argv[1:2] == ["cli"]:  # before the imports below: they start the engine
    from afh import cli

    sys.exit(cli.main(sys.argv[2:]))

import argparse
import asyncio
import logging
import os
import secrets
import socket
import threading
import time
import webbrowser

import uvicorn

from afh import __version__, api, devapi, store
from afh.engine.core import engine


class WindowApi:
    """Native dialogs exposed to the page as window.pywebview.api.*"""

    def __init__(self) -> None:
        self._window = None  # private on purpose: pywebview exposes every public attribute

    def pick_folder(self):
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def pick_files(self):
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return list(result or [])


def free_port(preferred: int = 0) -> int:
    """`preferred` when it is free (Settings → Developer → fixed port), otherwise any free port."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
        except OSError:
            s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def log_to_file() -> None:
    """Keep a rotating log in ~/.afh/logs (the bug report includes the end of it)."""
    from logging.handlers import RotatingFileHandler

    folder = store.AFH_DIR / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "afh-backend.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Flow Harness")
    parser.add_argument("--browser", action="store_true", help="open in the default browser instead of a window")
    parser.add_argument("--headless", action="store_true", help="only print the URL (for development)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    store.AFH_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stderr is None:  # pythonw.exe has no console; keep a log file instead
        sys.stdout = sys.stderr = open(store.AFH_DIR / "afh.log", "w", encoding="utf-8", buffering=1)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(name)s: %(message)s")
    for_cli = os.environ.get("AFH_CLI_BACKEND") == "1"  # a private backend for one afh command
    if not for_cli:
        log_to_file()
    logging.getLogger("afh").info("AFH %s starting", __version__)

    try:
        fixed = int((store.load_settings().get("developer") or {}).get("port") or 0)
    except (TypeError, ValueError):
        fixed = 0
    port = args.port or free_port(fixed)
    token = secrets.token_urlsafe(24)
    api.ACCESS["token"] = token
    api.ACCESS["hosts"] = {f"127.0.0.1:{port}", f"localhost:{port}"}
    api.ACCESS["port"] = port

    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning"))
    serving = threading.Thread(target=server.run, daemon=True, name="afh-server")
    serving.start()
    while not server.started:
        if not serving.is_alive():
            sys.exit(f"AFH couldn't listen on port {port}; try --port with another number.")
        time.sleep(0.05)
    engine.ready.wait(timeout=30)
    if not for_cli:
        devapi.write_discovery(port, __version__)
        try:  # resume remote control if it was left on
            from afh import remote

            remote.apply(remote.settings())
        except Exception as exc:
            logging.getLogger("afh").warning("remote control not started: %s", exc)
        try:  # reconnect to the AFH account for the phone apps if it was left on
            from afh import cloud

            cloud.start()
        except Exception as exc:
            logging.getLogger("afh").warning("AFH account connection not started: %s", exc)

    url = f"http://127.0.0.1:{port}/#token={token}"
    try:
        if args.browser or args.headless:
            raise ImportError
        import webview

        bridge = WindowApi()
        bridge._window = webview.create_window("Agent Flow Harness", url, js_api=bridge, width=1320, height=860, min_size=(860, 560), background_color="#0f0d0c")
        webview.start(debug=args.debug)
    except ImportError:
        print(f"AFH is running at {url}", flush=True)
        if not args.headless:
            webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        if engine.loop:
            try:
                asyncio.run_coroutine_threadsafe(engine.stop(), engine.loop).result(timeout=5)
            except Exception:
                pass
        server.should_exit = True
        devapi.clear_discovery()
    sys.exit(0)


if __name__ == "__main__":
    main()
