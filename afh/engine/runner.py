"""The agent loop: stream the model, run its tool calls, repeat until it answers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from . import diagnostics as diagmod
from . import hooks as hookmod
from .types import BudgetExceeded, ChatMessage, ChatRequest, PermissionDenied, ToolCall, ToolContext, ToolResult, event, new_id, now_ms

if TYPE_CHECKING:
    from .core import Engine

log = logging.getLogger("afh.runner")

MAX_STEPS = 200
RETRYABLE = {429, 500, 502, 503, 504}
# Tools that only read (or wait on other agents) run at the same time when one reply calls several.
PARALLEL_SAFE = {"read", "glob", "grep", "list", "webfetch", "websearch", "subagent", "skill", "jobs"}
PRUNE_AT = 0.55  # share of the context window: above it, old tool outputs are shortened
PRUNE_TO = 0.40
PRUNE_KEEP = 8  # the newest tool results are never shortened
PRUNE_HEAD = 600


def estimate_tokens(messages: list[ChatMessage], system: str = "") -> int:
    chars = len(system)
    images = 0
    for m in messages:
        chars += len(m.text) + len(m.reasoning)
        for c in m.tool_calls:
            chars += len(c.name) + len(json.dumps(c.input, ensure_ascii=False))
        images += len(m.images)
    return int(chars / 3.6) + images * 1200


def prune_history(messages: list[ChatMessage], context: int, system: str = "") -> int:
    """Shorten old tool outputs in place when the prompt gets big. Stored messages are untouched:
    only what is sent changes, and it is cut down to PRUNE_TO so the cache prefix stays stable for a while."""
    est = estimate_tokens(messages, system)
    if est < context * PRUNE_AT:
        return 0
    tool_idx = [i for i, m in enumerate(messages) if m.role == "tool"]
    candidates = tool_idx[:-PRUNE_KEEP] if len(tool_idx) > PRUNE_KEEP else []
    trimmed = 0
    for i in candidates:
        m = messages[i]
        if len(m.text) <= PRUNE_HEAD * 2:
            continue
        saved = len(m.text) - PRUNE_HEAD
        m.text = m.text[:PRUNE_HEAD] + f"\n… [{saved:,} characters of this old output were removed to save context; run the tool again if you need it]"
        est -= int(saved / 3.6)
        trimmed += 1
        if est <= context * PRUNE_TO:
            break
    return trimmed


def fit_history(messages: list[ChatMessage], context: int, system: str = "") -> int:
    """Last resort when even a compacted, pruned history is too big: leave the oldest messages out of
    the request (never out of the thread) and tell the model so. Returns how many were left out."""
    limit = int(context * 0.9)
    if estimate_tokens(messages, system) <= limit or len(messages) < 3:
        return 0
    dropped = 0
    while len(messages) > 2 and estimate_tokens(messages, system) > limit:
        messages.pop(0)
        dropped += 1
    while messages and messages[0].role == "tool":  # a result without its call is invalid
        messages.pop(0)
        dropped += 1
    messages.insert(0, ChatMessage("user", f"[{dropped} earlier messages of this conversation are not shown: it is longer than this model's context window. Ask the user if you need something from them.]"))
    return dropped


def close_interrupted(msg: dict) -> bool:
    """Mark a stored assistant message that was cut off (app quit, crash, update) as interrupted.
    True when it was unfinished: still streaming, or a tool call still pending or running."""
    if msg.get("type") != "assistant":
        return False
    open_tools = [p for p in msg.get("content", []) if p.get("type") == "tool" and p.get("state", {}).get("status") in ("streaming", "pending", "running")]
    if msg.get("time", {}).get("completed") and not open_tools:
        return False
    for p in open_tools:
        p["state"] = {"status": "error", "input": p["state"].get("input") if isinstance(p["state"].get("input"), dict) else {},
                      "error": {"type": "aborted", "message": "Interrupted: AFH was closed or restarted"}, "content": []}
    if not msg.get("time", {}).get("completed"):
        msg["error"] = {"type": "aborted", "message": "Step interrupted: AFH was closed or restarted"}
        msg["finish"] = "error"
        msg.setdefault("time", {})["completed"] = now_ms()
    return True


def _norm(path: str) -> str:
    return os.path.normcase(path).replace("\\", "/")


class AccountSwitch(Exception):
    """The step was refused for this account's limit; run it again on another account."""


