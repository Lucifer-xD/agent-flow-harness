"""The terminal app, end to end: the real app driven by key presses, a real backend, a scripted model."""
import asyncio
import json
import re
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

pytest.importorskip("textual")

import test_cli  # noqa: E402
from test_cli import Model, environment, start_app, stop_app  # noqa: E402

from afh import cli  # noqa: E402
from afh.tui import themes  # noqa: E402
from afh.tui.app import AFH  # noqa: E402
from afh.tui.commands import COMMANDS, LOCAL  # noqa: E402
from afh.tui.dialogs import Approval, Confirm, Form, Picker, Prompt, Question, Viewer, fuzzy  # noqa: E402
from afh.tui.settings import TABS, Panes, SettingsScreen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
plain_script = test_cli.script_for


def script_for(messages: list[dict], model: str = "") -> dict:
    last = next(m for m in reversed(messages) if m.get("role") == "user")
    text = last["content"] if isinstance(last["content"], str) else json.dumps(last["content"])
    if messages[-1].get("role") == "tool":
        return {"text": "All done."}
    if "ASKME" in text:
        return {"tool": ("question", {"questions": [{"question": "Which color?", "options": [{"label": "Red"}, {"label": "Blue"}]}]})}
    if "PLAN" in text:
        return {"tool": ("todo", {"todos": [{"content": "First step", "status": "completed"}, {"content": "Second step", "status": "in_progress"}]})}
    if "HELPER" in text:
        return {"tool": ("subagent", {"agent": "general", "description": "Look into it", "prompt": "say hello"})}
    if "SLOW" in text:
        return {"tool": ("shell", {"command": "ping -n 30 127.0.0.1" if test_cli.os.name == "nt" else "sleep 30"})}
    if "SEEN-SHELL" in text:
        return {"text": "shell-output-seen" if "marker-from-shell" in json.dumps(messages) else "shell-output-missing"}
    return plain_script(messages, model)


@pytest.fixture(scope="module")
def backend(tmp_path_factory):
    test_cli.script_for = script_for
    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = tmp_path_factory.mktemp("afh-tui-home")
    proc, url, token = start_app(environment(home))
    headers = {"x-afh-token": token}
    r = httpx.post(f"{url}/api/providers", headers=headers, timeout=30, trust_env=False, json={
        "id": "demo", "name": "Demo", "kind": "openai", "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1", "api_key": "x",
        "models": [{"id": "demo-model", "name": "Demo model", "context": 200000, "output": 16000}, {"id": "demo-two", "name": "Demo two", "context": 200000, "output": 16000}]})
    assert r.status_code < 300, r.text
    httpx.put(f"{url}/api/settings", headers=headers, timeout=30, trust_env=False, json={"defaultModel": {"providerID": "demo", "id": "demo-model"}})
    found = json.loads((home / "api.json").read_text(encoding="utf-8"))  # how the app is really reached: the discovery file
    yield {"url": found["url"], "token": token, "key": found["key"], "home": home}
    stop_app(proc)
    server.shutdown()
    test_cli.script_for = plain_script


def screen_text(app) -> str:
    strips = app.screen._compositor.render_strips()
    return "\n".join("".join(seg.text for seg in strip) for strip in strips)


async def until(pilot, check, secs: float = 20, what: str = "") -> None:
    end = time.time() + secs
    while time.time() < end:
        await pilot.pause(0.05)
        if check():
            return
    raise AssertionError(f"timed out waiting for {what or check}\n{screen_text(pilot.app)}")


async def shows(pilot, text: str, secs: float = 20) -> None:
    await until(pilot, lambda: text in screen_text(pilot.app), secs, repr(text))


async def type_in(pilot, text: str) -> None:
    await pilot.press(*["space" if c == " " else c for c in text])


async def send(pilot, text: str) -> None:
    pilot.app.composer.set_text(text)
    await pilot.pause()
    await pilot.press("enter")


def play(backend, project, script, size=(100, 32), **kw) -> None:
    async def go() -> None:
        client = cli.Client(backend["url"], backend["key"])
        events = cli.Events(client)
        app = AFH(client, events, str(project), home=backend["home"], **kw)
        async with app.run_test(size=size) as pilot:
            await until(pilot, lambda: app.boot and app.scroller.query("#home") or app.thread, what="the app to start")
            await script(app, pilot)
            for w in app.workers:
                w.cancel()

    asyncio.run(asyncio.wait_for(go(), 90))


def test_start_screen_shows_where_you_are(backend, tmp_path):
    async def script(app, pilot):
        await shows(pilot, "Demo model")
        await shows(pilot, tmp_path.name[:12])
        assert "commands" in screen_text(app)

    play(backend, tmp_path, script)


