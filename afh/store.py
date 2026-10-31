"""AFH's own files under ~/.afh: settings, prompts, personalization, instructions."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

HOME = Path.home()
AFH_DIR = Path(os.environ.get("AFH_HOME", HOME / ".afh"))
SETTINGS_PATH = AFH_DIR / "settings.json"
PERSONALIZATION_PATH = AFH_DIR / "personalization.md"
GLOBAL_AGENTS_MD = AFH_DIR / "AGENTS.md"
LEGACY_AGENTS_MD = HOME / ".config" / "opencode" / "AGENTS.md"

DEFAULT_SETTINGS: dict[str, Any] = {
    "projects": [],
    "lastProject": None,
    "defaultModel": None,  # {"providerID": ..., "id": ..., "variant": ...}
    "defaultAgent": "build",
    "defaultMode": "ask",  # ask | full | readonly
    "ui": {
        "theme": "system",  # system | dark | light  (light = the Paper preset)
        "preset": "sunset",  # sunset | midnight | forest | ocean | mono | custom
        "accent": "#ff6a2a",
        "bg": "#0f0d0c",
        "text": "#f1ede9",
        "font": "inter",  # inter | system | serif | mono
        "fontSize": 14,
        "radius": 12,
        "density": "comfortable",  # comfortable | compact
        "bubbles": "bubbles",  # bubbles | flat
        "showReasoning": True,
        "showMeta": True,  # model, tokens under replies
        "animations": True,
        "animSpeed": 1.0,
        "logoAnim": True,
        "themeTransition": "circle",  # circle | diamond | wipe | fade | blur | none
        "msgAnim": "rise",  # rise | fade | slide | pop | blur | none
        "glass": True,
        "customCss": "",
        "sendKey": "enter",  # enter | ctrl-enter
        "liveFiles": True,  # open the Live pane while the model writes/edits a file
        "chatWidth": 820,  # px, the conversation column (drag its edge to change)
        "language": "en",  # en | ar  (the interface; the conversation follows its own text)
        "direction": "auto",  # auto (from the language) | ltr | rtl
        "darkPreset": "sunset",  # your favourite theme of each mode, used by the dark/light switch
        "lightPreset": "paper",
        "sounds": True,
        "notify": True,
        "reopenLast": True,
        "confirmDelete": True,
    },
    "personalization": {
        "enabled": True,
        "name": "",
        "role": "",
        "about": "",
        "style": "balanced",  # concise | balanced | detailed
        "tone": "",
        "instructions": "",
    },
    # The harness system prompt (empty = DEFAULT_SYSTEM_PROMPT) and per-mode replacements.
    "prompts": {"system": "", "agents": {}},
    # Custom agents: {id: {name, description, mode, system, model, readonly, color}}
    "agents": {},
    # MCP servers: [{name, type: local|remote, command|url, environment|headers, disabled}]
    "mcp": {"servers": []},
    "migration": {},
    # Remote control: LAN listener (+ optional Cloudflare quick tunnel) behind a password.
    "remote": {"enabled": False, "port": 0, "passwordHash": "", "tunnel": "none"},
    # Delegate mode: a leader agent that hands work to these delegates (child sessions).
    "delegation": {
        "leaderInstructions": "",
        "delegates": [],  # {id, name, model: {providerID, id, variant}, job, system, enabled, readonly, color}
    },
    # The agent's browser tool (Chrome/Edge via DevTools): visible = show its window instead of headless.
    "browser": {"enabled": True, "visible": False, "path": ""},
    # The mic button: transcription provider ("" = Groq, then OpenAI), model and spoken language.
    "voice": {"provider": "", "model": "", "language": ""},
    # Desktop app updates: auto = download new versions in the background; feed = where to look.
    "updates": {"auto": True, "feed": ""},
    # The agent loop: steps per run, and whether an out-of-date to-do list sends it back to work once.
    "agent": {"maxSteps": 200, "todoNudge": True, "resumeOnRestart": True, "compactAt": 80},  # compactAt: % of the context window
    # Goals: autopilot keeps the agent going until it reports the goal achieved or blocked.
    "goals": {"autopilot": True, "maxTurns": 10, "auto": True},
    # Error checks after edits (see engine/diagnostics.py). commands: [{name, glob, command, timeout, enabled}]
    "diagnostics": {"enabled": True, "typescript": True, "ruff": True, "commands": []},
    # Hooks: [{id, name, event: pre_tool|post_tool|stop, matcher, command, timeout, enabled}]
    "hooks": [],
    # Spending limits in USD (0 = none).
    "budget": {"perThread": 0, "perDay": 0},
    # "commands" (slash commands) is left out on purpose: absent = AFH's starter commands.
}

LEADER_ID = "delegate"

# The one harness system prompt. It goes to every model in every mode. Users can edit it in Settings → Prompts.
DEFAULT_SYSTEM_PROMPT = """You are a coding agent running inside Agent Flow Harness (AFH), a desktop app that gives you tools to read, write and run code in the user's project folder. Help the user get real work done: understand the request, look at the actual code, make the change, verify it, and report plainly.

