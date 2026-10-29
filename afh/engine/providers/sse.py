"""Shared transport helpers for the provider adapters.

SSE/line parsing, the error events every adapter yields the same way, the httpx client with
the timeouts we want for streaming, and small message helpers (images, tool argument JSON).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import secrets
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import httpx

from afh.engine.types import ChatMessage, ProviderEvent

# Connect fast, wait generously between chunks, never cap the whole call (long generations).
TIMEOUT = httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=20.0)


class ProviderError(Exception):
    """Raised by non-streaming calls (``list_models``) when the server answers with an error."""

    def __init__(self, message: str, status: int | None = None, response: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.response = response


def make_client(headers: dict[str, str], transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    # ``transport`` exists so tests can plug in httpx.MockTransport.
    return httpx.AsyncClient(timeout=TIMEOUT, headers=headers, transport=transport, follow_redirects=True)


def join_url(base: str, path: str) -> str:
    """``base_url`` + path without doubling a version segment the user already put in base."""
    base = base.rstrip("/")
    for prefix in ("/v1beta", "/v1"):
        if base.endswith(prefix) and path.startswith(prefix + "/"):
            path = path[len(prefix):]
            break
    return base + path


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else url


# ---- SSE ------------------------------------------------------------------------------------


async def iter_sse(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the ``data:`` payload of every SSE event (multi-line data joined with ``\\n``).

    Stops at the OpenAI-style ``[DONE]`` sentinel. ``event:``/``id:``/``retry:`` fields and
    comment lines are ignored; CRLF endings are tolerated.
    """
    data: list[str] = []
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                payload = "\n".join(data)
                data = []
                if payload.strip() == "[DONE]":
                    return
                yield payload
            continue
        if line[0] == ":":
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data.append(value)
    if data:  # stream closed without a trailing blank line
        payload = "\n".join(data)
        if payload.strip() != "[DONE]":
            yield payload


async def iter_json(response: httpx.Response) -> AsyncIterator[dict]:
    """``iter_sse`` + ``json.loads``; lines that are not JSON objects are skipped (mid-stream garbage)."""
    async for payload in iter_sse(response):
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if isinstance(data, dict):
            yield data


# ---- errors ---------------------------------------------------------------------------------


def decode_body(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _find_message(data: Any) -> str:
    if isinstance(data, list):
        for item in data:
            if found := _find_message(item):
                return found
        return ""
    if not isinstance(data, dict):
        return ""
    err = data.get("error")
    if isinstance(err, dict):
        for key in ("message", "msg", "detail"):
            if isinstance(err.get(key), str) and err[key]:
                return err[key]
    if isinstance(err, str) and err:
        return err
    for key in ("message", "msg", "error_description"):
        if isinstance(data.get(key), str) and data[key]:
            return data[key]
    detail = data.get("detail")
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list):  # FastAPI/vLLM validation errors
        msgs = [d.get("msg") for d in detail if isinstance(d, dict) and d.get("msg")]
        if msgs:
            return "; ".join(msgs)
    return ""


def error_message(body: str, status: int | None = None) -> str:
    """Best human-readable message from an error body: JSON ``error.message`` first, then text."""
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if msg := _find_message(data):
        return msg
    text = body.strip()
    if text:
        return text[:500]
    return f"HTTP {status}" if status else "Request failed"


def http_error(status: int, body: str) -> ProviderEvent:
    return {"type": "error", "message": error_message(body, status), "status": status, "kind": "http", "response": body[:2000]}


def stream_error(data: dict) -> ProviderEvent:
    """An error object the server sent inside the event stream (after a 200)."""
    body = json.dumps(data)
    return {"type": "error", "message": error_message(body), "status": None, "kind": "stream", "response": body[:2000]}


def network_error(exc: Exception, url: str) -> ProviderEvent:
    where = origin(url)
    detail = str(exc).strip()
    if isinstance(exc, httpx.ConnectTimeout):
        msg = f"Timed out connecting to {where}"
    elif isinstance(exc, httpx.ConnectError):
        msg = f"Unable to connect to {where}" + (f": {detail}" if detail else "")
    elif isinstance(exc, httpx.ReadTimeout):
        msg = f"Timed out waiting for {where} to send data"
    elif isinstance(exc, httpx.RemoteProtocolError):
        msg = f"Connection to {where} was closed unexpectedly" + (f": {detail}" if detail else "")
    else:
        msg = detail or type(exc).__name__
    return {"type": "error", "message": msg, "status": None, "kind": "network", "response": ""}


# Everything httpx can raise while connecting, sending or reading a stream.
NETWORK_ERRORS = (httpx.HTTPError, httpx.StreamError, httpx.InvalidURL)


# ---- message helpers ------------------------------------------------------------------------


def parse_tool_input(raw: str) -> dict | None:
    """Parsed tool arguments, ``{}`` for an empty string, ``None`` when the JSON is unusable."""
    text = raw.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def new_call_id() -> str:
    return "call_" + secrets.token_hex(8)


def image_data(image: str) -> tuple[str, str] | None:
    """``(media_type, base64)`` from a data URL or a local image path; ``None`` when unusable."""
    if image.startswith("data:"):
        header, _, data = image.partition(",")
        if not data:
            return None
        media = header[5:].split(";")[0] or "image/png"
        if ";base64" not in header:  # a percent/plain data URL: encode the raw text
            data = base64.b64encode(data.encode("utf-8")).decode("ascii")
        return media, data.strip()
    try:
        path = Path(image)
        raw = path.read_bytes()
    except (OSError, ValueError):
        return None
    media = mimetypes.guess_type(path.name)[0] or ""
    if not media.startswith("image/"):
        return None
    return media, base64.b64encode(raw).decode("ascii")


def tool_name_for(messages: list[ChatMessage], tool_call_id: str) -> str:
    """The function name behind a tool result, found in the assistant message that made the call."""
    for m in reversed(messages):
        if m.role == "assistant":
            for call in m.tool_calls:
                if call.id == tool_call_id:
                    return call.name
    return ""


def usage_event(input: int = 0, output: int = 0, reasoning: int = 0, cache_read: int = 0, cache_write: int = 0) -> ProviderEvent:
    """``input`` = uncached prompt tokens only (adapters subtract cache reads where the API includes them)."""
    return {"type": "usage", "input": max(0, int(input or 0)), "output": int(output or 0), "reasoning": int(reasoning or 0),
            "cache_read": int(cache_read or 0), "cache_write": int(cache_write or 0)}
