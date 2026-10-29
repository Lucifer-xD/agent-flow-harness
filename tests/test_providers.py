"""Tests for afh.engine.providers. Everything runs offline against httpx.MockTransport; the
live smoke test at the bottom only runs when AFH_LIVE_PROVIDER_JSON points to a JSON file."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from afh.engine.providers import AnthropicProvider, GeminiProvider, OpenAICompatProvider, ProviderError, catalog, make_provider
from afh.engine.providers.sse import iter_sse
from afh.engine.types import ChatMessage, ChatRequest, ModelInfo, ProviderConfig, ToolCall, ToolSpec

PNG = "data:image/png;base64,iVBORw0KGgo="

# ---- helpers ----------------------------------------------------------------------------


def sse(*events, sep: str = "\n") -> bytes:
    """SSE body from dicts (JSON) or raw strings; ``sep`` lets a test use CRLF."""
    chunks = []
    for ev in events:
        data = ev if isinstance(ev, str) else json.dumps(ev)
        chunks.append(f"data: {data}{sep}{sep}")
    return "".join(chunks).encode()


class Server:
    """A MockTransport that records requests and answers from a queue (or a callable)."""

    def __init__(self, *responses):
        self.requests: list[httpx.Request] = []
        self.responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def body(self, i: int = 0) -> dict:
        return json.loads(self.requests[i].content)


def stream_response(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


def run(coro):
    return asyncio.run(coro)


async def _collect(provider, req):
    return [ev async for ev in provider.stream(req)]


def collect(provider, req) -> list[dict]:
    return run(_collect(provider, req))


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def text_of(events: list[dict], kind: str = "text.delta") -> str:
    return "".join(e["text"] for e in events if e["type"] == kind)


def cfg(kind: str, **extra) -> ProviderConfig:
    base = {"openai": "https://api.example.com/v1", "anthropic": "https://api.anthropic.com", "gemini": "https://generativelanguage.googleapis.com"}[kind]
    return ProviderConfig(id=f"test-{kind}", name="Test", kind=kind, base_url=base, api_key="sk-test", extra=extra)


def tool_round_trip() -> list[ChatMessage]:
    return [
        ChatMessage(role="user", text="Read a.txt", images=[PNG]),
        ChatMessage(role="assistant", text="Reading.", reasoning="I should read it.",
                    tool_calls=[ToolCall(id="call_1", name="read", input={"path": "a.txt"})]),
        ChatMessage(role="tool", text="hello", tool_call_id="call_1", tool_name="read"),
    ]


READ_TOOL = ToolSpec(name="read", description="Read a file", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False})


# ---- sse.py -----------------------------------------------------------------------------


def test_iter_sse_multiline_crlf_comments_and_done():
    body = (
        ": keep-alive\r\n"
        "event: message\r\n"
        "data: first\r\n"
        "data: second\r\n"
        "\r\n"
        "data:{\"x\": 1}\r\n\r\n"
        "data: [DONE]\r\n\r\n"
        "data: after-done\r\n\r\n"
    ).encode()
    server = Server(stream_response(body))

    async def go():
        async with httpx.AsyncClient(transport=server.transport) as client:
            async with client.stream("GET", "http://x/") as resp:
                return [p async for p in iter_sse(resp)]

    assert run(go()) == ["first\nsecond", '{"x": 1}']


def test_iter_sse_flushes_last_event_without_blank_line():
    server = Server(stream_response(b"data: tail"))

    async def go():
        async with httpx.AsyncClient(transport=server.transport) as client:
            async with client.stream("GET", "http://x/") as resp:
                return [p async for p in iter_sse(resp)]

    assert run(go()) == ["tail"]


# ---- OpenAI-compatible ------------------------------------------------------------------


def oa_chunk(delta: dict | None = None, finish: str | None = None, usage: dict | None = None) -> dict:
    chunk: dict = {"id": "c1", "object": "chat.completion.chunk", "model": "m", "choices": []}
    if delta is not None or finish is not None:
        chunk["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish}]
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def test_openai_text_reasoning_usage_and_finish():
    body = sse(
        oa_chunk({"role": "assistant", "reasoning_content": "Let me "}),
        oa_chunk({"reasoning_content": "think."}),
        oa_chunk({"content": "Hello"}),
        "not json at all {",
        oa_chunk({"content": " world"}),
        oa_chunk({}, finish="stop"),
        oa_chunk(usage={"prompt_tokens": 12, "completion_tokens": 7, "completion_tokens_details": {"reasoning_tokens": 3},
                        "prompt_tokens_details": {"cached_tokens": 4}}),
        "[DONE]",
    )
    server = Server(stream_response(body))
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="be brief", messages=[ChatMessage(role="user", text="hi")]))

    assert types(events) == ["reasoning.delta", "reasoning.delta", "text.delta", "text.delta", "usage", "finish"]
    assert text_of(events, "reasoning.delta") == "Let me think."
    assert text_of(events) == "Hello world"
    assert events[-2] == {"type": "usage", "input": 8, "output": 7, "reasoning": 3, "cache_read": 4, "cache_write": 0}
    assert events[-1] == {"type": "finish", "reason": "stop"}
    req = server.requests[0]
    assert req.headers["authorization"] == "Bearer sk-test"
    assert str(req.url) == "https://api.example.com/v1/chat/completions"
    sent = server.body()
    assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True}
    assert sent["messages"] == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]


def test_openai_streamed_tool_call_in_three_chunks():
    body = sse(
        oa_chunk({"role": "assistant", "content": None, "tool_calls": [{"index": 0, "id": "call_abc", "type": "function", "function": {"name": "read", "arguments": ""}}]}),
        oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"path"'}}]}),
        oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": ': "a.txt"'}}]}),
        oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}),
        oa_chunk({}, finish="tool_calls"),
        "[DONE]",
    )
    server = Server(stream_response(body))
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="read it")], tools=[READ_TOOL]))

    assert events == [
        {"type": "tool.start", "id": "call_abc", "name": "read"},
        {"type": "tool.delta", "id": "call_abc", "text": '{"path"'},
        {"type": "tool.delta", "id": "call_abc", "text": ': "a.txt"'},
        {"type": "tool.delta", "id": "call_abc", "text": "}"},
        {"type": "tool.end", "id": "call_abc", "name": "read", "input": {"path": "a.txt"}, "raw": '{"path": "a.txt"}'},
        {"type": "finish", "reason": "tool_calls"},
    ]
    assert server.body()["tools"] == [{"type": "function", "function": {"name": "read", "description": "Read a file", "parameters": READ_TOOL.parameters}}]


def test_openai_parallel_tool_calls_interleaved_by_index():
    body = sse(
        oa_chunk({"tool_calls": [{"index": 0, "id": "call_0", "function": {"name": "read", "arguments": ""}}]}),
        oa_chunk({"tool_calls": [{"index": 1, "id": "call_1", "function": {"name": "grep", "arguments": ""}}]}),
        oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"path":'}}, {"index": 1, "function": {"arguments": '{"q": "x"'}}]}),
        oa_chunk({"tool_calls": [{"index": 1, "function": {"arguments": "}"}}]}),
        oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": ' "b.txt"'}}]}),  # never closed → malformed
        oa_chunk({}, finish="tool_calls"),
    )
    server = Server(stream_response(body))
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="go")]))

    assert types(events) == ["tool.start", "tool.start", "tool.delta", "tool.delta", "tool.delta", "tool.delta", "tool.end", "tool.end", "finish"]
    assert [e["id"] for e in events if e["type"] == "tool.delta"] == ["call_0", "call_1", "call_1", "call_0"]
    ends = [e for e in events if e["type"] == "tool.end"]
    assert ends[0] == {"type": "tool.end", "id": "call_0", "name": "read", "input": None, "raw": '{"path": "b.txt"'}
    assert ends[1] == {"type": "tool.end", "id": "call_1", "name": "grep", "input": {"q": "x"}, "raw": '{"q": "x"}'}
    assert events[-1]["reason"] == "tool_calls"


def test_openai_length_finish_and_tool_end_without_finish_reason():
    body = sse(oa_chunk({"content": "trunc"}), oa_chunk({}, finish="length"))
    p = OpenAICompatProvider(cfg("openai"), transport=Server(stream_response(body)).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[]))
    assert events[-1] == {"type": "finish", "reason": "length"}

    # Server drops the connection without a finish_reason: calls still get their tool.end.
    body = sse(oa_chunk({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "f", "arguments": "{}"}}]}))
    p = OpenAICompatProvider(cfg("openai"), transport=Server(stream_response(body)).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[]))
    assert types(events) == ["tool.start", "tool.delta", "tool.end", "finish"]
    assert events[2]["input"] == {} and events[3]["reason"] == "tool_calls"


def test_openai_http_401_error():
    err = {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error", "code": "invalid_api_key"}}
    server = Server(httpx.Response(401, json=err))
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="hi")]))
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "error" and ev["status"] == 401 and ev["kind"] == "http"
    assert ev["message"] == "Incorrect API key provided"
    assert json.loads(ev["response"]) == err


def test_openai_network_error():
    server = Server(httpx.ConnectError("[WinError 10061] No connection could be made"))
    p = OpenAICompatProvider(ProviderConfig(id="ollama", name="Ollama", kind="openai", base_url="http://localhost:11434/v1"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="hi")]))
    assert len(events) == 1
    assert events[0]["kind"] == "network" and events[0]["status"] is None
    assert events[0]["message"].startswith("Unable to connect to http://localhost:11434")
    assert "10061" in events[0]["message"]
    assert "authorization" not in server.requests[0].headers  # no key configured


def test_openai_retries_once_without_stream_options_on_400():
    rejected = httpx.Response(400, json={"error": {"message": "Unrecognized request argument supplied: stream_options"}})
    server = Server(rejected, stream_response(sse(oa_chunk({"content": "ok"}), oa_chunk({}, finish="stop"))))
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="hi")]))
    assert text_of(events) == "ok"
    assert "stream_options" in server.body(0)
    assert "stream_options" not in server.body(1)

    # A second 400 is reported, not retried again.
    server = Server(rejected, rejected)
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[]))
    assert types(events) == ["error"] and events[0]["status"] == 400 and len(server.requests) == 2


def test_openai_mid_stream_error_object():
    body = sse(oa_chunk({"content": "partial"}), {"error": {"message": "overloaded", "code": 529}})
    p = OpenAICompatProvider(cfg("openai"), transport=Server(stream_response(body)).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[]))
    assert types(events) == ["text.delta", "error"]
    assert events[1]["kind"] == "stream" and events[1]["message"] == "overloaded"


def test_openai_message_translation_round_trip():
    p = OpenAICompatProvider(cfg("openai", echo_reasoning=True))
    req = ChatRequest(model="m", system="sys", messages=tool_round_trip())
    msgs = p.translate_messages(req)
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": [{"type": "text", "text": "Read a.txt"}, {"type": "image_url", "image_url": {"url": PNG}}]}
    assert msgs[2] == {
        "role": "assistant", "content": "Reading.", "reasoning_content": "I should read it.",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read", "arguments": '{"path": "a.txt"}'}}],
    }
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": "hello"}

    # Without echo_reasoning the reasoning stays out; an assistant with only tool calls has null content.
    p = OpenAICompatProvider(cfg("openai"))
    msgs = p.translate_messages(ChatRequest(model="m", system="", messages=[ChatMessage(role="assistant", reasoning="r", tool_calls=[ToolCall(id="c", name="f", input={})])]))
    assert msgs == [{"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}]


def test_openai_variant_effort_zai_thinking_and_temperature_knobs():
    msgs = [ChatMessage(role="user", text="hi")]
    body = OpenAICompatProvider(cfg("openai")).build_body(ChatRequest(model="m", system="", messages=msgs, variant="high", temperature=0.2, max_tokens=100))
    assert body["reasoning_effort"] == "high" and body["temperature"] == 0.2 and body["max_tokens"] == 100

    body = OpenAICompatProvider(cfg("openai", effort_param="reasoning_effort_level", effort_map={"max": "high"}, no_temperature=True, max_tokens_param="max_completion_tokens")) \
        .build_body(ChatRequest(model="m", system="", messages=msgs, variant="max", temperature=0.2, max_tokens=100))
    assert body["reasoning_effort_level"] == "high" and "temperature" not in body and body["max_completion_tokens"] == 100

    body = OpenAICompatProvider(cfg("openai", effort_style="openrouter")).build_body(ChatRequest(model="m", system="", messages=msgs, variant="low"))
    assert body["reasoning"] == {"effort": "low"} and "reasoning_effort" not in body

    zai = OpenAICompatProvider(cfg("openai", thinking="zai"))
    body = zai.build_body(ChatRequest(model="glm-5.3", system="", messages=msgs, variant="high"))
    assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "high"  # the effort level reaches GLM too
    body = zai.build_body(ChatRequest(model="glm-5.3", system="", messages=msgs, variant=None, reasoning=False))
    assert body["thinking"] == {"type": "disabled"}
    body = zai.build_body(ChatRequest(model="glm-5.3", system="", messages=msgs, variant=None))
    assert "thinking" not in body

    # reasoning=False never sends an effort, even with a variant.
    body = OpenAICompatProvider(cfg("openai")).build_body(ChatRequest(model="m", system="", messages=msgs, variant="high", reasoning=False))
    assert "reasoning_effort" not in body


def test_openai_list_models_parsing():
    data = {"object": "list", "data": [
        {"id": "gpt-6.1", "object": "model"},
        {"id": "deepseek-chat"},
        {"id": "moonshotai/kimi-k3", "context_length": 262144, "top_provider": {"max_completion_tokens": 32000}},
        {"object": "model"},  # no id → skipped
    ]}
    server = Server(httpx.Response(200, json=data))
    p = OpenAICompatProvider(cfg("openai"), transport=server.transport)
    models = run(p.list_models())
    assert str(server.requests[0].url) == "https://api.example.com/v1/models"
    by_id = {m.id: m for m in models}
    assert list(by_id) == ["gpt-6.1", "deepseek-chat", "moonshotai/kimi-k3"]
    assert by_id["gpt-6.1"].name == "GPT-6.1" and by_id["gpt-6.1"].reasoning and by_id["gpt-6.1"].context == 1_000_000
    assert by_id["deepseek-chat"].reasoning is False and by_id["deepseek-chat"].context == 128_000
    assert by_id["moonshotai/kimi-k3"].context == 262144 and by_id["moonshotai/kimi-k3"].output == 32000 and by_id["moonshotai/kimi-k3"].name == "Kimi K3"

    # Static metadata wins over guesses and static-only models are kept.
    config = cfg("openai")
    config.models = [ModelInfo(id="gpt-6.1", name="My GPT", context=42), ModelInfo(id="only-static", name="Static")]
    models = run(OpenAICompatProvider(config, transport=Server(httpx.Response(200, json=data)).transport).list_models())
    by_id = {m.id: m for m in models}
    assert by_id["gpt-6.1"].name == "My GPT" and by_id["gpt-6.1"].context == 42 and "only-static" in by_id

    with pytest.raises(ProviderError) as info:
        run(OpenAICompatProvider(cfg("openai"), transport=Server(httpx.Response(401, json={"error": {"message": "bad key"}})).transport).list_models())
    assert info.value.status == 401 and "bad key" in str(info.value)


# ---- Anthropic --------------------------------------------------------------------------


def anthropic_stream() -> bytes:
    return sse(
        {"type": "message_start", "message": {"id": "msg_1", "role": "assistant", "usage": {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 3}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Need to "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "read."}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig123"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Let me "}},
        {"type": "ping"},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "look."}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": ""}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"path"'}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": ': "a.txt"'}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "}"}},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 42}},
        {"type": "message_stop"},
    )


def test_anthropic_stream_thinking_text_tool_usage_finish():
    server = Server(stream_response(anthropic_stream()))
    p = AnthropicProvider(cfg("anthropic"), transport=server.transport)
    req = ChatRequest(model="claude-sonnet-5-5", system="sys", messages=[ChatMessage(role="user", text="read a.txt")], tools=[READ_TOOL], variant="high")
    events = collect(p, req)

    assert types(events) == ["reasoning.delta", "reasoning.delta", "text.delta", "text.delta", "tool.start", "tool.delta", "tool.delta", "tool.delta", "tool.end", "usage", "finish"]
    assert text_of(events, "reasoning.delta") == "Need to read." and text_of(events) == "Let me look."
    assert events[4] == {"type": "tool.start", "id": "toolu_1", "name": "read"}
    assert events[8] == {"type": "tool.end", "id": "toolu_1", "name": "read", "input": {"path": "a.txt"}, "raw": '{"path": "a.txt"}'}
    assert events[9] == {"type": "usage", "input": 10, "output": 42, "reasoning": 0, "cache_read": 3, "cache_write": 0}
    assert events[10] == {"type": "finish", "reason": "tool_calls"}

    request = server.requests[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-test" and request.headers["anthropic-version"] == "2023-06-01"
    body = server.body()
    assert body["system"][0]["text"] == "sys" and body["stream"] is True
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 8192} and body["max_tokens"] >= 16384
    assert body["tools"] == [{"name": "read", "description": "Read a file", "input_schema": READ_TOOL.parameters, "cache_control": {"type": "ephemeral"}}]
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "read a.txt", "cache_control": {"type": "ephemeral"}}]}]


def test_anthropic_translation_round_trip_and_thinking_replay():
    p = AnthropicProvider(cfg("anthropic"))
    history = tool_round_trip()
    history[1].tool_calls[0].id = "toolu_1"
    history[2].tool_call_id = "toolu_1"
    msgs = p.translate_messages(history)
    assert msgs == [
        {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}, {"type": "text", "text": "Read a.txt"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Reading."}, {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {"path": "a.txt"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "hello"}]},
    ]
    # Thinking cannot be enabled on this continuation: the signed block is unknown → thinking off, temperature allowed.
    body = p.build_body(ChatRequest(model="claude-sonnet-5-5", system="", messages=history, variant="max", temperature=0.5))
    assert "thinking" not in body and body["temperature"] == 0.5

    # After streaming the response that made the call, the signed thinking is replayed and thinking stays on.
    p = AnthropicProvider(cfg("anthropic"), transport=Server(stream_response(anthropic_stream())).transport)
    collect(p, ChatRequest(model="claude-sonnet-5-5", system="", messages=[ChatMessage(role="user", text="x")], variant="high"))
    body = p.build_body(ChatRequest(model="claude-sonnet-5-5", system="", messages=history, variant="max", temperature=0.5))
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 32000} and "temperature" not in body
    assert body["messages"][1]["content"][0] == {"type": "thinking", "thinking": "Need to read.", "signature": "sig123"}

    # Two tool results in a row land in one user turn; system-role history joins the system prompt.
    msgs = p.translate_messages([
        ChatMessage(role="assistant", tool_calls=[ToolCall(id="a", name="f", input={}), ToolCall(id="b", name="g", input={})]),
        ChatMessage(role="tool", text="1", tool_call_id="a"), ChatMessage(role="tool", text="", tool_call_id="b"),
    ])
    assert [m["role"] for m in msgs] == ["assistant", "user"] and len(msgs[1]["content"]) == 2
    assert msgs[1]["content"][1]["content"] == "(no output)"
    body = p.build_body(ChatRequest(model="m", system="A", messages=[ChatMessage(role="system", text="B"), ChatMessage(role="user", text="hi")]))
    assert body["system"] == [{"type": "text", "text": "A\n\nB", "cache_control": {"type": "ephemeral"}}] and body["max_tokens"] == 16384
    # prompt caching: the newest user turn carries a breakpoint; turned off, the system prompt is plain text
    assert body["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    off = AnthropicProvider(cfg("anthropic", cache=False))
    plain = off.build_body(ChatRequest(model="m", system="A", messages=[ChatMessage(role="user", text="hi")]))
    assert plain["system"] == "A" and "cache_control" not in plain["messages"][-1]["content"][-1]


def test_anthropic_http_401_and_network_error():
    err = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    p = AnthropicProvider(cfg("anthropic"), transport=Server(httpx.Response(401, json=err)).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="hi")]))
    assert len(events) == 1 and json.loads(events[0].pop("response")) == err
    assert events[0] == {"type": "error", "message": "invalid x-api-key", "status": 401, "kind": "http"}

    p = AnthropicProvider(cfg("anthropic"), transport=Server(httpx.ConnectError("Name or service not known")).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[ChatMessage(role="user", text="hi")]))
    assert types(events) == ["error"] and events[0]["kind"] == "network"
    assert events[0]["message"] == "Unable to connect to https://api.anthropic.com: Name or service not known"


def test_anthropic_stream_error_event_and_max_tokens():
    body = sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "Hi"}},
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    )
    p = AnthropicProvider(cfg("anthropic"), transport=Server(stream_response(body)).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[]))
    assert types(events) == ["text.delta", "usage", "finish"] and events[-1]["reason"] == "length"

    body = sse({"type": "message_start", "message": {"usage": {}}}, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    p = AnthropicProvider(cfg("anthropic"), transport=Server(stream_response(body)).transport)
    events = collect(p, ChatRequest(model="m", system="", messages=[]))
    assert types(events) == ["error"] and events[0]["message"] == "Overloaded"


def test_anthropic_list_models():
    page1 = {"data": [{"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5", "type": "model"}], "has_more": True, "last_id": "claude-sonnet-5-5"}
    page2 = {"data": [{"id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5"}], "has_more": False}
    server = Server(httpx.Response(200, json=page1), httpx.Response(200, json=page2))
    models = run(AnthropicProvider(cfg("anthropic"), transport=server.transport).list_models())
    assert [m.id for m in models] == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    assert models[0].name == "Claude Sonnet 5.5" and models[0].context == 200_000 and models[0].reasoning and models[0].variants == ["low", "high", "max"]
    assert "after_id=claude-sonnet-5-5" in str(server.requests[1].url)


# ---- Gemini -----------------------------------------------------------------------------


def gemini_stream() -> bytes:
    return sse(
        {"candidates": [{"content": {"parts": [{"text": "Thinking about it.", "thought": True}], "role": "model"}, "index": 0}]},
        {"candidates": [{"content": {"parts": [{"text": "I will "}], "role": "model"}}]},
        {"candidates": [{"content": {"parts": [{"text": "read it."}], "role": "model"}}]},
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": "read", "args": {"path": "a.txt"}}, "thoughtSignature": "sigXYZ"}], "role": "model"}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 9, "thoughtsTokenCount": 6, "cachedContentTokenCount": 2, "totalTokenCount": 35}},
    )


def test_gemini_stream_text_reasoning_tool_usage_finish():
    server = Server(stream_response(gemini_stream()))
    p = GeminiProvider(cfg("gemini"), transport=server.transport)
    req = ChatRequest(model="gemini-3-pro", system="sys", messages=[ChatMessage(role="user", text="read a.txt")], tools=[READ_TOOL], variant="high", max_tokens=2048)
    events = collect(p, req)

    assert types(events) == ["reasoning.delta", "text.delta", "text.delta", "tool.start", "tool.delta", "tool.end", "usage", "finish"]
    assert text_of(events) == "I will read it."
    call_id = events[3]["id"]
    assert events[3]["name"] == "read" and call_id.startswith("call_")
    assert events[4] == {"type": "tool.delta", "id": call_id, "text": '{"path": "a.txt"}'}
    assert events[5] == {"type": "tool.end", "id": call_id, "name": "read", "input": {"path": "a.txt"}, "raw": '{"path": "a.txt"}'}
    assert events[6] == {"type": "usage", "input": 18, "output": 15, "reasoning": 6, "cache_read": 2, "cache_write": 0}
    assert events[7] == {"type": "finish", "reason": "tool_calls"}

    request = server.requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro:streamGenerateContent?alt=sse"
    assert request.headers["x-goog-api-key"] == "sk-test"
    body = server.body()
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "read a.txt"}]}]
    assert body["generationConfig"] == {"maxOutputTokens": 2048, "thinkingConfig": {"thinkingLevel": "high", "includeThoughts": True}}
    decl = body["tools"][0]["functionDeclarations"][0]
    assert decl["name"] == "read" and "additionalProperties" not in decl["parameters"] and decl["parameters"]["required"] == ["path"]

    # The signature that came with the call is replayed on the next turn.
    history = [ChatMessage(role="user", text="x"), ChatMessage(role="assistant", tool_calls=[ToolCall(id=call_id, name="read", input={"path": "a.txt"})]),
               ChatMessage(role="tool", text="hello", tool_call_id=call_id)]
    contents = p.translate_messages(history, "gemini-3-pro")
    assert contents[1]["parts"][0] == {"functionCall": {"name": "read", "args": {"path": "a.txt"}}, "thoughtSignature": "sigXYZ"}


def test_gemini_translation_round_trip_and_variants():
    p = GeminiProvider(cfg("gemini"))
    history = tool_round_trip()
    history[2].tool_name = ""  # name must be recovered from the assistant's call
    contents = p.translate_messages(history, "gemini-2.5-pro")
    assert contents == [
        {"role": "user", "parts": [{"text": "Read a.txt"}, {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}}]},
        {"role": "model", "parts": [{"text": "Reading."}, {"functionCall": {"name": "read", "args": {"path": "a.txt"}}}]},
        {"role": "user", "parts": [{"functionResponse": {"name": "read", "response": {"result": "hello"}}}]},
    ]
    # Gemini 3 without a known signature gets the documented placeholder.
    contents = p.translate_messages(history, "gemini-3-flash")
    assert contents[1]["parts"][1]["thoughtSignature"] == "skip_thought_signature_validator"

    body = p.build_body(ChatRequest(model="gemini-2.5-flash", system="", messages=history, variant="max", temperature=0.1))
    assert body["generationConfig"] == {"temperature": 0.1, "thinkingConfig": {"thinkingBudget": 24576, "includeThoughts": True}}
    body = p.build_body(ChatRequest(model="gemini-2.5-flash", system="", messages=history, variant=None))
    assert body["generationConfig"] == {"thinkingConfig": {"includeThoughts": True}}
    body = p.build_body(ChatRequest(model="gemini-2.5-flash", system="", messages=history, variant="high", reasoning=False))
    assert "generationConfig" not in body
    assert GeminiProvider(cfg("gemini", key_in_query=True)).url("/v1beta/models/x:streamGenerateContent", "alt=sse").endswith("?alt=sse&key=sk-test")


def test_gemini_http_error_blocked_finish_and_network_error():
    err = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}
    p = GeminiProvider(cfg("gemini"), transport=Server(httpx.Response(400, json=[err])).transport)  # Google wraps SSE errors in a list
    events = collect(p, ChatRequest(model="gemini-3-pro", system="", messages=[ChatMessage(role="user", text="hi")]))
    assert types(events) == ["error"] and events[0]["status"] == 400 and events[0]["message"].startswith("API key not valid")

    body = sse({"candidates": [{"content": {"parts": [{"text": "I"}]}, "finishReason": "SAFETY"}], "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}})
    p = GeminiProvider(cfg("gemini"), transport=Server(stream_response(body)).transport)
    events = collect(p, ChatRequest(model="gemini-3-pro", system="", messages=[]))
    assert types(events) == ["text.delta", "usage", "error", "finish"] and events[2]["kind"] == "blocked" and events[3]["reason"] == "error"

    body = sse({"candidates": [{"content": {"parts": [{"text": "I"}]}, "finishReason": "MAX_TOKENS"}]})
    events = collect(GeminiProvider(cfg("gemini"), transport=Server(stream_response(body)).transport), ChatRequest(model="g", system="", messages=[]))
    assert events[-1] == {"type": "finish", "reason": "length"}

    p = GeminiProvider(cfg("gemini"), transport=Server(httpx.ConnectTimeout("timed out")).transport)
    events = collect(p, ChatRequest(model="gemini-3-pro", system="", messages=[]))
    assert events == [{"type": "error", "message": "Timed out connecting to https://generativelanguage.googleapis.com", "status": None, "kind": "network", "response": ""}]


def test_gemini_list_models():
    data = {"models": [
        {"name": "models/gemini-3-pro", "displayName": "Gemini 3 Pro", "inputTokenLimit": 1048576, "outputTokenLimit": 65536, "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
    ]}
    server = Server(httpx.Response(200, json=data))
    models = run(GeminiProvider(cfg("gemini"), transport=server.transport).list_models())
    assert "x-goog-api-key" in server.requests[0].headers and "key=" not in str(server.requests[0].url)
    assert [m.id for m in models] == ["gemini-3-pro"]
    assert models[0].name == "Gemini 3 Pro" and models[0].context == 1048576 and models[0].output == 65536 and models[0].reasoning


# ---- catalog ----------------------------------------------------------------------------


def test_catalog_entries_and_factory():
    required = {"name", "kind", "base_url", "env", "docs", "extra"}
    for pid, entry in catalog.KNOWN.items():
        assert required <= set(entry), pid
        assert entry["kind"] in ("openai", "anthropic", "gemini"), pid
    assert catalog.KNOWN["kimi"]["base_url"] == "https://api.kimi.ai/coding/v1" and catalog.KNOWN["kimi"]["name"] == "Kimi (kimi.ai coding plan)"
    assert catalog.KNOWN["zai-coding"]["extra"]["thinking"] == "zai"
    assert catalog.KNOWN["ollama"]["needs_key"] is False and catalog.KNOWN["ollama"]["base_url"] == "http://localhost:11434/v1"
    assert catalog.OPENCODE_TO_AFH["kimi-code-plan-global"] == "kimi" and catalog.OPENCODE_TO_AFH["zai-coding-plan"] == "zai-coding"
    assert catalog.OPENCODE_TO_AFH["google"] == "gemini" and catalog.OPENCODE_TO_AFH["github-copilot"] is None
    assert all(v is None or v in catalog.KNOWN for v in catalog.OPENCODE_TO_AFH.values())

    kimi = catalog.config_from_catalog("kimi", api_key="k")
    assert isinstance(make_provider(kimi), OpenAICompatProvider) and kimi.extra == {"echo_reasoning": True}
    assert isinstance(make_provider(catalog.config_from_catalog("anthropic")), AnthropicProvider)
    assert isinstance(make_provider(catalog.config_from_catalog("gemini")), GeminiProvider)
    with pytest.raises(ValueError):
        make_provider(ProviderConfig(id="x", name="x", kind="nope", base_url=""))  # type: ignore[arg-type]

    # fetch_models=False providers answer from the static list without a request.
    models = run(make_provider(kimi).list_models())
    assert [m.id for m in models][:2] == ["k3.1-pro", "k3.1-pro-highspeed"] and models[0].context == 1_000_000 and models[0].variants == ["low", "high", "max"]


def test_catalog_heuristics():
    assert catalog.context_for("k3.1-pro") == 1_000_000
    assert catalog.context_for("k3-256k") == 256_000
    assert catalog.context_for("claude-opus-5-5") == 200_000
    assert catalog.context_for("totally-unknown") == 128_000
    assert catalog.is_reasoning("glm-5.3") and catalog.is_reasoning("deepseek-reasoner") and not catalog.is_reasoning("gpt-4o-mini")
    assert catalog.pretty_name("gpt-6.1-mini") == "GPT-6.1 Mini"
    assert catalog.pretty_name("glm-5.3-flash") == "GLM-5.3 Flash"
    assert catalog.pretty_name("openai/gpt-oss-120b") == "GPT Oss 120b"
    for pid, models in catalog.STATIC_MODELS.items():
        assert all(isinstance(m, ModelInfo) and m.context >= 100_000 for m in models), pid


# ---- live smoke test --------------------------------------------------------------------


@pytest.mark.skipif(not os.environ.get("AFH_LIVE_PROVIDER_JSON"), reason="set AFH_LIVE_PROVIDER_JSON to a JSON file {kind, base_url, api_key, model}")
def test_live_provider_smoke():
    spec = json.loads(Path(os.environ["AFH_LIVE_PROVIDER_JSON"]).read_text(encoding="utf-8"))
    config = ProviderConfig(id="live", name="live", kind=spec["kind"], base_url=spec["base_url"], api_key=spec.get("api_key", ""), extra=spec.get("extra", {}))
    p = make_provider(config)
    req = ChatRequest(model=spec["model"], system="Answer in one short sentence.", messages=[ChatMessage(role="user", text="Say hello and name one color.")],
                      variant=spec.get("variant"), max_tokens=spec.get("max_tokens", 512))
    events = collect(p, req)
    print(json.dumps(events, indent=1)[:4000])
    assert not [e for e in events if e["type"] == "error"], events
    assert text_of(events).strip()
    assert events[-1]["type"] == "finish" and events[-1]["reason"] in ("stop", "length")

    if spec.get("tools", True):
        req = ChatRequest(model=spec["model"], system="Use the read tool to read a.txt. Do not answer without calling it.",
                          messages=[ChatMessage(role="user", text="Read a.txt")], tools=[READ_TOOL], variant=spec.get("variant"), max_tokens=spec.get("max_tokens", 512))
        events = collect(p, req)
        print(json.dumps(events, indent=1)[:4000])
        kinds = types(events)
        assert "tool.start" in kinds and "tool.end" in kinds and kinds.index("tool.start") < kinds.index("tool.delta") < kinds.index("tool.end"), events
        assert [e for e in events if e["type"] == "tool.end"][0]["input"] == {"path": "a.txt"}

    models = run(p.list_models())
    assert models and all(isinstance(m, ModelInfo) for m in models)
