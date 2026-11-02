"""System prompt assembly: the harness prompt, then mode rules, then everything contextual
(AGENTS.md files, personalization, skills, MCP instructions, environment)."""

from __future__ import annotations

import datetime as dt
import platform
import sys
from pathlib import Path

from .. import store


def _read(path: Path, limit: int = 40_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except OSError:
        return ""


def instruction_files(directory: str) -> list[tuple[str, str]]:
    """AGENTS.md from the global config dir, then from the project root up to the folder."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in [store.GLOBAL_AGENTS_MD, store.LEGACY_AGENTS_MD]:
        if str(p) not in seen and p.is_file() and (text := _read(p)):
            seen.add(str(p))
            found.append((str(p), text))
    d = Path(directory)
    chain = [d, *d.parents][:4]
    for folder in reversed(chain):
        for name in ("AGENTS.md", "CLAUDE.md"):
            p = folder / name
            if p.is_file() and (text := _read(p)):
                found.append((str(p), text))
                break
    return found


def harness_guide(tools: list[str], agents: list | None = None, agent=None) -> str:
    """What AFH itself can do for the model, written from the tools this thread really has, so the
    model uses goals, the to-do list, subagents, jobs and worktrees on its own, without being told."""
    have = set(tools)
    lines = ["# Your harness: Agent Flow Harness", "",
             "You run inside AFH, which gives you more than file and shell tools. Use these on your own judgment; the user does not have to ask for them."]
    if "goal" in have:
        lines.append("- **Goal** (`goal` tool): rarely needed. Do NOT set a goal for ordinary tasks - features, fixes, questions, multi-step "
                     "work - plan those with `todo` and just do them. Set one only when the user asks for a goal, or tells you to keep going on "
                     "your own until something is true (\"don't stop until the tests pass\", \"work on this overnight\"). While a goal is active, "
                     "AFH may send you back to work when you stop: if the goal turns out impossible, or you tried and keep failing the same way, "
                     "call `goal` with status \"blocked\" and explain - never retry the same thing over and over.")
    if "todo" in have:
        lines.append("- **To-do list** (`todo` tool): the user watches it live. Plan multi-step work there and keep it current, one item in progress at a time.")
    if "question" in have:
        lines.append("- **Questions** (`question` tool): when you are blocked on a choice only the user can make, pause and ask with `question` "
                     "instead of guessing or stopping - give each question 2-5 labelled options (recommended one first), set multiple where several "
                     "can apply. The user picks in a card and you get the answers back and keep going. Use it for decisions, not for facts you can "
                     "find in the code yourself, and not for permission to act.")
    if "subagent" in have:
        delegates = [a for a in agents or [] if getattr(a, "kind", "") == "delegate"]
        who = "; ".join(f"`{a.id}` ({a.name}): {a.description}" for a in delegates) or "none"
        lines.append("- **Subagents** (`subagent` tool): hand a self-contained task to another agent; it works in its own thread (the user can watch it) and "
                     f"reports back. Available: {who}. Use them for independent pieces of work - several `subagent` calls in ONE reply run at the same "
                     "time - for wide research that would flood your context, or when a delegate's job fits. The subagent cannot see this conversation: "
                     "give it a complete brief (goal, files, constraints, what to report). With `worktree: true` it works on its own git branch, so "
                     "parallel subagents never edit the same files; merge their branches with git afterwards. Check their work before you rely on it.")
    if "memory" in have:
        lines.append("- **Project memory** (`memory` tool): what you know about this project from earlier threads (see \"Project memory\" "
                     "below); every thread here starts with it, and the user sees and edits it from the Memory button. Read it before you start "
                     "and follow it. Save to it (action \"add\") the moment you learn something the next thread would otherwise have to "
                     "rediscover: when the user says \"remember\", \"always\", \"never\", \"from now on\" or corrects how you did something; "
                     "when you work out how to install, run, build or test the project; when a gotcha cost you time. When a fact is wrong or "
                     "outdated, fix it (\"replace\") or drop it (\"remove\"); \"list\" shows it as it is now. Before you finish a long task, "
                     "ask yourself whether you learned something worth keeping. One short, specific fact per line; never task progress "
                     "(that is the to-do list), nothing AGENTS.md already says. The memory is private and local - it stays on this "
                     "computer and AFH keeps it out of git - so it is safe for access tokens, API keys, logins and other credentials: "
                     "save them when the user gives them to you or you will need them again, and use the ones stored there when a task "
                     "calls for them. Keep them out of project files, commits and anything shared.")
    if "jobs" in have:
        lines.append("- **Background jobs**: start servers and watchers with `shell` and `background: true`, then `jobs` to read output, wait for a "
                     "line like \"ready\", and stop them when done.")
    if "browser" in have:
        lines.append("- **Browser** (`browser` tool): a real browser tab for this thread (in the AFH app, a side panel the user watches live and "
                     "can take over). After building or changing anything with a UI, open it (start the dev server as a background job first), look "
                     "at the screenshot, click through the change and read `console` for errors before you call it done. Use it for web tasks too. "
                     "Click by selector or visible text, or at x,y read off the latest screenshot. If the user takes the tab over, stop using it.")
    if "computer" in have:
        lines.append("- **Computer** (`computer` tool): see the screen and use the mouse and keyboard in desktop apps, for tasks with no "
                     "file, shell or web path. Prefer `edit`/`shell` for code and `browser` for the web; reach for `computer` only for GUI-only "
                     "work (a native app, a settings screen, a tool with no API). Ask for every app the task needs at once with `request_access` "
                     "(the user approves each app once; in Full access mode nothing asks). Screenshot, read it, act on x,y from that image; use `batch` when you can predict "
                     "several steps, `zoom` to read small text, and set `intent` to a few words so the user sees what each move does. When the "
                     "user asks HOW to do something, teach instead of doing it: `teach` one step at a time (text + x,y pointing at the control), "
                     "and wait for them to click Next. Never change the user's own open documents or tabs unless they asked: start a new "
                     "document (ctrl+n) for your own work. The user stops you with Esc.")
    if "harness" in have:
        lines.append("- **Extending AFH** (`harness` tool): when the user asks to install, add or remove a skill, an MCP server, a slash command, a hook "
                     "or a custom agent - a GitHub link, a repo, an npm/pip package, a URL - do it with `harness`, never by cloning into folders or "
                     "editing settings.json yourself (AFH would not pick it up). Skills install from any Git/GitHub link (`/tree/<branch>/<path>` "
                     "picks one folder); MCP servers connect immediately and their tools are yours on the next step. For an MCP server, read its "
                     "README first for the exact command and required environment variables, and ask the user for API keys you do not have. "
                     "After installing, confirm it worked (the skill is listed, the server is connected with tools) and tell the user; if a "
                     "server fails, read the error, fix the command and add it again. `harness` with action `list` shows everything installed.")
    lines.append("- **Error checks**: after you edit files, AFH checks them (syntax, types, lint) and appends any problems to the tool result. Fix them.")
    lines.append("- **Context**: long threads are summarised automatically and old tool outputs may be shortened. Re-run a tool if you need its full output again.")
    lines.append("- **The user's controls**: approval modes (some actions ask the user first), undo, context editing, hooks that may block a tool or "
                 "send you back to work, and spending limits. Respect a refusal and the message that comes with it.")
    if agent is not None and getattr(agent, "kind", "") == "delegate":
        lines = [l for l in lines if not l.startswith("- **Goal**")]
    return "\n".join(lines)


def build(*, agent_system: str, directory: str, skills_text: str = "", mcp_instructions: str = "", settings: dict | None = None, extra: str = "") -> str:
    s = settings or store.load_settings()
    parts = [agent_system.strip()]
    if extra.strip():
        parts.append(extra.strip())
    for path, text in instruction_files(directory):
        parts.append(f"# Instructions from {path}\n\n{text}")
    if s.get("personalization", {}).get("enabled", True):
        if not store.PERSONALIZATION_PATH.exists():
            store.write_personalization(s["personalization"])
        if text := _read(store.PERSONALIZATION_PATH):
            parts.append(text)
    if skills_text.strip():
        parts.append("# Skills\n\nLoad a skill with the `skill` tool when its description matches the task. Available skills (id · name · description):\n" + skills_text.strip())
    if mcp_instructions.strip():
        parts.append("# MCP servers\n\n" + mcp_instructions.strip())
    parts.append(
        "# Environment\n\n"
        f"- Working directory (the project): {directory}\n"
        f"- Platform: {platform.system()} {platform.release()} ({sys.platform}); shell for the `shell` tool: {'PowerShell' if sys.platform == 'win32' else 'bash'}\n"
        f"- Date: {dt.date.today().strftime('%A, %B %d, %Y')}\n"
        "- Paths may be absolute or relative to the working directory."
    )
    return "\n\n".join(parts)