def test_a_message_gets_a_reply(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "say hello")
        await shows(pilot, "Hello from the mock.")
        await until(pilot, lambda: not app.thread.busy)
        assert "say hello" in screen_text(app)

    play(backend, tmp_path, script)


def test_tool_rows_and_approval(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "WRITE the file")
        await until(pilot, lambda: isinstance(app.screen, Approval), what="the approval")
        await pilot.press("y")
        await shows(pilot, "All done.")
        assert (tmp_path / "hello.txt").read_text() == "hi\n"
        await shows(pilot, "hello.txt")

    play(backend, tmp_path, script)


def test_saying_no_to_an_approval(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "WRITE the file")
        await until(pilot, lambda: isinstance(app.screen, Approval), what="the approval")
        await pilot.press("n")
        await pilot.press("enter")
        await until(pilot, lambda: not app.thread.busy)
        assert not (tmp_path / "hello.txt").exists()

    play(backend, tmp_path, script)


def test_question_card(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "ASKME something")
        await until(pilot, lambda: isinstance(app.screen, Question), what="the question")
        await shows(pilot, "Which color?")
        await pilot.press("down", "enter")
        await shows(pilot, "All done.")

    play(backend, tmp_path, script)


def test_todo_list_shows_above_the_box(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "PLAN it")
        await shows(pilot, "Second step")
        await shows(pilot, "1/2")

    play(backend, tmp_path, script, mode="full")


def test_escape_stops_a_run(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "SLOW down")
        await until(pilot, lambda: app.thread and app.thread.busy and any(m.get("type") == "assistant" for m in app.thread.messages), what="the run")
        await pilot.pause(1)
        await pilot.press("escape")
        await until(pilot, lambda: not app.thread.busy, what="the stop")

    play(backend, tmp_path, script, mode="full")


def test_slash_menu_filters_and_tab_completes(backend, tmp_path):
    async def script(app, pilot):
        await type_in(pilot, "/mod")
        await until(pilot, lambda: app.composer.menu_open(), what="the menu")
        await shows(pilot, "/model")
        await pilot.press("escape")
        await until(pilot, lambda: not app.composer.menu_open())
        app.composer.clear()
        await type_in(pilot, "/hel")
        await until(pilot, lambda: app.composer.menu_open())
        await pilot.press("tab")
        await until(pilot, lambda: app.composer.text.startswith("/help"))

    play(backend, tmp_path, script)


def test_at_finds_files(backend, tmp_path):
    (tmp_path / "notes.md").write_text("x")

    async def script(app, pilot):
        await type_in(pilot, "look at @no")
        await shows(pilot, "notes.md")
        await pilot.press("tab")
        await until(pilot, lambda: "@notes.md" in app.composer.text)

    play(backend, tmp_path, script)


def test_model_picker_changes_the_model(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "/model")
        await until(pilot, lambda: isinstance(app.screen, Picker), what="the picker")
        await type_in(pilot, "two")
        await pilot.pause(0.1)
        await pilot.press("enter")
        await until(pilot, lambda: (app.model_ref() or {}).get("id") == "demo-two", what="the change")
        await shows(pilot, "Demo two")

    play(backend, tmp_path, script)


def test_tab_and_shift_tab_change_agent_and_approvals(backend, tmp_path):
    async def script(app, pilot):
        before = app.agent_id()
        await pilot.press("tab")
        await until(pilot, lambda: app.agent_id() != before)
        await pilot.press("shift+tab")
        await until(pilot, lambda: app.mode_id() == "full")
        await shows(pilot, "full access")

    play(backend, tmp_path, script)


def test_undo_rewinds_files_and_redo_puts_them_back(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "WRITE the file")
        await shows(pilot, "All done.")
        await until(pilot, lambda: not app.thread.busy)
        assert (tmp_path / "hello.txt").exists()
        await send(pilot, "/undo")
        await until(pilot, lambda: isinstance(app.screen, Picker), what="the undo list")
        await pilot.press("enter")
        await until(pilot, lambda: not (tmp_path / "hello.txt").exists(), what="the rewind")
        await until(pilot, lambda: app.composer.text.startswith("WRITE"), what="the text back in the box")
        app.composer.clear()
        await send(pilot, "/redo")
        await until(pilot, lambda: (tmp_path / "hello.txt").exists(), what="the redo")

    play(backend, tmp_path, script, mode="full")


def test_shell_line_reaches_the_model(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "!echo marker-from-shell")
        await shows(pilot, "marker-from-shell")
        await send(pilot, "SEEN-SHELL?")
        await shows(pilot, "shell-output-seen")

    play(backend, tmp_path, script)


