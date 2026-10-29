"""Tests for the AFH engine built-in tools (afh.engine.tools). Offline; shell tests use PowerShell on Windows."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

from afh.engine.tools import files as files_mod
from afh.engine.tools import web as web_mod
from afh.engine.tools.files import EditTool, GlobTool, GrepTool, ListTool, PatchTool, ReadTool, WriteTool
from afh.engine.tools.registry import builtin_tools, tool_specs
from afh.engine.tools.shell import ShellTool, clean_clixml, truncate_output
from afh.engine.tools.web import WebFetchTool, WebSearchTool
from afh.engine.types import PermissionDenied, ToolContext

IS_WINDOWS = sys.platform == "win32"


# ---- fakes & helpers ------------------------------------------------------------------


class FakeGate:
    def __init__(self, deny: set[str] | None = None):
        self.calls: list[tuple[str, list[str], dict | None]] = []
        self.deny = deny or set()

    async def require(self, action: str, resources: list[str], metadata: dict | None = None) -> None:
        self.calls.append((action, list(resources), metadata))
        if action in self.deny:
            raise PermissionDenied(f"{action} denied by test")

    def actions(self) -> list[str]:
        return [c[0] for c in self.calls]


class FakeSnapshots:
    def __init__(self):
        self.recorded: list[str] = []

    def record(self, path: str) -> None:
        self.recorded.append(path)


def make_ctx(directory: Path, gate: FakeGate | None = None, **kw) -> ToolContext:
    return ToolContext(session_id="ses_test", message_id="msg_test", directory=str(directory),
                       permissions=gate or FakeGate(), snapshots=FakeSnapshots(), emit=lambda *_: None, **kw)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n\n\ndef main():\n    print('hello')\n", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n\nhello world\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.py").write_text("def hidden():\n    pass\n", encoding="utf-8")
    return tmp_path


# ---- read -------------------------------------------------------------------------------


def test_read_whole_file_has_line_numbers_and_end_marker(project):
    ctx = make_ctx(project)
    res = run(ReadTool().run(ctx, {"path": "src/app.py"}))
    assert not res.is_error
    assert res.text.startswith("1: import os\n2: \n3: \n4: def main():\n5:     print('hello')")
    assert "(End of file" in res.text and "5 lines total" in res.text
    assert res.metadata["total_lines"] == 5 and res.metadata["end"] is True
    assert ctx.permissions.calls[0][0] == "read"


def test_read_offset_and_limit(project):
    ctx = make_ctx(project)
    res = run(ReadTool().run(ctx, {"path": "src/app.py", "offset": 4, "limit": 1}))
    assert res.text.splitlines()[0] == "4: def main():"
    assert "(End of file" not in res.text
    assert "offset=5" in res.text
    assert res.truncated is True
    res = run(ReadTool().run(ctx, {"path": "src/app.py", "offset": 5}))
    assert "(End of file" in res.text


def test_read_missing_file_and_directory(project):
    ctx = make_ctx(project)
    res = run(ReadTool().run(ctx, {"path": "nope.txt"}))
    assert res.is_error and "not found" in res.text.lower()
    res = run(ReadTool().run(ctx, {"path": "src"}))
    assert not res.is_error and "app.py" in res.text and "util.py" in res.text


def test_relative_path_cannot_escape_project(project):
    ctx = make_ctx(project)
    res = run(ReadTool().run(ctx, {"path": "../../outside.txt"}))
    assert res.is_error and "escapes" in res.text
    # Absolute paths are allowed (the permission prompt shows them).
    outside = project.parent / "outside_abs.txt"
    outside.write_bytes(b"x\n")
    res = run(ReadTool().run(ctx, {"path": str(outside)}))
    assert not res.is_error and res.text.startswith("1: x")


# ---- write ------------------------------------------------------------------------------


def test_write_new_file_creates_dirs_and_reports_added(project):
    gate = FakeGate()
    ctx = make_ctx(project, gate)
    res = run(WriteTool().run(ctx, {"path": "deep/new/file.txt", "content": "a\nb\nc\n"}))
    assert not res.is_error
    assert res.text == "Wrote 3 lines to deep/new/file.txt"
    assert (project / "deep" / "new" / "file.txt").read_text(encoding="utf-8") == "a\nb\nc\n"
    assert len(res.files) == 1 and res.files[0].status == "added" and res.files[0].additions == 3
    action, resources, meta = gate.calls[0]
    assert action == "edit" and resources == [str(project / "deep" / "new" / "file.txt")]
    assert meta["files"][0]["status"] == "added" and meta["files"][0]["patch"].startswith("--- /dev/null\n+++ b/deep/new/file.txt")
    assert ctx.snapshots.recorded == [str(project / "deep" / "new" / "file.txt")]


def test_write_overwrite_reports_modified_with_diff(project):
    ctx = make_ctx(project)
    res = run(WriteTool().run(ctx, {"path": "README.md", "content": "# Demo\n\nchanged\n"}))
    assert res.files[0].status == "modified"
    assert "-hello world" in res.files[0].patch and "+changed" in res.files[0].patch
    assert res.files[0].additions == 1 and res.files[0].deletions == 1


def test_write_keeps_crlf_of_existing_file(project):
    path = project / "win.txt"
    path.write_bytes(b"a\r\nb\r\n")
    res = run(WriteTool().run(make_ctx(project), {"path": "win.txt", "content": "a\nc\n"}))
    assert not res.is_error and path.read_bytes() == b"a\r\nc\r\n"
    assert res.files[0].additions == 1 and res.files[0].deletions == 1


# ---- edit -------------------------------------------------------------------------------


def test_edit_exact_match(project):
    gate = FakeGate()
    ctx = make_ctx(project, gate)
    res = run(EditTool().run(ctx, {"path": "src/app.py", "oldString": "print('hello')", "newString": "print('bye')"}))
    assert not res.is_error, res.text
    assert "1 replacement" in res.text and "5:     print('bye')" in res.text
    assert (project / "src" / "app.py").read_text(encoding="utf-8").endswith("print('bye')\n")
    assert gate.actions() == ["edit"] and gate.calls[0][2]["files"][0]["status"] == "modified"
    assert "-    print('hello')" in res.metadata["diff"] and "+    print('bye')" in res.metadata["diff"]
    assert ctx.snapshots.recorded == [str(project / "src" / "app.py")]


def test_edit_whitespace_normalised_match_keeps_file_indentation_elsewhere(project):
    ctx = make_ctx(project)
    res = run(EditTool().run(ctx, {"path": "src/util.py", "oldString": "def helper():\n  return 42", "newString": "def helper():\n    return 43"}))
    assert not res.is_error, res.text
    assert res.metadata["loose"] is True
    assert (project / "src" / "util.py").read_text(encoding="utf-8") == "def helper():\n    return 43\n"


def test_edit_not_found(project):
    ctx = make_ctx(project)
    res = run(EditTool().run(ctx, {"path": "src/util.py", "oldString": "does not exist", "newString": "x"}))
    assert res.is_error and "oldString not found in src/util.py" in res.text and "read the file again" in res.text
    assert ctx.permissions.calls == [] and ctx.snapshots.recorded == []


def test_edit_multiple_matches_requires_replace_all(project):
    path = project / "multi.txt"
    path.write_bytes(b"foo\nbar\nfoo\n")
    ctx = make_ctx(project)
    res = run(EditTool().run(ctx, {"path": "multi.txt", "oldString": "foo", "newString": "baz"}))
    assert res.is_error and "2 places" in res.text
    res = run(EditTool().run(ctx, {"path": "multi.txt", "oldString": "foo", "newString": "baz", "replaceAll": True}))
    assert not res.is_error and "2 replacements" in res.text
    assert path.read_text(encoding="utf-8") == "baz\nbar\nbaz\n"


def test_edit_preserves_crlf(project):
    path = project / "win.txt"
    path.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    ctx = make_ctx(project)
    res = run(EditTool().run(ctx, {"path": "win.txt", "oldString": "two", "newString": "2"}))
    assert not res.is_error
    assert path.read_bytes() == b"one\r\n2\r\nthree\r\n"


# ---- patch ------------------------------------------------------------------------------


def test_patch_modifies_and_creates_files(project):
    gate = FakeGate()
    ctx = make_ctx(project, gate)
    patch = (
        "--- a/src/util.py\n"
        "+++ b/src/util.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def helper():\n"
        "-    return 42\n"
        "+    return 7\n"
        "--- /dev/null\n"
        "+++ b/src/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+VALUE = 1\n"
        "+OTHER = 2\n"
    )
    res = run(PatchTool().run(ctx, {"patch": patch}))
    assert not res.is_error, res.text
    assert (project / "src" / "util.py").read_text(encoding="utf-8") == "def helper():\n    return 7\n"
    assert (project / "src" / "new.py").read_text(encoding="utf-8") == "VALUE = 1\nOTHER = 2\n"
    assert [f.status for f in res.files] == ["modified", "added"]
    assert [f.file for f in res.files] == ["src/util.py", "src/new.py"]
    assert len(gate.calls) == 1 and gate.calls[0][0] == "edit" and len(gate.calls[0][2]["files"]) == 2
    assert sorted(ctx.snapshots.recorded) == sorted([str(project / "src" / "util.py"), str(project / "src" / "new.py")])
    assert "modified src/util.py (+1 -1)" in res.text and "added    src/new.py (+2 -0)" in res.text


def test_patch_rejects_wrong_context_and_can_delete(project):
    ctx = make_ctx(project)
    bad = "--- a/src/util.py\n+++ b/src/util.py\n@@ -1,2 +1,2 @@\n def helper():\n-    return 99\n+    return 7\n"
    res = run(PatchTool().run(ctx, {"patch": bad}))
    assert res.is_error and "does not apply" in res.text
    assert (project / "src" / "util.py").read_text(encoding="utf-8") == "def helper():\n    return 42\n"
    delete = "--- a/README.md\n+++ /dev/null\n@@ -1,3 +0,0 @@\n-# Demo\n-\n-hello world\n"
    res = run(PatchTool().run(ctx, {"patch": delete}))
    assert not res.is_error, res.text
    assert not (project / "README.md").exists() and res.files[0].status == "deleted"


def test_patch_inserts_after_named_line(project):
    path = project / "ins.txt"
    path.write_bytes(b"a\nb\nc\n")
    ctx = make_ctx(project)
    patch = "--- a/ins.txt\n+++ b/ins.txt\n@@ -1,0 +2,1 @@\n+X\n"
    res = run(PatchTool().run(ctx, {"patch": patch}))
    assert not res.is_error, res.text
    assert path.read_text(encoding="utf-8") == "a\nX\nb\nc\n"


# ---- glob / grep / list -----------------------------------------------------------------


def test_glob_recursive_skips_node_modules_and_sorts_newest_first(project):
    old = project / "src" / "util.py"
    os.utime(old, (time.time() - 1000, time.time() - 1000))
    ctx = make_ctx(project)
    res = run(GlobTool().run(ctx, {"pattern": "**/*.py"}))
    assert not res.is_error
    lines = res.text.splitlines()
    assert set(lines) == {"src/app.py", "src/util.py"}
    assert lines[-1] == "src/util.py"  # oldest last
    assert "node_modules" not in res.text
    res = run(GlobTool().run(ctx, {"pattern": "*.py", "path": "src"}))
    assert set(res.text.splitlines()) == {"src/app.py", "src/util.py"}
    assert ctx.permissions.actions() == ["read", "read"]


def test_glob_no_match(project):
    res = run(GlobTool().run(make_ctx(project), {"pattern": "**/*.zig"}))
    assert not res.is_error and res.text.startswith("No files match")


def test_grep_python_fallback_outputs_path_line_text(project, monkeypatch):
    monkeypatch.setattr(files_mod.shutil, "which", lambda name: None)
    ctx = make_ctx(project)
    res = run(GrepTool().run(ctx, {"pattern": r"def \w+\("}))
    assert not res.is_error
    assert "src/app.py:4: def main():" in res.text
    assert "src/util.py:1: def helper():" in res.text
    assert "node_modules" not in res.text
    assert res.metadata["backend"] == "python"
    res = run(GrepTool().run(ctx, {"pattern": "hello", "include": "*.md"}))
    assert res.text.strip() == "README.md:3: hello world"
    res = run(GrepTool().run(ctx, {"pattern": "hello", "maxResults": 1}))
    assert res.truncated is True and "(more…" in res.text
    res = run(GrepTool().run(ctx, {"pattern": "zzz_nothing"}))
    assert res.text.startswith("No matches")


@pytest.mark.skipif(files_mod.shutil.which("rg") is None, reason="rg is not on PATH")
def test_grep_rg_backend(project):
    res = run(GrepTool().run(make_ctx(project), {"pattern": "def main"}))
    assert res.metadata["backend"] == "rg" and "src/app.py:4: def main():" in res.text


def test_list_tree(project):
    res = run(ListTool().run(make_ctx(project), {}))
    assert not res.is_error
    assert res.text.splitlines()[0] == str(project)
    assert "  src/" in res.text and "    app.py" in res.text and "  README.md" in res.text
    assert "node_modules/ (not expanded)" in res.text and "pkg" not in res.text


# ---- shell ------------------------------------------------------------------------------


def test_shell_echo(project):
    gate = FakeGate()
    ctx = make_ctx(project, gate)
    res = run(ShellTool().run(ctx, {"command": "echo hello", "description": "Say hello"}))
    assert not res.is_error, res.text
    assert res.text.strip() == "hello"
    assert res.metadata["exit_code"] == 0
    assert gate.calls == [("shell", ["echo hello"], {"command": "echo hello", "description": "Say hello"})]


def test_shell_runs_in_project_directory(project):
    cmd = "Get-Location | Select-Object -ExpandProperty Path" if IS_WINDOWS else "pwd"
    res = run(ShellTool().run(make_ctx(project), {"command": cmd}))
    assert os.path.normcase(res.text.strip()) == os.path.normcase(str(project))


def test_shell_non_zero_exit(project):
    res = run(ShellTool().run(make_ctx(project), {"command": "echo oops; exit 3"}))
    assert "oops" in res.text and res.text.rstrip().endswith("[exit code: 3]")
    assert res.metadata["exit_code"] == 3 and res.is_error is False


@pytest.mark.skipif(not IS_WINDOWS, reason="PowerShell error stream")
def test_shell_powershell_errors_are_plain_text(project):
    res = run(ShellTool().run(make_ctx(project), {"command": r"Get-Item C:\definitely_missing_zzz"}))
    assert "CLIXML" not in res.text and "<Objs" not in res.text
    assert "Cannot find path" in res.text
    assert res.metadata["exit_code"] == 1


def test_shell_timeout_kills_process(project):
    cmd = "Start-Sleep 30" if IS_WINDOWS else "sleep 30"
    t0 = time.monotonic()
    res = run(ShellTool().run(make_ctx(project), {"command": cmd, "timeout": 2}))
    elapsed = time.monotonic() - t0
    assert elapsed < 20, f"took {elapsed:.1f}s"
    assert res.metadata["timed_out"] is True and res.is_error
    assert "timed out after 2s" in res.text and "killed" in res.text


def test_shell_output_truncation_keeps_head_and_tail():
    text = "A" * 20_000 + "B" * 20_000
    out, truncated = truncate_output(text)
    assert truncated and len(out) <= 30_000
    assert out.startswith("AAAA") and out.endswith("BBBB") and "… (truncated) …" in out
    assert truncate_output("short") == ("short", False)


def test_clean_clixml():
    raw = ('#< CLIXML\r\ndone\r\n<Objs Version="1.1.0.1" xmlns="x"><S S="Error">Get-Item : no such thing_x000D__x000A_</S>'
           '<S S="Error">At line:5 char:1_x000D__x000A_</S><S S="Error">+ Get-Item x_x000D__x000A_</S><S S="warning">careful</S></Objs>')
    cleaned = clean_clixml(raw)
    assert cleaned == "done\r\nGet-Item : no such thing\nWARNING: careful\n"


# ---- web --------------------------------------------------------------------------------


def mock_client(handler):
    def factory(timeout=30.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True, timeout=timeout)
    return factory


PAGE = """<!doctype html><html><head><title>Demo  Page</title><style>body{}</style><script>var x=1;</script></head>
<body><nav><a href="/skip">skip me</a></nav>
<h1>Welcome</h1><p>Some <b>bold</b> text and a <a href="/docs">link</a>.</p>
<ul><li>one</li><li>two</li></ul><pre><code>x = 1\ny = 2</code></pre></body></html>"""


def test_webfetch_converts_html_to_markdown(project, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "https://example.com/page"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE)

    monkeypatch.setattr(web_mod, "make_client", mock_client(handler))
    gate = FakeGate()
    res = run(WebFetchTool().run(make_ctx(project, gate), {"url": "https://example.com/old"}))
    assert not res.is_error, res.text
    assert "# Welcome" in res.text
    assert "[link](https://example.com/docs)" in res.text
    assert "- one" in res.text and "- two" in res.text
    assert "```\nx = 1\ny = 2\n```" in res.text
    assert "skip me" not in res.text and "var x" not in res.text and "body{}" not in res.text
    assert res.metadata["title"] == "Demo Page" and res.metadata["url"] == "https://example.com/page" and res.metadata["status"] == 200
    assert gate.calls[0][:2] == ("web", ["https://example.com/old"])


def test_webfetch_text_format_and_raw_html(project, monkeypatch):
    handler = lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE)  # noqa: E731
    monkeypatch.setattr(web_mod, "make_client", mock_client(handler))
    ctx = make_ctx(project)
    res = run(WebFetchTool().run(ctx, {"url": "https://example.com/", "format": "text"}))
    assert "Welcome" in res.text and "#" not in res.text and "](" not in res.text and "link" in res.text
    res = run(WebFetchTool().run(ctx, {"url": "https://example.com/", "format": "html"}))
    assert res.text.startswith("<!doctype html>")


def test_webfetch_errors_cap_and_scheme(project, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/big":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="x" * 150_000)
        return httpx.Response(404, text="nothing here")

    monkeypatch.setattr(web_mod, "make_client", mock_client(handler))
    ctx = make_ctx(project)
    res = run(WebFetchTool().run(ctx, {"url": "https://example.com/missing"}))
    assert res.is_error and res.text.startswith("HTTP 404") and "nothing here" in res.text
    res = run(WebFetchTool().run(ctx, {"url": "https://example.com/big"}))
    assert res.truncated and "(truncated" in res.text and len(res.text) < 101_000
    res = run(WebFetchTool().run(ctx, {"url": "ftp://example.com/x"}))
    assert res.is_error and "http" in res.text
    assert len(ctx.permissions.calls) == 2  # the ftp URL was rejected before asking


def test_websearch_tavily_and_missing_key(project, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    res = run(WebSearchTool().run(make_ctx(project), {"query": "python"}))
    assert res.is_error and "Settings" in res.text

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.tavily.com" and request.headers["authorization"] == "Bearer tv-key"
        return httpx.Response(200, json={"answer": "Python is a language.", "results": [
            {"title": "Python.org", "url": "https://www.python.org/", "content": "Official  site"},
        ]})

    monkeypatch.setattr(web_mod, "make_client", mock_client(handler))
    ctx = make_ctx(project, settings={"TAVILY_API_KEY": "tv-key"})
    res = run(WebSearchTool().run(ctx, {"query": "python", "limit": 3}))
    assert not res.is_error, res.text
    assert "Summary: Python is a language." in res.text
    assert "1. Python.org\n   https://www.python.org/\n   Official site" in res.text
    assert ctx.permissions.calls[0][0] == "web"


# ---- permissions, read-only, registry ----------------------------------------------------


def test_permission_denied_propagates_and_nothing_is_written(project):
    gate = FakeGate(deny={"edit", "shell", "web"})
    ctx = make_ctx(project, gate)
    with pytest.raises(PermissionDenied):
        run(WriteTool().run(ctx, {"path": "denied.txt", "content": "x"}))
    assert not (project / "denied.txt").exists() and ctx.snapshots.recorded == []
    with pytest.raises(PermissionDenied):
        run(EditTool().run(ctx, {"path": "README.md", "oldString": "hello", "newString": "bye"}))
    assert "hello world" in (project / "README.md").read_text(encoding="utf-8")
    with pytest.raises(PermissionDenied):
        run(ShellTool().run(ctx, {"command": "echo no"}))
    with pytest.raises(PermissionDenied):
        run(WebFetchTool().run(ctx, {"url": "https://example.com/"}))


def test_read_only_blocks_edit_and_shell_before_asking(project):
    gate = FakeGate()
    ctx = make_ctx(project, gate, read_only=True)
    for tool, args in [
        (WriteTool(), {"path": "x.txt", "content": "x"}),
        (EditTool(), {"path": "README.md", "oldString": "hello", "newString": "bye"}),
        (PatchTool(), {"patch": "--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,1 @@\n-# Demo\n+# X\n"}),
        (ShellTool(), {"command": "echo hi"}),
    ]:
        with pytest.raises(PermissionDenied):
            run(tool.run(ctx, args))
    assert gate.calls == []
    res = run(ReadTool().run(ctx, {"path": "README.md"}))  # reading is still fine
    assert not res.is_error and "# Demo" in res.text


def test_registry_and_specs(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    names = [t.spec.name for t in builtin_tools({})]
    assert names == ["read", "write", "edit", "patch", "glob", "grep", "list", "shell", "webfetch", "browser"]
    assert "browser" not in [t.spec.name for t in builtin_tools({"browser": {"enabled": False}})]
    with_key = [t.spec.name for t in builtin_tools({"web": {"braveApiKey": "b"}})]
    assert "websearch" in with_key
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    assert "websearch" in [t.spec.name for t in builtin_tools({})]
    specs = tool_specs(builtin_tools({}))
    for spec in specs:
        assert spec.parameters["type"] == "object" and spec.description.count(". ") >= 1
        for name, prop in spec.parameters["properties"].items():
            assert prop.get("type") and prop.get("description"), f"{spec.name}.{name}"


def test_make_client_defaults():
    client = web_mod.make_client(5)
    assert "Mozilla" in client.headers["user-agent"] and client.follow_redirects is True
    run(client.aclose())


def test_glob_literal_prefix_and_absolute_pattern(project):
    ctx = make_ctx(project)
    res = run(GlobTool().run(ctx, {"pattern": "src/*.py"}))
    assert set(res.text.splitlines()) == {"src/app.py", "src/util.py"}
    # The literal folder prefix becomes the walk root, so only that folder is scanned (and asked about).
    assert ctx.permissions.calls[-1][1] == [str(project / "src")]
    res = run(GlobTool().run(ctx, {"pattern": str(project / "src" / "*.py")}))
    assert set(res.text.splitlines()) == {"src/app.py", "src/util.py"}
    res = run(GlobTool().run(ctx, {"pattern": "../*.txt"}))
    assert res.is_error and "escapes" in res.text
