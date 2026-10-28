"""OpenCode's built-in system prompts, fetched from the open-source repo and cached on disk.

Source: https://github.com/anomalyco/opencode (branch ``dev``)
- harness prompt:  packages/core/src/session/runner/prompt/system.txt
                   (rendered by packages/core/src/session/system-prompt.ts, which fills
                   ``${OPENCODE_TOOL_GUIDANCE}`` from the tools available to the session)
- model prompts:   packages/core/src/plugin/system-prompt/*.txt, chosen by
                   packages/core/src/plugin/optimize.ts (rules replicated in ``pick_for_model``)
- identity block:  packages/core/src/plugin/identity.ts inserts "# Your Model" after the first part.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from . import store

REPO = "anomalyco/opencode"
BRANCH = "dev"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
HARNESS_PATH = "packages/core/src/session/runner/prompt/system.txt"
PROVIDER_DIR = "packages/core/src/plugin/system-prompt"
PROVIDER_LIST_URL = f"https://api.github.com/repos/{REPO}/contents/{PROVIDER_DIR}?ref={BRANCH}"
KNOWN_PROVIDER_KEYS = ("anthropic", "gpt", "gpt-astra", "kimi", "meta", "trinity")

CACHE_PATH = store.AFH_DIR / "cache" / "builtin-prompts.json"
MAX_AGE = 24 * 3600
TIMEOUT = 15.0
HEADERS = {"User-Agent": "agent-flow-harness", "Accept": "application/vnd.github+json, text/plain"}

TOOL_GUIDANCE_PLACEHOLDER = "${OPENCODE_TOOL_GUIDANCE}"
MODEL_NAME_PLACEHOLDER = "{{MODEL_NAME}}"

# Verbatim copy of system.txt (dev, 2026-10-28) used only when neither network nor cache is available.
FALLBACK_HARNESS = """You are an AI agent running in OpenCode, a coding agent harness. Help the user accomplish their goals using the tools you have available.

# Harness
- Responses are rendered as GitHub-flavored Markdown.
- `<system-reminder>` blocks are harness instructions, not user-authored content. Read and follow them.
- Prefer parallelizing independent tool calls.
${OPENCODE_TOOL_GUIDANCE}

# Communication
- Use clear file paths when referring to files.
- Keep responses clear and concise, and avoid unnecessary technical jargon.

