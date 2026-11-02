"""Background commands: dev servers, watchers and long builds the agent starts and checks on later.

``shell`` with ``background: true`` starts a job and returns at once with its id and first output;
the ``jobs`` tool reads new output, waits for a line to appear, lists jobs or stops one. Jobs belong
to a thread: they are stopped when the thread is deleted and when AFH quits.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from typing import Callable

from .tools.files import BaseTool, ToolError, int_arg, require_writable, str_arg
from .tools.shell import LIVE_TAIL, clean_clixml, kill_tree, spawn, stream_output, truncate_output
from .types import ToolContext, ToolResult, ToolSpec, event

BUFFER_LIMIT = 2_000_000  # bytes kept per job (the oldest output is dropped first)
MAX_JOBS_PER_THREAD = 8
READ_LIMIT = 20_000  # characters returned per read
START_WAIT = 4.0  # seconds `shell background` waits for the first output


class Job:
    def __init__(self, jid: str, sid: str, command: str, description: str, cwd: str):
        self.id = jid
        self.session_id = sid
        self.command = command
        self.description = description
        self.cwd = cwd
        self.proc: asyncio.subprocess.Process | None = None
        self.buf = bytearray()
        self.dropped = 0  # bytes discarded from the front of buf
        self.read_pos = 0  # absolute offset the agent has read up to
        self.started = time.time()
        self.ended: float | None = None
        self.exit_code: int | None = None
        self.stopped = False
        self.changed = asyncio.Event()
        self.pump: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.ended is None

    def text(self, start: int | None = None) -> str:
        offset = max(0, (start if start is not None else self.dropped) - self.dropped)
        raw = bytes(self.buf[offset:]).decode("utf-8", errors="replace")
        return clean_clixml(raw).replace("\r\n", "\n").replace("\r", "\n")

    def tail(self, chars: int = 2000) -> str:
        t = self.text()
        return t[-chars:]

    def to_dict(self, tail: int = 0) -> dict:
        d = {"id": self.id, "sessionID": self.session_id, "command": self.command, "description": self.description, "cwd": self.cwd,
             "running": self.running, "exitCode": self.exit_code, "stopped": self.stopped, "started": int(self.started * 1000),
             "ended": int(self.ended * 1000) if self.ended else None, "bytes": self.dropped + len(self.buf), "pid": self.proc.pid if self.proc else None}
        if tail:
            d["tail"] = self.tail(tail)
        return d


class JobManager:
    def __init__(self, publish: Callable[[dict], None]):
        self.publish = publish
        self.jobs: dict[str, Job] = {}
        self._n = 0

    def for_session(self, sid: str) -> list[Job]:
        return [j for j in self.jobs.values() if j.session_id == sid]

    def get(self, jid: str, sid: str | None = None) -> Job:
        job = self.jobs.get(jid)
        if job is None or (sid and job.session_id != sid):
            raise ToolError(f"No background job '{jid}'. Running jobs: {', '.join(j.id for j in self.for_session(sid or '') if j.running) or 'none'}")
        return job

    def _notify(self, sid: str) -> None:
        self.publish(event("session.jobs.updated", sid, jobs=[j.to_dict() for j in self.for_session(sid)]))

    async def start(self, sid: str, command: str, cwd: str, shell_pref: str | None, description: str = "") -> Job:
        running = [j for j in self.for_session(sid) if j.running]
        if len(running) >= MAX_JOBS_PER_THREAD:
            raise ToolError(f"This thread already runs {len(running)} background jobs; stop one first (jobs action=stop).")
        self._n += 1
        job = Job(f"job{self._n}", sid, command, description, cwd)
        try:
            job.proc = await spawn(command, cwd, shell_pref)
        except FileNotFoundError as e:
            raise ToolError(f"Could not start the shell ({e}).") from None
        self.jobs[job.id] = job
        job.pump = asyncio.create_task(self._pump(job))
        self._notify(sid)
        return job

    async def _pump(self, job: Job) -> None:
        assert job.proc and job.proc.stdout
        try:
            while True:
                chunk = await job.proc.stdout.read(65536)
                if not chunk:
                    break
                job.buf.extend(chunk)
                if len(job.buf) > BUFFER_LIMIT:
                    cut = len(job.buf) - BUFFER_LIMIT
                    del job.buf[:cut]
                    job.dropped += cut
                job.changed.set()
            await job.proc.wait()
        except asyncio.CancelledError:
            pass
        finally:
            job.exit_code = job.proc.returncode if job.proc else None
            job.ended = time.time()
            job.changed.set()
            self._notify(job.session_id)

    async def wait_output(self, job: Job, seconds: float, pattern: str | None = None) -> bool:
        """Wait until new output arrives (or `pattern` appears in unread output), the job ends, or time runs out."""
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE) if pattern else None
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            unread = job.text(job.read_pos)
            if regex is not None and regex.search(unread):
                return True
            if regex is None and unread.strip():
                return True
            if not job.running:
                return regex is None
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            job.changed.clear()
            try:
                await asyncio.wait_for(job.changed.wait(), min(left, 1.0))
            except asyncio.TimeoutError:
                pass

    def read(self, job: Job) -> tuple[str, bool]:
        text = job.text(job.read_pos)
        job.read_pos = job.dropped + len(job.buf)
        if len(text) > READ_LIMIT:
            return "… (earlier output skipped) …\n" + text[-READ_LIMIT:], True
        return text, False

    async def stop(self, job: Job) -> None:
        if job.running and job.proc:
            job.stopped = True
            await kill_tree(job.proc)
            try:
                await asyncio.wait_for(job.proc.wait(), 10)
            except asyncio.TimeoutError:
                pass
        if job.pump:
            try:
                await asyncio.wait_for(asyncio.shield(job.pump), 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                job.pump.cancel()
        self._notify(job.session_id)

    async def stop_session(self, sid: str, forget: bool = False) -> None:
        for job in self.for_session(sid):
            await self.stop(job)
            if forget:
                self.jobs.pop(job.id, None)

    async def stop_all(self) -> None:
        for job in list(self.jobs.values()):
            try:
                await self.stop(job)
            except Exception:
                pass

    def remove(self, jid: str) -> None:
        job = self.jobs.get(jid)
        if job and not job.running:
            self.jobs.pop(jid, None)
            self._notify(job.session_id)


def describe(job: Job) -> str:
    if job.running:
        state = f"running for {int(time.time() - job.started)}s"
    elif job.stopped:
        state = "stopped"
    else:
        state = f"exited with code {job.exit_code}"
    return f"{job.id} ({state}): {job.command}"


@contextlib.asynccontextmanager
async def live_job(ctx: ToolContext, job: Job):
    """While a tool waits on a job, its card shows the job's output as it arrives."""
    task = asyncio.create_task(stream_output(ctx, lambda: (job.dropped + len(job.buf), bytes(job.buf[-LIVE_TAIL * 2:]))))
    try:
        yield
    finally:
        task.cancel()


