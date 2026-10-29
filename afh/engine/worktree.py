"""Git worktrees: a thread (or a delegate) can work in its own copy of the repository on its own
branch, so parallel agents never overwrite each other's files. AFH creates them under
``~/.afh/worktrees`` and can merge the branch back or remove the copy when you are done."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .. import store
from .tools.shell import CREATE_NO_WINDOW, child_env
from .types import new_id

ROOT = store.AFH_DIR / "worktrees"
IS_WINDOWS = sys.platform == "win32"


class GitError(Exception):
    pass


async def git(*args: str, cwd: str, check: bool = True, timeout: float = 120) -> str:
    if not shutil.which("git"):
        raise GitError("Git is not installed (or not on PATH).")
    proc = await asyncio.create_subprocess_exec("git", *args, cwd=cwd, env={**child_env(), "GIT_TERMINAL_PROMPT": "0"}, stdin=subprocess.DEVNULL,
                                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **({"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}))
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise GitError(f"git {args[0]} timed out") from None
    text = out.decode("utf-8", errors="replace").strip()
    if check and proc.returncode != 0:
        raise GitError(text.splitlines()[-1] if text else f"git {args[0]} failed ({proc.returncode})")
    return text


async def repo_root(directory: str) -> str | None:
    try:
        return str(Path(await git("rev-parse", "--show-toplevel", cwd=directory, timeout=15)).resolve())
    except (GitError, OSError):
        return None


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:32].strip("-")
    return s or "thread"


async def create(directory: str, name: str = "") -> dict:
    """New worktree on a new branch from the current HEAD of `directory`'s repository."""
    root = await repo_root(directory)
    if not root:
        raise GitError("This project is not a git repository, so it cannot get its own worktree. Run `git init` and commit first.")
    try:
        head = await git("rev-parse", "HEAD", cwd=root, timeout=15)
    except GitError:
        raise GitError("The repository has no commits yet; make a first commit before using worktrees.") from None
    base = await git("rev-parse", "--abbrev-ref", "HEAD", cwd=root, timeout=15)
    short = new_id("wt")[-6:].lower()
    branch = f"afh/{slug(name)}-{short}"
    path = ROOT / f"{Path(root).name}-{short}"
    ROOT.mkdir(parents=True, exist_ok=True)
    await git("worktree", "add", "-b", branch, str(path), "HEAD", cwd=root)
    # Keep the same sub-folder when the project is a folder inside the repository.
    sub = Path(directory).resolve().relative_to(Path(root)) if Path(directory).resolve() != Path(root) else Path(".")
    work_dir = (path / sub).resolve()
    return {"path": str(path), "directory": str(work_dir), "branch": branch, "base": base if base != "HEAD" else head[:12], "baseCommit": head, "repo": root}


async def is_merged(wt: dict) -> bool:
    """True when the branch's commits are already in the branch the main checkout is on."""
    try:
        await git("merge-base", "--is-ancestor", wt["branch"], "HEAD", cwd=wt["repo"], timeout=15)
        return True
    except (GitError, OSError):
        return False


async def status(wt: dict) -> dict:
    path = wt["path"]
    if not Path(path).exists():
        return {"exists": False, "dirty": [], "ahead": 0, "commits": [], "merged": False}
    porcelain = await git("status", "--porcelain", cwd=path, check=False)
    dirty = [l[3:] for l in porcelain.splitlines() if l.strip()]
    log = await git("log", "--oneline", f"{wt['baseCommit']}..HEAD", cwd=path, check=False)
    commits = [l for l in log.splitlines() if l.strip()]
    merged = bool(commits) and await is_merged(wt)
    return {"exists": True, "dirty": dirty, "ahead": len(commits), "commits": commits[:20], "merged": merged, "branch": wt["branch"], "base": wt.get("base")}


async def commit_all(wt: dict, message: str) -> bool:
    path = wt["path"]
    if not (await git("status", "--porcelain", cwd=path, check=False)).strip():
        return False
    await git("add", "-A", cwd=path)
    await git("-c", "user.name=Agent Flow Harness", "-c", "user.email=afh@localhost", "commit", "-m", message, "--no-verify", cwd=path, check=False)
    return True


async def merge(wt: dict, message: str) -> dict:
    """Commit the worktree's changes and merge its branch into the branch the main checkout is on."""
    committed = await commit_all(wt, message)
    root = wt["repo"]
    current = await git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    out = await git("merge", "--no-ff", "--no-edit", "-m", f"Merge {wt['branch']}: {message}", wt["branch"], cwd=root, check=False)
    if "CONFLICT" in out or "Automatic merge failed" in out:
        await git("merge", "--abort", cwd=root, check=False)
        raise GitError(f"Merging {wt['branch']} into {current} has conflicts; nothing was changed. Resolve them by hand (git merge {wt['branch']}) or ask the agent to rebase its branch.")
    if "error:" in out.lower() or "fatal:" in out.lower():
        raise GitError(out.splitlines()[-1])
    return {"merged": True, "into": current, "committed": committed, "output": out[-2000:]}


async def remove(wt: dict, delete_branch: bool = True) -> None:
    root = wt["repo"]
    if Path(wt["path"]).exists():
        await git("worktree", "remove", "--force", wt["path"], cwd=root, check=False)
    if Path(wt["path"]).exists():
        shutil.rmtree(wt["path"], ignore_errors=True)
    await git("worktree", "prune", cwd=root, check=False)
    if delete_branch:
        await git("branch", "-D", wt["branch"], cwd=root, check=False)
