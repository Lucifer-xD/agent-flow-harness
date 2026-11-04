"""Model races with real git worktrees and a real check command; only the model is faked."""
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from afh import store
from afh.engine import race as racemod
from afh.engine import worktree as wtmod

CHECK = f'"{sys.executable}" -c "import pathlib,sys; sys.exit(0 if \'good\' in pathlib.Path(\'answer.txt\').read_text() else 1)"'


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class FakeEngine:
    """A "model" writes answer.txt in its worktree the moment it gets the prompt."""

    def __init__(self, answers):
        self.answers = answers
        self.sessions: dict[str, dict] = {}
        self.store = self

    def settings(self):
        return {"shell": "cmd" if sys.platform == "win32" else None}

    async def create_worktree_session(self, directory, name, **kw):
        wt = await wtmod.create(directory, name)
        s = {"id": f"s{len(self.sessions)}", "wt": wt, "cost": 0.01 * (len(self.sessions) + 1), **kw}
        self.sessions[s["id"]] = s
        return s

    def get_session(self, sid):
        return self.sessions[sid]

    def _afh(self, sid):
        return {"worktree": self.sessions[sid]["wt"]}

    async def prompt(self, sid, text):
        answer = self.answers[self.sessions[sid]["model"]["id"]]
        if answer is not None:
            (Path(self.sessions[sid]["wt"]["directory"]) / "answer.txt").write_text(answer)

    def is_running(self, sid):
        return False

    def interrupt(self, sid):
        pass


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AFH_DIR", tmp_path / "afh")
    monkeypatch.setattr(wtmod, "ROOT", tmp_path / "afh" / "worktrees")
    (tmp_path / "afh").mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-b", "main", cwd=repo)
    (repo / "a.txt").write_text("a\n")
    git("add", "-A", cwd=repo)
    git("commit", "-m", "first", cwd=repo)
    return repo


def race_of(project, answers, check=CHECK):
    races = racemod.Races(FakeEngine(answers))

    async def go():
        race = await races.start(str(project), "solve it", [f"p/{m}" for m in answers], check)
        await races.running[race["id"]]
        return races, races.get(race["id"])

    return go


def test_the_check_scores_each_model_and_passing_comes_first(project):
    _, race = asyncio.run(race_of(project, {"bad": "wrong", "good": "good answer", "idle": None})())
    assert race["status"] == "finished"
    assert [e["model"] for e in race["entries"]] == ["p/good", "p/bad", "p/idle"]
    good, bad, idle = race["entries"]
    assert good["passed"] is True and good["changed"] and good["files"] == 1
    assert bad["passed"] is False
    assert not idle["changed"] and "passed" not in idle


def test_nothing_is_merged_until_you_pick(project):
    asyncio.run(race_of(project, {"one": "good", "two": "good"})())
    assert not (project / "answer.txt").exists()


def test_picking_merges_that_model_and_clears_the_rest(project):
    async def go():
        races, race = await race_of(project, {"one": "good one", "two": "good two"})()
        chosen = next(e for e in race["entries"] if e["model"] == "p/two")
        return races, race, await races.pick(race["id"], chosen["session"]), chosen

    _, race, done, chosen = asyncio.run(go())
    assert (project / "answer.txt").read_text() == "good two"
    assert done["status"] == "closed" and done["picked"] == chosen["session"]
    assert not list((store.AFH_DIR / "worktrees").glob("*"))
    assert "race-" not in git("branch", "--list", cwd=project)


def test_discarding_changes_nothing_in_the_checkout(project):
    async def go():
        races, race = await race_of(project, {"one": "x", "two": "y"})()
        return await races.discard(race["id"])

    assert asyncio.run(go())["status"] == "closed"
    assert not (project / "answer.txt").exists()
    assert not list((store.AFH_DIR / "worktrees").glob("*"))


def test_a_closed_race_cannot_be_picked_again(project):
    async def go():
        races, race = await race_of(project, {"one": "x", "two": "y"})()
        await races.discard(race["id"])
        await races.pick(race["id"], race["entries"][0]["session"])

    with pytest.raises(ValueError, match="closed"):
        asyncio.run(go())


def test_a_model_that_changed_nothing_cannot_be_picked(project):
    async def go():
        races, race = await race_of(project, {"one": "x", "idle": None})()
        idle = next(e for e in race["entries"] if e["model"] == "p/idle")
        await races.pick(race["id"], idle["session"])

    with pytest.raises(ValueError, match="changed nothing"):
        asyncio.run(go())


@pytest.mark.parametrize("models,prompt", [(["p/one"], "x"), (["p/a", "noslash"], "x"), (["p/a", "p/b"], "  ")])
def test_bad_races_are_refused_before_anything_starts(project, models, prompt):
    races = racemod.Races(FakeEngine({}))
    with pytest.raises(ValueError):
        asyncio.run(races.start(str(project), prompt, models))
    assert not (store.AFH_DIR / "worktrees").exists()
