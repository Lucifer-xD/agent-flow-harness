"""Tests for afh.skills_store. Live tests hit skills.sh; install tests only touch tmp_path."""

from __future__ import annotations

import json

import pytest

from afh import skills_store as ss

SOURCE, SLUG = "vercel-labs/skills", "find-skills"


def _hex64(s):
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


@pytest.fixture(autouse=True)
def _fresh_cache():
    ss.clear_cache()
    yield
    ss.clear_cache()


# --------------------------------------------------------------------------- catalogue (live)


def test_search_live():
    out = ss.search("find skills", limit=10)
    assert out["data"], "search returned nothing"
    first = out["data"][0]
    for key in ("id", "slug", "name", "source", "installs", "sourceType", "installUrl", "url"):
        assert key in first
    assert first["id"] == f"{first['source']}/{first['slug']}"
    assert any(s["id"] == f"{SOURCE}/{SLUG}" for s in out["data"])
    assert ss.search("find", owner="vercel-labs")["data"][0]["source"].startswith("vercel-labs/")


def test_search_rejects_short_query():
    with pytest.raises(ValueError):
        ss.search("f")


def test_browse_live():
    out = ss.browse("trending", page=0, per_page=5)
    assert len(out["data"]) == 5
    pag = out["pagination"]
    assert pag["page"] == 0 and pag["perPage"] == 5 and pag["hasMore"] is True and pag["total"] > 5
    assert all(row["installs"] >= 0 and row["slug"] for row in out["data"])
    page2 = ss.browse("trending", page=1, per_page=5)
    assert page2["data"][0]["id"] != out["data"][0]["id"]
    assert ss.browse("all-time", per_page=3)["data"]
    assert ss.browse("hot", per_page=3)["data"]
    with pytest.raises(ValueError):
        ss.browse("weekly")


def test_curated_live():
    out = ss.curated()
    assert out["totalOwners"] >= len(out["data"]) > 10
    owners = {o["owner"]: o for o in out["data"]}
    assert "vercel-labs" in owners
    vl = owners["vercel-labs"]
    assert vl["featuredRepo"] and vl["skills"]
    assert vl["skills"][0]["id"].startswith("vercel-labs/")


def test_detail_and_audit_live():
    d = ss.detail(SOURCE, SLUG)
    assert d["id"] == f"{SOURCE}/{SLUG}" and d["slug"] == SLUG
    assert _hex64(d["hash"])
    paths = [f["path"] for f in d["files"]]
    assert "SKILL.md" in paths
    assert d["installs"] is None or d["installs"] > 0

    a = ss.audit(SOURCE, SLUG)
    assert a and a["audits"] and a["audits"][0]["status"] in ("pass", "warn", "fail")
    assert ss.audit("nobody-xyz/nothing", "zzz-nope") is None

    with pytest.raises(ss.SkillsError) as exc:
        ss.detail("nobody-xyz/nothing", "zzz-nope")
    assert exc.value.status == 404


def test_get_is_cached(monkeypatch):
    calls = []
    real = ss.httpx.get

    def counting(*a, **kw):
        calls.append(a[0])
        return real(*a, **kw)

    monkeypatch.setattr(ss.httpx, "get", counting)
    ss.search("react")
    ss.search("react")
    assert len(calls) == 1


# --------------------------------------------------------------------------- install (tmp only)


