"""The ChatGPT web lane: the proof-of-work solver and the emulated-tool-call bridge that lets a
plain chat model drive the harness. (The live transport is exercised by the E2E script.)"""

from __future__ import annotations

import hashlib

from afh.engine.providers import chatgpt_bridge as br
from afh.engine.providers.pow import PoW
from afh.engine.types import ChatMessage, ToolCall, ToolSpec


def tools():
    return [ToolSpec("shell", "Run a command", {"type": "object", "properties": {"command": {"type": "string"}}}),
            ToolSpec("read", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})]


# ---- proof of work ----

def test_pow_answer_meets_difficulty():
    p = PoW("UA/1.0")
    for diff in ("0", "0f", "0fffff"):
        base = p.answer("seed-123", diff)
        assert hashlib.sha3_512(("seed-123" + base).encode()).hexdigest()[:len(diff)] <= diff


def test_pow_proof_prefixes_and_cache():
    p = PoW()
    rp = p.requirements_proof()
    assert rp.startswith("gAAAAAC") and p.requirements_proof() == rp  # cached
    cp = p.conversation_proof("0.42", "0fffff")
    assert cp.startswith("gAAAAAB")
    assert hashlib.sha3_512(("0.42" + cp[len("gAAAAAB"):]).encode()).hexdigest()[:6] <= "0fffff"


# ---- preamble + history ----

def test_preamble_lists_tools_and_protocol():
    pre = br.tool_preamble(tools(), "auto")
    assert br.OPEN in pre and "shell" in pre and "read" in pre and "Harness protocol" in pre
    assert "must request at least one action" in br.tool_preamble(tools(), "required")
    assert 'must request the action "read"' in br.tool_preamble(tools(), {"name": "read"})


def test_transform_history_blocks_and_collapses():
    msgs = [
        ChatMessage(role="user", text="hi"),
        ChatMessage(role="assistant", text="Let me look.", tool_calls=[ToolCall("c1", "read", {"path": "a.txt"})]),
        ChatMessage(role="tool", text="line one", tool_call_id="c1", tool_name="read"),
        ChatMessage(role="tool", text="line two", tool_call_id="c2", tool_name="shell"),
    ]
    turns = br.transform_history(msgs)
    assert turns[0] == {"role": "user", "text": "hi", "images": []}
    assert br.OPEN in turns[1]["text"] and '"read"' in turns[1]["text"] and turns[1]["role"] == "assistant"
    # the two tool results collapse into one user turn
    assert len([t for t in turns if t["role"] == "user" and t["text"].startswith("<tool_response")]) == 1
    collapsed = turns[-1]["text"]
    assert "line one" in collapsed and "line two" in collapsed and collapsed.count("<tool_response") == 2


def test_inject_preamble_first_and_reminder_last():
    turns = [{"role": "user", "text": "do a thing", "images": []},
             {"role": "assistant", "text": "ok", "images": []},
             {"role": "user", "text": "<tool_response name=\"read\">x</tool_response>", "images": []}]
    out = br.inject_preamble(turns, "PREAMBLE", ["read", "shell"])
    assert out[0]["text"].startswith("PREAMBLE") and "do a thing" in out[0]["text"]
    assert "Harness reminder" in out[-1]["text"] and "read, shell" in out[-1]["text"]


# ---- parsing replies ----

def test_extract_single_call_and_text():
    text = 'Sure, let me check.\n<tool_call>\n{"name": "read", "arguments": {"path": "a.txt"}}\n</tool_call>'
    clean, calls = br.extract_tool_calls(text)
    assert clean == "Sure, let me check."
    assert len(calls) == 1 and calls[0]["name"] == "read" and calls[0]["input"] == {"path": "a.txt"}


def test_extract_ignores_quoted_protocol():
    text = "Here is how the format looks:\n```\nexplain <tool_call> then a block\n```\nok"
    clean, calls = br.extract_tool_calls(text)
    assert calls == [] and "<tool_call>" in clean


def test_extract_lenient_windows_path_and_unterminated():
    # lone backslashes in a Windows path, and no closing tag at the end of the stream
    text = '<tool_call>{"name":"read","arguments":{"path":"C:\\Users\\a.txt"}}'
    _clean, calls = br.extract_tool_calls(text)
    assert len(calls) == 1 and calls[0]["input"]["path"] == "C:\\Users\\a.txt"