# How you work
- Start by understanding: read the relevant files, search the codebase (glob/grep), and check how things are already done before changing anything. Do not guess at file contents or APIs you can read.
- Plan briefly for non-trivial tasks, then act. Prefer small, focused changes that match the project's existing style, naming and conventions.
- Verify your work: run the tests, the build or the program when you can. Say exactly what you ran and what happened. Never claim something works without checking.
- When something fails, read the error, investigate the cause, fix it, and re-verify. Do not loop on the same failing action.
- If a request is ambiguous in a way that matters, ask one clear question; otherwise state your assumption and proceed.

# Tools
- Use `read` to look at files (not shell `cat`/`type`), with offsets for large files. Use `glob` to find files and `grep` to search contents.
- Use `edit` for targeted changes to existing files; use `write` only for new files or full rewrites, and read a file before overwriting it.
- Use `shell` to run commands, tests and builds. Quote paths with spaces. Prefer non-interactive flags; never start commands that wait for input.
- Start servers, watchers and other long-running commands with `shell` and `background: true`, then use `jobs` to read their output, wait for a "ready" line, and stop them when you are done.
- After you edit files AFH checks them (syntax, types, lint where available) and appends any problems to the tool result. Fix reported problems before moving on.
- Run independent tool calls in parallel when they don't depend on each other: several reads, searches or delegations in one reply run at the same time.

# To-do list
- For any task with three or more steps, or when the user lists several things, keep a to-do list with the `todo` tool. The user sees it live.
- Write concrete, checkable items. Keep exactly one item `in_progress`; mark it `completed` as soon as it is done, then start the next. Add items you discover; mark dropped ones `cancelled`.
- Never mark an item completed if it is partly done or its tests fail. Before you finish, make sure the list matches reality.
- Skip the list for a single quick change or a question.
- Load a skill with the `skill` tool when one matches the task. Use `webfetch`/`websearch` for documentation you don't have. Use the `subagent` tool only when an agent is configured for the job.

# Safety
- The user approves file changes and commands according to the thread's approval mode; respect every refusal and the message that comes with it.
- Never run destructive or irreversible commands (deleting folders, `git push --force`, `git reset --hard`, dropping data, mass renames) unless the user explicitly asked for that exact action.
- Never read, print or send secrets (API keys, tokens, passwords, .env contents) unless the task is specifically about them.
- Do not change files outside the project folder unless asked.

# Communication
- Answer in concise GitHub-flavored Markdown. Use code blocks for code, paths and commands. No filler, no restating the request, no emoji.
- Explain decisions when they matter; keep routine steps short. Reference files as `path:line`.
- When done, summarize what changed, what you verified, and anything left open. Report failures honestly.

Project instructions (AGENTS.md), the project memory, personalization, loaded skills and the environment description follow this prompt; they take precedence where they are more specific."""

PLAN_RULES = """

# Plan mode
You are in planning mode. Investigate the codebase as needed, but do not edit files or run commands that change anything. Produce a clear, ordered plan: what to change, where (files/functions), risks, and how to verify. End by asking the user to confirm before implementation."""


def system_prompt(settings: dict | None = None) -> str:
    s = settings or load_settings()
    return (s.get("prompts", {}).get("system") or "").strip() or DEFAULT_SYSTEM_PROMPT

LEADER_RULES = """
# Delegation

You are the **lead agent**. You plan, decide, talk to the user, and review results. You have delegate agents, each with a job. Delegates run in their own child session with their own model and report back to you.

{delegates}