def test_threads_picker_opens_a_thread(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "say hello")
        await shows(pilot, "Hello from the mock.")
        await until(pilot, lambda: not app.thread.busy)
        sid = app.thread.id
        await send(pilot, "/new")
        await until(pilot, lambda: app.thread is None)
        await pilot.press("ctrl+k")
        await until(pilot, lambda: isinstance(app.screen, Picker), what="the thread list")
        await pilot.pause(0.2)
        await pilot.press("enter")
        await until(pilot, lambda: app.thread and app.thread.id == sid, what="the thread")
        await shows(pilot, "Hello from the mock.")

    play(backend, tmp_path, script)


def test_palette_finds_things(backend, tmp_path):
    async def script(app, pilot):
        await pilot.press("ctrl+p")
        await until(pilot, lambda: isinstance(app.screen, Picker), what="the palette")
        await type_in(pilot, "personaliz")
        await shows(pilot, "Personalization")
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, SettingsScreen), what="settings")
        await shows(pilot, "Your name")

    play(backend, tmp_path, script)


def test_help_viewer(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "?")
        await until(pilot, lambda: isinstance(app.screen, Viewer), what="help")
        await shows(pilot, "Esc Esc")
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, Viewer))

    play(backend, tmp_path, script)


def test_every_thread_command_opens_without_an_error(backend, tmp_path):
    """Each command against a real thread: it must draw, not crash or show an API error."""

    async def script(app, pilot):
        await send(pilot, "WRITE the file")
        await shows(pilot, "All done.")
        await until(pilot, lambda: not app.thread.busy)
        failures = []
        app.fail = lambda err: failures.append(str(err))
        for name in ("diff", "cost", "prompt", "context", "jobs", "memory", "todo", "goal", "status", "images", "helpers", "worktree", "theme", "agent", "mode", "connect", "race"):
            await send(pilot, f"/{name}")
            await pilot.pause(0.6)
            for _ in range(4):
                if app.screen is app.main_screen:
                    break
                await pilot.press("escape")
                await pilot.pause(0.15)
            assert app.screen is app.main_screen, name
            assert not failures, (name, failures)

    play(backend, tmp_path, script, mode="full")


def test_every_settings_section_loads(backend, tmp_path):
    async def script(app, pilot):
        await pilot.press("f2")
        await until(pilot, lambda: isinstance(app.screen, SettingsScreen), what="settings")
        screen = app.screen
        for tid, label in TABS:
            rows = await getattr(Panes(screen), f"pane_{tid}")()
            assert rows, tid
            screen.tab = tid
            await screen.draw()
            await pilot.pause(0.02)
            assert label in screen_text(app), label
            assert not any("Couldn't load" in r.label for r in rows), tid

    play(backend, tmp_path, script, size=(120, 40))


def test_a_settings_toggle_saves(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "/settings general")
        await until(pilot, lambda: isinstance(app.screen, SettingsScreen), what="settings")
        await shows(pilot, "Ask before deleting")
        screen = app.screen
        at = next(i for i, r in enumerate(screen.rows) if "Ask before deleting" in r.label)
        box = screen.query_one("#rows")
        box.highlighted = at
        before = app.setting("confirmDelete", True)
        await pilot.press("enter")
        await until(pilot, lambda: app.setting("confirmDelete", True) != before, what="the save")
        saved = httpx.get(f"{backend['url']}/api/settings", headers={"x-afh-token": backend["token"]}, trust_env=False).json()
        assert saved["ui"]["confirmDelete"] == (not before)

    play(backend, tmp_path, script)


def test_narrow_terminal_still_works(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "say hello")
        await shows(pilot, "Hello from the mock.")

    play(backend, tmp_path, script, size=(80, 24))


def test_ctrl_c_clears_then_quits(backend, tmp_path):
    async def script(app, pilot):
        await type_in(pilot, "abc")
        await pilot.press("ctrl+c")
        await until(pilot, lambda: not app.composer.text)
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+c")
        await until(pilot, lambda: not app.is_running or app._exit, what="the exit")

    play(backend, tmp_path, script)


def test_goal_from_the_dialog_starts_work(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "say hello")
        await shows(pilot, "Hello from the mock.")
        await until(pilot, lambda: not app.thread.busy)
        await send(pilot, "/goal")
        await until(pilot, lambda: isinstance(app.screen, Form), what="the goal form")
        app.screen.query_one("#f-text").text = "Ship the thing"
        await pilot.press("ctrl+s")
        await shows(pilot, "Ship the thing")
        await until(pilot, lambda: not app.thread.busy, 30)
        assert app.thread.goal["text"] == "Ship the thing"

    play(backend, tmp_path, script)


