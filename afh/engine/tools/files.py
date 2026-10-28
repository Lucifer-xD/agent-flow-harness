"""File tools: read, write, edit, patch, glob, grep, list.

Path rules shared by every tool here (see ``resolve_path``):

* relative paths are resolved against ``ctx.directory`` and may not escape it with ``..``;
* absolute paths are allowed anywhere — the permission prompt shows the user the full path,
  which is the real protection.

Nothing is written before ``ctx.permissions.require(...)`` returned and the snapshot was recorded.
"""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from afh.engine.types import FileDiff, PermissionDenied, ToolContext, ToolResult, ToolSpec

# Directories no search tool descends into unless a path points straight at them.
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__"})

READ_DEFAULT_LIMIT = 2000
MAX_LINE_CHARS = 2000  # longer lines are clipped so one minified file cannot flood the context
GLOB_CAP = 200
GREP_DEFAULT_CAP = 100
GREP_LINE_CHARS = 500
LIST_CAP = 300
LIST_DEPTH = 2

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


class ToolError(Exception):
    """A failure the model should see as an error result (bad input, missing file...), not a crash."""


class BaseTool:
    """Turns ToolError/OS errors into ``ToolResult(is_error=True)``; PermissionDenied propagates."""

    spec: ToolSpec

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        try:
            return await self._run(ctx, input or {})
        except ToolError as e:
            return ToolResult(text=str(e), is_error=True)
        except (OSError, UnicodeError, ValueError) as e:
            return ToolResult(text=f"{type(e).__name__}: {e}", is_error=True)

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError


# ---- shared helpers ------------------------------------------------------------------


def project_root(ctx: ToolContext) -> Path:
    return Path(os.path.normpath(os.path.abspath(ctx.directory)))


def _inside(path: Path, base: Path) -> bool:
    a, b = os.path.normcase(str(path)), os.path.normcase(str(base))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def resolve_path(ctx: ToolContext, raw: str | None) -> Path:
    """Project-relative paths stay inside the project; absolute paths are taken as given."""
    base = project_root(ctx)
    raw = (raw or "").strip().strip('"')
    if not raw or raw == ".":
        return base
    if os.path.isabs(raw):
        return Path(os.path.normpath(raw))
    path = Path(os.path.normpath(os.path.join(str(base), raw)))
    if not _inside(path, base):
        raise ToolError(f"Path {raw!r} escapes the project directory ({base}). Use an absolute path if you really mean a file outside the project.")
    return path


def display_path(ctx: ToolContext, path: Path) -> str:
    """Project-relative with forward slashes when inside the project, else the absolute path."""
    base = project_root(ctx)
    if _inside(path, base):
        rel = os.path.relpath(str(path), str(base))
        return "." if rel == "." else rel.replace("\\", "/")
    return str(path)


def require_writable(ctx: ToolContext) -> None:
    if ctx.read_only:
        raise PermissionDenied("This session is read-only: file edits and shell commands are not allowed.")


def _is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def read_text_lenient(path: Path) -> str:
    """For display: decode as UTF-8, replacing undecodable bytes; drops a BOM."""
    data = path.read_bytes()
    if _is_binary(data):
        raise ToolError(f"{path} is a binary file and cannot be shown as text.")
    return data.decode("utf-8", errors="replace").lstrip("﻿")


