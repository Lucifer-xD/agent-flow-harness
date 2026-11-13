"""The `threads` tool: a model reads another thread (or its own, from before a compaction) word for
word, in pages, after the user allowed it or named the thread themselves."""

from __future__ import annotations

import asyncio

from afh.engine import runner as runmod
from afh.engine.threads import COMPACTED, ThreadsTool, named_by_user, page, transcript
from afh.engine.types import ChatMessage, ToolContext

from test_engine_features import FakeProvider, home, make_engine, run_prompt, text_of, tool_results  # noqa: F401 - `home` is a fixture

FILE = "<!doctype html>\n<title>Shop</title>\n<h1>Tea & \"biscuits\"</h1>\n\t<p>line with a tab, a backslash \\ and ünïcödé ✓</p>\n"


def old_thread(e, project, title="Build a website", compact=True):
    """A thread with file-writing steps, compacted twice when asked, so the model in it only sees summaries."""
    e.providers["fake"].replies = [
        [("write", {"path": "index.html", "content": FILE})], "The page is written: index.html has the heading.",
        "The colour is #0a7 because you asked for teal.", "Deployed to the staging box.", "Fixed the footer link.",
        "Added the contact form.", "Renamed the page to Shop.", "Wrote the README.", "All checks pass."]
    sid = e.create_session(str(project), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    e.store.update_session(sid, title=title)
    for ask in ["Make index.html with a heading", "Which colour did you pick and why?", "Deploy it", "Fix the footer", "Add a contact form", "Rename it to Shop",
                "Write a README", "Run the checks"]:
        asyncio.run(run_prompt(e, project, ask, sid=sid))
        if compact and ask in ("Deploy it", "Rename it to Shop"):
            e.providers["fake"].replies.insert(0, "ANSWER:\nSUMMARY-ONLY-TEXT the user wants a site")
            assert asyncio.run(e.compact_now(sid)) is True
    return sid


def tool_ctx(e, sid) -> ToolContext:
    s = e.store.get_session(sid)
    return ToolContext(session_id=sid, message_id="m", directory=s["location"]["directory"], permissions=e.gate_for(s, e.agent_for(s)), snapshots=None,  # type: ignore[arg-type]
                       emit=lambda *_: None, engine=e)


async def answer(e, decision, message=None):
    """Reply to the next approval card."""
    while not e.pending:
        await asyncio.sleep(0)
    req = next(iter(e.pending.values()))
    req.reply(decision, message)
    return req


def asked(e) -> list[dict]:
    return [ev for ev in e.events if ev["type"] == "permission.asked"]


def test_a_compacted_thread_is_read_from_its_first_message_exactly_as_it_was(home, tmp_path):
    p = FakeProvider([])
    e = make_engine(p)
    old = old_thread(e, tmp_path)
    stored = e.store.list_messages(old)
    assert sum(1 for m in stored if m["type"] == "compaction") == 2
    # the model working in the old thread no longer sees its beginning
    assert not any("Make index.html" in m.text for m in runmod.to_chat(stored))

    # a new thread, another model step: "read that session and carry on"
    p.replies = [[("threads", {"action": "read", "thread": "build a website"})], "Read it all. Carrying on from the checks."]
    new = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="ask")["id"]
    asyncio.run(run_prompt(e, tmp_path, "Read the session Build a Website and continue from where we stopped", sid=new))
    part = tool_results(e, new)[0]
    assert part["state"]["status"] == "completed" and not asked(e)  # the user named it: no question
    got = text_of(part)
    for said in ["Make index.html with a heading", "Which colour did you pick and why?", "The colour is #0a7 because you asked for teal.", "Deploy it", "Deployed to the staging box.",
                 "Run the checks", "All checks pass."]:
        assert said in got
    assert FILE in got  # a tool call's arguments, every character: quotes, tab, backslash, non-ASCII
    assert "SUMMARY-ONLY-TEXT" not in got and got.count(COMPACTED) == 2  # the summaries are not the thread
    assert "the whole thread" in got and "you have reached its last character" in got
    assert part["state"]["metadata"]["done"] is True and part["state"]["metadata"]["thread"]["id"] == old
    # and the model that asked really received it
    assert any(m.role == "tool" and FILE in m.text for m in p.requests[-1].messages)


