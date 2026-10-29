"""Hooks: the user's own commands that run at fixed points of a run.

``settings.hooks`` is a list of ``{id, name, event, matcher, command, timeout, enabled}``:

* ``pre_tool``  — before a tool runs. Exit code 2 blocks the call; the hook's output tells the model why.
* ``post_tool`` — after a tool succeeded (e.g. format the file that was just written). Output, and any
  failure, is added to what the model sees from that tool.
* ``stop``      — when the agent is about to finish. Exit code 2 sends the output back to the model and
  the run continues (e.g. "tests fail: <output>"), at most ``STOP_ROUNDS`` times per run.

``matcher`` is a regular expression on the tool name (empty = every tool; ignored for ``stop``). The hook
gets a JSON payload on stdin and these environment variables: AFH_EVENT, AFH_TOOL, AFH_TOOL_INPUT (JSON),
AFH_FILES (changed/target files, separated by the OS path separator), AFH_SESSION_ID, AFH_PROJECT_DIR.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time

from .tools.shell import clean_clixml, kill_tree, spawn, truncate_output

log = logging.getLogger("afh.hooks")

EVENTS = ("pre_tool", "post_tool", "stop")
DEFAULT_TIMEOUT = 60
STOP_ROUNDS = 3
BLOCK_CODE = 2


def hooks_for(settings: dict | None, event_name: str, tool: str | None = None) -> list[dict]:
    out = []
    for h in (settings or {}).get("hooks") or []:
        if not isinstance(h, dict) or h.get("enabled") is False or h.get("event") != event_name or not str(h.get("command") or "").strip():
            continue
        matcher = str(h.get("matcher") or "").strip()
        if tool is not None and matcher and event_name != "stop":
            try:
                if not re.search(matcher, tool, re.IGNORECASE):
                    continue
            except re.error:
                continue
        out.append(h)
    return out


def files_of(tool_input: dict, result_files: list[str] | None = None) -> list[str]:
    files = list(result_files or [])
    for key in ("path", "filePath", "file_path", "file"):
        v = tool_input.get(key) if isinstance(tool_input, dict) else None
        if isinstance(v, str) and v and v not in files:
            files.append(v)
    return files


async def run_hook(hook: dict, payload: dict, cwd: str, shell_pref: str | None = None) -> dict:
    """Run one hook. Returns {name, code, output, ms, timedOut}."""
    command = str(hook.get("command") or "")
    env = {
        "AFH_EVENT": str(payload.get("event") or ""),
        "AFH_TOOL": str(payload.get("tool") or ""),
        "AFH_TOOL_INPUT": json.dumps(payload.get("input") or {}, ensure_ascii=False)[:30_000],
        "AFH_FILES": os.pathsep.join(payload.get("files") or []),
        "AFH_SESSION_ID": str(payload.get("sessionID") or ""),
        "AFH_PROJECT_DIR": cwd,
    }
    started = time.monotonic()
    timeout = float(hook.get("timeout") or DEFAULT_TIMEOUT)
    name = hook.get("name") or command.split()[0]
    try:
        proc = await spawn(command, cwd, shell_pref, stdin=subprocess.PIPE, env=env)
    except (FileNotFoundError, OSError) as e:
        return {"name": name, "code": -1, "output": f"could not start: {e}", "ms": 0, "timedOut": False}
    timed_out = False
    try:
        out, _ = await asyncio.wait_for(proc.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")), timeout)
    except asyncio.TimeoutError:
        timed_out = True
        await kill_tree(proc)
        out = b""
    text = clean_clixml(out.decode("utf-8", errors="replace")).replace("\r\n", "\n").strip()
    text, _ = truncate_output(text, 8000)
    code = proc.returncode if proc.returncode is not None else -1
    return {"name": name, "code": -2 if timed_out else code, "output": text or ("(timed out)" if timed_out else ""), "ms": int((time.monotonic() - started) * 1000), "timedOut": timed_out}


async def run_all(hooks: list[dict], payload: dict, cwd: str, shell_pref: str | None = None) -> list[dict]:
    results = []
    for h in hooks:  # in order: a formatter should finish before a linter reads the file
        try:
            results.append(await run_hook(h, payload, cwd, shell_pref))
        except Exception as err:  # a broken hook must never break the run
            log.warning("hook %s failed: %s", h.get("name"), err)
            results.append({"name": h.get("name") or "hook", "code": -1, "output": str(err), "ms": 0, "timedOut": False})
    return results
