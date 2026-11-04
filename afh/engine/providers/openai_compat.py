"""OpenAI-compatible chat completions adapter (OpenAI, Kimi, Moonshot, Z.AI, DeepSeek, Groq, local servers...).

Tool-call arguments are forwarded as they stream (``tool.delta`` per chunk); nothing waits
for the final JSON except the parsed ``input`` in ``tool.end``.

Knobs read from ``config.extra``:
  effort_param      request field for ``req.variant`` (default ``reasoning_effort``)
  effort_style      ``"openrouter"`` sends ``{"reasoning": {"effort": v}}`` instead of a flat field
  effort_map        rename variants per provider, e.g. ``{"max": "high"}``
  thinking          ``"zai"`` sends GLM's ``{"thinking": {"type": "enabled"|"disabled"}}`` instead of an effort
  no_temperature    never send ``temperature`` (some reasoning models reject it)
  max_tokens_param  ``max_tokens`` (default) or ``max_completion_tokens`` (new OpenAI models)
  echo_reasoning    replay assistant reasoning in history under ``reasoning_field`` (Kimi needs it)
  reasoning_field   the delta/history field for reasoning text (default ``reasoning_content``)
  body              extra top-level fields merged into every request
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from afh.engine import auth, pricing, usage
from afh.engine.providers import catalog
from afh.engine.providers.sse import (
    NETWORK_ERRORS, ProviderError, decode_body, error_message, http_error, image_data, iter_json, join_url,
    make_client, network_error, new_call_id, parse_tool_input, stream_error, usage_event,
)
from afh.engine.types import ChatRequest, ModelInfo, ProviderConfig, ProviderEvent, ToolSpec


@dataclass
class _Call:
    """One streamed tool call, keyed by ``index`` in the chunk."""

    index: int
    id: str = ""
    name: str = ""
    raw: str = ""
    started: bool = False
    pending: str = ""  # argument text that arrived before the name (rare)
    ended: bool = False


class OpenAICompatProvider:
    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport

    # ---- request ----------------------------------------------------------------------

    def headers(self) -> dict[str, str]:
        h = {"content-type": "application/json", "accept": "text/event-stream"}
        if self.config.api_key:  # Azure wants ``api-key: <key>``, Cloudflare's gateway its own header
            prefix = self.config.extra.get("auth_prefix", "Bearer ")
            h[self.config.extra.get("auth_header", "authorization")] = f"{prefix}{self.config.api_key}"
        h.update(self.config.headers)
        return h

    def build_body(self, req: ChatRequest, include_usage: bool = True) -> dict:
        extra = self.config.extra
        body: dict = {"model": req.model, "messages": self.translate_messages(req), "stream": True}
        if include_usage:
            body["stream_options"] = {"include_usage": True}
        if req.tools:
            body["tools"] = [tool_spec(t) for t in req.tools]
        if req.max_tokens:
            body[extra.get("max_tokens_param", "max_tokens")] = req.max_tokens
        if req.temperature is not None and not extra.get("no_temperature"):
            body["temperature"] = req.temperature
        if extra.get("thinking") == "zai":
            if req.variant and req.reasoning:
                body["thinking"] = {"type": "enabled"}
                # GLM-5.x takes an effort level too (low / high / max); without it every effort was the same.
                body[extra.get("effort_param", "reasoning_effort")] = extra.get("effort_map", {}).get(req.variant, req.variant)
            elif not req.reasoning:
                body["thinking"] = {"type": "disabled"}
        elif req.variant and req.reasoning:
            effort = extra.get("effort_map", {}).get(req.variant, req.variant)
            if extra.get("effort_style") == "openrouter":
                body["reasoning"] = {"effort": effort}
            else:
                body[extra.get("effort_param", "reasoning_effort")] = effort
        body.update(extra.get("body", {}))
        return body

    def translate_messages(self, req: ChatRequest) -> list[dict]:
        extra = self.config.extra
        reasoning_field = extra.get("reasoning_field", "reasoning_content")
        out: list[dict] = []
        if req.system:
            out.append({"role": "system", "content": req.system})
        for m in req.messages:
            if m.role == "system":
                out.append({"role": "system", "content": m.text})
            elif m.role == "user":
                parts: list[dict] = []
                if m.text:
                    parts.append({"type": "text", "text": m.text})
                for img in m.images:
                    data = image_data(img)
                    if data:
                        parts.append({"type": "image_url", "image_url": {"url": f"data:{data[0]};base64,{data[1]}"}})
                # Plain string unless there is an image: every server accepts a string.
                out.append({"role": "user", "content": parts if len(parts) > 1 or (parts and parts[0]["type"] != "text") else m.text})
            elif m.role == "assistant":
                msg: dict = {"role": "assistant", "content": m.text or None}
                if extra.get("echo_reasoning") and m.reasoning:
                    msg[reasoning_field] = m.reasoning
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.input, ensure_ascii=False)}}
                        for c in m.tool_calls
                    ]
                out.append(msg)
            elif m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.text})
        return out

    # ---- streaming --------------------------------------------------------------------

    async def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]:
        try:
            base, signed = await auth.prepare(self.config, req)  # signed-in providers (Copilot): fresh token + headers
        except Exception as exc:
            yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
            return
        url = join_url(base, "/chat/completions")
        body = self.build_body(req)
        async with make_client(self.headers() | signed, self._transport) as client:
            for attempt in (0, 1):
                try:
                    async with client.stream("POST", url, json=body) as resp:
                        usage.observe(self.config.id, resp.headers)
                        if resp.status_code == 401 and attempt == 0 and auth.signed_in(self.config):
                            # A revoked or rotated token: get a new one and try once more.
                            await resp.aread()
                            try:
                                base, signed = await auth.prepare(self.config, req, force=True)
                            except Exception as exc:
                                yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
                                return
                            client.headers.update(signed)
                            url = join_url(base, "/chat/completions")
                            continue
                        if resp.status_code == 400 and attempt == 0 and "stream_options" in body:
                            # Older servers reject stream_options; a 400 costs no tokens, so retry without it.
                            await resp.aread()
                            body = {k: v for k, v in body.items() if k != "stream_options"}
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
        reasoning_fields = ("reasoning_content", "reasoning", self.config.extra.get("reasoning_field", "reasoning_content"))
        calls: dict[int, _Call] = {}
        by_id: dict[str, int] = {}
        finish: str | None = None
        usage: dict | None = None

        async for chunk in iter_json(resp):
            if chunk.get("error") and not chunk.get("choices"):
                yield stream_error(chunk)
                return
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                text = delta.get("content")
                if isinstance(text, list):  # a few servers send content parts even in deltas
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                if isinstance(text, str) and text:
                    yield {"type": "text.delta", "text": text}
                for f in dict.fromkeys(reasoning_fields):
                    r = delta.get(f)
                    if isinstance(r, str) and r:
                        yield {"type": "reasoning.delta", "text": r}
                for item in delta.get("tool_calls") or []:
                    if not isinstance(item, dict):
                        continue
                    idx = item.get("index")
                    if idx is None:  # servers that omit index: key by id, else append
                        idx = by_id.get(item.get("id") or "", len(calls))
                    call = calls.get(idx)
                    if call is None:
                        call = calls[idx] = _Call(index=idx)
                    if item.get("id") and not call.id:
                        call.id = item["id"]
                        by_id[call.id] = idx
                    fn = item.get("function") or {}
                    if fn.get("name") and not call.started:
                        call.name = fn["name"]  # assumed to arrive whole on the first chunk
                    if not call.started and call.name:
                        call.id = call.id or new_call_id()
                        call.started = True
                        yield {"type": "tool.start", "id": call.id, "name": call.name}
                        if call.pending:
                            yield {"type": "tool.delta", "id": call.id, "text": call.pending}
                            call.pending = ""
                    args = fn.get("arguments")
                    if isinstance(args, str) and args:
                        call.raw += args
                        if call.started:
                            yield {"type": "tool.delta", "id": call.id, "text": args}
                        else:
                            call.pending += args
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                    for ev in self._end_calls(calls):
                        yield ev
            u = chunk.get("usage")
            if isinstance(u, dict) and u:
                usage = u

        for ev in self._end_calls(calls):
            yield ev
        if usage:
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0
            yield usage_event(
                input=(usage.get("prompt_tokens") or 0) - cached, output=usage.get("completion_tokens", 0),
                reasoning=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
                cache_read=cached,
            )
        started = any(c.started for c in calls.values())
        if finish == "length":
            reason = "length"
        elif started or finish in ("tool_calls", "function_call"):
            reason = "tool_calls"  # some servers say "stop" even when they called tools
        else:
            reason = "stop"
        yield {"type": "finish", "reason": reason}

    @staticmethod
    def _end_calls(calls: dict[int, _Call]) -> list[ProviderEvent]:
        out = []
        for call in sorted(calls.values(), key=lambda c: c.index):
            if call.started and not call.ended:
                call.ended = True
                out.append({"type": "tool.end", "id": call.id, "name": call.name, "input": parse_tool_input(call.raw), "raw": call.raw})
        return out

    # ---- models -----------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
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
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"{url} did not return JSON") from exc
        items = data.get("data") if isinstance(data, dict) else data
        fetched: list[ModelInfo] = []
        for item in items or []:
            if isinstance(item, str):
                item = {"id": item}
            if not isinstance(item, dict) or not item.get("id"):
                continue
            caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else None
            if caps is not None:  # GitHub Copilot: only chat models this account may pick
                if caps.get("type", "chat") != "chat" or item.get("model_picker_enabled") is False or (item.get("policy") or {}).get("state") == "disabled":
                    continue
                limits, supports = caps.get("limits") or {}, caps.get("supports") or {}
                model = catalog.guess_model(str(item["id"]), "openai", name=item.get("name") or "",
                                            context=limits.get("max_context_window_tokens") or limits.get("max_prompt_tokens"), output=limits.get("max_output_tokens"))
                model.tools = supports.get("tool_calls", True) is not False
                if supports.get("vision"):
                    model.input = ["text", "image"]
                fetched.append(model)
                continue
            mid = str(item["id"])
            context = item.get("context_length") or item.get("context_window") or (item.get("top_provider") or {}).get("context_length")
            output = item.get("max_output_tokens") or item.get("max_completion_tokens") or (item.get("top_provider") or {}).get("max_completion_tokens")
            model = catalog.guess_model(mid, "openai", name=item.get("display_name") or item.get("name") or "", context=context, output=output)
            model.cost = pricing.from_openrouter(item.get("pricing"))
            fetched.append(model)
        return catalog.merge_static(self.config, fetched)


def tool_spec(t: ToolSpec) -> dict:
    return {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
