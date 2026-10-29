"""The engine facade the API talks to: providers and models, sessions, runs, permissions,
delegation, undo, compaction, MCP and skills. One instance per process."""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .. import store as appstore
from . import agents as agentmod
from . import commands as cmdmod
from . import config as provcfg
from . import hooks as hookmod
from . import permissions as perm
from . import pricing
from . import prompt as promptmod
from . import state as statemod
from . import worktree as wtmod
from .jobs import JobManager, JobsTool
from .runner import Run, to_chat
from .sessions import Store
from .types import BudgetExceeded, ChatMessage, ChatRequest, FileDiff, ModelInfo, Provider, ToolContext, ToolResult, ToolSpec, event, new_id, now_ms

log = logging.getLogger("afh.engine")


def used_tokens(tokens: dict) -> int:
    """Prompt size of a step: uncached input plus what was read from or written to the cache."""
    cache = tokens.get("cache") or {}
    return int(tokens.get("input", 0) or 0) + int(cache.get("read", 0) or 0) + int(cache.get("write", 0) or 0)


def transcript_of(messages: list[dict], brief: bool = False) -> str:
    """Stored messages as plain text for the summariser, tool calls included (shortened). `brief`
    keeps the conversation but drops tool output, for histories too long to summarise in full."""
    out = []
    for m in messages:
        t = m.get("type")
        if t == "user":
            out.append(f"[user] {m.get('text', '')[:3000] if brief else m.get('text', '')}")
        elif t in ("system", "synthetic", "compaction"):
            if m.get("text"):
                out.append(f"[{t}] {m['text'][:1500 if brief else 4000]}")
        elif t == "assistant":
            for p in m.get("content", []):
                if p.get("type") == "text" and p.get("text"):
                    out.append(f"[assistant] {p['text'][:2000] if brief else p['text']}")
                elif p.get("type") == "tool":
                    st = p.get("state") or {}
                    inp = st.get("input")
                    args = json.dumps(inp, ensure_ascii=False)[:160 if brief else 400] if isinstance(inp, dict) else str(inp or "")[:160]
                    if brief:
                        out.append(f"[tool {p.get('name')}] {args}")
                        continue
                    result = "\n".join(c.get("text", "") for c in st.get("content") or [] if c.get("type") == "text")
                    status = st.get("status", "")
                    out.append(f"[tool {p.get('name')} {status}] {args}\n  → {result[:600]}")
    return "\n\n".join(out)


def split_chunks(text: str, size: int) -> list[str]:
    """Cut a transcript into pieces of at most `size` characters, at line breaks where possible."""
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            end = cut if cut > start else end
        chunks.append(text[start:end])
        start = end
    return chunks


SUMMARY_PROMPT = ("Summarise this coding conversation for the assistant that will continue it: the user's requests and goal, decisions made, "
                  "files created or changed (paths), commands that matter and their results, what is done, what is left, and any open questions. "
                  "This summary replaces the messages, so be complete but tight (roughly 200 to 700 words, short sections); keep exact names, paths and numbers. "
                  "Write the summary itself after the ANSWER: marker, all on following lines.")
PART_PROMPT = ("This is part {n} of {total} of a long coding conversation, in order. Summarise this part for the assistant that will continue "
               "the conversation: what the user asked, what was decided and built (files, paths, commands, results), problems and how they ended. "
               "Keep exact names and numbers; be compact. Write the summary after the ANSWER: marker, all on following lines.")
MERGE_PROMPT = ("These are summaries of consecutive parts of one long coding conversation, oldest first. Merge them into one summary for the "
                "assistant that will continue it: the project and the user's goals, what exists now (files, features, decisions), what changed over "
                "time where it still matters, what is left and open questions. Later parts win when they disagree. This summary replaces the whole "
                "history, so be thorough: roughly 600 to 1500 words under the headings Project and goals, Current state, Key decisions, Files and "
                "commands, Problems and how they ended, Next steps. Keep exact names, paths and numbers. Write the summary after the ANSWER: marker, all on following lines.")



