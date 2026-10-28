"""The agent loop: stream the model, run its tool calls, repeat until it answers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from .types import ChatMessage, ChatRequest, PermissionDenied, ToolCall, ToolContext, ToolResult, event, new_id, now_ms

if TYPE_CHECKING:
    from .core import Engine

log = logging.getLogger("afh.runner")

MAX_STEPS = 100
RETRYABLE = {429, 500, 502, 503, 504}


class Interrupted(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, ev: dict):
        super().__init__(ev.get("message", "provider error"))
        self.ev = ev

    def to_dict(self) -> dict:
        e = self.ev
        return {"type": e.get("kind") or "ProviderError", "message": e.get("message", ""), "status": e.get("status"), "response": e.get("response")}


def to_chat(messages: list[dict]) -> list[ChatMessage]:
    """Stored messages → provider-neutral chat history (tool results follow their call)."""
    out: list[ChatMessage] = []
    for m in messages:
        t = m.get("type")
        if t == "user":
            out.append(ChatMessage("user", m.get("text", ""), images=[f.get("uri", "") for f in m.get("files", []) if str(f.get("uri", "")).startswith("data:")]))
        elif t in ("synthetic", "system"):
            if m.get("text"):
                out.append(ChatMessage("user", m["text"]))
        elif t == "compaction":
            out.append(ChatMessage("user", "Summary of the conversation so far (earlier messages were compacted):\n\n" + m.get("text", "")))
            out.append(ChatMessage("assistant", "Understood — I'll continue from that summary."))
        elif t == "assistant":
            text = "\n\n".join(p.get("text", "") for p in m.get("content", []) if p.get("type") == "text" and p.get("text"))
            reasoning = "\n".join(p.get("text", "") for p in m.get("content", []) if p.get("type") == "reasoning" and p.get("text"))
            calls = [ToolCall(p["id"], p["name"], p.get("state", {}).get("input") if isinstance(p.get("state", {}).get("input"), dict) else {})
                     for p in m.get("content", []) if p.get("type") == "tool"]
            if not text and not calls:
                continue
            out.append(ChatMessage("assistant", text, reasoning=reasoning, tool_calls=calls))
            for p in m.get("content", []):
                if p.get("type") != "tool":
                    continue
                st = p.get("state", {})
                body = "\n".join(c.get("text", "") for c in st.get("content", []) if c.get("type") == "text")
                if st.get("status") == "error" and st.get("error"):
                    body = f"Error: {st['error'].get('message', '')}\n{body}".strip()
                out.append(ChatMessage("tool", body or "(no output)", tool_call_id=p["id"], tool_name=p["name"]))
    return out


class Run:
    def __init__(self, engine: "Engine", session: dict):
        self.engine = engine
        self.session = session
        self.sid = session["id"]
        self.abort = asyncio.Event()
        self.queued: list[dict] = []  # follow-up prompts sent while running
        self.task: asyncio.Task | None = None

    def emit(self, type_: str, **data: Any) -> None:
        self.engine.publish(event(type_, self.sid, **data))

    # ---- main loop ---------------------------------------------------------------------

    async def run(self) -> None:
        e = self.engine
        store = e.store
        self.emit("session.execution.started")
        store.touch(self.sid)
        failed = False
        try:
            agent = e.agent_for(self.session)
            gate = e.gate_for(self.session, agent)
            await e.maybe_compact(self.session, agent)
            for step in range(MAX_STEPS):
                if self.abort.is_set():
                    raise Interrupted()
                model_ref = e.model_ref_for(self.session, agent)
                provider, model = e.resolve_model(model_ref)
                msg = {"id": new_id("msg"), "type": "assistant", "agent": agent.id, "model": model_ref, "content": [], "time": {"created": now_ms()}}
                store.add_message(self.sid, msg)
                self.emit("session.step.started", assistantMessageID=msg["id"], agent=agent.id, model=model_ref, started=msg["time"]["created"])
                tools = e.tools_for(self.session, agent)
                req = ChatRequest(model=model.id, system=e.system_prompt_for(self.session, agent), messages=to_chat(store.list_messages(self.sid)[:-1]),
                                  tools=[t.spec for t in tools] if model.tools else [], variant=model_ref.get("variant") or None, max_tokens=min(model.output, 32_000),
                                  reasoning=model.reasoning)
                tool_calls = await self._stream_step(provider, req, msg, model)
                if self.abort.is_set():
                    raise Interrupted()
                if not tool_calls:
                    if self.queued:
                        continue  # a follow-up arrived while answering: go around once more
                    break
                for call in tool_calls:
                    if self.abort.is_set():
                        raise Interrupted()
                    await self._run_tool(call, msg, tools, gate, agent)
                store.save_message(self.sid, msg)
                if self.queued:
                    self.queued.clear()
            self.emit("session.execution.succeeded")
        except Interrupted:
            self._mark_interrupted()
            self.emit("session.execution.interrupted")
        except ProviderError as err:
            failed = True
            self.emit("session.execution.failed", error=err.to_dict())
        except Exception as err:  # a bug in the engine: surface it, don't hang the thread
            failed = True
            log.exception("run failed")
            self.emit("session.execution.failed", error={"type": type(err).__name__, "message": str(err)})
        finally:
            store.touch(self.sid, idle=True)
            e.runs.pop(self.sid, None)
            for req in [r for r in e.pending.values() if r.session_id == self.sid]:
                req.reply("reject", "The run ended")
        if not failed:
            await e.after_run(self.session)

    async def _stream_step(self, provider, req: ChatRequest, msg: dict, model) -> list[ToolCall]:
        """One model call with retries. Fills msg.content in place and persists it. Returns tool calls to run."""
        store = self.engine.store
        attempt = 0
        while True:
            attempt += 1
            parts_by_tool: dict[str, dict] = {}
            text_part = reasoning_part = None
            tokens = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
            finish = "stop"
            tool_calls: list[ToolCall] = []
            ordinal = {"text": 0, "reasoning": 0}
            msg["content"] = []
            first = True
            try:
                async for ev in provider.stream(req):
                    if self.abort.is_set():
                        raise Interrupted()
                    t = ev["type"]
                    if first and t != "error":
                        first = False
                        msg["time"]["streamed"] = now_ms()
                    if t == "text.delta":
                        if text_part is None or text_part.get("_closed"):
                            if text_part is not None:
                                ordinal["text"] += 1
                            text_part = {"type": "text", "text": "", "ordinal": ordinal["text"]}
                            msg["content"].append(text_part)
                            self.emit("session.text.started", assistantMessageID=msg["id"], ordinal=ordinal["text"])
                        if reasoning_part and not reasoning_part.get("_closed"):
                            self._close(reasoning_part, msg)
                        text_part["text"] += ev["text"]
                        self.emit("session.text.delta", assistantMessageID=msg["id"], ordinal=text_part["ordinal"], delta=ev["text"])
                    elif t == "reasoning.delta":
                        if reasoning_part is None or reasoning_part.get("_closed"):
                            if reasoning_part is not None:
                                ordinal["reasoning"] += 1
                            reasoning_part = {"type": "reasoning", "text": "", "ordinal": ordinal["reasoning"], "time": {"created": now_ms()}}
                            msg["content"].append(reasoning_part)
                            self.emit("session.reasoning.started", assistantMessageID=msg["id"], ordinal=ordinal["reasoning"])
                        reasoning_part["text"] += ev["text"]
                        self.emit("session.reasoning.delta", assistantMessageID=msg["id"], ordinal=reasoning_part["ordinal"], delta=ev["text"])
                    elif t == "tool.start":
                        for p in (text_part, reasoning_part):
                            if p and not p.get("_closed"):
                                self._close(p, msg)
                        part = {"type": "tool", "id": ev["id"], "name": ev["name"], "state": {"status": "streaming", "input": ""}, "time": {"created": now_ms()}}
                        parts_by_tool[ev["id"]] = part
                        msg["content"].append(part)
                        self.emit("session.tool.input.started", assistantMessageID=msg["id"], id=ev["id"], name=ev["name"])
                    elif t == "tool.delta":
                        part = parts_by_tool.get(ev["id"])
                        if part is not None:
                            part["state"]["input"] += ev["text"]
                            self.emit("session.tool.input.delta", assistantMessageID=msg["id"], id=ev["id"], delta=ev["text"])
                    elif t == "tool.end":
                        part = parts_by_tool.get(ev["id"])
                        if part is None:
                            part = {"type": "tool", "id": ev["id"], "name": ev["name"], "state": {}, "time": {"created": now_ms()}}
                            parts_by_tool[ev["id"]] = part
                            msg["content"].append(part)
                            self.emit("session.tool.input.started", assistantMessageID=msg["id"], id=ev["id"], name=ev["name"])
                        raw = ev.get("raw") or (part["state"].get("input") if isinstance(part["state"].get("input"), str) else "")
                        inp = ev.get("input")
                        if inp is None:
                            try:
                                inp = json.loads(raw) if raw.strip() else {}
                            except json.JSONDecodeError:
                                inp = {"_raw": raw}
                        part["state"] = {"status": "pending", "input": inp}
                        self.emit("session.tool.input.ended", assistantMessageID=msg["id"], id=ev["id"], text=raw)
                        tool_calls.append(ToolCall(ev["id"], ev["name"], inp))
                    elif t == "usage":
                        tokens = {"input": ev.get("input", 0), "output": ev.get("output", 0), "reasoning": ev.get("reasoning", 0), "cache": {"read": ev.get("cache_read", 0), "write": 0}}
                    elif t == "finish":
                        finish = ev.get("reason", "stop")
                    elif t == "error":
                        raise ProviderError(ev)
                break
            except ProviderError as err:
                status = err.ev.get("status")
                retryable = err.ev.get("kind") == "network" or status in RETRYABLE
                if retryable and attempt < 4 and not self.abort.is_set():
                    delay = min(8, 2 ** attempt)
                    self.emit("session.retry.scheduled", attempt=attempt, error=err.to_dict(), delay=delay)
                    await asyncio.sleep(delay)
                    continue
                msg["error"] = err.to_dict()
                msg["finish"] = "error"
                msg["time"]["completed"] = now_ms()
                store.save_message(self.sid, msg)
                self.emit("session.step.failed", assistantMessageID=msg["id"], error=err.to_dict())
                raise
        for p in (text_part, reasoning_part):
            if p and not p.get("_closed"):
                self._close(p, msg)
        for p in msg["content"]:
            p.pop("_closed", None)
        msg["tokens"] = tokens
        msg["finish"] = "tool-calls" if tool_calls else finish
        msg["time"]["completed"] = now_ms()
        store.save_message(self.sid, msg)
        self.engine.add_usage(self.sid, tokens)
        self.emit("session.step.ended", assistantMessageID=msg["id"], finish=msg["finish"], tokens=tokens)
        self.emit("session.usage.updated", tokens=self.engine.store.get_session(self.sid)["tokens"])
        return tool_calls

    def _close(self, part: dict, msg: dict) -> None:
        part["_closed"] = True
        if part["type"] == "reasoning":
            part.setdefault("time", {})["completed"] = now_ms()
            self.emit("session.reasoning.ended", assistantMessageID=msg["id"], ordinal=part["ordinal"], text=part["text"])
        else:
            self.emit("session.text.ended", assistantMessageID=msg["id"], ordinal=part["ordinal"], text=part["text"])

    async def _run_tool(self, call: ToolCall, msg: dict, tools, gate, agent) -> None:
        part = next((p for p in msg["content"] if p.get("type") == "tool" and p["id"] == call.id), None)
        if part is None:
            return
        part["state"] = {"status": "running", "input": call.input, "metadata": {}}
        self.emit("session.tool.called", assistantMessageID=msg["id"], id=call.id, input=call.input, executed=False)
        tool = next((t for t in tools if t.spec.name == call.name), None)
        started = time.time()
        if tool is None:
            result = ToolResult(text=f"Unknown tool '{call.name}'. Available tools: {', '.join(t.spec.name for t in tools)}", is_error=True)
        elif "_raw" in call.input:
            result = ToolResult(text="The tool arguments were not valid JSON. Try again with well-formed arguments.", is_error=True)
        else:
            ctx = ToolContext(session_id=self.sid, message_id=msg["id"], directory=self.session["location"]["directory"], permissions=gate,
                              snapshots=self.engine.snapshots_for(self.sid, msg["id"]), emit=lambda t, d: self.emit(t, assistantMessageID=msg["id"], id=call.id, **d),
                              settings=self.engine.settings(), read_only=self.engine.is_read_only(self.session, agent))
            try:
                result = await tool.run(ctx, call.input)
            except PermissionDenied as err:
                result = ToolResult(text=f"The user did not allow this action. {err.message}".strip(), is_error=True, metadata={"rejected": True})
            except asyncio.CancelledError:
                raise
            except Exception as err:
                log.exception("tool %s failed", call.name)
                result = ToolResult(text=f"{type(err).__name__}: {err}", is_error=True)
        meta = dict(result.metadata)
        if result.files:
            meta["files"] = [f.to_dict() for f in result.files]
        meta["duration_ms"] = int((time.time() - started) * 1000)
        content = [{"type": "text", "text": result.text}]
        if result.is_error:
            part["state"] = {"status": "error", "input": call.input, "error": {"type": "ToolError", "message": result.text[:500]}, "content": content, "metadata": meta}
            self.emit("session.tool.failed", assistantMessageID=msg["id"], id=call.id, error=part["state"]["error"], content=content, metadata=meta, executed=True)
        else:
            part["state"] = {"status": "completed", "input": call.input, "content": content, "metadata": meta}
            self.emit("session.tool.success", assistantMessageID=msg["id"], id=call.id, content=content, metadata=meta, executed=True)
        self.engine.store.save_message(self.sid, msg)

    def _mark_interrupted(self) -> None:
        msgs = self.engine.store.list_messages(self.sid)
        if msgs and msgs[-1].get("type") == "assistant" and not msgs[-1].get("time", {}).get("completed"):
            m = msgs[-1]
            for p in m.get("content", []):
                if p.get("type") == "tool" and p.get("state", {}).get("status") in ("streaming", "pending", "running"):
                    p["state"] = {"status": "error", "input": p["state"].get("input") or {}, "error": {"type": "aborted", "message": "Interrupted"}, "content": []}
            m["error"] = {"type": "aborted", "message": "Step interrupted"}
            m["finish"] = "error"
            m["time"]["completed"] = now_ms()
            self.engine.store.save_message(self.sid, m)
