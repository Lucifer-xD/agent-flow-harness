"""Per-thread working state the agent keeps: its to-do list and the thread's goal.

Both live in the session's ``metadata.afh`` (``todos``, ``goal``), so they survive restarts,
compaction and context edits. The model changes them through the ``todo`` and ``goal`` tools;
the user changes them from the UI. Every change is published as an event so the UI stays live.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import ToolContext, ToolResult, ToolSpec, now_ms

if TYPE_CHECKING:
    from .core import Engine

TODO_STATUSES = ("pending", "in_progress", "completed", "cancelled")
_STATUS_ALIASES = {
    "todo": "pending", "open": "pending", "not_started": "pending", "waiting": "pending",
    "in-progress": "in_progress", "inprogress": "in_progress", "active": "in_progress", "doing": "in_progress", "working": "in_progress", "started": "in_progress",
    "done": "completed", "complete": "completed", "finished": "completed", "ok": "completed",
    "canceled": "cancelled", "skipped": "cancelled", "dropped": "cancelled", "removed": "cancelled",
}
MARKS = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "cancelled": "[-]"}
MAX_TODOS = 50
GOAL_STATUSES = ("active", "achieved", "blocked", "paused")
DEFAULT_GOAL_TURNS = 10


# ---- to-do list ----------------------------------------------------------------------------


def norm_status(value) -> str:
    s = str(value or "pending").strip().lower().replace(" ", "_")
    s = _STATUS_ALIASES.get(s, s)
    return s if s in TODO_STATUSES else "pending"


def normalize_todos(items, previous: list[dict] | None = None) -> list[dict]:
    """Clean a list from the model or the UI: ids, statuses, no empty or duplicate items."""
    prev = {t["id"]: t for t in previous or []}
    out: list[dict] = []
    used: set[str] = set()
    for i, raw in enumerate(items or []):
        if isinstance(raw, str):
            raw = {"content": raw}
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or raw.get("text") or raw.get("title") or raw.get("task") or "").strip()
        if not content:
            continue
        tid = str(raw.get("id") or "").strip() or None
        if not tid or tid in used:
            tid = next((p["id"] for p in prev.values() if p["content"] == content and p["id"] not in used), None) or _next_id(used | set(prev))
        used.add(tid)
        item = {"id": tid, "content": content[:500], "status": norm_status(raw.get("status"))}
        active = str(raw.get("activeForm") or raw.get("active_form") or "").strip()
        if active:
            item["activeForm"] = active[:200]
        old = prev.get(tid)
        item["created"] = (old or {}).get("created") or now_ms()
        if old and old.get("status") != item["status"]:
            item["changed"] = now_ms()
        elif old and old.get("changed"):
            item["changed"] = old["changed"]
        out.append(item)
        if len(out) >= MAX_TODOS:
            break
    return out


def _next_id(used: set[str]) -> str:
    n = 1
    while str(n) in used:
        n += 1
    return str(n)


def merge_todos(current: list[dict], updates) -> list[dict]:
    """`merge: true`: items with a known id update that item; the rest are appended."""
    by_id = {t["id"]: dict(t) for t in current}
    order = [t["id"] for t in current]
    extra = []
    for raw in updates or []:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("id") or "").strip()
        if tid and tid in by_id:
            for key in ("content", "status", "activeForm"):
                if raw.get(key) not in (None, ""):
                    by_id[tid][key] = raw[key]
        else:
            extra.append(raw)
    return normalize_todos([by_id[i] for i in order] + extra, current)


def todo_counts(todos: list[dict]) -> dict:
    c = {s: 0 for s in TODO_STATUSES}
    for t in todos:
        c[t["status"]] = c.get(t["status"], 0) + 1
    return {**c, "total": len(todos), "open": c["pending"] + c["in_progress"]}


def render_todos(todos: list[dict]) -> str:
    if not todos:
        return "(the to-do list is empty)"
    return "\n".join(f"{MARKS[t['status']]} {i}. {t['content']}" for i, t in enumerate(todos, 1))


def open_todos(todos: list[dict]) -> list[dict]:
    return [t for t in todos if t["status"] in ("pending", "in_progress")]


class TodoTool:
    spec = ToolSpec(
        name="todo",
        description=(
            "Keep a to-do list for the current task; the user watches it live. Use it for any task with 3 or more "
            "steps, or when the user gives you several things to do. Every call sends the COMPLETE list, in order - it "
            "replaces the previous one - with each item's current status. Rules: break the work into concrete, verifiable "
            "steps; keep exactly ONE item in_progress at a time; mark an item completed right after you finish it (not in "
            "a batch at the end); add items you discover along the way; mark items you drop as cancelled. Never mark an item "
            "completed if its tests fail or it is only partly done. Call it with no arguments to read the current list "
            "(the user may have edited it). Example: {\"todos\": [{\"content\": \"Add the parser\", \"status\": \"completed\"}, "
            "{\"content\": \"Write tests\", \"status\": \"in_progress\"}, {\"content\": \"Update the README\", \"status\": \"pending\"}]}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete to-do list, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "What to do, imperative (\"Add login form validation\")."},
                            "status": {"type": "string", "enum": list(TODO_STATUSES)},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
        },
    )

    def __init__(self, engine: "Engine"):
        self.engine = engine

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        e = self.engine
        current = e.todos(ctx.session_id)
        items = input.get("todos")
        if items is None:
            return ToolResult(text=_todo_report(current, "Current to-do list"), metadata={"todos": current, "read": True})
        if not isinstance(items, list):
            return ToolResult(text="`todos` must be an array of {id, content, status} objects.", is_error=True)
        todos = merge_todos(current, items) if input.get("merge") else normalize_todos(items, current)
        todos = e.set_todos(ctx.session_id, todos, by="agent")
        text = _todo_report(todos, "To-do list updated")
        running = [t for t in todos if t["status"] == "in_progress"]
        if len(running) > 1:
            text += f"\n\nNote: {len(running)} items are in progress. Keep exactly one in progress: finish it, then start the next."
        elif not running and open_todos(todos):
            text += "\n\nNote: nothing is in progress. Mark the item you are working on now as in_progress."
        return ToolResult(text=text, metadata={"todos": todos, "counts": todo_counts(todos)})


def _todo_report(todos: list[dict], title: str) -> str:
    c = todo_counts(todos)
    head = f"{title} ({c['completed']}/{c['total'] - c['cancelled']} done)" if todos else title
    return f"{head}:\n{render_todos(todos)}"


# ---- goal ------------------------------------------------------------------------------------


def make_goal(text: str, criteria: str = "", autopilot: bool = True, max_turns: int = DEFAULT_GOAL_TURNS, previous: dict | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("The goal needs a description")
    t = now_ms()
    return {
        "text": text[:4000], "criteria": (criteria or "").strip()[:4000], "status": "active",
        "autopilot": bool(autopilot), "maxTurns": max(1, min(100, int(max_turns or DEFAULT_GOAL_TURNS))), "turns": 0,
        "summary": "", "progress": [], "created": (previous or {}).get("created") or t, "updated": t,
    }


def goal_prompt(goal: dict | None) -> str:
    """The system-prompt section for a thread with a goal. It changes only when the goal does."""
    if not goal or goal.get("status") not in ("active", "blocked", "paused"):
        return ""
    lines = ["# Goal of this thread", "", "The user set this goal. Everything you do in this thread works toward it.", "", f"**Goal:** {goal['text']}"]
    if goal.get("criteria"):
        lines += ["", f"**Done when:** {goal['criteria']}"]
    lines += [
        "",
        "How to work toward it:",
        "- Keep a to-do list (`todo` tool) of the steps that get you there, and update it as you go.",
        "- Verify for real: run the tests, the build or the program; read the result. The goal is achieved only when every \"done when\" condition holds and you checked it.",
        "- When it is achieved, call `goal` with status \"achieved\" and a summary of what you did and how you verified it, then give the user your final report.",
        "- If you cannot make progress without the user (a decision, credentials, something outside your reach), call `goal` with status \"blocked\" and say exactly what you need.",
        "- Use status \"progress\" for a short milestone note when a big part is done.",
    ]
    if goal.get("autopilot"):
        lines.append("- Autopilot is on: if you stop before the goal is achieved or blocked, AFH asks you to continue. Do not stop to ask for permission to keep going.")
    if goal.get("status") == "blocked":
        lines += ["", f"Status: blocked — {goal.get('summary') or 'waiting for the user'}. Continue when the user has answered."]
    return "\n".join(lines)


def continuation_text(goal: dict, todos: list[dict]) -> str:
    left = open_todos(todos)
    parts = [
        f"[Goal autopilot {goal['turns']}/{goal['maxTurns']}] You stopped, but the goal is not marked achieved yet.",
        f"Goal: {goal['text']}",
    ]
    if goal.get("criteria"):
        parts.append(f"Done when: {goal['criteria']}")
    if left:
        parts.append("Open to-do items:\n" + render_todos(left))
    parts.append("Continue working toward the goal now. If it is fully done, verify it and call `goal` with status \"achieved\". "
                 "If you truly cannot continue without the user, call `goal` with status \"blocked\" and explain what you need.")
    return "\n\n".join(parts)


class GoalTool:
    spec = ToolSpec(
        name="goal",
        description=(
            "Report on the thread's goal (set by the user; see \"Goal of this thread\" in your instructions). "
            "status \"achieved\": every done-when condition holds and you verified it - give the summary and evidence. "
            "status \"blocked\": you cannot continue without the user - say exactly what you need. "
            "status \"progress\": a short milestone note. Do not claim achieved for partial or unverified work."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["achieved", "blocked", "progress"]},
                "summary": {"type": "string", "description": "What was done / what is blocking / the milestone, in one to five sentences."},
                "evidence": {"type": "string", "description": "For achieved: how you verified it (commands run and their results)."},
            },
            "required": ["status", "summary"],
        },
    )

    def __init__(self, engine: "Engine"):
        self.engine = engine

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        e = self.engine
        goal = e.goal(ctx.session_id)
        if not goal:
            return ToolResult(text="This thread has no goal. Only the user can set one.", is_error=True)
        status = str(input.get("status") or "").strip().lower()
        summary = str(input.get("summary") or "").strip()
        evidence = str(input.get("evidence") or "").strip()
        if status not in ("achieved", "blocked", "progress"):
            return ToolResult(text="status must be \"achieved\", \"blocked\" or \"progress\".", is_error=True)
        if not summary:
            return ToolResult(text="Give a summary.", is_error=True)
        if status == "achieved":
            left = open_todos(e.todos(ctx.session_id))
            if left:
                return ToolResult(text=("Your to-do list still has open items:\n" + render_todos(left) +
                                        "\n\nFinish them (or mark them cancelled if they are not needed) before marking the goal achieved."), is_error=True)
        note = {"status": status, "summary": summary[:2000], "time": now_ms()}
        if evidence:
            note["evidence"] = evidence[:3000]
        goal = e.update_goal(ctx.session_id, status=None if status == "progress" else status, note=note)
        if status == "achieved":
            text = "Goal marked achieved. Now give the user your final report: what changed, how you verified it, anything left open."
        elif status == "blocked":
            text = "Goal marked blocked; autopilot pauses. Tell the user exactly what you need, then stop."
        else:
            text = "Progress noted. Keep going."
        return ToolResult(text=text, metadata={"goal": goal})
