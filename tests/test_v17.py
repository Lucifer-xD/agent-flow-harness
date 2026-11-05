"""1.7: compaction threshold, developer API keys and the one-call run endpoint, scheduled jobs,
browser screenshots for vision models, uploads, voice provider choice and bug reports."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from afh import api as apimod
from afh import bugreport, devapi
from afh.engine import config as provcfg
from afh.engine import schedules, voice
from afh.engine.core import compact_ratio
from afh.engine.runner import to_chat
from afh.engine.tools.browser import BrowserManager, find_browsers

from test_engine_features import FakeProvider, home, make_engine  # noqa: F401 - fixture

# ---- compaction threshold ---------------------------------------------------------------------


def test_compact_ratio_follows_setting_and_is_clamped():
    assert compact_ratio({}) == 0.8
    assert compact_ratio({"agent": {"compactAt": 40}}) == 0.4
    assert compact_ratio({"agent": {"compactAt": 60}}) == 0.6
    assert compact_ratio({"agent": {"compactAt": 5}}) == 0.2
    assert compact_ratio({"agent": {"compactAt": 150}}) == 0.95


# ---- developer API keys ------------------------------------------------------------------------


def test_api_keys_are_hashed_checked_and_revoked(home):
    info, raw = devapi.create_key("ci")
    assert raw.startswith("afh_") and info["name"] == "ci"
    stored = (home / "api-keys.json").read_text(encoding="utf-8")
    assert raw not in stored  # only the hash is kept
    assert devapi.check(raw) and not devapi.check(raw + "x") and not devapi.check(None)
    assert devapi.delete_key(info["id"])
    assert not devapi.check(raw)


def test_api_key_opens_the_local_api(home, monkeypatch):
    e = make_engine(FakeProvider([]))
    monkeypatch.setattr(apimod, "engine", e)
    monkeypatch.setitem(apimod.ACCESS, "token", "window-token")
    client = TestClient(apimod.app)
    _, raw = devapi.create_key("script")
    assert client.get("/api/v1/sessions/nope/reply").status_code == 401
    assert client.get("/api/v1/sessions/nope/reply", headers={"Authorization": "Bearer afh_wrong"}).status_code == 401
    r = client.get("/api/v1/sessions/nope/reply", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 404  # authorised; the thread just doesn't exist


def test_v1_run_starts_a_thread_and_returns_the_reply(home, tmp_path, monkeypatch):
    e = make_engine(FakeProvider([[("todo", {"todos": [{"content": "Do it", "status": "completed"}]})], "Finished: added the endpoint."]))
    monkeypatch.setattr(apimod, "engine", e)
    project = tmp_path / "proj"
    project.mkdir()

    async def go():
        e.loop = asyncio.get_running_loop()
        return await apimod.run_task({"prompt": "Add an endpoint", "directory": str(project), "model": "fake/m", "timeout": 30})

    out = asyncio.run(go())
    assert out["done"] is True
    assert out["reply"] == "Finished: added the endpoint."
    assert out["todos"][0]["content"] == "Do it"
    session = e.store.get_session(out["sessionID"])
    assert session["location"]["directory"] == str(project) and session["metadata"]["afh"]["mode"] == "full"


def test_v1_run_needs_a_prompt_and_a_folder(home, monkeypatch):
    monkeypatch.setattr(apimod, "engine", make_engine(FakeProvider([])))
    with pytest.raises(ValueError):
        asyncio.run(apimod.run_task({"prompt": "", "directory": "."}))
    with pytest.raises(ValueError):
        asyncio.run(apimod.run_task({"prompt": "hi", "directory": "Z:/no/such/folder"}))


# ---- scheduled jobs ----------------------------------------------------------------------------


def test_next_run_times():
    mon_8am = dt.datetime(2026, 10, 26, 8, 0)  # a Monday
    assert schedules.next_after({"every": "daily", "time": "09:30"}, mon_8am) == dt.datetime(2026, 10, 26, 9, 30)
    assert schedules.next_after({"every": "daily", "time": "07:00"}, mon_8am) == dt.datetime(2026, 10, 27, 7, 0)
    assert schedules.next_after({"every": "hourly", "time": "00:15"}, mon_8am) == dt.datetime(2026, 10, 26, 8, 15)
    assert schedules.next_after({"every": "interval", "minutes": 90}, mon_8am) == dt.datetime(2026, 10, 26, 9, 30)
    fri_6pm = dt.datetime(2026, 10, 30, 18, 0)
    assert schedules.next_after({"every": "weekdays", "time": "09:00"}, fri_6pm) == dt.datetime(2026, 11, 2, 9, 0)
    assert schedules.next_after({"every": "weekly", "time": "10:00", "weekday": 2}, mon_8am) == dt.datetime(2026, 10, 28, 10, 0)


def test_jobs_are_validated_saved_and_due(home, tmp_path):
    with pytest.raises(ValueError):
        schedules.upsert({"name": "x", "directory": str(tmp_path), "prompt": ""})
    with pytest.raises(ValueError):
        schedules.upsert({"name": "x", "directory": str(tmp_path / "missing"), "prompt": "go"})
    job = schedules.upsert({"name": "Nightly", "directory": str(tmp_path), "prompt": "run tests", "every": "interval", "minutes": 1})
    assert job["minutes"] == 5 and job["mode"] == "full" and job["nextRun"]
    saved = schedules.load()[0]
    assert not schedules.due(saved, dt.datetime.now())
    assert schedules.due(saved, dt.datetime.now() + dt.timedelta(minutes=6))
    assert not schedules.due({**saved, "enabled": False}, dt.datetime.now() + dt.timedelta(days=1))
    assert schedules.delete(job["id"]) and schedules.load() == []


def test_scheduler_run_starts_a_thread_and_records_it(home, tmp_path):
    job = schedules.upsert({"name": "Check", "directory": str(tmp_path), "prompt": "hi"})
    started, published = [], []

    async def start(j):
        started.append(j["id"])
        return "ses_1"

    sid = asyncio.run(schedules.Scheduler(start, published.append).run(schedules.load()[0]))
    assert sid == "ses_1" and started == [job["id"]]
    saved = schedules.load()[0]
    assert saved["lastSession"] == "ses_1" and saved["lastStatus"] == "started" and saved["lastRun"]
    assert published[0]["type"] == "schedule.ran"


# ---- browser screenshots reach vision models ---------------------------------------------------


def _shot_turn(cid: str, uri: str) -> dict:
    return {"type": "assistant", "content": [{"type": "tool", "id": cid, "name": "browser", "state": {
        "status": "completed", "input": {"action": "screenshot"},
        "content": [{"type": "text", "text": "Screenshot attached"}, {"type": "image", "uri": uri}]}}]}


def test_only_the_newest_two_screenshots_go_to_vision_models():
    msgs = [{"type": "user", "text": "check the page"}] + [_shot_turn(f"c{i}", f"data:image/jpeg;base64,{i}") for i in range(3)]
    images = [img for m in to_chat(msgs, vision=True) for img in m.images]
    assert images == ["data:image/jpeg;base64,1", "data:image/jpeg;base64,2"]
    assert not [img for m in to_chat(msgs, vision=False) for img in m.images]


def test_browser_candidates_and_port_file(tmp_path):
    custom = tmp_path / "mybrowser.exe"
    custom.write_text("")
    assert find_browsers({"browser": {"path": str(custom)}})[0] == str(custom)
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("51234\n/devtools/browser/abc\n")
    assert BrowserManager._read_port(port_file) == (51234, "ws://127.0.0.1:51234/devtools/browser/abc")
    port_file.write_text("garbage")
    assert BrowserManager._read_port(port_file) is None


# ---- uploads, voice, bug reports ---------------------------------------------------------------


def test_pasted_image_upload_and_thumbnail(home, monkeypatch):
    monkeypatch.setitem(apimod.ACCESS, "token", "t")
    client = TestClient(apimod.app)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = client.post("/api/uploads", content=png, headers={"x-afh-token": "t", "x-filename": "screen%20shot.png", "content-type": "image/png"})
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith(str(home / "uploads")) and path.endswith("screen shot.png")
    img = client.get("/api/image", params={"path": path, "token": "t"})
    assert img.status_code == 200 and img.content == png
    assert client.get("/api/image", params={"path": str(home / "settings.json"), "token": "t"}).status_code == 404


def test_voice_picks_a_configured_provider(home, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        voice.pick({})
    provcfg.upsert("openai", {"name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "api_key": "sk-test"})
    assert voice.pick({}) == ("https://api.openai.com/v1", "sk-test", "gpt-4o-mini-transcribe")
    provcfg.upsert("local", {"name": "Local", "kind": "openai", "base_url": "http://127.0.0.1:9000/v1/"})
    assert voice.pick({"voice": {"provider": "local", "model": "whisper"}}) == ("http://127.0.0.1:9000/v1", "", "whisper")


def test_bug_report_has_no_secrets(home, monkeypatch, tmp_path):
    from afh import store

    store.save_settings({"remote": {"passwordHash": "hash-value"}, "personalization": {"about": "private notes"}})
    provcfg.upsert("openai", {"name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "api_key": "sk-secretsecretsecret123"})
    (home / "logs").mkdir()
    (home / "logs" / "afh-backend.log").write_text(
        "2026 INFO x: GET /api/events?token=abcdef123456 200\n2026 ERROR afh: failed with Bearer sk-secretsecretsecret123\n", encoding="utf-8")
    (home / "logs" / "updates.log").write_text("2026 error: download failed from https://x/?token=abcdef123456\n", encoding="utf-8")
    monkeypatch.setattr(bugreport, "_target_folder", lambda: tmp_path)
    path = bugreport.build("It crashed when I pasted an image")
    with zipfile.ZipFile(path) as z:
        everything = "".join(z.read(n).decode("utf-8") for n in z.namelist())
        assert "It crashed when I pasted an image" in z.read("README.md").decode()
        providers = json.loads(z.read("providers.json"))
    for secret in ("sk-secretsecretsecret123", "hash-value", "private notes", "abcdef123456"):
        assert secret not in everything
    assert providers[0]["hasKey"] is True and "api_key" not in providers[0]
    assert "ERROR afh" in everything  # the problem lines are still there
    assert "download failed" in everything  # and why an update failed


# ---- a provider retry stays with the reply it happened in -------------------------------------


class FlakyProvider(FakeProvider):
    """Times out on the first call, then answers."""

    async def stream(self, req):
        if not getattr(self, "failed", False):
            self.failed = True
            yield {"type": "error", "kind": "network", "message": "Timed out connecting to https://api.example"}
            return
        async for ev in super().stream(req):
            yield ev


def test_retry_is_recorded_on_the_retried_reply(home, tmp_path, monkeypatch):
    from test_engine_features import run_prompt

    from afh.engine import runner as runmod

    real_sleep = asyncio.sleep
    monkeypatch.setattr(runmod.asyncio, "sleep", lambda s: real_sleep(0))
    e = make_engine(FlakyProvider(["Recovered answer."]))
    session = asyncio.run(run_prompt(e, tmp_path, "hi"))
    replies = [m for m in e.store.list_messages(session["id"]) if m.get("type") == "assistant"]
    assert len(replies) == 1
    assert replies[0]["retries"][0]["attempt"] == 1 and "Timed out" in replies[0]["retries"][0]["error"]["message"]
    assert replies[0]["content"][0]["text"] == "Recovered answer."
    ev = next(x for x in e.events if x["type"] == "session.retry.scheduled")
    assert ev["data"]["assistantMessageID"] == replies[0]["id"]


# ---- transport errors (SSL, dropped sockets) are retryable, not fatal -------------------------


def test_ssl_and_os_errors_count_as_retryable_network_errors():
    import ssl

    from afh.engine.providers import sse
    from afh.engine.runner import RETRYABLE  # noqa: F401 - documents where retry is decided

    assert issubclass(ssl.SSLError, sse.NETWORK_ERRORS) and issubclass(OSError, sse.NETWORK_ERRORS)
    e = sse.network_error(ssl.SSLError("SSLV3_ALERT_BAD_RECORD_MAC"), "https://api.kimi.ai/coding/v1/chat/completions")
    assert e["kind"] == "network" and "api.kimi.ai" in e["message"]
    # kind == "network" is what runner._stream_step retries on
    assert e["kind"] == "network"
    dropped = sse.network_error(ConnectionResetError(10054, "forcibly closed"), "https://api.example/v1")
    assert dropped["kind"] == "network" and "api.example" in dropped["message"]


def test_provider_stream_turns_a_raw_ssl_error_into_a_retryable_event():
    import ssl
    import unittest.mock as mock

    from afh.engine.providers import openai_compat
    from afh.engine.types import ChatRequest, ProviderConfig

    p = openai_compat.OpenAICompatProvider(ProviderConfig(id="kimi", name="Kimi", kind="openai", base_url="https://x/v1", api_key="k"))

    class Client:  # async context manager whose .stream() raises a raw TLS error, as httpx can mid-read
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            raise ssl.SSLError("[SSL: SSLV3_ALERT_BAD_RECORD_MAC] sslv3 alert bad record mac")

    async def collect():
        with mock.patch.object(openai_compat, "make_client", lambda *a, **k: Client()):
            return [ev async for ev in p.stream(ChatRequest(model="m", system="", messages=[]))]

    evs = asyncio.run(collect())
    assert evs and evs[-1]["type"] == "error" and evs[-1]["kind"] == "network"