def test_extract_multiple_blocks():
    text = ('<tool_call>{"name":"read","arguments":{"path":"a"}}</tool_call>\n'
            '<tool_call>{"name":"shell","arguments":{"command":"ls"}}</tool_call>')
    clean, calls = br.extract_tool_calls(text)
    assert clean == "" and [c["name"] for c in calls] == ["read", "shell"]


def test_block_wrapped_in_code_fence_is_a_real_call():
    text = '```\n<tool_call>{"name":"read","arguments":{"path":"a"}}</tool_call>\n```'
    _clean, calls = br.extract_tool_calls(text)
    assert len(calls) == 1 and calls[0]["name"] == "read"


# ---- nudging ----

def test_unfulfilled_intent_detection():
    assert br.looks_like_unfulfilled_intent("Let me read the file first.")
    assert br.looks_like_unfulfilled_intent("I can't verify the contents without checking.")
    assert br.looks_like_unfulfilled_intent("")
    assert not br.looks_like_unfulfilled_intent("The file has 42 lines.")
    assert not br.looks_like_unfulfilled_intent("Which file do you mean?")


# ---- streaming splitter ----

def test_splitter_holds_back_partial_opener():
    s = br.ToolCallSplitter()
    out = "".join(s.push(c) for c in 'Hello <tool_call>{"name":"read","arguments":{"path":"a"}}</tool_call>')
    assert out.strip() == "Hello"  # the opener and block never leak
    text, calls, unsent = s.finish()
    assert len(calls) == 1 and calls[0]["name"] == "read" and unsent == ""


def test_splitter_plain_text_passes_through():
    s = br.ToolCallSplitter()
    out = "".join(s.push(c) for c in "Just a normal answer.")
    assert out == "Just a normal answer."
    _text, calls, _unsent = s.finish()
    assert calls == []


# ---- live transport, offline (mock transport) ----

import asyncio
import json
import time

import httpx

from afh.engine.providers.chatgpt_web import ChatGPTWebProvider
from afh.engine.types import ChatRequest, ProviderConfig