Rules:
- When a task matches a delegate's job, hand it over with the `subagent` tool: `agent` = the delegate id, `description` = a short title, `prompt` = a complete, self-contained brief (goal, exact file paths, constraints, acceptance criteria, and what to report back). The delegate cannot see this conversation.
- To continue an earlier delegation with the same delegate, pass the `sessionID` it returned. Start a fresh delegation when the task is unrelated.
- Independent tasks can run at the same time: call `subagent` several times in ONE reply and the delegations run in parallel. When two of them may edit the same files, give each `worktree: true` so it works on its own branch, then merge the branches (git merge) and check the result.
- Use `background: true` only for independent work you do not need right away, and tell the user you did.
- When a delegate reports back, verify its work yourself (read the files, run the tests) before telling the user it is done. Fix small issues yourself; send bigger ones back to the delegate with precise feedback.
- Do the work yourself only when no delegate's job matches or the task is trivial.
- Tell the user, in one line, what you delegated and to whom. Never pretend delegated work is your own.
{extra}
"""

DELEGATE_PROMPT = """You are **{name}**, a delegate agent in Agent Flow Harness. Your job: {job}

A lead agent sends you tasks and reviews your work; you cannot see the user's conversation. Do exactly the brief you are given, in the project folder you are running in. Work carefully, test what you change, and finish with a short report: what you did, which files you changed, what you verified, and anything the lead must know (open questions, risks). Do not ask questions back unless the brief is impossible to act on — state your assumption and proceed.
{system}"""


def _model_string(m: dict | None) -> str | None:
    if not m or not m.get("providerID") or not m.get("id"):
        return None
    s = f"{m['providerID']}/{m['id']}"
    if m.get("variant") and m["variant"] != "default":
        s += f"#{m['variant']}"
    return s


def leader_prompt(delegates: list[dict], extra: str = "") -> str:
    lines = []
    for d in delegates:
        model = _model_string(d.get("model")) or "the thread's model"
        lines.append(f"- **{d.get('name') or d['id']}** (id: `{d['id']}`, model: {model}): {d.get('job', '').strip() or 'general tasks'}")
    rules = LEADER_RULES.format(delegates="\n".join(lines) or "- (no delegates configured yet — do the work yourself)", extra=extra.strip())
    return (system_prompt().strip() + "\n\n" + rules.strip()).strip()



STYLE_TEXT = {
    "concise": "Keep replies short and direct. Skip preamble and summaries unless asked.",
    "balanced": "Be clear and reasonably brief; explain decisions when they matter.",
    "detailed": "Give thorough explanations, walk through your reasoning, and mention trade-offs.",
}

_lock = threading.RLock()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(default)
    except json.JSONDecodeError:
        backup = path.with_suffix(path.suffix + ".corrupt")
        path.replace(backup)
        return copy.deepcopy(default)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _merge_defaults(data: dict, defaults: dict) -> dict:
    out = copy.deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_defaults(value, out[key])
        else:
            out[key] = value
    return out


def load_settings() -> dict:
    with _lock:
        return _merge_defaults(_read_json(SETTINGS_PATH, {}), DEFAULT_SETTINGS)


def save_settings(patch: dict) -> dict:
    with _lock:
        current = load_settings()
        merged = _merge_defaults(patch, current)
        _write_json(SETTINGS_PATH, merged)
        write_personalization(merged["personalization"])
        return merged


def replace_setting(key: str, value: Any) -> dict:
    """Set one top-level key outright; ``save_settings`` merges dicts, so it can never drop an entry."""
    with _lock:
        current = load_settings()
        current[key] = value
        _write_json(SETTINGS_PATH, current)
        return current





def write_personalization(p: dict) -> None:
    lines: list[str] = []
    if p.get("enabled"):
        if p.get("name"):
            lines.append(f"- The user's name is {p['name']}.")
        if p.get("role"):
            lines.append(f"- The user works as: {p['role']}.")
        if p.get("about"):
            lines.append(f"- About the user: {p['about'].strip()}")
        if p.get("style") in STYLE_TEXT:
            lines.append(f"- Response style: {STYLE_TEXT[p['style']]}")
        if p.get("tone"):
            lines.append(f"- Tone: {p['tone']}.")
    body = ""
    if lines:
        body = "# About the user (set in AFH)\n\n" + "\n".join(lines) + "\n"
    if p.get("enabled") and p.get("instructions", "").strip():
        body += "\n# Custom instructions (set in AFH)\n\n" + p["instructions"].strip() + "\n"
    PERSONALIZATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERSONALIZATION_PATH.write_text(body, encoding="utf-8")




def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def write_text_with_backup(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".afh-bak")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    path.write_text(text, encoding="utf-8")
