"""The engine facade the API talks to: providers and models, sessions, runs, permissions,
delegation, undo, compaction, MCP and skills. One instance per process."""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from .. import store as appstore
from . import agents as agentmod
from . import config as provcfg
from . import permissions as perm
from . import prompt as promptmod
from .runner import Run, to_chat
from .sessions import Store
from .types import ChatMessage, ChatRequest, FileDiff, ModelInfo, Provider, ToolContext, ToolResult, ToolSpec, event, new_id, now_ms

log = logging.getLogger("afh.engine")


class Engine:
    def __init__(self) -> None:
        self.store = Store(appstore.AFH_DIR / "afh.db")
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.pending: dict[str, perm.Request] = {}
        self.runs: dict[str, Run] = {}
        self.providers: dict[str, Provider] = {}
        self.models: dict[str, list[ModelInfo]] = {}
        self.mcp = None
        self.skills: list = []
        self.ready = threading.Event()
        self.error: str | None = None
        self.stashes: dict[str, dict] = {}  # staged undos per session

    # ---- lifecycle ---------------------------------------------------------------------

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        try:
            self.reload_providers()
            await self.start_mcp()
            self.error = None
        except Exception as err:
            log.exception("engine start")
            self.error = str(err)
        self.ready.set()
        self.publish(event("afh.ready"))

    async def restart(self) -> None:
        """Re-read providers, agents and MCP servers. Nothing to kill: it's all in-process."""
        self.publish(event("afh.restarting"))
        self.ready.clear()
        try:
            self.reload_providers()
            await self.start_mcp()
        finally:
            self.ready.set()
            self.publish(event("afh.ready"))
            self.publish(event("model.updated"))
            self.publish(event("agent.updated"))

    async def stop(self) -> None:
        for run in list(self.runs.values()):
            run.abort.set()
        if self.mcp:
            try:
                await self.mcp.stop()
            except Exception:
                pass

    def settings(self) -> dict:
        return appstore.load_settings()

    # ---- events ------------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self._subscribers.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers = [s for s in self._subscribers if s[1] is not q]

    def publish(self, ev: dict) -> None:
        """Thread-safe: each subscriber's queue is fed on the loop that created it."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        def put(q: asyncio.Queue) -> None:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

        for loop, q in list(self._subscribers):
            if loop is running:
                put(q)
            elif not loop.is_closed():
                loop.call_soon_threadsafe(put, q)

    # ---- providers & models -------------------------------------------------------------

    def reload_providers(self) -> None:
        from .providers.catalog import make_provider

        self.providers = {}
        for cfg in provcfg.provider_configs():
            try:
                self.providers[cfg.id] = make_provider(cfg)
                self.models[cfg.id] = list(cfg.models)
            except Exception as err:
                log.warning("provider %s skipped: %s", cfg.id, err)

    async def refresh_models(self, pid: str | None = None) -> None:
        for p_id, provider in self.providers.items():
            if pid and p_id != pid:
                continue
            if not provider.config.fetch_models:
                continue
            try:
                fetched = await provider.list_models()
            except Exception as err:
                log.info("models for %s not fetched: %s", p_id, err)
                continue
            provcfg.upsert(p_id, {"fetched": [m.to_dict() for m in fetched]})
        self.reload_providers()
        self.publish(event("model.updated"))

    def list_models(self, include_hidden: bool = False) -> list[dict]:
        out = []
        for pid, models in self.models.items():
            for m in models:
                if m.hidden and not include_hidden:
                    continue
                out.append({**m.to_dict(), "providerID": pid, "enabled": not m.hidden})
        return out

    def default_model(self) -> dict | None:
        s = self.settings()
        ref = s.get("defaultModel")
        if ref and self.find_model(ref):
            return {"id": ref["id"], "providerID": ref["providerID"]}
        for m in self.list_models():
            return {"id": m["id"], "providerID": m["providerID"]}
        return None

    def find_model(self, ref: dict | None) -> ModelInfo | None:
        if not ref:
            return None
        for m in self.models.get(ref.get("providerID", ""), []):
            if m.id == ref.get("id"):
                return m
        return None

    def resolve_model(self, ref: dict | None) -> tuple[Provider, ModelInfo]:
        ref = ref or self.default_model()
        if not ref:
            raise RuntimeError("No model is configured. Add a provider in Settings → Models & providers.")
        provider = self.providers.get(ref.get("providerID", ""))
        model = self.find_model(ref)
        if provider is None:
            raise RuntimeError(f"Provider '{ref.get('providerID')}' is not configured (Settings → Models & providers).")
        if model is None:  # unknown id: still try it, the provider decides
            model = ModelInfo(id=ref["id"], name=ref["id"])
        return provider, model

    # ---- agents, prompts, tools ------------------------------------------------------------

    def agent_for(self, session: dict) -> agentmod.AgentConfig:
        return agentmod.get_agent(session.get("agent"), self.settings())

    def model_ref_for(self, session: dict, agent: agentmod.AgentConfig) -> dict:
        ref = session.get("model") or agent.model or self.default_model()
        if not ref:
            raise RuntimeError("No model is configured. Add a provider in Settings → Models & providers.")
        return {"id": ref["id"], "providerID": ref["providerID"], **({"variant": ref["variant"]} if ref.get("variant") else {})}

    def system_prompt_for(self, session: dict, agent: agentmod.AgentConfig) -> str:
        from .skills import catalog_text

        directory = session["location"]["directory"]
        skills = self.skills_for(directory)
        return promptmod.build(agent_system=agent.system, directory=directory, skills_text=catalog_text(skills) if skills else "",
                               mcp_instructions=self.mcp.instructions() if self.mcp else "", settings=self.settings())

    def skills_for(self, directory: str) -> list:
        from .skills import discover

        try:
            return discover(directory, appstore.AFH_DIR)
        except Exception as err:
            log.warning("skills: %s", err)
            return []

    def tools_for(self, session: dict, agent: agentmod.AgentConfig) -> list:
        from .skills import SkillTool
        from .tools.registry import builtin_tools

        tools = list(builtin_tools(self.settings()))
        skills = self.skills_for(session["location"]["directory"])
        if skills:
            tools.append(SkillTool(skills))
        if self.mcp:
            tools.extend(self.mcp.tools())
        if agent.kind in ("leader", "builtin", "custom") and agentmod.delegate_ids(self.settings()):
            tools.append(SubagentTool(self))
        return tools

    def is_read_only(self, session: dict, agent: agentmod.AgentConfig) -> bool:
        rules = [*session.get("permissions", []), *agent.permissions]
        return perm.decide(rules, "edit", ["*"]) == "deny"

    def gate_for(self, session: dict, agent: agentmod.AgentConfig) -> perm.Gate:
        rules = [*session.get("permissions", []), *agent.permissions]
        if agent.kind == "leader":
            allowed = agentmod.delegate_ids(self.settings())
            rules += [{"action": "subagent", "resource": "*", "effect": "deny"}] + [{"action": "subagent", "resource": d, "effect": "allow"} for d in allowed]

        def changed(new_rules: list[dict]) -> None:
            session["permissions"] = [r for r in new_rules if r not in agent.permissions]
            self.store.update_session(session["id"], permissions=session["permissions"])
            self.publish(event("session.permissions", session["id"], permissions=session["permissions"]))

        return perm.Gate(session["id"], rules, self.publish, self.pending, changed)

    def snapshots_for(self, sid: str, mid: str):
        store = self.store

        class _Snap:
            def record(self, path: str) -> None:
                store.record_snapshot(sid, mid, str(Path(path)))

        return _Snap()

    # ---- MCP -------------------------------------------------------------------------------

    async def start_mcp(self) -> None:
        from .mcp import McpManager

        if self.mcp:
            try:
                await self.mcp.stop()
            except Exception:
                pass
        self.mcp = McpManager()
        servers = (self.settings().get("mcp") or {}).get("servers", [])
        try:
            await self.mcp.start([s for s in servers if isinstance(s, dict)])
        except Exception as err:
            log.warning("mcp: %s", err)
        self.publish(event("mcp.status.changed"))

    # ---- sessions ----------------------------------------------------------------------------

    def create_session(self, directory: str, *, title: str | None = None, agent: str | None = None, model: dict | None = None, mode: str | None = None,
                       parent_id: str | None = None, permissions: list | None = None) -> dict:
        mode = mode or self.settings().get("defaultMode", "ask")
        s = self.store.create_session(directory, title=title, agent=agent or self.settings().get("defaultAgent", "build"), model=model,
                                      permissions=permissions if permissions is not None else perm.rules_for_mode(mode), metadata={"afh": {"mode": mode}}, parent_id=parent_id)
        self.publish(event("session.created", s["id"], parentID=parent_id, title=title, agent=s["agent"], model=s["model"], location=s["location"]))
        return s

    def update_session(self, sid: str, **fields: Any) -> dict:
        if "mode" in fields:
            mode = fields.pop("mode")
            fields["permissions"] = perm.rules_for_mode(mode)
            s = self.store.get_session(sid) or {}
            fields["metadata"] = {**s.get("metadata", {}), "afh": {**s.get("metadata", {}).get("afh", {}), "mode": mode}}
        s = self.store.update_session(sid, **fields)
        if "title" in fields:
            self.publish(event("session.renamed", sid, title=fields["title"]))
        if "archived" in fields:
            self.publish(event("session.archived" if fields["archived"] else "session.unarchived", sid))
        return s

    def delete_session(self, sid: str) -> None:
        run = self.runs.get(sid)
        if run:
            run.abort.set()
        self.store.delete_session(sid)
        self.publish(event("session.deleted", sid))

    def fork_session(self, sid: str, before: str | None = None) -> dict:
        src = self.store.get_session(sid)
        if not src:
            raise KeyError(sid)
        msgs = self.store.list_messages(sid)
        if before:
            seq = self.store.message_seq(sid, before)
            msgs = [m for m in msgs if (self.store.message_seq(sid, m["id"]) or 0) < (seq or 10**9)]
        new = self.store.create_session(src["location"]["directory"], title=(src.get("title") or "Thread") + " (fork)", agent=src.get("agent"), model=src.get("model"),
                                        permissions=src.get("permissions"), metadata=src.get("metadata"))
        for m in msgs:
            copy_ = json.loads(json.dumps(m))
            copy_["id"] = new_id("msg")
            self.store.add_message(new["id"], copy_)
        self.publish(event("session.created", new["id"], title=new["title"]))
        return self.store.get_session(new["id"])

    # ---- prompting ------------------------------------------------------------------------------

    async def prompt(self, sid: str, text: str, files: list[dict] | None = None, *, agent: str | None = None, model: dict | None = None) -> dict:
        session = self.store.get_session(sid)
        if not session:
            raise KeyError(sid)
        fields: dict[str, Any] = {}
        if agent and agent != session.get("agent"):
            fields["agent"] = agent
        if model:
            fields["model"] = model
        if fields:
            session = self.store.update_session(sid, **fields)
        from .skills import discover, mentioned

        msg = {"id": new_id("msg"), "type": "user", "text": text, "time": {"created": now_ms()}}
        if files:
            msg["files"] = files
        self.store.add_message(sid, msg)
        self.publish(event("session.inbox.enqueued", sid, inboxID=msg["id"], item={"type": "user", "payload": {"text": text, "files": files or []}, "delivery": "steer"}))
        self.publish(event("session.inbox.delivered", sid, inboxID=msg["id"]))
        for sk in mentioned(text, discover(session["location"]["directory"], appstore.AFH_DIR)):
            self.store.add_message(sid, {"id": new_id("msg"), "type": "system", "text": f"Skill {sk.id} ({sk.name}):\n\n{sk.body}", "metadata": {"notice": "skill", "instructionSources": [sk.id]}, "time": {"created": now_ms()}})
        run = self.runs.get(sid)
        if run:
            run.queued.append(msg)
            return msg
        self.start_run(session)
        return msg

    def start_run(self, session: dict) -> Run:
        run = Run(self, session)
        self.runs[session["id"]] = run
        run.task = asyncio.create_task(run.run())
        return run

    def interrupt(self, sid: str) -> None:
        run = self.runs.get(sid)
        if run:
            run.abort.set()
            for req in [r for r in self.pending.values() if r.session_id == sid]:
                req.reply("reject", "Interrupted")

    def is_running(self, sid: str) -> bool:
        return sid in self.runs

    def add_usage(self, sid: str, tokens: dict) -> None:
        s = self.store.get_session(sid)
        if not s:
            return
        t = s.get("tokens") or {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        t["input"] += tokens.get("input", 0)
        t["output"] += tokens.get("output", 0)
        t["reasoning"] += tokens.get("reasoning", 0)
        t["cache"]["read"] += tokens.get("cache", {}).get("read", 0)
        self.store.update_session(sid, tokens=t)

    async def after_run(self, session: dict) -> None:
        s = self.store.get_session(session["id"])
        if s and not s.get("title") and not s.get("parentID"):
            asyncio.create_task(self.make_title(s))

    # ---- titles & compaction ----------------------------------------------------------------------

    async def _complete(self, model_ref: dict, system: str, text: str, max_tokens: int = 200) -> str:
        provider, model = self.resolve_model(model_ref)
        # Thinking models may spend the whole budget on reasoning, so give room and ask for a marker line.
        marker = "Put your final answer on a single line starting with ANSWER: ."
        req = ChatRequest(model=model.id, system=f"{system}\n\n{marker}", messages=[ChatMessage("user", text)],
                          max_tokens=max(max_tokens, 400) + 1200, reasoning=False, variant=None)
        out: list[str] = []
        async for ev in provider.stream(req):
            if ev["type"] == "text.delta":
                out.append(ev["text"])
            elif ev["type"] == "error":
                raise RuntimeError(ev.get("message"))
        text_out = "".join(out).strip()
        for line in reversed(text_out.splitlines()):
            if line.strip().upper().startswith("ANSWER:"):
                return line.split(":", 1)[1].strip()
        return text_out

    async def make_title(self, session: dict) -> None:
        msgs = self.store.list_messages(session["id"])
        first = next((m for m in msgs if m.get("type") == "user"), None)
        if not first:
            return
        try:
            agent = self.agent_for(session)
            title = await self._complete(self.model_ref_for(session, agent), "You name conversations. Reply with only a title of 3 to 6 words, plain text, no quotes, no trailing period.",
                                         f"Title this request:\n\n{first.get('text', '')[:1500]}", 40)
            title = title.splitlines()[0].strip().strip('"').strip("'").rstrip(".")[:80] if title else ""
        except Exception as err:
            log.info("title: %s", err)
            title = ""
        if not title:
            title = " ".join(first.get("text", "").split()[:6]) or "New thread"
        self.update_session(session["id"], title=title)

    async def maybe_compact(self, session: dict, agent: agentmod.AgentConfig) -> None:
        """When the last step used most of the window, summarise older messages."""
        msgs = self.store.list_messages(session["id"])
        last = next((m for m in reversed(msgs) if m.get("type") == "assistant" and m.get("tokens")), None)
        if not last:
            return
        try:
            _, model = self.resolve_model(self.model_ref_for(session, agent))
        except Exception:
            return
        used = last["tokens"].get("input", 0) + last["tokens"].get("cache", {}).get("read", 0)
        if used < model.context * 0.8 or len(msgs) < 8:
            return
        keep = msgs[-6:]
        old = msgs[:-6]
        transcript = "\n\n".join(f"[{m.get('type')}] " + (m.get("text") or "\n".join(p.get("text", "") for p in m.get("content", []) if p.get("type") == "text")) for m in old)[:120_000]
        try:
            summary = await self._complete(self.model_ref_for(session, agent), "Summarise this coding conversation for the assistant that will continue it: goals, decisions, files touched, what is done and what is left. Be precise and compact. Write the summary itself after the ANSWER: marker, all on following lines.", transcript, 1500)
        except Exception as err:
            log.info("compaction skipped: %s", err)
            return
        compaction = {"id": new_id("msg"), "type": "compaction", "text": summary, "time": {"created": now_ms()}}
        self.store.replace_messages(session["id"], [compaction, *keep])
        self.publish(event("session.compaction.ended", session["id"]))

    # ---- undo (revert) ------------------------------------------------------------------------------

    def revert_stage(self, sid: str, message_id: str, files: bool = True) -> dict:
        seq = self.store.message_seq(sid, message_id)
        if seq is None:
            raise KeyError(message_id)
        self.revert_clear(sid)
        removed = self.store.messages_from(sid, seq)
        restored: list[FileDiff] = []
        stash_files: list[dict] = []
        if files:
            latest: dict[str, dict] = {}
            for snap in self.store.snapshots_from(sid, seq):  # oldest first → the first one per path is the original
                latest.setdefault(snap["path"], snap)
            for path, snap in latest.items():
                p = Path(path)
                current = p.read_bytes() if p.is_file() else None
                stash_files.append({"path": path, "existed": current is not None, "content": current})
                if snap["existed"]:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(snap["content"] or b"")
                elif p.exists():
                    p.unlink()
                restored.append(FileDiff(file=path, patch="", status="modified" if snap["existed"] else "deleted"))
        self.stashes[sid] = {"seq": seq, "messages": removed, "files": stash_files}
        self.store.delete_messages_from(sid, seq)
        self.publish(event("session.revert.staged", sid, revert={"messageID": message_id, "files": [f.to_dict() for f in restored]}))
        return {"messageID": message_id, "files": [f.to_dict() for f in restored]}

    def revert_commit(self, sid: str) -> None:
        self.stashes.pop(sid, None)
        self.publish(event("session.revert.committed", sid))

    def revert_clear(self, sid: str) -> None:
        stash = self.stashes.pop(sid, None)
        if not stash:
            return
        for f in stash["files"]:
            p = Path(f["path"])
            if f["existed"]:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(f["content"] or b"")
            elif p.exists():
                p.unlink()
        for m in stash["messages"]:
            self.store.add_message(sid, m)
        self.publish(event("session.revert.cleared", sid))

    # ---- changes / usage ----------------------------------------------------------------------------

    def diff(self, sid: str) -> list[dict]:
        out = []
        for f in self.store.touched_files(sid):
            p = Path(f["path"])
            before = (f["content"] or b"").decode("utf-8", "replace") if f["existed"] else ""
            after = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
            if before == after:
                continue
            patch = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f["path"], tofile=f["path"]))
            adds = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
            status = "added" if not f["existed"] else "deleted" if not p.is_file() else "modified"
            out.append({"file": f["path"], "patch": patch, "status": status, "additions": adds, "deletions": dels})
        return out

    def usage(self, sid: str) -> dict:
        s = self.store.get_session(sid) or {}
        msgs = self.store.list_messages(sid)
        last = next((m for m in reversed(msgs) if m.get("type") == "assistant" and m.get("tokens")), None)
        ref = s.get("model") or self.default_model() or {}
        model = self.find_model(ref)
        tools = sum(1 for m in msgs if m.get("type") == "assistant" for p in m.get("content", []) if p.get("type") == "tool")
        return {"model": ref, "modelName": model.name if model else None, "contextLimit": model.context if model else None, "outputLimit": model.output if model else None,
                "lastInput": ((last or {}).get("tokens") or {}).get("input", 0) + (((last or {}).get("tokens") or {}).get("cache") or {}).get("read", 0),
                "totals": s.get("tokens"), "cost": s.get("cost", 0), "agent": s.get("agent"), "created": (s.get("time") or {}).get("created"),
                "messages": {"user": sum(1 for m in msgs if m.get("type") == "user"), "assistant": sum(1 for m in msgs if m.get("type") == "assistant"),
                             "system": sum(1 for m in msgs if m.get("type") in ("system", "synthetic")), "tools": tools}}

    # ---- export / import ----------------------------------------------------------------------------

    def export_session(self, sid: str) -> dict:
        s = self.store.get_session(sid)
        if not s:
            raise KeyError(sid)
        return {"format": "afh-session", "version": 2, "app": "agent-flow-harness", "exportedAt": now_ms(), "info": s, "messages": self.store.list_messages(sid)}

    def import_session(self, payload: dict, directory: str) -> dict:
        info = payload.get("info") or {}
        messages = payload.get("messages") or []
        s = self.store.create_session(directory, title=info.get("title") or "Imported thread", agent=info.get("agent"), model=info.get("model"),
                                      permissions=info.get("permissions") or perm.rules_for_mode(self.settings().get("defaultMode", "ask")), metadata=info.get("metadata") or {})
        for m in messages:
            if m.get("type") in ("idle",):
                continue
            m = json.loads(json.dumps(m))
            m["id"] = new_id("msg")
            self.store.add_message(s["id"], m)
        self.publish(event("session.created", s["id"], title=s["title"]))
        return self.store.get_session(s["id"])

    def replace_messages(self, sid: str, messages: list[dict]) -> dict:
        self.store.replace_messages(sid, [json.loads(json.dumps(m)) for m in messages])
        return self.store.get_session(sid)

    def context(self, sid: str) -> list[dict]:
        return self.store.list_messages(sid)


# ---- delegation: the leader hands work to a delegate in a child session -----------------------


class SubagentTool:
    spec = ToolSpec(
        name="subagent",
        description=("Delegate a task to one of the configured delegate agents. It runs in its own session with its own model and reports back. "
                     "Give a complete, self-contained prompt (goal, exact file paths, constraints, acceptance criteria, what to report). "
                     "Pass sessionID to continue a previous delegation with the same delegate; omit it for a fresh one. Set background=true to return "
                     "immediately and be told when it finishes."),
        parameters={"type": "object", "properties": {
            "agent": {"type": "string", "description": "The delegate's id"},
            "description": {"type": "string", "description": "A short title for the task (3-8 words)"},
            "prompt": {"type": "string", "description": "The full brief for the delegate"},
            "sessionID": {"type": "string", "description": "Continue this earlier child session instead of starting a new one"},
            "background": {"type": "boolean", "description": "Return immediately; the result arrives later as a message"},
        }, "required": ["agent", "description", "prompt"]},
    )

    def __init__(self, engine: Engine):
        self.engine = engine

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        e = self.engine
        aid = str(input.get("agent", ""))
        agent = next((a for a in agentmod.all_agents(e.settings()) if a.id == aid and a.kind == "delegate"), None)
        if agent is None:
            return ToolResult(text=f"No delegate named '{aid}'. Delegates: {', '.join(agentmod.delegate_ids(e.settings())) or 'none configured'}", is_error=True)
        await ctx.permissions.require("subagent", [aid], {"agent": aid, "description": input.get("description")})
        parent = e.store.get_session(ctx.session_id) or {}
        child = e.store.get_session(str(input.get("sessionID") or "")) if input.get("sessionID") else None
        if child is None:
            child = e.create_session(ctx.directory, title=str(input.get("description") or f"Delegated to {agent.name}")[:80], agent=aid, model=agent.model,
                                     parent_id=ctx.session_id, permissions=parent.get("permissions"))
        msg = {"id": new_id("msg"), "type": "user", "text": str(input.get("prompt", "")), "time": {"created": now_ms()}}
        e.store.add_message(child["id"], msg)
        e.publish(event("session.inbox.enqueued", child["id"], inboxID=msg["id"], item={"type": "user", "payload": {"text": msg["text"]}, "delivery": "steer"}))
        run = e.start_run(child)
        if input.get("background"):
            async def notify() -> None:
                await run.task
                report = self._report(child["id"])
                e.store.add_message(ctx.session_id, {"id": new_id("msg"), "type": "synthetic", "text": f"Delegate {agent.name} finished (sessionID: {child['id']}):\n\n{report}", "time": {"created": now_ms()}})
                if not e.is_running(ctx.session_id):
                    e.start_run(e.store.get_session(ctx.session_id))
            asyncio.create_task(notify())
            return ToolResult(text=f"<subagent sessionID=\"{child['id']}\" state=\"running\">Started in the background. You'll get its report as a new message.</subagent>",
                              metadata={"sessionID": child["id"], "status": "running"})
        await run.task
        report = self._report(child["id"])
        state = "completed" if "failed" not in report[:40].lower() else "failed"
        return ToolResult(text=f"<subagent sessionID=\"{child['id']}\" state=\"{state}\">\n{report}\n</subagent>", metadata={"sessionID": child["id"], "status": state})

    def _report(self, sid: str) -> str:
        msgs = self.engine.store.list_messages(sid)
        for m in reversed(msgs):
            if m.get("type") == "assistant":
                text = "\n\n".join(p.get("text", "") for p in m.get("content", []) if p.get("type") == "text" and p.get("text"))
                if m.get("error"):
                    return f"Delegate failed: {m['error'].get('message', '')}\n{text}".strip()
                if text:
                    return text
        return "(the delegate produced no report)"


engine = Engine()
