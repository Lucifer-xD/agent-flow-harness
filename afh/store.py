"""AFH's own files under ~/.afh.

AFH never edits the user's global opencode.json. Everything AFH changes
(agents, system prompts, MCP servers, plugins, providers) lives in an overlay
config that is passed to `opencode serve` through OPENCODE_CONFIG_CONTENT.
"""

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
OVERLAY_PATH = AFH_DIR / "config.json"
PERSONALIZATION_PATH = AFH_DIR / "personalization.md"
GLOBAL_AGENTS_MD = HOME / ".config" / "opencode" / "AGENTS.md"

DEFAULT_SETTINGS: dict[str, Any] = {
    "projects": [],
    "lastProject": None,
    "defaultModel": None,  # {"providerID": ..., "id": ..., "variant": ...}
    "defaultAgent": "build",
    "defaultMode": "ask",  # ask | full | readonly
    "ui": {
        "theme": "system",  # system | dark | light
        "accent": "#ff6a2a",
        "fontSize": 14,
        "density": "comfortable",  # comfortable | compact
        "showReasoning": True,
        "animations": True,
        "sendKey": "enter",  # enter | ctrl-enter
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
    # Remote control: LAN listener (+ optional Cloudflare quick tunnel) behind a password.
    "remote": {"enabled": False, "port": 0, "passwordHash": "", "tunnel": "none"},
    # Delegate mode: a leader agent that hands work to these delegates (each an OpenCode subagent).
    "delegation": {
        "leaderInstructions": "",
        "delegates": [],  # {id, name, model: {providerID, id, variant}, job, system, enabled, readonly, color}
        "managed": [],  # agent ids Astra wrote into the overlay, so they can be removed cleanly
    },
}

LEADER_ID = "delegate"

LEADER_RULES = """
# Delegation

You are the **lead agent**. You plan, decide, talk to the user, and review results. You have delegate agents, each with a job. Delegates run in their own child session with their own model and report back to you.

{delegates}

Rules:
- When a task matches a delegate's job, hand it over with the `subagent` tool: `agent` = the delegate id, `description` = a short title, `prompt` = a complete, self-contained brief (goal, exact file paths, constraints, acceptance criteria, and what to report back). The delegate cannot see this conversation.
- To continue an earlier delegation with the same delegate, pass the `sessionID` it returned. Start a fresh delegation when the task is unrelated.
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
    base = ""
    try:  # OpenCode's own harness prompt (rendered) keeps the tool guidance intact
        from . import builtin_prompts

        base = builtin_prompts.render(builtin_prompts.get_prompts().get("harness", "") or "", tools=("shell", "write", "edit"))
    except Exception:
        base = ""
    return (base.strip() + "\n\n" + rules.strip()).strip()


def apply_delegation(settings: dict) -> None:
    """Rewrite the delegate/leader agents in the overlay from settings['delegation']."""
    deleg = settings.get("delegation", {})
    delegates = [d for d in deleg.get("delegates", []) if d.get("id")]
    enabled = [d for d in delegates if d.get("enabled", True)]

    def apply(cfg: dict) -> None:
        agents = cfg.setdefault("agents", {})
        for old in deleg.get("managed", []) + [LEADER_ID]:
            agents.pop(old, None)
        for d in enabled:
            entry: dict = {
                "mode": "subagent",
                "description": d.get("job", "").strip() or f"Delegate agent {d.get('name') or d['id']}",
                "system": DELEGATE_PROMPT.format(name=d.get("name") or d["id"], job=d.get("job", "").strip() or "general tasks", system=("\n" + d["system"].strip()) if d.get("system", "").strip() else ""),
            }
            if model := _model_string(d.get("model")):
                entry["model"] = model
            if d.get("color"):
                entry["color"] = d["color"]
            if d.get("readonly"):
                entry["permissions"] = [
                    {"action": "edit", "resource": "*", "effect": "deny"},
                    {"action": "shell", "resource": "*", "effect": "deny"},
                ]
            agents[d["id"]] = entry
        agents[LEADER_ID] = {
            "mode": "primary",
            "description": "Leads the work and delegates tasks to your delegate models.",
            "system": leader_prompt(enabled, deleg.get("leaderInstructions", "")),
            "color": "#ff6a2a",
            "permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}]
            + [{"action": "subagent", "resource": d["id"], "effect": "allow"} for d in enabled],
        }

    update_overlay(apply)
    with _lock:
        current = load_settings()
        current["delegation"]["managed"] = [d["id"] for d in delegates]
        _write_json(SETTINGS_PATH, current)

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


def load_overlay() -> dict:
    with _lock:
        return _read_json(OVERLAY_PATH, {})


def save_overlay(data: dict) -> None:
    with _lock:
        _write_json(OVERLAY_PATH, data)


def update_overlay(fn) -> dict:
    """Apply fn(overlay) under the lock and persist the result."""
    with _lock:
        data = load_overlay()
        fn(data)
        save_overlay(data)
        return data


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


def server_config() -> dict:
    """The overlay handed to `opencode serve`, plus AFH's personalization file."""
    cfg = copy.deepcopy(load_overlay())
    if not PERSONALIZATION_PATH.exists():
        write_personalization(load_settings()["personalization"])
    instructions = list(cfg.get("instructions") or [])
    path = str(PERSONALIZATION_PATH)
    if path not in instructions:
        instructions.append(path)
    cfg["instructions"] = instructions
    return cfg


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
