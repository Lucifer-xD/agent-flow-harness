"""Launch AFH: the API server, the OpenCode engine, and the desktop window.

    python run.py            desktop window
    python run.py --browser  open in your default browser instead
"""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from afh import api, store
from afh.engine import engine


class WindowApi:
    """Native dialogs exposed to the page as window.pywebview.api.*"""

    def __init__(self) -> None:
        # Private on purpose: pywebview exposes every public attribute to JavaScript.
        self._window = None

    def pick_folder(self):
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def pick_files(self):
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return list(result or [])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="AFH desktop coding agent")
    parser.add_argument("--browser", action="store_true", help="open in the default browser instead of a window")
    parser.add_argument("--headless", action="store_true", help="only print the URL (for development)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    store.AFH_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stderr is None:  # pythonw.exe has no console; keep a log file instead
        sys.stdout = sys.stderr = open(store.AFH_DIR / "afh.log", "w", encoding="utf-8", buffering=1)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(name)s: %(message)s")

    port = args.port or free_port()
    token = secrets.token_urlsafe(24)
    api.ACCESS["token"] = token
    api.ACCESS["hosts"] = {f"127.0.0.1:{port}", f"localhost:{port}"}

    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning"))
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    while not server.started:
        if not serving.is_alive():
            sys.exit(f"AFH couldn't listen on port {port}; try --port with another number.")
        time.sleep(0.05)
    threading.Thread(target=engine.start, daemon=True).start()
    try:  # resume remote control if it was left on
        from afh import remote

        remote.apply(remote.settings())
    except Exception as exc:
        logging.getLogger("afh").warning("remote control not started: %s", exc)

    url = f"http://127.0.0.1:{port}/#token={token}"
    try:
        if args.browser or args.headless:
            raise ImportError
        import webview

        bridge = WindowApi()
        bridge._window = webview.create_window(
            "AFH", url, js_api=bridge, width=1320, height=860, min_size=(860, 560), background_color="#0d0e12"
        )
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
        engine.stop()
        server.should_exit = True
    sys.exit(0)


if __name__ == "__main__":
    main()
