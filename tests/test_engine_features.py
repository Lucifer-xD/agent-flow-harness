"""The 1.4 engine features end to end, driven by a scripted fake model: to-do list, goal autopilot,
parallel tools, error checks after edits, hooks, background jobs, slash commands, pricing and
spending limits, context pruning, compaction and worktrees."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from afh import store as appstore
from afh.engine import commands as cmdmod
from afh.engine import config as provcfg
from afh.engine import pricing
from afh.engine import runner as runmod
from afh.engine import state as statemod
from afh.engine import worktree as wtmod
from afh.engine.core import Engine
from afh.engine.jobs import JobManager, JobsTool
from afh.engine.tools.shell import ShellTool
from afh.engine.types import ChatMessage, ModelInfo, ProviderConfig, ToolContext, ToolResult, ToolSpec


# ---- harness ------------------------------------------------------------------------------------


class FakeProvider:
    """Plays back one scripted reply per model call. A reply is a string (plain text) or a list of
    (tool name, input) calls. Records every request so tests can look at what the model was sent."""

    def __init__(self, replies, usage=None):
        self.config = ProviderConfig(id="fake", name="Fake", kind="openai", base_url="http://fake")
        self.replies = list(replies)
        self.requests = []
        self.usage = usage or {"input": 100, "output": 20, "cache_read": 0, "cache_write": 0}
        self.n = 0

    async def stream(self, req):
        self.requests.append(req)
        reply = self.replies.pop(0) if self.replies else "All done."
        if isinstance(reply, str):
            yield {"type": "text.delta", "text": reply}
        else:
            for name, inp in reply:
                self.n += 1
                cid = f"call_{self.n}"
                yield {"type": "tool.start", "id": cid, "name": name}
                yield {"type": "tool.end", "id": cid, "name": name, "input": inp, "raw": json.dumps(inp)}
        yield {"type": "usage", "reasoning": 0, **self.usage}
        yield {"type": "finish", "reason": "stop" if isinstance(reply, str) else "tool_calls"}

    async def list_models(self):
        return []


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "afh-home"
    h.mkdir()
    monkeypatch.setattr(appstore, "AFH_DIR", h)
    monkeypatch.setattr(appstore, "SETTINGS_PATH", h / "settings.json")
    monkeypatch.setattr(appstore, "PERSONALIZATION_PATH", h / "personalization.md")
    monkeypatch.setattr(appstore, "GLOBAL_AGENTS_MD", h / "AGENTS.md")
    monkeypatch.setattr(appstore, "LEGACY_AGENTS_MD", h / "none" / "AGENTS.md")
    monkeypatch.setattr(provcfg, "PATH", h / "providers.json")
    monkeypatch.setattr(wtmod, "ROOT", h / "worktrees")
    appstore.save_settings({"defaultMode": "full"})
    return h


def make_engine(provider: FakeProvider) -> Engine:
    e = Engine()
    e.providers = {"fake": provider}
    e.models = {"fake": [ModelInfo(id="m", name="M", context=100_000, output=4096)]}
    e.events = []
    e.publish = lambda ev: e.events.append(ev)  # noqa: E731 - capture instead of SSE
    e.jobs.publish = e.publish

    async def no_title(session):  # titles would take a scripted reply
        return None

    e.after_run = no_title
    return e


async def run_prompt(e: Engine, project: Path, text: str, sid: str | None = None, **settings) -> dict:
    if settings:
        appstore.save_settings(settings)
    e.loop = asyncio.get_running_loop()
    if sid is None:
        sid = e.create_session(str(project), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    await e.prompt(sid, text)
    await e.runs[sid].task
    return e.store.get_session(sid)


def notices(e: Engine, sid: str) -> list[dict]:
    return [m for m in e.store.list_messages(sid) if m.get("type") == "synthetic"]


def tool_results(e: Engine, sid: str) -> list[dict]:
    return [p for m in e.store.list_messages(sid) if m.get("type") == "assistant" for p in m["content"] if p.get("type") == "tool"]


def text_of(part: dict) -> str:
    return "\n".join(c.get("text", "") for c in part["state"].get("content") or [])


# ---- to-do list --------------------------------------------------------------------------------


def test_todo_normalize_statuses_ids_and_merge():
    todos = statemod.normalize_todos([{"content": "a", "status": "done"}, {"content": "b", "status": "In Progress"}, "c", {"content": "  "}, {"content": "d", "status": "weird"}])
    assert [(t["id"], t["content"], t["status"]) for t in todos] == [("1", "a", "completed"), ("2", "b", "in_progress"), ("3", "c", "pending"), ("4", "d", "pending")]
    merged = statemod.merge_todos(todos, [{"id": "2", "status": "completed"}, {"content": "e", "status": "pending"}])
    assert [t["status"] for t in merged] == ["completed", "completed", "pending", "pending", "pending"] and merged[-1]["id"] == "5"
    assert statemod.todo_counts(merged)["open"] == 3
    assert statemod.render_todos(merged[:2]) == "[x] 1. a\n[x] 2. b"


def test_todo_tool_live_state_and_nudge_once(home, tmp_path):
    p = FakeProvider([
        [("todo", {"todos": [{"id": "1", "content": "Write code", "status": "in_progress"}, {"id": "2", "content": "Test it", "status": "pending"}]})],
        "I wrote the code.",  # stops with open items -> one nudge
        [("todo", {"merge": True, "todos": [{"id": "1", "status": "completed"}, {"id": "2", "status": "completed"}]})],
        "Everything is done.",
    ])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "build it"))
    sid = s["id"]
    assert [t["status"] for t in e.todos(sid)] == ["completed", "completed"]
    kinds = [n["metadata"]["notice"] for n in notices(e, sid)]
    assert kinds == ["todo"], kinds
    assert "still has open items" in notices(e, sid)[0]["text"] and "Test it" in notices(e, sid)[0]["text"]
    assert any(ev["type"] == "session.todos.updated" for ev in e.events)
    first = tool_results(e, sid)[0]
    assert first["state"]["status"] == "completed" and "(0/2 done)" in text_of(first)
    assert len(p.requests) == 4


def test_todo_nudge_can_be_turned_off_and_user_edit_reaches_model(home, tmp_path):
    p = FakeProvider([[("todo", {"todos": [{"content": "A", "status": "in_progress"}]})], "Stopping here.", "ok"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "go", agent={"todoNudge": False}))
    assert notices(e, s["id"]) == []
    e.set_todos(s["id"], [{"id": "1", "content": "A", "status": "completed"}, {"content": "B", "status": "pending"}], by="user")
    asyncio.run(run_prompt(e, tmp_path, "continue", sid=s["id"]))
    sent = "\n".join(m.text for m in p.requests[-1].messages)
    assert "The user edited your to-do list" in sent and "[ ] 2. B" in sent


# ---- goal ------------------------------------------------------------------------------------------


def test_goal_autopilot_continues_until_achieved(home, tmp_path):
    p = FakeProvider([
        "I looked around.",  # stops without reporting -> autopilot continues
        [("goal", {"status": "achieved", "summary": "Done and verified", "evidence": "pytest: 3 passed"})],
        "Final report: all good.",
    ])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.set_goal(sid, "make the tests pass", "pytest exits 0", autopilot=True, max_turns=5)
    asyncio.run(run_prompt(e, tmp_path, "start", sid=sid))
    g = e.goal(sid)
    assert g["status"] == "achieved" and g["turns"] == 1 and g["summary"] == "Done and verified"
    assert [n["metadata"]["notice"] for n in notices(e, sid)] == ["goal"]
    assert "Goal autopilot 1/5" in notices(e, sid)[0]["text"]
    assert "# Goal of this thread" in p.requests[0].system and "pytest exits 0" in p.requests[0].system
    assert "goal" in [t.name for t in p.requests[0].tools]


def test_goal_achieved_refused_with_open_todos_and_blocked_stops(home, tmp_path):
    p = FakeProvider([
        [("todo", {"todos": [{"content": "step", "status": "in_progress"}]})],
        [("goal", {"status": "achieved", "summary": "done"})],  # refused: open to-do
        [("goal", {"status": "blocked", "summary": "need an API key"})],
        "I need your API key.",
    ])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.set_goal(sid, "ship it")
    asyncio.run(run_prompt(e, tmp_path, "go", sid=sid))
    parts = tool_results(e, sid)
    assert parts[1]["state"]["status"] == "error" and "still has open items" in text_of(parts[1])
    g = e.goal(sid)
    assert g["status"] == "blocked" and g["turns"] == 0
    # once the user replies, the goal is active again with a fresh budget
    p.replies = ["ok"]
    asyncio.run(run_prompt(e, tmp_path, "here is the key", sid=sid, agent={"todoNudge": False}))
    assert e.goal(sid)["status"] == "active"


def test_goal_autopilot_budget_runs_out(home, tmp_path):
    p = FakeProvider(["a", "b", "c", "d", "e"])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.set_goal(sid, "never done", max_turns=2)
    asyncio.run(run_prompt(e, tmp_path, "go", sid=sid))
    g = e.goal(sid)
    assert g["turns"] == 2 and g["exhausted"] is True and g["status"] == "active"
    assert len(p.requests) == 3
    assert any(ev["type"] == "session.notice" and "Autopilot paused" in ev["data"]["label"] for ev in e.events)


def test_slash_goal_sets_goal_and_prompts(home, tmp_path):
    p = FakeProvider([[("goal", {"status": "achieved", "summary": "x"})], "done"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "/goal the README has install steps"))
    user = [m for m in e.store.list_messages(s["id"]) if m["type"] == "user"][0]
    assert user["command"]["name"] == "goal" and "README has install steps" in user["text"]
    assert e.goal(s["id"])["status"] == "achieved"


# ---- parallel tools ----------------------------------------------------------------------------


class SlowRead:
    spec = ToolSpec(name="read", description="slow", parameters={"type": "object", "properties": {}})

    async def run(self, ctx, input):
        await asyncio.sleep(0.4)
        return ToolResult(text=f"read {input.get('n')}")


def test_read_only_calls_run_in_parallel(home, tmp_path):
    p = FakeProvider([[("read", {"n": 1}), ("read", {"n": 2}), ("read", {"n": 3})], "done"])
    e = make_engine(p)
    e.tools_for = lambda session, agent: [SlowRead()]
    t0 = time.monotonic()
    s = asyncio.run(run_prompt(e, tmp_path, "read three files"))
    elapsed = time.monotonic() - t0
    assert [text_of(x) for x in tool_results(e, s["id"])] == ["read 1", "read 2", "read 3"]
    assert elapsed < 1.0, elapsed  # three 0.4 s reads, not 1.2 s


# ---- error checks after edits -------------------------------------------------------------------


def test_diagnostics_report_syntax_errors_after_edit(home, tmp_path):
    p = FakeProvider([[("write", {"path": "bad.py", "content": "def f(:\n    pass\n"}), ("write", {"path": "ok.json", "content": "{\"a\": 1}"})], "done"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "write files", agent={"todoNudge": False}))
    parts = tool_results(e, s["id"])
    last = parts[-1]
    assert "Problems found after this edit" in text_of(last) and "SyntaxError" in text_of(last)
    # each card shows the checks of its own file; the report goes to the model once, on the last edit
    assert parts[0]["state"]["metadata"]["diagnostics"]["ran"] == ["python syntax"] and parts[0]["state"]["metadata"]["diagnostics"]["ok"] is False
    assert last["state"]["metadata"]["diagnostics"]["ran"] == ["json"] and last["state"]["metadata"]["diagnostics"]["ok"] is True
    assert "Problems found" not in text_of(parts[0])
    assert "Problems found" in p.requests[1].messages[-1].text  # the model saw it


def test_diagnostics_clean_and_disabled(home, tmp_path):
    p = FakeProvider([[("write", {"path": "good.py", "content": "x = 1\n"})], "done"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "write", agent={"todoNudge": False}))
    assert "no problems found" in text_of(tool_results(e, s["id"])[-1])
    p2 = FakeProvider([[("write", {"path": "bad2.py", "content": "def (:"})], "done"])
    e2 = make_engine(p2)
    s2 = asyncio.run(run_prompt(e2, tmp_path, "write", diagnostics={"enabled": False}))
    assert "diagnostics" not in tool_results(e2, s2["id"])[-1]["state"]["metadata"]


def test_diagnostics_custom_command(home, tmp_path):
    p = FakeProvider([[("write", {"path": "a.txt", "content": "hello"})], "done"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "write", diagnostics={"commands": [{"name": "txtcheck", "glob": "*.txt", "command": "echo 'custom-problem'; exit 3"}]}))
    t = text_of(tool_results(e, s["id"])[-1])
    assert "txtcheck" in t and "custom-problem" in t


# ---- hooks ----------------------------------------------------------------------------------------


def test_pre_tool_hook_blocks_and_post_tool_hook_reports(home, tmp_path):
    hooks = [
        {"name": "no-shell", "event": "pre_tool", "matcher": "^shell$", "command": "echo 'shell is off'; exit 2"},
        {"name": "after-write", "event": "post_tool", "matcher": "write", "command": "echo formatted"},
    ]
    p = FakeProvider([[("shell", {"command": "echo hi"}), ("write", {"path": "f.txt", "content": "x"})], "done"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "go", hooks=hooks, agent={"todoNudge": False}))
    shell, write = tool_results(e, s["id"])
    assert shell["state"]["status"] == "error" and "Blocked by the user's hook 'no-shell'" in text_of(shell) and "shell is off" in text_of(shell)
    assert "[Hook 'after-write']" in text_of(write) and "formatted" in text_of(write)
    assert write["state"]["metadata"]["hooks"][0]["code"] == 0


def test_stop_hook_sends_the_agent_back_at_most_three_times(home, tmp_path):
    p = FakeProvider(["one", "two", "three", "four", "five"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "go", hooks=[{"name": "tests", "event": "stop", "command": "echo '2 tests failed'; exit 2"}]))
    assert [n["metadata"]["notice"] for n in notices(e, s["id"])] == ["hook", "hook", "hook"]
    assert "2 tests failed" in notices(e, s["id"])[0]["text"]
    assert len(p.requests) == 4


# ---- background jobs ---------------------------------------------------------------------------


RUN = "& " if sys.platform == "win32" else ""  # PowerShell needs & to run a quoted program path


class AllowGate:
    async def require(self, action, resources, metadata=None):
        return None


class NoSnap:
    def record(self, path):
        pass


def test_background_job_start_wait_for_pattern_and_stop(tmp_path):
    async def go():
        events = []
        jobs = JobManager(events.append)
        ctx = ToolContext(session_id="s1", message_id="m1", directory=str(tmp_path), permissions=AllowGate(), snapshots=NoSnap(), emit=lambda *a: None, jobs=jobs)
        script = tmp_path / "srv.py"
        script.write_text("import time\nprint('booting', flush=True)\ntime.sleep(0.5)\nprint('ready on port 1234', flush=True)\ntime.sleep(60)\n")
        res = await ShellTool().run(ctx, {"command": f'{RUN}"{sys.executable}" "{script}"', "background": True})
        assert not res.is_error and "Started background job job1" in res.text and "booting" in res.text
        jid = res.metadata["job"]["id"]
        out = await JobsTool().run(ctx, {"action": "output", "id": jid, "wait": 10, "pattern": "ready on"})
        assert "ready on port 1234" in out.text and out.metadata["matched"] is True
        listed = await JobsTool().run(ctx, {"action": "list"})
        assert "running" in listed.text
        stopped = await JobsTool().run(ctx, {"action": "stop", "id": jid})
        assert "Stopped job1" in stopped.text and not jobs.get(jid).running
        assert any(e["type"] == "session.jobs.updated" for e in events)
        missing = await JobsTool().run(ctx, {"action": "output", "id": "nope"})
        assert missing.is_error

    asyncio.run(go())


def test_background_job_that_exits_immediately_reports_failure(tmp_path):
    async def go():
        jobs = JobManager(lambda ev: None)
        ctx = ToolContext(session_id="s1", message_id="m1", directory=str(tmp_path), permissions=AllowGate(), snapshots=NoSnap(), emit=lambda *a: None, jobs=jobs)
        res = await ShellTool().run(ctx, {"command": f'{RUN}"{sys.executable}" -c "import sys; print(\'port in use\'); sys.exit(1)"', "background": True})
        assert res.is_error and "already exited (code 1)" in res.text and "port in use" in res.text

    asyncio.run(go())


# ---- slash commands -------------------------------------------------------------------------------


def test_slash_commands_parse_expand_and_sources(home, tmp_path):
    assert cmdmod.parse("/review src/a.py") == ("review", "src/a.py")
    assert cmdmod.parse("/usr/bin/python run") is None and cmdmod.parse("hello") is None
    assert cmdmod.expand("Explain $ARGUMENTS please", "the router") == "Explain the router please"
    assert cmdmod.expand("Move $1 to $2", "a.txt b.txt") == "Move a.txt to b.txt"
    assert cmdmod.expand("Do it", "now") == "Do it\n\nnow"
    (tmp_path / ".afh" / "commands").mkdir(parents=True)
    (tmp_path / ".afh" / "commands" / "deploy.md").write_text("---\ndescription: Ship to staging\n---\nDeploy $ARGUMENTS to staging.\n", encoding="utf-8")
    names = {c["name"]: c for c in cmdmod.all_commands(str(tmp_path))}
    assert names["deploy"]["description"] == "Ship to staging" and names["deploy"]["source"] == "project"
    assert names["goal"]["builtin"] and names["review"]["source"] == "settings"


def test_custom_command_expands_in_the_prompt(home, tmp_path):
    p = FakeProvider(["ok"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "/explain the login flow"))
    user = [m for m in e.store.list_messages(s["id"]) if m["type"] == "user"][0]
    assert user["command"]["name"] == "explain" and user["text"].startswith("Explain how the login flow works")
    assert p.requests[0].messages[-1].text.startswith("Explain how the login flow works")


# ---- cost, limits, pruning, compaction ---------------------------------------------------------------


def test_pricing_cost_and_openrouter_prices():
    price = {"input": 3.0, "output": 15.0, "cacheRead": 0.3}
    tokens = {"input": 1_000_000, "output": 100_000, "cache": {"read": 2_000_000, "write": 0}}
    assert pricing.cost_of(tokens, price) == pytest.approx(3.0 + 1.5 + 0.6)
    assert pricing.cost_of(tokens, None) is None
    assert pricing.from_openrouter({"prompt": "0.000003", "completion": "0.000015"}) == {"input": 3.0, "output": 15.0}
    assert pricing.is_plan({"catalog": "zai-coding"}, "zai-coding") and not pricing.is_plan({}, "openai")


def test_cost_is_recorded_and_thread_limit_stops_the_run(home, tmp_path):
    provcfg.upsert("fake", {"name": "Fake", "kind": "openai", "base_url": "http://fake", "prices": {"m": {"input": 10.0, "output": 10.0}}})
    p = FakeProvider(["hi", "again"], usage={"input": 50_000, "output": 50_000, "cache_read": 0, "cache_write": 0})
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "hello"))
    assert s["cost"] == pytest.approx(1.0)
    asst = [m for m in e.store.list_messages(s["id"]) if m["type"] == "assistant"][0]
    assert asst["cost"] == pytest.approx(1.0)
    assert e.store.cost_since(0) == pytest.approx(1.0)
    rows = e.store.usage_rows(0)
    assert rows[0]["model"] == "m" and rows[0]["input"] == 50_000
    asyncio.run(run_prompt(e, tmp_path, "more", sid=s["id"], budget={"perThread": 0.5}))
    failed = [ev for ev in e.events if ev["type"] == "session.execution.failed"]
    assert failed and failed[-1]["data"]["error"]["type"] == "Spending limit reached"
    assert len(p.requests) == 1


def test_prune_history_shortens_old_tool_outputs_only():
    big = "x" * 40_000
    msgs = [ChatMessage("user", "start")]
    for i in range(12):
        msgs.append(ChatMessage("tool", big, tool_call_id=str(i), tool_name="read"))
    n = runmod.prune_history(msgs, context=100_000)
    assert n > 0
    tools = [m for m in msgs if m.role == "tool"]
    assert "characters of this old output were removed" in tools[0].text
    assert all(len(m.text) == 40_000 for m in tools[-runmod.PRUNE_KEEP:])
    small = [ChatMessage("user", "hi"), ChatMessage("tool", "short", tool_call_id="1")]
    assert runmod.prune_history(small, context=100_000) == 0


def test_manual_compaction_keeps_todos_and_goal(home, tmp_path):
    p = FakeProvider(["one", "two", "three", "four", "ANSWER: summary of the work"])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    for t in ("a", "b", "c", "d"):
        asyncio.run(run_prompt(e, tmp_path, t, sid=sid))
    e.set_todos(sid, [{"content": "keep me", "status": "pending"}])
    e.set_goal(sid, "the big goal", autopilot=False)
    assert asyncio.run(e.compact_now(sid)) is True
    msgs = e.store.list_messages(sid)
    comp = [m for m in msgs if m["type"] == "compaction"]
    assert len(comp) == 1 and msgs[0]["type"] == "user"  # the history stays; the summary sits where it happened
    assert len(msgs) == 4 * 2 + 1 and msgs[-5]["type"] == "compaction"  # before the four messages it keeps (half of eight)
    assert runmod.to_chat(msgs)[0].text.startswith("Summary of the conversation so far")
    msgs[0] = comp[0]  # the rest of this test reads the summary text
    assert "summary of the work" in msgs[0]["text"] and "keep me" in msgs[0]["text"] and "the big goal" in msgs[0]["text"]


def test_compaction_keeps_a_multi_line_summary_and_never_an_empty_one(home, tmp_path):
    p = FakeProvider(["one", "two", "three", "four", "Let me sum up.\nANSWER:\nThe user built a parser.\nFiles: parser.py, test_parser.py.\nLeft: docs."])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    for t in ("a", "b", "c", "d"):
        asyncio.run(run_prompt(e, tmp_path, t, sid=sid))
    assert asyncio.run(e.compact_now(sid)) is True
    text = next(m for m in e.store.list_messages(sid) if m["type"] == "compaction")["text"]
    assert "The user built a parser." in text and "Left: docs." in text and "Let me sum up" not in text

    p2 = FakeProvider(["one", "two", "three", "four", "ANSWER:"])
    e2 = make_engine(p2)
    sid2 = e2.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    for t in ("a", "b", "c", "d"):
        asyncio.run(run_prompt(e2, tmp_path, t, sid=sid2))
    before = len(e2.store.list_messages(sid2))
    assert asyncio.run(e2.compact_now(sid2)) is False
    assert len(e2.store.list_messages(sid2)) == before  # history untouched


# ---- worktrees ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_worktree_create_status_merge_remove(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")

    async def go():
        wt = await wtmod.create(str(repo), "Add feature")
        assert Path(wt["path"]).is_dir() and wt["branch"].startswith("afh/add-feature-")
        (Path(wt["directory"]) / "feature.txt").write_text("new\n")
        st = await wtmod.status(wt)
        assert st["dirty"] == ["feature.txt"] and st["ahead"] == 0
        assert (await wtmod.status(wt))["merged"] is False
        res = await wtmod.merge(wt, "Add feature")
        assert res["merged"] and res["committed"]
        assert (repo / "feature.txt").read_text() == "new\n"
        after = await wtmod.status(wt)
        assert after["ahead"] == 1 and after["merged"] is True and after["dirty"] == []
        await wtmod.remove(wt)
        assert not Path(wt["path"]).exists()

    asyncio.run(go())


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_worktree_thread_is_listed_under_its_project(home, tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    e = make_engine(FakeProvider([]))

    async def go():
        e.loop = asyncio.get_running_loop()
        s = await e.create_worktree_session(str(repo), title="Try idea")
        assert s["location"]["directory"] != str(repo) and s["project"] == str(repo)
        assert [x["id"] for x in e.store.list_sessions(str(repo))] == [s["id"]]
        assert "# Worktree" in e.system_prompt_for(s, e.agent_for(s))
        wt = e._afh(s["id"])["worktree"]
        report = await e._cleanup_worktrees([wt])  # clean: removed
        assert report[0]["kept"] is False and not Path(wt["path"]).exists()

    asyncio.run(go())


# ---- 1.5: the model drives goals and subagents; huge histories ---------------------------------------------


def test_model_sets_its_own_goal_and_achieves_it(home, tmp_path):
    p = FakeProvider([
        [("goal", {"status": "set", "text": "notes.txt lists three fruits", "criteria": "the file has 3 lines"})],
        [("write", {"path": "notes.txt", "content": "apple\nbanana\ncherry\n"})],
        [("goal", {"status": "achieved", "summary": "Wrote notes.txt", "evidence": "read it back: 3 lines"})],
        "Done.",
    ])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "write a fruits file"))
    g = e.goal(s["id"])
    assert g["status"] == "achieved" and g["by"] == "agent" and g["text"] == "notes.txt lists three fruits"
    assert "# Your harness: Agent Flow Harness" in p.requests[0].system and "**Goal**" in p.requests[0].system
    assert "# Goal of this thread" in p.requests[1].system  # the goal joins the prompt as soon as it is set


def test_goal_set_refuses_to_replace_an_active_goal(home, tmp_path):
    p = FakeProvider([[("goal", {"status": "set", "text": "something else"})], "ok"])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.set_goal(sid, "the user's goal", autopilot=False)
    asyncio.run(run_prompt(e, tmp_path, "go", sid=sid, agent={"todoNudge": False}))
    part = tool_results(e, sid)[0]
    assert part["state"]["status"] == "error" and "already has an active goal" in text_of(part)
    assert e.goal(sid)["text"] == "the user's goal"


def test_builtin_helper_subagent_in_build_mode_uses_the_thread_model(home, tmp_path):
    p = FakeProvider([
        [("subagent", {"agent": "general", "description": "Count files", "prompt": "Say how many files there are."}),
         ("subagent", {"agent": "general", "description": "Second task", "prompt": "Say hello."})],
        "child one reports", "child two reports",  # the two helpers answer (in either order)
        "Both helpers reported.",
    ])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "use helpers", agent={"todoNudge": False}))
    assert "subagent" in [t.name for t in p.requests[0].tools] and "`general` (Helper)" in p.requests[0].system
    kids = e.store.list_sessions(parent_id=s["id"])
    assert len(kids) == 2 and all(k["agent"] == "general" and k["model"] == {"providerID": "fake", "id": "m"} for k in kids)
    assert all("child" in text_of(x) for x in tool_results(e, s["id"]))
    # helpers get the harness prompt plus delegate rules, and no subagent/goal tools of their own
    child_req = p.requests[1]
    assert "# You are a delegate" in child_req.system and "subagent" not in [t.name for t in child_req.tools] and "goal" not in [t.name for t in child_req.tools]


def test_helper_can_be_turned_off(home, tmp_path):
    appstore.save_settings({"delegation": {"builtinHelper": False, "delegates": []}})
    p = FakeProvider(["hi"])
    e = make_engine(p)
    asyncio.run(run_prompt(e, tmp_path, "hello"))
    assert "subagent" not in [t.name for t in p.requests[0].tools]


def test_imported_thread_model_is_mapped_to_a_configured_provider(home, tmp_path):
    from afh import transfer

    e = make_engine(FakeProvider([]))
    payload = {"format": "afh-session", "info": {"title": "old", "model": {"providerID": "zai-coding-cn", "id": "M"}}, "messages": [{"type": "user", "text": "hi"}]}
    s = transfer.import_session(e, payload, str(tmp_path))
    assert s["model"] == {"id": "m", "providerID": "fake"}
    payload["info"]["model"] = {"providerID": "nowhere", "id": "unknown-model"}
    assert transfer.import_session(e, payload, str(tmp_path))["model"] is None
    # an old thread whose provider is gone still runs, on the default model
    sid = e.store.create_session(str(tmp_path), model={"providerID": "gone", "id": "x"})["id"]
    assert e.model_ref_for(e.store.get_session(sid), e.agent_for(e.store.get_session(sid))) == {"id": "m", "providerID": "fake"}


def test_huge_history_is_compacted_in_chunks_before_the_first_answer(home, tmp_path):
    big = "word " * 2000  # ~10k characters per message
    msgs = []
    for i in range(80):
        msgs.append({"type": "user", "text": f"request {i}: {big}"})
        msgs.append({"type": "assistant", "content": [{"type": "text", "text": f"answer {i}: {big}"}], "model": {"providerID": "fake", "id": "m"}})
    p = FakeProvider([])
    e = make_engine(p)
    e.models = {"fake": [ModelInfo(id="m", name="M", context=60_000, output=4096)]}  # 1.6M characters >> 60k tokens
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    for m in msgs:
        e.store.add_message(sid, m)
    p.replies = [f"ANSWER:\nPart summary {i}" for i in range(200)]

    async def go():
        e.loop = asyncio.get_running_loop()
        await e.prompt(sid, "continue")
        await e.runs[sid].task

    asyncio.run(go())
    stored = e.store.list_messages(sid)
    comp = [m for m in stored if m["type"] == "compaction"]
    assert len(comp) == 1 and comp[0]["text"].strip() and comp[0]["metadata"]["compacted"] > 100
    assert stored[0]["type"] == "user" and len(stored) > 160  # nothing deleted
    progress = [ev["data"] for ev in e.events if ev["type"] == "session.compaction.progress"]
    assert progress and progress[-1]["done"] == progress[-1]["total"] > 2  # several parts plus the merge
    final = p.requests[-1]
    assert runmod.estimate_tokens(final.messages, final.system) < 60_000


def test_fit_history_leaves_out_the_oldest_and_says_so():
    msgs = [ChatMessage("user", "x" * 40_000) for _ in range(10)] + [ChatMessage("user", "latest")]
    n = runmod.fit_history(msgs, context=20_000)
    assert n > 0 and msgs[-1].text == "latest" and "earlier messages of this conversation are not shown" in msgs[0].text
    assert runmod.estimate_tokens(msgs) <= 20_000


def test_a_three_step_plan_without_a_goal_gets_one_from_the_request(home, tmp_path):
    plan = {"todos": [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "pending"}, {"content": "c", "status": "pending"}]}
    p = FakeProvider([[("todo", plan)], [("goal", {"status": "set", "text": "sharper goal", "criteria": "tests pass"})], "ok"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "please add a parser module with tests", agent={"todoNudge": False}, goals={"autopilot": False}))
    parts = tool_results(e, s["id"])
    assert "AFH set this task as the thread's goal" in text_of(parts[0])
    g = e.goal(s["id"])
    assert g["text"] == "sharper goal" and g["by"] == "agent"  # the model may replace an automatic goal


def test_auto_goal_can_be_turned_off(home, tmp_path):
    plan = {"todos": [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "pending"}, {"content": "c", "status": "pending"}]}
    p = FakeProvider([[("todo", plan)], "ok"])
    e = make_engine(p)
    s = asyncio.run(run_prompt(e, tmp_path, "please add a parser module with tests", agent={"todoNudge": False}, goals={"auto": False}))
    assert e.goal(s["id"]) is None


# ---- 1.6: picking up after a restart ---------------------------------------------------------------------


def test_threads_cut_off_by_a_restart_resume_on_start(home, tmp_path):
    e = make_engine(FakeProvider([]))
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.store.add_message(sid, {"type": "user", "text": "build it"})
    e.store.add_message(sid, {"type": "assistant", "content": [{"type": "tool", "id": "c1", "name": "shell", "state": {"status": "running", "input": {"command": "x"}}}],
                              "time": {"created": 1, "completed": 2}, "finish": "tool-calls", "model": {"providerID": "fake", "id": "m"}})
    e.store.touch(sid)  # a run started and never finished
    done = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"})["id"]
    e.store.add_message(done, {"type": "user", "text": "hi"})
    e.store.add_message(done, {"type": "assistant", "content": [{"type": "text", "text": "hello"}], "time": {"created": 1, "completed": 2}, "finish": "stop"})
    e.store.touch(done)  # its run ended but idle was never written (killed right at the end)
    e2 = make_engine(FakeProvider(["Picked it up, all done."]))  # a fresh process on the same database
    e2.store = e.store

    async def go():
        e2.loop = asyncio.get_running_loop()
        resumed = await e2.resume_interrupted()
        for s_id in resumed:
            await e2.runs[s_id].task
        return resumed

    assert asyncio.run(go()) == [sid]
    msgs = e2.store.list_messages(sid)
    assert msgs[1]["content"][0]["state"]["status"] == "error" and "restarted" in msgs[1]["content"][0]["state"]["error"]["message"]
    assert msgs[2]["type"] == "synthetic" and msgs[2]["metadata"]["notice"] == "resume"
    assert msgs[-1]["type"] == "assistant" and msgs[-1]["content"][0]["text"] == "Picked it up, all done."
    assert e2.store.get_session(done)["time"].get("idle")  # a finished thread is only marked idle, not re-run


def test_imported_threads_are_never_resumed(home, tmp_path):
    from afh import transfer

    e = make_engine(FakeProvider(["should not run"]))
    payload = {"format": "afh-session", "info": {"title": "old"}, "messages": [{"type": "user", "text": "an old question", "time": {"created": 1000}}]}
    transfer.import_session(e, payload, str(tmp_path))

    async def go():
        e.loop = asyncio.get_running_loop()
        return await e.resume_interrupted()

    assert asyncio.run(go()) == []


def test_models_get_real_facts_from_models_dev(home):
    from afh.engine import modelsdev

    modelsdev._data = None
    p = {"catalog": "zai-coding", "fetch_models": False}
    glm = {m.id: m for m in provcfg.models_of(p, "zai-coding")}["glm-5.3"]
    assert glm.context >= 1_000_000 and glm.variants == ["low", "high", "max"] and glm.reasoning
    kimi = {m.id: m for m in provcfg.models_of({"catalog": "kimi", "fetch_models": False}, "kimi")}["k3.1-pro"]
    assert kimi.context >= 1_000_000 and "image" in kimi.input and "video" in kimi.input
    # an id the endpoint reports (custom provider) is enriched from the maker's own listing
    custom = provcfg.models_of({"fetched": [{"id": "claude-opus-5-5", "context": 200000}]}, "my-gateway")[0]
    assert custom.context >= 1_000_000 and "xhigh" in custom.variants
    # the user's own correction wins
    fixed = {m.id: m for m in provcfg.models_of({"catalog": "zai-coding", "overrides": {"glm-5.3": {"context": 123456, "variants": ["high"]}}}, "zai-coding")}["glm-5.3"]
    assert fixed.context == 123456 and fixed.variants == ["high"]


def test_a_second_compaction_summarises_from_the_first_and_keeps_everything(home, tmp_path):
    p = FakeProvider(["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10"])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    for t in "abcde":
        asyncio.run(run_prompt(e, tmp_path, t, sid=sid))
    p.replies = ["ANSWER:\nfirst summary of a to c"]
    assert asyncio.run(e.compact_now(sid)) is True
    p.replies = ["r6", "r7", "r8", "r9"]
    for t in "fghi":
        asyncio.run(run_prompt(e, tmp_path, t, sid=sid))
    p.replies = ["ANSWER:\nsecond summary"]
    assert asyncio.run(e.compact_now(sid)) is True
    msgs = e.store.list_messages(sid)
    assert [m["text"] for m in msgs if m["type"] == "user"] == list("abcdefghi")  # every message is still there
    assert sum(1 for m in msgs if m["type"] == "compaction") == 2
    assert "first summary" in p.requests[-1].messages[0].text  # the second summary was built on the first
    chat = runmod.to_chat(msgs)
    assert "second summary" in chat[0].text and "first summary" not in "".join(c.text for c in chat)


def test_finished_lists_and_achieved_goals_are_kept_in_history(home, tmp_path):
    p = FakeProvider([
        [("todo", {"todos": [{"content": "Write code", "status": "completed"}, {"content": "Test it", "status": "completed"}]})],
        [("goal", {"status": "achieved", "summary": "Shipped"})],
        "All done.",
    ])
    e = make_engine(p)
    sid = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.set_goal(sid, "ship it", "", autopilot=False, max_turns=5)
    asyncio.run(run_prompt(e, tmp_path, "go", sid=sid))
    afh = e.store.get_session(sid)["metadata"]["afh"]
    assert [t["content"] for t in afh["todoHistory"][0]["todos"]] == ["Write code", "Test it"] and afh["todoHistory"][0]["completed"]
    assert afh["goalHistory"][0]["text"] == "ship it" and afh["goalHistory"][0]["summary"] == "Shipped"
    # the same finished list reported again is not stored twice
    e.set_todos(sid, afh["todoHistory"][0]["todos"])
    assert len(e.store.get_session(sid)["metadata"]["afh"]["todoHistory"]) == 1
    ev = [x for x in e.events if x["type"] == "session.goal.updated" and x["data"].get("history")]
    assert ev and ev[-1]["data"]["history"][0]["text"] == "ship it"