# Working in codebases
- Keep changes consistent with the structure, naming, style, and patterns of the surrounding code.
- Treat unfamiliar files or changes as potential user work and investigate before deleting or overwriting them.
"""

# From packages/core/src/plugin/optimize.ts (dev). Every rule is a case-insensitive substring test on
# model.id only; provider and family are not consulted. Plugins run in this order and a later
# "override" replaces an earlier one; "append" adds to whatever system[0] currently is. A plugin does
# nothing when the agent has a custom `system` prompt, and `${OPENCODE_TOOL_GUIDANCE}` is filled by
# SessionSystemPrompt.render for whichever template wins.
SELECTION_RULES = [
    "Default: packages/core/src/session/runner/prompt/system.txt (key 'harness') is system[0] for every model.",
    "opencode.prompt.openai: if model.id contains 'gpt' -> override with gpt-astra.txt when it also contains 'astra', else gpt.txt.",
    "opencode.prompt.anthropic: if model.id contains 'claude' -> APPEND anthropic.txt to the current system[0] (harness + anthropic).",
    "opencode.prompt.kimi: if model.id contains 'kimi' -> override with kimi.txt.",
    "opencode.prompt.arcee: if model.id contains 'trinity' -> override with trinity.txt.",
    "opencode.prompt.meta: if model.id contains 'muse' -> override with meta.txt, replacing {{MODEL_NAME}} with model.name.",
    "Order: openai, anthropic, kimi, arcee, meta; all plugins run on the 'context', 'compaction' and 'generate' hooks.",
    "Skipped entirely when the agent defines its own `system` prompt.",
    "AFH extension (not in OpenCode): when no rule matches model.id, the same substrings are tried on family and provider_id.",
]

_lock = threading.RLock()


# --------------------------------------------------------------------------- fetch / cache


def _fetch_text(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _provider_keys() -> list[str]:
    """List system-prompt/*.txt via the GitHub API; fall back to the known names when rate limited/offline."""
    try:
        resp = httpx.get(PROVIDER_LIST_URL, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        names = [e["name"] for e in resp.json() if isinstance(e, dict) and e.get("type") == "file"]
        keys = sorted(n[:-4] for n in names if n.endswith(".txt"))
        if keys:
            return keys
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    return list(KNOWN_PROVIDER_KEYS)


def fetch_prompts() -> dict:
    """Download everything from GitHub (no cache). Raises httpx.HTTPError when offline."""
    harness = _fetch_text(RAW_BASE + HARNESS_PATH)
    providers: dict[str, str] = {}
    for key in _provider_keys():
        providers[key] = _fetch_text(f"{RAW_BASE}{PROVIDER_DIR}/{key}.txt")
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"https://github.com/{REPO}/tree/{BRANCH}",
        "harness": harness,
        "providers": providers,
        "selection_rules": list(SELECTION_RULES),
    }


def _read_cache() -> dict | None:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("harness"), str) or not isinstance(data.get("providers"), dict):
        return None
    return data


def _cache_age(data: dict) -> float:
    try:
        fetched = datetime.fromisoformat(data["fetchedAt"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return time.time() - fetched.timestamp()
    except (KeyError, TypeError, ValueError):
        return float("inf")


def _fallback() -> dict:
    return {
        "fetchedAt": None,
        "source": "bundled",
        "harness": FALLBACK_HARNESS,
        "providers": {},
        "selection_rules": list(SELECTION_RULES),
    }


def get_prompts(force: bool = False) -> dict:
    """Prompts from the 24h disk cache, else GitHub, else the stale cache, else the bundled fallback.

    The result always has keys fetchedAt, source, harness, providers, selection_rules, plus
    ``stale`` (True when an expired cache was served because the network failed).
    """
    with _lock:
        cached = _read_cache()
        if cached and not force and _cache_age(cached) < MAX_AGE:
            return {**cached, "selection_rules": list(SELECTION_RULES), "stale": False}
        try:
            fresh = fetch_prompts()
        except (httpx.HTTPError, ValueError) as exc:
            if cached:
                return {**cached, "selection_rules": list(SELECTION_RULES), "stale": True, "error": str(exc)}
            return {**_fallback(), "stale": True, "error": str(exc)}
        store._write_json(CACHE_PATH, fresh)
        return {**fresh, "stale": False}


# --------------------------------------------------------------------------- selection


def _match(haystack: str) -> str | None:
    """The optimize.ts rules, in plugin order; later overrides win, exactly as in OpenCode."""
    key: str | None = None
    if "gpt" in haystack:
        key = "gpt-astra" if "astra" in haystack else "gpt"
    if "claude" in haystack:
        key = "anthropic"  # append mode: harness text + anthropic.txt
    if "kimi" in haystack:
        key = "kimi"
    if "trinity" in haystack:
        key = "trinity"
    if "muse" in haystack:
        key = "meta"
    return key


def pick_for_model(provider_id: str, model_id: str, family: str | None = None, strict: bool = False) -> str:
    """Which prompt OpenCode uses: one of 'harness', 'gpt', 'gpt-astra', 'anthropic', 'kimi', 'trinity', 'meta'.

    Exact OpenCode behaviour (optimize.ts) looks only at model.id. With ``strict=False`` AFH also
    tries the family and provider id when the model id alone matches nothing, e.g.
    ('kimi-code-plan-global', 'k3.1-pro') -> 'kimi'.
    """
    key = _match((model_id or "").lower())
    if key is None and not strict:
        key = _match(f"{family or ''} {provider_id or ''}".lower())
    return key or "harness"


def render(template: str, tools: list[str] | tuple[str, ...] = ()) -> str:
    """Port of SessionSystemPrompt.render (packages/core/src/session/system-prompt.ts)."""
    instructions: list[str] = []
    if "shell" in tools:
        instructions += [
            "- Prefer dedicated tools over shell commands; fall back to the shell when a tool cannot do what you need.",
            "- Do not chain shell commands with separators like `echo \"====\";` or `printf '---'`; the output becomes noisy in a way that makes the user's side of the conversation worse.",
        ]
    if "write" in tools:
        instructions.append(
            "- Use the write tool to create files or completely replace their content. Prefer using the edit tool for targeted changes."
        )
    if "edit" in tools:
        instructions.append(
            "- Use the edit tool for targeted changes to existing text files. It replaces the exact text in `oldString` with `newString`, and the values must differ. By default, `oldString` must occur exactly once. If it occurs multiple times, include more surrounding context to make it unique or set `replaceAll` to true to replace every occurrence."
        )
    return template.replace(TOOL_GUIDANCE_PLACEHOLDER, "\n".join(instructions), 1)


def compose_for_model(
    provider_id: str,
    model_id: str,
    family: str | None = None,
    model_name: str | None = None,
    tools: list[str] | tuple[str, ...] = ("shell", "write", "edit"),
    prompts: dict | None = None,
) -> dict[str, Any]:
    """The system[0] text OpenCode would build for a model: {key, text, mode}."""
    prompts = prompts or get_prompts()
    key = pick_for_model(provider_id, model_id, family)
    harness = prompts.get("harness") or FALLBACK_HARNESS
    providers = prompts.get("providers") or {}
    if key == "harness":
        return {"key": key, "mode": "default", "text": render(harness, tools)}
    template = providers.get(key)
    if template is None:  # cache predates this provider file or offline fallback
        return {"key": key, "mode": "default", "text": render(harness, tools), "missing": key}
    if key == "anthropic":
        return {"key": key, "mode": "append", "text": render(harness, tools) + "\n\n" + render(template, tools)}
    if key == "meta":
        template = template.replace(MODEL_NAME_PLACEHOLDER, model_name or model_id)
    return {"key": key, "mode": "override", "text": render(template, tools)}
