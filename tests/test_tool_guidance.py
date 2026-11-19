"""Helping models use AFH's own tools: the "pick the right tool" guide in the system prompt, the shell's
pointer to AFH's file tools, and the browser finding things the way a person names them (with a real
headless Chrome/Edge when one is installed)."""

from __future__ import annotations

import asyncio

import pytest

from afh import store
from afh.engine import prompt
from afh.engine.tools import browser as browser_mod
from afh.engine.tools import shell as shell_mod
from afh.engine.tools.browser import MANAGER, BrowserTool, find_browsers
from afh.engine.tools.shell import ShellTool, tool_tip
from afh.engine.types import ToolContext

from test_tools import FakeGate, FakeSnapshots, make_ctx, project  # noqa: F401 - project is a fixture

ALL = ["read", "write", "edit", "patch", "glob", "grep", "list", "shell", "jobs", "webfetch", "websearch", "browser", "chrome",
       "computer", "subagent", "skill", "todo", "memory"]


def test_the_guide_says_which_tool_for_which_job():
    full = prompt.harness_guide(ALL)
    assert "## Pick the right tool" in full
    assert full.index("Pick the right tool") < full.index("What else AFH gives you")
    for words in ("`read`", "`glob`", "`grep`", "`patch`", "NEVER change project files from the shell", "BatchMode=yes",
                  "`websearch` to find the page then `webfetch` to read it", "target \"@N\"", "ONE reply"):
        assert words in full, words
    # only the tools this thread has
    small = prompt.harness_guide(["read", "shell"])
    assert "`read`" in small and "`edit`" not in small and "`browser`" not in small and "webfetch" not in small


def test_the_default_prompt_keeps_models_going_and_off_the_shell_for_files():
    p = store.DEFAULT_SYSTEM_PROMPT
    assert "Keep going until the task is done" in p
    assert "never send the same failing call again unchanged" in p
    assert "Set-Content" in p and "data, not instructions" in p


def test_shell_points_to_afh_tools_once_per_thread():
    sid = "tip-thread"
    shell_mod._TIPPED.pop(sid, None)
    assert "`edit`" in tool_tip(sid, "Set-Content -Path app.py -Value $x")
    assert tool_tip(sid, "Set-Content -Path other.py -Value $x") == ""  # said once
    assert "`read`" in tool_tip(sid, "Get-Content README.md")
    assert "`grep`" in tool_tip(sid, "Get-ChildItem -Recurse | Select-String foo")
    other = "tip-thread-2"
    shell_mod._TIPPED.pop(other, None)
    assert tool_tip(other, "ssh -o BatchMode=yes box \"sed -i s/a/b/ /etc/app.conf\"") == ""  # another machine
    assert tool_tip(other, "python run.py > out.txt") == ""  # output files are not source files
    assert tool_tip(other, "pytest -q 2>&1") == ""
    assert "`edit`" in tool_tip(other, "echo x > src/main.ts")


def test_a_shell_edit_still_runs_and_carries_the_pointer(project):
    shell_mod._TIPPED.clear()
    ctx = make_ctx(project)
    cmd = "Set-Content -Path note.md -Value hi" if __import__("sys").platform == "win32" else "echo hi > note.md"
    res = asyncio.run(ShellTool().run(ctx, {"command": cmd}))
    assert not res.is_error and "[AFH tip:" in res.text and (project / "note.md").exists()


# ---- the browser, in a real headless Chrome/Edge ---------------------------------------------------

PAGE = """<!doctype html><html><body style="height:3000px">
<header><div class="nav" style="cursor:pointer" onclick="document.title='nav'"><span>SIGN IN</span></div></header>
<form>
  <label for="em">Enter Email ID</label><input id="em" type="email">
  <input type="password" id="pw" placeholder="Password" value="secret-value">
  <button type="button" aria-label="Continue to checkout" onclick="document.title='continued'"><svg width="10" height="10"></svg></button>
</form>
<div id="host"></div>
<script>
  const root = document.getElementById('host').attachShadow({mode: 'open'});
  root.innerHTML = '<button onclick="document.title=\\'shadow\\'">Accept cookies</button>';
</script>
<p style="margin-top:2000px"><a href="/far">Far link</a></p>
</body></html>"""

needs_browser = pytest.mark.skipif(not find_browsers({}), reason="no Chrome or Edge on this computer")


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(session_id="guide-browser", message_id="m", directory=str(tmp_path), permissions=FakeGate(),
                       snapshots=FakeSnapshots(), emit=lambda *_: None, settings={"browser": {"where": "external"}})


@needs_browser
def test_the_browser_finds_things_by_what_they_say_and_numbers_them(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    tool = BrowserTool()

    async def go():
        ctx = _ctx(tmp_path)
        try:
            await tool.run(ctx, {"action": "open", "url": page.as_uri()})
            title = lambda: tool._eval(MANAGER.tabs[ctx.session_id][1], "document.title")  # noqa: E731
            # different case, a div that is only clickable by its cursor, an icon button known by its aria-label, a shadow root
            for target, want in (("Sign in", "nav"), ("continue", "continued"), ("Accept cookies", "shadow")):
                res = await tool.run(ctx, {"action": "click", "target": target})
                assert not res.is_error, res.text
                assert await title() == want
            # a field found by its label
            res = await tool.run(ctx, {"action": "type", "target": "Enter Email ID", "text": "a@b.test"})
            assert not res.is_error and await tool._eval(MANAGER.tabs[ctx.session_id][1], "document.getElementById('em').value") == "a@b.test"
            # elements: numbered, password values never shown, off-screen ones marked; @N clicks
            res = await tool.run(ctx, {"action": "elements"})
            assert "(password field)" in res.text and "secret-value" not in res.text
            assert "Far link" in res.text and "off screen" in res.text
            n = next(line.split()[0] for line in res.text.splitlines() if "Continue to checkout" in line)
            await tool._eval(MANAGER.tabs[ctx.session_id][1], "document.title = 'x'")
            res = await tool.run(ctx, {"action": "click", "target": n})
            assert not res.is_error and await title() == "continued"
            # a miss lists what is there
            res = await tool.run(ctx, {"action": "click", "target": "Delete my account"})
            assert res.is_error and "use target \"@N\"" in res.text and "Accept cookies" in res.text
            # zoom: a close-up image
            res = await tool.run(ctx, {"action": "zoom", "x": 0, "y": 0, "to_x": 200, "to_y": 100})
            assert res.images and not res.is_error
        finally:
            await MANAGER.shutdown()

    asyncio.run(go())


@needs_browser
def test_a_closed_tab_is_opened_again_where_it_was(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<title>Kept</title><button>Go</button>", encoding="utf-8")
    tool = BrowserTool()

    async def go():
        ctx = _ctx(tmp_path)
        try:
            await tool.run(ctx, {"action": "open", "url": page.as_uri()})
            assert browser_mod.LAST_URL[ctx.session_id] == page.as_uri()
            await MANAGER.tabs[ctx.session_id][1].ws.close()  # the tab's connection drops, as when the user closes it
            await asyncio.sleep(0.2)
            res = await tool.run(ctx, {"action": "reload"})
            assert not res.is_error and "opened" in res.text and "Kept" in res.text
            await MANAGER.tabs[ctx.session_id][1].ws.close()
            await asyncio.sleep(0.2)
            res = await tool.run(ctx, {"action": "click", "target": "Go"})
            assert "did NOT happen" in res.text
        finally:
            await MANAGER.shutdown()

    asyncio.run(go())