def test_a_message_sent_during_a_run_is_queued(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "SLOW down")
        await until(pilot, lambda: app.thread and any(m.get("type") == "assistant" for m in app.thread.messages), what="the run")
        await send(pilot, "and then this")
        await shows(pilot, "and then this")
        await pilot.press("escape")
        await until(pilot, lambda: not app.thread.busy, 30, "the stop")

    play(backend, tmp_path, script, mode="full")


def test_thread_tools(backend, tmp_path):
    async def script(app, pilot):
        failures = []
        app.fail = lambda err: failures.append(str(err))
        await send(pilot, "say hello")
        await shows(pilot, "Hello from the mock.")
        await until(pilot, lambda: not app.thread.busy)
        first = app.thread.id
        await send(pilot, "/rename A better name")
        await shows(pilot, "A better name")
        await send(pilot, "/export")
        await until(pilot, lambda: list(tmp_path.glob("*.afh-session.json")), what="the export")
        await send(pilot, "/fork")
        await until(pilot, lambda: app.thread and app.thread.id != first, what="the fork")
        await shows(pilot, "Hello from the mock.")
        fork = app.thread.id
        await send(pilot, "/remember Tests use pytest")
        await pilot.pause(0.3)
        memory = httpx.get(f"{backend['url']}/api/projects/memory", params={"directory": str(tmp_path)}, headers={"x-afh-token": backend["token"]}, trust_env=False).json()
        assert "Tests use pytest" in memory["text"]
        await send(pilot, "/delete")
        await until(pilot, lambda: isinstance(app.screen, Confirm), what="the question")
        await pilot.press("y")
        await until(pilot, lambda: app.thread is None, what="the delete")
        ids = [x["id"] for x in httpx.get(f"{backend['url']}/api/sessions", params={"directory": str(tmp_path)}, headers={"x-afh-token": backend["token"]}, trust_env=False).json()]
        assert fork not in ids and first in ids
        assert not failures, failures

    play(backend, tmp_path, script)


def test_helper_shows_as_a_card_and_can_be_watched(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "HELPER please")
        await shows(pilot, "Look into it", 30)
        await until(pilot, lambda: not app.thread.busy, 30, "the run")
        parent = app.thread.id
        await send(pilot, "/helpers")
        await until(pilot, lambda: isinstance(app.screen, Picker), what="the helpers")
        await pilot.pause(0.1)
        await pilot.press("enter")
        await until(pilot, lambda: app.thread and app.thread.id != parent, what="the helper's thread")
        await send(pilot, "/back")
        await until(pilot, lambda: app.thread and app.thread.id == parent, what="the way back")

    play(backend, tmp_path, script, mode="full")


def test_todo_editor(backend, tmp_path):
    async def script(app, pilot):
        await send(pilot, "say hello")
        await shows(pilot, "Hello from the mock.")
        await until(pilot, lambda: not app.thread.busy)
        await send(pilot, "/todo")
        await until(pilot, lambda: isinstance(app.screen, Picker), what="the list")
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Prompt), what="the prompt")
        await type_in(pilot, "A step")
        await pilot.press("enter")
        await until(pilot, lambda: app.thread.todos, what="the save")
        await pilot.press("escape")
        await shows(pilot, "A step")

    play(backend, tmp_path, script)


def test_fuzzy_ranks_exact_first():
    assert fuzzy("mod", "model") > fuzzy("mod", "my old dog")
    assert fuzzy("xyz", "model") is None


def test_same_settings_sections_as_the_app():
    source = (ROOT / "web/js/settings.js").read_text(encoding="utf-8")
    app_tabs = re.findall(r'\["([a-z]+)", "[^"]+", "[a-z]+"\]', source[source.index("const TABS"):source.index("];", source.index("const TABS"))])
    assert app_tabs and app_tabs == [t for t, _ in TABS]
    assert all(hasattr(Panes, f"pane_{t}") for t in app_tabs)


def test_same_themes_as_the_app():
    source = (ROOT / "web/js/appearance.js").read_text(encoding="utf-8")
    ids = set(re.findall(r"^\s*\{ id: \"([a-z0-9-]+)\"", source, re.M)) or set(re.findall(r"^\s*\"?([a-z0-9-]+)\"?: \{ name:", source, re.M))
    assert ids and ids <= set(themes.PRESETS)


def test_every_app_command_exists_here():
    wanted = "help new clear resume sessions threads model agent mode connect compact undo redo diff cost goal todo memory remember jobs theme thinking details export import editor status update bug exit quit settings rename fork archive delete copy context prompt worktree usage live helpers approvals images race remote".split()
    assert set(wanted) <= LOCAL
    from afh.tui.actions import Actions

    for c in [*COMMANDS, *[{"name": x} for x in wanted]]:
        assert hasattr(Actions, f"cmd_{c['name']}"), c["name"]


def test_screens_used_here_exist():
    assert Confirm and Prompt
