"""Owns the `opencode serve` process, the SDK client, and the event fan-out."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any

from opencode import OpencodeServer

from . import store

log = logging.getLogger("afh.engine")

# Events the UI never needs; dropping them keeps the stream light.
IGNORED_EVENTS = {"mcp.resources.changed", "session.step.streamed", "session.viewed"}


def dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(obj, (list, tuple)):
        return [dump(o) for o in obj]
    return obj


class Engine:
    def __init__(self) -> None:
        self._server: OpencodeServer | None = None
        self.client = None
        self._generation = 0
        self._lock = threading.RLock()
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self.ready = threading.Event()
        self.error: str | None = None

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self.ready.clear()
            self.error = None
            try:
                server = OpencodeServer(cwd=str(Path.home()), config=store.server_config(), startup_timeout=60)
                server.__enter__()
                self._server = server
                self.client = server.client()
            except Exception as exc:  # surfaced to the UI by /api/bootstrap
                log.exception("opencode failed to start")
                self.error = str(exc)
                self.publish({"type": "afh.error", "data": {"message": self.error}})
                return
            self._generation += 1
            threading.Thread(target=self._pump, args=(self._generation,), daemon=True).start()
            self.ready.set()
        self.publish({"type": "afh.ready", "data": {}})

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self.ready.clear()
            client, server = self.client, self._server
            self.client = self._server = None
        for closer in (lambda: client and client.close(), lambda: server and server.__exit__(None, None, None)):
            try:
                closer()
            except Exception:
                log.debug("shutdown error", exc_info=True)

    def restart(self) -> None:
        self.publish({"type": "afh.restarting", "data": {}})
        self.stop()
        self.start()

    def require(self):
        if not self.ready.wait(timeout=90) or self.client is None:
            raise RuntimeError(self.error or "OpenCode is not running")
        return self.client

    # ---- events ----------------------------------------------------------

    def _pump(self, generation: int) -> None:
        while generation == self._generation:
            client = self.client
            if client is None:
                return
            try:
                with client.event.subscribe() as stream:
                    for event in stream:
                        if generation != self._generation:
                            return
                        data = dump(event)
                        if data.get("type") not in IGNORED_EVENTS:
                            self.publish(data)
            except Exception:
                if generation != self._generation:
                    return
                log.debug("event stream dropped; reconnecting", exc_info=True)
                time.sleep(1.0)

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._subscribers.add((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers = {s for s in self._subscribers if s[1] is not queue}

    def publish(self, event: dict) -> None:
        for loop, queue in list(self._subscribers):
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except RuntimeError:  # loop closed
                self._subscribers.discard((loop, queue))


def _offer(queue: asyncio.Queue, event: dict) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


engine = Engine()
