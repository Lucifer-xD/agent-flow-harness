"""Tests for afh.builtin_prompts (live GitHub fetch + disk cache + selection rules)."""

from __future__ import annotations

import json

import httpx
import pytest

from afh import builtin_prompts as bp

HARNESS_START = "You are an AI agent running in OpenCode"


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "cache" / "builtin-prompts.json"
    monkeypatch.setattr(bp, "CACHE_PATH", path)
    return path


def test_live_fetch_then_cache(cache_path, monkeypatch):
    out = bp.get_prompts(force=True)
    assert out["stale"] is False and out["source"].startswith("https://github.com/anomalyco/opencode")
    assert out["harness"].startswith(HARNESS_START) and bp.TOOL_GUIDANCE_PLACEHOLDER in out["harness"]
    assert set(bp.KNOWN_PROVIDER_KEYS) <= set(out["providers"])
    assert out["providers"]["anthropic"].startswith("# Code comments")
    assert out["providers"]["gpt"].startswith(HARNESS_START)
    assert bp.MODEL_NAME_PLACEHOLDER in out["providers"]["meta"]
    assert out["selection_rules"] == bp.SELECTION_RULES
    assert cache_path.is_file()
    assert json.loads(cache_path.read_text(encoding="utf-8"))["harness"] == out["harness"]

    # second call: served from cache, no network
    def boom(*a, **kw):
        raise AssertionError("network used although cache is fresh")

    monkeypatch.setattr(bp, "fetch_prompts", boom)
    again = bp.get_prompts()
    assert again["harness"] == out["harness"] and again["stale"] is False


def test_stale_cache_when_offline(cache_path, monkeypatch):
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps({"fetchedAt": "2020-01-01T00:00:00+00:00", "source": "x", "harness": "old", "providers": {"gpt": "g"}}),
        encoding="utf-8",
    )

    def offline():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bp, "fetch_prompts", offline)
    out = bp.get_prompts()
    assert out["harness"] == "old" and out["stale"] is True and "offline" in out["error"]


def test_bundled_fallback_when_offline_without_cache(cache_path, monkeypatch):
    monkeypatch.setattr(bp.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    out = bp.get_prompts(force=True)
    assert out["source"] == "bundled" and out["harness"] == bp.FALLBACK_HARNESS
    assert out["harness"].startswith(HARNESS_START) and out["providers"] == {}
    assert not cache_path.exists()


def test_bundled_fallback_matches_live():
    live = bp.fetch_prompts()["harness"]
    assert live.strip() == bp.FALLBACK_HARNESS.strip(), "system.txt changed upstream; refresh FALLBACK_HARNESS"


@pytest.mark.parametrize(
    "provider, model, expected",
    [
        ("anthropic", "claude-sonnet-5-5", "anthropic"),
        ("openai", "gpt-6.1", "gpt"),
        ("openai", "gpt-6-astra", "gpt-astra"),
        ("kimi-code-plan-global", "k3.1-pro", "kimi"),
        ("moonshotai", "kimi-k3", "kimi"),
        ("zai-coding-plan", "glm-5.3", "harness"),
        ("muse", "muse", "meta"),
        ("arcee-ai", "trinity-large", "trinity"),
        ("openrouter", "anthropic/claude-opus-5", "anthropic"),
    ],
)
def test_pick_for_model(provider, model, expected):
    assert bp.pick_for_model(provider, model, None) == expected


def test_pick_for_model_strict_only_uses_model_id():
    assert bp.pick_for_model("kimi-code-plan-global", "k3.1-pro", None, strict=True) == "harness"
    assert bp.pick_for_model("x", "y", "claude", strict=True) == "harness"
    assert bp.pick_for_model("x", "y", "claude") == "anthropic"


def test_render_and_compose():
    text = bp.render("a\n${OPENCODE_TOOL_GUIDANCE}\nb", ["shell", "edit"])
    assert "${OPENCODE_TOOL_GUIDANCE}" not in text and "Prefer dedicated tools" in text and "edit tool" in text
    assert "write tool" not in text
    assert bp.render("x\n${OPENCODE_TOOL_GUIDANCE}", []) == "x\n"

    prompts = {"harness": "H ${OPENCODE_TOOL_GUIDANCE}", "providers": {"anthropic": "A", "meta": "M {{MODEL_NAME}}", "gpt": "G"}}
    assert bp.compose_for_model("anthropic", "claude-x", prompts=prompts, tools=()) == {"key": "anthropic", "mode": "append", "text": "H \n\nA"}
    assert bp.compose_for_model("muse", "muse", model_name="Muse Spark", prompts=prompts, tools=())["text"] == "M Muse Spark"
    assert bp.compose_for_model("openai", "gpt-6", prompts=prompts, tools=())["text"] == "G"
    assert bp.compose_for_model("zai", "glm-5", prompts=prompts, tools=()) == {"key": "harness", "mode": "default", "text": "H "}
    missing = bp.compose_for_model("x", "kimi-k3", prompts=prompts, tools=())
    assert missing["key"] == "kimi" and missing["missing"] == "kimi" and missing["text"] == "H "
