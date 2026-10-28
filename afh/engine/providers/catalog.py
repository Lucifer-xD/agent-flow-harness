"""Known providers, static model lists and model-id heuristics.

``KNOWN`` is what the Models tab offers as one-click providers. ``STATIC_MODELS`` covers
providers whose ``/models`` endpoint is missing or too poor to drive the UI (no context sizes,
no reasoning flag). The heuristics here are only fallbacks for ids we have never seen.
"""

from __future__ import annotations

import httpx

from afh.engine.types import ModelInfo, Provider, ProviderConfig

# ---- one-click providers -------------------------------------------------------------------
# id, display name, wire protocol, base URL, env vars that may hold the key, docs link, adapter knobs.
# ``needs_key`` False = local servers that accept any/no key.

KNOWN: dict[str, dict] = {
    "openai": {
        "name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1",
        "env": ["OPENAI_API_KEY"], "docs": "https://platform.openai.com/docs/api-reference/chat",
        # New OpenAI models reject ``max_tokens``; effort values are OpenAI's own words.
        "extra": {"max_tokens_param": "max_completion_tokens", "effort_map": {"max": "high"}},
    },
    "anthropic": {
        "name": "Anthropic", "kind": "anthropic", "base_url": "https://api.anthropic.com",
        "env": ["ANTHROPIC_API_KEY"], "docs": "https://docs.anthropic.com/en/api/messages", "extra": {},
    },
    "gemini": {
        "name": "Google Gemini", "kind": "gemini", "base_url": "https://generativelanguage.googleapis.com",
        "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "docs": "https://ai.google.dev/api/generate-content", "extra": {},
    },
    "kimi": {
        "name": "Kimi (kimi.ai coding plan)", "kind": "openai", "base_url": "https://api.kimi.ai/coding/v1",
        "env": ["KIMI_API_KEY"], "docs": "https://platform.kimi.ai/docs",
        # Kimi thinking models want their reasoning echoed back on tool-call turns.
        "extra": {"echo_reasoning": True}, "fetch_models": False,
    },
    "moonshot": {
        "name": "Moonshot AI", "kind": "openai", "base_url": "https://api.moonshot.ai/v1",
        "env": ["MOONSHOT_API_KEY"], "docs": "https://platform.moonshot.ai/docs", "extra": {"echo_reasoning": True},
    },
    "zai": {
        "name": "Z.AI", "kind": "openai", "base_url": "https://api.z.ai/api/paas/v4",
        "env": ["ZAI_API_KEY", "ZHIPU_API_KEY"], "docs": "https://docs.z.ai/api-reference", "extra": {"thinking": "zai"},
    },
    "zai-coding": {
        "name": "Z.AI (coding plan)", "kind": "openai", "base_url": "https://api.z.ai/api/coding/paas/v4",
        "env": ["ZAI_API_KEY", "ZHIPU_API_KEY"], "docs": "https://docs.z.ai/devpack/overview",
        "extra": {"thinking": "zai"}, "fetch_models": False,
    },
    "deepseek": {
        "name": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1",
        "env": ["DEEPSEEK_API_KEY"], "docs": "https://api-docs.deepseek.com", "extra": {},
    },
    "groq": {
        "name": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1",
        "env": ["GROQ_API_KEY"], "docs": "https://console.groq.com/docs/api-reference", "extra": {},
    },
    "openrouter": {
        "name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
        "env": ["OPENROUTER_API_KEY"], "docs": "https://openrouter.ai/docs/api-reference/overview",
        "headers": {"X-Title": "Agent Flow Harness"},
        "extra": {"effort_style": "openrouter"},  # ``{"reasoning": {"effort": ...}}``
    },
    "mistral": {
        "name": "Mistral", "kind": "openai", "base_url": "https://api.mistral.ai/v1",
        "env": ["MISTRAL_API_KEY"], "docs": "https://docs.mistral.ai/api", "extra": {},
    },
    "xai": {
        "name": "xAI", "kind": "openai", "base_url": "https://api.x.ai/v1",
        "env": ["XAI_API_KEY"], "docs": "https://docs.x.ai/docs/api-reference", "extra": {},
    },
    "together": {
        "name": "Together AI", "kind": "openai", "base_url": "https://api.together.xyz/v1",
        "env": ["TOGETHER_API_KEY"], "docs": "https://docs.together.ai/reference/chat-completions-1", "extra": {},
    },
    "fireworks": {
        "name": "Fireworks AI", "kind": "openai", "base_url": "https://api.fireworks.ai/inference/v1",
        "env": ["FIREWORKS_API_KEY"], "docs": "https://docs.fireworks.ai/api-reference/post-chatcompletions", "extra": {},
    },
    "cerebras": {
        "name": "Cerebras", "kind": "openai", "base_url": "https://api.cerebras.ai/v1",
        "env": ["CEREBRAS_API_KEY"], "docs": "https://inference-docs.cerebras.ai/api-reference/chat-completions", "extra": {},
    },
    "perplexity": {
        "name": "Perplexity", "kind": "openai", "base_url": "https://api.perplexity.ai",
        "env": ["PERPLEXITY_API_KEY"], "docs": "https://docs.perplexity.ai/api-reference/chat-completions", "extra": {},
    },
    "ollama": {
        "name": "Ollama (local)", "kind": "openai", "base_url": "http://localhost:11434/v1",
        "env": [], "docs": "https://github.com/ollama/ollama/blob/main/docs/openai.md", "extra": {}, "needs_key": False,
    },
    "lmstudio": {
        "name": "LM Studio (local)", "kind": "openai", "base_url": "http://localhost:1234/v1",
        "env": [], "docs": "https://lmstudio.ai/docs/app/api/endpoints/openai", "extra": {}, "needs_key": False,
    },
    "vllm": {
        "name": "vLLM (local)", "kind": "openai", "base_url": "http://localhost:8000/v1",
        "env": [], "docs": "https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html", "extra": {},
        "needs_key": False, "custom_url": True,
    },
}

