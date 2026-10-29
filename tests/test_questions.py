"""The `question` tool: the model pauses, the user answers in a card, the run continues."""

from __future__ import annotations

import asyncio

import pytest

from afh.engine import permissions as perm
from afh.engine.questions import QuestionTool, clean, report
from afh.engine.types import PermissionDenied, ToolContext


def gate_and_pending():
    pending: dict = {}
    events: list = []
    g = perm.Gate("s", perm.rules_for_mode("readonly"), events.append, pending, lambda r: None)  # even read-only asks
    return g, pending, events


def ctx(g) -> ToolContext:
    return ToolContext(session_id="s", message_id="m", directory=".", permissions=g, snapshots=None, emit=lambda *_: None)  # type: ignore[arg-type]


def test_clean_validates_and_trims():
    qs = clean([{"question": "Which DB?", "header": "  Database  ", "options": ["Postgres", {"label": "SQLite", "description": "  file based "}, "Postgres"]}])
    assert qs[0]["header"] == "Database" and qs[0]["multiple"] is False
    assert [o["label"] for o in qs[0]["options"]] == ["Postgres", "SQLite"]  # dupes dropped
    assert qs[0]["options"][1]["description"] == "file based"
    with pytest.raises(ValueError):
        clean([])
    with pytest.raises(ValueError):
        clean([{"question": ""}])
    with pytest.raises(ValueError):
        clean([{"question": "q", "options": []}] * 7)


def test_report_maps_answers_to_questions():
    qs = clean([{"question": "Which DB?", "options": ["Postgres", "SQLite"]},
                {"question": "Extras?", "options": ["Auth", "Billing"], "multiple": True}])
    text, norm = report(qs, [{"selected": ["SQLite"]}, {"selected": ["Auth", "Billing"], "other": "and search"}])
    assert norm[0]["selected"] == ["SQLite"] and norm[1]["selected"] == ["Auth", "Billing"]
    assert "SQLite" in text and "Auth, Billing" in text and "and search" in text


def test_question_waits_then_returns_the_answer():
    async def go():
        g, pending, events = gate_and_pending()

        async def answer_when_asked():
            while not pending:
                await asyncio.sleep(0)
            req = next(iter(pending.values()))
            assert req.action == "question" and req.metadata["questions"][0]["question"] == "Which DB?"
            req.reply("answer", None, [{"selected": ["SQLite"], "other": ""}])

        res, _ = await asyncio.gather(
            QuestionTool().run(ctx(g), {"questions": [{"question": "Which DB?", "options": ["Postgres", "SQLite"]}]}),
            answer_when_asked(),
        )
        assert not res.is_error and "SQLite" in res.text
        assert res.metadata["answers"] == [{"selected": ["SQLite"], "other": ""}]
        assert not pending  # cleaned up
        assert [e["type"] for e in events] == ["permission.asked", "permission.replied"]

    asyncio.run(go())


def test_skip_and_stop():
    async def go():
        g, pending, _ = gate_and_pending()

        async def reply_with(decision, **kw):
            while not pending:
                await asyncio.sleep(0)
            next(iter(pending.values())).reply(decision, kw.get("message"), kw.get("answers"))

        res, _ = await asyncio.gather(QuestionTool().run(ctx(g), {"questions": [{"question": "q?", "options": ["a"]}]}), reply_with("dismiss"))
        assert not res.is_error and res.metadata["dismissed"] and "closed the questions" in res.text

        with pytest.raises(PermissionDenied):
            await asyncio.gather(QuestionTool().run(ctx(g), {"questions": [{"question": "q?", "options": ["a"]}]}), reply_with("reject", message="Interrupted"))

    asyncio.run(go())


def test_bad_input_is_an_error_not_a_prompt():
    res = asyncio.run(QuestionTool().run(ctx(gate_and_pending()[0]), {"questions": []}))
    assert res.is_error and "question" in res.text