class Interrupted(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, ev: dict):
        super().__init__(ev.get("message", "provider error"))
        self.ev = ev

    def to_dict(self) -> dict:
        e = self.ev
        return {"type": e.get("kind") or "ProviderError", "message": e.get("message", ""), "status": e.get("status"), "response": e.get("response")}


def live_start(messages: list[dict]) -> int:
    """Index of the latest compaction: the model sees it and what follows. Everything before stays in
    the thread for the user to read; the compaction summary stands in for it."""
    return max((i for i, m in enumerate(messages) if m.get("type") == "compaction"), default=0)


def to_chat(messages: list[dict], vision: bool = False) -> list[ChatMessage]:
    """Stored messages → provider-neutral chat history (tool results follow their call).

    With `vision`, the newest tool screenshots (browser) follow their results as an image message;
    older ones are left out so a long browsing session doesn't fill the context with pictures."""
    out: list[ChatMessage] = []
    live = messages[live_start(messages):]
    recent_shots: set[str] = set()
    if vision:
        ids = [p["id"] for m in live if m.get("type") == "assistant" for p in m.get("content", [])
               if p.get("type") == "tool" and any(c.get("type") == "image" for c in p.get("state", {}).get("content", []))]
        recent_shots = set(ids[-2:])
    for m in live:
        t = m.get("type")
        if t == "user":
            out.append(ChatMessage("user", m.get("text", ""), images=[f.get("uri", "") for f in m.get("files", []) if str(f.get("uri", "")).startswith("data:")]))
        elif t in ("synthetic", "system"):
            if m.get("text"):
                out.append(ChatMessage("user", m["text"]))
        elif t == "shell":
            out.append(ChatMessage("user", f"I ran this in the project folder:\n$ {m.get('command', '')}\n{m.get('output', '')}"))
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
            shots = [c["uri"] for p in m.get("content", []) if p.get("type") == "tool" and p["id"] in recent_shots
                     for c in p.get("state", {}).get("content", []) if c.get("type") == "image" and c.get("uri")]
            if shots:
                out.append(ChatMessage("user", "(Screenshot from the browser tool above.)", images=shots))
    return out


