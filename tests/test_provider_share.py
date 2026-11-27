"""Share a provider (engine/share.py, /api/providers/{id}/share, /api/provider-share/*): one code
carries the whole provider, with or without its keys and sign-ins, optionally locked with a
password; applying it adds the provider, replaces yours, adds only its accounts, or keeps both."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from afh import api as apimod
from afh import remote
from afh.engine import config as provcfg
from afh.engine import share
from tests.test_engine_features import home  # noqa: F401  (fixture)


@pytest.fixture
def client(home, monkeypatch):  # noqa: F811
    monkeypatch.setitem(apimod.ACCESS, "token", "")
    monkeypatch.setitem(apimod.ACCESS, "hosts", set())
    monkeypatch.setitem(remote.state, "port", 0)

    async def no_refresh(pid):
        return None

    monkeypatch.setattr(apimod.engine, "refresh_models", no_refresh)
    return TestClient(apimod.app)


def make_remote():
    provcfg.upsert("lucifer", {"name": "Lucifer (remote)", "kind": "openai", "base_url": "http://192.168.1.20:8080/v1", "fetch_models": False,
                               "headers": {"Authorization": "Bearer hdr-secret", "X-Title": "AFH"},
                               "models": [{"id": "qwen3.8", "name": "Qwen3.8 Uncensored"}, {"id": "small", "name": "Small"}],
                               "overrides": {"qwen3.8": {"variants": ["low", "high", "max"], "context": 262144}},
                               "hidden": ["small"], "prices": {"qwen3.8": {"input": 0.1, "output": 0.2}}, "extra": {"temperature": 1},
                               "api_key": "sk-remote-key-2366d"})
    return provcfg.add_account("lucifer", {"api_key": "sk-second-key-9999"}, label="Backup")


def wipe():
    provcfg.remove("lucifer")
    assert provcfg.entry("lucifer") is None


def test_round_trip_carries_everything(client):
    second = make_remote()
    code = client.post("/api/providers/lucifer/share", json={}).json()["code"]
    assert code.startswith(share.PLAIN) and "sk-remote" not in code  # compressed, not readable at a glance
    before = provcfg.entry("lucifer")
    wipe()
    pre = client.post("/api/provider-share/read", json={"code": code}).json()
    assert pre["name"] == "Lucifer (remote)" and pre["secrets"] and not pre["exists"]
    assert [a["label"] for a in pre["accounts"]] == ["Key ••••366d", "Backup"]
    assert pre["local"] == "192.168.1.20" and pre["effortModels"] == 1 and pre["shownCount"] == 1
    assert "sk-" not in str(pre) and "hdr-secret" not in str(pre)  # the preview never holds a secret
    out = client.post("/api/provider-share/apply", json={"code": code}).json()
    assert out["providerID"] == "lucifer" and out["mode"] == "new"
    after = provcfg.entry("lucifer")
    for k in ("name", "base_url", "headers", "models", "overrides", "hidden", "prices", "extra", "accounts", "active", "api_key"):
        assert after[k] == before[k], k
    assert after["enabled"] is True
    cfg = provcfg.provider_config("lucifer")
    assert cfg.api_key == "sk-remote-key-2366d"
    qwen = next(m for m in cfg.models if m.id == "qwen3.8")
    assert qwen.variants == ["low", "high", "max"] and qwen.context == 262144 and qwen.reasoning
    assert any(a["id"] == second for a in after["accounts"])


def test_without_secrets_drops_keys_sign_ins_and_auth_headers(client):
    make_remote()
    code = client.post("/api/providers/lucifer/share", json={"secrets": False}).json()["code"]
    data = share.decode(code)
    p = data["provider"]
    assert not data["secrets"] and "accounts" not in p and "api_key" not in p and "auth" not in p
    assert p["headers"] == {"X-Title": "AFH"} and p["overrides"]["qwen3.8"]["variants"] == ["low", "high", "max"]


def test_password_lock(client):
    make_remote()
    code = client.post("/api/providers/lucifer/share", json={"password": "open sesame"}).json()["code"]
    assert code.startswith(share.LOCKED)
    assert client.post("/api/provider-share/read", json={"code": code}).json() == {"needsPassword": True, "wrongPassword": False, "error": "This share code is locked with a password"}
    wrong = client.post("/api/provider-share/read", json={"code": code, "password": "nope"}).json()
    assert wrong["needsPassword"] and wrong["wrongPassword"]
    assert client.post("/api/provider-share/apply", json={"code": code, "password": "nope"}).status_code == 400
    ok = client.post("/api/provider-share/read", json={"code": code, "password": "open sesame"}).json()
    assert ok["name"] == "Lucifer (remote)" and not ok["needsPassword"]
    # a changed character anywhere is caught, not applied
    bad = code[:-8] + ("A" if code[-8] != "A" else "B") + code[-7:]
    assert client.post("/api/provider-share/read", json={"code": bad, "password": "open sesame"}).json()["needsPassword"]


def test_when_the_same_provider_is_already_here(client):
    make_remote()
    code = share.export("lucifer")["code"]
    provcfg.upsert("lucifer", {"name": "Mine", "base_url": "https://mine/v1"})
    mine_accounts = len(provcfg.accounts("lucifer"))
    pre = client.post("/api/provider-share/read", json={"code": code}).json()
    assert pre["exists"] and pre["existingName"] == "Mine" and pre["copyId"] == "lucifer-2"
    # keep both: the shared one under a new id
    out = client.post("/api/provider-share/apply", json={"code": code, "mode": "copy"}).json()
    assert out == {"providerID": "lucifer-2", "mode": "copy", "name": "Lucifer (remote) (shared)", "added": 2}
    assert provcfg.entry("lucifer")["name"] == "Mine" and provcfg.entry("lucifer-2")["base_url"] == "http://192.168.1.20:8080/v1"
    # only the accounts: yours keeps its settings, the shared keys join it (the same key is not added twice)
    out = client.post("/api/provider-share/apply", json={"code": code, "mode": "accounts"}).json()
    assert out["mode"] == "accounts" and provcfg.entry("lucifer")["base_url"] == "https://mine/v1"
    assert len(provcfg.accounts("lucifer")) == mine_accounts  # both keys were already there
    # replace
    out = client.post("/api/provider-share/apply", json={"code": code, "mode": "replace"}).json()
    assert out["mode"] == "replace" and provcfg.entry("lucifer")["name"] == "Lucifer (remote)"


def test_default_model_comes_along_when_asked(client):
    make_remote()
    apimod.store.save_settings({"defaultModel": {"providerID": "lucifer", "id": "qwen3.8", "variant": "high"}})
    code = client.post("/api/providers/lucifer/share", json={}).json()["code"]
    apimod.store.save_settings({"defaultModel": None})
    wipe()
    pre = client.post("/api/provider-share/read", json={"code": code}).json()
    assert pre["defaultModel"] == {"id": "qwen3.8", "variant": "high"}
    client.post("/api/provider-share/apply", json={"code": code, "makeDefault": True})
    assert apimod.store.load_settings()["defaultModel"] == {"providerID": "lucifer", "id": "qwen3.8", "variant": "high"}


def test_sign_ins_travel_with_a_note(client):
    provcfg.add_account("antigravity", {"auth": {"type": "antigravity", "account": "one@example.com", "access": "t1", "refresh": "r1"}},
                        {"name": "Google Antigravity", "kind": "gemini", "base_url": "https://x", "catalog": "antigravity"}, activate=True)
    provcfg.add_account("antigravity", {"auth": {"type": "antigravity", "account": "two@example.com", "access": "t2", "refresh": "r2"}})
    code = share.export("antigravity")["code"]
    provcfg.remove("antigravity")
    pre = share.preview(code)
    assert [a["kind"] for a in pre["accounts"]] == ["signin", "signin"] and pre["signInNote"] and "t1" not in str(pre)
    share.apply(code)
    assert [a["auth"]["refresh"] for a in provcfg.accounts("antigravity")] == ["r1", "r2"]


def test_codes_that_are_not_codes(client):
    for text in ("", "hello", "AFH-PROVIDER-1:@@@", "AFH-PROVIDER-1:" + "A" * 40, "AFH-PROVIDER-9:abc"):
        r = client.post("/api/provider-share/read", json={"code": text})
        assert r.status_code == 400, text
    # a code pasted with a message around it and broken over lines still reads
    make_remote()
    code = share.export("lucifer")["code"]
    wrapped = "Here you go:\n" + "\n".join(code[i:i + 60] for i in range(0, len(code), 60)) + "\nenjoy"
    assert share.preview(wrapped)["name"] == "Lucifer (remote)"


def test_never_through_remote_control(client, monkeypatch):
    make_remote()
    code = share.export("lucifer")["code"]
    monkeypatch.setitem(remote.state, "port", 80)  # the test client's requests arrive on port 80
    monkeypatch.setitem(remote.state, "tokens", {"phone"})
    h = {"x-afh-token": "phone"}
    r = client.post("/api/providers/lucifer/share", json={}, headers=h)
    assert r.status_code == 403 and "AFH-PROVIDER" not in r.text
    assert client.post("/api/provider-share/read", json={"code": code}, headers=h).status_code == 403
    assert client.post("/api/provider-share/apply", json={"code": code}, headers=h).status_code == 403
