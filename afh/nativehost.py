"""The helper Chrome (or Edge, Brave) starts for the AFH browser extension: Chrome's "native messaging".

Chrome runs this program (AFH's own backend executable, which sees the extension's origin
``chrome-extension://<id>/`` as its first argument) and talks to it over stdin/stdout: each message is
a 4-byte little-endian length and then that much UTF-8 JSON. This helper finds the running AFH app
through ``~/.afh/api.json`` (address and the key only this user can read), opens a websocket to
``/api/extension/host`` and relays messages both ways, unchanged. When AFH isn't open it waits and
connects as soon as it is; it tells the extension which ({"afh": "connected" | "waiting"}).

Nothing goes to stdout but protocol frames: Chrome would read anything else as a broken message.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import sys
import threading
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger("afh.nativehost")
RETRY = 3.0  # seconds between looks for the AFH app while it isn't open
MAX_TO_CHROME = 1024 * 1024  # Chrome's limit for one message from a native host


def afh_home() -> Path:
    return Path(os.environ.get("AFH_HOME") or Path.home() / ".afh")


def read_frame(stream: BinaryIO) -> dict | None:
    """One message from Chrome, or None when Chrome closed the pipe."""
    head = stream.read(4)
    if len(head) < 4:
        return None
    (size,) = struct.unpack("<I", head)
    body = b""
    while len(body) < size:
        part = stream.read(size - len(body))
        if not part:
            return None
        body += part
    return json.loads(body.decode("utf-8"))


def write_frame(stream: BinaryIO, msg: dict, lock: threading.Lock) -> None:
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_TO_CHROME:  # only AFH's commands go this way, and they are small; never send a broken one
        log.warning("dropped a message to the extension of %d bytes", len(data))
        if "id" in msg:
            data = json.dumps({"id": msg["id"], "error": {"message": "message too large"}}).encode("utf-8")
        else:
            return
    with lock:
        stream.write(struct.pack("<I", len(data)) + data)
        stream.flush()


def find_afh() -> tuple[str, str] | None:
    """(websocket URL, key) of the running AFH app, or None when it isn't open."""
    try:
        info = json.loads((afh_home() / "api.json").read_text(encoding="utf-8"))
        url, key = str(info.get("url") or ""), str(info.get("key") or "")
    except (OSError, ValueError):
        return None
    if not url.startswith("http://127.0.0.1:") or not key:
        return None
    return "ws://" + url[len("http://"):].rstrip("/") + "/api/extension/host", key


class Relay:
    """Chrome's pipe on one side, the AFH app's websocket on the other."""

    def __init__(self, stdin: BinaryIO, stdout: BinaryIO):
        self.stdin, self.stdout = stdin, stdout
        self.out_lock = threading.Lock()
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.hello: dict | None = None
        self.ws = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def _read_chrome(self) -> None:  # a thread: stdin blocks
        while True:
            try:
                msg = read_frame(self.stdin)
            except Exception as err:
                log.info("chrome pipe: %s", err)
                msg = None
            self.loop.call_soon_threadsafe(self.inbox.put_nowait, msg)
            if msg is None:
                return

    def to_chrome(self, msg: dict) -> None:
        write_frame(self.stdout, msg, self.out_lock)

    async def run(self, find=find_afh) -> None:
        import websockets

        self.loop = asyncio.get_running_loop()
        threading.Thread(target=self._read_chrome, daemon=True, name="chrome-pipe").start()
        pump = asyncio.create_task(self._from_chrome())
        said = ""
        try:
            while not pump.done():
                where = find()
                if where:
                    try:
                        async with websockets.connect(where[0], additional_headers={"x-afh-token": where[1]}, max_size=None,
                                                      ping_interval=20, open_timeout=10) as ws:
                            self.ws = ws
                            if self.hello is not None:
                                await ws.send(json.dumps(self.hello))
                            self.to_chrome({"afh": "connected"})
                            said = "connected"
                            async for raw in ws:
                                self.to_chrome(json.loads(raw))
                    except Exception as err:  # not running after all, refused, or it quit
                        log.info("afh: %s", err)
                    finally:
                        self.ws = None
                if said != "waiting":
                    self.to_chrome({"afh": "waiting"})
                    said = "waiting"
                done, _ = await asyncio.wait({pump}, timeout=RETRY)
        finally:
            pump.cancel()

    async def _from_chrome(self) -> None:
        while True:
            msg = await self.inbox.get()
            if msg is None:  # Chrome closed the extension (or itself): we are done
                if self.ws is not None:
                    await self.ws.close()
                return
            if isinstance(msg, dict) and "hello" in msg:
                self.hello = msg
            if self.ws is not None:
                try:
                    await self.ws.send(json.dumps(msg))
                except Exception:
                    pass  # AFH just went away: the command is lost, as the tab state is
            elif isinstance(msg, dict) and msg.get("id") is not None and "method" not in msg:
                pass  # a reply for an AFH that is gone
            elif isinstance(msg, dict) and msg.get("id") is not None:
                self.to_chrome({"id": msg["id"], "error": {"message": "AFH isn't open"}})


def _std_streams() -> tuple[BinaryIO, BinaryIO]:
    stdin = sys.stdin.buffer if sys.stdin is not None else os.fdopen(0, "rb", buffering=0)
    stdout = sys.stdout.buffer if sys.stdout is not None else os.fdopen(1, "wb", buffering=0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(stdout.fileno(), os.O_BINARY)
    return stdin, stdout


def main() -> int:
    try:
        afh_home().mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=str(afh_home() / "extension-host.log"), level=logging.INFO, format="%(asctime)s %(message)s")
    except OSError:
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    stdin, stdout = _std_streams()
    sys.stdout = sys.stderr  # a stray print must never reach Chrome's pipe
    log.info("started for %s", " ".join(sys.argv[1:2]))
    try:
        asyncio.run(Relay(stdin, stdout).run())
    except KeyboardInterrupt:
        pass
    log.info("stopped")
    return 0


def is_native_launch(argv: list[str]) -> bool:
    """Chrome starts a native host with the caller's origin as its first argument."""
    return any(a.startswith("chrome-extension://") for a in argv[1:3])
