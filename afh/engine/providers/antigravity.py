"""Google Antigravity adapter: Gemini and Claude models paid for by a Google account's Antigravity
quota (sign in with ``engine/auth.py``; there is no API key).

Requests are Gemini ``generateContent`` bodies wrapped for Google's Cloud Code backend:
``POST /v1internal:streamGenerateContent?alt=sse`` with ``{project, model, request, ...}``, and each
SSE event carries the usual Gemini chunk under ``response``. ``fetchAvailableModels`` lists the
account's models together with the share of quota left on each (``quota``).

Claude models behind this API want tool-call ids on both halves of a call and VALIDATED function
calling; their thinking config uses snake_case keys.

Google lists some models once per effort (``gemini-3.8-flash-low``/``-medium``/``-high``). AFH shows
them as one model whose effort levels are those suffixes (``extra["effort_ids"]``, saved when the
list is fetched) and sends ``<model>-<effort>`` for the effort picked.
"""

from __future__ import annotations

import re
import uuid
from typing import AsyncIterator

import httpx

from afh.engine import auth, usage
from afh.engine import config as provcfg
from afh.engine.providers import catalog
from afh.engine.providers.gemini import BUDGETS, GeminiProvider
from afh.engine.providers.sse import (
    NETWORK_ERRORS, ProviderError, decode_body, error_message, http_error, iter_json, make_client, network_error,
)
from afh.engine.types import ChatRequest, ModelInfo, ProviderConfig, ProviderEvent

# Chat models the account can pick; image models, routers and completion-only ids are left out.
_CHAT = ("gemini-", "claude-", "gpt-oss-")
_SKIP = ("image", "imagen", "-disabled", "-tiered", "chat_", "tab_")
_EFFORTS = ("minimal", "low", "medium", "high")
_EFFORT_ID = re.compile(r"^(.+)-(minimal|low|medium|high)$")
_EFFORT_NAME = re.compile(r"\s*\((minimal|low|medium|high)\)\s*$", re.IGNORECASE)


def _is_claude(model: str) -> bool:
    return "claude" in model.lower()


