"""The Copy key button (POST /api/providers/{id}/key): the key in use, one account's, one from the
environment, a sign-in that has none, and never through remote control."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from afh import api as apimod
from afh import remote
from afh.engine import config as provcfg
from tests.test_engine_features import home  # noqa: F401  (fixture)


@pytest.fixture
def client(home, monkeypatch):  # noqa: F811
    monkeypatch.setitem(apimod.ACCESS, "token", "")
    monkeypatch.setitem(apimod.ACCESS, "hosts", set())
    monkeypatch.setitem(remote.state, "port", 0)
    return TestClient(apimod.app)


def test_copies_the_key_in_use_and_each_accounts_own(client):
    provcfg.upsert("kimi", {"name": "Kimi", "kind": "openai", "base_url": "https://x/v1", "api_key": "sk-first-key-1111"})
    second = provcfg.add_account("kimi", {"api_key": "sk-second-key-2222"}, label="Work")
    r = client.post("/api/providers/kimi/key", json={})
    assert r.status_code == 200 and r.json()["key"] == "sk-first-key-1111" and r.json()["source"] == "account"
    assert r.headers["cache-control"] == "no-store"
    r = client.post("/api/providers/kimi/key", json={"account": second})
    assert r.json() == {"key": "sk-second-key-2222", "source": "account", "label": "Work"}
    provcfg.update_account("kimi", second, {"active": True})
    assert client.post("/api/providers/kimi/key").json()["key"] == "sk-second-key-2222"
    # the list the page shows still holds only the hint, never the key
    listed = client.get("/api/providers").json()["configured"][0]
    assert "sk-second-key-2222" not in str(listed) and listed["keyHint"].endswith("2222")


def test_a_key_from_the_environment_is_copied_too(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-3333")
    provcfg.upsert("openai", {"name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "catalog": "openai"})
    r = client.post("/api/providers/openai/key", json={})
    assert r.json()["key"] == "sk-from-env-3333" and r.json()["source"] == "environment"


def test_a_sign_in_has_no_key_to_copy(client):
    aid = provcfg.add_account("antigravity", {"auth": {"type": "antigravity", "account": "one@example.com", "access": "t1"}},
                              {"name": "Antigravity", "kind": "gemini", "base_url": "https://x"}, activate=True)
    r = client.post("/api/providers/antigravity/key", json={"account": aid})
    assert r.status_code == 400 and "sign-in" in r.json()["error"]
    assert client.post("/api/providers/nope/key", json={}).status_code == 404
    assert client.post("/api/providers/antigravity/key", json={"account": "missing"}).status_code == 404


def test_never_through_remote_control(client, monkeypatch):
    provcfg.upsert("kimi", {"name": "Kimi", "kind": "openai", "base_url": "https://x/v1", "api_key": "sk-first-key-1111"})
    monkeypatch.setitem(remote.state, "port", 80)  # the test client's requests arrive on port 80
    monkeypatch.setitem(remote.state, "tokens", {"phone"})
    r = client.post("/api/providers/kimi/key", json={}, headers={"x-afh-token": "phone"})
    assert r.status_code == 403 and "sk-" not in r.text
