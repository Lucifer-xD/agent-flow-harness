"""Anthropic Messages API adapter (``/v1/messages``, streamed).

Thinking blocks and history: Anthropic requires the *signed* thinking blocks of the last
assistant turn to be replayed when that turn called tools and thinking is still enabled.
``ChatMessage`` only keeps reasoning text, so the adapter remembers the signed blocks of each
streamed response in memory, keyed by the tool_use ids it produced, and replays them when the
same assistant message comes back in history. When it cannot (after a restart), thinking is
turned off for that one request instead of letting the API reject it. Thinking blocks of older
turns are never replayed (the API drops them anyway).

Knobs read from ``config.extra``: ``max_tokens`` (default 16384), ``budgets`` (variant → budget_tokens),
``version`` (anthropic-version header), ``body`` (extra top-level fields), ``cache`` (prompt caching, default on).

Prompt caching: up to four ``cache_control`` breakpoints - the last tool definition, the system
prompt, and the newest two user turns - so every step re-reads the long, unchanged prefix of the
conversation from Anthropic's cache instead of paying for it again.
"""

from __future__ import annotations

from typing import AsyncIterator

import httpx

from afh.engine.providers import catalog
from afh.engine.providers.sse import (
    NETWORK_ERRORS, ProviderError, decode_body, error_message, http_error, image_data, iter_json, join_url,
    make_client, network_error, parse_tool_input, stream_error, usage_event,
)
from afh.engine.types import ChatMessage, ChatRequest, ModelInfo, ProviderConfig, ProviderEvent

DEFAULT_MAX_TOKENS = 16_384
BUDGETS = {"low": 2048, "medium": 4096, "high": 8192, "max": 16384}
STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length", "refusal": "stop"}
_CACHE_LIMIT = 256


