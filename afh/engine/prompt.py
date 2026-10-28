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
