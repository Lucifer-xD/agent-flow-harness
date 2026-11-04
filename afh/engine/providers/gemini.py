"""Google Gemini adapter (``models/{model}:streamGenerateContent?alt=sse``).

Gemini delivers function-call arguments whole, so each call becomes ``tool.start`` → one
``tool.delta`` with the JSON → ``tool.end``. Gemini 3 attaches a ``thoughtSignature`` to
function-call parts that must be replayed in history; the adapter remembers signatures per
tool-call id in memory and otherwise sends Google's documented skip-validation placeholder.

The key goes in the ``x-goog-api-key`` header (never in the URL, so it stays out of logs);
set ``extra["key_in_query"]`` for proxies that only understand ``?key=``.

Knobs read from ``config.extra``: ``budgets`` (variant → thinkingBudget), ``key_in_query``,
``body`` (extra top-level fields).
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from afh.engine import usage
from afh.engine.providers import catalog
from afh.engine.providers.sse import (
    NETWORK_ERRORS, ProviderError, decode_body, error_message, http_error, image_data, iter_json, join_url,
    make_client, network_error, new_call_id, stream_error, tool_name_for, usage_event,
)
from afh.engine.types import ChatMessage, ChatRequest, ModelInfo, ProviderConfig, ProviderEvent

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
BUDGETS = {"low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384, "max": 24576}
LEVELS = {"low": "low", "medium": "medium", "high": "high", "max": "high"}  # Gemini 3 ``thinkingLevel``
SKIP_SIGNATURE = "skip_thought_signature_validator"
# Finish reasons that mean the model was cut off rather than done.
BLOCKED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "MALFORMED_FUNCTION_CALL", "IMAGE_SAFETY"}
# The JSON-schema keys Gemini's OpenAPI subset accepts; anything else (exclusiveMinimum, const,
# $ref, additionalProperties...) is a 400 "Unknown name", so it is rewritten or dropped.
_SCHEMA_KEEP = {"type", "format", "description", "nullable", "enum", "items", "properties", "required", "anyOf",
                "minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "pattern", "propertyOrdering"}
_FORMATS = {"enum", "date-time", "int32", "int64", "float", "double"}
# Constraints validated function calling rejects; kept as description hints.
_STRICT_HINTS = ("minLength", "maxLength", "pattern", "minItems", "maxItems", "format")
_CACHE_LIMIT = 512


class GeminiProvider:
    call_ids = False  # send tool-call ids on functionCall/functionResponse (Claude behind a Gemini API needs them)

    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport
        self._signatures: dict[str, str] = {}  # tool-call id → thoughtSignature

    # ---- request ----------------------------------------------------------------------

    def headers(self) -> dict[str, str]:
        h = {"content-type": "application/json", "accept": "text/event-stream"}
        if self.config.api_key and not self.config.extra.get("key_in_query"):
            h["x-goog-api-key"] = self.config.api_key
        h.update(self.config.headers)
        return h

    def url(self, path: str, query: str = "") -> str:
        url = join_url(self.config.base_url or DEFAULT_BASE_URL, path)
        params = [query] if query else []
        if self.config.api_key and self.config.extra.get("key_in_query"):
            params.append(f"key={self.config.api_key}")
        return url + ("?" + "&".join(params) if params else "")

    def build_body(self, req: ChatRequest) -> dict:
        extra = self.config.extra
        body: dict = {"contents": self.translate_messages(req.messages, req.model)}
        system = "\n\n".join(s for s in [req.system] + [m.text for m in req.messages if m.role == "system"] if s)
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if req.tools:
            decls = []
            for t in req.tools:
                decl: dict = {"name": t.name, "description": t.description}
                params = clean_schema(t.parameters or {}, strict=self.strict_schema(req))
                if params.get("properties"):  # an empty object schema is rejected
                    decl["parameters"] = params
                decls.append(decl)
            body["tools"] = [{"functionDeclarations": decls}]
        gen: dict = {}
        if req.max_tokens:
            gen["maxOutputTokens"] = req.max_tokens
        if req.temperature is not None:
            gen["temperature"] = req.temperature
        if req.reasoning and req.variant:
            if "gemini-3" in req.model.lower():
                gen["thinkingConfig"] = {"thinkingLevel": LEVELS.get(req.variant, "high"), "includeThoughts": True}
            else:
                gen["thinkingConfig"] = {"thinkingBudget": extra.get("budgets", BUDGETS).get(req.variant, BUDGETS["high"]), "includeThoughts": True}
        elif req.reasoning and "gemini-2.5" in req.model.lower():
            gen["thinkingConfig"] = {"includeThoughts": True}  # dynamic budget, but show the thoughts
        if gen:
            body["generationConfig"] = gen
        body.update(extra.get("body", {}))
        return body

    def strict_schema(self, req: ChatRequest) -> bool:
        return False

    def translate_messages(self, messages: list[ChatMessage], model: str = "") -> list[dict]:
        out: list[dict] = []
        gemini3 = "gemini-3" in model.lower()

        def push(role: str, parts: list[dict]) -> None:
            if out and out[-1]["role"] == role:
                out[-1]["parts"].extend(parts)
            else:
                out.append({"role": role, "parts": parts})

        for m in messages:
            if m.role == "user":
                parts: list[dict] = []
                if m.text:
                    parts.append({"text": m.text})
                for img in m.images:
                    data = image_data(img)
                    if data:
                        parts.append({"inlineData": {"mimeType": data[0], "data": data[1]}})
                if parts:
                    push("user", parts)
            elif m.role == "assistant":
                parts = []
                if m.text:
                    parts.append({"text": m.text})
                for c in m.tool_calls:
                    part: dict = {"functionCall": {"name": c.name, "args": c.input, **({"id": c.id} if self.call_ids else {})}}
                    sig = self._signatures.get(c.id)
                    if sig:
                        part["thoughtSignature"] = sig
                    elif gemini3:
                        part["thoughtSignature"] = SKIP_SIGNATURE
                    parts.append(part)
                if parts:
                    push("model", parts)
            elif m.role == "tool":
                name = m.tool_name or tool_name_for(messages, m.tool_call_id) or "tool"
                response = {"result": m.text}
                fr = {"name": name, "response": response, **({"id": m.tool_call_id} if self.call_ids and m.tool_call_id else {})}
                push("user", [{"functionResponse": fr}])
        return out

    # ---- streaming --------------------------------------------------------------------

    async def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]:
        url = self.url(f"/v1beta/models/{req.model}:streamGenerateContent", "alt=sse")
        body = self.build_body(req)
        async with make_client(self.headers(), self._transport) as client:
            try:
                async with client.stream("POST", url, json=body) as resp:
                    usage.observe(self.config.id, resp.headers)
                    if resp.status_code >= 300:
                        yield http_error(resp.status_code, decode_body(await resp.aread()))
                        return
                    async for ev in self._parse(resp):
                        yield ev
            except NETWORK_ERRORS as exc:
                yield network_error(exc, url)

    async def _parse(self, resp: httpx.Response) -> AsyncIterator[ProviderEvent]:
        async for ev in self._parse_events(iter_json(resp)):
            yield ev

    async def _parse_events(self, events: AsyncIterator[dict]) -> AsyncIterator[ProviderEvent]:
        calls = 0
        finish: str | None = None
        usage: dict | None = None
        blocked: str | None = None

        async for ev in events:
            if ev.get("error"):
                yield stream_error(ev)
                return
            feedback = ev.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                blocked = f"prompt blocked: {feedback['blockReason']}"
            for cand in ev.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        yield {"type": "reasoning.delta" if part.get("thought") else "text.delta", "text": text}
                    fc = part.get("functionCall")
                    if isinstance(fc, dict) and fc.get("name"):
                        calls += 1
                        cid = fc.get("id") or new_call_id()
                        args = fc.get("args") if isinstance(fc.get("args"), dict) else {}
                        raw = json.dumps(args, ensure_ascii=False)
                        if part.get("thoughtSignature"):
                            self._remember(cid, part["thoughtSignature"])
                        yield {"type": "tool.start", "id": cid, "name": fc["name"]}
                        yield {"type": "tool.delta", "id": cid, "text": raw}
                        yield {"type": "tool.end", "id": cid, "name": fc["name"], "input": args, "raw": raw}
                if cand.get("finishReason"):
                    finish = cand["finishReason"]
            if isinstance(ev.get("usageMetadata"), dict):
                usage = ev["usageMetadata"]

        if usage:
            thoughts = usage.get("thoughtsTokenCount") or 0
            yield usage_event(
                input=(usage.get("promptTokenCount") or 0) - (usage.get("cachedContentTokenCount") or 0),
                output=(usage.get("candidatesTokenCount") or 0) + thoughts,  # like OpenAI, output includes reasoning
                reasoning=thoughts, cache_read=usage.get("cachedContentTokenCount") or 0,
            )
        if blocked or (finish in BLOCKED):
            msg = blocked or f"Generation stopped: {finish}"
            yield {"type": "error", "message": msg, "status": None, "kind": "blocked", "response": ""}
            yield {"type": "finish", "reason": "error"}
        elif finish == "MAX_TOKENS":
            yield {"type": "finish", "reason": "length"}
        else:
            yield {"type": "finish", "reason": "tool_calls" if calls else "stop"}

    def _remember(self, call_id: str, signature: str) -> None:
        self._signatures[call_id] = signature
        while len(self._signatures) > _CACHE_LIMIT:
            self._signatures.pop(next(iter(self._signatures)))

    # ---- models -----------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        if not self.config.fetch_models:
            return catalog.merge_static(self.config, [])
        fetched: list[ModelInfo] = []
        token: str | None = None
        async with make_client(self.headers(), self._transport) as client:
            for _ in range(10):
                url = self.url("/v1beta/models", "pageSize=1000" + (f"&pageToken={token}" if token else ""))
                try:
                    resp = await client.get(url)
                except NETWORK_ERRORS as exc:
                    raise ProviderError(network_error(exc, url)["message"]) from exc
                if resp.status_code >= 300:
                    body = decode_body(resp.content)
                    raise ProviderError(error_message(body, resp.status_code), resp.status_code, body[:2000])
                data = resp.json()
                for item in data.get("models") or []:
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    methods = item.get("supportedGenerationMethods") or []
                    if methods and "generateContent" not in methods:
                        continue  # embeddings, imagen, tts...
                    mid = str(item["name"]).removeprefix("models/")
                    fetched.append(catalog.guess_model(mid, "gemini", name=item.get("displayName") or "",
                                                       context=item.get("inputTokenLimit"), output=item.get("outputTokenLimit")))
                token = data.get("nextPageToken")
                if not token:
                    break
        return catalog.merge_static(self.config, fetched)


def clean_schema(schema: dict, strict: bool = False) -> dict:
    """A JSON schema reduced to what Gemini's function declarations accept: ``exclusiveMinimum``
    becomes ``minimum``, ``const`` a one-value ``enum``, ``type: [x, "null"]`` ``nullable``; other
    keywords are dropped. ``strict`` also moves length/pattern/format limits into the description."""
    src = dict(schema)
    for exclusive, inclusive in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        if isinstance(src.get(exclusive), (int, float)) and not isinstance(src[exclusive], bool):
            src.setdefault(inclusive, src[exclusive])
    if "const" in src and "enum" not in src:
        src["enum"] = [src["const"]]
    if isinstance(src.get("type"), list):
        types = [t for t in src["type"] if t != "null"]
        if len(types) < len(src["type"]):
            src["nullable"] = True
        src["type"] = types[0] if types else "string"
    if "anyOf" not in src and isinstance(src.get("oneOf"), list):
        src["anyOf"] = src["oneOf"]
    if src.get("format") not in _FORMATS:
        src.pop("format", None)
    hints = []
    if strict:
        hints = [f"{k}: {src.pop(k)}" for k in _STRICT_HINTS if k in src]
    out: dict = {}
    for key, value in src.items():
        if key not in _SCHEMA_KEEP:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: clean_schema(v, strict) if isinstance(v, dict) else v for k, v in value.items()}
        elif isinstance(value, dict):
            out[key] = clean_schema(value, strict)
        elif isinstance(value, list) and key != "enum":
            out[key] = [clean_schema(v, strict) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    if hints:
        out["description"] = (f"{out['description']} " if out.get("description") else "") + f"({', '.join(hints)})"
    if "enum" in out and not all(isinstance(v, str) for v in out["enum"]):  # Gemini enums are strings only
        values = out.pop("enum")
        out["description"] = (f"{out['description']} " if out.get("description") else "") + f"(one of: {', '.join(json.dumps(v) for v in values)})"
    return out
