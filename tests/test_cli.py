"""The afh command, end to end: real processes against a scripted model."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from afh import cli

ROOT = Path(__file__).resolve().parent.parent
RUN = [sys.executable, str(ROOT / "run.py")]


def script_for(messages: list[dict], model: str = "") -> dict:
    """What the scripted model does next: the first keyword of the latest user message picks it."""
    if messages[-1].get("role") == "tool":
        return {"text": "All done."}
    last = next(m for m in reversed(messages) if m.get("role") == "user")
    text = last["content"] if isinstance(last["content"], str) else json.dumps(last["content"])
    if "RACE" in text:
        return {"tool": ("write", {"path": "answer.txt", "content": f"from {model}\n"})}
    if "WRITE" in text:
        return {"tool": ("write", {"path": "hello.txt", "content": "hi\n"})}
    if "SHELL" in text:
        return {"tool": ("shell", {"command": "echo from-shell"})}
    if "BOOM" in text:
        return {"status": 400}
    if "PIPED-TEXT" in text:
        return {"text": "Saw the piped text."}
    return {"text": "Hello from the mock."}


class Model(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.reply(200, "application/json", json.dumps({"data": [{"id": "demo-model"}]}))

    def reply(self, status: int, kind: str, body: str):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        step = script_for(body["messages"], body.get("model", ""))
        if step.get("status"):
            return self.reply(step["status"], "application/json", json.dumps({"error": {"message": "scripted failure"}}))
        if not body.get("stream"):
            return self.reply(200, "application/json", json.dumps({"id": "x", "object": "chat.completion", "model": "demo-model", "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "A title"}}]}))

        def chunk(delta: dict, finish=None) -> str:
            return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "model": "demo-model",
                                          "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

        out = chunk({"role": "assistant"})
        if "tool" in step:
            name, args = step["tool"]
            out += chunk({"tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})
            out += chunk({}, "tool_calls")
        else:
            out += chunk({"content": step["text"]}) + chunk({}, "stop")
        self.reply(200, "text/event-stream", out + "data: [DONE]\n\n")


@pytest.fixture(scope="module")
def model():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def environment(home: Path) -> dict:
    return {**os.environ, "AFH_HOME": str(home), "USERPROFILE": str(home), "HOME": str(home), "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}


def start_app(env: dict) -> tuple[subprocess.Popen, str, str]:
    proc = subprocess.Popen([*RUN, "--headless"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8")
    for line in proc.stdout:
        m = re.search(r"(http://127\.0\.0\.1:\d+)/#token=(\S+)", line)
        if m:
            threading.Thread(target=proc.stdout.read, daemon=True).start()
            return proc, m.group(1), m.group(2)
    raise AssertionError("the backend never started")


def stop_app(proc: subprocess.Popen) -> None:
    cli.stop_process(proc) if os.name != "nt" else subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def home(model, tmp_path_factory):
    """A profile with the scripted model set up, and no app running."""
    home = tmp_path_factory.mktemp("afh-home")
    proc, url, token = start_app(environment(home))
    try:
        r = httpx.post(f"{url}/api/providers", headers={"x-afh-token": token}, timeout=30, trust_env=False, json={
            "id": "demo", "name": "Demo", "kind": "openai", "base_url": model, "api_key": "x",
            "models": [{"id": "demo-model", "name": "Demo model", "context": 200000, "output": 16000},
                       {"id": "demo-two", "name": "Demo two", "context": 200000, "output": 16000}]})
        assert r.status_code < 300, r.text
        httpx.put(f"{url}/api/settings", headers={"x-afh-token": token}, timeout=30, trust_env=False,
                  json={"defaultModel": {"providerID": "demo", "id": "demo-model"}})
    finally:
        stop_app(proc)
    (home / "api.json").unlink(missing_ok=True)
    return home


@pytest.fixture
def project(tmp_path):
    return tmp_path


def afh(home: Path, project: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*RUN, "cli", *args], cwd=project, env=environment(home), capture_output=True, text=True, encoding="utf-8",
                          input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL, timeout=120)


def test_answer_goes_to_stdout_and_progress_to_stderr(home, project):
    r = afh(home, project, "run", "say hello")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Hello from the mock."
    assert "files changed" in r.stderr


def test_json_events_and_a_result_line(home, project):
    r = afh(home, project, "run", "--json", "--mode", "full", "WRITE the file")
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in r.stdout.splitlines()]
    assert any(e.get("type") == "session.tool.called" for e in lines)
    result = lines[-1]
    assert result["type"] == "result" and result["ok"] is True and result["reply"] == "All done."
    assert (project / "hello.txt").read_text() == "hi\n"
    assert any("hello.txt" in str(f) for f in result["changedFiles"])


def test_nobody_to_approve_means_refused_not_stuck(home, project):
    r = afh(home, project, "run", "--mode", "ask", "WRITE the file")
    assert r.returncode == 0, r.stderr
    assert "nobody here to approve" in r.stderr
    assert not (project / "hello.txt").exists()


def test_read_mode_cannot_write(home, project):
    r = afh(home, project, "run", "--mode", "read", "WRITE the file")
    assert r.returncode == 0, r.stderr
    assert not (project / "hello.txt").exists()


def test_shell_tool_runs_in_full_mode(home, project):
    r = afh(home, project, "run", "--json", "--mode", "full", "SHELL please")
    assert r.returncode == 0, r.stderr
    assert "from-shell" in r.stdout


def test_piped_text_joins_the_prompt(home, project):
    r = afh(home, project, "run", "-q", "look at this", stdin="PIPED-TEXT")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Saw the piped text."


def test_a_failed_run_exits_1(home, project):
    r = afh(home, project, "run", "BOOM")
    assert r.returncode == 1
    assert "Failed" in r.stderr


@pytest.mark.parametrize("args", [["run"], ["run", "--mode", "bad", "x"], ["run", "-m", "noslash", "x"]])
def test_usage_errors_exit_2(home, project, args):
    assert afh(home, project, *args).returncode == 2


def test_continue_uses_the_latest_thread(home, project):
    first = json.loads(afh(home, project, "run", "--json", "one").stdout.splitlines()[-1])
    second = json.loads(afh(home, project, "run", "--json", "-c", "two").stdout.splitlines()[-1])
    assert first["sessionID"] == second["sessionID"]
    assert first["sessionID"] in afh(home, project, "threads").stdout


def make_repo(folder: Path) -> None:
    def git(*args):
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", *args], cwd=folder, check=True, capture_output=True)

    git("init", "-b", "main")
    (folder / "a.txt").write_text("a\n")
    git("add", "-A")
    git("commit", "-m", "first")


def test_race_scores_models_and_merges_only_the_pick(home, project):
    (project / "check.py").write_text("import pathlib, sys\nsys.exit(0 if 'two' in pathlib.Path('answer.txt').read_text() else 1)\n")
    make_repo(project)
    r = afh(home, project, "race", "RACE it", "-m", "demo/demo-model", "-m", "demo/demo-two", "--check", f"{sys.executable} check.py", "--json")
    assert r.returncode == 0, r.stderr
    race = json.loads(r.stdout.splitlines()[-1])
    assert race["status"] == "finished"
    assert [(e["model"], e["passed"]) for e in race["entries"]] == [("demo/demo-two", True), ("demo/demo-model", False)], race["entries"]
    assert not (project / "answer.txt").exists()  # nothing lands until you pick

    assert "check passed" in afh(home, project, "race", "show", race["id"]).stdout
    r = afh(home, project, "race", "pick", race["id"], "1")
    assert r.returncode == 0, r.stderr
    assert (project / "answer.txt").read_text() == "from demo-two\n"
    assert afh(home, project, "race", "pick", race["id"], "1").returncode == 1  # already closed


def test_github_settings_through_the_command(home, project):
    r = afh(home, project, "github", "add", "me/project", "--path", str(project))
    assert r.returncode == 0, r.stderr
    assert "me/project" in r.stdout and "approvals: ask" in r.stdout
    assert "No such folder" in afh(home, project, "github", "add", "me/other", "--path", str(project / "nope")).stderr
    assert afh(home, project, "github", "add", "not a repo").returncode == 1
    assert afh(home, project, "github", "mode", "bad").returncode == 1
    assert "me/project" not in afh(home, project, "github", "remove", "me/project").stdout
    afh(home, project, "github", "off")


def test_private_backend_leaves_no_discovery_file(home, project):
    assert "private" in afh(home, project, "status").stdout
    assert not (home / "api.json").exists()


def test_uses_the_running_app(home, project):
    proc, _, _ = start_app(environment(home))
    try:
        found = json.loads((home / "api.json").read_text(encoding="utf-8"))
        assert found["key"].startswith("afh_")
        r = afh(home, project, "status")
        assert "the running app" in r.stdout, r.stdout + r.stderr
        assert afh(home, project, "run", "hello").stdout.strip() == "Hello from the mock."
    finally:
        stop_app(proc)
        (home / "api.json").unlink(missing_ok=True)


def test_a_stale_discovery_file_is_ignored(home, project):
    (home / "api.json").write_text(json.dumps({"url": "http://127.0.0.1:9", "key": "afh_old"}), encoding="utf-8")
    try:
        assert "private" in afh(home, project, "status").stdout
    finally:
        (home / "api.json").unlink(missing_ok=True)


def test_shim_lands_on_the_path_once(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOME", tmp_path / ".afh")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "add_to_windows_path", lambda folder: True)  # never the real registry
    done = cli.install_shim()
    shim = tmp_path / ".afh" / "bin" / ("afh.cmd" if os.name == "nt" else "afh")
    assert shim.is_file() and done["pathChanged"]
    assert " cli" in shim.read_text(encoding="utf-8")
    folder = tmp_path / ".afh" / "bin"
    assert cli.add_to_shell_profiles(folder) is (os.name == "nt")  # already added on a Mac
    assert not cli.add_to_shell_profiles(folder)
    assert (tmp_path / ".zprofile").read_text(encoding="utf-8").count(str(folder)) == 1
