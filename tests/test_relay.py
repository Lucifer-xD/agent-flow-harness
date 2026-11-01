"""The relay (relay/app.py): accounts, computers, and a request carried from a phone to a computer."""

import base64
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def relay(tmp_path, monkeypatch):
    monkeypatch.setenv("AFH_RELAY_DB", str(tmp_path / "relay.db"))
    monkeypatch.setenv("AFH_RELAY_DEV", "1")  # the test client speaks plain http
    spec = importlib.util.spec_from_file_location("afh_relay_app", ROOT / "relay" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["afh_relay_app"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("afh_relay_app", None)


def test_accounts_and_computers(relay):
    phone = TestClient(relay.app)
    assert phone.get("/relay/api/me").status_code == 401
    assert phone.post("/relay/api/signup", json={"email": "not-an-email", "password": "longenough"}).status_code == 400
    assert phone.post("/relay/api/signup", json={"email": "a@example.com", "password": "short"}).status_code == 400
    r = phone.post("/relay/api/signup", json={"email": "A@Example.com", "password": "correct horse"})
    assert r.status_code == 200 and "token" not in r.json()  # the browser keeps an HttpOnly cookie instead
    assert phone.post("/relay/api/signup", json={"email": "a@example.com", "password": "correct horse"}).status_code == 409
    assert phone.get("/relay/api/me").json()["user"]["email"] == "a@example.com"

    desktop = TestClient(relay.app)
    assert desktop.post("/relay/api/signin", json={"email": "a@example.com", "password": "wrong one"}).status_code == 401
    session = desktop.post("/relay/api/signin", json={"email": "a@example.com", "password": "correct horse", "kind": "desktop"}).json()["token"]
    comp = desktop.post("/relay/api/computers", json={"name": "Work PC"}, headers={"authorization": f"Bearer {session}"}).json()
    assert comp["token"].startswith("afhc_")
    listed = phone.get("/relay/api/me").json()["computers"]
    assert [(c["name"], c["online"]) for c in listed] == [("Work PC", False)]

    # nothing stored can sign anyone in: passwords and tokens are hashed
    db = relay.db().execute("SELECT pw FROM users").fetchone()["pw"]
    assert db.startswith("scrypt$") and "correct horse" not in db
    assert relay.db().execute("SELECT token FROM computers").fetchone()["token"] != comp["token"]

    # another account can't see or reach it
    other = TestClient(relay.app)
    other.post("/relay/api/signup", json={"email": "b@example.com", "password": "another one"})
    assert other.get(f"/r/{comp['id']}/api/bootstrap").status_code == 404
    assert phone.get(f"/r/{comp['id']}/api/bootstrap").status_code == 503  # offline

    assert desktop.post("/relay/api/computer/forget", headers={"authorization": f"Bearer {comp['token']}"}).json() == {"ok": True}
    assert phone.get("/relay/api/me").json()["computers"] == []


def test_a_phone_request_reaches_the_computer(relay):
    with TestClient(relay.app) as phone:  # one event loop for both ends, as on the server
        phone_meets_computer(phone)


def phone_meets_computer(phone):
    phone.post("/relay/api/signup", json={"email": "c@example.com", "password": "correct horse"})
    session = phone.post("/relay/api/signin", json={"email": "c@example.com", "password": "correct horse", "kind": "desktop"}).json()["token"]
    comp = phone.post("/relay/api/computers", json={"name": "PC"}, headers={"authorization": f"Bearer {session}"}).json()

    with phone.websocket_connect("/relay/agent", headers={"authorization": f"Bearer {comp['token']}"}) as ws:
        seen = []

        def answer():  # the computer's side: one small answer, one streamed in pieces
            for _ in range(2):
                req = json.loads(ws.receive_text())
                seen.append(req)
                if req["path"] == "/api/small":
                    body = base64.b64encode(json.dumps({"echo": base64.b64decode(req["body"]).decode()}).encode()).decode()
                    ws.send_text(json.dumps({"t": "res", "id": req["id"], "status": 200, "headers": {"content-type": "application/json", "set-cookie": "x=1"}, "body": body, "end": True}))
                else:
                    ws.send_text(json.dumps({"t": "res", "id": req["id"], "status": 200, "headers": {"content-type": "text/plain"}}))
                    for part in (b"one ", b"two"):
                        ws.send_text(json.dumps({"t": "chunk", "id": req["id"], "data": base64.b64encode(part).decode()}))
                    ws.send_text(json.dumps({"t": "end", "id": req["id"]}))

        t = threading.Thread(target=answer)
        t.start()
        assert phone.get("/relay/api/me").json()["computers"][0]["online"] is True
        r = phone.post(f"/r/{comp['id']}/api/small?x=1", json={"hi": 1})
        assert r.status_code == 200 and r.json() == {"echo": '{"hi":1}'}
        assert "x=1" not in r.headers.get("set-cookie", "")  # the computer can't set cookies on the site
        r = phone.get(f"/r/{comp['id']}/api/stream")
        assert r.text == "one two"
        t.join(timeout=5)
        assert seen[0]["query"] == "x=1" and "cookie" not in seen[0]["headers"]  # the relay's own cookie never reaches the computer

        # who can reach the computer is decided on the computer
        assert phone.put(f"/r/{comp['id']}/api/cloud", json={"enabled": False}).status_code == 403
        assert phone.post(f"/r/{comp['id']}/api/remote/disconnect-all").status_code == 403


def test_a_removed_computer_is_refused(relay):
    computer = TestClient(relay.app)
    with pytest.raises(Exception):
        with computer.websocket_connect("/relay/agent", headers={"authorization": "Bearer afhc_nope"}):
            pass


def test_a_computer_is_linked_from_the_website(relay):
    computer = TestClient(relay.app)
    start = computer.post("/relay/api/link/start", json={"name": "  Work   PC "}).json()
    assert start["url"].endswith("/account?link=" + start["code"]) and len(start["code"]) == 9
    assert computer.get("/relay/api/link/poll", params={"poll": start["poll"]}).status_code == 202

    site = TestClient(relay.app)
    assert site.get(f"/relay/api/link/{start['code'].lower()}").json()["name"] == "Work PC"
    assert site.post(f"/relay/api/link/{start['code']}/approve").status_code == 401  # signed in first
    site.post("/relay/api/signup", json={"email": "d@example.com", "password": "correct horse"})
    assert site.post(f"/relay/api/link/{start['code']}/approve").json()["computer"]["name"] == "Work PC"
    assert site.post(f"/relay/api/link/{start['code']}/approve").status_code == 410  # only once

    got = computer.get("/relay/api/link/poll", params={"poll": start["poll"]}).json()
    assert got["email"] == "d@example.com" and got["computer"]["token"].startswith("afhc_")
    assert computer.get("/relay/api/link/poll", params={"poll": start["poll"]}).status_code == 410  # handed out once
    assert [c["name"] for c in site.get("/relay/api/me").json()["computers"]] == ["Work PC"]

    # cancelling in the browser tells the computer
    again = computer.post("/relay/api/link/start", json={}).json()
    site.post(f"/relay/api/link/{again['code']}/deny")
    assert computer.get("/relay/api/link/poll", params={"poll": again["poll"]}).status_code == 410


def test_the_phone_app_signs_in_with_a_token(relay):
    app = TestClient(relay.app)
    app.post("/relay/api/signup", json={"email": "e@example.com", "password": "correct horse"})
    app.cookies.clear()
    r = app.post("/relay/api/signin", json={"email": "e@example.com", "password": "correct horse", "kind": "app"},
                 headers={"origin": "https://localhost"})
    assert r.headers["access-control-allow-origin"] == "https://localhost" and "set-cookie" not in r.headers
    token = r.json()["token"]
    assert app.get("/relay/api/me").status_code == 401
    assert app.get("/relay/api/me", headers={"authorization": f"Bearer {token}"}).json()["user"]["email"] == "e@example.com"
    # other sites get no CORS grant
    r = app.get("/relay/api/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_the_web_chat_forwards_to_public_https_only(relay, monkeypatch):
    web = TestClient(relay.app)
    assert web.post("/relay/api/fwd", headers={"x-afh-target": "https://example.com/"}).status_code == 401
    assert web.post("/relay/api/signup", json={"email": "fwd@example.com", "password": "correct horse 1"}).status_code == 200
    # not https, a private address, this server itself: refused before anything is sent
    for target in ("http://example.com/", "https://127.0.0.1/", "https://localhost:8840/relay/api/me", "https://10.0.0.5/", "https://user:pw@example.com/"):
        assert web.get("/relay/api/fwd", headers={"x-afh-target": target}).status_code == 400, target

    seen = {}

    class Upstream:
        status_code = 200
        headers = {"content-type": "text/event-stream", "set-cookie": "x=1"}

        async def aiter_raw(self):
            yield b"data: one\n\n"
            yield b"data: two\n\n"

        async def aclose(self):
            pass

    class Client:
        def build_request(self, method, url, headers, content):
            seen.update(method=method, url=url, headers=headers, content=content)
            return object()

        async def send(self, req, stream):
            return Upstream()

    async def public(host, port):
        return True

    monkeypatch.setattr(relay, "fwd_client", lambda: Client())
    monkeypatch.setattr(relay, "public_host", public)
    res = web.post("/relay/api/fwd", content=b'{"model":"m"}', headers={
        "x-afh-target": "https://api.example.com/v1/chat/completions", "authorization": "Bearer sk-test",
        "content-type": "application/json", "x-afh-ua": "Tester/1"})
    assert res.status_code == 200
    assert res.text == "data: one\n\ndata: two\n\n"
    assert "set-cookie" not in res.headers  # the provider's cookies stay out of agentflowharness.com
    assert seen["url"] == "https://api.example.com/v1/chat/completions" and seen["content"] == b'{"model":"m"}'
    sent = {k.lower(): v for k, v in seen["headers"].items()}
    assert sent["authorization"] == "Bearer sk-test" and sent["user-agent"] == "Tester/1"
    assert "cookie" not in sent and "x-afh-target" not in sent  # the AFH session never leaves
