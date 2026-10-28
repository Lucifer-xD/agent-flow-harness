"""Tests for afh.transfer. Server-backed tests need `opencode` on PATH and are skipped otherwise."""

from __future__ import annotations

import json
import shutil
from itertools import islice
from pathlib import Path

import pytest
import zstandard

from afh import transfer as t

SCRATCH = Path(r"C:\Users\you\AppData\Local\Temp\afh-transfer-test\pytest")
REAL_DSH = Path.home() / ".dsh" / "sessions"

server = pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode is not on PATH")


# ---- fixtures ------------------------------------------------------------------


def zadloop_records() -> list[dict]:
    created = 1792178079082
    cwd = r"C:\Users\you\Desktop\fixture-ws"
    return [
        {"type": "session", "version": 4, "id": "session-aaaa", "createdAt": created, "cwd": cwd, "isSeeded": False, "delegationDepth": 0},
        {"type": "permission/preset", "seq": 0, "time": created + 1, "data": {"preset": "workspace-write"}},
        {"type": "agent/inbox/spliced", "seq": 1, "time": created + 2, "data": {"inserted": [{"content": [{"type": "text", "text": "Read a.txt"}], "role": "user", "id": "u1"}]}},
        {"type": "turn/start", "seq": 2, "time": created + 3, "data": {"turn": 1}},
        {"type": "system/message", "seq": 3, "time": created + 4, "data": {"turn": 1, "step": 1, "message": {"role": "system", "content": [{"type": "text", "text": "You are a test agent."}], "id": "s1"}}},
        {"type": "user/message", "seq": 4, "time": created + 5, "data": {"content": [{"type": "text", "text": "Read a.txt"}], "source": {"kind": "user"}, "role": "user", "id": "u1"}},
        {"type": "user/message", "seq": 5, "time": created + 6, "data": {"content": [{"type": "text", "text": "runtime noise"}], "source": {"kind": "runtime-context"}, "role": "user", "id": "u2"}},
        {"type": "request/context", "seq": 6, "time": created + 7, "data": {"provider": "muse-browser", "model": "muse-web"}},
        {"type": "session/title", "seq": 7, "time": created + 8, "data": {"title": "Read a.txt", "source": {"kind": "fallback"}}},
        {
            "type": "assistant/message", "seq": 8, "time": created + 100,
            "data": {"turn": 1, "step": 1, "message": {"role": "assistant", "content": [
                {"type": "reasoning", "text": "I should read the file."},
                {"type": "tool-call", "id": "call_1", "name": "read", "arguments": "{\"file_path\":\"a.txt\"}"},
                {"type": "tool-call", "id": "call_2", "name": "shell", "arguments": "not json"},
            ], "source": {"kind": "model", "provider": "muse-browser", "model": "muse-web"}, "id": "a1"},
                     "usage": {"inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 2}},
        },
        {"type": "tool/call", "seq": 9, "time": created + 101, "data": {"turn": 1, "step": 1, "callId": "call_1", "name": "read", "arguments": "{\"file_path\":\"a.txt\"}"}},
        {"type": "tool/result", "seq": 10, "time": created + 150, "data": {"turn": 1, "step": 1, "message": {"role": "tool", "toolCallId": "call_1", "content": [{"type": "text", "text": "FILE BODY"}], "isError": False, "id": "r1"}, "meta": {"path": "a.txt"}}},
        {"type": "tool/result", "seq": 11, "time": created + 160, "data": {"turn": 1, "step": 1, "message": {"role": "tool", "toolCallId": "call_2", "content": [{"type": "text", "text": "command failed"}], "isError": True, "id": "r2"}}},
        {
            "type": "assistant/message", "seq": 12, "time": created + 200,
            "data": {"turn": 1, "step": 2, "message": {"role": "assistant", "content": [{"type": "text", "text": "a.txt says FILE BODY"}],
                                                        "source": {"kind": "model", "provider": "muse-browser", "model": "muse-web"}, "id": "a2"}, "usage": {"inputTokens": 20, "outputTokens": 7}},
        },
        {"type": "session/title", "seq": 13, "time": created + 201, "data": {"title": "Reading a.txt", "source": {"kind": "provider"}}},
        {"type": "turn/end", "seq": 14, "time": created + 202, "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]


def write_zadloop(path: Path, records: list[dict]) -> Path:
    """Two zstd frames, like a log appended across runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    half = len(records) // 2
    cctx = zstandard.ZstdCompressor()
    with open(path, "wb") as fh:
        for chunk in (records[:half], records[half:]):
            fh.write(cctx.compress("".join(json.dumps(r) + "\n" for r in chunk).encode("utf-8")))
    return path


@pytest.fixture
def dsh_home(tmp_path: Path) -> Path:
    home = tmp_path / ".dsh"
    write_zadloop(home / "sessions" / "--C-fixture-ws--" / "session-aaaa" / "session.v4.jsonl.zstd", zadloop_records())
    older = zadloop_records()[:1]
    older[0] = dict(older[0], id="session-bbbb", createdAt=1700000000000)
    write_zadloop(home / "sessions" / "--C-fixture-ws--" / "session-bbbb" / "session.v4.jsonl.zstd", older)
    (home / "storages").mkdir()
    (home / "storages" / "workspace.json").write_text(json.dumps({"tables": {"workspaces": {"w1": {
        "path": r"C:\Users\you\Desktop\fixture-ws", "title": "fixture-ws", "sessionIds": ["session-aaaa", "session-bbbb"]}}}}))
    return home


# ---- ids -------------------------------------------------------------------------


def test_new_id_format_and_order():
    a, b = t.new_id("msg", 1000, 0), t.new_id("msg", 1000, 1)
    assert a.startswith("msg_") and len(a) == 4 + 12 + 14 and a < b
    assert t.new_id("msg", 1000, 5) < t.new_id("msg", 2000, 0)
    s_old, s_new = t.new_id("ses", 1000), t.new_id("ses", 2000)
    assert s_old.startswith("ses_") and s_new < s_old  # sessions sort newest first


# ---- payload handling --------------------------------------------------------------


def raw_export() -> dict:
    return {
        "info": {"id": "ses_x", "parentID": "ses_parent", "fork": {"sessionID": "ses_p", "boundary": {}}, "revert": {},
                 "projectID": "orig", "location": {"directory": r"C:\orig"}, "title": "T", "metadata": {"afh": {"mode": "ask"}},
                 "time": {"created": 1700000000000, "updated": 1700000001000}},
        "messages": [
            {"id": "msg_1", "type": "user", "text": "hello", "time": {"created": 1700000000000}},
            {"id": "msg_2", "type": "assistant", "model": {"id": "m", "providerID": "p"}, "time": {"created": 1700000000500},
             "content": [{"type": "tool", "id": "c1", "name": "read", "state": {"status": "completed", "input": {}, "content": []}}]},
        ],
    }


def test_unpack_accepts_afh_envelope_and_raw_export():
    raw = raw_export()
    info, messages = t.unpack(raw)
    assert info["id"] == "ses_x" and len(messages) == 2
    wrapped = {"format": t.FORMAT, "version": 1, "app": t.APP, **raw}
    assert t.unpack(wrapped) == (info, messages)


@pytest.mark.parametrize("bad", [{}, {"messages": []}, {"info": {}, "messages": "x"}, {"format": "other", "info": {}}, "nope"])
def test_unpack_rejects_garbage(bad):
    with pytest.raises(ValueError):
        t.unpack(bad)


def test_clean_info_strips_server_owned_fields_and_fills_required():
    info = t.clean_info(raw_export()["info"], r"C:\dest")
    for key in t.DROP_INFO - {"projectID", "location"}:
        assert key not in info
    assert info["location"] == {"directory": r"C:\dest"} and info["projectID"]
    assert info["cost"] == 0 and info["tokens"] == t.ZERO_TOKENS
    assert info["id"] == "ses_x" and info["title"] == "T" and info["metadata"] == {"afh": {"mode": "ask"}}
    assert t.clean_info({"id": "bogus"}, r"C:\dest")["id"].startswith("ses_")
    filled = t.clean_info({}, r"C:\dest")
    assert filled["time"]["created"] == filled["time"]["updated"]


def test_clean_message_assistant_defaults():
    m = t.clean_message(raw_export()["messages"][1])
    assert m["agent"] == "build" and m["time"]["completed"] == m["time"]["created"]
    part = m["content"][0]
    assert part["time"] == {"created": 1700000000500} and part["state"]["content"]  # non-empty for the server
    assert t.clean_message(raw_export()["messages"][0])["text"] == "hello"


def test_renumber_keeps_order_with_fresh_msg_ids():
    out = t.renumber([{"id": "a", "type": "user"}, {"id": "b", "type": "assistant"}])
    assert [m["type"] for m in out] == ["user", "assistant"]
    assert all(m["id"].startswith("msg_") for m in out) and out[0]["id"] < out[1]["id"]


def test_summarize():
    s = t.summarize({"format": t.FORMAT, "app": t.APP, **raw_export()})
    assert s == {"title": "T", "messages": 2, "firstUserText": "hello", "created": "2023-11-14T22:13:20+00:00",
                 "model": None, "source": t.APP}


# ---- zadloop -------------------------------------------------------------------------


def test_read_zadloop_handles_multiple_frames(tmp_path: Path):
    path = write_zadloop(tmp_path / "s.jsonl.zstd", zadloop_records())
    assert [r["type"] for r in t.read_zadloop(path)] == [r["type"] for r in zadloop_records()]


def test_zadloop_to_opencode_shapes(tmp_path: Path):
    path = write_zadloop(tmp_path / "s.jsonl.zstd", zadloop_records())
    info, messages = t.zadloop_to_opencode(path)

    assert info["id"].startswith("ses_") and info["title"] == "Reading a.txt"  # last title wins
    assert info["model"] == {"id": "muse-web", "providerID": "muse-browser"} and info["agent"] == "build"
    assert info["time"] == {"created": 1792178079082, "updated": 1792178079082 + 202}
    assert info["metadata"]["afh"] == {"importedFrom": "zadloop", "sourcePath": str(path), "sourceId": "session-aaaa",
                                       "sourceCwd": r"C:\Users\you\Desktop\fixture-ws"}
    assert info["location"] == {"directory": r"C:\Users\you\Desktop\fixture-ws"}
    assert info["tokens"] == {"input": 30, "output": 12, "reasoning": 0, "cache": {"read": 2, "write": 0}}

    assert [m["type"] for m in messages] == ["system", "user", "assistant", "assistant"]
    ids = [m["id"] for m in messages]
    assert ids == sorted(ids) and all(i.startswith("msg_") for i in ids)
    assert messages[0]["text"] == "You are a test agent."
    assert messages[1]["text"] == "Read a.txt"  # the runtime-context "user" record is dropped

    a1 = messages[2]
    assert a1["agent"] == "build" and a1["model"] == {"id": "muse-web", "providerID": "muse-browser"}
    assert a1["finish"] == "tool-calls" and a1["time"] == {"created": 1792178079082 + 100, "completed": 1792178079082 + 160}
    assert a1["tokens"] == {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 2, "write": 0}}
    reasoning, read, shell = a1["content"]
    assert reasoning == {"type": "reasoning", "text": "I should read the file."}
    assert read["type"] == "tool" and read["id"] == "call_1" and read["name"] == "read"
    assert read["state"] == {"status": "completed", "input": {"file_path": "a.txt"},
                             "content": [{"type": "text", "text": "FILE BODY"}], "metadata": {"path": "a.txt"}}
    assert read["time"] == {"created": 1792178079082 + 100, "completed": 1792178079082 + 150}
    assert shell["state"] == {"status": "error", "input": {"arguments": "not json"},
                              "error": {"type": "ToolError", "message": "command failed"}}
    assert messages[3]["content"] == [{"type": "text", "text": "a.txt says FILE BODY"}] and messages[3]["finish"] == "stop"


def test_zadloop_unpaired_tool_call_gets_placeholder(tmp_path: Path):
    records = [r for r in zadloop_records() if r["type"] != "tool/result"]
    path = write_zadloop(tmp_path / "s.jsonl.zstd", records)
    _, messages = t.zadloop_to_opencode(path)
    states = [p["state"] for p in messages[2]["content"] if p["type"] == "tool"]
    assert all(s["status"] == "completed" and s["content"][0]["text"] == "(no result recorded)" for s in states)


def test_list_zadloop_sessions(dsh_home: Path):
    sessions = t.list_zadloop_sessions(dsh_home)
    assert [s["id"] for s in sessions] == ["session-aaaa", "session-bbbb"]  # newest first
    first = sessions[0]
    assert first["title"] == "Reading a.txt" and first["messages"] == 3 and first["workspace"] == "fixture-ws"
    assert first["cwd"] == r"C:\Users\you\Desktop\fixture-ws" and first["createdAt"] == 1792178079082
    assert Path(first["path"]).is_file()
    assert sessions[1]["messages"] == 0 and sessions[1]["title"] == "session-bbbb"
    assert t.list_zadloop_sessions(dsh_home / "missing") == []


def test_load_zadloop_payload_roundtrips_through_unpack_and_summarize(tmp_path: Path):
    payload = t.load_zadloop(write_zadloop(tmp_path / "s.jsonl.zstd", zadloop_records()))
    assert payload["format"] == t.FORMAT and payload["app"] == "zadloop"
    s = t.summarize(payload)
    assert s["title"] == "Reading a.txt" and s["messages"] == 3 and s["firstUserText"] == "Read a.txt" and s["source"] == "zadloop"


@pytest.mark.skipif(not REAL_DSH.is_dir(), reason="no ~/.dsh/sessions on this machine")
def test_real_zadloop_files_convert():
    sessions = t.list_zadloop_sessions()
    assert sessions
    for s in sessions:
        info, messages = t.zadloop_to_opencode(s["path"])
        assert info["title"] and info["id"].startswith("ses_")
        assert sum(1 for m in messages if m["type"] in ("user", "assistant")) == s["messages"]
        for m in messages:
            assert m["id"].startswith("msg_")
            if m["type"] == "assistant":
                assert m["content"] and "completed" in m["time"]
                for p in m["content"]:
                    if p["type"] == "tool":
                        assert p["time"] and p["state"]["status"] in ("completed", "error")


# ---- server-backed -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from opencode import OpencodeServer

    SCRATCH.mkdir(parents=True, exist_ok=True)
    with OpencodeServer(cwd=str(SCRATCH), config={}) as srv, srv.client() as c:
        created: list[str] = []
        c.afh_created = created  # sessions to delete at teardown
        yield c
        for sid in created:
            try:
                c.session.remove(sid)
            except Exception:
                pass


def message_list(client, sid: str) -> list[dict]:
    return [t.dump(m) for m in islice(client.message.list(sid, order="asc", limit=200), 2000)]


@server
def test_export_import_roundtrip_real_session(client):
    # An idle top-level session: a live one changes between export and import, a child can't be imported alone.
    candidates = [s for s in islice(client.session.list(limit=20), 20) if not s.parent_id and s.time and s.time.idle]
    source = next((s for s in candidates if len(message_list(client, s.id)) >= 2), None)
    if source is None:
        pytest.skip("no existing session with messages")
    payload = t.export_session(client, source.id)
    assert payload["format"] == t.FORMAT and payload["info"]["id"] == source.id
    before = message_list(client, source.id)

    imported = t.import_session(client, payload, str(SCRATCH))
    client.afh_created.append(imported["id"])
    assert imported["id"] != source.id and imported["id"].startswith("ses_")
    assert imported["location"]["directory"] == str(SCRATCH) and imported["title"] == payload["info"]["title"]
    after = message_list(client, imported["id"])
    assert len(after) == len(before)
    assert [m["type"] for m in after] == [m["type"] for m in before]
    assert [m.get("text") for m in after if m["type"] == "user"] == [m.get("text") for m in before if m["type"] == "user"]
    assert {m["id"] for m in after}.isdisjoint({m["id"] for m in before})

    # Same payload again: the original still exists, so another fresh session is created.
    again = t.import_session(client, payload, str(SCRATCH))
    client.afh_created.append(again["id"])
    assert again["id"] not in (source.id, imported["id"]) and len(message_list(client, again["id"])) == len(before)


@server
def test_import_raw_export_with_foreign_ids_and_metadata(client):
    payload = raw_export()
    payload["info"]["id"] = "session-not-opencode"  # Zadloop-style id must be replaced
    imported = t.import_session(client, payload, str(SCRATCH))
    client.afh_created.append(imported["id"])
    assert imported["id"].startswith("ses_") and imported.get("parentID") is None
    assert imported["metadata"] == {"afh": {"mode": "ask"}} and imported["time"]["created"] == 1700000000000
    msgs = message_list(client, imported["id"])
    assert [m["type"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"][0]["state"]["status"] == "completed"


@server
def test_zadloop_import_keeps_tool_parts(client, tmp_path: Path):
    real = [s for s in t.list_zadloop_sessions() if REAL_DSH.is_dir()]
    path = next((s["path"] for s in real if any(
        p["type"] == "tool" for m in t.zadloop_to_opencode(s["path"])[1] if m["type"] == "assistant" for p in m["content"])), None)
    path = path or write_zadloop(tmp_path / "s.jsonl.zstd", zadloop_records())
    payload = t.load_zadloop(path)
    expected = payload["messages"]

    imported = t.import_session(client, payload, str(SCRATCH))
    client.afh_created.append(imported["id"])
    assert imported["title"] == payload["info"]["title"]
    assert imported["metadata"]["afh"]["importedFrom"] == "zadloop" and imported["metadata"]["afh"]["sourcePath"] == str(path)
    assert imported["location"]["directory"] == str(SCRATCH)

    msgs = message_list(client, imported["id"])
    assert [m["type"] for m in msgs] == [m["type"] for m in expected]
    assert [m["id"] for m in msgs] == [m["id"] for m in expected]  # fresh ids were accepted as-is
    tools = [p for m in msgs if m["type"] == "assistant" for p in m["content"] if p["type"] == "tool"]
    want = [p for m in expected if m["type"] == "assistant" for p in m["content"] if p["type"] == "tool"]
    assert tools and len(tools) == len(want)
    for got, exp in zip(tools, want):
        assert got["id"] == exp["id"] and got["name"] == exp["name"]
        assert got["state"]["status"] == exp["state"]["status"] and got["state"]["input"] == exp["state"]["input"]
        if exp["state"]["status"] == "completed":
            assert got["state"]["content"] == exp["state"]["content"]
    assert [p["type"] for m in msgs for p in m.get("content", [])] == [p["type"] for m in expected for p in m.get("content", [])]