def compact_ratio(settings: dict) -> float:
    """How full the context window may get before older messages are summarised (Settings → Agent)."""
    try:
        pct = int((settings.get("agent") or {}).get("compactAt") or 80)
    except (TypeError, ValueError):
        pct = 80
    return max(20, min(95, pct)) / 100

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
        self.jobs = JobManager(self.publish)  # background shell commands
        self.compact_failed: dict[str, float] = {}  # session -> time of the last failed automatic compaction

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
        asyncio.ensure_future(self.resume_interrupted())
        asyncio.ensure_future(self._refresh_catalog())
        from .schedules import Scheduler

        self.scheduler = Scheduler(self._start_scheduled, lambda ev: self.publish(event(ev["type"], None, **ev["data"])))
        self.scheduler.start()

    async def _start_scheduled(self, job: dict) -> str:
        """One run of a scheduled job: a new thread in the job's folder, with the job's prompt."""
        ref = job.get("model")
        if isinstance(ref, str) and "/" in ref:
            pid, _, mid = ref.partition("/")
            ref = {"providerID": pid, "id": mid}
        when = time.strftime("%b %d %H:%M")
        s = self.create_session(job["directory"], title=f"{job['name']} · {when}", agent=job.get("agent"), model=ref or None, mode=job.get("mode") or "full")
        self._patch_afh(s["id"], scheduled={"id": job["id"], "name": job["name"]})
        await self.prompt(s["id"], job["prompt"])
        return s["id"]

    async def _refresh_catalog(self) -> None:
        """Model facts (context, efforts, inputs, prices) from models.dev, once a day, in the background."""
        from . import modelsdev

        if await modelsdev.refresh():
            self.reload_providers()
            self.publish(event("model.updated"))

    async def resume_interrupted(self) -> list[str]:
        """After AFH quits mid-run (an update, a crash, closing the window), pick those threads up again:
        close the cut-off step, tell the model what happened, and continue. Settings: agent.resumeOnRestart."""
        from .runner import close_interrupted

        resumed: list[str] = []
        try:
            settings = self.settings()
            resume = (settings.get("agent") or {}).get("resumeOnRestart", True)
            for sid in self.store.unfinished_sessions(now_ms() - 12 * 3600 * 1000):
                if sid in self.runs:
                    continue
                msgs = self.store.list_messages(sid)
                if not msgs:
                    continue
                last = msgs[-1]
                cut = close_interrupted(last)
                if cut:
                    self.store.save_message(sid, last)
                pending = cut or last.get("type") in ("user", "synthetic") or (last.get("type") == "assistant" and last.get("finish") == "tool-calls")
                for child in self.store.list_sessions(parent_id=sid, limit=200):  # delegations die with their lead; it can re-delegate
                    ms = self.store.list_messages(child["id"])
                    if ms and close_interrupted(ms[-1]):
                        self.store.save_message(child["id"], ms[-1])
                    self.store.touch(child["id"], idle=True)
                session = self.store.get_session(sid)
                imported = ((session or {}).get("metadata") or {}).get("afh", {}).get("importedFrom")
                if imported and (last.get("time") or {}).get("created", 0) < ((session or {}).get("time") or {}).get("created", 0):
                    pending = False  # an import that was never run here: its history ends where the other app stopped
                if not pending or not resume or not session:
                    self.store.touch(sid, idle=True)
                    continue
                note = {"id": new_id("msg"), "type": "synthetic", "time": {"created": now_ms()},
                        "metadata": {"notice": "resume", "label": "AFH restarted — picking up where it left off"},
                        "text": ("AFH was closed or restarted while you were working (for example to install an update), so your last step was cut off. "
                                 "Continue the task from where you left off: check the to-do list and the files for what is already done, redo any "
                                 "interrupted tool call that is still needed, and keep going.")}
                self.store.add_message(sid, note)
                self.publish(event("session.notice", sid, kind="resume", label=note["metadata"]["label"], message=note))
                self.start_run(session)
                resumed.append(sid)
        except Exception as err:  # never block startup
            log.warning("resume after restart: %s", err)
        if resumed:
            log.info("resumed %d interrupted thread(s)", len(resumed))
        return resumed

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
        if getattr(self, "scheduler", None):
            self.scheduler.stop()
        from .tools.browser import MANAGER as browser

        await browser.shutdown()
        for run in list(self.runs.values()):
            run.abort.set()
        await self.jobs.stop_all()
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
        if ref and ref.get("providerID") not in self.providers:
            # A provider AFH doesn't have (an imported thread, a removed provider): the same model elsewhere, else the default.
            from ..transfer import usable_model

            ref = usable_model(self, ref) or (agent.model if agent.model and agent.model.get("providerID") in self.providers else None) or self.default_model()
        if not ref:
            raise RuntimeError("No model is configured. Add a provider in Settings → Models & providers.")
        return {"id": ref["id"], "providerID": ref["providerID"], **({"variant": ref["variant"]} if ref.get("variant") else {})}

    def system_prompt_for(self, session: dict, agent: agentmod.AgentConfig) -> str:
        from .skills import catalog_text

        directory = session["location"]["directory"]
        skills = self.skills_for(directory)
        names = []
        try:
            names = [t.spec.name for t in self.tools_for(session, agent)]
        except Exception as err:
            log.info("tools for prompt: %s", err)
        extra = promptmod.harness_guide(names, agentmod.all_agents(self.settings()), agent)
        goal_text = statemod.goal_prompt(self.goal(session["id"]))
        if goal_text:
            extra += "\n\n" + goal_text
        wt = self._afh(session["id"]).get("worktree")
        if wt:
            extra = (extra + "\n\n" if extra else "") + (
                f"# Worktree\n\nThis thread works in its own git worktree (a separate copy of the repository) on branch `{wt['branch']}`, "
                f"made from `{wt.get('base')}`. Edit files only here: {directory}. The user merges the branch back from the app; "
                "commit your work with git when a piece is done.")
        return promptmod.build(agent_system=agent.system, directory=directory, skills_text=catalog_text(skills) if skills else "",
                               mcp_instructions=self.mcp.instructions() if self.mcp else "", settings=self.settings(), extra=extra)

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
        tools += [JobsTool(), statemod.TodoTool(self)]
        if agent.kind != "delegate":  # goals belong to the thread the user talks to
            tools.append(statemod.GoalTool(self))
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
                       parent_id: str | None = None, permissions: list | None = None, project: str | None = None, worktree: dict | None = None) -> dict:
        mode = mode or self.settings().get("defaultMode", "ask")
        afh: dict[str, Any] = {"mode": mode}
        if worktree:
            afh["worktree"] = worktree
            directory = worktree["directory"]
        s = self.store.create_session(directory, title=title, agent=agent or self.settings().get("defaultAgent", "build"), model=model,
                                      permissions=permissions if permissions is not None else perm.rules_for_mode(mode), metadata={"afh": afh}, parent_id=parent_id,
                                      project=project)
        self.publish(event("session.created", s["id"], parentID=parent_id, title=title, agent=s["agent"], model=s["model"], location=s["location"]))
        return s

    async def create_worktree_session(self, directory: str, name: str | None = None, **kw: Any) -> dict:
        """A thread in its own git worktree: same repository, its own branch (named after `name`) and folder."""
        project = kw.pop("project", None) or directory
        wt = await wtmod.create(directory, name or kw.get("title") or "thread")
        return self.create_session(wt["directory"], project=project, worktree=wt, **kw)

    def update_session(self, sid: str, **fields: Any) -> dict:
        if "mode" in fields:
            mode = fields.pop("mode")
            fields["permissions"] = perm.rules_for_mode(mode)
            with self.store.lock:
                s = self.store.get_session(sid) or {}
                fields["metadata"] = {**s.get("metadata", {}), "afh": {**s.get("metadata", {}).get("afh", {}), "mode": mode}}
                s = self.store.update_session(sid, **fields)
        else:
            s = self.store.update_session(sid, **fields)
        if "title" in fields:
            self.publish(event("session.renamed", sid, title=fields["title"]))
        if "archived" in fields:
            self.publish(event("session.archived" if fields["archived"] else "session.unarchived", sid))
        return s

    def delete_session(self, sid: str) -> dict:
        """Delete a thread (and its delegations). Its background jobs stop; a worktree with no
        unsaved or unmerged work is removed, one with work in it is kept and reported."""
        out: dict[str, Any] = {"ok": True}
        sessions = [sid] + [c["id"] for c in self.store.list_sessions(parent_id=sid, limit=1000)]
        worktrees = []
        for s_id in sessions:
            run = self.runs.get(s_id)
            if run:
                run.abort.set()
            self.on_loop(self.jobs.stop_session(s_id, forget=True))
            wt = self._afh(s_id).get("worktree")
            if wt:
                worktrees.append(wt)
        self.store.delete_session(sid)
        self.publish(event("session.deleted", sid))
        if worktrees:
            fut = self.on_loop(self._cleanup_worktrees(worktrees))
            if fut is not None and not isinstance(fut, asyncio.Task):
                try:
                    out["worktrees"] = fut.result(60)
                except Exception as err:
                    out["worktrees"] = [{"path": w["path"], "kept": True, "error": str(err)} for w in worktrees]
        return out

    def on_loop(self, coro):
        """Schedule a coroutine on the engine's loop from any thread. From another thread it
        returns a concurrent Future (wait on it with .result()); on the loop, a Task."""
        if self.loop is None or self.loop.is_closed():
            coro.close()
            return None
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            return asyncio.ensure_future(coro)
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _cleanup_worktrees(self, worktrees: list[dict]) -> list[dict]:
        report = []
        for wt in worktrees:
            try:
                st = await wtmod.status(wt)
                if st["exists"] and (st["dirty"] or (st["ahead"] and not st["merged"])):
                    report.append({"path": wt["path"], "branch": wt["branch"], "kept": True, "dirty": len(st["dirty"]), "ahead": st["ahead"]})
                    continue
                await wtmod.remove(wt)
                report.append({"path": wt["path"], "branch": wt["branch"], "kept": False})
            except Exception as err:
                report.append({"path": wt["path"], "branch": wt.get("branch"), "kept": True, "error": str(err)})
        return report

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
        self.store.touch(new["id"], idle=True)  # a copy, not a run that was cut off
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
        if self.stashes.pop(sid, None) is not None:  # sending after an undo keeps the undo
            self.publish(event("session.revert.committed", sid))
        fields: dict[str, Any] = {}
        if agent and agent != session.get("agent"):
            fields["agent"] = agent
        if model:
            fields["model"] = model
        if fields:
            session = self.store.update_session(sid, **fields)
        from .skills import discover, mentioned

        command = None
        parsed = cmdmod.parse(text) if text.lstrip().startswith("/") else None
        if parsed:
            name, args = parsed
            if name == "goal":
                if not args:
                    raise ValueError("Write the goal after /goal, e.g. /goal all tests pass and the login page works")
                self.set_goal(sid, args, autopilot=self.settings().get("goals", {}).get("autopilot", True))
                text, command = f"Work toward the goal of this thread:\n\n{args}", {"name": "goal", "args": args}
            elif name == "compact":
                await self.compact_now(sid)
                return {"command": "compact"}
            else:
                found = next((c for c in cmdmod.all_commands(session["location"]["directory"], self.settings()) if c["name"] == name and c.get("prompt")), None)
                if found:
                    text, command = cmdmod.expand(found["prompt"], args), {"name": name, "args": args, "source": found.get("source")}
                elif any(c["name"] == name for c in cmdmod.BUILTINS):
                    raise ValueError(f"/{name} runs in the composer of the AFH window")
        goal = self.goal(sid)
        if goal and (goal.get("turns") or goal.get("exhausted") or goal.get("status") == "blocked") and (command or {}).get("name") != "goal":
            # The user replied: a fresh autopilot budget, and a blocked goal is back in play.
            self.update_goal(sid, status="active" if goal.get("status") == "blocked" else None, turns=0, exhausted=False)

        msg = {"id": new_id("msg"), "type": "user", "text": text, "time": {"created": now_ms()}}
        if command:
            msg["command"] = command
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

    def add_usage(self, sid: str, tokens: dict, cost: float | None = None) -> None:
        with self.store.lock:
            s = self.store.get_session(sid)
            if not s:
                return
            t = s.get("tokens") or {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
            t.setdefault("cache", {}).setdefault("read", 0)
            t["cache"].setdefault("write", 0)
            t["input"] += tokens.get("input", 0)
            t["output"] += tokens.get("output", 0)
            t["reasoning"] += tokens.get("reasoning", 0)
            t["cache"]["read"] += tokens.get("cache", {}).get("read", 0)
            t["cache"]["write"] += tokens.get("cache", {}).get("write", 0)
            fields: dict[str, Any] = {"tokens": t}
            if cost:
                fields["cost"] = round((s.get("cost") or 0) + cost, 8)
            self.store.update_session(sid, **fields)

    # ---- cost & spending limits ---------------------------------------------------------------------

    def price_for(self, ref: dict | None) -> dict | None:
        """USD per 1M tokens for a model, or None (unknown price, or a flat-rate plan)."""
        if not ref:
            return None
        entry = provcfg.entry(ref.get("providerID", "")) or {}
        if pricing.is_plan(entry, ref.get("providerID", "")):
            return None
        return pricing.price_for(entry, ref.get("providerID", ""), self.find_model(ref))

    def check_budget(self, session: dict) -> None:
        b = self.settings().get("budget") or {}
        per_thread = float(b.get("perThread") or 0)
        per_day = float(b.get("perDay") or 0)
        if per_thread > 0:
            spent = (self.store.get_session(session["id"]) or {}).get("cost") or 0
            if spent >= per_thread:
                raise BudgetExceeded(f"This thread has spent ${spent:.2f}, over its ${per_thread:.2f} limit. Raise the limit in Settings → Usage & cost to continue.")
        if per_day > 0:
            import datetime as dt

            start = int(dt.datetime.combine(dt.date.today(), dt.time()).timestamp() * 1000)
            spent = self.store.cost_since(start)
            if spent >= per_day:
                raise BudgetExceeded(f"Today's spending is ${spent:.2f}, over the ${per_day:.2f} daily limit. Raise it in Settings → Usage & cost to continue.")

    # ---- thread state: to-do list & goal ------------------------------------------------------------

    def _afh(self, sid: str) -> dict:
        s = self.store.get_session(sid) or {}
        return (s.get("metadata") or {}).get("afh") or {}

    def _patch_afh(self, sid: str, **fields: Any) -> dict:
        with self.store.lock:
            s = self.store.get_session(sid)
            if not s:
                raise KeyError(sid)
            meta = s.get("metadata") or {}
            afh = {**(meta.get("afh") or {}), **fields}
            afh = {k: v for k, v in afh.items() if v is not None}
            self.store.update_session(sid, metadata={**meta, "afh": afh}, updated=s["time"]["updated"])
        return afh

    def todos(self, sid: str) -> list[dict]:
        return list(self._afh(sid).get("todos") or [])

    def set_todos(self, sid: str, todos: list, by: str = "agent") -> list[dict]:
        todos = statemod.normalize_todos(todos, self.todos(sid))
        fields: dict[str, Any] = {"todos": todos}
        c = statemod.todo_counts(todos)
        if c["total"] and not c["open"] and c["completed"]:
            # A finished list goes to the thread's history ("Completed lists" in the Goal menu).
            history = list(self._afh(sid).get("todoHistory") or [])
            sig = [t["content"] for t in todos]
            if not history or [t["content"] for t in history[-1]["todos"]] != sig:
                history.append({"todos": todos, "completed": now_ms()})
                fields["todoHistory"] = history[-30:]
        self._patch_afh(sid, **fields)
        self.publish(event("session.todos.updated", sid, todos=todos, counts=c, by=by, history=fields.get("todoHistory")))
        if by == "user":
            # The model learns about the user's edit the next time it is called.
            self.store.add_message(sid, {"id": new_id("msg"), "type": "system", "metadata": {"notice": "todos"}, "time": {"created": now_ms()},
                                         "text": "The user edited your to-do list. It is now:\n" + statemod.render_todos(todos) + "\n\nFollow this list from now on."})
        return todos

    def goal(self, sid: str) -> dict | None:
        return self._afh(sid).get("goal")

    def set_goal(self, sid: str, text: str, criteria: str = "", autopilot: bool = True, max_turns: int | None = None, by: str = "user") -> dict:
        prev = self.goal(sid)
        goal = statemod.make_goal(text, criteria, autopilot, max_turns or self.settings().get("goals", {}).get("maxTurns", statemod.DEFAULT_GOAL_TURNS), prev)
        goal["by"] = by
        self._patch_afh(sid, goal=goal)
        self.publish(event("session.goal.updated", sid, goal=goal))
        return goal

    def update_goal(self, sid: str, status: str | None = None, note: dict | None = None, **fields: Any) -> dict | None:
        goal = self.goal(sid)
        if not goal:
            return None
        goal = {**goal, **fields, "updated": now_ms()}
        if status:
            goal["status"] = status
            if status == "achieved":
                goal["achieved"] = now_ms()
        if note:
            goal["progress"] = [*(goal.get("progress") or []), note][-20:]
            if note.get("status") in ("achieved", "blocked"):
                goal["summary"] = note.get("summary", "")
        extra: dict[str, Any] = {}
        if status == "achieved":
            # Achieved goals are kept in the thread's history ("Achieved goals" in the Goal menu).
            history = list(self._afh(sid).get("goalHistory") or [])
            history.append({k: goal.get(k) for k in ("text", "criteria", "summary", "achieved", "created", "by")})
            extra["goalHistory"] = history[-30:]
        self._patch_afh(sid, goal=goal, **extra)
        self.publish(event("session.goal.updated", sid, goal=goal, history=extra.get("goalHistory")))
        return goal

    def clear_goal(self, sid: str) -> None:
        with self.store.lock:
            s = self.store.get_session(sid)
            if not s:
                raise KeyError(sid)
            meta = s.get("metadata") or {}
            afh = {k: v for k, v in (meta.get("afh") or {}).items() if k != "goal"}
            self.store.update_session(sid, metadata={**meta, "afh": afh}, updated=s["time"]["updated"])
        self.publish(event("session.goal.updated", sid, goal=None))

    async def on_agent_stop(self, run: Run) -> dict | None:
        """The model ended its turn without tool calls. Returns {kind, text} to make it continue:
        a stop hook that failed, goal autopilot, or (once per run) an out-of-date to-do list."""
        sid = run.sid
        settings = self.settings()
        directory = run.session["location"]["directory"]
        if run.stop_rounds < hookmod.STOP_ROUNDS:
            hs = hookmod.hooks_for(settings, "stop")
            if hs:
                results = await hookmod.run_all(hs, {"event": "stop", "sessionID": sid, "project": directory}, directory, settings.get("shell"))
                self.publish(event("session.hooks.ran", sid, hook="stop", results=results))
                blocking = [r for r in results if r["code"] == hookmod.BLOCK_CODE]
                if blocking:
                    run.stop_rounds += 1
                    body = "\n\n".join(f"Hook '{r['name']}':\n{r['output'] or '(no output)'}" for r in blocking)
                    return {"kind": "hook", "text": f"A stop hook did not pass, so the work is not finished yet. Fix this, then finish again:\n\n{body}",
                            "label": f"Stop hook failed: {', '.join(r['name'] for r in blocking)} — continuing"}
        goal = self.goal(sid)
        if goal and goal.get("status") == "active" and goal.get("autopilot"):
            if goal.get("turns", 0) < goal.get("maxTurns", statemod.DEFAULT_GOAL_TURNS):
                goal = self.update_goal(sid, turns=goal.get("turns", 0) + 1)
                return {"kind": "goal", "text": statemod.continuation_text(goal, self.todos(sid)),
                        "label": f"Goal not achieved yet — continuing ({goal['turns']}/{goal['maxTurns']})"}
            if not goal.get("exhausted"):
                self.update_goal(sid, exhausted=True)
                self.publish(event("session.notice", sid, kind="goal", label=f"Autopilot paused after {goal.get('maxTurns')} continuations — reply to keep going"))
        todos = self.todos(sid)
        left = statemod.open_todos(todos)
        if left and not run.todo_nudged and (settings.get("agent") or {}).get("todoNudge", True):
            run.todo_nudged = True
            return {"kind": "todo", "label": f"{len(left)} to-do item{'s' if len(left) != 1 else ''} still open — checking",
                    "text": ("You ended your turn, but your to-do list still has open items:\n" + statemod.render_todos(left) +
                             "\n\nIf they are done, mark them completed (todo tool). If they are no longer needed, mark them cancelled. "
                             "Otherwise keep working on them now. If you stopped because you need the user's answer, keep the list as it is and end your turn with the question.")}
        return None

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
        lines = text_out.splitlines()
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().upper().startswith("ANSWER:"):
                # The answer is the rest of the marker line plus everything after it (summaries span lines).
                rest = lines[i].split(":", 1)[1].strip()
                tail = "\n".join(lines[i + 1:]).strip()
                return "\n".join(x for x in (rest, tail) if x).strip()
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

    async def maybe_compact(self, session: dict, agent: agentmod.AgentConfig, force: bool = False) -> bool:
        """Summarise older messages when the conversation no longer fits comfortably (or on /compact).

        The trigger is the real size of what would be sent (an imported thread can be millions of
        tokens before the model ever answered), not just the last step's token count."""
        from .runner import live_start

        everything = self.store.list_messages(session["id"])
        msgs = everything[live_start(everything):]  # what the model sees now: the last summary onward
        try:
            ref = self.model_ref_for(session, agent)
            _, model = self.resolve_model(ref)
        except Exception:
            return False
        if not force:
            if len(msgs) < 8 or time.time() - self.compact_failed.get(session["id"], 0) < 600:
                return False
            last = next((m for m in reversed(msgs) if m.get("type") == "assistant" and m.get("tokens")), None)
            measured = used_tokens(last["tokens"]) if last else 0
            from .runner import estimate_tokens

            estimated = estimate_tokens(to_chat(msgs))
            if max(measured, estimated) < model.context * compact_ratio(self.settings()):
                return False
        keep_n = 6 if len(msgs) > 8 else max(1, len(msgs) // 2)
        keep = msgs[-keep_n:]
        old = msgs[:-keep_n]
        if not old:
            return False
        self.publish(event("session.compaction.started", session["id"], messages=len(old)))
        try:
            summary = await self.summarize_history(session["id"], ref, model, old)
        except Exception as err:
            log.info("compaction skipped: %s", err)
            self.compact_failed[session["id"]] = time.time()
            self.publish(event("session.compaction.ended", session["id"], skipped=str(err)))
            return False
        if len(summary.strip()) < 10:  # never trade the history for an empty summary
            log.info("compaction skipped: the summary came back empty")
            self.compact_failed[session["id"]] = time.time()
            self.publish(event("session.compaction.ended", session["id"], skipped="the model returned no summary"))
            return False
        extra = []
        todos = self.todos(session["id"])
        if todos:
            extra.append("Your to-do list at this point:\n" + statemod.render_todos(todos))
        goal = self.goal(session["id"])
        if goal and goal.get("status") in ("active", "blocked"):
            extra.append(f"The thread's goal (still {goal['status']}): {goal['text']}")
        text = summary.strip() + ("\n\n" + "\n\n".join(extra) if extra else "")
        compacted = sum(1 for m in old if m.get("type") != "compaction")
        compaction = {"id": new_id("msg"), "type": "compaction", "text": text, "time": {"created": now_ms()},
                      "metadata": {"compacted": compacted, "auto": not force}}
        # Nothing is deleted: the summary goes in where it happened, before the messages it keeps.
        # The model reads from the summary on; the user still sees every message above it.
        self.store.insert_before(session["id"], keep[0]["id"], compaction)
        self.publish(event("session.compaction.ended", session["id"], compacted=compacted))
        return True

    async def summarize_history(self, sid: str, ref: dict, model: ModelInfo, old: list[dict]) -> str:
        """One summary of `old`, however long: a single call when it fits, otherwise the history is cut
        into chunks that are summarised (three at a time) and the partial summaries are merged."""
        budget = int(max(40_000, min(model.context * 0.45 * 3.6, 360_000)))  # characters per call
        text = transcript_of(old)
        if len(text) > budget:
            text = transcript_of(old, brief=True)
        if len(text) <= budget:
            return await self._complete(ref, SUMMARY_PROMPT, text, 2500)
        chunks = split_chunks(text, budget)
        total = len(chunks)
        done = 0
        self.publish(event("session.compaction.progress", sid, done=0, total=total + 1))
        sem = asyncio.Semaphore(3)

        async def part(i: int, chunk: str) -> str:
            nonlocal done
            async with sem:
                prompt = PART_PROMPT.format(n=i + 1, total=total)
                for attempt in range(2):
                    try:
                        out = await self._complete(ref, prompt, chunk, 1500)
                        if out.strip():
                            break
                    except Exception as err:
                        log.info("summary part %s failed: %s", i + 1, err)
                        out = ""
                done += 1
                self.publish(event("session.compaction.progress", sid, done=done, total=total + 1))
                return out.strip() or f"(part {i + 1} could not be summarised)"

        parts = await asyncio.gather(*(part(i, c) for i, c in enumerate(chunks)))
        merged = "\n\n".join(f"## Part {i + 1} of {total}\n{p}" for i, p in enumerate(parts))[-budget:]
        final = await self._complete(ref, MERGE_PROMPT, merged, 5000)
        self.publish(event("session.compaction.progress", sid, done=total + 1, total=total + 1))
        return final if final.strip() else merged

    async def compact_now(self, sid: str) -> bool:
        session = self.store.get_session(sid)
        if not session:
            raise KeyError(sid)
        if self.is_running(sid):
            raise ValueError("Wait for the thread to finish (or stop it) before compacting")
        return await self.maybe_compact(session, self.agent_for(session), force=True)

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
        entry = provcfg.entry(ref.get("providerID", "")) or {}
        return {"model": ref, "modelName": model.name if model else None, "contextLimit": model.context if model else None, "outputLimit": model.output if model else None,
                "lastInput": used_tokens((last or {}).get("tokens") or {}),
                "totals": s.get("tokens"), "cost": s.get("cost", 0), "price": self.price_for(ref), "plan": pricing.is_plan(entry, ref.get("providerID", "")),
                "agent": s.get("agent"), "created": (s.get("time") or {}).get("created"),
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
                     "immediately and be told when it finishes. Several subagent calls in the same reply run AT THE SAME TIME - use that to fan out "
                     "independent tasks. When parallel delegates would edit files, give each `worktree: true` so it works in its own git worktree "
                     "(own branch and folder); its report names the branch to merge (git merge <branch>)."),
        parameters={"type": "object", "properties": {
            "agent": {"type": "string", "description": "The delegate's id"},
            "description": {"type": "string", "description": "A short title for the task (3-8 words)"},
            "prompt": {"type": "string", "description": "The full brief for the delegate"},
            "sessionID": {"type": "string", "description": "Continue this earlier child session instead of starting a new one"},
            "background": {"type": "boolean", "description": "Return immediately; the result arrives later as a message"},
            "worktree": {"type": "boolean", "description": "Run the delegate in its own git worktree (a separate copy on a new branch) so parallel delegates never clash"},
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
        wt_note = ""
        if child is None:
            title = str(input.get("description") or f"Delegated to {agent.name}")[:80]
            perms = list(parent.get("permissions") or [])
            if ctx.read_only:  # a read-only thread (Plan mode, Read only) never gets write access through a subagent
                perms += agentmod.READONLY_RULES
            kw = dict(title=title, agent=aid, model=agent.model or parent.get("model"), parent_id=ctx.session_id, permissions=perms)
            if input.get("worktree"):
                try:
                    child = await e.create_worktree_session(ctx.directory, project=parent.get("project") or ctx.directory, **kw)
                    wt = e._afh(child["id"]).get("worktree") or {}
                    wt_note = f"\nWorktree: {wt.get('path')} on branch {wt.get('branch')} (merge it with: git merge {wt.get('branch')})"
                except wtmod.GitError as err:
                    return ToolResult(text=f"Could not create a worktree for the delegate: {err}", is_error=True)
            else:
                child = e.create_session(ctx.directory, **kw)
        msg = {"id": new_id("msg"), "type": "user", "text": str(input.get("prompt", "")), "time": {"created": now_ms()}}
        e.store.add_message(child["id"], msg)
        e.publish(event("session.inbox.enqueued", child["id"], inboxID=msg["id"], item={"type": "user", "payload": {"text": msg["text"]}, "delivery": "steer"}))
        e.publish(event("session.inbox.delivered", child["id"], inboxID=msg["id"]))
        run = e.start_run(child)
        if input.get("background"):
            async def notify() -> None:
                await run.task
                report = self._report(child["id"])
                e.store.add_message(ctx.session_id, {"id": new_id("msg"), "type": "synthetic", "text": f"Delegate {agent.name} finished (sessionID: {child['id']}):\n\n{report}", "time": {"created": now_ms()}})
                if not e.is_running(ctx.session_id):
                    e.start_run(e.store.get_session(ctx.session_id))
            asyncio.create_task(notify())
            return ToolResult(text=f"<subagent sessionID=\"{child['id']}\" state=\"running\">Started in the background. You'll get its report as a new message.{wt_note}</subagent>",
                              metadata={"sessionID": child["id"], "status": "running"})
        try:
            await run.task
        except asyncio.CancelledError:
            e.interrupt(child["id"])
            raise
        report = self._report(child["id"])
        state = "completed" if "failed" not in report[:40].lower() else "failed"
        return ToolResult(text=f"<subagent sessionID=\"{child['id']}\" state=\"{state}\">\n{report}{wt_note}\n</subagent>", metadata={"sessionID": child["id"], "status": state})

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
