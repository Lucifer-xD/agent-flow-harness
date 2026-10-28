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
        "accent": "#7c6cff",
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
}

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
