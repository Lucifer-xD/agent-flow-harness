"""Model races: the same task for several models at once, each in its own git worktree. A check
command (the project's tests, usually) scores the results, you read them side by side, and the one
you pick is merged. Nothing is merged without that pick.

A race starts from the checkout's HEAD. Files that aren't committed, like node_modules or a venv,
aren't in a worktree, so the check may need to install them first ("npm ci && npm test").
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .. import store
from . import worktree as wtmod
from .tools.shell import kill_tree, spawn
from .types import new_id, now_ms

log = logging.getLogger("afh.race")

FILE = "races.json"
RUN_LIMIT = 3600
CHECK_LIMIT = 900
OUTPUT_LIMIT = 4000
KEEP = 20


def split_ref(ref: str) -> dict:
    provider, _, model = ref.partition("/")
    if not model:
        raise ValueError(f'Write each model as provider/model, not "{ref}"')
    return {"providerID": provider, "id": model}


def rank(entries: list[dict]) -> list[dict]:
    """Finished work first, then passing checks, then the lowest cost, then the smallest change."""
    def score(e: dict) -> tuple:
        return (not e.get("changed"), e.get("error") is not None, e.get("passed") is False, e.get("cost") or 0, e.get("lines") or 0)

    return sorted(entries, key=score)


class Races:
    def __init__(self, engine):
        self.engine = engine
        self.running: dict[str, asyncio.Task] = {}

    def path(self):
        return store.AFH_DIR / FILE

    def read(self) -> list[dict]:
        try:
            return json.loads(self.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def save(self, race: dict) -> None:
        races = [r for r in self.read() if r["id"] != race["id"]]
        self.path().write_text(json.dumps([race, *races][:KEEP], indent=2), encoding="utf-8")

    def get(self, rid: str) -> dict:
        found = next((r for r in self.read() if r["id"] == rid), None)
        if not found:
            raise KeyError(rid)
        return found

    async def start(self, directory: str, prompt: str, models: list[str], check: str = "", mode: str = "full") -> dict:
        refs = [split_ref(m) for m in models]
        if len(refs) < 2:
            raise ValueError("A race needs at least two models")
        if not prompt.strip():
            raise ValueError("Say what the models should do")
        race: dict[str, Any] = {"id": new_id("race"), "status": "running", "prompt": prompt, "directory": directory, "check": check,
                                "created": now_ms(), "entries": [], "picked": None}
        for ref in refs:
            name = f"race-{ref['id']}"
            s = await self.engine.create_worktree_session(directory, name, title=f"Race: {ref['id']}", model=ref, mode=mode)
            race["entries"].append({"session": s["id"], "model": f"{ref['providerID']}/{ref['id']}", "status": "running"})
        self.save(race)
        for e in race["entries"]:
            await self.engine.prompt(e["session"], prompt)
        self.running[race["id"]] = asyncio.ensure_future(self.finish(race))
        return race

    async def finish(self, race: dict) -> None:
        try:
            await asyncio.gather(*(self.settle(race, e) for e in race["entries"]))
            race["entries"] = rank(race["entries"])
            race["status"] = "finished"
            self.save(race)
        finally:
            self.running.pop(race["id"], None)

    async def settle(self, race: dict, entry: dict) -> None:
        sid = entry["session"]
        started = time.time()
        await asyncio.sleep(0.3)
        while self.engine.is_running(sid):
            if time.time() - started > RUN_LIMIT:
                self.engine.interrupt(sid)
                entry["error"] = "ran out of time"
                break
            await asyncio.sleep(0.5)
        entry["seconds"] = round(time.time() - started)
        s = self.engine.store.get_session(sid) or {}
        entry["cost"] = s.get("cost") or 0
        wt = self.engine._afh(sid).get("worktree") or {}
        try:
            await wtmod.commit_all(wt, f"Race: {entry['model']}")
            stat = await wtmod.git("diff", "--shortstat", f"{wt['baseCommit']}..HEAD", cwd=wt["path"], check=False)
            numbers = [int(w) for w in stat.replace(",", " ").split() if w.isdigit()]
            entry["changed"] = bool(numbers)
            entry["files"] = numbers[0] if numbers else 0
            entry["lines"] = sum(numbers[1:])
            if race["check"] and entry["changed"]:
                await self.run_check(race["check"], wt, entry)
        except (wtmod.GitError, OSError, KeyError) as err:
            entry["error"] = str(err)
        entry["status"] = "finished"
        self.save(race)

    async def run_check(self, command: str, wt: dict, entry: dict) -> None:
        proc = await spawn(command, wt["directory"], self.engine.settings().get("shell"))
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), CHECK_LIMIT)
        except asyncio.TimeoutError:
            await kill_tree(proc)
            entry["passed"], entry["checkOutput"] = False, f"The check ran for over {CHECK_LIMIT} seconds."
            return
        entry["passed"] = proc.returncode == 0
        entry["checkOutput"] = out.decode("utf-8", "replace")[-OUTPUT_LIMIT:]

    async def pick(self, rid: str, sid: str) -> dict:
        """Merge the chosen model's branch into the checkout and clear away the rest."""
        race = self.get(rid)
        if race["status"] != "finished":
            raise ValueError("That race is still running" if race["status"] == "running" else "That race is already closed")
        entry = next((e for e in race["entries"] if e["session"] == sid), None)
        if not entry:
            raise ValueError("That model isn't in this race")
        if not entry.get("changed"):
            raise ValueError("That model changed nothing, so there's nothing to merge")
        out = await wtmod.merge(self.engine._afh(sid)["worktree"], f"{entry['model']}: {race['prompt'][:60]}")
        await self.close(race, sid)
        return {**race, "merged": out}

    async def discard(self, rid: str) -> dict:
        race = self.get(rid)
        if race["status"] == "running":
            raise ValueError("That race is still running")
        await self.close(race, None)
        return race

    async def close(self, race: dict, picked: str | None) -> None:
        for e in race["entries"]:
            wt = self.engine._afh(e["session"]).get("worktree")
            if wt:
                await wtmod.remove(wt, delete_branch=True)
        race["picked"], race["status"] = picked, "closed"
        self.save(race)
