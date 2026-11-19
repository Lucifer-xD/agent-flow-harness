"""The engine's handling of things that go wrong outside it: pages that refuse or don't exist, commands that run
past their time, models a provider no longer has, and runs that an install would cut off."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

from afh.engine import config as provcfg
from afh.engine import jobs as jobsmod
from afh.engine import limits
from afh.engine.providers.antigravity import AntigravityProvider
from afh.engine.types import ChatMessage, ChatRequest, ProviderConfig
from afh.engine.jobs import JobManager, JobsTool
from afh.engine.tools import web as web_mod
from afh.engine.tools.shell import ShellTool
from afh.engine.tools.web import WebFetchTool

from test_tools import make_ctx, mock_client, project  # noqa: F401 - project is a fixture

IS_WINDOWS = sys.platform == "win32"


def run(coro):
    return asyncio.run(coro)


# ---- web pages -------------------------------------------------------------------------------


def test_webfetch_tries_the_other_github_branch(project, monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if "/master/" in request.url.path:
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="# readme")
        return httpx.Response(404, text="404: Not Found")

    monkeypatch.setattr(web_mod, "make_client", mock_client(handler))
    res = run(WebFetchTool().run(make_ctx(project), {"url": "https://raw.githubusercontent.com/o/r/main/README.md"}))
    assert not res.is_error and res.text == "# readme"
    assert seen == ["/o/r/main/README.md", "/o/r/master/README.md"]


def test_webfetch_says_what_to_do_next(project, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403 if "blocked" in request.url.path else 404, text="nope")

    monkeypatch.setattr(web_mod, "make_client", mock_client(handler))
    ctx = make_ctx(project)
    res = run(WebFetchTool().run(ctx, {"url": "https://example.com/missing"}))
    assert res.text.startswith("HTTP 404") and "Don't guess addresses" in res.text
    res = run(WebFetchTool().run(ctx, {"url": "https://example.com/blocked"}))
    assert res.text.startswith("HTTP 403") and "browser tool" in res.text
    assert "AFH" not in web_mod.USER_AGENT


# ---- commands that run past their time --------------------------------------------------------


def test_a_slow_command_moves_to_the_background(project):
    async def go():
        jobs = JobManager(lambda ev: None)
        ctx = make_ctx(project, jobs=jobs)
        cmd = ("Write-Output start; Start-Sleep 3; Write-Output finished" if IS_WINDOWS
               else "echo start; sleep 3; echo finished")
        t0 = time.monotonic()
        res = await ShellTool().run(ctx, {"command": cmd, "timeout": 1})
        assert time.monotonic() - t0 < 10
        assert not res.is_error and res.metadata["background"] and "background job job1" in res.text
        assert "start" in res.text
        job = jobs.get("job1")
        await jobs.wait_output(job, 20, pattern="finished")
        out = await JobsTool().run(ctx, {"action": "output", "id": "job1", "wait": 10})
        body = out.text.split("\n\n", 1)[1]  # after the job's header line, which repeats the command
        assert "finished" in body and "start" not in body  # the shell call already returned "start"
        for _ in range(100):
            if not job.running:
                break
            await asyncio.sleep(0.1)
        assert not job.running and job.exit_code == 0

    run(go())


def _sse(events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


NOT_FOUND = {"error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}}
HELLO = [{"response": {"candidates": [{"content": {"parts": [{"text": "Hi"}]}, "finishReason": "STOP"}]}}]


def _antigravity(handler, saved):
    cfg = ProviderConfig(id="antigravity", name="Google Antigravity", kind="antigravity", base_url="https://cc.example.com",
                         auth={"type": "antigravity", "access": "tok", "refresh": "r", "expires": time.time() + 3600, "project": "proj-old"},
                         account_id="a1", account_label="second account")
    return AntigravityProvider(cfg, transport=httpx.MockTransport(handler))


def _stream(p):
    async def go():
        return [ev async for ev in p.stream(ChatRequest(model="gemini-4-argon", system="", messages=[ChatMessage("user", "hi")]))]

    return asyncio.run(go())


def test_antigravity_finds_the_accounts_new_project_after_a_404(monkeypatch):
    saved = []
    monkeypatch.setattr(provcfg, "save_creds", lambda pid, aid, patch: saved.append((pid, aid, patch["auth"]["project"])))
    projects = []

    def handler(request):
        if request.url.path.endswith("loadCodeAssist"):
            return httpx.Response(200, json={"cloudaicompanionProject": "proj-new"})
        project = json.loads(request.content)["project"]
        projects.append(project)
        if project == "proj-old":
            return httpx.Response(404, json=NOT_FOUND)
        return httpx.Response(200, content=_sse(HELLO), headers={"content-type": "text/event-stream"})

    out = _stream(_antigravity(handler, saved))
    assert projects == ["proj-old", "proj-new"] and saved == [("antigravity", "a1", "proj-new")]
    assert any(e["type"] == "text.delta" for e in out) and not any(e["type"] == "error" for e in out)


def test_antigravity_404_says_what_it_means_and_moves_to_another_account(monkeypatch):
    monkeypatch.setattr(provcfg, "save_creds", lambda *a: None)

    def handler(request):
        if request.url.path.endswith("loadCodeAssist"):
            return httpx.Response(200, json={"cloudaicompanionProject": "proj-old"})  # same project: nothing to retry
        return httpx.Response(404, json=NOT_FOUND)

    out = _stream(_antigravity(handler, []))
    err = next(e for e in out if e["type"] == "error")
    assert err["status"] == 404 and err["missing"]
    assert "can't use gemini-4-argon" in err["message"] and "second account" in err["message"]
    kind, until = limits.classify(err)
    assert kind == "used_up" and until > time.time() + 3600
    assert limits.short_reason(err) == "this account can't use the model"


def test_without_room_for_a_job_a_slow_command_is_still_stopped(project, monkeypatch):
    monkeypatch.setattr(jobsmod, "MAX_JOBS_PER_THREAD", 0)

    async def go():
        ctx = make_ctx(project, jobs=JobManager(lambda ev: None))
        cmd = "Start-Sleep 30" if IS_WINDOWS else "sleep 30"
        res = await ShellTool().run(ctx, {"command": cmd, "timeout": 1})
        assert res.is_error and res.metadata["timed_out"] and "killed" in res.text and "BatchMode" in res.text

    run(go())
