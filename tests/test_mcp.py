"""Tests for afh.engine.mcp against the real filesystem MCP server (via npx)."""

from __future__ import annotations

import shutil
import sys

import mcp_types as mt
import pytest

from afh.engine import mcp as m
from afh.engine.types import PermissionDenied, ToolContext

NPX = shutil.which("npx")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --------------------------------------------------------------------------- pure units


def test_sanitize_tool_name():
    assert m.sanitize_tool_name("fs", "read_file") == "fs_read_file"
    assert m.sanitize_tool_name("my server!", "do.thing/now") == "my_server__do_thing_now"
    assert m.sanitize_tool_name("_", "_") == "tool"  # stripped to nothing
    long = m.sanitize_tool_name("s" * 40, "t" * 40)
    assert len(long) == 64 and long.startswith("s" * 40 + "_")
    assert m.sanitize_tool_name("a-b", "c-d") == "a-b_c-d"


def test_result_to_text():
    res = mt.CallToolResult(
        content=[
            mt.TextContent(text="hello"),
            mt.ImageContent(data="AAAA", mime_type="image/png"),
            mt.EmbeddedResource(resource=mt.TextResourceContents(uri="file:///x.txt", text="inside")),
            mt.EmbeddedResource(resource=mt.BlobResourceContents(uri="file:///b.bin", blob="AAAA", mime_type="application/octet-stream")),
        ],
        is_error=False,
    )
    text = m.result_to_text(res)
    assert text.splitlines() == ["hello", "[image image/png, 3 bytes]", "[resource file:///x.txt]", "inside", "[resource file:///b.bin (application/octet-stream), 3 bytes]"]
    only_structured = mt.CallToolResult(content=[], structured_content={"a": 1})
    assert m.result_to_text(only_structured) == '{\n  "a": 1\n}'


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command wrapping")
def test_windows_command_wrapping():
    exe, args = m._windows_command("npx", ["-y", "pkg"], None)
    assert exe.lower().endswith("cmd.exe") and args[:3] == ["/d", "/c", "call"] and args[3].lower().endswith("npx.cmd") and args[4:] == ["-y", "pkg"]
    exe, args = m._windows_command("python", ["-V"], None)
    assert exe.lower().endswith(".exe") and args == ["-V"]
    with pytest.raises(FileNotFoundError):
        m._windows_command("nonexistent-cmd-xyz", [], None)


# --------------------------------------------------------------------------- live server


class Gate:
    def __init__(self, deny: set[str] | None = None):
        self.deny = deny or set()
        self.calls: list[tuple] = []

    async def require(self, action, resources, metadata=None):
        self.calls.append((action, resources, metadata))
        if set(resources) & self.deny:
            raise PermissionDenied("user said no")


def ctx(gate: Gate, directory: str) -> ToolContext:
    return ToolContext(session_id="s", message_id="m", directory=directory, permissions=gate, snapshots=None, emit=lambda *_: None)  # type: ignore[arg-type]


def fs_config(tmp_path, name="fs"):
    return {"name": name, "type": "local", "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", str(tmp_path)], "timeout": {"startup": 180, "execution": 60}}


@pytest.mark.skipif(not NPX, reason="npx not installed")
async def test_filesystem_server_end_to_end(tmp_path):
    (tmp_path / "hello.txt").write_text("hello from afh", encoding="utf-8")
    bad = {"name": "broken", "type": "local", "command": ["nonexistent-cmd-xyz", "--flag"]}
    off = {"name": "off", "type": "local", "command": ["whatever"], "disabled": True}
    mgr = m.McpManager()
    try:
        await mgr.start([fs_config(tmp_path), bad, off])
        status = {s["name"]: s for s in mgr.status()}
        assert status["fs"]["status"] == "connected" and status["fs"]["tools"] > 0, status
        assert status["fs"]["transport"] == "stdio"
        assert status["broken"]["status"] == "failed" and "nonexistent-cmd-xyz" in status["broken"]["error"]
        assert status["off"] == {"name": "off", "status": "disabled", "tools": 0}

        tools = {t.spec.name: t for t in mgr.tools()}
        assert "fs_read_file" in tools or "fs_read_text_file" in tools, list(tools)
        assert all(set(t.spec.name) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") for t in tools.values())
        read = tools.get("fs_read_text_file") or tools["fs_read_file"]
        assert read.spec.parameters["type"] == "object" and "path" in read.spec.parameters["properties"]
        assert read.spec.description

        gate = Gate()
        res = await read.run(ctx(gate, str(tmp_path)), {"path": str(tmp_path / "hello.txt")})
        assert not res.is_error and "hello from afh" in res.text, res
        assert gate.calls[0][0] == "mcp" and gate.calls[0][1] == [read.spec.name]
        assert gate.calls[0][2]["server"] == "fs" and gate.calls[0][2]["input"]["path"].endswith("hello.txt")
        assert res.metadata["server"] == "fs"

        listing = await tools["fs_list_directory"].run(ctx(Gate(), str(tmp_path)), {"path": str(tmp_path)})
        assert not listing.is_error and "hello.txt" in listing.text

        # tool errors come back as is_error, not exceptions
        missing = await read.run(ctx(Gate(), str(tmp_path)), {"path": str(tmp_path / "nope.txt")})
        assert missing.is_error and missing.text

        # permission denial propagates from the gate
        with pytest.raises(PermissionDenied):
            await read.run(ctx(Gate(deny={read.spec.name}), str(tmp_path)), {"path": str(tmp_path / "hello.txt")})

        # instructions() only includes servers that sent some; never crashes
        assert isinstance(mgr.instructions(), str)

        # reconnect keeps working and the broken server stays reported
        assert await mgr.reconnect("fs") is True
        status = {s["name"]: s for s in mgr.status()}
        assert status["fs"]["status"] == "connected" and status["broken"]["status"] == "failed"
        read2 = {t.spec.name: t for t in mgr.tools()}[read.spec.name]
        res2 = await read2.run(ctx(Gate(), str(tmp_path)), {"path": str(tmp_path / "hello.txt")})
        assert "hello from afh" in res2.text

        # a failing server can be retried and still fails cleanly
        assert await mgr.reconnect("broken") is False
        assert {s["name"]: s for s in mgr.status()}["broken"]["status"] == "failed"

        await mgr.disconnect("fs")
        assert {s["name"]: s for s in mgr.status()}["fs"]["status"] == "pending"
        assert not any(t.server == "fs" for t in mgr.tools())
        unavailable = await mgr.call("fs", "read_file", {"path": "x"})
        assert unavailable.is_error and "unavailable" in unavailable.text
    finally:
        await mgr.stop()
    assert all(s["status"] in ("pending", "failed", "disabled") for s in mgr.status())


@pytest.mark.skipif(not NPX, reason="npx not installed")
async def test_startup_timeout_marks_failed(tmp_path):
    cfg = fs_config(tmp_path)
    cfg["timeout"] = {"startup": 0.001, "execution": 60}
    mgr = m.McpManager()
    try:
        await mgr.start([cfg])
        s = mgr.status()[0]
        assert s["status"] == "failed" and "timed out" in s["error"]
        assert mgr.tools() == []
    finally:
        await mgr.stop()


async def test_remote_unreachable_fails_without_raising():
    mgr = m.McpManager()
    try:
        await mgr.start([{"name": "nowhere", "type": "remote", "url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "Bearer x"}, "timeout": {"startup": 20}}])
        s = mgr.status()[0]
        assert s["status"] == "failed" and s["error"]
    finally:
        await mgr.stop()
