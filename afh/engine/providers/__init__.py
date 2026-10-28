"""LLM provider adapters for the AFH engine.

Three wire protocols cover every provider the catalog knows: OpenAI-compatible chat
completions, Anthropic Messages and Google Gemini. ``make_provider`` picks the adapter by
``ProviderConfig.kind``; each adapter implements the ``Provider`` protocol from ``types.py``.
"""

from afh.engine.providers.anthropic import AnthropicProvider
from afh.engine.providers.catalog import KNOWN, OPENCODE_TO_AFH, STATIC_MODELS, config_from_catalog, context_for, make_provider
from afh.engine.providers.gemini import GeminiProvider
from afh.engine.providers.openai_compat import OpenAICompatProvider
from afh.engine.providers.sse import ProviderError, iter_sse

__all__ = [
    "AnthropicProvider", "GeminiProvider", "OpenAICompatProvider", "ProviderError",
    "KNOWN", "OPENCODE_TO_AFH", "STATIC_MODELS", "config_from_catalog", "context_for", "iter_sse", "make_provider",
]
