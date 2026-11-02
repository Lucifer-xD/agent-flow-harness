"""Design first: the `design` tool shows options A/B/C as mockups, waits for a pick, and the pick becomes .afh/design.md."""

from __future__ import annotations

import asyncio

import pytest

from afh.engine import permissions as perm
from afh.engine.design import DesignTool, clean, prompt_section, report
from afh.engine.types import PermissionDenied, ToolContext


def project(tmp_path, letters="ab", screens=("home", "detail")):
    for x in letters:
        for s in screens:
            f = tmp_path / ".afh" / "designs" / "notes" / x / f"{s}.html"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"<!doctype html><h1>{x} {s}</h1>", encoding="utf-8")
    return {"title": "Notes app", "platform": "android", "options": [
        {"name": f"Option {x}", "summary": "  calm   and light ", "screens": [{"name": s.title(), "device": "phone", "file": f".afh/designs/notes/{x}/{s}.html"} for s in screens]}
        for x in letters]}


def gate_and_pending():
    pending: dict = {}
    events: list = []
    g = perm.Gate("s", perm.rules_for_mode("full"), events.append, pending, lambda r: None)
    return g, pending, events


def ctx(g, directory) -> ToolContext:
    return ToolContext(session_id="s", message_id="m", directory=str(directory), permissions=g, snapshots=None, emit=lambda *_: None)  # type: ignore[arg-type]


def test_clean_sizes_screens_for_the_platform(tmp_path):
    req = clean(project(tmp_path), str(tmp_path))
    assert req["platform"] == "android" and [o["letter"] for o in req["options"]] == ["A", "B"]
    sc = req["options"][0]["screens"][0]
    assert (sc["width"], sc["height"]) == (412, 915) and sc["path"].endswith("home.html")
    assert req["options"][0]["summary"] == "calm and light"
    raw = project(tmp_path)
    raw["options"][0]["name"], raw["options"][1]["name"] = "A — Quiet Paper", "A calm look"
    assert [o["name"] for o in clean(raw, str(tmp_path))["options"]] == ["Quiet Paper", "A calm look"]
    raw = project(tmp_path)
    raw["platform"] = "ios"
    assert clean(raw, str(tmp_path))["options"][0]["screens"][0]["width"] == 393
    raw["options"][0]["screens"][0]["device"] = "toaster"
    assert clean(raw, str(tmp_path))["options"][0]["screens"][0]["device"] == "desktop"


def test_clean_refuses_bad_requests(tmp_path):
    raw = project(tmp_path)
    with pytest.raises(ValueError, match="2-4 options"):
        clean({**raw, "options": raw["options"][:1]}, str(tmp_path))
    bad = project(tmp_path)
    bad["options"][0]["screens"][0]["file"] = "../outside.html"
    with pytest.raises(ValueError, match="outside the project"):
        clean(bad, str(tmp_path))
    bad = project(tmp_path)
    bad["options"][1]["screens"][0]["file"] = ".afh/designs/notes/b/missing.html"
    with pytest.raises(ValueError, match="write it first"):
        clean(bad, str(tmp_path))


def test_report_choice_and_new_options(tmp_path):
    req = clean(project(tmp_path), str(tmp_path))
    text = report(req, {"choice": "b", "notes": "bigger buttons"})
    assert "chose option B" in text and "bigger buttons" in text and ".afh/design.md" in text and "b/home.html" in text
    text = report(req, {"choice": "", "notes": "darker"})
    assert "different options" in text and "darker" in text and "call `design` again" in text


def test_prompt_section_reads_the_design_system(tmp_path):
    assert prompt_section(str(tmp_path)) == ""
    (tmp_path / ".afh").mkdir()
    (tmp_path / ".afh" / "design.md").write_text("Colours: #112233", encoding="utf-8")
    out = prompt_section(str(tmp_path))
    assert "Project design system" in out and "#112233" in out


def test_design_waits_for_a_pick(tmp_path):
    async def go():
        g, pending, events = gate_and_pending()

        async def pick():
            while not pending:
                await asyncio.sleep(0)
            req = next(iter(pending.values()))
            assert req.action == "design" and len(req.metadata["design"]["options"]) == 2  # asks even with full access
            req.reply("answer", None, [{"choice": "A", "notes": "warmer"}])

        res, _ = await asyncio.gather(DesignTool().run(ctx(g, tmp_path), project(tmp_path)), pick())
        assert not res.is_error and "chose option A" in res.text
        assert res.metadata["answer"] == {"choice": "A", "notes": "warmer"}
        assert not pending and [e["type"] for e in events] == ["permission.asked", "permission.replied"]

    asyncio.run(go())


def test_design_skip_stop_and_errors(tmp_path):
    async def go():
        g, pending, _ = gate_and_pending()

        async def reply_with(decision):
            while not pending:
                await asyncio.sleep(0)
            next(iter(pending.values())).reply(decision, None, None)

        res, _ = await asyncio.gather(DesignTool().run(ctx(g, tmp_path), project(tmp_path)), reply_with("dismiss"))
        assert not res.is_error and res.metadata["dismissed"] and "without choosing" in res.text
        with pytest.raises(PermissionDenied):
            await asyncio.gather(DesignTool().run(ctx(g, tmp_path), project(tmp_path)), reply_with("reject"))
        res = await DesignTool().run(ctx(g, tmp_path), {"title": "x", "platform": "web", "options": []})
        assert res.is_error and not pending

    asyncio.run(go())


def test_mockup_endpoint_only_serves_design_html(tmp_path):
    from afh import api as apimod

    project(tmp_path)
    ok = tmp_path / ".afh" / "designs" / "notes" / "a" / "home.html"
    assert "a home" in apimod.design_file(str(ok))["html"]
    (tmp_path / "secret.html").write_text("no", encoding="utf-8")
    (tmp_path / ".afh" / "designs" / "notes" / "a" / "key.txt").write_text("no", encoding="utf-8")
    (tmp_path / "designs").mkdir()
    (tmp_path / "designs" / ".afh.html").write_text("no", encoding="utf-8")
    for bad in (tmp_path / "secret.html", tmp_path / ".afh" / "designs" / "notes" / "a" / "key.txt", tmp_path / "designs" / ".afh.html",
                ok.parent / ".." / ".." / ".." / ".." / "secret.html"):
        with pytest.raises(KeyError):
            apimod.design_file(str(bad))
