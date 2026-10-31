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
