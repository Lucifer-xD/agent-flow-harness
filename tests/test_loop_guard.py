"""A model that keeps repeating the same step is told to change course, then stopped; Kimi endpoints get
their reasoning sent back with tool-call turns."""

from __future__ import annotations

import asyncio
import json

from afh.engine import loopguard
from afh.engine.providers.openai_compat import OpenAICompatProvider, echoes_reasoning
from afh.engine.types import ChatMessage, ChatRequest, ProviderConfig, ToolCall

from test_engine_features import home, make_engine, notices  # noqa: F401 - home is a fixture


class TalkingProvider:
    """Each reply is (text, [(tool, input), ...]); the text streams before the calls, as real models do."""

    def __init__(self, replies):
        self.config = ProviderConfig(id="fake", name="Fake", kind="openai", base_url="http://fake")
        self.replies = list(replies)
        self.requests = []
        self.n = 0

    async def stream(self, req):
        self.requests.append(req)
        text, calls = self.replies.pop(0) if self.replies else ("All done.", [])
        if text:
            yield {"type": "text.delta", "text": text}
        for name, inp in calls:
            self.n += 1
            cid = f"call_{self.n}"
            yield {"type": "tool.start", "id": cid, "name": name}
            yield {"type": "tool.end", "id": cid, "name": name, "input": inp, "raw": json.dumps(inp)}
        yield {"type": "usage", "reasoning": 0, "input": 10, "output": 5, "cache_read": 0, "cache_write": 0}
        yield {"type": "finish", "reason": "tool_calls" if calls else "stop"}

    async def list_models(self):
        return []


SAME = "Still invalid. The account might be wrong, or the API has more requirements. Let me check cookies:"


def _run(e, project, text):
    async def go():
        e.loop = asyncio.get_running_loop()
        sid = e.create_session(str(project), model={"providerID": "fake", "id": "m"}, mode="full")["id"]
        await e.prompt(sid, text)
        await e.runs[sid].task
        return sid

    return asyncio.run(go())


def test_a_repeating_model_is_told_once_then_stopped(home, tmp_path):
    step = (SAME, [("shell", {"command": "python -c \"print('invalid')\""})])
    p = TalkingProvider([step] * 30)
    e = make_engine(p)
    sid = _run(e, tmp_path, "log in to the mobile api")
    loops = [m for m in notices(e, sid) if m["metadata"].get("notice") == "loop"]
    assert len(loops) == 2, loops
    told, stopped = loops
    assert "same thing 3 times" in told["text"] and "different approach" in told["text"]
    assert stopped["text"] == "" and stopped["metadata"]["label"].startswith("Stopped")
    # the model read the note on the step after it, and the run ended long before the scripted 30 steps
    assert any("[AFH: you have now done the same thing" in m.text for m in p.requests[3].messages if m.role == "user")
    assert len(p.requests) == 6 and len(p.replies) == 24
    # the note reaches the model; the stop line does not
    history = p.requests[-1].messages
    assert not any("Stopped: the model" in (m.text or "") for m in history)


def test_different_words_and_calls_are_not_a_loop(home, tmp_path):
    replies = [(f"Step {i}: now checking file number {i} for the bug we are after.", [("shell", {"command": f"python -c \"print({i})\""})]) for i in range(8)]
    p = TalkingProvider(replies + [("Found it and fixed it.", [])])
    e = make_engine(p)
    sid = _run(e, tmp_path, "find the bug")
    assert not [m for m in notices(e, sid) if m["metadata"].get("notice") == "loop"]
    assert len(p.requests) == 9


def test_waiting_on_a_job_is_not_a_loop():
    g = loopguard.LoopGuard()
    for _ in range(10):
        assert g.step("Still building, waiting a little longer before checking again.", [("jobs", {"action": "status", "id": "j1"})]) is None


def test_fixing_and_rerunning_the_tests_is_not_a_loop():
    g = loopguard.LoopGuard()
    run_tests = ("Now let me run the tests again to see if that fixed it:", [("shell", {"command": "pytest -q"})])
    for i in range(6):
        assert g.step(f"Changing line {i}.", [("edit", {"file": "a.py", "old": str(i), "new": str(i + 1)})]) is None
        assert g.step(*run_tests) is None
    # without edits in between, the same check three times is a loop
    assert g.step(*run_tests) is None and g.step(*run_tests)[0] == "note"


def test_pressing_a_key_or_scrolling_again_is_not_a_loop():
    g = loopguard.LoopGuard()
    for _ in range(8):
        assert g.step("", [("browser", {"action": "press", "key": "PageDown"})]) is None
        assert g.step("", [("computer", {"action": "scroll", "direction": "down"})]) is None


def test_same_call_with_no_words_counts_too():
    g = loopguard.LoopGuard()
    call = [("browser", {"action": "click", "x": 10, "y": 20})]
    assert g.step("", call) is None and g.step("", call) is None
    verdict = g.step("", call)
    assert verdict and verdict[0] == "note" and "browser" in verdict[1]
    assert g.step("", [("browser", {"action": "screenshot"})]) is None
    assert g.step("", call) is None and g.step("", call) is None
    assert g.step("", call)[0] == "stop"


def test_kimi_endpoints_get_their_reasoning_back():
    def cfg(url, **extra):
        return ProviderConfig(id="x", name="X", kind="openai", base_url=url, extra=extra)

    assert echoes_reasoning(cfg("https://api.kimi.com/coding/v1"))  # the China coding plan, added from models.dev
    assert echoes_reasoning(cfg("https://api.moonshot.cn/v1"))
    assert not echoes_reasoning(cfg("https://api.kimi.com/coding/v1", echo_reasoning=False))
    assert not echoes_reasoning(cfg("https://api.deepseek.com/v1"))  # DeepSeek refuses reasoning in the history
    assert not echoes_reasoning(cfg("https://notkimi.com.example.org/v1"))
    assert echoes_reasoning(cfg("http://127.0.0.1:9000/v1", echo_reasoning=True))

    prov = OpenAICompatProvider(cfg("https://api.kimi.com/coding/v1"))
    req = ChatRequest(model="k3", system="", messages=[
        ChatMessage("user", "hi"),
        ChatMessage("assistant", "", reasoning="I should list the files first.", tool_calls=[ToolCall("c1", "list", {"path": "."})]),
        ChatMessage("tool", "a.py", tool_call_id="c1", tool_name="list"),
    ])
    sent = prov.translate_messages(req)
    assert sent[1]["reasoning_content"] == "I should list the files first."