# OpenCode provider ids → AFH catalog ids (None = no equivalent, the migration skips it).
OPENCODE_TO_AFH: dict[str, str | None] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",
    "kimi-code-plan-global": "kimi",
    "kimi-code-plan": "moonshot",
    "moonshotai": "moonshot",
    "moonshot": "moonshot",
    "zai-coding-plan": "zai-coding",
    "zai": "zai",
    "zhipuai": "zai",
    "deepseek": "deepseek",
    "groq": "groq",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "xai": "xai",
    "togetherai": "together",
    "fireworks-ai": "fireworks",
    "cerebras": "cerebras",
    "perplexity": "perplexity",
    "ollama": "ollama",
    "lmstudio": "lmstudio",
    "vllm": "vllm",
    # OAuth/cloud integrations the engine cannot drive with an API key.
    "github-copilot": None,
    "opencode": None,
    "amazon-bedrock": None,
    "google-vertex": None,
    "google-vertex-anthropic": None,
    "azure": None,
}


# ---- static model lists --------------------------------------------------------------------


def _m(id: str, name: str, context: int, output: int = 16_384, reasoning: bool = False,
       variants: list[str] | None = None, image: bool = True, hidden: bool = False) -> ModelInfo:
    return ModelInfo(id=id, name=name, context=context, output=output, tools=True, reasoning=reasoning,
                     variants=list(variants or []), input=["text", "image"] if image else ["text"], hidden=hidden)


_LHM = ["low", "high", "max"]
_LMH = ["low", "medium", "high"]

