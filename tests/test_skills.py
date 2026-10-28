"""Tests for afh.engine.skills: discovery across roots, frontmatter, catalog, tool output, mentions."""

from __future__ import annotations

from pathlib import Path

import pytest

from afh.engine import skills as sk
from afh.engine.types import PermissionDenied, ToolContext


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel / sk.SKILL_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def tree(tmp_path):
    user = tmp_path / "user"
    home = tmp_path / "afh-home"
    project = tmp_path / "project"
    _write(user / ".config" / "opencode" / "skills", "deploy", "---\nname: Deploy\ndescription: Ship the app\n---\nGlobal deploy steps.\n")
    _write(user / ".claude" / "skills", "review", '---\nname: "Code Review"\ndescription: >\n  Review a diff\n  carefully.\n---\n# Review\nLook at the diff.\n')
    _write(user / ".agents" / "skills", "hidden", "---\nname: Hidden\ndescription: Not advertised\ndisable-model-invocation: true\n---\nSecret.\n")
    _write(home, "skills/afh-only", "No frontmatter at all.\n")
    _write(project / ".afh" / "skills", "deploy", "---\nname: Deploy (project)\ndescription: Project deploy\nmetadata:\n  opencode/autoinvoke: false\n  owner: me\n---\nProject deploy steps.\n")
    _write(project / ".claude" / "skills", "tools/lint", "---\nname: Lint\ndescription: |\n  Run the linter\n  and fix issues\n---\nlint body\n")
    (project / ".claude" / "skills" / "tools" / "lint" / "scripts").mkdir()
    (project / ".claude" / "skills" / "tools" / "lint" / "scripts" / "run.py").write_text("print(1)\n")
    (project / ".claude" / "skills" / "tools" / "lint" / "reference.md").write_text("ref\n")
    return {"user": user, "home": home, "project": project}


def test_discover_roots_and_override(tree):
    found = sk.discover(str(tree["project"]), tree["home"], user_home=tree["user"])
    ids = {s.id: s for s in found}
    assert set(ids) == {"deploy", "review", "hidden", "afh-only", "tools/lint"}
    # project .afh/skills wins over the global opencode skill with the same id
    assert ids["deploy"].name == "Deploy (project)" and ids["deploy"].source == "project:afh"
    assert ids["deploy"].advertise is False  # metadata.opencode/autoinvoke: false
    assert ids["hidden"].advertise is False  # disable-model-invocation
    assert ids["review"].description == "Review a diff carefully."  # folded scalar, quoted name
    assert ids["review"].name == "Code Review" and ids["review"].body.startswith("# Review")
    assert ids["tools/lint"].description == "Run the linter and fix issues"  # literal block collapsed to one line
    assert ids["afh-only"].name == "afh-only" and ids["afh-only"].description == "" and ids["afh-only"].body == "No frontmatter at all."
    assert ids["afh-only"].source == "afh"


def test_discover_without_project(tree):
    found = sk.discover(None, tree["home"], user_home=tree["user"])
    ids = {s.id: s for s in found}
    assert ids["deploy"].source == "global:opencode" and "tools/lint" not in ids


def test_frontmatter_parser_variants():
    meta, body = sk.split_frontmatter("---\nname: X\nlist:\n  - a\n  - b\nflag: yes\nnum: 3\n---\nbody\n")
    assert meta == {"name": "X", "list": ["a", "b"], "flag": True, "num": "3"} and body == "body"
    assert sk.split_frontmatter("plain") == ({}, "plain")
    assert sk.split_frontmatter("---\nname: unterminated\n")[0] == {}


def test_catalog_text(tree):
    found = sk.discover(str(tree["project"]), tree["home"], user_home=tree["user"])
    text = sk.catalog_text(found)
    assert "- review · Code Review · Review a diff carefully." in text
    assert "- tools/lint · Lint · Run the linter and fix issues" in text
    assert "hidden" not in text and "deploy" not in text  # not advertised
    assert "- afh-only · afh-only" in text
    assert sk.catalog_text([]) == ""


class _Gate:
    def __init__(self, deny: set[str] | None = None):
        self.calls: list[tuple] = []
        self.deny = deny or set()

    async def require(self, action, resources, metadata=None):
        self.calls.append((action, resources, metadata))
        if set(resources) & self.deny:
            raise PermissionDenied("no")


def _ctx(gate: _Gate) -> ToolContext:
    return ToolContext(session_id="s", message_id="m", directory=".", permissions=gate, snapshots=None, emit=lambda *_: None)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_skill_tool_output(tree):
    found = sk.discover(str(tree["project"]), tree["home"], user_home=tree["user"])
    tool = sk.SkillTool(lambda: found)
    gate = _Gate()
    res = await tool.run(_ctx(gate), {"id": "tools/lint"})
    assert not res.is_error
    skill_dir = str(tree["project"] / ".claude" / "skills" / "tools" / "lint")
    lines = res.text.splitlines()
    assert lines[0] == '<skill_content name="Lint">' and lines[1] == "# Skill: Lint" and lines[2] == ""
    assert lines[3] == "lint body"
    assert f"Base directory for this skill: {skill_dir}" in lines
    assert "Note: file list is sampled." in lines and lines[-1] == "</skill_content>"
    files = [l for l in lines if l.startswith("<file>")]
    assert files == [f"<file>{Path(skill_dir) / 'reference.md'}</file>", f"<file>{Path(skill_dir) / 'scripts' / 'run.py'}</file>"]
    assert "SKILL.md" not in res.text.split("<skill_files>")[1]
    assert gate.calls == [("skill", ["tools/lint"], {"skill": "tools/lint", "path": str(Path(skill_dir) / "SKILL.md")})]
    assert res.metadata["directory"] == skill_dir and res.metadata["name"] == "Lint"
    assert tool.spec.name == "skill" and tool.spec.parameters["required"] == ["id"]


@pytest.mark.anyio
async def test_skill_tool_missing_and_denied(tree):
    found = sk.discover(str(tree["project"]), tree["home"], user_home=tree["user"])
    tool = sk.SkillTool(found)
    res = await tool.run(_ctx(_Gate()), {"id": "nope"})
    assert res.is_error and "Unable to load skill nope" in res.text and "tools/lint" in res.text
    with pytest.raises(PermissionDenied):
        await tool.run(_ctx(_Gate(deny={"review"})), {"id": "review"})
    # hidden skills can still be loaded explicitly, and a leading @ is tolerated
    assert not (await tool.run(_ctx(_Gate()), {"id": "@hidden"})).is_error


def test_file_list_capped(tmp_path):
    d = tmp_path / "big"
    _write(tmp_path, "big", "---\nname: Big\n---\nbody")
    for i in range(15):
        (d / f"f{i:02d}.txt").write_text("x")
    skill = sk.discover(None, tmp_path / "nohome", user_home=tmp_path / "nouser")
    assert skill == []  # 'big' is not under any root
    s = sk.load_skill(d / "SKILL.md", tmp_path, "test")
    files = sk.supporting_files(s)
    assert len(files) == 10 and files[0].endswith("f00.txt")


def test_mentioned(tree):
    found = sk.discover(str(tree["project"]), tree["home"], user_home=tree["user"])
    got = sk.mentioned("please use @tools/lint, then @review. ignore @unknown and me@review and @review again", found)
    assert [s.id for s in got] == ["tools/lint", "review"]
    assert sk.mentioned("nothing here", found) == []
