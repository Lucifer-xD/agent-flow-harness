"""Google Antigravity adapter: Gemini and Claude models paid for by a Google account's Antigravity
quota (sign in with ``engine/auth.py``; there is no API key).

Requests are Gemini ``generateContent`` bodies wrapped for Google's Cloud Code backend:
``POST /v1internal:streamGenerateContent?alt=sse`` with ``{project, model, request, ...}``, and each
SSE event carries the usual Gemini chunk under ``response``. ``fetchAvailableModels`` lists the
account's models together with the share of quota left on each (``quota``).

Claude models behind this API want tool-call ids on both halves of a call and VALIDATED function
calling; their thinking config uses snake_case keys.

Google lists some models once per effort (``gemini-4-hydrogen-low``/``-medium``/``-high``/``-xhigh``,
and the same for the newer Claude models). AFH shows them as one model whose effort levels are those
suffixes (``extra["effort_ids"]``, saved when the list is fetched) and sends ``<model>-<effort>`` for
the effort picked.
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
_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")  # weakest first: the order the picker shows
_EFFORT_ID = re.compile(r"^(.+)-(none|minimal|low|medium|high|xhigh|max)$")
_EFFORT_NAME = re.compile(r"\s*\((none|minimal|low|medium|high|x-?high|extra[ -]high|max|maximum)\)\s*$", re.IGNORECASE)


def regrouped(extra: dict, model: str) -> tuple[str, str] | None:
    """(model, effort) for an id that was one model per effort before AFH grouped it
    (``gemini-4-hydrogen-xhigh`` is now ``gemini-4-hydrogen`` at ``xhigh``), so a thread that was
    using the old id carries on with the same model and effort."""
    for base, efforts in ((extra or {}).get("effort_ids") or {}).items():
        for e in efforts:
            if model == f"{base}-{e}":
                return base, e
    return None


def _is_claude(model: str) -> bool:
    return "claude" in model.lower()


def regroup_stored(entry: dict) -> dict | None:
    """A patch for a stored provider whose model list was saved before per-effort ids were one model
    (``gemini-4-hydrogen-xhigh`` beside ``gemini-4-hydrogen``, ``claude-opus-5-5-low``/``-high``): the same
    grouping ``list_models`` does, so it holds from the first start after an update, not only after the
    list is fetched again. None when there is nothing to regroup."""
    fetched = [dict(m) for m in entry.get("fetched") or [] if isinstance(m, dict)]
    extra = dict(entry.get("extra") or {})
    effort_ids = {k: list(v) for k, v in (extra.get("effort_ids") or {}).items()}
    by_id = {m.get("id"): m for m in fetched}
    stray: dict[str, dict[str, dict]] = {}
    for m in fetched:
        mid = str(m.get("id") or "")
        match = None if mid in effort_ids or (_is_claude(mid) and "thinking" in mid) else _EFFORT_ID.match(mid)
        if match:
            stray.setdefault(match.group(1), {})[match.group(2)] = m
    if not stray:
        return None
    members_of = {id(m) for members in stray.values() for m in members.values()}
    out = [m for m in fetched if id(m) not in members_of]
    for base, members in stray.items():
        efforts = [e for e in _EFFORTS if e in members or e in effort_ids.get(base, [])]
        head = by_id.get(base)
        if head is None:
            src = members["high" if "high" in members else [e for e in _EFFORTS if e in members][-1]]
            head = {**src, "id": base, "name": _EFFORT_NAME.sub("", str(src.get("name") or "")) or base}
            out.append(head)
        head["variants"] = efforts if len(efforts) > 1 else []
        head["reasoning"] = bool(head.get("reasoning")) or len(efforts) > 1
        effort_ids[base] = efforts
    hidden = list(entry.get("hidden") or [])
    gone = [b for b in stray if b not in hidden and all(f"{b}-{e}" in hidden for e in effort_ids[b])]
    return {"fetched": out, "extra": {**extra, "effort_ids": effort_ids}, **({"hidden": hidden + gone} if gone else {})}


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
            rechecked = False
            for attempt in (0, 1, 2):
                try:
                    async with client.stream("POST", url, json=body) as resp:
                        usage.observe(usage.key(self.config), resp.headers)
                        if resp.status_code == 404:
                            text = decode_body(await resp.aread())
                            if not rechecked and await self._recheck_project(client):
                                rechecked = True  # Google moved the account's quota to another project: try there once
                                body["project"] = (self.config.auth or {}).get("project", "")
                                continue
                            yield self._not_found(req, text, resp.headers)
                            return
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
                            yield http_error(resp.status_code, decode_body(await resp.aread()), resp.headers)
                            return
                        async for ev in self._parse_events(self._unwrap(resp)):
                            yield ev
                        return
                except NETWORK_ERRORS as exc:
                    yield network_error(exc, url)
                    return

    async def _recheck_project(self, client: httpx.AsyncClient) -> bool:
        """Ask Google again which project holds this account's quota. True when it changed (and is saved)."""
        cfg = self.config
        auth_ = dict(cfg.auth or {})
        try:
            project = await auth._antigravity_project(client, auth_.get("access", ""))
        except Exception:  # refused or unreachable: the 404 stands
            return False
        if not project or project == auth_.get("project"):
            return False
        cfg.auth = auth_ | {"project": project}
        provcfg.save_creds(cfg.id, cfg.account_id, {"auth": cfg.auth})
        return True

    def _not_found(self, req: ChatRequest, body: str, headers) -> dict:
        """Google's bare "Requested entity was not found": say what it means. engine/limits.py reads `missing` to move a
        run to another account, since this one can't use the model."""
        ev = http_error(404, body, headers)
        who = f" ({self.config.account_label})" if self.config.account_label else ""
        ev["message"] = (f"Google says this account{who} can't use {self.model_id(req)}: the model has left its plan, or the "
                         "account was never set up for it. Pick another model, or another account in Settings → Models & accounts.")
        ev["missing"] = True
        return ev

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
            # the older Claude ids end in "-thinking" and take a thinking budget; the newer ones are listed per effort
            match = None if _is_claude(mid) and "thinking" in mid else _EFFORT_ID.match(mid)
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
            patch: dict = {"extra": self.config.extra}
            try:
                # A model the user had hidden at every effort stays hidden now that it is one entry.
                hidden = list((provcfg.entry(self.config.id) or {}).get("hidden") or [])
                gone = [b for b, efforts in effort_ids.items() if b not in hidden and all(f"{b}-{e}" in hidden for e in efforts)]
                if gone:
                    patch["hidden"] = hidden + gone
                provcfg.upsert(self.config.id, patch)
            except Exception:
                pass
        return catalog.merge_static(self.config, fetched)