class AnthropicProvider:
    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport
        self._thinking: dict[str, list[dict]] = {}  # tool_use id → signed thinking blocks of that response

    # ---- request ----------------------------------------------------------------------

    def headers(self) -> dict[str, str]:
        h = {
            "content-type": "application/json", "accept": "text/event-stream",
            "anthropic-version": self.config.extra.get("version", "2023-06-01"),
        }
        if self.config.api_key:
            h["x-api-key"] = self.config.api_key
        h.update(self.config.headers)
        return h

    def build_body(self, req: ChatRequest) -> dict:
        extra = self.config.extra
        max_tokens = req.max_tokens or extra.get("max_tokens") or DEFAULT_MAX_TOKENS
        messages = self.translate_messages(req.messages)
        body: dict = {"model": req.model, "max_tokens": max_tokens, "messages": messages, "stream": True}
        system = "\n\n".join(s for s in [req.system] + [m.text for m in req.messages if m.role == "system"] if s)
        cache = extra.get("cache", True)
        if system:
            body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache else system
        if req.tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in req.tools]
            if cache:
                body["tools"][-1]["cache_control"] = {"type": "ephemeral"}
        if cache:
            self._mark_cache(messages)
        thinking = bool(req.reasoning and req.variant) and self._can_think(messages)
        if thinking:
            budget = extra.get("budgets", BUDGETS).get(req.variant, BUDGETS["high"])
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            body["max_tokens"] = max(max_tokens, budget + 8192)  # the budget counts against max_tokens
        elif req.temperature is not None:  # temperature is rejected alongside thinking
            body["temperature"] = req.temperature
        body.update(extra.get("body", {}))
        return body

    @staticmethod
    def _mark_cache(messages: list[dict]) -> None:
        """Breakpoints on the last block of the newest two user turns (four in all with tools and system)."""
        marked = 0
        for msg in reversed(messages):
            if msg["role"] != "user" or not msg["content"]:
                continue
            block = msg["content"][-1]
            if block.get("type") in ("text", "tool_result", "image"):
                block["cache_control"] = {"type": "ephemeral"}
                marked += 1
            if marked == 2:
                break

    @staticmethod
    def _can_think(messages: list[dict]) -> bool:
        """False when the last assistant turn used tools and we have no signed thinking to replay."""
        for msg in reversed(messages):
            if msg["role"] != "assistant":
                continue
            content = msg["content"]
            if any(b.get("type") == "tool_use" for b in content):
                return content[0].get("type") in ("thinking", "redacted_thinking")
            return True
        return True

    def translate_messages(self, messages: list[ChatMessage]) -> list[dict]:
        out: list[dict] = []

        def push(role: str, blocks: list[dict]) -> None:
            if out and out[-1]["role"] == role:  # the API wants alternating roles
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})

        last_assistant = max((i for i, m in enumerate(messages) if m.role == "assistant"), default=-1)
        for i, m in enumerate(messages):
            if m.role == "user":
                blocks: list[dict] = []
                for img in m.images:
                    data = image_data(img)
                    if data:
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": data[0], "data": data[1]}})
                if m.text:
                    blocks.append({"type": "text", "text": m.text})
                if blocks:
                    push("user", blocks)
            elif m.role == "assistant":
                blocks = []
                if i == last_assistant and m.tool_calls:
                    blocks.extend(self._thinking.get(m.tool_calls[0].id, []))
                text = m.text.rstrip() if i == len(messages) - 1 else m.text  # no trailing whitespace in a prefill
                if text:
                    blocks.append({"type": "text", "text": text})
                for c in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.input})
                if blocks:
                    push("assistant", blocks)
            elif m.role == "tool":
                push("user", [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.text or "(no output)"}])
        return out

    # ---- streaming --------------------------------------------------------------------

    async def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]:
        url = join_url(self.config.base_url, "/v1/messages")
        body = self.build_body(req)
        async with make_client(self.headers(), self._transport) as client:
            try:
                async with client.stream("POST", url, json=body) as resp:
                    if resp.status_code >= 300:
                        yield http_error(resp.status_code, decode_body(await resp.aread()))
                        return
                    async for ev in self._parse(resp):
                        yield ev
            except NETWORK_ERRORS as exc:
                yield network_error(exc, url)

    async def _parse(self, resp: httpx.Response) -> AsyncIterator[ProviderEvent]:
        blocks: dict[int, dict] = {}
        thinking: list[dict] = []  # signed thinking blocks of this response, for replay
        tool_ids: list[str] = []
        stop_reason: str | None = None
        input_tokens = output_tokens = cache_read = cache_write = 0

        async for ev in iter_json(resp):
            t = ev.get("type")
            if t == "message_start":
                u = (ev.get("message") or {}).get("usage") or {}
                input_tokens = u.get("input_tokens") or 0
                cache_read = u.get("cache_read_input_tokens") or 0
                cache_write = u.get("cache_creation_input_tokens") or 0
                output_tokens = u.get("output_tokens") or 0
            elif t == "content_block_start":
                cb = ev.get("content_block") or {}
                idx = ev.get("index", 0)
                block = blocks[idx] = {"type": cb.get("type"), "id": cb.get("id", ""), "name": cb.get("name", ""), "raw": "",
                                      "thinking": "", "signature": "", "data": cb.get("data", "")}
                if block["type"] == "tool_use":
                    tool_ids.append(block["id"])
                    yield {"type": "tool.start", "id": block["id"], "name": block["name"]}
                elif block["type"] == "text" and cb.get("text"):
                    yield {"type": "text.delta", "text": cb["text"]}
                elif block["type"] == "thinking" and cb.get("thinking"):
                    block["thinking"] = cb["thinking"]
                    yield {"type": "reasoning.delta", "text": cb["thinking"]}
            elif t == "content_block_delta":
                d = ev.get("delta") or {}
                block = blocks.get(ev.get("index", 0))
                if block is None:
                    continue
                dt = d.get("type")
                if dt == "text_delta" and d.get("text"):
                    yield {"type": "text.delta", "text": d["text"]}
                elif dt == "thinking_delta" and d.get("thinking"):
                    block["thinking"] += d["thinking"]
                    yield {"type": "reasoning.delta", "text": d["thinking"]}
                elif dt == "input_json_delta":
                    part = d.get("partial_json") or ""
                    if part:
                        block["raw"] += part
                        yield {"type": "tool.delta", "id": block["id"], "text": part}
                elif dt == "signature_delta":
                    block["signature"] = d.get("signature", "")
            elif t == "content_block_stop":
                block = blocks.get(ev.get("index", 0))
                if block is None:
                    continue
                if block["type"] == "tool_use":
                    yield {"type": "tool.end", "id": block["id"], "name": block["name"], "input": parse_tool_input(block["raw"]), "raw": block["raw"]}
                elif block["type"] == "thinking" and block["signature"]:
                    thinking.append({"type": "thinking", "thinking": block["thinking"], "signature": block["signature"]})
                elif block["type"] == "redacted_thinking":
                    thinking.append({"type": "redacted_thinking", "data": block["data"]})
            elif t == "message_delta":
                stop_reason = (ev.get("delta") or {}).get("stop_reason") or stop_reason
                u = ev.get("usage") or {}
                output_tokens = u.get("output_tokens") or output_tokens
            elif t == "message_stop":
                break
            elif t == "error":
                yield stream_error(ev)
                return

        if thinking and tool_ids:
            self._remember(tool_ids, thinking)
        yield usage_event(input=input_tokens, output=output_tokens, cache_read=cache_read, cache_write=cache_write)
        reason = STOP_REASONS.get(stop_reason or "", "tool_calls" if tool_ids else "stop")
        yield {"type": "finish", "reason": reason}

    def _remember(self, tool_ids: list[str], thinking: list[dict]) -> None:
        for tid in tool_ids:
            self._thinking[tid] = thinking
        while len(self._thinking) > _CACHE_LIMIT:  # bounded: oldest first
            self._thinking.pop(next(iter(self._thinking)))

    # ---- models -----------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        if not self.config.fetch_models:
            return catalog.merge_static(self.config, [])
        fetched: list[ModelInfo] = []
        after: str | None = None
        async with make_client(self.headers(), self._transport) as client:
            for _ in range(10):  # paginated; ten pages is far more than the API has
                url = join_url(self.config.base_url, "/v1/models") + "?limit=1000" + (f"&after_id={after}" if after else "")
                try:
                    resp = await client.get(url)
                except NETWORK_ERRORS as exc:
                    raise ProviderError(network_error(exc, url)["message"]) from exc
                if resp.status_code >= 300:
                    body = decode_body(resp.content)
                    raise ProviderError(error_message(body, resp.status_code), resp.status_code, body[:2000])
                data = resp.json()
                for item in data.get("data") or []:
                    if isinstance(item, dict) and item.get("id"):
                        fetched.append(catalog.guess_model(str(item["id"]), "anthropic", name=item.get("display_name") or "", context=200_000))
                after = data.get("last_id") if data.get("has_more") else None
                if not after:
                    break
        return catalog.merge_static(self.config, fetched)