def read_text_exact(path: Path) -> str:
    """For editing: the file must round-trip, so it has to be valid UTF-8 (a BOM is kept as a char)."""
    data = path.read_bytes()
    if _is_binary(data):
        raise ToolError(f"{path} is a binary file and cannot be edited as text.")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{path} is not valid UTF-8 text; use `write` to replace it entirely.") from None


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" keeps whatever line endings the content already has (CRLF files stay CRLF).
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def match_line_endings(old: str | None, new: str) -> str:
    """A CRLF file stays CRLF even when the model writes LF (it rarely sees the \r in a read result)."""
    if old and "\r\n" in old and "\r\n" not in new:
        return new.replace("\n", "\r\n")
    return new


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _diff_lines(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
        lines.append("\\ No newline at end of file\n")
    return lines


def make_diff(display: str, old: str | None, new: str | None) -> FileDiff:
    """Unified diff old→new with git-style a/ b/ headers; status from which side is missing."""
    old_lines = _diff_lines(old) if old is not None else []
    new_lines = _diff_lines(new) if new is not None else []
    patch = "".join(difflib.unified_diff(
        old_lines, new_lines,
        fromfile="/dev/null" if old is None else f"a/{display}",
        tofile="/dev/null" if new is None else f"b/{display}",
        n=3,
    ))
    body = [l for l in patch.splitlines() if not l.startswith(("---", "+++", "@@", "\\"))]
    status = "added" if old is None else "deleted" if new is None else "modified"
    return FileDiff(file=display, patch=patch, status=status,
                    additions=sum(1 for l in body if l.startswith("+")),
                    deletions=sum(1 for l in body if l.startswith("-")))


def _clip(line: str, limit: int = MAX_LINE_CHARS) -> str:
    return line if len(line) <= limit else line[:limit] + f"… (+{len(line) - limit} chars)"


def int_arg(input: dict, key: str, default: int) -> int:
    value = input.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(f"Parameter {key!r} must be an integer, got {value!r}.") from None


def str_arg(input: dict, key: str, required: bool = True) -> str:
    value = input.get(key)
    if value is None or (required and value == ""):
        if required:
            raise ToolError(f"Missing required parameter {key!r}.")
        return ""
    return value if isinstance(value, str) else str(value)


# ---- read ------------------------------------------------------------------------------


class ReadTool(BaseTool):
    spec = ToolSpec(
        name="read",
        description=(
            "Reads a file from the project (or anywhere, with an absolute path) and returns its lines prefixed "
            "with their 1-based line number, like `12: text`. Use `offset` and `limit` to page through large "
            "files; by default the first 2000 lines are returned and the result says how many lines the file has "
            "and whether the end was reached. Reading a directory lists its entries. Prefer this over shell "
            "`cat`/`type`, and read a file before editing it so your `edit` strings match exactly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File (or directory) to read. Relative paths are resolved against the project folder."},
                "offset": {"type": "integer", "description": "1-based line number to start from (default 1)."},
                "limit": {"type": "integer", "description": f"Maximum number of lines to return (default {READ_DEFAULT_LIMIT})."},
            },
            "required": ["path"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        path = resolve_path(ctx, str_arg(input, "path"))
        await ctx.permissions.require("read", [str(path)])
        if path.is_dir():
            entries = sorted(os.listdir(path), key=str.lower)
            lines = [f"{name}/" if (path / name).is_dir() else name for name in entries]
            text = f"Directory {display_path(ctx, path)} ({len(lines)} entries):\n" + "\n".join(f"  {l}" for l in lines)
            return ToolResult(text=text, metadata={"path": str(path), "directory": True, "entries": len(lines)})
        if not path.exists():
            raise ToolError(f"File not found: {path}")

        offset = max(1, int_arg(input, "offset", 1))
        limit = max(1, int_arg(input, "limit", READ_DEFAULT_LIMIT))
        text = await asyncio.to_thread(read_text_lenient, path)
        lines = text.splitlines()
        total = len(lines)
        if total == 0:
            return ToolResult(text="(Empty file)\n\n(End of file - 0 lines total)", metadata={"path": str(path), "total_lines": 0, "end": True})
        if offset > total:
            raise ToolError(f"offset {offset} is past the end of {display_path(ctx, path)} ({total} lines).")

        chunk = lines[offset - 1:offset - 1 + limit]
        last = offset + len(chunk) - 1
        out = [f"{offset + i}: {_clip(line)}" for i, line in enumerate(chunk)]
        end = last >= total
        if end:
            out.append(f"\n(End of file - {total} lines total)")
        else:
            out.append(f"\n(Showing lines {offset}-{last} of {total}. Call read again with offset={last + 1} to continue.)")
        return ToolResult(text="\n".join(out), truncated=not end,
                          metadata={"path": str(path), "total_lines": total, "offset": offset, "last": last, "end": end})


# ---- write -----------------------------------------------------------------------------


class WriteTool(BaseTool):
    spec = ToolSpec(
        name="write",
        description=(
            "Creates a file or replaces its whole content with `content`; parent folders are created as needed. "
            "Use it for new files or complete rewrites. For changes to an existing file prefer `edit`, which keeps "
            "the rest of the file intact and produces a smaller diff. Read a file before overwriting it. The user "
            "sees a diff and can refuse, and the previous content is snapshotted for undo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to write. Relative paths are resolved against the project folder."},
                "content": {"type": "string", "description": "The complete new content of the file."},
            },
            "required": ["path", "content"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        require_writable(ctx)
        path = resolve_path(ctx, str_arg(input, "path"))
        content = str_arg(input, "content", required=False)
        if path.is_dir():
            raise ToolError(f"{path} is a directory.")
        old = await asyncio.to_thread(read_text_exact_or_none, path)
        content = match_line_endings(old, content)
        display = display_path(ctx, path)
        diff = make_diff(display, old, content)

        await ctx.permissions.require("edit", [str(path)], {"files": [diff.to_dict()]})
        ctx.snapshots.record(str(path))
        await asyncio.to_thread(write_text, path, content)
        return ToolResult(text=f"Wrote {count_lines(content)} lines to {display}", files=[diff],
                          metadata={"path": str(path), "file": display, "status": diff.status, "diff": diff.patch})


def read_text_exact_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return read_text_exact(path)
    except ToolError:
        # Overwriting a binary/non-UTF-8 file is fine; the diff just cannot show the old side.
        return ""


# ---- edit ------------------------------------------------------------------------------


_WS_RUN = re.compile(r"[ \t]+")


def _loose_pattern(old: str) -> re.Pattern:
    """Regex that matches `old` ignoring indentation width, inner whitespace runs and trailing spaces."""
    parts = []
    for line in old.replace("\r\n", "\n").split("\n"):
        words = [re.escape(w) for w in _WS_RUN.split(line.strip()) if w]
        parts.append(r"[ \t]*" + r"[ \t]+".join(words) + r"[ \t]*")
    return re.compile(r"\r?\n".join(parts))


@dataclass
class _Match:
    start: int
    end: int


def find_matches(content: str, old: str) -> tuple[list[_Match], bool]:
    """Exact matches first; if none, whitespace-normalised ones. Returns (matches, was_loose)."""
    matches: list[_Match] = []
    pos = content.find(old)
    while pos != -1:
        matches.append(_Match(pos, pos + len(old)))
        pos = content.find(old, pos + len(old))
    if matches:
        return matches, False
    pattern = _loose_pattern(old)
    loose = [_Match(m.start(), m.end()) for m in pattern.finditer(content) if m.end() > m.start()]
    return loose, True


def _context(text: str, start: int, end: int, around: int = 3) -> str:
    first = text.count("\n", 0, start) + 1
    last = first + text.count("\n", start, end)
    lines = text.splitlines()
    lo, hi = max(1, first - around), min(len(lines), last + around)
    return "\n".join(f"{i}: {_clip(lines[i - 1])}" for i in range(lo, hi + 1))


class EditTool(BaseTool):
    spec = ToolSpec(
        name="edit",
        description=(
            "Replaces one exact occurrence of `oldString` with `newString` in a file. `oldString` must match the "
            "file text exactly (copy it from a `read` result, including indentation) and must be unique in the file "
            "- add surrounding lines to make it unique, or set `replaceAll` to change every occurrence. If no "
            "exact match exists a whitespace-tolerant match is tried (different indentation or spacing); if that "
            "also fails the tool reports it and you should read the file again. The user sees the diff and can "
            "refuse; the previous content is snapshotted for undo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to edit. Relative paths are resolved against the project folder."},
                "oldString": {"type": "string", "description": "The exact text to replace (unique in the file unless replaceAll is true)."},
                "newString": {"type": "string", "description": "The replacement text (must differ from oldString)."},
                "replaceAll": {"type": "boolean", "description": "Replace every occurrence of oldString instead of requiring a single match (default false)."},
            },
            "required": ["path", "oldString", "newString"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        require_writable(ctx)
        path = resolve_path(ctx, str_arg(input, "path"))
        old = str_arg(input, "oldString")
        new = str_arg(input, "newString", required=False)
        replace_all = bool(input.get("replaceAll", False))
        if old == new:
            raise ToolError("oldString and newString are identical; nothing to do.")
        if not path.is_file():
            raise ToolError(f"File not found: {path}")
        display = display_path(ctx, path)

        content = await asyncio.to_thread(read_text_exact, path)
        new = match_line_endings(content, new)
        matches, loose = find_matches(content, old)
        if not matches:
            raise ToolError(f"oldString not found in {display} — read the file again and copy the exact text.")
        if len(matches) > 1 and not replace_all:
            raise ToolError(f"oldString matches {len(matches)} places in {display}; include more surrounding lines to make it unique, or set replaceAll=true.")
        if not replace_all:
            matches = matches[:1]

        # Rebuild from the original spans so a loose match keeps the file's own indentation elsewhere.
        pieces, cursor = [], 0
        for m in matches:
            pieces.append(content[cursor:m.start])
            pieces.append(new)
            cursor = m.end
        pieces.append(content[cursor:])
        updated = "".join(pieces)
        diff = make_diff(display, content, updated)

        await ctx.permissions.require("edit", [str(path)], {"files": [diff.to_dict()]})
        ctx.snapshots.record(str(path))
        await asyncio.to_thread(write_text, path, updated)

        first = matches[0].start
        context = _context(updated, first, first + len(new))
        note = " (matched with normalised whitespace)" if loose else ""
        text = f"Edited {display}: {len(matches)} replacement{'s' if len(matches) != 1 else ''}{note}.\n\n{context}"
        return ToolResult(text=text, files=[diff],
                          metadata={"path": str(path), "file": display, "diff": diff.patch, "replacements": len(matches), "loose": loose})


# ---- patch -----------------------------------------------------------------------------


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    old_start: int
    lines: list[str] = field(default_factory=list)  # with their leading ' ', '-', '+' or '\'


@dataclass
class FilePatch:
    old_path: str | None  # None = new file
    new_path: str | None  # None = deleted
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


def _header_path(raw: str) -> str | None:
    raw = raw.strip().split("\t")[0].strip()
    if raw.strip('"') == "/dev/null" or not raw:
        return None
    raw = raw.strip('"')
    if raw[:2] in ("a/", "b/"):
        raw = raw[2:]
    return raw


def parse_patch(text: str) -> list[FilePatch]:
    """Parse a unified diff. Hunk line counts are not trusted (models miscount); hunks end at the next header."""
    lines = text.replace("\r\n", "\n").split("\n")
    files: list[FilePatch] = []
    current: FilePatch | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            current = FilePatch(_header_path(line[4:]), _header_path(lines[i + 1][4:]))
            files.append(current)
            i += 2
            continue
        m = _HUNK_RE.match(line)
        if m and current is not None:
            hunk = Hunk(int(m.group(1)))
            current.hunks.append(hunk)
            i += 1
            while i < len(lines):
                body = lines[i]
                if _HUNK_RE.match(body) or body.startswith("diff ") or (body.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")):
                    break
                if body == "":
                    # A blank context line that lost its leading space (common in model output); skip a trailing blank.
                    if i == len(lines) - 1:
                        i += 1
                        break
                    body = " "
                if body[0] not in " -+\\":
                    raise ToolError(f"Malformed patch line {i + 1}: {body[:80]!r} (hunk lines must start with ' ', '-', '+').")
                hunk.lines.append(body)
                i += 1
            continue
        i += 1
    if not files:
        raise ToolError("No file headers found in the patch. Expected '--- a/path' / '+++ b/path' lines followed by @@ hunks.")
    return files


def _locate(lines: list[str], before: list[str], guess: int) -> int | None:
    if not before:
        return min(max(guess, 0), len(lines))
    if 0 <= guess <= len(lines) - len(before) and lines[guess:guess + len(before)] == before:
        return guess
    hits = [i for i in range(len(lines) - len(before) + 1) if lines[i:i + len(before)] == before]
    return min(hits, key=lambda i: abs(i - guess)) if hits else None


def apply_file_patch(old_text: str | None, fp: FilePatch) -> str:
    """Apply the hunks with zero fuzz (context must match; the hunk may be found at another offset)."""
    text = (old_text or "").replace("\r\n", "\n")
    newline = "\r\n" if old_text and "\r\n" in old_text else "\n"
    trailing = text.endswith("\n") if text else True
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    if not text:
        lines = []

    out = lines[:]
    offset = 0
    for n, hunk in enumerate(fp.hunks, 1):
        body = [l for l in hunk.lines if l[0] != "\\"]
        before = [l[1:] for l in body if l[0] in " -"]
        after = [l[1:] for l in body if l[0] in " +"]
        # A zero-length old range names the line *before* the insertion, so no -1 there.
        guess = (hunk.old_start - 1 if before else hunk.old_start) + offset
        pos = _locate(out, before, guess)
        if pos is None:
            raise ToolError(f"Hunk {n} (@@ -{hunk.old_start} @@) for {fp.path} does not apply: the context lines were not found. Read the file and regenerate the patch.")
        out[pos:pos + len(before)] = after
        offset += len(after) - len(before)
        for idx, l in enumerate(hunk.lines):
            if l.startswith("\\") and idx > 0:
                trailing = hunk.lines[idx - 1][0] == "-"  # marker after a removed line: only the old side lacked it
    result = newline.join(out)
    return result + newline if trailing and out else result


class PatchTool(BaseTool):
    spec = ToolSpec(
        name="patch",
        description=(
            "Applies a unified diff (the `diff -u` / `git diff` format) that may change several files at once. "
            "Each file needs `--- a/path` and `+++ b/path` headers followed by `@@` hunks; use `/dev/null` as the "
            "old side to create a file or as the new side to delete one. Context lines must match the file "
            "exactly (no fuzz), though a hunk may apply at a shifted line number. For single-file changes `edit` "
            "is simpler and less error-prone. The user sees one diff per file and can refuse."
        ),
        parameters={
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "The unified diff text. Paths are relative to the project folder."},
            },
            "required": ["patch"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        require_writable(ctx)
        files = parse_patch(str_arg(input, "patch"))
        plan: list[tuple[Path, str | None, FileDiff]] = []
        for fp in files:
            path = resolve_path(ctx, fp.path)
            display = display_path(ctx, path)
            if fp.old_path is None:
                if path.exists():
                    raise ToolError(f"{display} already exists but the patch creates it (--- /dev/null).")
                old = None
            else:
                if not path.is_file():
                    raise ToolError(f"File not found: {display}")
                old = await asyncio.to_thread(read_text_exact, path)
            new = None if fp.new_path is None else apply_file_patch(old, fp)
            plan.append((path, new, make_diff(display, old, new)))

        await ctx.permissions.require("edit", [str(p) for p, _, _ in plan], {"files": [d.to_dict() for _, _, d in plan]})
        for path, new, diff in plan:
            ctx.snapshots.record(str(path))
            if new is None:
                path.unlink()
            else:
                await asyncio.to_thread(write_text, path, new)
        summary = "\n".join(f"  {d.status:<8} {d.file} (+{d.additions} -{d.deletions})" for _, _, d in plan)
        return ToolResult(text=f"Applied patch to {len(plan)} file{'s' if len(plan) != 1 else ''}:\n{summary}",
                          files=[d for _, _, d in plan], metadata={"files": [d.file for _, _, d in plan]})


# ---- glob ------------------------------------------------------------------------------


def glob_to_regex(pattern: str) -> re.Pattern:
    """Glob → regex with `**` spanning directories; `*` and `?` never cross a slash."""
    pattern = pattern.replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                if i < n and pattern[i] == "/":
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                cls = pattern[i + 1:j].replace("\\", "\\\\")
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                out.append(f"[{cls}]")
                i = j
        elif c == "{":
            j = pattern.find("}", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                out.append("(?:" + "|".join(re.escape(a) for a in pattern[i + 1:j].split(",")) + ")")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE if IS_WINDOWS else 0)


def _walk_files(root: Path):
    """os.walk with the skip list pruned; yields (abs_path, rel_path_with_slashes)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                yield full, os.path.relpath(full, root).replace("\\", "/")
            except ValueError:  # device names like `nul` live on their own "mount" on Windows
                continue


_GLOB_CHARS = frozenset("*?[{")


def split_literal_prefix(pattern: str) -> tuple[str, str]:
    """`src/lib/**/*.py` → (`src/lib`, `**/*.py`): the walk starts at the deepest literal folder."""
    parts = pattern.replace("\\", "/").split("/")
    i = 0
    while i < len(parts) - 1 and not (set(parts[i]) & _GLOB_CHARS):
        i += 1
    return "/".join(parts[:i]), "/".join(parts[i:])


def glob_files(root: Path, pattern: str, scan_cap: int = 20_000) -> list[tuple[float, str]]:
    regex = glob_to_regex(pattern)
    hits: list[tuple[float, str]] = []
    for full, rel in _walk_files(root):
        if regex.match(rel):
            try:
                hits.append((os.stat(full).st_mtime, full))
            except OSError:
                continue
            if len(hits) >= scan_cap:
                break
    hits.sort(key=lambda h: h[0], reverse=True)
    return hits


class GlobTool(BaseTool):
    spec = ToolSpec(
        name="glob",
        description=(
            "Finds files whose path matches a glob pattern, newest first. Use `**` to search subfolders "
            "(`**/*.py`, `src/**/*.test.ts`); a bare `*.md` only matches the top level of the searched folder. "
            ".git, node_modules, .venv and __pycache__ are skipped. Returns at most 200 paths and says when "
            "there are more - narrow the pattern or `path` in that case. Use `grep` to search file contents."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. `**/*.py` or `src/**/*.tsx`."},
                "path": {"type": "string", "description": "Folder to search in (default: the project folder)."},
            },
            "required": ["pattern"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        pattern = str_arg(input, "pattern").strip()
        if not pattern:
            raise ToolError("Missing required parameter 'pattern'.")
        prefix, pattern = split_literal_prefix(pattern)
        base = str_arg(input, "path", required=False)
        # An absolute prefix (or none) stands on its own; a relative one is joined to `path`.
        root = resolve_path(ctx, prefix if os.path.isabs(prefix) or not base else os.path.join(base, prefix)) if prefix else resolve_path(ctx, base)
        await ctx.permissions.require("read", [str(root)])
        if not root.is_dir():
            raise ToolError(f"Not a directory: {root}")
        hits = await asyncio.to_thread(glob_files, root, pattern)
        shown = [display_path(ctx, Path(p)) for _, p in hits[:GLOB_CAP]]
        if not shown:
            return ToolResult(text=f"No files match {pattern!r} under {display_path(ctx, root)}.", metadata={"count": 0})
        text = "\n".join(shown)
        if len(hits) > GLOB_CAP:
            text += f"\n(more… showing {GLOB_CAP} of {len(hits)} matches; narrow the pattern or path)"
        return ToolResult(text=text, truncated=len(hits) > GLOB_CAP, metadata={"count": len(hits), "shown": len(shown)})


# ---- grep ------------------------------------------------------------------------------


_RG_LINE = re.compile(r"^(.*?):(\d+):(.*)$")


def _include_matches(rel: str, include: str) -> bool:
    if not include:
        return True
    if "/" in include or "**" in include:
        return glob_to_regex(include).match(rel) is not None
    name = rel.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(name.lower() if IS_WINDOWS else name, include.lower() if IS_WINDOWS else include)


def grep_python(root: Path, pattern: str, include: str, cap: int) -> list[tuple[str, int, str]]:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ToolError(f"Invalid regular expression {pattern!r}: {e}") from None
    hits: list[tuple[str, int, str]] = []
    targets = [(str(root), root.name)] if root.is_file() else _walk_files(root)
    for full, rel in targets:
        if not _include_matches(rel, include):
            continue
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if _is_binary(data):
            continue
        for no, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                hits.append((full, no, line))
                if len(hits) > cap:
                    return hits
    return hits


async def grep_rg(rg: str, root: Path, pattern: str, include: str, cap: int) -> list[tuple[str, int, str]]:
    argv = [rg, "-n", "--no-heading", "--color", "never", "--hidden", "--max-columns", str(GREP_LINE_CHARS)]
    for d in sorted(SKIP_DIRS):
        argv += ["--glob", f"!{d}"]
    if include:
        argv += ["--glob", include]
    argv += ["-e", pattern, "--", str(root)]
    proc = await asyncio.create_subprocess_exec(*argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    out, err = await proc.communicate()
    if proc.returncode not in (0, 1):
        raise ToolError(f"rg failed: {err.decode('utf-8', errors='replace').strip()}")
    hits: list[tuple[str, int, str]] = []
    for raw in out.decode("utf-8", errors="replace").splitlines():
        m = _RG_LINE.match(raw)
        if m:
            hits.append((m.group(1), int(m.group(2)), m.group(3)))
            if len(hits) > cap:
                break
    return hits


class GrepTool(BaseTool):
    spec = ToolSpec(
        name="grep",
        description=(
            "Searches file contents with a regular expression and returns matching lines as `path:line: text`. "
            "Searches the whole project by default; restrict with `path` (a folder or a single file) and `include` "
            "(a filename glob like `*.py` or `src/**/*.ts`). Case-sensitive; use `(?i)` for case-insensitive "
            "search. Skips .git, node_modules, .venv, __pycache__ and binary files. Returns at most `maxResults` "
            "matches (default 100) and says when there are more. Use `glob` to find files by name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to search for (Rust/Python syntax; avoid lookaround)."},
                "path": {"type": "string", "description": "Folder or file to search (default: the project folder)."},
                "include": {"type": "string", "description": "Only search files matching this glob, e.g. `*.ts` or `**/*.test.py`."},
                "maxResults": {"type": "integer", "description": f"Maximum number of matching lines to return (default {GREP_DEFAULT_CAP})."},
            },
            "required": ["pattern"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        pattern = str_arg(input, "pattern")
        root = resolve_path(ctx, str_arg(input, "path", required=False))
        include = str_arg(input, "include", required=False).strip()
        cap = max(1, int_arg(input, "maxResults", GREP_DEFAULT_CAP))
        await ctx.permissions.require("read", [str(root)])
        if not root.exists():
            raise ToolError(f"Path not found: {root}")
        rg = shutil.which("rg")
        if rg:
            hits = await grep_rg(rg, root, pattern, include, cap)
            backend = "rg"
        else:
            hits = await asyncio.to_thread(grep_python, root, pattern, include, cap)
            backend = "python"
        more = len(hits) > cap
        hits = hits[:cap]
        if not hits:
            return ToolResult(text=f"No matches for {pattern!r}" + (f" in files matching {include!r}" if include else "") + f" under {display_path(ctx, root)}.", metadata={"count": 0, "backend": backend})
        lines = [f"{display_path(ctx, Path(p))}:{no}: {_clip(text.rstrip(), GREP_LINE_CHARS)}" for p, no, text in hits]
        text = "\n".join(lines)
        if more:
            text += f"\n(more… showing the first {cap} matches; narrow the pattern, path or include)"
        return ToolResult(text=text, truncated=more, metadata={"count": len(hits), "more": more, "backend": backend})


# ---- list ------------------------------------------------------------------------------


def build_tree(root: Path, depth: int = LIST_DEPTH, cap: int = LIST_CAP) -> tuple[list[str], int, bool]:
    lines: list[str] = []
    count = 0
    truncated = False

    def walk(folder: str, level: int) -> None:
        nonlocal count, truncated
        try:
            entries = sorted(os.scandir(folder), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for entry in entries:
            if count >= cap:
                truncated = True
                return
            count += 1
            indent = "  " * level
            if entry.is_dir():
                if entry.name in SKIP_DIRS:
                    lines.append(f"{indent}{entry.name}/ (not expanded)")
                else:
                    lines.append(f"{indent}{entry.name}/")
                    if level + 1 < depth:
                        walk(entry.path, level + 1)
            else:
                lines.append(f"{indent}{entry.name}")

    walk(str(root), 0)
    return lines, count, truncated


class ListTool(BaseTool):
    spec = ToolSpec(
        name="list",
        description=(
            "Shows a folder as a tree, two levels deep, folders first (names ending in `/`). .git, node_modules, "
            ".venv and __pycache__ are shown but not expanded. At most 300 entries are listed. Good for a first "
            "look at a project; use `glob` to find specific files and `read` to open them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder to list (default: the project folder)."},
            },
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        root = resolve_path(ctx, str_arg(input, "path", required=False))
        await ctx.permissions.require("read", [str(root)])
        if not root.is_dir():
            raise ToolError(f"Not a directory: {root}")
        lines, count, truncated = await asyncio.to_thread(build_tree, root)
        text = f"{root}\n" + "\n".join(f"  {l}" for l in lines)
        if truncated:
            text += f"\n(more… showing the first {LIST_CAP} entries; list a subfolder for the rest)"
        return ToolResult(text=text, truncated=truncated, metadata={"path": str(root), "entries": count})
