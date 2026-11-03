"""The ``harness`` tool: the model installs and removes what extends AFH itself.

Skills (from any Git/GitHub link or a local folder), MCP servers, slash commands, hooks and
custom agents go exactly where the Settings screens put them, and take effect live: tools and
the system prompt are rebuilt every step, and a new MCP server is connected in place, so the
model can use what it installed on its very next step. Every change asks the user first
(it runs or fetches code, so it goes through the same approval as ``shell``).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from .. import store
from . import commands as cmdmod
from . import hooks as hookmod
from .skills import IGNORED_DIRS, SKILL_FILE, discover, split_frontmatter
from .types import PermissionDenied, ToolContext, ToolResult, ToolSpec, new_id

if TYPE_CHECKING:
    from .core import Engine

ACTIONS = ("list", "install_skill", "remove_skill", "add_mcp", "remove_mcp", "add_command", "remove_command",
           "add_hook", "remove_hook", "add_agent", "remove_agent")
SLUG = re.compile(r"[^a-z0-9_-]+")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$")
IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
FETCH_TIMEOUT = 180
MAX_SKILL_BYTES = 50 * 1024 * 1024


def slug(text: str) -> str:
    return SLUG.sub("-", text.strip().lower()).strip("-")[:60] or "skill"


# ---- skills ----------------------------------------------------------------------------------


def parse_source(source: str) -> dict:
    """``{"url", "ref", "path"}`` for a Git/GitHub link; ``{"local": Path}`` for a folder on disk.

    GitHub links may point inside the repo (``/tree/<ref>/<path>`` or ``/blob/<ref>/<path>/SKILL.md``);
    ``owner/repo`` alone means GitHub."""
    raw = source.strip()
    local = Path(raw).expanduser()
    if raw and local.exists():
        return {"local": local}
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:/(?:tree|blob)/([^/\s]+)(?:/(.*))?)?/?(?:[#?].*)?$", raw)
    if m:
        owner, repo, ref, path = m.groups()
        path = (path or "").strip("/")
        if path.endswith(SKILL_FILE):
            path = path[: -len(SKILL_FILE)].strip("/")
        return {"url": f"https://github.com/{owner}/{repo}.git", "ref": ref or "", "path": path, "github": f"{owner}/{repo}"}
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", raw):
        return {"url": f"https://github.com/{raw.removesuffix('.git')}.git", "ref": "", "path": "", "github": raw.removesuffix(".git")}
    if re.match(r"^(https?://|git@|ssh://)", raw):
        return {"url": raw, "ref": "", "path": ""}
    raise ValueError(f"Not a Git/GitHub link or an existing folder: {source}")


async def _git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec("git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), FETCH_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, f"git {args[0]} timed out after {FETCH_TIMEOUT}s"
    return proc.returncode or 0, out.decode("utf-8", errors="replace").strip()


async def fetch(src: dict, into: Path) -> Path:
    """Download the repository into ``into`` (git when installed, else GitHub's zip); returns its root."""
    if shutil.which("git"):
        dest = into / "repo"
        args = ["clone", "--depth", "1", "--quiet"] + (["--branch", src["ref"]] if src["ref"] else []) + [src["url"], str(dest)]
        code, out = await _git(*args)
        if code != 0 and src["ref"]:  # a commit sha, or a branch name with slashes: clone fully, then check it out
            if dest.exists():
                rmtree(dest)
            code, out = await _git("clone", "--quiet", src["url"], str(dest))
            if code == 0:
                code, out = await _git("checkout", "--quiet", src["ref"], cwd=str(dest))
        if code == 0:
            return dest
        if not src.get("github"):
            raise RuntimeError(f"git clone failed: {out[-800:]}")
    if not src.get("github"):
        raise RuntimeError("git is not installed, and only GitHub links can be downloaded without it")
    url = f"https://codeload.github.com/{src['github']}/zip/{src['ref'] or 'HEAD'}"
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"Downloading {url} failed: HTTP {resp.status_code}")
    dest = into / "zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise RuntimeError(f"unsafe path in archive: {member}")
        zf.extractall(dest)
    tops = [p for p in dest.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else dest


def find_skills(root: Path) -> list[Path]:
    """Folders under ``root`` (itself included) that hold a SKILL.md, outermost first."""
    found: list[Path] = []
    for path in sorted(root.rglob(SKILL_FILE), key=lambda p: (len(p.parts), str(p))):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        folder = path.parent
        if not any(folder != f and f in folder.parents for f in found):  # a skill's own sub-skills ride along
            found.append(folder)
    return found


def rmtree(path: Path) -> None:
    """``shutil.rmtree`` that also clears read-only files (a cloned skill's .git on Windows)."""
    def unlock(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=unlock)


def _size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file() and not any(p in IGNORED_DIRS for p in f.relative_to(folder).parts))