class Run:
    def __init__(self, engine: "Engine", session: dict):
        self.engine = engine
        self.session = session
        self.sid = session["id"]
        self.abort = asyncio.Event()
        self.queued: list[dict] = []  # follow-up prompts sent while running
        self.task: asyncio.Task | None = None
        self.stop_rounds = 0  # stop hooks that sent the agent back to work
        self.todo_nudged = False
        self.work_steps = 0  # steps that ran tools other than todo/goal
        self.goal_nudge_at: int | None = None  # work_steps when autopilot last sent the agent back
        self.step_files: list[tuple[str, str]] = []  # (tool call id, absolute path) changed in this step
        self.msg: dict | None = None  # the step being answered, as streamed so far

    def stop(self) -> None:
        """Stop now: whatever the run is waiting on (the model, a command, a retry pause) is cancelled."""
        self.abort.set()
        if self.task and not self.task.done():
            self.task.get_loop().call_soon_threadsafe(self.task.cancel)

    def ended(self, task: asyncio.Task) -> None:
        # Cancelled before run() got going, so its own cleanup never ran.
        if task.cancelled() and self.engine.runs.get(self.sid) is self:
            self.engine.runs.pop(self.sid, None)
            self.engine.store.touch(self.sid, idle=True)
            self.emit("session.execution.interrupted")

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
            max_steps = int((e.settings().get("agent") or {}).get("maxSteps") or MAX_STEPS)
            for step in range(max_steps):
                if self.abort.is_set():
                    raise Interrupted()
                e.check_budget(self.session)
                await e.maybe_compact(self.session, agent)  # also mid-run: long tool chains can outgrow the window
                model_ref = e.model_ref_for(self.session, agent)
                provider, model = e.resolve_model(model_ref)
                from . import accounts as accountsmod

                provider = await accountsmod.before_step(e, self, provider, model.id)  # another account when this one is near its limit
                msg = {"id": new_id("msg"), "type": "assistant", "agent": agent.id, "model": model_ref, "content": [], "time": {"created": now_ms()}}
                if provider.config.account_id and len(accountsmod.pool(provider.config.id)[1]) > 1:
                    msg["account"] = {"id": provider.config.account_id, "label": provider.config.account_label}
                store.add_message(self.sid, msg)
                self.msg = msg
                self.emit("session.step.started", assistantMessageID=msg["id"], agent=agent.id, model=model_ref, started=msg["time"]["created"])
                tools = e.tools_for(self.session, agent)
                system = e.system_prompt_for(self.session, agent)
                history = to_chat(store.list_messages(self.sid)[:-1], vision="image" in (model.input or []))
                pruned = prune_history(history, model.context, system)
                if pruned:
                    msg["pruned"] = pruned
                left_out = fit_history(history, model.context, system)
                if left_out:
                    msg["leftOut"] = left_out
                req = ChatRequest(model=model.id, system=system, messages=history,
                                  tools=[t.spec for t in tools] if model.tools else [], variant=model_ref.get("variant") or None, max_tokens=min(model.output, 32_000),
                                  reasoning=model.reasoning)
                try:
                    tool_calls = await self._stream_step(provider, req, msg, model, model_ref)
                except AccountSwitch:
                    continue  # the same step again; before_step picks the next account
                if self.abort.is_set():
                    raise Interrupted()
                if not tool_calls:
                    if self.queued:
                        self.queued.clear()
                        continue  # a follow-up arrived while answering: go around once more
                    nudge = await e.on_agent_stop(self)
                    if nudge and not self.abort.is_set():
                        note = {"id": new_id("msg"), "type": "synthetic", "text": nudge["text"], "time": {"created": now_ms()},
                                "metadata": {"notice": nudge["kind"], "label": nudge.get("label", "")}}
                        store.add_message(self.sid, note)
                        self.emit("session.notice", kind=nudge["kind"], label=nudge.get("label", ""), message=note)
                        continue
                    break
                self.step_files = []
                if any(c.name not in ("todo", "goal") for c in tool_calls):
                    self.work_steps += 1
                await self._run_tools(tool_calls, msg, tools, gate, agent)
                await self._diagnose(msg)
                store.save_message(self.sid, msg)
                if self.queued:
                    self.queued.clear()
            else:
                self.emit("session.notice", kind="limit", label=f"Stopped after {max_steps} steps (the per-run limit) — send a message to continue")
            self.emit("session.execution.succeeded")
        except (Interrupted, asyncio.CancelledError) as err:
            if isinstance(err, asyncio.CancelledError):
                if not self.abort.is_set():
                    raise  # cancelled from outside: AFH is shutting down
                asyncio.current_task().uncancel()
            self._mark_interrupted()
            self.emit("session.execution.interrupted")
        except ProviderError as err:
            failed = True
            self.emit("session.execution.failed", error=err.to_dict())
        except BudgetExceeded as err:
            failed = True
            self.emit("session.execution.failed", error={"type": "Spending limit reached", "message": str(err)})
        except Exception as err:  # a bug in the engine: surface it, don't hang the thread
            failed = True
            log.exception("run failed")
            self.emit("session.execution.failed", error={"type": type(err).__name__, "message": str(err)})
        finally:
            store.touch(self.sid, idle=True)
            e.runs.pop(self.sid, None)
            if getattr(e, "_computer", None):
                e._computer.clear(self.sid)  # hide the computer-use overlay the moment the run ends
            for req in [r for r in e.pending.values() if r.session_id == self.sid]:
                req.reply("reject", "The run ended")
        if not failed:
            await e.after_run(self.session)

    async def _stream_step(self, provider, req: ChatRequest, msg: dict, model, model_ref: dict | None = None) -> list[ToolCall]:
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
                        tokens = {"input": ev.get("input", 0), "output": ev.get("output", 0), "reasoning": ev.get("reasoning", 0),
                                  "cache": {"read": ev.get("cache_read", 0), "write": ev.get("cache_write", 0)}}
                    elif t == "served":
                        # which model the backend actually served (ChatGPT web lane): proof of the real model
                        msg["served"] = {"slug": ev.get("slug"), "experience": ev.get("experience")}
                        self.emit("session.served", assistantMessageID=msg["id"], slug=ev.get("slug"), experience=ev.get("experience"))
                    elif t == "finish":
                        finish = ev.get("reason", "stop")
                    elif t == "error":
                        raise ProviderError(ev)
                break
            except ProviderError as err:
                status = err.ev.get("status")
                from . import accounts as accountsmod

                if not self.abort.is_set() and accountsmod.on_refusal(provider, err.ev):
                    # This account is used up and another one can take over: drop the attempt (it
                    # has nothing the model said) and run the step again on the next account.
                    msg["content"] = []
                    msg["finish"] = "switched"
                    msg["time"]["completed"] = now_ms()
                    store.save_message(self.sid, msg)
                    self.emit("session.step.ended", assistantMessageID=msg["id"], finish="switched", tokens=None, cost=None)
                    raise AccountSwitch() from err
                retryable = err.ev.get("kind") == "network" or status in RETRYABLE
                if retryable and attempt < 4 and not self.abort.is_set():
                    delay = min(8, 2 ** attempt)
                    # Kept on the message, so the note stays where it happened (above the retried reply).
                    msg.setdefault("retries", []).append({"attempt": attempt, "error": err.to_dict(), "time": now_ms()})
                    msg["content"] = []
                    store.save_message(self.sid, msg)
                    self.emit("session.retry.scheduled", assistantMessageID=msg["id"], attempt=attempt, error=err.to_dict(), delay=delay)
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
        cost = None
        try:
            from .pricing import cost_of

            cost = cost_of(tokens, self.engine.price_for(model_ref))
        except Exception as err:  # pricing must never break a run
            log.info("cost: %s", err)
        if cost is not None:
            msg["cost"] = cost
        store.save_message(self.sid, msg)
        self.engine.add_usage(self.sid, tokens, cost)
        self.emit("session.step.ended", assistantMessageID=msg["id"], finish=msg["finish"], tokens=tokens, cost=cost)
        s = self.engine.store.get_session(self.sid) or {}
        self.emit("session.usage.updated", tokens=s.get("tokens"), cost=s.get("cost", 0))
        return tool_calls

    def _close(self, part: dict, msg: dict) -> None:
        part["_closed"] = True
        if part["type"] == "reasoning":
            part.setdefault("time", {})["completed"] = now_ms()
            self.emit("session.reasoning.ended", assistantMessageID=msg["id"], ordinal=part["ordinal"], text=part["text"])
        else:
            self.emit("session.text.ended", assistantMessageID=msg["id"], ordinal=part["ordinal"], text=part["text"])

    async def _run_tools(self, calls: list[ToolCall], msg: dict, tools, gate, agent) -> None:
        """Run a reply's tool calls in order; consecutive read-only calls (and delegations) run together."""
        i = 0
        while i < len(calls):
            if self.abort.is_set():
                raise Interrupted()
            group = [calls[i]]
            if calls[i].name in PARALLEL_SAFE:
                while i + len(group) < len(calls) and calls[i + len(group)].name in PARALLEL_SAFE:
                    group.append(calls[i + len(group)])
            if len(group) == 1:
                await self._run_tool(group[0], msg, tools, gate, agent)
            else:
                results = await asyncio.gather(*(self._run_tool(c, msg, tools, gate, agent) for c in group), return_exceptions=True)
                for r in results:
                    if isinstance(r, asyncio.CancelledError):
                        raise r
                    if isinstance(r, BaseException):
                        log.error("parallel tool failed: %r", r)
            i += len(group)

    async def _run_tool(self, call: ToolCall, msg: dict, tools, gate, agent) -> None:
        part = next((p for p in msg["content"] if p.get("type") == "tool" and p["id"] == call.id), None)
        if part is None:
            return
        part["state"] = {"status": "running", "input": call.input, "metadata": {}}
        self.emit("session.tool.called", assistantMessageID=msg["id"], id=call.id, input=call.input, executed=False)
        tool = next((t for t in tools if t.spec.name == call.name), None)
        started = time.time()
        settings = self.engine.settings()
        directory = self.session["location"]["directory"]
        hook_runs: list[dict] = []
        if tool is None:
            result = ToolResult(text=f"Unknown tool '{call.name}'. Available tools: {', '.join(t.spec.name for t in tools)}", is_error=True)
        elif "_raw" in call.input:
            result = ToolResult(text="The tool arguments were not valid JSON. Try again with well-formed arguments.", is_error=True)
        else:
            blocked = None
            pre = hookmod.hooks_for(settings, "pre_tool", call.name)
            if pre:
                payload = {"event": "pre_tool", "tool": call.name, "input": call.input, "files": hookmod.files_of(call.input), "sessionID": self.sid, "project": directory}
                runs = await hookmod.run_all(pre, payload, directory, settings.get("shell"))
                hook_runs += [{**r, "event": "pre_tool"} for r in runs]
                blocked = next((r for r in runs if r["code"] == hookmod.BLOCK_CODE), None)
            if blocked:
                result = ToolResult(text=f"Blocked by the user's hook '{blocked['name']}': {blocked['output'] or 'no reason given'}", is_error=True, metadata={"blockedBy": blocked["name"]})
            else:
                ctx = ToolContext(session_id=self.sid, message_id=msg["id"], directory=directory, permissions=gate,
                                  snapshots=self.engine.snapshots_for(self.sid, msg["id"]), emit=lambda t, d: self.emit(t, assistantMessageID=msg["id"], id=call.id, **d),
                                  settings=settings, read_only=self.engine.is_read_only(self.session, agent), jobs=self.engine.jobs, engine=self.engine)
                try:
                    result = await tool.run(ctx, call.input)
                except PermissionDenied as err:
                    result = ToolResult(text=f"The user did not allow this action. {err.message}".strip(), is_error=True, metadata={"rejected": True})
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    log.exception("tool %s failed", call.name)
                    result = ToolResult(text=f"{type(err).__name__}: {err}", is_error=True)
                if not result.is_error:
                    changed = [self._abs(f.file, directory) for f in result.files if f.status != "deleted"]
                    self.step_files += [(call.id, p) for p in changed]
                    post = hookmod.hooks_for(settings, "post_tool", call.name)
                    if post:
                        payload = {"event": "post_tool", "tool": call.name, "input": call.input, "files": hookmod.files_of(call.input, changed), "sessionID": self.sid,
                                   "project": directory, "output": result.text[:20_000]}
                        runs = await hookmod.run_all(post, payload, directory, settings.get("shell"))
                        hook_runs += [{**r, "event": "post_tool"} for r in runs]
                        notes = [f"[Hook '{r['name']}' exited {r['code']}]\n{r['output']}".rstrip() if r["code"] != 0 else f"[Hook '{r['name']}']\n{r['output']}"
                                 for r in runs if r["output"] or r["code"] != 0]
                        if notes:
                            result.text = result.text + "\n\n" + "\n\n".join(notes)
        meta = dict(result.metadata)
        if hook_runs:
            meta["hooks"] = [{k: r[k] for k in ("name", "event", "code", "output", "ms")} for r in hook_runs]
        if result.files:
            meta["files"] = [f.to_dict() for f in result.files]
        meta["duration_ms"] = int((time.time() - started) * 1000)
        content = [{"type": "text", "text": result.text}] + [{"type": "image", "uri": u} for u in result.images]
        if result.is_error:
            part["state"] = {"status": "error", "input": call.input, "error": {"type": "ToolError", "message": result.text[:500]}, "content": content, "metadata": meta}
            self.emit("session.tool.failed", assistantMessageID=msg["id"], id=call.id, error=part["state"]["error"], content=content, metadata=meta, executed=True)
        else:
            part["state"] = {"status": "completed", "input": call.input, "content": content, "metadata": meta}
            self.emit("session.tool.success", assistantMessageID=msg["id"], id=call.id, content=content, metadata=meta, executed=True)
        self.engine.store.save_message(self.sid, msg)

    @staticmethod
    def _abs(file: str, directory: str) -> str:
        return file if os.path.isabs(file) else os.path.normpath(os.path.join(directory, file))

    async def _diagnose(self, msg: dict) -> None:
        """After a step that changed files: check them and append any problems to the last edit's result."""
        if not self.step_files or self.abort.is_set():
            return
        settings = self.engine.settings()
        directory = self.session["location"]["directory"]
        paths = list(dict.fromkeys(p for _, p in self.step_files))
        try:
            results = await diagmod.check_files(paths, directory, settings)
        except Exception as err:
            log.warning("diagnostics failed: %s", err)
            return
        if not results:
            return
        parts = {p["id"]: p for p in msg["content"] if p.get("type") == "tool" and p.get("state", {}).get("status") == "completed"}
        last_id = next((cid for cid, _ in reversed(self.step_files) if cid in parts), None)
        if last_id is None:
            return
        # Each edit card shows the checks of its own files; the model gets one report, on the last edit.
        for cid in dict.fromkeys(cid for cid, _ in self.step_files):
            part = parts.get(cid)
            if part is None:
                continue
            mine = {_norm(diagmod._rel(p, directory)) for c, p in self.step_files if c == cid}
            own = [r for r in results if any(_norm(f) in mine for f in r["files"])]
            st = part["state"]
            if own:
                st.setdefault("metadata", {})["diagnostics"] = diagmod.summary(own)
            if cid == last_id and st.get("content"):
                st["content"][0]["text"] = st["content"][0]["text"] + diagmod.report(results)
            if own or cid == last_id:
                self.emit("session.tool.success", assistantMessageID=msg["id"], id=cid, content=st["content"], metadata=st.get("metadata", {}), executed=True)
        self.engine.store.save_message(self.sid, msg)

    def _mark_interrupted(self) -> None:
        m = self.msg  # the step in hand, with what was written before the stop
        if m is None:
            return
        for p in m.get("content", []):
            p.pop("_closed", None)
            if p.get("type") == "tool" and p.get("state", {}).get("status") in ("streaming", "pending", "running"):
                p["state"] = {"status": "error", "input": p["state"].get("input") or {}, "error": {"type": "aborted", "message": "Interrupted"}, "content": []}
                self.emit("session.tool.failed", assistantMessageID=m["id"], id=p["id"], error=p["state"]["error"], content=[], metadata={}, executed=False)
        if not m.get("time", {}).get("completed"):
            m["error"] = {"type": "aborted", "message": "Step interrupted"}
            m["finish"] = "error"
            m["time"]["completed"] = now_ms()
        self.engine.store.save_message(self.sid, m)
