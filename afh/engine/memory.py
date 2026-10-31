"""Project memory: a short list of facts the agent learns about a project and keeps between threads
(how to run the tests, conventions, what the user prefers). It lives in the project as
.afh/memory.md, goes into the system prompt of every thread there, and the user can read and edit
it from the sidebar."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .. import store
from .types import ToolContext, ToolResult, ToolSpec

if TYPE_CHECKING:
    from .core import Engine

MEMORY_FILE = Path(".afh") / "memory.md"
MAX_FACTS = 60
MAX_FACT_LEN = 300
HEADER = "# Project memory\n\nFacts AFH learned about this project. Edit freely; one fact per line.\n\n"


def path_for(project: str) -> Path:
    return Path(project) / MEMORY_FILE


def facts(text: str) -> list[str]:
    """The facts in a memory file: its bullet lines (anything else is the user's own notes and is kept as it is)."""
    return [line[2:].strip() for line in text.splitlines() if line.startswith("- ") and line[2:].strip()]


def render(items: list[str]) -> str:
    return HEADER + "".join(f"- {f}\n" for f in items)


def prompt_section(project: str, text: str) -> str:
    """The memory as the model sees it in its system prompt."""
    items = facts(text)
    where = str(path_for(project))
    if not items:
        return (f"# Project memory\n\nNothing remembered about this project yet ({where}). When you learn something durable and "
                "non-obvious about it - how to run or test it, a convention, something the user wants done a certain way - "
                "save it with the `memory` tool so later threads start knowing it.")
    return (f"# Project memory\n\nWhat earlier threads learned about this project ({where}; the user can edit it). Trust it, "
            "but if a fact turns out wrong, fix it with the `memory` tool.\n\n" + "".join(f"- {f}\n" for f in items)).rstrip()


class MemoryTool:
    spec = ToolSpec(
        name="memory",
        description=(
            "The project's memory: facts kept between threads, shown to every agent working in this project and editable by the user. "
            "Use it for things that are durable, non-obvious and worth knowing next time - how to run, build or test the project, "
            "conventions and gotchas, the user's preferences about how work is done here. Not for task progress, not for what is "
            "already in AGENTS.md or obvious from the code, never for secrets. "
            "action \"add\": remember one fact (`text`, one sentence). action \"replace\": fix a fact (`old` is the wrong one, `text` the "
            "correct one). action \"remove\": forget a fact (`old`). Each fact is one line; keep them short and specific."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                "text": {"type": "string", "description": "For add/replace: the fact, one short sentence."},
                "old": {"type": "string", "description": "For replace/remove: the existing fact (or a distinctive part of it)."},
            },
            "required": ["action"],
        },
    )

    def __init__(self, engine: "Engine"):
        self.engine = engine

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        e = self.engine
        project = e.memory_project(ctx.session_id) or ctx.directory
        action = str(input.get("action") or "").strip().lower()
        text = " ".join(str(input.get("text") or "").split())
        old = " ".join(str(input.get("old") or "").split())
        items = facts(e.read_memory(project))
        if action not in ("add", "replace", "remove"):
            return ToolResult(text='action must be "add", "replace" or "remove".', is_error=True)
        if action in ("add", "replace") and not text:
            return ToolResult(text="Give the fact in `text`.", is_error=True)
        if len(text) > MAX_FACT_LEN:
            return ToolResult(text=f"Keep a fact under {MAX_FACT_LEN} characters: one specific sentence.", is_error=True)
        if action in ("replace", "remove"):
            if not old:
                return ToolResult(text="Say which fact in `old`.", is_error=True)
            hits = [f for f in items if old.lower() in f.lower()]
            if not hits:
                return ToolResult(text="No fact matches `old`. The memory is now:\n" + ("\n".join(f"- {f}" for f in items) or "(empty)"), is_error=True)
            if len(hits) > 1 and old.lower() not in [f.lower() for f in items]:
                return ToolResult(text="`old` matches more than one fact; quote one of them exactly:\n" + "\n".join(f"- {f}" for f in hits), is_error=True)
            target = old if old.lower() in [f.lower() for f in items] else hits[0]
            idx = [f.lower() for f in items].index(target.lower())
            if action == "remove":
                items.pop(idx)
                done = "Forgotten."
            else:
                items[idx] = text
                done = "Fact updated."
        else:
            if text.lower() in [f.lower() for f in items]:
                return ToolResult(text="Already remembered.", metadata={"count": len(items)})
            if len(items) >= MAX_FACTS:
                return ToolResult(text=f"The memory is full ({MAX_FACTS} facts). Remove or merge facts that no longer matter before adding more:\n" +
                                  "\n".join(f"- {f}" for f in items), is_error=True)
            items.append(text)
            done = "Remembered; every later thread in this project will know it."
        e.set_memory_facts(project, items, by="agent")
        return ToolResult(text=f"{done} The memory now has {len(items)} fact{'s' if len(items) != 1 else ''}.", metadata={"count": len(items), "action": action})


def write(project: str, items: list[str], existing: str = "") -> str:
    """Write the facts back, keeping any notes the user wrote outside the bullet list."""
    notes = "\n".join(line for line in existing.splitlines() if not line.startswith("- ")).strip()
    text = (notes + "\n\n" if notes else HEADER) + "".join(f"- {f}\n" for f in items)
    store.write_text_with_backup(path_for(project), text)
    return text