async def start_background(ctx: ToolContext, command: str, description: str, wait: float) -> ToolResult:
    jobs: JobManager = ctx.jobs
    job = await jobs.start(ctx.session_id, command, ctx.directory, (ctx.settings or {}).get("shell"), description)
    async with live_job(ctx, job):
        await jobs.wait_output(job, wait)
        await asyncio.sleep(0.3)  # let a burst of startup output land
    text, _ = jobs.read(job)
    text = text.strip()
    head = f"Started background job {job.id}: {command}"
    if not job.running:
        head = f"Background job {job.id} already exited (code {job.exit_code}): {command}"
    body = text or "(no output yet)"
    body, _ = truncate_output(body, 8000)
    tip = (f"\n\nRead more output with jobs(action=\"output\", id=\"{job.id}\"), wait for a line with `pattern`, and stop it with "
           f"jobs(action=\"stop\", id=\"{job.id}\") when you no longer need it.") if job.running else ""
    return ToolResult(text=f"{head}\n\n{body}{tip}", is_error=not job.running and job.exit_code not in (0, None),
                      metadata={"command": command, "description": description, "background": True, "job": job.to_dict()})


class JobsTool(BaseTool):
    spec = ToolSpec(
        name="jobs",
        description=(
            "Manage background commands started with `shell` and `background: true` (dev servers, watchers, long builds). "
            "action \"output\": new output since your last read (set `wait` seconds to wait for output, and `pattern` - a regex - "
            "to wait until a line like \"ready on\" or \"error\" appears). action \"list\": all jobs of this thread. "
            "action \"stop\": stop a job and its child processes. Stop servers you started when you are done with them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["output", "list", "stop"]},
                "id": {"type": "string", "description": "The job id (e.g. \"job1\"); required for output and stop."},
                "wait": {"type": "integer", "description": "output: seconds to wait for new output (default 0, max 300)."},
                "pattern": {"type": "string", "description": "output: wait until this regex matches the unread output."},
            },
            "required": ["action"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        jobs: JobManager | None = ctx.jobs
        if jobs is None:
            raise ToolError("Background jobs are not available here.")
        action = str_arg(input, "action").strip().lower()
        if action == "list":
            items = jobs.for_session(ctx.session_id)
            if not items:
                return ToolResult(text="No background jobs in this thread.", metadata={"jobs": []})
            return ToolResult(text="\n".join(describe(j) for j in items), metadata={"jobs": [j.to_dict() for j in items]})
        jid = str_arg(input, "id").strip()
        job = jobs.get(jid, ctx.session_id)
        if action == "stop":
            require_writable(ctx)
            was = job.running
            await jobs.stop(job)
            text, _ = jobs.read(job)
            tail = text.strip()[-3000:]
            return ToolResult(text=(f"Stopped {job.id}." if was else f"{job.id} had already exited (code {job.exit_code}).") + (f"\n\nLast output:\n{tail}" if tail else ""),
                              metadata={"job": job.to_dict()})
        if action != "output":
            raise ToolError("action must be \"output\", \"list\" or \"stop\".")
        wait = min(300, max(0, int_arg(input, "wait", 0)))
        pattern = str_arg(input, "pattern", required=False) or None
        if pattern:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ToolError(f"Invalid pattern: {e}") from None
        async with live_job(ctx, job):
            matched = await jobs.wait_output(job, wait, pattern) if (wait or pattern) else True
        text, skipped = jobs.read(job)
        status = describe(job)
        note = ""
        if pattern and not matched:
            note = f"\n[pattern {pattern!r} not seen within {wait}s]"
        return ToolResult(text=f"{status}\n\n{text.strip() or '(no new output)'}{note}", truncated=skipped,
                          metadata={"job": job.to_dict(), "matched": matched})