def skills_dir(scope: str, directory: str) -> Path:
    return store.AFH_DIR / "skills" if scope != "project" else Path(directory) / ".afh" / "skills"


async def install_skill(source: str, scope: str, directory: str, only: list[str] | None = None, name: str = "") -> dict:
    src = parse_source(source)
    target_root = skills_dir(scope, directory)
    with tempfile.TemporaryDirectory(prefix="afh-skill-", ignore_cleanup_errors=True) as tmp:  # git packs are read-only on Windows
        base = src["local"] if "local" in src else await fetch(src, Path(tmp))
        start = (base / src["path"]) if src.get("path") else base
        if not start.exists():
            raise ValueError(f"'{src['path']}' does not exist in that repository")
        folders = find_skills(start)
        if not folders:
            raise ValueError("No SKILL.md found there. A skill is a folder with a SKILL.md that starts with --- name / description --- front matter.")
        wanted = {slug(o) for o in only or []}
        installed, skipped = [], []
        for folder in folders:
            meta, _ = split_frontmatter((folder / SKILL_FILE).read_text(encoding="utf-8", errors="replace"))
            label = str(meta.get("name") or folder.name)
            if wanted and slug(label) not in wanted and slug(folder.name) not in wanted:
                continue
            if not meta.get("name") or not meta.get("description"):
                skipped.append({"folder": folder.name, "reason": "SKILL.md has no name/description front matter"})
                continue
            if _size(folder) > MAX_SKILL_BYTES:
                skipped.append({"folder": folder.name, "reason": "larger than 50 MB"})
                continue
            dest = target_root / slug(name if name and len(folders) == 1 else label)
            target_root.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                rmtree(dest)
            shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
            (dest / ".afh-source.json").write_text(json.dumps({"source": source, "path": str(folder.relative_to(base).as_posix())}), encoding="utf-8")
            installed.append({"name": label, "path": str(dest)})
        if wanted and not installed and not skipped:
            raise ValueError(f"None of {sorted(wanted)} found. Skills there: " + ", ".join(f.name for f in folders))
    ids = {s.dir: s.id for s in discover(directory, store.AFH_DIR)}
    for item in installed:
        item["id"] = ids.get(item["path"], "")
    return {"installed": installed, "skipped": skipped}


def remove_skill(name: str, directory: str) -> str:
    """Delete an installed skill folder (by id or name) from any skills folder AFH reads."""
    for s in discover(directory, store.AFH_DIR):
        if name in (s.id, s.name, Path(s.dir).name):
            rmtree(Path(s.dir))
            return s.dir
    raise ValueError(f"No installed skill called '{name}'")


# ---- MCP -------------------------------------------------------------------------------------


