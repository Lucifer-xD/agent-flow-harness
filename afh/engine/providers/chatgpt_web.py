"""The ChatGPT normal-chat lane, in-harness (no middleman).

Drives ChatGPT's own web backend with a browser session (imported from the user's Chrome),
the way shadowgate does: session cookie → access token (``auth.prepare``) → sentinel
requirements + proof-of-work (``pow.py``) → ``POST /backend-api/conversation`` SSE. The bare
chat slugs are the unmetered lane (they do not spend Codex / work credits); ``-wm`` slugs with
``conversation_origin: "tpp"`` are the metered work lane.

The backend has no native function calling, so ``chatgpt_bridge`` teaches the chat model a text
protocol and this adapter turns ``<tool_call>`` blocks back into ordinary tool events — so AFH's
agent loop drives the whole harness through a model that is "just a chat". When the model
announces an action without emitting a block, it is nudged (a few times) within the same turn.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import AsyncIterator

import httpx

from afh.engine import auth
from afh.engine.providers import catalog, chatgpt_bridge as bridge
from afh.engine.providers.pow import PoW
from afh.engine.providers.sse import (
    NETWORK_ERRORS, ProviderError, decode_body, error_message, http_error, iter_json, join_url,
    make_client, network_error, usage_event,
)
from afh.engine.types import ChatRequest, ModelInfo, ProviderConfig, ProviderEvent

MAX_NUDGES = 2
MAX_PART_CHARS = 320_000  # a single message above ~330k chars is rejected
_PUA = re.compile("[-]")
_PUA_SPAN = re.compile("[\\s\\S]*?")
_WRITING = re.compile(r":::writing\{[^}\n]*\}\n?")
_WRITING_LINE = re.compile(r"^:::[ \t]*$\n?", re.M)


def _effort(variant: str | None) -> str | None:
    if not variant:
        return None
    return "extended" if variant in ("high", "xhigh", "max", "extended") else "standard"


def clean_visible_text(s: str) -> str:
    return _WRITING_LINE.sub("", _WRITING.sub("", _PUA.sub("", _PUA_SPAN.sub("", s))))


def hold_back_partial_markup(s: str) -> str:
    """Drop an unterminated private-use marker or writing fence from the end of streamed text."""
    o = s.rfind("")
    if o != -1 and s.find("", o) == -1:
        s = s[:o]
    m = re.search(r"(?:^|\n)(:{1,3}(?:writing(?:\{[^}\n]*)?|w|wr|wri|writ|writi|writin)?)$", s)
    if m:
        s = s[: len(s) - len(m.group(1))]
    return s


class ChatGPTWebProvider:
    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport
        self._pow: PoW | None = None
        self.last_served: dict = {}  # {experience, slug, tool} from the backend's server_ste_metadata

    def pow(self) -> PoW:
        if self._pow is None:
            self._pow = PoW(user_agent=(self.config.auth or {}).get("ua") or "")
        return self._pow

    # ---- building the request ----

    def _turns(self, req: ChatRequest) -> list[dict]:
        turns = bridge.transform_history(req.messages)
        if req.system:
            turns = [{"role": "critic", "text": req.system, "images": []}, *turns]
        if req.tools:
            preamble = bridge.tool_preamble(req.tools, "auto")
            turns = bridge.inject_preamble(turns, preamble, [t.name for t in req.tools])
        return turns

    def build_body(self, turns: list[dict], slug: str, effort: str | None, work_mode: bool) -> dict:
        messages = []
        for t in turns:
            for part in _split_long(t["text"]):
                messages.append({"id": str(uuid.uuid4()), "author": {"role": t["role"]},
                                 "content": {"content_type": "text", "parts": [part]}})
        body: dict = {
            "action": "next", "conversation_mode": {"kind": "primary_assistant"}, "messages": messages,
            "parent_message_id": str(uuid.uuid4()), "model": slug, "history_and_training_disabled": True,
            "websocket_request_id": str(uuid.uuid4()), "force_use_sse": True,
        }
        if effort:
            body["thinking_effort"] = effort
        if work_mode:
            body["conversation_origin"] = "tpp"  # the -wm slug silently falls back to a chat model without this
        return body

    # ---- the stream ----

    async def stream(self, req: ChatRequest) -> AsyncIterator[ProviderEvent]:
        try:
            base, signed = await auth.prepare(self.config, req)
        except Exception as exc:
            yield {"type": "error", "message": str(exc), "status": 401, "kind": "auth", "response": ""}
            return
        slug = req.model
        work = slug.endswith("-wm")
        effort = _effort(req.variant) if (work or "thinking" in slug) else None
        turns = self._turns(req)
        nudges = 0
        refreshed = False
        text_out = ""
        async with make_client(signed, self._transport) as client:
            while True:
                try:
                    req_tok = await self._requirements(client, base)
                except _AuthExpired:
                    if refreshed:
                        yield {"type": "error", "message": "ChatGPT session expired. Import your Chrome login again.", "status": 401, "kind": "auth", "response": ""}
                        return
                    refreshed = True
                    base, signed = await self._reprepare(req)
                    client.headers.update(signed)
                    continue
                except ProviderError as exc:
                    yield {"type": "error", "message": str(exc), "status": 502, "kind": "upstream", "response": ""}
                    return
                except NETWORK_ERRORS as exc:
                    yield network_error(exc, base)
                    return
                proof = self.pow().conversation_proof(req_tok["seed"], req_tok["difficulty"]) if req_tok["pow"] else ""
                body = self.build_body(turns, slug, effort, work)
                input_ids = {m["id"] for m in body["messages"]}
                headers = {"accept": "text/event-stream", "content-type": "application/json",
                           "openai-sentinel-chat-requirements-token": req_tok["token"]}
                if proof:
                    headers["openai-sentinel-proof-token"] = proof
                splitter = bridge.ToolCallSplitter()
                stream_err: dict | None = None
                try:
                    async with client.stream("POST", join_url(base, "/backend-api/conversation"), json=body, headers=headers) as resp:
                        if resp.status_code == 401 and not refreshed:
                            await resp.aread()
                            refreshed = True
                            base, signed = await self._reprepare(req)
                            client.headers.update(signed)
                            continue
                        if resp.status_code >= 300:
                            yield http_error(resp.status_code, decode_body(await resp.aread()))
                            return
                        async for ev in self._translate(resp, input_ids):
                            if "text" in ev:
                                safe = splitter.push(ev["text"])
                                if safe:
                                    text_out += safe
                                    yield {"type": "text.delta", "text": safe}
                            elif "reasoning" in ev:
                                yield {"type": "reasoning.delta", "text": ev["reasoning"]}
                            elif "served" in ev:
                                self.last_served = ev["served"]
                                if ev["served"].get("slug"):
                                    yield {"type": "served", "slug": ev["served"].get("slug"), "experience": ev["served"].get("experience")}
                            elif "error" in ev:
                                stream_err = ev["error"]
                                break
                except NETWORK_ERRORS as exc:
                    if not text_out:
                        yield network_error(exc, base)
                        return
                    stream_err = {"message": str(exc)}
                full, calls, unsent = splitter.finish()
                if stream_err and not full and not calls:
                    yield {"type": "error", "message": error_message(json.dumps(stream_err)) or str(stream_err), "status": 502, "kind": "upstream", "response": ""}
                    return
                if calls:
                    if unsent:
                        yield {"type": "text.delta", "text": unsent}
                    for c in calls:
                        yield {"type": "tool.start", "id": c["id"], "name": c["name"]}
                        if c["raw"]:
                            yield {"type": "tool.delta", "id": c["id"], "text": c["raw"]}
                        yield {"type": "tool.end", "id": c["id"], "name": c["name"], "input": c["input"], "raw": c["raw"]}
                    yield usage_event(output=_estimate(full))
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                # no tool call this sub-turn: nudge if the model stalled, else finish
                if req.tools and nudges < MAX_NUDGES and (not full.strip() or bridge.looks_like_unfulfilled_intent(full)):
                    nudges += 1
                    turns = [*turns, {"role": "assistant", "text": full, "images": []},
                             {"role": "user", "text": bridge.NUDGE_EMPTY_MESSAGE if not full.strip() else bridge.NUDGE_MESSAGE, "images": []}]
                    continue
                if unsent:
                    yield {"type": "text.delta", "text": unsent}
                yield usage_event(output=_estimate(full))
                yield {"type": "finish", "reason": "length" if stream_err else "stop"}
                return

    async def _reprepare(self, req: ChatRequest) -> tuple[str, dict]:
        return await auth.prepare(self.config, req, force=True)

    async def _requirements(self, client: httpx.AsyncClient, base: str) -> dict:
        resp = await client.post(join_url(base, "/backend-api/sentinel/chat-requirements"),
                                 json={"p": self.pow().requirements_proof()}, headers={"accept": "*/*", "content-type": "application/json"})
        if resp.status_code == 401:
            raise _AuthExpired()
        if resp.status_code >= 300:
            raise ProviderError(error_message(decode_body(resp.content), resp.status_code), resp.status_code)
        data = resp.json() if resp.content else {}
        if data.get("force_login"):
            raise _AuthExpired()
        po = data.get("proofofwork") or {}
        return {"token": data.get("token") or "", "pow": bool(po.get("required")), "seed": po.get("seed") or "", "difficulty": po.get("difficulty") or ""}

    async def _translate(self, resp: httpx.Response, skip_ids: set[str]) -> AsyncIterator[dict]:
        """Port of shadowgate's parseChatGPTSSE (chat turns): yields {text}/{reasoning}/{error} deltas.
        Handles full frames, wrapped full frames and delta/patch frames; thoughts become reasoning."""
        tracked: dict[str, dict] = {}   # id -> {parts, refs, final, emitted}
        meta: dict[str, dict] = {}       # id -> last full message object (for patches)
        thoughts: dict[str, str] = {}
        state = {"last_id": "", "out_tail": "", "seen_slug": "", "errored": set()}

        def visible(m: dict) -> bool:
            if (m.get("author") or {}).get("role") != "assistant":
                return False
            ct = (m.get("content") or {}).get("content_type")
            if ct not in ("text", "multimodal_text") or not isinstance((m.get("content") or {}).get("parts"), list):
                return False
            if m.get("recipient") and m.get("recipient") != "all":
                return False
            mt = (m.get("metadata") or {}).get("message_type")
            if mt and mt not in ("next", "continue"):
                return False
            if (m.get("metadata") or {}).get("is_visually_hidden_from_conversation") is True:
                return False
            return True

        def emit_text(t: dict):
            raw = hold_back_partial_markup("".join(p for p in t["parts"] if isinstance(p, str)))
            if not t["final"]:
                p = raw.find("")
                if p != -1:
                    raw = raw[:p]
            full = clean_visible_text(raw)
            if full.startswith(t["emitted"]):
                delta = full[len(t["emitted"]):]
            elif not t["emitted"]:
                delta = full
            else:
                return
            if not delta:
                return
            if not t["emitted"]:
                if not state["out_tail"]:
                    delta = delta.lstrip()
                elif not state["out_tail"][-1:].isspace() and not delta[:1].isspace():
                    delta = "\n\n" + delta
                if not delta:
                    return
            t["emitted"] = full
            state["out_tail"] = delta[-2:]
            yield {"text": delta}

        def handle_message(m: dict):
            if not m or not m.get("id") or m["id"] in skip_ids:
                return
            meta[m["id"]] = m
            md = m.get("metadata") or {}
            em = md.get("error_metadata")
            if isinstance(em, dict) and (em.get("error_code") or em.get("error_message")) and m["id"] not in state["errored"]:
                state["errored"].add(m["id"])
                yield {"error": {"code": em.get("error_code") or "upstream_error", "message": em.get("error_message") or ""}}
            if isinstance(md.get("model_slug"), str) and md["model_slug"] != state["seen_slug"]:
                state["seen_slug"] = md["model_slug"]
            ct = (m.get("content") or {}).get("content_type") or ""
            role = (m.get("author") or {}).get("role")
            if role == "assistant" and ct == "thoughts" and isinstance((m.get("content") or {}).get("thoughts"), list):
                txt = "\n".join("\n".join(x for x in (th.get("summary"), th.get("content")) if isinstance(x, str) and x)
                                for th in m["content"]["thoughts"]).strip()
                prev = thoughts.get(m["id"], "")
                if txt.startswith(prev) and len(txt) > len(prev):
                    chunk = ("" if prev else ("\n" if thoughts else "")) + txt[len(prev):]
                    thoughts[m["id"]] = txt
                    yield {"reasoning": chunk}
                elif not prev and txt:
                    thoughts[m["id"]] = txt
                    yield {"reasoning": ("\n" if len(thoughts) > 1 else "") + txt}
                return
            if role == "assistant" and ct == "reasoning_recap" and isinstance((m.get("content") or {}).get("content"), str) and not thoughts:
                thoughts[m["id"]] = m["content"]["content"]
                yield {"reasoning": m["content"]["content"]}
                return
            if not visible(m):
                return
            t = tracked.get(m["id"])
            if not t:
                t = {"parts": [], "refs": None, "final": False, "emitted": ""}
                tracked[m["id"]] = t
            t["parts"] = m["content"]["parts"]
            if m.get("status") and m["status"] != "in_progress":
                t["final"] = True
            if m.get("end_turn") is True:
                t["final"] = True
            state["last_id"] = m["id"]
            yield from emit_text(t)

        def handle_data(v: dict):
            if v.get("error"):
                yield {"error": v["error"]}
                return
            if v.get("type") == "server_ste_metadata":
                md = v.get("metadata") or {}
                yield {"served": {"experience": md.get("product_experience") or md.get("requested_model_experience"),
                                  "slug": md.get("model_slug"), "tool": md.get("tool_name")}}
                return
            if v.get("message"):
                yield from handle_message(v["message"])
                return
            vv = v.get("v")
            if isinstance(vv, dict) and vv.get("message"):
                yield from handle_message(vv["message"])
                return
            ops = vv if (v.get("o") == "patch" and isinstance(vv, list)) else ([v] if vv is not None else [])
            for op in ops:
                if not isinstance(op, dict):
                    continue
                path = op.get("p") if isinstance(op.get("p"), str) else "/message/content/parts/0"
                base_m = meta.get(state["last_id"])
                if not base_m:
                    continue
                if re.fullmatch(r"/message/content/parts/\d+", path) and isinstance(op.get("v"), str):
                    idx = int(path.rsplit("/", 1)[1])
                    parts = list((base_m.get("content") or {}).get("parts") or [])
                    while len(parts) <= idx:
                        parts.append("")
                    parts[idx] = op["v"] if op.get("o") == "replace" else (parts[idx] if isinstance(parts[idx], str) else "") + op["v"]
                    base_m["content"] = {**(base_m.get("content") or {}), "content_type": (base_m.get("content") or {}).get("content_type") or "text", "parts": parts}
                    yield from handle_message(base_m)
                elif path == "/message/status" and isinstance(op.get("v"), str):
                    base_m["status"] = op["v"]
                elif path == "/message/metadata" and isinstance(op.get("v"), dict):
                    base_m["metadata"] = {**(base_m.get("metadata") or {}), **op["v"]}
                    yield from handle_message(base_m)
                elif path == "/message/end_turn":
                    base_m["end_turn"] = op.get("v")

        async for frame in iter_json(resp):
            for ev in handle_data(frame):
                yield ev

    async def list_models(self) -> list[ModelInfo]:
        base, signed = await auth.prepare(self.config)
        url = join_url(base, "/backend-api/models?history_and_training_disabled=false")
        async with make_client(signed | {"accept": "application/json"}, self._transport) as client:
            try:
                resp = await client.get(url)
            except NETWORK_ERRORS as exc:
                raise ProviderError(network_error(exc, url)["message"]) from exc
        if resp.status_code >= 300:
            raise ProviderError(error_message(decode_body(resp.content), resp.status_code), resp.status_code, decode_body(resp.content)[:2000])
        out = [m for m in (chatgpt_chat_model(item) for item in (resp.json() or {}).get("models") or []) if m]
        if not out:
            raise ProviderError("ChatGPT listed no models for this account")
        return out


class _AuthExpired(Exception):
    pass


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_PART_CHARS:
        return [text]
    return [text[i:i + MAX_PART_CHARS] for i in range(0, len(text), MAX_PART_CHARS)]


def _estimate(text: str) -> int:
    return max(0, round(len(text) / 4))


def chatgpt_chat_model(item: dict) -> ModelInfo | None:
    """One entry of GET /backend-api/models → an AFH model, or None to hide it.

    The account's list is noisy: the real named family (GPT-6 Astra, GPT-6.1 Sol, GPT-5.6 Terra…)
    only appears as work-mode entries, while the non-work slugs are generic duplicates (gpt-6,
    gpt-6-instant, …-mini, …-thinking, research, hidden alpha gates). We surface exactly the named
    family. These real models are only reachable through the work-mode conversation (the ``-wm`` slug
    with ``conversation_origin: "tpp"``); the bare slug silently falls back to a generic gpt-6/gpt-5-6
    (the "echo trap"). So we keep the ``-wm`` slug and the provider sends tpp — the reply is the actual
    model, drawn from the plan's ChatGPT allowance (not Codex credits)."""
    if not isinstance(item, dict) or not item.get("slug"):
        return None
    slug = str(item["slug"])
    tags = item.get("tags") or []
    if "hidden" in tags:
        return None
    if not (bool(item.get("is_work_mode_model")) or slug.endswith("-wm")):
        return None  # the non-work slugs are duplicate generic gpt-6/gpt-5-6 rows — skip the clutter
    efforts = [str((e or {}).get("thinking_effort", e)) for e in (item.get("thinking_efforts") or []) if e]
    efforts = [e for e in efforts if e and e != "None"]
    title = item.get("title") or catalog.pretty_name(slug)
    return ModelInfo(id=slug, name=title, context=int(item.get("max_tokens") or 200_000), output=32_000,
                     tools=True, reasoning=bool(efforts), variants=efforts, input=["text", "image"])