class AntigravityProvider(GeminiProvider):
    call_ids = True

    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(config, transport)
        self.call_ids = True

    def headers(self) -> dict[str, str]:
        return {"content-type": "application/json", "accept": "text/event-stream", **self.config.headers}

    def efforts(self, model: str) -> list[str]:
        return list((self.config.extra.get("effort_ids") or {}).get(model) or [])

    def model_id(self, req: ChatRequest) -> str:
        """The id Google knows: ``<model>-<effort>`` for a model listed once per effort."""
        efforts = self.efforts(req.model)
        if not efforts:
            return req.model
        pick = req.variant if req.variant in efforts else ("high" if "high" in efforts else efforts[-1])
        return f"{req.model}-{pick}"

    def strict_schema(self, req: ChatRequest) -> bool:
        return _is_claude(req.model)

    def build_body(self, req: ChatRequest) -> dict:
        body = super().build_body(req)
        if self.efforts(req.model):  # the effort is in the id; just show the thoughts
            gen = body.setdefault("generationConfig", {})
            gen.pop("thinkingConfig", None)
            if req.reasoning:
                gen["thinkingConfig"] = {"includeThoughts": True}
        if _is_claude(req.model):
            for group in body.get("tools") or []:
                for decl in group.get("functionDeclarations") or []:
                    decl.setdefault("parameters", {"type": "object", "properties": {}})
            if body.get("tools"):
                body["toolConfig"] = {"functionCallingConfig": {"mode": "VALIDATED"}}
            gen = body.setdefault("generationConfig", {})
            gen.pop("thinkingConfig", None)
            if req.reasoning and "thinking" in req.model.lower():
                budget = self.config.extra.get("budgets", BUDGETS).get(req.variant or "high", BUDGETS["high"])
                gen["thinkingConfig"] = {"include_thoughts": True, "thinking_budget": budget}
                gen["maxOutputTokens"] = max(int(gen.get("maxOutputTokens") or 0), budget + 8192)
        return body

    def wrap(self, req: ChatRequest) -> dict:
        return {"project": (self.config.auth or {}).get("project", ""), "model": self.model_id(req), "request": self.build_body(req),
                "requestType": "agent", "userAgent": "antigravity", "requestId": f"agent-{uuid.uuid4()}"}

    async def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]:
        try:
            base, signed = await auth.prepare(self.config, req)
        except Exception as exc:
            yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
            return
        url = f"{base.rstrip('/')}/v1internal:streamGenerateContent?alt=sse"
        body = self.wrap(req)
        async with make_client(self.headers() | signed, self._transport) as client:
            for attempt in (0, 1):
                try:
                    async with client.stream("POST", url, json=body) as resp:
                        usage.observe(self.config.id, resp.headers)
                        if resp.status_code == 401 and attempt == 0:
                            await resp.aread()
                            try:
                                _, signed = await auth.prepare(self.config, req, force=True)
                            except Exception as exc:
                                yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
                                return
                            client.headers.update(signed)
                            continue
                        if resp.status_code >= 300:
                            yield http_error(resp.status_code, decode_body(await resp.aread()))
                            return
                        async for ev in self._parse_events(self._unwrap(resp)):
                            yield ev
                        return
                except NETWORK_ERRORS as exc:
                    yield network_error(exc, url)
                    return

    @staticmethod
    async def _unwrap(resp: httpx.Response) -> AsyncIterator[dict]:
        async for ev in iter_json(resp):
            inner = ev.get("response")
            yield inner if isinstance(inner, dict) else ev

    # ---- models and quota ---------------------------------------------------------------

    async def available(self) -> dict:
        """The raw ``fetchAvailableModels`` answer: every model with its ``quotaInfo``."""
        base, signed = await auth.prepare(self.config)
        url = f"{base.rstrip('/')}/v1internal:fetchAvailableModels"
        project = (self.config.auth or {}).get("project", "")
        async with make_client({"content-type": "application/json"} | signed, self._transport) as client:
            try:
                resp = await client.post(url, json={"project": project} if project else {})
            except NETWORK_ERRORS as exc:
                raise ProviderError(network_error(exc, url)["message"]) from exc
        if resp.status_code >= 300:
            body = decode_body(resp.content)
            raise ProviderError(error_message(body, resp.status_code), resp.status_code, body[:2000])
        return resp.json()

    async def list_models(self) -> list[ModelInfo]:
        data = await self.available()
        visible = {i for sort in data.get("agentModelSorts") or [] for g in sort.get("groups") or [] for i in g.get("modelIds") or []}
        visible |= {i for ids in (data.get("tieredModelIds") or {}).values() for i in ids}
        fetched: list[ModelInfo] = []
        groups: dict[str, dict[str, ModelInfo]] = {}  # base id -> effort -> model
        for mid, m in (data.get("models") or {}).items():
            if not isinstance(m, dict) or not mid.startswith(_CHAT) or any(x in mid for x in _SKIP) or m.get("disabled"):
                continue
            if visible and mid not in visible:
                continue
            info = catalog.guess_model(mid, "gemini", name=m.get("displayName") or "", context=m.get("maxTokens"), output=m.get("maxOutputTokens"))
            info.input = ["text"] if m.get("supportsImages") is False else ["text", "image"]
            if m.get("supportsThinking") is not None:
                info.reasoning = bool(m["supportsThinking"])
            if _is_claude(mid):
                info.variants = ["low", "high", "max"] if "thinking" in mid else []
            match = None if _is_claude(mid) else _EFFORT_ID.match(mid)
            if match:
                groups.setdefault(match.group(1), {})[match.group(2)] = info
            else:
                fetched.append(info)
        effort_ids: dict[str, list[str]] = {}
        for base, members in groups.items():
            efforts = [e for e in _EFFORTS if e in members]
            info = members["high" if "high" in members else efforts[-1]]
            info.id = base
            info.name = _EFFORT_NAME.sub("", info.name) or base
            info.variants = efforts if len(efforts) > 1 else []
            info.reasoning = info.reasoning or len(efforts) > 1
            effort_ids[base] = efforts
            fetched.append(info)
        if effort_ids != (self.config.extra.get("effort_ids") or {}):
            self.config.extra = {**self.config.extra, "effort_ids": effort_ids}
            try:
                provcfg.upsert(self.config.id, {"extra": self.config.extra})
            except Exception:
                pass
        return catalog.merge_static(self.config, fetched)