def mcp_entry(body: dict) -> dict:
    """The settings entry for an MCP server, validated the same way as Settings → MCP."""
    name = str(body.get("name") or "").strip()
    if not NAME.match(name):
        raise ValueError("MCP server name may use letters, numbers, - _ . (max 61)")
    kind = "remote" if body.get("url") and not body.get("command") else str(body.get("type") or "local")
    if kind == "remote":
        url = str(body.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("Remote MCP servers need an http(s) url")
        entry: dict[str, Any] = {"name": name, "type": "remote", "url": url}
        if body.get("headers"):
            entry["headers"] = {str(k): str(v) for k, v in dict(body["headers"]).items()}
        return entry
    command = body.get("command")
    if isinstance(command, str):
        import shlex
        command = shlex.split(command, posix=False)
    command = [str(p).strip('"') for p in command or [] if str(p).strip()]
    if not command:
        raise ValueError("Local MCP servers need a command, e.g. [\"npx\", \"-y\", \"@scope/server\"]")
    entry = {"name": name, "type": "local", "command": command}
    if body.get("environment"):
        entry["environment"] = {str(k): str(v) for k, v in dict(body["environment"]).items()}
    if body.get("cwd"):
        entry["cwd"] = str(body["cwd"])
    return entry


def _masked(entry: dict) -> str:
    """What the approval card shows: the command or URL, with secret values hidden."""
    what = " ".join(entry["command"]) if entry.get("command") else entry.get("url", "")
    secrets = {**entry.get("environment", {}), **entry.get("headers", {})}
    return what + "".join(f"\n{k}=••••" for k in secrets)


# ---- the tool --------------------------------------------------------------------------------


class HarnessTool:
    spec = ToolSpec(
        name="harness",
        description=(
            "Install, add or remove what extends AFH itself: skills, MCP servers, slash commands, hooks and custom agents. "
            "Use this - not shell or file edits - whenever the user asks to install/add/remove any of these (a GitHub link, a repo, "
            "an npm/pip MCP package, a URL) or asks what is installed. Changes take effect on your next step, no restart.\n"
            "Actions:\n"
            "- list: everything installed (skills, MCP servers with status, commands, hooks, agents).\n"
            "- install_skill: source = GitHub/Git URL (a /tree/<branch>/<path> link picks one folder), owner/repo, or a local folder; "
            "scope = global (all projects, default) or project; only = names to pick from a repo with many skills; name = folder name override.\n"
            "- remove_skill: name.\n"
            "- add_mcp: name; local servers: command (array, e.g. [\"npx\",\"-y\",\"@modelcontextprotocol/server-github\"]), environment {KEY: value}, cwd; "
            "remote servers: url, headers {}. It connects right away and reports the tools or the startup error. Read the server's README for the right "
            "command and required env vars; ask the user for keys you do not have.\n"
            "- remove_mcp: name.\n"
            "- add_command: name, prompt ($ARGUMENTS = what the user types after /name), description, scope.\n"
            "- remove_command: name.\n"
            "- add_hook: name, event (pre_tool | post_tool | stop), command, matcher (regex on tool names), timeout.\n"
            "- remove_hook: name.\n"
            "- add_agent: id, name, description, system (its instructions), model (\"provider/model\"), readonly.\n"
            "- remove_agent: id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS)},
                "source": {"type": "string", "description": "install_skill: GitHub/Git URL, owner/repo, or a local folder"},
                "scope": {"type": "string", "enum": ["global", "project"], "description": "global (default) or this project only"},
                "only": {"type": "array", "items": {"type": "string"}, "description": "install_skill: which skills to take from a repo that has several"},
                "name": {"type": "string"},
                "id": {"type": "string"},
                "type": {"type": "string", "enum": ["local", "remote"]},
                "command": {"description": "add_mcp: argv array (or a string); add_hook: a shell command", "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
                "url": {"type": "string"},
                "environment": {"type": "object", "additionalProperties": {"type": "string"}},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "cwd": {"type": "string"},
                "prompt": {"type": "string"},
                "description": {"type": "string"},
                "event": {"type": "string", "enum": list(hookmod.EVENTS)},
                "matcher": {"type": "string"},
                "timeout": {"type": "number"},
                "system": {"type": "string"},
                "model": {"type": "string"},
                "readonly": {"type": "boolean"},
            },
            "required": ["action"],
        },
    )

    def __init__(self, engine: "Engine"):
        self.engine = engine

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        action = str(input.get("action") or "")
        if action not in ACTIONS:
            return ToolResult(text=f"Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}", is_error=True)
        try:
            if action == "list":
                return ToolResult(text=self.listing(ctx.directory), metadata={"action": action})
            return await getattr(self, action)(ctx, input)
        except PermissionDenied:
            raise
        except (ValueError, RuntimeError, OSError, KeyError) as err:
            return ToolResult(text=f"{action} failed: {err}", is_error=True, metadata={"action": action})

    async def _ask(self, ctx: ToolContext, title: str, what: str, resource: str) -> None:
        # Installing fetches or runs code, so it is approved like a shell command (and denied in read-only threads).
        await ctx.permissions.require("shell", [resource], {"title": title, "command": what})

    def _changed(self, kind: str) -> None:
        self.engine.publish({"type": kind, "data": {}})

    # -- skills --

    async def install_skill(self, ctx: ToolContext, input: dict) -> ToolResult:
        source = str(input.get("source") or "").strip()
        if not source:
            raise ValueError("source is required (a GitHub/Git URL, owner/repo or a folder)")
        scope = "project" if input.get("scope") == "project" else "global"
        await self._ask(ctx, "Install a skill?", f"{source}\n→ {skills_dir(scope, ctx.directory)}", f"install skill {source}")
        out = await install_skill(source, scope, ctx.directory, input.get("only") or None, str(input.get("name") or ""))
        self._changed("skills.changed")
        lines = [f"Installed {len(out['installed'])} skill(s) ({scope}):"] + [f"- `{s['id'] or s['name']}` → {s['path']}" for s in out["installed"]]
        lines += [f"Skipped {s['folder']}: {s['reason']}" for s in out["skipped"]]
        if out["installed"]:
            lines.append("They are in your skill list from the next step on; load one with the `skill` tool.")
        return ToolResult(text="\n".join(lines), metadata={"action": "install_skill", **out}, is_error=not out["installed"])

    async def remove_skill(self, ctx: ToolContext, input: dict) -> ToolResult:
        name = str(input.get("name") or input.get("id") or "").strip()
        await self._ask(ctx, "Remove a skill?", name, f"remove skill {name}")
        path = remove_skill(name, ctx.directory)
        self._changed("skills.changed")
        return ToolResult(text=f"Removed skill '{name}' ({path}).", metadata={"action": "remove_skill", "path": path})

    # -- MCP --

    async def add_mcp(self, ctx: ToolContext, input: dict) -> ToolResult:
        entry = mcp_entry(input)
        await self._ask(ctx, f"Add MCP server '{entry['name']}'?", _masked(entry), f"mcp {entry['name']}")
        servers = [s for s in (store.load_settings().get("mcp") or {}).get("servers", []) if isinstance(s, dict) and s.get("name") != entry["name"]]
        store.save_settings({"mcp": {"servers": [*servers, entry]}})
        e = self.engine
        if e.mcp is None:
            await e.start_mcp()
            status = next((s for s in e.mcp.status() if s["name"] == entry["name"]), {"status": "pending"})
        else:
            status = await e.mcp.add(entry)
            self._changed("mcp.status.changed")
        tools = e.mcp.tool_names(entry["name"]) if e.mcp else []
        if status.get("status") == "connected":
            text = f"MCP server '{entry['name']}' is connected with {len(tools)} tool(s): {', '.join(tools) or 'none'}. You can call them from your next step."
            return ToolResult(text=text, metadata={"action": "add_mcp", "status": status, "tools": tools})
        text = (f"MCP server '{entry['name']}' was saved but did not start: {status.get('error') or status.get('status')}.\n"
                "Fix the command/url/environment and call add_mcp again with the same name (it replaces the entry), or remove_mcp it.")
        return ToolResult(text=text, metadata={"action": "add_mcp", "status": status}, is_error=True)

    async def remove_mcp(self, ctx: ToolContext, input: dict) -> ToolResult:
        name = str(input.get("name") or "").strip()
        servers = [s for s in (store.load_settings().get("mcp") or {}).get("servers", []) if isinstance(s, dict)]
        if not any(s.get("name") == name for s in servers):
            raise ValueError(f"No MCP server called '{name}'")
        await self._ask(ctx, f"Remove MCP server '{name}'?", name, f"mcp {name}")
        store.save_settings({"mcp": {"servers": [s for s in servers if s.get("name") != name]}})
        if self.engine.mcp:
            await self.engine.mcp.remove(name)
        self._changed("mcp.status.changed")
        return ToolResult(text=f"Removed MCP server '{name}'.", metadata={"action": "remove_mcp"})

    # -- commands --

    def _commands_dir(self, scope: str, directory: str) -> Path:
        return Path(directory) / ".afh" / "commands" if scope == "project" else store.AFH_DIR / "commands"

    async def add_command(self, ctx: ToolContext, input: dict) -> ToolResult:
        name = str(input.get("name") or "").strip().lstrip("/").lower()
        prompt = str(input.get("prompt") or "").strip()
        if not cmdmod.NAME.match(name) or any(c["name"] == name for c in cmdmod.BUILTINS):
            raise ValueError("Command name must be lowercase letters, numbers, - _ : and not a built-in (goal, todo, compact, jobs, new, cost)")
        if not prompt:
            raise ValueError("prompt is required")
        path = self._commands_dir(str(input.get("scope") or "global"), ctx.directory) / f"{name}.md"
        desc = " ".join(str(input.get("description") or "").split())
        await self._ask(ctx, f"Add the /{name} command?", f"{path}\n\n{prompt}", f"command {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((f"---\ndescription: {desc}\n---\n\n" if desc else "") + prompt + "\n", encoding="utf-8")
        self._changed("commands.changed")
        return ToolResult(text=f"Added /{name} ({path}). The user can run it from the message box now.", metadata={"action": "add_command", "path": str(path)})

    async def remove_command(self, ctx: ToolContext, input: dict) -> ToolResult:
        name = str(input.get("name") or "").strip().lstrip("/").lower()
        found = next((c for c in cmdmod.all_commands(ctx.directory) if c["name"] == name and not c.get("builtin")), None)
        if not found:
            raise ValueError(f"No custom command /{name}")
        await self._ask(ctx, f"Remove the /{name} command?", found.get("path") or "Settings → Commands", f"command {name}")
        if found.get("path"):
            Path(found["path"]).unlink()
        else:
            saved = store.load_settings().get("commands")
            saved = cmdmod.DEFAULTS if saved is None else saved
            store.replace_setting("commands", [c for c in saved if c.get("name") != name])
        self._changed("commands.changed")
        return ToolResult(text=f"Removed /{name}.", metadata={"action": "remove_command"})

    # -- hooks --

    async def add_hook(self, ctx: ToolContext, input: dict) -> ToolResult:
        event = str(input.get("event") or "")
        command = input.get("command")
        command = " ".join(command) if isinstance(command, list) else str(command or "").strip()
        name = str(input.get("name") or "").strip() or event
        if event not in hookmod.EVENTS:
            raise ValueError(f"event must be one of {', '.join(hookmod.EVENTS)}")
        if not command:
            raise ValueError("command is required")
        matcher = str(input.get("matcher") or "")
        if matcher:
            re.compile(matcher)
        await self._ask(ctx, f"Add a {event} hook?", f"{command}\n(matcher: {matcher or 'every tool'})", f"hook {name}")
        hooks = [h for h in store.load_settings().get("hooks") or [] if h.get("name") != name]
        hook = {"id": new_id("hook"), "name": name, "event": event, "matcher": matcher, "command": command,
                "timeout": int(input.get("timeout") or 60), "enabled": True}
        store.replace_setting("hooks", [*hooks, hook])
        self._changed("settings.changed")
        return ToolResult(text=f"Added hook '{name}' ({event}): {command}", metadata={"action": "add_hook", "hook": hook})

    async def remove_hook(self, ctx: ToolContext, input: dict) -> ToolResult:
        key = str(input.get("name") or input.get("id") or "").strip()
        hooks = store.load_settings().get("hooks") or []
        if not any(key in (h.get("name"), h.get("id")) for h in hooks):
            raise ValueError(f"No hook called '{key}'")
        await self._ask(ctx, f"Remove hook '{key}'?", key, f"hook {key}")
        store.replace_setting("hooks", [h for h in hooks if key not in (h.get("name"), h.get("id"))])
        self._changed("settings.changed")
        return ToolResult(text=f"Removed hook '{key}'.", metadata={"action": "remove_hook"})

    # -- agents --

    async def add_agent(self, ctx: ToolContext, input: dict) -> ToolResult:
        aid = str(input.get("id") or input.get("name") or "").strip().lower()
        aid = slug(aid) if aid else ""
        settings = store.load_settings()
        if not IDENT.match(aid) or aid in {store.LEADER_ID, "build", "plan", "redteam"} or any(d.get("id") == aid for d in settings["delegation"].get("delegates", [])):
            raise ValueError("Agent id must be lowercase letters, numbers, - _ and not build, plan, redteam, delegate or a delegate's id")
        entry: dict[str, Any] = {"mode": "primary", "name": str(input.get("name") or aid.title())}
        for key in ("description", "system", "model"):
            if input.get(key):
                entry[key] = str(input[key])
        if input.get("readonly"):
            entry["readonly"] = True
        await self._ask(ctx, f"Add the '{entry['name']}' agent?", json.dumps(entry, indent=2)[:2000], f"agent {aid}")
        store.replace_setting("agents", {**(settings.get("agents") or {}), aid: entry})
        self._changed("agent.updated")
        return ToolResult(text=f"Added agent '{aid}'. The user picks it from the mode menu under the message box.", metadata={"action": "add_agent"})

    async def remove_agent(self, ctx: ToolContext, input: dict) -> ToolResult:
        aid = str(input.get("id") or input.get("name") or "").strip().lower()
        agents = store.load_settings().get("agents") or {}
        if aid not in agents:
            raise ValueError(f"No custom agent '{aid}'")
        await self._ask(ctx, f"Remove the '{aid}' agent?", aid, f"agent {aid}")
        store.replace_setting("agents", {k: v for k, v in agents.items() if k != aid})
        self._changed("agent.updated")
        return ToolResult(text=f"Removed agent '{aid}'.", metadata={"action": "remove_agent"})

    # -- list --

    def listing(self, directory: str) -> str:
        s = store.load_settings()
        out = ["# Installed in AFH", "", "## Skills"]
        skills = discover(directory, store.AFH_DIR)
        out += [f"- `{k.id}` {k.name}: {k.description[:120]} ({k.source}, {k.dir})" for k in skills] or ["(none)"]
        out += ["", "## MCP servers"]
        status = {x["name"]: x for x in (self.engine.mcp.status() if self.engine.mcp else [])}
        for srv in (s.get("mcp") or {}).get("servers", []):
            st = status.get(srv.get("name"), {})
            state = "disabled" if srv.get("disabled") else st.get("status", "pending")
            what = " ".join(srv.get("command") or []) or srv.get("url", "")
            out.append(f"- {srv.get('name')}: {state}, {st.get('tools', 0)} tools ({what})" + (f" error: {st['error']}" if st.get("error") else ""))
        if not (s.get("mcp") or {}).get("servers"):
            out.append("(none)")
        out += ["", "## Slash commands (custom)"]
        cmds = [c for c in cmdmod.all_commands(directory, s) if not c.get("builtin")]
        out += [f"- /{c['name']}: {c.get('description', '')} ({c.get('path') or 'Settings'})" for c in cmds] or ["(none)"]
        out += ["", "## Hooks"]
        out += [f"- {h.get('name')} [{h.get('event')}{', off' if h.get('enabled') is False else ''}] {h.get('command')}" for h in s.get("hooks") or []] or ["(none)"]
        out += ["", "## Custom agents"]
        out += [f"- {k}: {v.get('name', k)} - {v.get('description', '')}" for k, v in (s.get("agents") or {}).items()] or ["(none)"]
        out += [f"- delegate {d.get('id')}: {d.get('job', '')}" for d in (s.get("delegation") or {}).get("delegates", [])]
        return "\n".join(out)
