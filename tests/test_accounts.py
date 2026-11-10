"""Several accounts per provider (engine/config.py, engine/accounts.py, engine/limits.py): storage,
sorting refusals, and a running task moving to the next account without stopping."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from afh.engine import accounts as accmod
from afh.engine import config as provcfg
from afh.engine import limits, usage
from afh.engine.runner import to_chat
from afh.engine.types import ModelInfo, ProviderConfig
from tests.test_engine_features import home, make_engine, run_prompt  # noqa: F401  (fixture)


@pytest.fixture
def state(home, monkeypatch):  # noqa: F811
    monkeypatch.setattr(accmod, "STATE", home / "account-state.json")
    usage._cache.clear()
    usage._headers.clear()
    return home


# ---- storage ---------------------------------------------------------------------------------------


def test_an_old_single_key_becomes_account_one(state):
    provcfg.PATH.write_text(json.dumps({"providers": {"kimi": {"id": "kimi", "name": "Kimi", "kind": "openai", "base_url": "https://x/v1", "api_key": "sk-old-key-1234"}}}))
    p = provcfg.entry("kimi")
    assert len(p["accounts"]) == 1 and p["accounts"][0]["api_key"] == "sk-old-key-1234" and p["active"] == p["accounts"][0]["id"]
    cfg = provcfg.provider_config("kimi")
    assert cfg.api_key == "sk-old-key-1234" and cfg.account_id == p["active"]
    # typing a new key in the provider form replaces the key of the account in use, not adds one
    provcfg.upsert("kimi", {"api_key": "sk-new-key-5678"})
    p = provcfg.entry("kimi")
    assert len(p["accounts"]) == 1 and p["accounts"][0]["api_key"] == "sk-new-key-5678" and p["api_key"] == "sk-new-key-5678"


def test_sign_ins_add_accounts_and_the_same_account_only_renews(state):
    base = {"name": "Antigravity", "kind": "antigravity", "base_url": "https://g"}
    a1 = provcfg.add_account("antigravity", {"auth": {"type": "antigravity", "account": "one@example.com", "access": "t1"}}, base, activate=True)
    a2 = provcfg.add_account("antigravity", {"auth": {"type": "antigravity", "account": "two@example.com", "access": "t2"}}, base, activate=False)
    again = provcfg.add_account("antigravity", {"auth": {"type": "antigravity", "account": "ONE@example.com", "access": "t1b"}}, base, activate=True)
    p = provcfg.entry("antigravity")
    assert again == a1 and a1 != a2 and len(p["accounts"]) == 2
    assert p["active"] == a1 and p["auth"]["access"] == "t1b"  # renewed, still in use
    # a refreshed token goes to its own account; the provider's copy only follows the one in use
    provcfg.save_creds("antigravity", a2, {"auth": {"type": "antigravity", "account": "two@example.com", "access": "t2-fresh"}})
    p = provcfg.entry("antigravity")
    assert p["auth"]["access"] == "t1b" and next(a for a in p["accounts"] if a["id"] == a2)["auth"]["access"] == "t2-fresh"
    assert provcfg.account_config("antigravity", a2).auth["access"] == "t2-fresh"
    view = provcfg.public(p)
    assert [a["label"] for a in view["accounts"]] == ["ONE@example.com", "two@example.com"] and view["accounts"][0]["kind"] == "signin"
    assert "t1b" not in json.dumps(view)  # never the tokens


def test_order_switch_off_and_remove(state):
    ids = [provcfg.add_account("zai", {"api_key": f"sk-zai-key-000{n}"}, {"name": "Z.ai", "kind": "openai", "base_url": "https://z"}) for n in range(3)]
    p = provcfg.entry("zai")
    assert p["active"] == ids[0] and [a["id"] for a in p["accounts"]] == ids
    provcfg.update_account("zai", ids[2], {"move": -1})
    assert [a["id"] for a in provcfg.entry("zai")["accounts"]] == [ids[0], ids[2], ids[1]]
    provcfg.update_account("zai", ids[0], {"enabled": False})  # switching off the one in use moves on
    assert provcfg.entry("zai")["active"] == ids[2]
    provcfg.update_account("zai", ids[1], {"active": True, "label": "Spare"})
    p = provcfg.entry("zai")
    assert p["active"] == ids[1] and p["api_key"] == "sk-zai-key-0001" and provcfg.account_label(p["accounts"][2]) == "Spare"
    provcfg.remove_account("zai", ids[1])
    p = provcfg.entry("zai")
    assert p["active"] == ids[2] and p["api_key"] == "sk-zai-key-0002"
    provcfg.remove_account("zai", ids[2])
    provcfg.remove_account("zai", ids[0])
    p = provcfg.entry("zai")
    assert p["accounts"] == [] and "api_key" not in p


# ---- what a refusal means --------------------------------------------------------------------------


def ev(status, body, headers=None, kind="http"):
    return {"type": "error", "status": status, "kind": kind, "message": body[:200], "response": body, **({"headers": headers} if headers else {})}


@pytest.mark.parametrize("sample, want", [
    (ev(429, '{"error":{"code":429,"message":"You exceeded your current quota, please check your plan and billing details.","status":"RESOURCE_EXHAUSTED"}}'), "used_up"),
    (ev(429, '{"error":{"code":429,"message":"No capacity available for model gemini-3-pro on the server","status":"RESOURCE_EXHAUSTED","details":[{"reason":"MODEL_CAPACITY_EXHAUSTED"}]}}'), "overloaded"),
    (ev(529, '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'), "overloaded"),
    (ev(429, '{"type":"error","error":{"type":"rate_limit_error","message":"This request would exceed the rate limit for your organization"}}', {"retry-after": "30"}), "used_up"),
    (ev(429, '{"error":{"type":"usage_limit_reached","message":"The usage limit has been reached","resets_in_seconds":1800}}'), "used_up"),
    (ev(429, '{"error":{"message":"You exceeded your current quota","type":"insufficient_quota","code":"insufficient_quota"}}'), "used_up"),
    (ev(429, '{"error":{"code":"1308","message":"Usage limit reached for 5 hour. Your limit will reset at 2026-11-10 18:00:00"}}'), "used_up"),
    (ev(429, '{"error":{"code":"1305","message":"The service may be temporarily overloaded, please try again later"}}'), "overloaded"),
    (ev(429, '{"error":{"type":"engine_overloaded_error","message":"The engine is currently overloaded, please try again later"}}'), "overloaded"),
    (ev(429, '{"error":{"type":"exceeded_current_quota_error","message":"Your account has exceeded its current quota"}}'), "used_up"),
    (ev(402, '{"error":{"message":"Insufficient Balance"}}'), "used_up"),
    (ev(400, '{"error":{"message":"Invalid tool schema"}}'), "other"),
    (ev(401, '{"error":{"message":"Invalid API key"}}'), "other"),
    (ev(None, "Connection reset", kind="network"), "other"),
])
def test_refusals_are_sorted(sample, want):
    assert limits.classify(sample)[0] == want


def test_reset_times_are_read():
    now = time.time()
    assert abs(limits.classify(ev(429, '{"error":{"type":"usage_limit_reached","resets_in_seconds":1800}}'))[1] - (now + 1800)) < 5
    assert abs(limits.classify(ev(429, '{"error":{"type":"rate_limit_error"}}', {"retry-after": "30"}))[1] - (now + 30)) < 5
    assert abs(limits.reset_time(ev(429, '{"error":{"details":[{"retryDelay":"42s"}]}}')) - (now + 42)) < 5
    assert limits.reset_time(ev(429, '{"resets_at": 1893456000}')) == 1893456000
    # nothing given: a plan rests an hour, a rate limit a minute
    assert abs(limits.classify(ev(429, '{"error":{"message":"quota exceeded"}}'))[1] - (now + limits.PLAN_REST)) < 5
    assert abs(limits.classify(ev(429, '{"error":{"message":"Too many requests"}}'))[1] - (now + limits.RATE_REST)) < 5


# ---- a running task moves between accounts ---------------------------------------------------------


class Acct:
    """One account of the fake provider: answers from a script, or refuses with ``refuse``."""

    def __init__(self, aid: str, label: str, replies=None, refuse: dict | None = None, used: float | None = None):
        self.config = ProviderConfig(id="fake", name="Fake", kind="openai", base_url="http://fake", api_key=f"sk-{aid}", account_id=aid, account_label=label)
        self.replies, self.refuse, self.used, self.calls = list(replies or []), refuse, used, 0

    async def stream(self, req):
        self.calls += 1
        if self.refuse:
            yield self.refuse
            return
        if self.used is not None:  # what the provider's headers would have said
            usage.observe(usage.key(self.config), {"x-codex-primary-used-percent": str(self.used), "x-codex-primary-window-minutes": "300",
                                                   "x-codex-primary-reset-after-seconds": "3600"})
        reply = self.replies.pop(0) if self.replies else "All done."
        if isinstance(reply, str):
            yield {"type": "text.delta", "text": reply}
        else:
            for n, (name, inp) in enumerate(reply):
                yield {"type": "tool.start", "id": f"c{self.config.account_id}{self.calls}{n}", "name": name}
                yield {"type": "tool.end", "id": f"c{self.config.account_id}{self.calls}{n}", "name": name, "input": inp, "raw": json.dumps(inp)}
        yield {"type": "usage", "input": 10, "output": 5, "reasoning": 0, "cache_read": 0, "cache_write": 0}
        yield {"type": "finish", "reason": "stop" if isinstance(reply, str) else "tool_calls"}

    async def list_models(self):
        return []


def three_accounts(*accts: Acct):
    data = {"providers": {"fake": {"id": "fake", "name": "Fake", "kind": "openai", "base_url": "http://fake", "enabled": True, "fetch_models": False,
                                   "accounts": [{"id": a.config.account_id, "label": a.config.account_label, "api_key": a.config.api_key, "enabled": True} for a in accts],
                                   "active": accts[0].config.account_id, "api_key": accts[0].config.api_key}}}
    provcfg.PATH.write_text(json.dumps(data))
    by_id = {a.config.account_id: a for a in accts}
    e = make_engine(accts[0])
    e.models = {"fake": [ModelInfo(id="m", name="M", context=100_000, output=4096)]}

    def use_account(pid):
        e.providers[pid] = by_id[provcfg.entry(pid)["active"]]
        return e.providers[pid]

    e.use_account = use_account
    return e


TODO = [("todo", {"todos": [{"content": "Do it", "status": "completed"}]})]
QUOTA = ev(429, '{"error":{"message":"You exceeded your current quota","type":"insufficient_quota"}}', {"retry-after": "3600"})


def test_a_refused_step_runs_again_on_the_next_account(state, tmp_path):
    a = Acct("a1", "first@example.com", refuse=QUOTA)
    b = Acct("a2", "second@example.com", replies=[TODO, "Finished."])
    c = Acct("a3", "third@example.com")
    e = three_accounts(a, b, c)
    s = asyncio.run(run_prompt(e, tmp_path, "build it"))
    msgs = e.store.list_messages(s["id"])
    assert a.calls == 1 and b.calls == 2 and c.calls == 0
    notes = [m for m in msgs if m.get("type") == "synthetic" and (m.get("metadata") or {}).get("notice") == "account"]
    assert len(notes) == 1 and "first@example.com to second@example.com" in notes[0]["metadata"]["label"] and "hit its limit" in notes[0]["metadata"]["label"]
    assert notes[0]["text"] == ""  # shown in the thread, never sent to the model
    assert not any("Account switched" in (m.text or "") for m in to_chat(msgs))
    done = [m for m in msgs if m.get("type") == "assistant" and m.get("finish") != "switched"]
    assert done[-1]["content"][0]["text"] == "Finished." and done[-1]["account"]["id"] == "a2"
    assert provcfg.entry("fake")["active"] == "a2" and accmod.resting("fake", "a1")
    assert not any(ev_["type"] == "session.execution.failed" for ev_ in e.events)


def test_near_the_threshold_the_next_step_moves_on(state, tmp_path):
    a = Acct("a1", "Work", replies=[TODO], used=93)  # the answer says 93% of the 5-hour window
    b = Acct("a2", "Home", replies=["Finished on the second account."], used=10)
    e = three_accounts(a, b)
    s = asyncio.run(run_prompt(e, tmp_path, "go"))
    msgs = e.store.list_messages(s["id"])
    note = next(m for m in msgs if (m.get("metadata") or {}).get("notice") == "account")
    assert "from Work to Home" in note["metadata"]["label"] and "93%" in note["metadata"]["label"]
    steps = [m for m in msgs if m.get("type") == "assistant"]
    assert [m["account"]["id"] for m in steps] == ["a1", "a2"] and a.calls == 1 and b.calls == 1


def test_under_the_threshold_nothing_changes(state, tmp_path):
    a = Acct("a1", "Work", replies=[TODO, "Done."], used=40)
    b = Acct("a2", "Home")
    e = three_accounts(a, b)
    s = asyncio.run(run_prompt(e, tmp_path, "go"))
    assert a.calls == 2 and b.calls == 0
    assert not any((m.get("metadata") or {}).get("notice") == "account" for m in e.store.list_messages(s["id"]))


def test_rotation_off_keeps_the_old_behaviour(state, tmp_path):
    a = Acct("a1", "Work", refuse=ev(400, '{"error":{"message":"quota exceeded"}}'))
    b = Acct("a2", "Home")
    e = three_accounts(a, b)
    provcfg.set_rotation("fake", False)
    asyncio.run(run_prompt(e, tmp_path, "go"))
    assert b.calls == 0 and any(x["type"] == "session.execution.failed" for x in e.events)


def test_when_all_are_used_up_it_waits_then_continues(state, tmp_path, monkeypatch):
    a = Acct("a1", "Work", replies=["Back at work."])
    b = Acct("a2", "Home")
    e = three_accounts(a, b)
    accmod.rest("fake", "a1", time.time() + 0.6, "quota")
    accmod.rest("fake", "a2", time.time() + 30, "quota")
    s = asyncio.run(run_prompt(e, tmp_path, "go"))
    labels = [(m.get("metadata") or {}).get("label", "") for m in e.store.list_messages(s["id"]) if m.get("type") == "synthetic"]
    assert any(x.startswith("All 2 Fake accounts are used up. Waiting until") for x in labels)
    assert a.calls == 1 and e.store.list_messages(s["id"])[-1]["content"][0]["text"] == "Back at work."


def test_when_all_are_used_up_it_can_stop_instead(state, tmp_path):
    from afh import store as appstore

    a, b = Acct("a1", "Work"), Acct("a2", "Home")
    e = three_accounts(a, b)
    appstore.save_settings({"defaultMode": "full", "accounts": {"whenAllUsed": "stop"}})
    accmod.rest("fake", "a1", time.time() + 600, "quota")
    accmod.rest("fake", "a2", time.time() + 900, "quota")
    asyncio.run(run_prompt(e, tmp_path, "go"))
    failed = [x for x in e.events if x["type"] == "session.execution.failed"]
    assert failed and "All 2 Fake accounts are used up" in failed[0]["data"]["error"]["message"] and a.calls == 0


def test_antigravity_counts_only_the_model_family_in_use():
    rep = {"windows": [{"id": "claude", "label": "Claude", "usedPercent": 97.0, "resetsAt": None},
                       {"id": "gemini-pro", "label": "Gemini Pro", "usedPercent": 20.0, "resetsAt": None}]}
    assert accmod.used(rep, "gemini-3-pro-high")[0] == 20.0
    assert accmod.used(rep, "claude-sonnet-4-6")[0] == 97.0
    assert accmod.used(rep, "gemini-3-flash")[0] is None  # no Flash window reported
    assert accmod.used({"windows": [], "limited": True}, "x")[0] == 100.0
