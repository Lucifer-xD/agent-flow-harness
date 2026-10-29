"""MCP servers as engine tools.

``McpManager`` owns one background task per configured server. The task enters the
transport and the ``mcp.Client`` context managers and parks there until it is told to stop,
because the SDK's anyio task groups must be entered and exited by the same task. Tool calls
can then come from any task (the dispatcher hands requests over memory streams).

Config shape (stored by the app, consumed here)::

    {"name": str, "type": "local" | "remote",
     "command": [str, ...], "cwd"?: str, "environment"?: {k: v},        # local
     "url"?: str, "headers"?: {k: v},                                    # remote
     "disabled"?: bool, "timeout"?: {"startup": s, "execution": s}}

Transports: local servers use stdio; remote servers try streamable HTTP first and fall back to
the older SSE transport when the endpoint answers the first POST with 404/405.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx2
import mcp_types as mt
from mcp import Client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from .types import ToolContext, ToolResult, ToolSpec

log = logging.getLogger(__name__)

DEFAULT_STARTUP_TIMEOUT = 60.0  # `npx -y` may have to download the server first
DEFAULT_EXECUTION_TIMEOUT = 120.0
MAX_TOOL_NAME = 64
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
_STDERR_TAIL = 2000  # bytes of server stderr quoted in a startup error

Status = Literal["connected", "pending", "failed", "disabled"]


def sanitize_tool_name(server: str, tool: str) -> str:
    """``server_tool`` restricted to ``[a-zA-Z0-9_-]`` and 64 chars (what every provider accepts)."""
    name = _NAME_RE.sub("_", f"{server}_{tool}").strip("_") or "tool"
    return name[:MAX_TOOL_NAME]


# ---- commands --------------------------------------------------------------------------------


def _resolve_command(exe: str, cwd: str | None) -> str | None:
    """Absolute path of ``exe`` (PATH, PATHEXT and cwd-relative), or None when nothing matches."""
    found = shutil.which(exe)
    if found:
        return found
    candidate = Path(cwd or os.getcwd()) / exe
    if candidate.is_file():
        return str(candidate)
    return None


def _windows_command(exe: str, args: list[str], cwd: str | None) -> tuple[str, list[str]]:
    """Make ``exe`` runnable on Windows.

    ``npx`` and friends are ``.cmd`` scripts, which CreateProcess cannot start directly, so they
    run through ``cmd.exe /d /c call <script> args...``. ``call`` keeps the script path quoted
    even though it contains spaces ("Program Files"): cmd.exe only strips quotes when the text
    after ``/c`` starts with one. Known limit: a literal ``%`` in an argument is expanded by cmd.
    """
    resolved = _resolve_command(exe, cwd)
    if resolved is None:
        if os.sep in exe or "/" in exe:
            return exe, args  # explicit path; let the spawn report the real error
        raise FileNotFoundError(f"Command not found: {exe}")
    if resolved.lower().endswith((".exe", ".com")):
        return resolved, args
    comspec = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
    return comspec, ["/d", "/c", "call", resolved, *args]


def stdio_params(cfg: dict) -> StdioServerParameters:
    command = [str(c) for c in (cfg.get("command") or [])]
    if not command:
        raise ValueError("local MCP server needs a non-empty 'command'")
    exe, args = command[0], command[1:]
    cwd = cfg.get("cwd") or None
    if sys.platform == "win32":
        exe, args = _windows_command(exe, args, cwd)
    # The SDK only forwards a safe subset of the environment by default; the user's server
    # expects the full one (PATH additions, proxies, API keys from the shell).
    env = {**os.environ, **{str(k): str(v) for k, v in (cfg.get("environment") or {}).items()}}
    return StdioServerParameters(command=exe, args=args, env=env, cwd=cwd)


# ---- state -------------------------------------------------------------------------------------


@dataclass
class _Server:
    name: str
    config: dict
    status: Status = "pending"
    error: str | None = None
    instructions: str | None = None
    tools: list[mt.Tool] = field(default_factory=list)
    client: Client | None = None
    task: asyncio.Task | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    transport: str = ""  # "stdio" | "streamable-http" | "sse"

    @property
    def startup_timeout(self) -> float:
        return float((self.config.get("timeout") or {}).get("startup") or DEFAULT_STARTUP_TIMEOUT)

    @property
    def execution_timeout(self) -> float:
        return float((self.config.get("timeout") or {}).get("execution") or DEFAULT_EXECUTION_TIMEOUT)


def _is_endpoint_rejection(exc: BaseException) -> bool:
    """The streamable transport turns a 404 into METHOD_NOT_FOUND and 405 (or any other
    non-JSON error status) into INTERNAL_ERROR "Server returned an error response"."""
    if not isinstance(exc, MCPError):
        return False
    if exc.code == mt.METHOD_NOT_FOUND:
        return True
    return exc.code == mt.INTERNAL_ERROR and "error response" in (exc.error.message or "")


def _describe(exc: BaseException) -> str:
    if isinstance(exc, MCPError):
        return f"{exc.error.message} (code {exc.code})"
    text = str(exc) or exc.__class__.__name__
    return text if len(text) < 500 else text[:500] + "…"


# ---- tool adapter --------------------------------------------------------------------------


def _content_text(block: Any) -> str:
    """One MCP content block as text for the model; binary blocks become short summaries."""
    if isinstance(block, mt.TextContent):
        return block.text
    if isinstance(block, mt.ImageContent):
        return f"[image {block.mime_type}, {len(block.data) * 3 // 4} bytes]"
    if isinstance(block, mt.AudioContent):
        return f"[audio {block.mime_type}, {len(block.data) * 3 // 4} bytes]"
    if isinstance(block, mt.EmbeddedResource):
        res = block.resource
        if isinstance(res, mt.TextResourceContents):
            return f"[resource {res.uri}]\n{res.text}"
        return f"[resource {res.uri} ({res.mime_type or 'binary'}), {len(res.blob) * 3 // 4} bytes]"
    if isinstance(block, mt.ResourceLink):
        return f"[resource link {block.uri}{' - ' + block.description if block.description else ''}]"
    return f"[{getattr(block, 'type', 'content')}]"


def result_to_text(result: mt.CallToolResult) -> str:
    parts = [_content_text(b) for b in result.content]
    text = "\n".join(p for p in parts if p)
    if not text and result.structured_content is not None:
        text = json.dumps(result.structured_content, indent=2, ensure_ascii=False)
    return text


class McpTool:
    """A ``Tool`` adapter around one tool of one connected server."""

    def __init__(self, manager: "McpManager", server: str, tool: mt.Tool, name: str):
        self.manager = manager
        self.server = server
        self.tool_name = tool.name
        schema = dict(tool.input_schema or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        self.spec = ToolSpec(name=name, description=tool.description or f"{tool.name} from MCP server {server}", parameters=schema)

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        await ctx.permissions.require("mcp", [self.spec.name], {"server": self.server, "input": input})
        return await self.manager.call(self.server, self.tool_name, input, ctx=ctx)


# ---- manager -----------------------------------------------------------------------------


class McpManager:
    def __init__(self) -> None:
        self._servers: dict[str, _Server] = {}
        self._tools: list[McpTool] = []
        self._refreshing: set[asyncio.Task] = set()

    # -- lifecycle --

    async def start(self, configs: list[dict]) -> None:
        """Register every config and connect the enabled ones concurrently; failures are
        recorded in ``status()`` rather than raised."""
        for cfg in configs:
            name = str(cfg.get("name") or "").strip()
            if not name:
                continue
            srv = _Server(name=name, config=cfg)
            if cfg.get("disabled"):
                srv.status = "disabled"
            self._servers[name] = srv
        enabled = [s.name for s in self._servers.values() if s.status != "disabled"]
        await asyncio.gather(*(self.connect(n) for n in enabled), return_exceptions=True)

    async def connect(self, name: str) -> bool:
        srv = self._servers[name]
        if srv.task is not None:
            await self.disconnect(name)
        srv.status, srv.error, srv.tools, srv.instructions = "pending", None, [], None
        srv.ready, srv.stop = asyncio.Event(), asyncio.Event()
        srv.task = asyncio.create_task(self._run(srv), name=f"mcp:{name}")
        try:
            await asyncio.wait_for(srv.ready.wait(), srv.startup_timeout)
        except asyncio.TimeoutError:
            srv.task.cancel()
            srv.status, srv.error = "failed", f"startup timed out after {srv.startup_timeout:g}s"
        self._rebuild_tools()
        return srv.status == "connected"

    async def disconnect(self, name: str) -> None:
        srv = self._servers[name]
        task, srv.task = srv.task, None
        if task is not None:
            srv.stop.set()
            try:
                await asyncio.wait_for(asyncio.shield(task), 10)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()
                try:
                    await task
                except BaseException:  # the server was unresponsive; the kill already happened
                    pass
        srv.client, srv.tools = None, []
        if srv.status != "disabled":
            srv.status = "failed" if srv.error else "pending"
        self._rebuild_tools()

    async def reconnect(self, name: str) -> bool:
        await self.disconnect(name)
        return await self.connect(name)

    async def add(self, cfg: dict) -> dict:
        """Register (or replace) one server while the others keep running; returns its status."""
        name = str(cfg.get("name") or "").strip()
        if name in self._servers:
            await self.disconnect(name)
        srv = _Server(name=name, config=cfg)
        self._servers[name] = srv
        if cfg.get("disabled"):
            srv.status = "disabled"
        else:
            await self.connect(name)
        return next(s for s in self.status() if s["name"] == name)

    async def remove(self, name: str) -> None:
        if name in self._servers:
            await self.disconnect(name)
            del self._servers[name]
            self._rebuild_tools()

    def tool_names(self, server: str) -> list[str]:
        """The names the model calls this server's tools by."""
        return [t.spec.name for t in self._tools if t.server == server]

    async def stop(self) -> None:
        for t in list(self._refreshing):
            t.cancel()
        await asyncio.gather(*(self.disconnect(n) for n in list(self._servers)), return_exceptions=True)

    # -- queries --

    def status(self) -> list[dict]:
        out = []
        for s in self._servers.values():
            entry: dict[str, Any] = {"name": s.name, "status": s.status, "tools": len(s.tools) if s.status == "connected" else 0}
            if s.error:
                entry["error"] = s.error
            if s.instructions:
                entry["instructions"] = s.instructions
            if s.transport:
                entry["transport"] = s.transport
            out.append(entry)
        return out

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    def instructions(self) -> str:
        """Server-provided instructions, for the system prompt."""
        chunks = [f"## MCP server: {s.name}\n{s.instructions.strip()}" for s in self._servers.values() if s.status == "connected" and s.instructions and s.instructions.strip()]
        return "\n\n".join(chunks)

    # -- calls --

    async def call(self, server: str, tool: str, arguments: dict, ctx: ToolContext | None = None) -> ToolResult:
        srv = self._servers.get(server)
        if srv is None or srv.status != "connected" or srv.client is None:
            reason = srv.error if srv and srv.error else "not connected"
            return ToolResult(text=f"MCP server '{server}' is unavailable: {reason}", is_error=True)
        emit = ctx.emit if ctx else None

        async def progress(value: float, total: float | None, message: str | None) -> None:
            if emit:
                emit("session.tool.progress", {"server": server, "tool": tool, "progress": value, "total": total, "message": message})

        try:
            result = await srv.client.call_tool(tool, arguments or {}, read_timeout_seconds=srv.execution_timeout, progress_callback=progress)
        except MCPError as exc:
            if exc.code == mt.CONNECTION_CLOSED:
                srv.status, srv.error = "failed", "connection closed by the server"
                self._rebuild_tools()
            if exc.code == mt.REQUEST_TIMEOUT:
                return ToolResult(text=f"MCP tool '{tool}' timed out after {srv.execution_timeout:g}s", is_error=True)
            return ToolResult(text=f"MCP error from '{server}': {_describe(exc)}", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ToolResult(text=f"MCP call to '{server}' failed: {_describe(exc)}", is_error=True)
        text = result_to_text(result)
        meta: dict[str, Any] = {"server": server, "tool": tool}
        if result.structured_content is not None:
            meta["structured"] = result.structured_content
        return ToolResult(text=text, metadata=meta, is_error=bool(result.is_error))

    # -- internals --

    def _rebuild_tools(self) -> None:
        tools: list[McpTool] = []
        taken: set[str] = set()
        for srv in self._servers.values():
            if srv.status != "connected":
                continue
            for t in srv.tools:
                name = sanitize_tool_name(srv.name, t.name)
                base, n = name, 2
                while name in taken:  # two tools collapsing to one sanitized name
                    suffix = f"_{n}"
                    name, n = base[: MAX_TOOL_NAME - len(suffix)] + suffix, n + 1
                taken.add(name)
                tools.append(McpTool(self, srv.name, t, name))
        self._tools = tools

    async def _run(self, srv: _Server) -> None:
        """Body of the per-server task: connect, list tools, then sleep until told to stop."""
        errlog = None
        try:
            kind = srv.config.get("type") or ("remote" if srv.config.get("url") else "local")
            if kind == "remote":
                await self._run_remote(srv)
            else:
                errlog = tempfile.TemporaryFile("w+b")  # stderr capture, quoted on startup failure
                params = stdio_params(srv.config)
                srv.transport = "stdio"
                await self._serve(srv, stdio_client(params, errlog=errlog), errlog=errlog)  # type: ignore[arg-type]
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # anyio may wrap failures in ExceptionGroups
            self._fail(srv, exc, errlog)
        finally:
            srv.client = None
            if srv.status == "connected":
                if srv.stop.is_set():  # clean disconnect()
                    srv.status = "pending"
                else:  # the server went away on its own
                    srv.status, srv.error = "failed", srv.error or "connection closed"
            srv.ready.set()
            if errlog is not None:
                errlog.close()
            self._rebuild_tools()

    async def _run_remote(self, srv: _Server) -> None:
        url = srv.config.get("url")
        if not url:
            raise ValueError("remote MCP server needs a 'url'")
        headers = {str(k): str(v) for k, v in (srv.config.get("headers") or {}).items()}
        srv.transport = "streamable-http"
        try:
            async with httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(30, read=300)) as http:
                await self._serve(srv, streamable_http_client(url, http_client=http))
            return
        except BaseException as exc:
            inner = _leaf(exc)
            if srv.ready.is_set() or not _is_endpoint_rejection(inner):
                raise
            log.info("mcp %s: streamable HTTP rejected (%s); trying SSE", srv.name, _describe(inner))
        srv.transport = "sse"
        await self._serve(srv, sse_client(url, headers=headers))

    async def _serve(self, srv: _Server, transport: Any, errlog: Any = None) -> None:
        async def on_message(message: Any) -> None:
            if isinstance(message, mt.ToolListChangedNotification):
                task = asyncio.get_running_loop().create_task(self._refresh_tools(srv))
                self._refreshing.add(task)
                task.add_done_callback(self._refreshing.discard)
            elif isinstance(message, Exception) and srv.status == "connected":
                srv.error = f"transport error: {_describe(message)}"
                log.warning("mcp %s: %s", srv.name, srv.error)

        # cache=None: the SDK's response cache would hide a server whose tool list changed
        # without sending list_changed (several do), and we re-list rarely anyway.
        async with Client(transport, message_handler=on_message, cache=None) as client:
            srv.instructions = client.instructions
            srv.tools = await self._list_all_tools(client)
            srv.client, srv.status, srv.error = client, "connected", None
            self._rebuild_tools()
            srv.ready.set()
            log.info("mcp %s: connected over %s with %d tools", srv.name, srv.transport, len(srv.tools))
            await self._wait_until_stopped(srv, client)

    async def _wait_until_stopped(self, srv: _Server, client: Client) -> None:
        """Park until ``disconnect()``; also notice a server that died (EOF closes the dispatcher)."""
        while not srv.stop.is_set():
            try:
                await asyncio.wait_for(srv.stop.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
            if _dispatcher_closed(client):
                srv.error = srv.error or "the server closed the connection"
                srv.status = "failed"
                raise ConnectionError(srv.error)

    async def _list_all_tools(self, client: Client) -> list[mt.Tool]:
        tools: list[mt.Tool] = []
        cursor: str | None = None
        for _ in range(100):  # pagination guard
            page = await client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                break
        return tools

    async def _refresh_tools(self, srv: _Server) -> None:
        if srv.client is None or srv.status != "connected":
            return
        try:
            srv.tools = await self._list_all_tools(srv.client)
            self._rebuild_tools()
            log.info("mcp %s: tool list refreshed (%d tools)", srv.name, len(srv.tools))
        except Exception as exc:
            log.warning("mcp %s: tools/list after list_changed failed: %s", srv.name, _describe(exc))

    def _fail(self, srv: _Server, exc: BaseException, errlog: Any) -> None:
        leaf = _leaf(exc)
        message = _describe(leaf)
        if isinstance(leaf, MCPError) and leaf.code == mt.CONNECTION_CLOSED:
            message = "the server exited before finishing the MCP handshake"
        tail = _read_tail(errlog)
        if tail:
            message += f"\nstderr: {tail}"
        srv.status, srv.error = "failed", message
        log.warning("mcp %s: failed: %s", srv.name, message.splitlines()[0])


def _leaf(exc: BaseException) -> BaseException:
    """The first real exception inside (possibly nested) ExceptionGroups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _dispatcher_closed(client: Client) -> bool:
    """Best-effort peek at the SDK's private closed flag (set at transport EOF)."""
    try:
        return bool(getattr(getattr(client.session, "_dispatcher", None), "_closed", False))
    except Exception:
        return False


def _read_tail(errlog: Any) -> str:
    if errlog is None:
        return ""
    try:
        errlog.flush()
        size = errlog.seek(0, os.SEEK_END)
        errlog.seek(max(0, size - _STDERR_TAIL))
        return errlog.read().decode("utf-8", "replace").strip()
    except Exception:
        return ""
