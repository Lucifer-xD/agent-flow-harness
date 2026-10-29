"""The `harness` tool: the model installs skills, MCP servers, commands, hooks and agents itself."""

from __future__ import annotations

import asyncio

import pytest

from afh import store as appstore
from afh.engine import commands as cmdmod
from afh.engine import install
from afh.engine.agents import all_agents
from afh.engine.skills import discover
from afh.engine.types import PermissionDenied, ToolContext

from test_engine_features import FakeProvider, home, make_engine  # noqa: F401 - fixture


class Gate:
    def __init__(self, deny: bool = False):
        self.deny = deny
        self.calls: list[tuple] = []

    async def require(self, action, resources, metadata=None):
        self.calls.append((action, resources, metadata))
        if self.deny:
            raise PermissionDenied("no")


def ctx(directory, gate=None) -> ToolContext:
    return ToolContext(session_id="s", message_id="m", directory=str(directory), permissions=gate or Gate(), snapshots=None, emit=lambda *_: None)  # type: ignore[arg-type]


def run(tool, c, **input):
    return asyncio.run(tool.run(c, input))


def skill(folder, name, description="does things"):
    folder.mkdir(parents=True)
    head = "---\n" + (f"name: {name}\n" if name else "") + (f"description: {description}\n" if description else "") + "---\n"
    (folder / "SKILL.md").write_text(head + "Body of " + str(name), encoding="utf-8")
    (folder / "helper.py").write_text("print(1)", encoding="utf-8")


def test_parse_source_understands_github_links():
    p = install.parse_source
    assert p("https://github.com/anthropics/skills") == {"url": "https://github.com/anthropics/skills.git", "ref": "", "path": "", "github": "anthropics/skills"}
    assert p("https://github.com/a/b/tree/main/skills/pdf")["path"] == "skills/pdf"
    assert p("https://github.com/a/b/tree/main/skills/pdf")["ref"] == "main"
    assert p("github.com/a/b/blob/dev/x/SKILL.md")["path"] == "x" and p("github.com/a/b.git")["url"] == "https://github.com/a/b.git"
    assert p("a/b")["github"] == "a/b"
    assert p("https://gitlab.com/x/y.git") == {"url": "https://gitlab.com/x/y.git", "ref": "", "path": ""}
    with pytest.raises(ValueError):
        p("not a source at all")


def test_install_skills_from_a_folder_live_and_remove(home, tmp_path):
    e = make_engine(FakeProvider([]))
    repo = tmp_path / "repo"
    skill(repo / "skills" / "pdf", "pdf-tools")
    skill(repo / "skills" / "pdf" / "nested", "inner")  # rides along with its parent
    skill(repo / "skills" / "web", "web-helper")
    skill(repo / "skills" / "broken", None)
    (repo / "skills" / "web" / ".git").mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    tool = install.HarnessTool(e)
    gate = Gate()

    res = run(tool, ctx(project, gate), action="install_skill", source=str(repo))
    assert not res.is_error, res.text
    assert gate.calls and gate.calls[0][0] == "shell" and gate.calls[0][2]["title"] == "Install a skill?"
    names = {s["name"] for s in res.metadata["installed"]}
    assert names == {"pdf-tools", "web-helper"}
    assert "broken" in res.text  # skipped, with the reason
    ids = {s.id for s in discover(str(project), home)}
    assert {"pdf-tools", "web-helper"} <= ids
    assert (home / "skills" / "pdf-tools" / "nested" / "SKILL.md").exists()
    assert not (home / "skills" / "web-helper" / ".git").exists()

    # the very next step sees it: tools and the system prompt are rebuilt from disk
    s = e.create_session(str(project))
    agent = all_agents()[0]
    assert "skill" in [t.spec.name for t in e.tools_for(s, agent)]
    prompt = e.system_prompt_for(s, agent)
    assert "pdf-tools" in prompt and "Extending AFH" in prompt

    assert "pdf-tools" in run(tool, ctx(project), action="list").text
    res = run(tool, ctx(project), action="remove_skill", name="pdf-tools")
    assert not res.is_error and not (home / "skills" / "pdf-tools").exists()