def _sse(*frames: dict) -> bytes:
    """Frames are dicts, serialised with correct JSON escaping (as the backend sends them)."""
    return ("".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n").encode()


def _msg(mid, parts, status="in_progress", ct="text", **md):
    return {"message": {"id": mid, "author": {"role": "assistant"}, "content": {"content_type": ct, "parts": parts},
                        "metadata": {"message_type": "next", **md}, "status": status}}


def _append(text):
    return {"p": "/message/content/parts/0", "o": "append", "v": text}


def _status(v):
    return {"p": "/message/status", "o": "replace", "v": v}


def _provider_for(bodies):
    """bodies: a list of SSE byte-bodies, one per conversation call (to exercise the nudge loop)."""
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sentinel/chat-requirements"):
            return httpx.Response(200, json={"token": "tkn", "proofofwork": {"required": True, "seed": "0.5", "difficulty": "0fffff"}})
        if request.url.path.endswith("/backend-api/conversation"):
            b = bodies[min(seen["n"], len(bodies) - 1)]
            seen["n"] += 1
            return httpx.Response(200, content=b, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    cfg = ProviderConfig(id="chatgpt-chat", name="ChatGPT chat", kind="chatgpt-web", base_url="https://chatgpt.com",
                         auth={"type": "chatgpt-web", "access": "tok", "expires": time.time() + 9999, "ua": "UA/1", "device_id": "dev-1"})
    return ChatGPTWebProvider(cfg, transport=httpx.MockTransport(handler)), seen


def _run(provider, req):
    async def go():
        return [ev async for ev in provider.stream(req)]
    return asyncio.run(go())


def _req(tools_on=True):
    return ChatRequest(model="gpt-5-6", system="You are helpful.", messages=[ChatMessage(role="user", text="how many lines in a.txt?")],
                       tools=tools() if tools_on else [])


def test_stream_plain_answer():
    p, _ = _provider_for([_sse(_msg("a1", ["Hello there."]), _status("finished_successfully"))])
    evs = _run(p, _req(tools_on=False))
    text = "".join(e["text"] for e in evs if e["type"] == "text.delta")
    assert text == "Hello there."
    assert evs[-1] == {"type": "finish", "reason": "stop"}
    assert not any(e["type"] == "tool.start" for e in evs)


def test_stream_emits_tool_call_from_text_protocol():
    p, _ = _provider_for([_sse(
        _msg("a1", ["Let me check."]),
        _append('\n<tool_call>\n{"name": "read", "arguments": {"path": "a.txt"}}\n</tool_call>'),
        _status("finished_successfully"),
    )])
    evs = _run(p, _req())
    text = "".join(e["text"] for e in evs if e["type"] == "text.delta")
    assert text.strip() == "Let me check."  # the block never leaks as visible text
    starts = [e for e in evs if e["type"] == "tool.start"]
    ends = [e for e in evs if e["type"] == "tool.end"]
    assert len(starts) == 1 and starts[0]["name"] == "read"
    assert ends[0]["input"] == {"path": "a.txt"}
    assert evs[-1] == {"type": "finish", "reason": "tool_calls"}


def test_stream_reasoning_then_answer():
    p, _ = _provider_for([_sse(
        {"message": {"id": "t1", "author": {"role": "assistant"}, "content": {"content_type": "thoughts", "thoughts": [{"summary": "Thinking", "content": "about it"}]}, "status": "in_progress"}},
        _msg("a1", ["The answer is 42."], status="finished_successfully"),
    )])
    evs = _run(p, _req(tools_on=False))
    reasoning = "".join(e["text"] for e in evs if e["type"] == "reasoning.delta")
    text = "".join(e["text"] for e in evs if e["type"] == "text.delta")
    assert "Thinking" in reasoning and "about it" in reasoning
    assert text == "The answer is 42."


def test_stream_nudges_when_model_announces_without_block():
    bodies = [
        _sse(_msg("a1", ["I will read the file now."], status="finished_successfully")),
        _sse(_msg("a2", ['<tool_call>{"name": "read", "arguments": {"path": "a.txt"}}</tool_call>'], status="finished_successfully")),
    ]
    p, seen = _provider_for(bodies)
    evs = _run(p, _req())
    assert seen["n"] == 2  # it nudged once, then got the block
    assert [e for e in evs if e["type"] == "tool.start"][0]["name"] == "read"
    assert evs[-1]["reason"] == "tool_calls"


# ---- chrome import: paste parsing + cookie decryption ----

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from afh.engine import chrome_import as ci


def test_parse_paste_bare_token():
    out = ci.parse_paste("  eyJ" + "a" * 50 + "  ")
    assert out == {"session_token": "eyJ" + "a" * 50}


def test_parse_paste_session_export_json():
    out = ci.parse_paste('{"session_token": "' + "t" * 40 + '", "deviceId": "dev-9", "userAgent": "UA/9"}')
    assert out["session_token"] == "t" * 40 and out["device_id"] == "dev-9" and out["ua"] == "UA/9"


def test_parse_paste_auth_session_reply():
    out = ci.parse_paste('{"accessToken": "' + "a" * 60 + '", "expires": "2026-12-01T00:00:00Z", "user": {"email": "x@y.z"}}')
    assert out["access"] == "a" * 60 and out["expires"] == "2026-12-01T00:00:00Z"


def test_parse_paste_rejects_junk():
    import pytest
    for bad in ("", "hello world", "{not json"):
        with pytest.raises(ci.ImportError_):
            ci.parse_paste(bad)


def test_decrypt_v10_roundtrip():
    key = os.urandom(32)
    nonce = os.urandom(12)
    secret = "session-value-é\U0001f600"
    enc = b"v10" + nonce + AESGCM(key).encrypt(nonce, secret.encode(), None)
    assert ci._decrypt(enc, key) == secret


def test_decrypt_v20_is_rejected_cleanly():
    import pytest
    with pytest.raises(ci.ImportError_) as e:
        ci._decrypt(b"v20" + os.urandom(40), os.urandom(32))
    assert e.value.reason == "app_bound"
