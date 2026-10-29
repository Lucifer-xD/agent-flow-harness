"""OpenAI Responses API adapter (``POST /responses``): ChatGPT sign-in (the Codex backend) and
providers that only speak Responses.

Requests are stateless (``store: false``): the whole history is sent as input items each turn.
Reasoning arrives as summary text; tool calls as ``function_call`` output items whose arguments
stream in ``response.function_call_arguments.delta`` events.

Knobs read from ``config.extra``: ``effort_map`` (rename variants), ``body`` (extra fields).
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from afh.engine import auth
from afh.engine.providers import catalog
from afh.engine.providers.sse import (
    NETWORK_ERRORS, ProviderError, decode_body, error_message, http_error, image_data, iter_json, join_url,
    make_client, network_error, parse_tool_input, stream_error, usage_event,
)
from afh.engine.types import ChatRequest, ModelInfo, ProviderConfig, ProviderEvent


class OpenAIResponsesProvider:
    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport

    @property
    def chatgpt(self) -> bool:
        return (self.config.auth or {}).get("type") == "chatgpt"

    def headers(self) -> dict[str, str]:
        h = {"content-type": "application/json", "accept": "text/event-stream"}
        if self.config.api_key and not self.chatgpt:
            h["authorization"] = f"Bearer {self.config.api_key}"
        h.update(self.config.headers)
        return h

    def build_body(self, req: ChatRequest) -> dict:
        extra = self.config.extra
        body: dict = {"model": req.model, "instructions": req.system or "", "input": self.translate_messages(req),
                      "stream": True, "store": False}
        if req.tools:
            body["tools"] = [{"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters, "strict": False} for t in req.tools]
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True
        if req.variant and req.reasoning:
            body["reasoning"] = {"effort": extra.get("effort_map", {}).get(req.variant, req.variant), "summary": "auto"}
            body["include"] = ["reasoning.encrypted_content"]
        if not self.chatgpt:  # the Codex backend rejects both
            if req.max_tokens:
                body["max_output_tokens"] = req.max_tokens
            if req.temperature is not None and not req.variant:
                body["temperature"] = req.temperature
        body.update(extra.get("body", {}))
        return body

    def translate_messages(self, req: ChatRequest) -> list[dict]:
        out: list[dict] = []
        for m in req.messages:
            if m.role == "system":
                out.append({"role": "developer", "content": [{"type": "input_text", "text": m.text}]})
            elif m.role == "user":
                parts: list[dict] = [{"type": "input_text", "text": m.text}] if m.text else []
                for img in m.images:
                    data = image_data(img)
                    if data:
                        parts.append({"type": "input_image", "image_url": f"data:{data[0]};base64,{data[1]}"})
                out.append({"role": "user", "content": parts or [{"type": "input_text", "text": ""}]})
            elif m.role == "assistant":
                if m.text:
                    out.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": m.text}]})
                for c in m.tool_calls:
                    out.append({"type": "function_call", "call_id": c.id, "name": c.name, "arguments": json.dumps(c.input, ensure_ascii=False)})
            elif m.role == "tool":
                out.append({"type": "function_call_output", "call_id": m.tool_call_id, "output": m.text})
        return out

    async def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]:
        try:
            base, signed = await auth.prepare(self.config, req)
        except Exception as exc:
            yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
            return
        url = join_url(base, "/responses")
        body = self.build_body(req)
        async with make_client(self.headers() | signed, self._transport) as client:
            for attempt in (0, 1):
                try:
                    async with client.stream("POST", url, json=body) as resp:
                        if resp.status_code == 401 and attempt == 0 and auth.signed_in(self.config):
                            await resp.aread()  # a revoked token: refresh once and retry
                            try:
                                base, signed = await auth.prepare(self.config, req, force=True)
                            except Exception as exc:
                                yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
                                return
                            client.headers.update(signed)
                            continue
                        if resp.status_code >= 300:
                            yield http_error(resp.status_code, decode_body(await resp.aread()))
                            return
                        async for ev in self._parse(resp):
                            yield ev
                        return
                except NETWORK_ERRORS as exc:
                    yield network_error(exc, url)
                    return

    async def _parse(self, resp: httpx.Response) -> AsyncIterator[ProviderEvent]:
        calls: dict[str, dict] = {}  # item id -> {call_id, name, raw, ended}
        summary_parts = 0
        finish = "stop"
        async for ev in iter_json(resp):
            t = ev.get("type") or ""
            if t == "response.output_text.delta":
                if ev.get("delta"):
                    yield {"type": "text.delta", "text": ev["delta"]}
            elif t in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
                if ev.get("delta"):
                    yield {"type": "reasoning.delta", "text": ev["delta"]}
            elif t == "response.reasoning_summary_part.added":
                summary_parts += 1
                if summary_parts > 1:
                    yield {"type": "reasoning.delta", "text": "\n\n"}
            elif t == "response.output_item.added":
                item = ev.get("item") or {}
                if item.get("type") == "function_call":
                    call = {"call_id": item.get("call_id") or item.get("id"), "name": item.get("name", ""), "raw": item.get("arguments") or "", "ended": False}
                    calls[item.get("id") or call["call_id"]] = call
                    yield {"type": "tool.start", "id": call["call_id"], "name": call["name"]}
                    if call["raw"]:
                        yield {"type": "tool.delta", "id": call["call_id"], "text": call["raw"]}
            elif t == "response.function_call_arguments.delta":
                call = calls.get(ev.get("item_id") or "")
                if call and ev.get("delta"):
                    call["raw"] += ev["delta"]
                    yield {"type": "tool.delta", "id": call["call_id"], "text": ev["delta"]}
            elif t == "response.output_item.done":
                item = ev.get("item") or {}
                call = calls.get(item.get("id") or item.get("call_id") or "")
                if item.get("type") == "function_call" and call and not call["ended"]:
                    call["ended"] = True
                    raw = item.get("arguments") if isinstance(item.get("arguments"), str) else call["raw"]
                    yield {"type": "tool.end", "id": call["call_id"], "name": call["name"], "input": parse_tool_input(raw), "raw": raw}
            elif t in ("response.completed", "response.incomplete"):
                r = ev.get("response") or {}
                u = r.get("usage") or {}
                if u:
                    cached = (u.get("input_tokens_details") or {}).get("cached_tokens") or 0
                    yield usage_event(input=(u.get("input_tokens") or 0) - cached, output=u.get("output_tokens") or 0,
                                      reasoning=(u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0, cache_read=cached)
                if t == "response.incomplete" and (r.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
                    finish = "length"
                break
            elif t == "response.failed":
                yield stream_error((ev.get("response") or {}).get("error") or ev)
                return
            elif t == "error":
                yield stream_error(ev)
                return
        for call in calls.values():  # a stream that ended without output_item.done
            if not call["ended"]:
                call["ended"] = True
                yield {"type": "tool.end", "id": call["call_id"], "name": call["name"], "input": parse_tool_input(call["raw"]), "raw": call["raw"]}
        if calls and finish != "length":
            finish = "tool_calls"
        yield {"type": "finish", "reason": finish}

    async def list_models(self) -> list[ModelInfo]:
        if self.chatgpt:  # the Codex backend's own list when it answers, else AFH's
            try:
                base, signed = await auth.prepare(self.config)
                async with make_client(self.headers() | signed, self._transport) as client:
                    resp = await client.get(join_url(base, "/models"), params={"client_version": "0.60.0"})
                items = (resp.json() or {}).get("models") if resp.status_code < 300 else None
                fetched = [catalog.guess_model(str(m.get("slug") or m.get("id")), "openai", name=m.get("display_name") or "",
                                               context=m.get("context_window")) for m in items or [] if isinstance(m, dict) and (m.get("slug") or m.get("id"))]
                return catalog.merge_static(self.config, fetched)
            except Exception:
                return catalog.merge_static(self.config, [])
        if not self.config.fetch_models:
            return catalog.merge_static(self.config, [])
        base, signed = await auth.prepare(self.config)
        url = join_url(base, "/models")
        async with make_client(self.headers() | signed, self._transport) as client:
            try:
                resp = await client.get(url)
            except NETWORK_ERRORS as exc:
                raise ProviderError(network_error(exc, url)["message"]) from exc
        if resp.status_code >= 300:
            body = decode_body(resp.content)
            raise ProviderError(error_message(body, resp.status_code), resp.status_code, body[:2000])
        items = (resp.json() or {}).get("data") or []
        return catalog.merge_static(self.config, [catalog.guess_model(str(m["id"]), "openai") for m in items if isinstance(m, dict) and m.get("id")])
