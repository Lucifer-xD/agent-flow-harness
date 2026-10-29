"""Scheduled jobs: run a prompt in a project on a timetable (every N minutes, hourly, daily,
on weekdays or weekly) — e.g. "every morning, update dependencies and run the tests".

Each run is a new thread in the job's folder, so you can read what happened. Jobs live in
``~/.afh/schedules.json``. They run while AFH is open; a run that was due while it was closed
happens once, soon after AFH starts.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("afh.schedules")
EVERY = ("interval", "hourly", "daily", "weekdays", "weekly")
CHECK_SECONDS = 30
_lock = threading.Lock()


def _file() -> Path:
    from .. import store

    return store.AFH_DIR / "schedules.json"


def load() -> list[dict]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _now_ms() -> int:
    return int(dt.datetime.now().timestamp() * 1000)


def _hm(text: str) -> tuple[int, int]:
    try:
        h, m = (int(x) for x in str(text or "09:00").split(":")[:2])
        return max(0, min(23, h)), max(0, min(59, m))
    except ValueError:
        return 9, 0


def clean(job: dict, old: dict | None = None) -> dict:
    """Validate a job from the UI/API, keeping its run history."""
    old = old or {}
    every = job.get("every") if job.get("every") in EVERY else "daily"
    out = {
        "id": old.get("id") or job.get("id") or secrets.token_hex(5),
        "name": str(job.get("name") or "").strip()[:80] or "Scheduled job",
        "directory": str(job.get("directory") or "").strip(),
        "prompt": str(job.get("prompt") or "").strip(),
        "every": every,
        "minutes": max(5, min(24 * 60, int(job.get("minutes") or 60))),
        "time": "%02d:%02d" % _hm(job.get("time")),
        "weekday": max(0, min(6, int(job.get("weekday") or 0))),  # Monday = 0
        "model": job.get("model") or None,
        "agent": job.get("agent") or None,
        "mode": job.get("mode") if job.get("mode") in ("full", "build", "plan", "readonly", "ask") else "full",
        "enabled": job.get("enabled", True) is not False,
        "created": old.get("created") or _now_ms(),
        "lastRun": old.get("lastRun"),
        "lastSession": old.get("lastSession"),
        "lastStatus": old.get("lastStatus"),
    }
    if not out["prompt"]:
        raise ValueError("The job needs a prompt")
    if not out["directory"] or not Path(out["directory"]).is_dir():
        raise ValueError("The job needs an existing project folder")
    return out


def next_after(job: dict, after: dt.datetime) -> dt.datetime:
    """The first time this job is due strictly after `after` (local time)."""
    every = job.get("every", "daily")
    if every == "interval":
        return after + dt.timedelta(minutes=int(job.get("minutes") or 60))
    h, m = _hm(job.get("time"))
    if every == "hourly":
        t = after.replace(minute=m, second=0, microsecond=0)
        return t if t > after else t + dt.timedelta(hours=1)
    t = after.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= after:
        t += dt.timedelta(days=1)
    if every == "weekdays":
        while t.weekday() >= 5:
            t += dt.timedelta(days=1)
    elif every == "weekly":
        while t.weekday() != int(job.get("weekday") or 0):
            t += dt.timedelta(days=1)
    return t


def due(job: dict, now: dt.datetime) -> bool:
    if not job.get("enabled", True):
        return False
    since = dt.datetime.fromtimestamp((job.get("lastRun") or job.get("created") or _now_ms()) / 1000)
    return next_after(job, since) <= now


def with_next(job: dict) -> dict:
    since = dt.datetime.fromtimestamp((job.get("lastRun") or job.get("created") or _now_ms()) / 1000)
    nxt = next_after(job, since)
    now = dt.datetime.now()
    if nxt < now:
        nxt = now
    return {**job, "nextRun": int(nxt.timestamp() * 1000) if job.get("enabled", True) else None}


# ---- CRUD ----


def list_jobs() -> list[dict]:
    return [with_next(j) for j in load()]


def upsert(job: dict) -> dict:
    with _lock:
        items = load()
        old = next((j for j in items if j["id"] == job.get("id")), None)
        new = clean(job, old)
        items = [new if j["id"] == new["id"] else j for j in items] if old else [*items, new]
        _save(items)
    return with_next(new)


def delete(job_id: str) -> bool:
    with _lock:
        items = load()
        kept = [j for j in items if j["id"] != job_id]
        if len(kept) == len(items):
            return False
        _save(kept)
    return True


def _mark(job_id: str, **fields: Any) -> None:
    with _lock:
        items = load()
        for j in items:
            if j["id"] == job_id:
                j.update(fields)
        _save(items)


# ---- running ----


class Scheduler:
    """Checks the jobs every half minute on the engine's loop and starts the ones that are due."""

    def __init__(self, start_run: Callable[[dict], Any], publish: Callable[[dict], None]):
        self.start_run = start_run  # async (job) -> session id
        self.publish = publish
        self.task: asyncio.Task | None = None
        self.running: set[str] = set()

    def start(self) -> None:
        if not self.task:
            self.task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None

    async def _loop(self) -> None:
        await asyncio.sleep(20)  # let the app settle (and resumed threads start) first
        while True:
            try:
                now = dt.datetime.now()
                for job in load():
                    if job["id"] not in self.running and due(job, now):
                        asyncio.create_task(self.run(job))
            except Exception:
                log.exception("schedule check failed")
            await asyncio.sleep(CHECK_SECONDS)

    async def run(self, job: dict) -> str | None:
        """Start one run now (also used by "Run now")."""
        if job["id"] in self.running:
            return None
        self.running.add(job["id"])
        _mark(job["id"], lastRun=_now_ms(), lastStatus="running")
        try:
            sid = await self.start_run(job)
            _mark(job["id"], lastSession=sid, lastStatus="started")
            self.publish({"type": "schedule.ran", "data": {"job": with_next({**job, "lastSession": sid}), "sessionID": sid}})
            return sid
        except Exception as err:
            log.warning("scheduled job %s failed to start: %s", job.get("name"), err)
            _mark(job["id"], lastStatus=f"failed: {err}"[:200])
            self.publish({"type": "schedule.failed", "data": {"job": job, "error": str(err)}})
            return None
        finally:
            self.running.discard(job["id"])