def test_install_only_picks_named_skills_into_the_project(home, tmp_path):
    e = make_engine(FakeProvider([]))
    repo = tmp_path / "repo"
    skill(repo / "a", "alpha")
    skill(repo / "b", "beta")
    project = tmp_path / "proj"
    project.mkdir()
    res = run(install.HarnessTool(e), ctx(project), action="install_skill", source=str(repo), only=["beta"], scope="project")
    assert [s["name"] for s in res.metadata["installed"]] == ["beta"]
    assert (project / ".afh" / "skills" / "beta" / "SKILL.md").exists()
    (tmp_path / "empty").mkdir()
    res = run(install.HarnessTool(e), ctx(project), action="install_skill", source=str(tmp_path / "empty"))
    assert res.is_error and "No SKILL.md" in res.text


def test_denied_install_changes_nothing(home, tmp_path):
    e = make_engine(FakeProvider([]))
    repo = tmp_path / "repo"
    skill(repo / "a", "alpha")
    with pytest.raises(PermissionDenied):
        run(install.HarnessTool(e), ctx(tmp_path, Gate(deny=True)), action="install_skill", source=str(repo))
    assert not (home / "skills").exists()


def test_add_mcp_saves_reports_failure_and_removes(home, tmp_path):
    e = make_engine(FakeProvider([]))
    tool = install.HarnessTool(e)
    gate = Gate()

    async def go():
        res = await tool.run(ctx(tmp_path, gate), {"action": "add_mcp", "name": "gh", "command": ["no-such-mcp-binary-xyz", "--stdio"], "environment": {"TOKEN": "secret123"}})
        assert res.is_error and "did not start" in res.text
        assert "secret123" not in gate.calls[0][2]["command"] and "TOKEN=" in gate.calls[0][2]["command"]
        servers = appstore.load_settings()["mcp"]["servers"]
        assert servers == [{"name": "gh", "type": "local", "command": ["no-such-mcp-binary-xyz", "--stdio"], "environment": {"TOKEN": "secret123"}}]
        assert "gh: failed" in (await tool.run(ctx(tmp_path), {"action": "list"})).text
        res = await tool.run(ctx(tmp_path), {"action": "remove_mcp", "name": "gh"})
        assert not res.is_error and appstore.load_settings()["mcp"]["servers"] == []
        assert not any(s["name"] == "gh" for s in e.mcp.status())
        await e.mcp.stop()

    asyncio.run(go())
    with pytest.raises(ValueError):
        install.mcp_entry({"name": "bad name!", "command": ["x"]})
    assert install.mcp_entry({"name": "r", "url": "https://mcp.example.com/mcp"})["type"] == "remote"


def test_commands_hooks_and_agents(home, tmp_path):
    e = make_engine(FakeProvider([]))
    tool = install.HarnessTool(e)
    c = ctx(tmp_path)

    assert not run(tool, c, action="add_command", name="/deploy", prompt="Deploy $ARGUMENTS", description="Ship it").is_error
    cmd = next(x for x in cmdmod.all_commands(str(tmp_path)) if x["name"] == "deploy")
    assert cmd["description"] == "Ship it" and cmd["prompt"] == "Deploy $ARGUMENTS"
    assert run(tool, c, action="add_command", name="goal", prompt="x").is_error  # built-ins are kept
    assert not run(tool, c, action="remove_command", name="deploy").is_error
    assert not any(x["name"] == "deploy" for x in cmdmod.all_commands(str(tmp_path)))

    assert not run(tool, c, action="add_hook", name="fmt", event="post_tool", matcher="^(write|edit)$", command="ruff format").is_error
    assert [h["name"] for h in appstore.load_settings()["hooks"]] == ["fmt"]
    assert run(tool, c, action="add_hook", name="x", event="nope", command="y").is_error
    assert not run(tool, c, action="remove_hook", name="fmt").is_error
    assert appstore.load_settings()["hooks"] == []

    assert not run(tool, c, action="add_agent", id="reviewer", name="Reviewer", system="Review code.", readonly=True).is_error
    assert any(a.id == "reviewer" for a in all_agents())
    assert run(tool, c, action="add_agent", id="build").is_error
    assert not run(tool, c, action="remove_agent", id="reviewer").is_error
    assert not any(a.id == "reviewer" for a in all_agents())  # really gone (settings merges used to keep it)


def test_replace_setting_drops_keys(home):
    appstore.save_settings({"agents": {"a": {"name": "A"}, "b": {"name": "B"}}})
    appstore.save_settings({"agents": {"b": {"name": "B"}}})
    assert "a" in appstore.load_settings()["agents"]  # why replace_setting exists
    appstore.replace_setting("agents", {"b": {"name": "B"}})
    assert list(appstore.load_settings()["agents"]) == ["b"]
