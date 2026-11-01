"""Error checks after edits: once a step has changed files, AFH checks them and tells the model
about problems right away, so it fixes its own mistakes before the user sees them.

Built in, no setup:
* Python: syntax (in-process), plus ``ruff`` for undefined names when it is installed;
* JSON and TOML: parsed in-process;
* JavaScript: ``node --check``;
* TypeScript: the project's own ``tsc --noEmit`` when it has a tsconfig.json and TypeScript in node_modules;
* Go (``gofmt -e``), PHP (``php -l``), Ruby (``ruby -wc``).

Users add their own checks in settings: ``diagnostics.commands = [{"glob": "*.ts", "command": "npx eslint {files}"}]``.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .tools.shell import CREATE_NO_WINDOW, child_env, clean_clixml, kill_soon, kill_tree, spawn

MAX_REPORT = 4000
FAST_TIMEOUT = 20
TSC_TIMEOUT = 90
IS_WINDOWS = sys.platform == "win32"

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def settings_of(settings: dict | None) -> dict:
    d = (settings or {}).get("diagnostics") or {}
    return {"enabled": d.get("enabled", True), "typescript": d.get("typescript", True), "ruff": d.get("ruff", True), "commands": d.get("commands") or []}


async def _exec(argv: list[str], cwd: str, timeout: float) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                    stderr=subprocess.STDOUT, **({"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}))
    except (FileNotFoundError, OSError) as e:
        return -1, f"could not start {argv[0]}: {e}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        await kill_tree(proc)
        return -2, f"timed out after {timeout:.0f}s"
    except asyncio.CancelledError:
        kill_soon(proc)
        raise
    return proc.returncode or 0, out.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()


async def _shell(command: str, cwd: str, timeout: float, shell_pref: str | None) -> tuple[int, str]:
    proc = await spawn(command, cwd, shell_pref)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        await kill_tree(proc)
        return -2, f"timed out after {timeout:.0f}s"
    except asyncio.CancelledError:
        kill_soon(proc)
        raise
    return proc.returncode or 0, clean_clixml(out.decode("utf-8", errors="replace")).replace("\r\n", "\n").strip()


def _which(name: str, root: Path | None = None) -> str | None:
    """A project-local binary (node_modules/.bin) first, then PATH."""
    if root is not None:
        for folder in [root, *root.parents][:6]:
            for cand in ([f"{name}.cmd", f"{name}.exe", name] if IS_WINDOWS else [name]):
                p = folder / "node_modules" / ".bin" / cand
                if p.is_file():
                    return str(p)
    return shutil.which(name)


def _rel(path: str, root: str) -> str:
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path


def _find_up(start: Path, name: str, stop: Path) -> Path | None:
    for folder in [start, *start.parents]:
        if (folder / name).is_file():
            return folder
        if folder == stop or len(folder.parts) <= 1:
            break
    return None


# ---- checkers: each returns a list of problem lines (empty = clean) -------------------------


def _python_syntax(path: Path) -> list[str]:
    try:
        source = path.read_bytes()
        compile(source, str(path), "exec", dont_inherit=True)
    except SyntaxError as e:
        line = (e.text or "").rstrip()
        return [f"{path.name}:{e.lineno}:{e.offset or 0}: SyntaxError: {e.msg}" + (f"\n    {line}" if line else "")]
    except (OSError, ValueError) as e:
        return [f"{path.name}: {e}"]
    return []


def _json(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as e:
        return [f"{path.name}: {e}"]
    if path.name in ("tsconfig.json", "jsconfig.json") or path.suffix.lower() in (".jsonc",) or ".vscode" in path.parts:
        return []  # JSON with comments
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return [f"{path.name}:{e.lineno}:{e.colno}: invalid JSON: {e.msg}"]
    return []


def _toml(path: Path) -> list[str]:
    if tomllib is None:
        return []
    try:
        tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError, OSError) as e:
        return [f"{path.name}: invalid TOML: {e}"]
    return []


async def check_files(paths: list[str], directory: str, settings: dict | None = None) -> list[dict]:
    """Check the files a step changed. Returns [{checker, files, problems, ok, ms}] for checks that ran."""
    cfg = settings_of(settings)
    if not cfg["enabled"]:
        return []
    root = Path(directory)
    files = [Path(p) for p in dict.fromkeys(paths) if Path(p).is_file()]
    if not files:
        return []
    by_ext: dict[str, list[Path]] = {}
    for f in files:
        by_ext.setdefault(f.suffix.lower(), []).append(f)
    results: list[dict] = []
    tasks = []

    def add(checker: str, fs: list[Path], problems: list[str], started: float, note: str = "") -> None:
        results.append({"checker": checker, "files": [_rel(str(f), directory) for f in fs], "problems": problems, "ok": not problems,
                        "ms": int((time.monotonic() - started) * 1000), **({"note": note} if note else {})})

    # in-process checks
    t0 = time.monotonic()
    py = by_ext.get(".py", []) + by_ext.get(".pyw", [])
    if py:
        add("python syntax", py, [p for f in py for p in _python_syntax(f)], t0)
    js = [f for ext in (".json", ".jsonc") for f in by_ext.get(ext, [])]
    if js:
        add("json", js, [p for f in js for p in _json(f)], t0)
    if by_ext.get(".toml"):
        add("toml", by_ext[".toml"], [p for f in by_ext[".toml"] for p in _toml(f)], t0)

    # external tools (only when installed)
    async def ruff() -> None:
        exe = _which("ruff", root) if cfg["ruff"] else None
        clean = [f for f in py if not _python_syntax(f)]
        if not exe or not clean:
            return
        s = time.monotonic()
        code, out = await _exec([exe, "check", "--no-cache", "--output-format", "concise", "--select", "E9,F63,F7,F82", *[str(f) for f in clean]], directory, FAST_TIMEOUT)
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith(("Found ", "All checks passed", "[*]")) and ":" in l]
        if code in (0, 1):
            add("ruff (undefined names)", clean, [_shorten(l, directory) for l in lines], s)

    async def node() -> None:
        fs = [f for ext in (".js", ".mjs", ".cjs") for f in by_ext.get(ext, [])]
        exe = _which("node") if fs else None
        if not exe:
            return
        s = time.monotonic()
        problems = []
        for f in fs:
            code, out = await _exec([exe, "--check", str(f)], directory, FAST_TIMEOUT)
            if code not in (0, -1, -2):
                problems.append(_node_error(out, f, directory))
        add("node --check", fs, problems, s)

    async def tsc() -> None:
        fs = [f for ext in (".ts", ".tsx", ".mts", ".cts") for f in by_ext.get(ext, [])]
        if not fs or not cfg["typescript"]:
            return
        project = _find_up(fs[0].parent, "tsconfig.json", root)
        if project is None:
            return
        exe = _which("tsc", project)
        if not exe or "node_modules" not in exe:
            return  # only the project's own TypeScript, so versions match
        s = time.monotonic()
        argv = ["cmd.exe", "/c", exe, "--noEmit", "--pretty", "false", "-p", str(project)] if IS_WINDOWS and exe.endswith(".cmd") else [exe, "--noEmit", "--pretty", "false", "-p", str(project)]
        code, out = await _exec(argv, str(project), TSC_TIMEOUT)
        if code == -2:
            add("tsc", fs, [], s, note=out)
            return
        names = {_rel(str(f), str(project)) for f in fs}
        lines = [l for l in out.splitlines() if "error TS" in l and any(l.replace("\\", "/").startswith(n) for n in names)]
        others = sum(1 for l in out.splitlines() if "error TS" in l) - len(lines)
        add("tsc", fs, lines, s, note=f"{others} more error(s) in other files" if others > 0 else "")

    async def simple(checker: str, exts: tuple[str, ...], argv_for) -> None:
        fs = [f for ext in exts for f in by_ext.get(ext, [])]
        if not fs:
            return
        argv0 = argv_for(fs[0])[0]
        if not shutil.which(argv0):
            return
        s = time.monotonic()
        problems = []
        for f in fs:
            code, out = await _exec(argv_for(f), directory, FAST_TIMEOUT)
            if checker == "gofmt" and out.strip():
                problems.append(_shorten(out, directory))
            elif checker != "gofmt" and code not in (0, -1, -2):
                problems.append(_shorten(out, directory))
        add(checker, fs, problems, s)

    async def custom() -> None:
        shell_pref = (settings or {}).get("shell")
        for c in cfg["commands"]:
            if not isinstance(c, dict) or not c.get("command") or c.get("enabled") is False:
                continue
            globs = [g.strip() for g in str(c.get("glob") or "*").split(",") if g.strip()]
            fs = [f for f in files if any(fnmatch.fnmatch(f.name, g) or fnmatch.fnmatch(_rel(str(f), directory), g) for g in globs)]
            if not fs:
                continue
            quoted = " ".join(_quote(str(f)) for f in fs)
            command = str(c["command"]).replace("{files}", quoted).replace("{file}", _quote(str(fs[0])))
            s = time.monotonic()
            code, out = await _shell(command, directory, float(c.get("timeout") or 60), shell_pref)
            add(c.get("name") or command.split()[0], fs, [_shorten(out, directory) or f"exit code {code}"] if code != 0 else [], s)

    tasks = [ruff(), node(), tsc(), custom(),
             simple("gofmt", (".go",), lambda f: ["gofmt", "-e", "-l", str(f)]),
             simple("php -l", (".php",), lambda f: ["php", "-l", str(f)]),
             simple("ruby -wc", (".rb",), lambda f: ["ruby", "-wc", str(f)])]
    await asyncio.gather(*tasks, return_exceptions=True)
    return results


def _quote(s: str) -> str:
    return f'"{s}"' if IS_WINDOWS else shlex.quote(s)


def _shorten(text: str, directory: str) -> str:
    base = str(Path(directory))
    return text.replace(base + os.sep, "").replace(base.replace("\\", "/") + "/", "").strip()


def _node_error(out: str, f: Path, directory: str) -> str:
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("    at ") and not l.startswith("Node.js v")]
    return _shorten("\n".join(lines[:8]), directory)


def report(results: list[dict]) -> str:
    """Text appended to the model's tool result. Empty when nothing ran."""
    if not results:
        return ""
    bad = [r for r in results if r["problems"]]
    if not bad:
        checked = ", ".join(sorted({r["checker"] for r in results}))
        return f"\n\n[Checked after the edit with {checked}: no problems found.]"
    out = ["", "", "[Problems found after this edit - fix them before moving on:]"]
    for r in bad:
        out.append(f"{r['checker']}:")
        out.extend("  " + l.replace("\n", "\n  ") for l in r["problems"])
        if r.get("note"):
            out.append(f"  ({r['note']})")
    text = "\n".join(out)
    return text if len(text) <= MAX_REPORT else text[:MAX_REPORT] + "\n  … (more problems not shown)"


def summary(results: list[dict]) -> dict:
    problems = sum(len(r["problems"]) for r in results)
    return {"ran": [r["checker"] for r in results], "problems": problems, "ok": problems == 0,
            "details": [{k: r[k] for k in ("checker", "files", "problems", "ok", "ms") if k in r} for r in results]}