def test_pages_put_end_to_end_are_the_whole_thread(home, tmp_path):
    e = make_engine(FakeProvider([]))
    old = old_thread(e, tmp_path)
    new = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    whole, index = transcript(e.store.list_messages(old))
    tool, ctx = ThreadsTool(e), tool_ctx(e, new)

    async def read_all():
        out, offset, calls = "", 0, 0
        while True:
            res = await tool.run(ctx, {"action": "read", "thread": old, "offset": offset, "limit": 300})
            assert not res.is_error and res.metadata["from"] == offset
            head, _, rest = res.text.partition("\n\n")  # the header, then the page itself, then the footer line
            out += rest.rsplit("\n\n", 1)[0]
            calls += 1
            if res.metadata["done"]:
                return out, calls
            assert f"offset={res.metadata['to']}" in res.text  # it says how to go on
            offset = res.metadata["to"]

    got, calls = asyncio.run(read_all())
    assert got == whole and calls > 3
    # a message number and a search hit lead to the same text
    third = next(x for x in index if x["n"] == 3)
    res = asyncio.run(tool.run(ctx, {"action": "read", "thread": old, "message": 3, "limit": 300}))
    assert res.metadata["from"] == third["offset"] and "==== #3 · " in res.text
    found = asyncio.run(tool.run(ctx, {"action": "search", "thread": old, "query": "TEAL"}))
    at = whole.casefold().find("teal")
    assert f"offset {at:,} · " in found.text and found.metadata["count"] >= 1
    outline = asyncio.run(tool.run(ctx, {"action": "outline", "thread": old}))
    assert "#1 · offset 0 · " in outline.text and "Run the checks" in outline.text and "All checks pass." not in outline.text
    text, end = page("a\n" * 50, 0, 31)
    assert end == 30 and text.endswith("\n")  # a page ends on a line break when one is near


def test_another_thread_asks_the_user_first(home, tmp_path):
    e = make_engine(FakeProvider([]))
    old = old_thread(e, tmp_path, compact=False)
    other = old_thread(e, tmp_path, title="Notes on pricing", compact=False)
    new = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="ask")["id"]
    e.store.add_message(new, {"type": "user", "text": "What did we do last week?"})
    tool, ctx = ThreadsTool(e), tool_ctx(e, new)

    async def go():
        e.loop = asyncio.get_running_loop()
        # looking for a thread is free; reading one is not
        listed = await tool.run(ctx, {"action": "list"})
        assert old in listed.text and "Build a website" in listed.text and not asked(e)
        # refused: the model is told, with what the user said
        res, req = await asyncio.gather(_denied(tool, ctx, old), answer(e, "reject", "not that one"))
        assert req.action == "threads" and req.metadata["kind"] == "thread" and req.metadata["thread"]["title"] == "Build a website" and "not that one" in res
        # allowed once: this thread may read it, page after page, without a second question
        res, _ = await asyncio.gather(tool.run(ctx, {"action": "read", "thread": old, "limit": 400}), answer(e, "once"))
        assert not res.is_error and len(asked(e)) == 2
        again = await tool.run(ctx, {"action": "read", "thread": old, "offset": res.metadata["to"], "limit": 400})
        assert not again.is_error and len(asked(e)) == 2
        # another thread is another question; "always" settles it for this thread, and is saved with it
        res, _ = await asyncio.gather(tool.run(ctx, {"action": "search", "thread": other, "query": "teal"}), answer(e, "always"))
        assert not res.is_error and len(asked(e)) == 3
        assert {"action": "threads", "resource": "*", "effect": "allow"} in e.store.get_session(new)["permissions"]
        e.__dict__.pop("_thread_reads")  # as after a restart: the saved rule still holds
        res = await tool.run(tool_ctx(e, new), {"action": "outline", "thread": old})
        assert not res.is_error and len(asked(e)) == 3

    asyncio.run(go())


