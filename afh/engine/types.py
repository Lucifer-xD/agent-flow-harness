"""Shared contracts of the AFH engine. Everything else imports from here.

Three streams of data move through the engine:

* **Provider events** — what an LLM adapter yields while streaming one model call.
* **Session events** — what the engine publishes to the UI (the names the web app already
  listens to: ``session.text.delta``, ``session.tool.input.delta``, ``permission.asked``...).
* **Messages** — what is stored per session and sent back to the model on the next turn.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Protocol

# ---- ids & time -----------------------------------------------------------------------

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def new_id(prefix: str) -> str:
    """Sortable id: prefix + 12 hex of milliseconds + 10 random chars (e.g. ``msg_0193...``)."""
    ms = int(time.time() * 1000)
    rand = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{prefix}_{ms:012x}{rand}"


def now_ms() -> int:
    return int(time.time() * 1000)


# ---- models & providers --------------------------------------------------------------------


@dataclass
class ModelInfo:
    id: str
    name: str
    context: int = 128_000  # context window in tokens
    output: int = 16_384  # max output tokens
    tools: bool = True
    reasoning: bool = False  # the model can return reasoning/thinking content
    variants: list[str] = field(default_factory=list)  # effort levels: "low", "high", "max"...
    input: list[str] = field(default_factory=lambda: ["text"])  # "text", "image"
    hidden: bool = False
    cost: dict | None = None  # USD per 1M tokens: {"input", "output", "cacheRead", "cacheWrite"}; None = unknown

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "context": self.context, "output": self.output, "tools": self.tools,
             "reasoning": self.reasoning, "variants": list(self.variants), "input": list(self.input), "hidden": self.hidden}
        if self.cost:
            d["cost"] = dict(self.cost)
        return d


@dataclass
class ProviderConfig:
    """One configured provider: where to call, how to authenticate, which models."""

    id: str  # e.g. "kimi", "zai-coding", "openai", "ollama", or a user id for custom endpoints
    name: str
    kind: Literal["openai", "anthropic", "gemini", "responses", "antigravity"]  # wire protocol ("responses" = OpenAI Responses API)
    base_url: str
    api_key: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    models: list[ModelInfo] = field(default_factory=list)  # known/static models (merged with /models when fetched)
    fetch_models: bool = True  # try GET /models on refresh
    extra: dict[str, Any] = field(default_factory=dict)  # provider-specific knobs (e.g. {"reasoning_field": "reasoning_content"})
    auth: dict[str, Any] = field(default_factory=dict)  # sign-in credentials (see engine/auth.py); empty = api_key


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema object


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ChatMessage:
    """Provider-neutral chat message. Adapters translate to their wire format."""

    role: Literal["system", "user", "assistant", "tool"]
    text: str = ""
    reasoning: str = ""  # assistant only; some providers need it echoed back
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant only
    tool_call_id: str = ""  # tool role: which call this answers
    tool_name: str = ""
    images: list[str] = field(default_factory=list)  # data: URLs or file paths (user only)


@dataclass
class ChatRequest:
    model: str
    system: str
    messages: list[ChatMessage]
    tools: list[ToolSpec] = field(default_factory=list)
    variant: str | None = None  # effort level ("low"/"high"/"max"/None)
    max_tokens: int | None = None
    temperature: float | None = None
    reasoning: bool = True  # ask for reasoning content when the model supports it


# Provider events (dicts, so adapters stay simple):
#   {"type": "text.delta", "text": str}
#   {"type": "reasoning.delta", "text": str}
#   {"type": "tool.start", "id": str, "name": str}
#   {"type": "tool.delta", "id": str, "text": str}            # raw JSON argument text as it streams
#   {"type": "tool.end", "id": str, "name": str, "input": dict | None, "raw": str}
#   {"type": "usage", "input": int, "output": int, "reasoning": int, "cache_read": int, "cache_write": int}
#       ``input`` counts only uncached prompt tokens; cache reads/writes are reported separately.
#   {"type": "finish", "reason": "stop" | "tool_calls" | "length" | "error"}
#   {"type": "error", "message": str, "status": int | None, "kind": str, "response": str}
ProviderEvent = dict[str, Any]


class Provider(Protocol):
    config: ProviderConfig

    def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]: ...

    async def list_models(self) -> list[ModelInfo]: ...


# ---- tools -------------------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """A spending limit (Settings → Usage & cost) stops the run before the next model call."""


class PermissionDenied(Exception):
    def __init__(self, message: str = "Not allowed"):
        super().__init__(message)
        self.message = message


class PermissionGate(Protocol):
    """Asks the user (or the session's rules) before a tool acts.

    ``action``: "edit" | "shell" | "read" | "web" | "mcp" | "subagent" | "question"
    ``resources``: what it touches (file paths, the command, a URL)
    ``metadata``: shown to the user — ``{"files": [FileDiff...]}`` for edits, ``{"command": str}`` for shell.
    Raises PermissionDenied when refused (its message carries what the user typed).
    """

    async def require(self, action: str, resources: list[str], metadata: dict | None = None) -> None: ...


@dataclass
class FileDiff:
    file: str
    patch: str
    status: Literal["added", "modified", "deleted"]
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict:
        return {"file": self.file, "patch": self.patch, "status": self.status, "additions": self.additions, "deletions": self.deletions}


class SnapshotStore(Protocol):
    """Remembers a file's content before a tool changes it, for undo."""

    def record(self, path: str) -> None: ...


@dataclass
class ToolContext:
    session_id: str
    message_id: str  # the assistant message this call belongs to
    directory: str  # project folder (cwd for everything)
    permissions: PermissionGate
    snapshots: SnapshotStore
    emit: Callable[[str, dict], None]  # emit(event_type, data) for progress events
    settings: dict = field(default_factory=dict)  # app settings (shell preference, timeouts...)
    read_only: bool = False  # the session forbids edits and shell
    jobs: Any = None  # the engine's JobManager (background shell commands), when available
    engine: Any = None  # the Engine, for tools that need more than files/shell (computer control)


@dataclass
class ToolResult:
    text: str
    metadata: dict = field(default_factory=dict)
    files: list[FileDiff] = field(default_factory=list)  # edits made (for the Changes panel and undo)
    is_error: bool = False
    truncated: bool = False
    images: list[str] = field(default_factory=list)  # data: URLs (browser screenshots) shown in the card and to vision models


class Tool(Protocol):
    spec: ToolSpec

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult: ...


# ---- session events published to the UI ------------------------------------------------------

EmitFn = Callable[[dict], None]
AsyncFn = Callable[..., Awaitable[Any]]


def event(type_: str, session_id: str | None = None, **data: Any) -> dict:
    """A UI event in the shape the web app expects: ``{"id","type","created","data":{...}}``."""
    if session_id is not None:
        data = {"sessionID": session_id, **data}
    return {"id": new_id("evt"), "type": type_, "created": now_ms(), "data": data}