def test_install_installed_updates_uninstall_live(tmp_path):
    root = tmp_path / "skills"
    manifest = ss.install(SOURCE, SLUG, scope="global", root=root)
    folder = root / SLUG
    assert (folder / "SKILL.md").is_file()
    saved = json.loads((folder / ss.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert saved["id"] == f"{SOURCE}/{SLUG}" and saved["scope"] == "global" and _hex64(saved["hash"])
    assert saved["hashSource"] == "skills.sh"
    assert manifest["path"] == str(folder) and "SKILL.md" in manifest["files"]
    assert not list(root.glob(".*staging*")) and not list(root.glob(".*old*"))

    rows = ss.installed(root=root, external_dirs=[])
    assert [r["slug"] for r in rows] == [SLUG]
    assert rows[0]["managed"] is True and rows[0]["name"] == "find-skills" and rows[0]["description"]

    updates = ss.check_updates(root=root)
    assert updates == [
        {
            "id": f"{SOURCE}/{SLUG}",
            "slug": SLUG,
            "scope": "global",
            "path": str(folder),
            "installedHash": saved["hash"],
            "latestHash": saved["hash"],
            "updateAvailable": False,
            "error": None,
        }
    ]

    # reinstall over an existing folder swaps atomically
    (folder / "junk.txt").write_text("x")
    ss.install(SOURCE, SLUG, root=root)
    assert not (folder / "junk.txt").exists() and (folder / "SKILL.md").is_file()

    assert ss.uninstall(SLUG, "global", root=root) is True
    assert not folder.exists()
    assert ss.uninstall(SLUG, "global", root=root) is False
    with pytest.raises(ValueError):
        ss.uninstall(SLUG, "external", root=root)


def test_project_scope_paths(tmp_path):
    assert ss.skills_root("project", tmp_path) == tmp_path / ".afh" / "skills"
    assert ss.skills_root("global") == ss.OPENCODE_SKILLS_DIR
    with pytest.raises(ValueError):
        ss.skills_root("project")
    with pytest.raises(ValueError):
        ss.skills_root("user")


def _fake_detail(monkeypatch, files):
    monkeypatch.setattr(
        ss, "detail", lambda source, slug: {**ss._record(source, slug), "hash": "h" * 64, "files": files}
    )


def test_install_rejects_unsafe_paths(tmp_path, monkeypatch):
    good = {"path": "SKILL.md", "contents": "---\nname: x\n---\n"}
    for bad in ("../evil.md", "/etc/passwd", "C:/win.txt", "a/../../b.md", "sub\\win.md", ss.MANIFEST_NAME):
        _fake_detail(monkeypatch, [good, {"path": bad, "contents": "pwn"}])
        with pytest.raises(ValueError):
            ss.install("o/r", "x", root=tmp_path)
        assert not (tmp_path / "x").exists()
        assert not list(tmp_path.glob("**/evil.md")) and not list(tmp_path.parent.glob("evil.md"))


def test_install_requires_skill_md_and_limits(tmp_path, monkeypatch):
    _fake_detail(monkeypatch, [{"path": "README.md", "contents": "no skill"}])
    with pytest.raises(ss.SkillsError):
        ss.install("o/r", "x", root=tmp_path)

    many = [{"path": f"ref/{i:03}.md", "contents": "x"} for i in range(ss.MAX_FILES + 5)]
    files = [{"path": "SKILL.md", "contents": "---\nname: x\n---\n"}, {"path": "big.bin", "contents": "a" * (ss.MAX_FILE_BYTES + 1)}] + many
    _fake_detail(monkeypatch, files)
    m = ss.install("o/r", "x", root=tmp_path)
    assert len(m["files"]) == ss.MAX_FILES
    reasons = {s["reason"] for s in m["skipped"]}
    assert "larger than 1 MB" in reasons and any("more than" in r for r in reasons)
    assert not (tmp_path / "x" / "big.bin").exists()
    with pytest.raises(ValueError):
        ss.install("o/r", "../x", root=tmp_path)
    with pytest.raises(ValueError):
        ss.install("not-a-repo", "x", root=tmp_path)


def test_installed_merges_unmanaged_and_external(tmp_path):
    root = tmp_path / "opencode"
    (root / "plain").mkdir(parents=True)
    (root / "plain" / "SKILL.md").write_text(
        '---\nname: "Plain Skill"\ndescription: >\n  folded line one\n  line two\nlicense: MIT\n---\n# body\n', encoding="utf-8"
    )
    (root / "noskill").mkdir()
    (root / ".hidden").mkdir()
    ext = tmp_path / "claude"
    (ext / "ext-skill").mkdir(parents=True)
    (ext / "ext-skill" / "SKILL.md").write_text("---\nname: ext-skill\ndescription: from claude dir\n---\n", encoding="utf-8")
    project = tmp_path / "proj"
    (project / ".afh" / "skills" / "proj-skill").mkdir(parents=True)
    (project / ".afh" / "skills" / "proj-skill" / "SKILL.md").write_text("---\nname: proj\n---\n")
    (project / ".agents" / "skills" / "agents-skill").mkdir(parents=True)
    (project / ".agents" / "skills" / "agents-skill" / "SKILL.md").write_text("---\nname: ag\n---\n")

    rows = {r["slug"]: r for r in ss.installed(project_dir=project, root=root, external_dirs=[ext])}
    assert set(rows) == {"plain", "ext-skill", "proj-skill", "agents-skill"}
    assert rows["plain"]["name"] == "Plain Skill" and rows["plain"]["description"] == "folded line one line two"
    assert rows["plain"]["managed"] is False and rows["plain"]["scope"] == "global"
    assert rows["ext-skill"]["scope"] == "external" and rows["agents-skill"]["scope"] == "external"
    assert rows["proj-skill"]["scope"] == "project"
    assert ss.check_updates(root=root) == []  # nothing managed


def test_parse_frontmatter():
    assert ss.parse_frontmatter("no frontmatter") == {}
    fm = ss.parse_frontmatter("---\nname: a-b\ndescription: 'it''s'\nmeta:\n  nested: 1\n---\nrest")
    assert fm["name"] == "a-b" and fm["description"] == "it''s" and "nested" not in fm
