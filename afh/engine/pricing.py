"""What a model call costs.

Prices are USD per million tokens: ``{"input", "output", "cacheRead", "cacheWrite"}``. They come from
(1) what the user typed in Settings → Usage & cost (``providers.json`` → ``prices``), then
(2) what the provider's model list reports (OpenRouter does). AFH ships no guessed prices: when a
price is unknown the cost shows as unknown instead of a made-up number. Subscription "coding
plans" have no per-token cost.
"""

from __future__ import annotations

from .types import ModelInfo

PLAN_PROVIDERS = ("kimi", "zai-coding", "kimi-code-plan-global", "kimi-code-plan", "zai-coding-plan")  # flat-rate coding plans (AFH and OpenCode ids)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def clean_price(p: dict | None) -> dict | None:
    if not isinstance(p, dict):
        return None
    out = {}
    for key in ("input", "output", "cacheRead", "cacheWrite"):
        v = _num(p.get(key))
        if v is not None:
            out[key] = v
    return out if ("input" in out or "output" in out) else None


def price_for(provider_entry: dict | None, provider_id: str, model: ModelInfo | None) -> dict | None:
    entry = provider_entry or {}
    mid = model.id if model else ""
    user = clean_price((entry.get("prices") or {}).get(mid))
    if user:
        return user
    if model and model.cost:
        return clean_price(model.cost)
    return None


def is_plan(provider_entry: dict | None, provider_id: str) -> bool:
    entry = provider_entry or {}
    if "plan" in entry:
        return bool(entry["plan"])
    return (entry.get("catalog") or provider_id) in PLAN_PROVIDERS


def cost_of(tokens: dict, price: dict | None) -> float | None:
    """USD for one step's tokens. ``input`` is uncached input; reasoning is billed as output by
    every provider AFH supports and is already part of ``output`` where the API counts it so."""
    if not price:
        return None
    cache = tokens.get("cache") or {}
    pin = price.get("input", 0.0)
    total = (tokens.get("input", 0) * pin
             + tokens.get("output", 0) * price.get("output", 0.0)
             + cache.get("read", 0) * price.get("cacheRead", pin)
             + cache.get("write", 0) * price.get("cacheWrite", pin))
    return round(total / 1_000_000, 8)


def from_openrouter(pricing: dict | None) -> dict | None:
    """OpenRouter lists USD per token as strings: {"prompt": "0.000003", "completion": "0.000015", ...}."""
    if not isinstance(pricing, dict):
        return None
    per = lambda k: (_num(pricing.get(k)) or 0.0) * 1_000_000  # noqa: E731
    out = {"input": per("prompt"), "output": per("completion")}
    if _num(pricing.get("input_cache_read")) is not None:
        out["cacheRead"] = per("input_cache_read")
    if _num(pricing.get("input_cache_write")) is not None:
        out["cacheWrite"] = per("input_cache_write")
    return out if (out["input"] or out["output"]) else None
