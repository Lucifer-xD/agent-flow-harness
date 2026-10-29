"""Python client for the Agent Flow Harness local API. One file, standard library only.

    from afh_sdk import AFH

    afh = AFH()                     # finds the running app; key from $AFH_API_KEY
    result = afh.run("Add a /health endpoint and a test for it", directory=r"C:\\code\\api")
    print(result["reply"])

    for event in afh.events():       # live events from every thread
        print(event["type"])

Create an API key in AFH → Settings → Developer. AFH must be running.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

__all__ = ["AFH", "AFHError"]
__version__ = "1.0.0"


class AFHError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _discover() -> str:
    home = Path(os.environ.get("AFH_HOME") or Path.home() / ".afh")
    try:
        return json.loads((home / "api.json").read_text(encoding="utf-8"))["url"]
    except (OSError, ValueError, KeyError):
        raise AFHError(0, "AFH doesn't seem to be running (no ~/.afh/api.json). Start the app, or pass url=") from None


class AFH:
    """A connection to the running AFH app."""

    def __init__(self, api_key: str | None = None, url: str | None = None, timeout: float = 60):
        self.url = (url or os.environ.get("AFH_URL") or _discover()).rstrip("/")
        self.api_key = api_key or os.environ.get("AFH_API_KEY")
        if not self.api_key:
            raise AFHError(0, "No API key: pass api_key= or set AFH_API_KEY (create one in Settings → Developer)")
        self.timeout = timeout

    # ---- plumbing ----

    def request(self, method: str, path: str, body: Any = None, *, params: dict | None = None, timeout: float | None = None) -> Any:
        url = self.url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error") or e.reason
            except ValueError:
                msg = e.reason
            raise AFHError(e.code, str(msg)) from None
        return json.loads(raw) if raw else None

    # ---- the one-call way ----

    def run(self, prompt: str, *, directory: str | None = None, session_id: str | None = None, model: str | None = None,
            agent: str | None = None, mode: str = "full", wait: bool = True, timeout: float = 1800) -> dict:
        """Start a thread in `directory` (or continue `session_id`), send `prompt` and wait for the answer.

        Returns {sessionID, done, reply, todos, goal, cost, title}. `model` is "provider/model",
        e.g. "kimi/kimi-k3.1-pro". mode: "full" (no approvals), "build" or "plan"."""
        body = {"prompt": prompt, "directory": directory, "sessionID": session_id, "model": model, "agent": agent,
                "mode": mode, "wait": wait, "timeout": timeout}
        return self.request("POST", "/api/v1/run", {k: v for k, v in body.items() if v is not None}, timeout=timeout + 30)

    # ---- threads ----

    def sessions(self, directory: str, archived: bool = False) -> list[dict]:
        return self.request("GET", "/api/sessions", params={"directory": directory, "archived": str(archived).lower()})

    def create_session(self, directory: str, *, title: str | None = None, model: str | None = None, agent: str | None = None,
                       mode: str | None = None, worktree: bool = False) -> dict:
        ref = None
        if model:
            pid, _, mid = model.partition("/")
            ref = {"providerID": pid, "id": mid}
        body = {"directory": directory, "title": title, "model": ref, "agent": agent, "mode": mode, "worktree": worktree}
        return self.request("POST", "/api/sessions", {k: v for k, v in body.items() if v not in (None, False)})

    def session(self, session_id: str) -> dict:
        return self.request("GET", f"/api/sessions/{session_id}")

    def messages(self, session_id: str) -> list[dict]:
        return self.request("GET", f"/api/sessions/{session_id}/messages")

    def prompt(self, session_id: str, text: str, files: list[str] | None = None) -> dict:
        """Send a message (returns at once; the run continues in the app)."""
        return self.request("POST", f"/api/sessions/{session_id}/prompt", {"text": text, "files": files or []})

    def reply(self, session_id: str) -> dict:
        """{running, reply}: the newest answer in a thread."""
        return self.request("GET", f"/api/v1/sessions/{session_id}/reply")

    def interrupt(self, session_id: str) -> None:
        self.request("POST", f"/api/sessions/{session_id}/interrupt")

    def delete_session(self, session_id: str) -> None:
        self.request("DELETE", f"/api/sessions/{session_id}")

    # ---- to-do list, goal, changes ----

    def todos(self, session_id: str) -> list[dict]:
        return self.request("GET", f"/api/sessions/{session_id}/todos")

    def set_todos(self, session_id: str, todos: list[dict]) -> list[dict]:
        return self.request("PUT", f"/api/sessions/{session_id}/todos", {"todos": todos})

    def goal(self, session_id: str) -> dict | None:
        return self.request("GET", f"/api/sessions/{session_id}/goal")

    def set_goal(self, session_id: str, text: str, criteria: str = "", *, autopilot: bool = True, start: bool = False) -> dict:
        return self.request("PUT", f"/api/sessions/{session_id}/goal", {"text": text, "criteria": criteria, "autopilot": autopilot, "start": start})

    def diff(self, session_id: str) -> list[dict]:
        return self.request("GET", f"/api/sessions/{session_id}/diff")

    def usage(self, session_id: str) -> dict:
        return self.request("GET", f"/api/sessions/{session_id}/usage")

    # ---- models & schedules ----

    def models(self) -> dict:
        """{models: [...], defaultModel, providerNames}. Use "providerID/id" of a model as `model=`."""
        return self.request("GET", "/api/models")

    def schedules(self) -> list[dict]:
        return self.request("GET", "/api/schedules")

    def run_schedule(self, schedule_id: str) -> dict:
        """Run a scheduled job now. Returns {sessionID} of the new thread."""
        return self.request("POST", f"/api/schedules/{schedule_id}/run")

    def save_schedule(self, job: dict) -> dict:
        """Create a job (no "id") or update one. Fields: name, directory, prompt, every
        (interval|hourly|daily|weekdays|weekly), minutes, time "HH:MM", weekday (0 = Monday),
        model "provider/model", mode, enabled."""
        if job.get("id"):
            return self.request("PUT", f"/api/schedules/{job['id']}", job)
        return self.request("POST", "/api/schedules", job)

    def delete_schedule(self, schedule_id: str) -> None:
        self.request("DELETE", f"/api/schedules/{schedule_id}")

    # ---- approvals (threads not in "full" mode ask before acting) ----

    def approvals(self, session_id: str) -> list[dict]:
        return self.request("GET", f"/api/sessions/{session_id}/permissions")

    def approve(self, session_id: str, request_id: str, decision: str = "once", message: str | None = None) -> None:
        """decision: "once", "always" (for this kind of action in this thread) or "reject"."""
        self.request("POST", f"/api/sessions/{session_id}/permissions/{request_id}", {"decision": decision, "message": message})

    # ---- live events ----

    def events(self, session_id: str | None = None) -> Iterator[dict]:
        """Yield events as they happen (Server-Sent Events), optionally only one thread's."""
        req = urllib.request.Request(self.url + "/api/events", headers={"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=None) as r:
            for raw in r:
                line = raw.decode("utf-8").rstrip("\n")
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                if session_id and (ev.get("data") or {}).get("sessionID") != session_id:
                    continue
                yield ev


if __name__ == "__main__":  # python afh_sdk.py "<prompt>" <directory>
    import sys

    if len(sys.argv) < 3:
        sys.exit('usage: python afh_sdk.py "<prompt>" <directory>')
    out = AFH().run(sys.argv[1], directory=sys.argv[2])
    print(out["reply"])
