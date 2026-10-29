"""Which built-in tools a session gets."""

from __future__ import annotations

from afh.engine.tools.browser import BrowserTool
from afh.engine.tools.files import EditTool, GlobTool, GrepTool, ListTool, PatchTool, ReadTool, WriteTool
from afh.engine.tools.shell import ShellTool
from afh.engine.tools.web import WebFetchTool, WebSearchTool, search_api_key
from afh.engine.types import Tool, ToolSpec


def builtin_tools(settings: dict | None = None) -> list[Tool]:
    """Fresh tool instances. `websearch` is only offered when a search API key is configured,
    so the model never sees a tool that can only fail."""
    tools: list[Tool] = [
        ReadTool(), WriteTool(), EditTool(), PatchTool(),
        GlobTool(), GrepTool(), ListTool(),
        ShellTool(), WebFetchTool(),
    ]
    if search_api_key(settings) is not None:
        tools.append(WebSearchTool())
    if ((settings or {}).get("browser") or {}).get("enabled", True) is not False:
        tools.append(BrowserTool())
    return tools


def tool_specs(tools: list[Tool]) -> list[ToolSpec]:
    return [t.spec for t in tools]
