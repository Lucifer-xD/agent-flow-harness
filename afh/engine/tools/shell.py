"""The `shell` tool: runs a command in the project folder through PowerShell (Windows) or bash.

Windows notes: the command goes to powershell.exe as ``-EncodedCommand`` (base64 UTF-16) because
``-Command <text>`` is re-parsed by the shell and mangles quotes. A small wrapper script forces
UTF-8 output and turns the command's real status into the process exit code. PowerShell writes its
own error stream as CLIXML when stderr is a pipe; ``clean_clixml`` turns that back into plain text.
"""

from __future__ import annotations

import asyncio
import base64
import html
import os
import re
import signal
import subprocess
import sys
import time

from afh.engine.types import ToolContext, ToolResult, ToolSpec
from afh.engine.tools.files import BaseTool, ToolError, int_arg, str_arg, require_writable

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
MAX_OUTPUT = 30_000
TRUNCATION_MARKER = "\n\n… (truncated) …\n\n"

_PS_WRAPPER = """[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ProgressPreference = 'SilentlyContinue'
{command}
$__afh_ok = $?
if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
if (-not $__afh_ok) {{ exit 1 }}
"""


def build_argv(command: str, shell_pref: str | None) -> list[str] | None:
    """argv for the platform shell, or None when the command must go through cmd.exe (see spawn)."""
    if not IS_WINDOWS:
        return ["bash", "-lc", command]
    if shell_pref == "cmd":
        return None
    exe = "pwsh" if shell_pref == "pwsh" else "powershell"
    script = _PS_WRAPPER.format(command=command)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    # Tools misbehave in a pipe: no pagers, no colour codes, UTF-8 from Python children.
    env.update({"NO_COLOR": "1", "TERM": "dumb", "PAGER": "cat", "GIT_PAGER": "cat", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    return env


async def spawn(command: str, cwd: str, shell_pref: str | None, *, stdin: int = subprocess.DEVNULL, env: dict[str, str] | None = None) -> asyncio.subprocess.Process:
    common = dict(cwd=cwd, env={**child_env(), **(env or {})}, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    argv = build_argv(command, shell_pref)
    if argv is None:
        # cmd.exe: let CreateProcess receive the line verbatim; chcp keeps the output UTF-8.
        return await asyncio.create_subprocess_shell(f"chcp 65001>nul & {command}", creationflags=CREATE_NO_WINDOW, **common)
    if IS_WINDOWS:
        return await asyncio.create_subprocess_exec(*argv, creationflags=CREATE_NO_WINDOW, **common)
    return await asyncio.create_subprocess_exec(*argv, start_new_session=True, **common)  # own process group for killpg


async def kill_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if IS_WINDOWS:
        try:
            killer = await asyncio.create_subprocess_exec("taskkill", "/T", "/F", "/PID", str(proc.pid), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            await asyncio.wait_for(killer.wait(), 10)
        except (OSError, asyncio.TimeoutError):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


_CLIXML_BLOCK = re.compile(r"<Objs [^>]*>(.*?)</Objs>", re.DOTALL)
_CLIXML_ITEM = re.compile(r'<S S="(\w+)">(.*?)</S>', re.DOTALL)
_CLIXML_ESC = re.compile(r"_x([0-9A-Fa-f]{4})_")
_PS_NOISE = re.compile(r"^\s*(At line:\d+|\+ )")


def clean_clixml(text: str) -> str:
    """PowerShell's error/warning stream arrives as CLIXML; turn it into the lines the user would see."""
    if "#< CLIXML" not in text and "<Objs " not in text:
        return text

    def render(block: re.Match) -> str:
        out = []
        for kind, raw in _CLIXML_ITEM.findall(block.group(1)):
            msg = html.unescape(_CLIXML_ESC.sub(lambda m: chr(int(m.group(1), 16)), raw)).rstrip()
            for line in msg.splitlines():
                if not line.strip() or _PS_NOISE.match(line):
                    continue
                out.append(f"WARNING: {line}" if kind.lower() == "warning" else line)
        return ("\n".join(out) + "\n") if out else ""

    text = text.replace("#< CLIXML\r\n", "").replace("#< CLIXML\n", "").replace("#< CLIXML", "")
    return _CLIXML_BLOCK.sub(render, text)


def truncate_output(text: str, limit: int = MAX_OUTPUT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    half = (limit - len(TRUNCATION_MARKER)) // 2
    return text[:half] + TRUNCATION_MARKER + text[-half:], True


class ShellTool(BaseTool):
    spec = ToolSpec(
        name="shell",
        description=(
            "Runs a command in the project folder and returns its combined stdout/stderr and exit code. On Windows "
            "the command runs in PowerShell (use PowerShell syntax: `;` to chain, `Get-ChildItem`, `$env:VAR`); on "
            "other systems in bash. Use it for builds, tests, git and package managers. Quote paths with spaces, "
            "pass non-interactive flags, and never start commands that wait for input. A normal command is killed when "
            "`timeout` seconds (default 120, max 600) elapse. For servers, watchers and anything that runs until stopped, "
            "set `background: true`: it starts a background job, returns its first output and a job id, and you check "
            "on it with the `jobs` tool. Output over 30000 characters is truncated in the middle. Prefer `read`, `glob` "
            "and `grep` for looking at files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command line to run."},
                "timeout": {"type": "integer", "description": f"Seconds before the command is killed (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT})."},
                "description": {"type": "string", "description": "One short sentence saying what the command does, shown to the user (e.g. 'Run the unit tests')."},
                "background": {"type": "boolean", "description": "Run as a background job (servers, watchers, long builds): returns right away with a job id. Default false."},
            },
            "required": ["command"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        require_writable(ctx)
        command = str_arg(input, "command").strip()
        if not command:
            raise ToolError("Missing required parameter 'command'.")
        timeout = min(MAX_TIMEOUT, max(1, int_arg(input, "timeout", DEFAULT_TIMEOUT)))
        description = str_arg(input, "description", required=False)
        background = bool(input.get("background"))
        await ctx.permissions.require("shell", [command], {"command": command, "description": description, **({"background": True} if background else {})})
        if background and ctx.jobs is not None:
            from afh.engine.jobs import START_WAIT, start_background

            return await start_background(ctx, command, description, START_WAIT)

        shell_pref = (ctx.settings or {}).get("shell")
        started = time.monotonic()
        try:
            proc = await spawn(command, ctx.directory, shell_pref)
        except FileNotFoundError as e:
            raise ToolError(f"Could not start the shell ({e}).") from None

        buf = bytearray()

        async def pump() -> None:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    return
                buf.extend(chunk)

        pump_task = asyncio.create_task(pump())
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await kill_tree(proc)
            await proc.wait()
        # A surviving grandchild could hold the pipe open; do not wait on it forever.
        try:
            await asyncio.wait_for(pump_task, 5)
        except asyncio.TimeoutError:
            pump_task.cancel()

        elapsed = time.monotonic() - started
        output = clean_clixml(buf.decode("utf-8", errors="replace")).replace("\r\n", "\n").strip()
        output, truncated = truncate_output(output)
        code = proc.returncode if proc.returncode is not None else -1
        text = output or "(no output)"
        if timed_out:
            text += f"\n[timed out after {timeout}s - the process tree was killed]"
        elif code != 0:
            text += f"\n[exit code: {code}]"
        return ToolResult(text=text, is_error=timed_out, truncated=truncated,
                          metadata={"command": command, "description": description, "exit_code": code, "timed_out": timed_out, "duration_ms": int(elapsed * 1000)})
