"""Built-in tools of the AFH engine: files, shell and web.

Every tool implements ``afh.engine.types.Tool``: a ``spec`` (name, description, JSON schema the
model reads) and ``run(ctx, input)``. Tools ask ``ctx.permissions`` before any side effect and
record snapshots before touching a file, so the UI can show diffs and undo.
"""

from __future__ import annotations

from afh.engine.tools.files import EditTool, GlobTool, GrepTool, ListTool, PatchTool, ReadTool, ToolError, WriteTool
from afh.engine.tools.registry import builtin_tools, tool_specs
from afh.engine.tools.shell import ShellTool
from afh.engine.tools.web import WebFetchTool, WebSearchTool

__all__ = [
    "EditTool",
    "GlobTool",
    "GrepTool",
    "ListTool",
    "PatchTool",
    "ReadTool",
    "ShellTool",
    "ToolError",
    "WebFetchTool",
    "WebSearchTool",
    "WriteTool",
    "builtin_tools",
    "tool_specs",
]