STATIC_MODELS: dict[str, list[ModelInfo]] = {
    "kimi": [
        _m("k3.1-pro", "Kimi K3.1 Pro", 1_000_000, 65_536, reasoning=True, variants=_LHM),
        _m("k3.1-pro-highspeed", "Kimi K3.1 Pro (high speed)", 1_000_000, 65_536, reasoning=True, variants=_LHM),
        _m("k3", "Kimi K3", 128_000, 32_768, reasoning=True, variants=_LHM),
        _m("k3-256k", "Kimi K3 (256k)", 256_000, 32_768, reasoning=True, variants=_LHM),
    ],
    "moonshot": [
        _m("kimi-k3.1-pro", "Kimi K3.1 Pro", 1_000_000, 65_536, reasoning=True, variants=_LHM),
        _m("kimi-k3", "Kimi K3", 128_000, 32_768, reasoning=True, variants=_LHM),
        _m("kimi-k2.5", "Kimi K2.5", 256_000, 32_768, reasoning=True, variants=_LHM),
    ],
    "zai-coding": [
        _m("glm-5.3", "GLM-5.3", 200_000, 65_536, reasoning=True, variants=["high"], image=False),
        _m("glm-5.3-flash", "GLM-5.3 Flash", 200_000, 32_768, reasoning=True, variants=["high"], image=False),
        _m("glm-5.3-highspeed", "GLM-5.3 (high speed)", 200_000, 65_536, reasoning=True, variants=["high"], image=False),
        _m("glm-5.3v", "GLM-5.3V", 128_000, 32_768, reasoning=True, variants=["high"]),
    ],
    "zai": [
        _m("glm-5.3", "GLM-5.3", 200_000, 65_536, reasoning=True, variants=["high"], image=False),
        _m("glm-5.3-flash", "GLM-5.3 Flash", 200_000, 32_768, reasoning=True, variants=["high"], image=False),
        _m("glm-5.3v", "GLM-5.3V", 128_000, 32_768, reasoning=True, variants=["high"]),
    ],
    "anthropic": [
        _m("claude-opus-5-5", "Claude Opus 5.5", 200_000, 64_000, reasoning=True, variants=_LHM),
        _m("claude-sonnet-5-5", "Claude Sonnet 5.5", 200_000, 64_000, reasoning=True, variants=_LHM),
        _m("claude-haiku-5-5", "Claude Haiku 5.5", 200_000, 32_000, reasoning=True, variants=_LHM),
    ],
    "openai": [
        _m("gpt-6.1", "GPT-6.1", 1_000_000, 128_000, reasoning=True, variants=_LMH),
        _m("gpt-6.1-mini", "GPT-6.1 mini", 1_000_000, 128_000, reasoning=True, variants=_LMH),
        _m("gpt-6.1-nano", "GPT-6.1 nano", 400_000, 64_000, reasoning=True, variants=_LMH),
        _m("gpt-6.1-codex", "GPT-6.1 Codex", 1_000_000, 128_000, reasoning=True, variants=_LMH),
    ],
    "gemini": [
        _m("gemini-3-pro", "Gemini 3 Pro", 1_000_000, 65_536, reasoning=True, variants=["low", "high"]),
        _m("gemini-3-flash", "Gemini 3 Flash", 1_000_000, 65_536, reasoning=True, variants=_LMH),
        _m("gemini-3-flash-lite", "Gemini 3 Flash Lite", 1_000_000, 65_536, reasoning=True, variants=_LMH),
        _m("gemini-2.5-pro", "Gemini 2.5 Pro", 1_048_576, 65_536, reasoning=True, variants=_LHM),
        _m("gemini-2.5-flash", "Gemini 2.5 Flash", 1_048_576, 65_536, reasoning=True, variants=_LHM),
    ],
    "deepseek": [
        _m("deepseek-chat", "DeepSeek Chat", 128_000, 8_192, image=False),
        _m("deepseek-reasoner", "DeepSeek Reasoner", 128_000, 65_536, reasoning=True, image=False),
    ],
}


# ---- heuristics for ids we only know by name ----------------------------------------------

# Longest/most specific substring wins; everything else falls back to 128k.
_CONTEXT_TABLE: list[tuple[str, int]] = [
    ("k3.1", 1_000_000), ("k3-256k", 256_000), ("k3", 128_000), ("kimi-k2.5", 256_000), ("kimi-k2", 256_000),
    ("glm-5", 200_000), ("glm-4.6", 200_000), ("glm-4.5", 128_000),
    ("claude", 200_000),
    ("gpt-6", 1_000_000), ("gpt-5", 400_000), ("gpt-4.1", 1_000_000), ("gpt-4o", 128_000),
    ("o4-", 200_000), ("o3", 200_000), ("o1", 200_000),
    ("gemini", 1_000_000),
    ("deepseek", 128_000),
    ("grok-4", 256_000), ("grok-3", 131_072),
    ("llama-4", 1_000_000), ("llama-3.3", 128_000), ("llama-3.1", 128_000),
    ("qwen3", 128_000), ("qwen2.5", 128_000),
    ("mistral-large", 128_000), ("codestral", 256_000), ("devstral", 256_000), ("magistral", 128_000),
    ("sonar", 128_000),
]

_REASONING_HINTS = ("k3", "k2.5", "thinking", "reason", "glm-5", "glm-4.5", "glm-4.6", "claude", "gpt-5", "gpt-6",
                    "o1", "o3", "o4-", "gemini-2.5", "gemini-3", "grok-4", "magistral", "qwq", "r1", "-think")
_NON_REASONING_HINTS = ("gpt-4o", "gpt-4.1", "deepseek-chat", "instruct", "embed", "whisper", "tts", "dall-e", "moderation")
_IMAGE_HINTS = ("gpt-4o", "gpt-4.1", "gpt-5", "gpt-6", "o3", "o4-", "claude", "gemini", "k3", "k2.5", "kimi-vl", "-vl", "vision",
                "pixtral", "llava", "glm-4.5v", "glm-4.6v", "glm-5.3v", "grok-4", "llama-4", "qwen3-vl", "qwen2.5-vl")
