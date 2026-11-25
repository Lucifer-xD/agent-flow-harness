"""A model that ends its turn without an answer: it is sent back, and when that doesn't help the user is told."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from afh.engine.providers import openai_compat
from afh.engine.providers.anthropic import AnthropicProvider
from afh.engine.providers.gemini import GeminiProvider
from afh.engine.providers.openai_compat import OpenAICompatProvider
from afh.engine.providers.openai_responses import OpenAIResponsesProvider
from afh.engine.runner import to_chat
from afh.engine.stall import TRIES, Stalls
from afh.engine.types import ChatMessage, ChatRequest, ProviderConfig

from test_engine_features import FakeProvider, home, make_engine, run_prompt  # noqa: F401 - home is a fixture


def play(fake, tmp_path, text):
    e = make_engine(fake)
    return e.store.list_messages(asyncio.run(run_prompt(e, tmp_path, text))["id"])


def msg(text="", think="", ending="", tools=()):
    content = ([{"type": "reasoning", "text": think}] if think else []) + ([{"type": "text", "text": text}] if text else []) + [{"type": "tool", "id": t, "name": t, "state": {}} for t in tools]
    return {"content": content, **({"ending": ending} if ending else {})}


class Call:
    def __init__(self, name): self.name = name


def test_a_real_answer_ends_the_run():
    assert Stalls().check(msg("All done.", "thinking"), worked=True) is None
    assert Stalls().check(msg("Here is the list:\n- a\n- b"), worked=True) is None
    assert Stalls().check(msg("It prints `</tool_call>` at the end, as asked."), worked=True) is None


def test_thinking_without_an_answer_is_sent_back_with_its_thoughts():
    s = Stalls().check(msg(think="First the tests. Then the drivers table."), worked=False)
    assert "after thinking" in s.label and "AFH asked it to carry on" in s.label
    assert "Then the drivers table." in s.text


def test_an_empty_reply_after_the_answer_is_a_real_ending():
    s = Stalls()
    s.progress(msg("The table is there and the data is safe.", tools=["todo"]), [Call("todo")])
    assert s.check(msg(), worked=True) is None
    s.progress(msg("Let me look.", tools=["read"]), [Call("read")])
    assert s.check(msg(), worked=True).text


@pytest.mark.parametrize("m,words", [
    (msg(think="x", ending="length"), "output limit"),
    (msg("Half an ans", ending="length"), "Continue exactly where you stopped"),
    (msg(ending="cut"), "connection closed"),
    (msg("Half an ans", ending="cut"), "Continue exactly where you stopped"),
    (msg(ending="malformed"), "malformed"),
    (msg("Running it.", ending="cut", tools=["write"]), "in the middle of a tool call"),
    (msg("<tool_call>{\"name\": \"read\"}</tool_call>"), "wrote a tool call as text"),
    (msg(think="I will read it <|tool_calls_section_end|>"), "wrote a tool call as text"),
])
def test_every_way_a_reply_can_end_too_early(m, words):
    assert words in Stalls().check(m, worked=True).text


def test_a_reply_that_hit_the_limit_gets_more_room():
    s = Stalls()
    before = s.max_tokens
    s.check(msg(think="x", ending="length"), worked=True)
    assert s.max_tokens == before * 2


def test_an_announced_step_is_sent_back_once():
    s = Stalls()
    assert "announcing a next step" in s.check(msg("Now I'll update the schema:"), worked=True).text
    assert s.check(msg("Now I'll update the schema:"), worked=True) is None
    assert Stalls().check(msg("Which one do you want:"), worked=False) is None


def test_after_a_few_tries_the_user_is_told():
    s = Stalls()
    for _ in range(TRIES):
        assert s.check(msg(think="hm"), worked=True).text
    end = s.check(msg(think="hm"), worked=True)
    assert end.text == "" and end.label.startswith("Stopped:") and "Send a message to continue" in end.label
    s.progress(msg(tools=["read"]), [Call("read")])
    assert s.check(msg(think="hm"), worked=True).text  # it worked in between: a new stall


def test_a_refusal_is_shown_not_argued_with():
    s = Stalls().check(msg(ending="refusal"), worked=False)
    assert s.text == "" and "declined" in s.label
    assert Stalls().check(msg("I can't help with that.", ending="refusal"), worked=False) is None


# ---- how the providers say a reply ended ---------------------------------------------------------


def ends(provider, events, done=False):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + ("data: [DONE]\n\n" if done else "")
    cls, kind = provider
    p = cls(ProviderConfig(id="p1", name="P", kind=kind, base_url="https://x.example/v1", api_key="k"),
            transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)))

    async def go():
        return [e async for e in p.stream(ChatRequest(model="m", system="", messages=[ChatMessage("user", "hi")]))]
    return [e["reason"] for e in asyncio.run(go()) if e["type"] == "finish"][-1]


CHAT = (OpenAICompatProvider, "openai")


def chunk(finish=None, **delta):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def test_openai_compatible_streams_that_close_early(monkeypatch):
    monkeypatch.setattr(openai_compat, "_SAYS_WHEN_DONE", set())
    assert ends(CHAT, [chunk(reasoning_content="hm")]) == "cut"
    assert ends(CHAT, [chunk(content="Hello.")]) == "stop"  # a server that never says when it is done
    assert ends(CHAT, [chunk(content="Hello."), chunk("stop")], done=True) == "stop"
    assert ends(CHAT, [chunk(content="Hel")]) == "cut"  # this one does: so now it was cut
    assert ends(CHAT, [chunk("content_filter")]) == "refusal"
    assert ends(CHAT, [chunk("length", reasoning_content="hm")]) == "length"


def test_the_other_protocols_that_close_early():
    r = (OpenAIResponsesProvider, "openai-responses")
    assert ends(r, [{"type": "response.reasoning_text.delta", "delta": "hm"}]) == "cut"
    assert ends(r, [{"type": "response.output_text.delta", "delta": "Hi"}, {"type": "response.completed", "response": {}}]) == "stop"
    a = (AnthropicProvider, "anthropic")
    assert ends(a, [{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "Hi"}}]) == "cut"
    assert ends(a, [{"type": "message_delta", "delta": {"stop_reason": "end_turn"}}, {"type": "message_stop"}]) == "stop"
    g = (GeminiProvider, "gemini")
    part = {"content": {"parts": [{"text": "hm", "thought": True}]}}
    assert ends(g, [{"candidates": [part]}]) == "cut"
    assert ends(g, [{"candidates": [{**part, "finishReason": "MALFORMED_FUNCTION_CALL"}]}]) == "malformed"
    assert ends(g, [{"candidates": [{**part, "finishReason": "STOP"}]}]) == "stop"


# ---- a whole run ----------------------------------------------------------------------------------


class Thinker(FakeProvider):
    """Replies are ("think", text) or ("halfcall", name) besides what FakeProvider plays."""

    async def stream(self, req):
        reply = self.replies[0] if self.replies else None
        if isinstance(reply, tuple):
            self.replies.pop(0)
            self.requests.append(req)
            yield {"type": "reasoning.delta", "text": reply[1]}
            if reply[0] == "halfcall":
                yield {"type": "tool.start", "id": "c9", "name": reply[1]}
                yield {"type": "tool.delta", "id": "c9", "text": "{\"pa"}
            yield {"type": "finish", "reason": "cut" if reply[0] == "halfcall" else "stop"}
            return
        async for ev in super().stream(req):
            yield ev


def test_a_run_goes_on_after_thinking_with_no_answer(home, tmp_path):
    fake = Thinker([("think", "I should check the drivers table"), "Yes, it is finished."])
    msgs = play(fake, tmp_path, "is it done?")
    notes = [m for m in msgs if m["type"] == "synthetic"]
    assert [n["metadata"]["notice"] for n in notes] == ["stalled"]
    assert msgs[-1]["content"][-1]["text"] == "Yes, it is finished."
    assert "drivers table" in fake.requests[1].messages[-1].text


def test_a_half_written_call_is_not_left_hanging(home, tmp_path):
    fake = Thinker([("halfcall", "read"), "Done."])
    msgs = play(fake, tmp_path, "go")
    part = next(p for m in msgs if m["type"] == "assistant" for p in m["content"] if p["type"] == "tool")
    assert part["state"]["status"] == "error" and "cut off" in part["state"]["error"]["message"]
    assert msgs[-1]["content"][-1]["text"] == "Done."


def test_a_run_that_never_answers_ends_with_a_notice(home, tmp_path):
    fake = Thinker([("think", "hm")] * (TRIES + 1))
    msgs = play(fake, tmp_path, "go")
    assert msgs[-1]["type"] == "synthetic" and msgs[-1]["metadata"]["label"].startswith("Stopped:")
    assert len(fake.requests) == TRIES + 1


def test_a_failed_result_reaches_the_model_once():
    m = {"type": "assistant", "content": [{"type": "tool", "id": "a", "name": "chrome", "state": {"status": "error", "input": {}, "error": {"message": "Not connected"}, "content": [{"type": "text", "text": "Not connected. Open it."}]}}]}
    assert to_chat([m])[-1].text == "Error: Not connected. Open it."
