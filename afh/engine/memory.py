"""Project memory: a short list of facts the agent learns about a project and keeps between threads
(how to run the tests, conventions, what the user prefers). It lives in the project as
.afh/memory.md, goes into the system prompt of every thread there, and the user can read and edit
it from the sidebar."""

from __future__ import annotations

import subprocess
import sys
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


def _git(project: str, *args: str) -> subprocess.CompletedProcess | None:
    from .tools.shell import CREATE_NO_WINDOW, child_env

    try:
        return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True, timeout=8, env=child_env(),
                              stdin=subprocess.DEVNULL, **({"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
    except (OSError, subprocess.SubprocessError):
        return None


def keep_out_of_git(project: str) -> bool:
    """The memory may hold tokens and credentials, so git must never pick the file up. In a git
    repository this adds it to .git/info/exclude (a local-only ignore: the project's own .gitignore
    is left alone). Returns True when the file is already tracked by git, which an ignore can't undo."""
    if not project or not path_for(project).is_file():
        return False
    r = _git(project, "rev-parse", "--show-toplevel", "--git-path", "info/exclude")
    if not r or r.returncode != 0:
        return False  # not a git repository (or no git): nothing to keep it out of
    lines = r.stdout.strip().splitlines()
    if len(lines) < 2:
        return False
    top, exclude = Path(lines[0]), Path(lines[1])
    if not exclude.is_absolute():
        exclude = Path(project) / exclude
    try:
        rel = path_for(project).resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return False
    try:
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if f"/{rel}" not in current.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            sep = "" if not current or current.endswith("\n") else "\n"
            exclude.write_text(current + sep + f"# AFH project memory (may hold credentials): never commit it\n/{rel}\n", encoding="utf-8")
    except OSError:
        pass
    t = _git(project, "ls-files", "--error-unmatch", "--", MEMORY_FILE.as_posix())  # relative to the project folder
    return bool(t and t.returncode == 0)


def facts(text: str) -> list[str]:
    """The facts in a memory file: its bullet lines (anything else is the user's own notes and is kept as it is)."""
    return [line[2:].strip() for line in text.splitlines() if line.startswith("- ") and line[2:].strip()]


def render(items: list[str]) -> str:
    return HEADER + "".join(f"- {f}\n" for f in items)


def notes(text: str) -> str:
    """Whatever the user wrote outside the bullet list (minus the file's own header): the model reads it too."""
    body = text.replace(HEADER.strip(), "", 1)
    lines = [line for line in body.splitlines() if not line.startswith("- ")]
    return "\n".join(lines).strip()


def show(text: str) -> str:
    """The memory as the `memory` tool's list action returns it."""
    items, extra = facts(text), notes(text)
    out = "\n".join(f"- {f}" for f in items) or "(no facts yet)"
    return out + (f"\n\nThe user's notes:\n{extra}" if extra else "")


def prompt_section(project: str, text: str) -> str:
    """The memory as the model sees it in its system prompt."""
    items, extra = facts(text), notes(text)
    where = str(path_for(project))
    if not items and not extra:
        return (f"# Project memory\n\nNothing remembered about this project yet ({where}). When you learn something durable and "
                "non-obvious about it - how to run or test it, a convention, something the user wants done a certain way - "
                "save it with the `memory` tool so later threads start knowing it.")
    out = (f"# Project memory\n\nWhat you and the user saved about this project in earlier threads ({where}; the user can "
           "see and edit it at any time, and changes reach you on your next step). Follow it: it is how things are done here. "
           "If a fact turns out wrong or outdated, fix it with the `memory` tool. Tokens, keys and credentials kept here are "
           "the user's, saved for you to use: use them when a task needs them, without asking again.\n\n")
    if items:
        out += "".join(f"- {f}\n" for f in items)
    if extra:
        out += ("\n" if items else "") + "The user's notes:\n" + extra + "\n"
    return out.rstrip()


class MemoryTool:
    spec = ToolSpec(
        name="memory",
        description=(
            "The project's memory: facts kept between threads, shown to every agent working in this project and editable by the user. "
            "Use it for things that are durable, non-obvious and worth knowing next time - how to run, build or test the project, "
            "conventions and gotchas, the user's preferences about how work is done here. Not for task progress, not for what is "
            "already in AGENTS.md or obvious from the code. "
            "It is a private, local file: it stays on this computer and AFH keeps it out of git, so it is the right place for "
            "access tokens, API keys, logins and other credentials you or the user want available in later threads. "
            "When you use a stored credential, pass it where it is needed (a command, a header, an environment variable); "
            "don't write it into project files, commits or anything shared. "
            "action \"add\": remember one fact (`text`, one sentence). action \"replace\": fix a fact (`old` is the wrong one, `text` the "
            "correct one). action \"remove\": forget a fact (`old`). action \"list\": read the memory as it is now. "
            "Each fact is one line; keep them short and specific, and replace an outdated fact instead of adding a second one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "replace", "remove", "list"]},
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
        current = e.read_memory(project)
        items = facts(current)
        if action == "list":
            return ToolResult(text=show(current), metadata={"count": len(items), "action": action})
        if action not in ("add", "replace", "remove"):
            return ToolResult(text='action must be "add", "replace", "remove" or "list".', is_error=True)
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