_NO_TOOLS_HINTS = ("sonar", "embed", "whisper", "tts", "dall-e", "moderation", "rerank")


def context_for(model_id: str) -> int:
    key = model_id.lower()
    best = 0
    size = 128_000
    for needle, ctx in _CONTEXT_TABLE:
        if needle in key and len(needle) > best:
            best, size = len(needle), ctx
    return size


def is_reasoning(model_id: str) -> bool:
    key = model_id.lower()
    if any(h in key for h in _NON_REASONING_HINTS):
        return False
    return any(h in key for h in _REASONING_HINTS)


def supports_images(model_id: str) -> bool:
    key = model_id.lower()
    return any(h in key for h in _IMAGE_HINTS)


def supports_tools(model_id: str) -> bool:
    key = model_id.lower()
    return not any(h in key for h in _NO_TOOLS_HINTS)


def default_variants(model_id: str, kind: str) -> list[str]:
    if not is_reasoning(model_id):
        return []
    key = model_id.lower()
    if kind == "anthropic" or kind == "gemini" or "k3" in key or "kimi" in key:
        return list(_LHM)
    if "glm" in key:
        return ["high"]
    return list(_LMH)


def pretty_name(model_id: str) -> str:
    """``gpt-6.1-mini`` → ``GPT-6.1 Mini``, ``moonshotai/kimi-k3`` → ``Kimi K3``."""
    tail = model_id.rsplit("/", 1)[-1]
    words = []
    for part in tail.replace("_", "-").split("-"):
        low = part.lower()
        if low in ("gpt", "glm", "llm", "vl", "ai"):
            words.append(low.upper())
        elif low.startswith("gpt"):
            words.append("GPT" + part[3:])
        elif low.startswith("glm"):
            words.append("GLM" + part[3:])
        elif low in ("k2", "k3", "k2.5", "k3.1", "o1", "o3", "o4", "r1", "v3", "v3.1", "v3.2"):
            words.append(part.upper())
        elif part[:1].isdigit():
            if words and words[-1].isupper() and words[-1].isalpha():  # "GPT" + "6.1" → "GPT-6.1"
                words[-1] += "-" + part
            else:
                words.append(part)
        else:
            words.append(part[:1].upper() + part[1:])
    return " ".join(w for w in words if w) or model_id


def guess_model(model_id: str, kind: str, name: str = "", context: int | None = None, output: int | None = None) -> ModelInfo:
    reasoning = is_reasoning(model_id)
    return ModelInfo(
        id=model_id, name=name or pretty_name(model_id), context=context or context_for(model_id),
        output=output or 16_384, tools=supports_tools(model_id), reasoning=reasoning,
        variants=default_variants(model_id, kind) if reasoning else [],
        input=["text", "image"] if supports_images(model_id) else ["text"],
    )


def static_models(config: ProviderConfig) -> dict[str, ModelInfo]:
    """Static metadata by id: the config's own list first, then the catalog's."""
    out = {m.id: m for m in STATIC_MODELS.get(config.id, [])}
    out.update({m.id: m for m in config.models})
    return out


def merge_static(config: ProviderConfig, fetched: list[ModelInfo]) -> list[ModelInfo]:
    """Prefer hand-written metadata over guessed metadata; keep static models the server did not list."""
    known = static_models(config)
    out: list[ModelInfo] = []
    seen: set[str] = set()
    for m in fetched:
        seen.add(m.id)
        out.append(known.get(m.id, m))
    out.extend(m for mid, m in known.items() if mid not in seen)
    return out


def config_from_catalog(provider_id: str, api_key: str = "", base_url: str | None = None) -> ProviderConfig:
    entry = KNOWN[provider_id]
    return ProviderConfig(
        id=provider_id, name=entry["name"], kind=entry["kind"], base_url=base_url or entry["base_url"], api_key=api_key,
        headers=dict(entry.get("headers", {})), models=list(STATIC_MODELS.get(provider_id, [])),
        fetch_models=entry.get("fetch_models", True), extra=dict(entry.get("extra", {})),
    )


def make_provider(config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None) -> Provider:
    from afh.engine.providers.anthropic import AnthropicProvider
    from afh.engine.providers.gemini import GeminiProvider
    from afh.engine.providers.openai_compat import OpenAICompatProvider

    if config.kind == "anthropic":
        return AnthropicProvider(config, transport=transport)
    if config.kind == "gemini":
        return GeminiProvider(config, transport=transport)
    if config.kind == "openai":
        return OpenAICompatProvider(config, transport=transport)
    raise ValueError(f"Unknown provider kind: {config.kind!r}")