async def _denied(tool, ctx, thread) -> str:
    from afh.engine.types import PermissionDenied

    try:
        await tool.run(ctx, {"action": "read", "thread": thread})
    except PermissionDenied as err:
        return err.message
    raise AssertionError("the thread was read without the user's yes")


def test_no_question_for_the_thread_itself_a_named_thread_or_full_access(home, tmp_path):
    e = make_engine(FakeProvider([]))
    old = old_thread(e, tmp_path)
    # its own beginning, lost to compaction, is still there to read
    mine = asyncio.run(ThreadsTool(e).run(tool_ctx(e, old), {"action": "read", "thread": "this"}))
    assert "Make index.html with a heading" in mine.text and not asked(e)
    # Full access never stops to ask
    full = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    assert not asyncio.run(ThreadsTool(e).run(tool_ctx(e, full), {"action": "read", "thread": old})).is_error and not asked(e)
    # named by the user: the title or the id, in a message they wrote themselves
    target = e.store.get_session(old)
    assert named_by_user([{"type": "user", "text": "carry on from  BUILD A   WEBSITE please"}], target)
    assert named_by_user([{"type": "user", "text": f"read {old}"}], target)
    assert not named_by_user([{"type": "synthetic", "text": "Build a website"}, {"type": "user", "text": "build something"}], target)
    assert not named_by_user([{"type": "user", "text": "anything"}], {"id": "ses_x", "title": "a"})  # a title too short to mean anything


def test_finding_a_thread_by_title(home, tmp_path):
    e = make_engine(FakeProvider([]))
    a = old_thread(e, tmp_path, title="Website redesign", compact=False)
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    b = old_thread(e, elsewhere, title="Website redesign", compact=False)
    c = old_thread(e, elsewhere, title="Website launch plan", compact=False)
    d = old_thread(e, tmp_path, title="Website copy", compact=False)
    new = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
    tool, ctx = ThreadsTool(e), tool_ctx(e, new)
    run = lambda inp: asyncio.run(tool.run(ctx, inp))  # noqa: E731
    assert run({"action": "read", "thread": "website redesign"}).metadata["thread"]["id"] == a  # this project's wins
    assert run({"action": "read", "thread": "launch"}).metadata["thread"]["id"] == c  # part of a title, when only one has it
    vague = run({"action": "read", "thread": "website"})
    assert vague.is_error and all(x in vague.text for x in (a, b, c, d))  # several: it lists them instead of guessing
    assert run({"action": "read", "thread": "no such thing"}).is_error
    here = run({"action": "list"})
    assert a in here.text and d in here.text and b not in here.text and "THIS THREAD" in here.text
    assert b in run({"action": "list", "all_projects": True}).text
    assert c in run({"action": "list", "query": "launch"}).text  # nothing here by that name: every project is searched


def test_who_gets_the_tool_and_what_is_shortened_last(home, tmp_path):
    e = make_engine(FakeProvider([]))
    names = lambda s: [t.spec.name for t in e.tools_for(s, e.agent_for(s))]  # noqa: E731
    s = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="ask")
    assert "threads" in names(s)
    gh = e.create_session(str(tmp_path), model={"providerID": "fake", "id": "m"}, mode="ask", origin="github")  # its prompt is an issue's text
    assert "threads" not in names(gh)
    # when the context fills up, other old tool output is shortened before pages of a thread
    big = "x" * 40_000
    msgs = [ChatMessage("user", "go")]
    for i in range(20):
        msgs.append(ChatMessage("tool", big, tool_call_id=f"c{i}", tool_name="threads" if i < 2 else "shell"))
    assert runmod.prune_history(msgs, 300_000) == 10
    tools = [m for m in msgs if m.role == "tool"]
    assert len(tools[0].text) == len(big) and len(tools[1].text) == len(big) and len(tools[2].text) < 1000
    # with nothing else left to shorten, a page goes too, and says how to get it back
    assert runmod.prune_history(msgs, 150_000) == 2 and "read that page again with the same offset" in tools[0].text
