"""Slash commands: saved prompts you run with ``/name args``.

Sources, later ones win on a name clash:
* AFH's built-ins (``/goal``, ``/compact``, ``/todo``…), handled by the engine or the UI;
* ``settings.commands``: ``[{name, description, prompt}]`` made in Settings → Commands;
* Markdown files: ``~/.afh/commands/*.md``, then the project's ``.afh/commands/*.md`` and
  ``.claude/commands/*.md`` (the file name is the command; optional ``---`` front matter with ``description``).

In a prompt, ``$ARGUMENTS`` is everything after the command and ``$1`` … ``$9`` are its words.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .. import store

NAME = re.compile(r"^[a-z0-9][a-z0-9_:-]{0,40}$")

BUILTINS = [
    {"name": "goal", "description": "Set the thread's goal; the agent keeps working until it is achieved", "args": "<what done looks like>", "builtin": True},
    {"name": "todo", "description": "Show the to-do list", "builtin": True},
    {"name": "memory", "description": "See and edit what the agent knows about this project", "builtin": True},
    {"name": "remember", "description": "Add something to the project memory", "args": "<fact>", "builtin": True},
    {"name": "compact", "description": "Summarise older messages now to free up context", "builtin": True},
    {"name": "jobs", "description": "Show background jobs (servers, watchers)", "builtin": True},
    {"name": "new", "description": "Start a new thread", "builtin": True},
    {"name": "cost", "description": "Show tokens and cost of this thread", "builtin": True},
]

DEFAULTS = [
    {"name": "review", "description": "Review the uncommitted changes for bugs and risks",
     "prompt": "Review the uncommitted changes in this repository (git diff, including untracked files). Look for bugs, edge cases, security problems and code that does not match the project's conventions. Report findings ordered by severity with file:line references. Do not change any files. $ARGUMENTS"},
    {"name": "fix-tests", "description": "Run the tests and fix what fails",
     "prompt": "Run the project's test suite. For every failing test, find the root cause and fix the code (not the test, unless the test itself is wrong). Re-run until everything passes, then summarise what was broken and what you changed. $ARGUMENTS"},
    {"name": "explain", "description": "Explain how a part of the code works",
     "prompt": "Explain how $ARGUMENTS works in this codebase: the entry points, the flow of data, the important files and functions (with file:line), and anything surprising. Read the code; do not guess."},
    {"name": "commit", "description": "Write a commit message and commit the changes",
     "prompt": "Look at the uncommitted changes (git status, git diff). Write a clear commit message in the style of this repository's recent commits (git log -10), then stage and commit the changes. Do not push. $ARGUMENTS"},
]


def _front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, text[end + 4:].lstrip("\n")


def _from_dir(folder: Path, source: str) -> list[dict]:
    out = []
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.md")):
        name = f.stem.lower()
        if not NAME.match(name):
            continue
        try:
            meta, body = _front_matter(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if body.strip():
            out.append({"name": name, "description": meta.get("description") or body.strip().splitlines()[0][:100], "prompt": body.strip(),
                        "args": meta.get("argument-hint") or meta.get("args") or "", "source": source, "path": str(f)})
    return out


def all_commands(directory: str | None, settings: dict | None = None) -> list[dict]:
    s = settings or store.load_settings()
    found: dict[str, dict] = {c["name"]: {**c, "source": "builtin"} for c in BUILTINS}
    saved = s.get("commands")
    for c in (DEFAULTS if saved is None else saved or []):
        if isinstance(c, dict) and NAME.match(str(c.get("name") or "")) and c.get("prompt") and c["name"] not in found:
            found[c["name"]] = {"name": c["name"], "description": c.get("description") or "", "prompt": c["prompt"], "args": c.get("args") or "", "source": "settings"}
    layers = [(store.AFH_DIR / "commands", "global")]
    if directory:
        layers += [(Path(directory) / ".claude" / "commands", "project"), (Path(directory) / ".afh" / "commands", "project")]
    for folder, source in layers:
        for c in _from_dir(folder, source):
            if c["name"] in found and found[c["name"]].get("builtin"):
                continue  # built-ins keep their meaning
            found[c["name"]] = c
    return sorted(found.values(), key=lambda c: (not c.get("builtin"), c["name"]))


def parse(text: str) -> tuple[str, str] | None:
    """`/name rest…` → (name, rest). None when the text is not a slash command."""
    m = re.match(r"^/([a-z0-9][a-z0-9_:-]{0,40})(?:\s+([\s\S]*))?$", text.strip(), re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or "").strip()


def expand(prompt: str, args: str) -> str:
    try:
        words = shlex.split(args, posix=True) if args else []
    except ValueError:
        words = args.split()
    out = prompt.replace("$ARGUMENTS", args)
    for i in range(9, 0, -1):
        out = out.replace(f"${i}", words[i - 1] if i <= len(words) else "")
    if "$ARGUMENTS" not in prompt and args and not re.search(r"\$\d", prompt):
        out = f"{out.rstrip()}\n\n{args}"
    return out.strip()
