"""Model facts from models.dev: context window, output limit, effort levels, input modalities
(image, video, audio, PDF) and prices, for thousands of models from every major provider.

AFH ships a trimmed snapshot (``data/models_dev.json``) so it is right offline, and refreshes it
from https://models.dev/api.json at most once a day into ``~/.afh/models-dev.json``. Facts here
beat AFH's own static list and the guesses made from a model's name; a value the user typed in
Settings → Models beats everything.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .. import store
from .types import ModelInfo

log = logging.getLogger("afh.modelsdev")

URL = "https://models.dev/api.json"
BUNDLED = Path(__file__).resolve().parent / "data" / "models_dev.json"
MAX_AGE = 24 * 3600

# AFH catalog id -> models.dev provider id(s), most specific first.
PROVIDER_MAP: dict[str, list[str]] = {
    "kimi": ["kimi-code-plan-global", "moonshotai"], "moonshot": ["moonshotai"], "zai": ["zai", "zhipuai"],
    "zai-coding": ["zai-coding-plan", "zai"], "openai": ["openai"], "anthropic": ["anthropic"], "gemini": ["google"],
    "deepseek": ["deepseek"], "groq": ["groq"], "openrouter": ["openrouter"], "mistral": ["mistral"], "xai": ["xai"],
    "together": ["togetherai"], "fireworks": ["fireworks-ai"], "cerebras": ["cerebras"], "perplexity": ["perplexity"],
    # ids OpenCode used, for migrated providers
    "kimi-code-plan-global": ["kimi-code-plan-global"], "kimi-code-plan": ["kimi-code-plan-cn", "moonshotai-cn"], "zai-coding-plan": ["zai-coding-plan"],
}

_data: dict | None = None
_by_id: dict[str, list[tuple[str, dict]]] | None = None


def cache_path() -> Path:
    return store.AFH_DIR / "models-dev.json"


def trim(raw: dict) -> dict:
    """Keep only what AFH uses (the full catalog is ~6 MB)."""
    out: dict = {}
    for pid, p in (raw or {}).items():
        if not isinstance(p, dict):
            continue
        models = {}
        for mid, m in (p.get("models") or {}).items():
            if not isinstance(m, dict):
                continue
            limit = m.get("limit") or {}
            efforts: list[str] = []
            for opt in m.get("reasoning_options") or []:
                if isinstance(opt, dict) and opt.get("type") == "effort":
                    efforts = [str(v) for v in opt.get("values") or []]
            cost = m.get("cost") or {}
            entry = {"name": m.get("name") or mid, "context": limit.get("context"), "output": limit.get("output"),
                     "reasoning": bool(m.get("reasoning")), "efforts": efforts, "tools": m.get("tool_call", True),
                     "input": (m.get("modalities") or {}).get("input") or ["text"], "canonical": m.get("canonical_model_id")}
            if cost:
                entry["cost"] = {k2: cost[k1] for k1, k2 in (("input", "input"), ("output", "output"), ("cache_read", "cacheRead"), ("cache_write", "cacheWrite")) if isinstance(cost.get(k1), (int, float))}
            models[mid] = entry
        out[pid] = {"name": p.get("name"), "api": p.get("api"), "npm": p.get("npm"), "env": list(p.get("env") or []), "doc": p.get("doc"), "models": models}
    return out


def load() -> dict:
    global _data, _by_id
    if _data is None:
        for path in (cache_path(), BUNDLED):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data and all("env" in p for p in list(data.values())[:5]):  # older caches lack provider env/npm
                _data = data
                break
        _data = _data or {}
        _by_id = None
    return _data


def _index() -> dict[str, list[tuple[str, dict]]]:
    global _by_id
    if _by_id is None:
        _by_id = {}
        for pid, p in load().items():
            for mid, m in p.get("models", {}).items():
                _by_id.setdefault(mid.lower(), []).append((pid, m))
    return _by_id


async def refresh(force: bool = False) -> bool:
    """Download a fresh catalog when the cached one is a day old (or `force`). True when it changed."""
    global _data, _by_id
    path = cache_path()
    try:
        if not force and path.is_file() and time.time() - path.stat().st_mtime < MAX_AGE:
            return False
    except OSError:
        pass
    try:
        import httpx

        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            resp = await client.get(URL)
        resp.raise_for_status()
        data = trim(resp.json())
        if len(data) < 10:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        _data, _by_id = data, None
        return True
    except Exception as err:  # offline, blocked, changed format: keep what we have
        log.info("models.dev refresh skipped: %s", err)
        return False


def _providers_for(pid: str, catalog: str | None) -> list[str]:
    """models.dev ids for a provider; a catalog id AFH has no mapping for is a models.dev id itself."""
    out: list[str] = []
    for key in (catalog, pid):
        for dev in PROVIDER_MAP.get(key or "") or ([key] if key and key in load() else []):
            if dev not in out:
                out.append(dev)
    return out


def lookup(pid: str, catalog: str | None, model_id: str) -> dict | None:
    """Facts for one model: from the provider's own entry when models.dev has it, else the model's
    canonical maker, else any provider listing the same id."""
    data = load()
    key = model_id.lower()
    for dev_pid in _providers_for(pid, catalog):
        models = data.get(dev_pid, {}).get("models", {})
        for mid, m in models.items():
            if mid.lower() == key:
                return m
    hits = _index().get(key) or _index().get(key.rsplit("/", 1)[-1]) or []
    if not hits:
        return None
    for dev_pid, m in hits:  # the maker's own listing first
        if (m.get("canonical") or "").split("/", 1)[0] == dev_pid:
            return m
    return hits[0][1]


def provider_models(pid: str, catalog: str | None) -> list[ModelInfo]:
    """Every model models.dev lists for this provider, as ModelInfo."""
    for dev_pid in _providers_for(pid, catalog):
        models = load().get(dev_pid, {}).get("models", {})
        if models:
            return [to_model(mid, m) for mid, m in models.items() if m.get("tools", True) is not False]
    return []


def to_model(mid: str, m: dict) -> ModelInfo:
    efforts = [e for e in m.get("efforts") or [] if e]
    return ModelInfo(id=mid, name=m.get("name") or mid, context=int(m.get("context") or 128_000), output=int(m.get("output") or 16_384),
                     tools=m.get("tools", True) is not False, reasoning=bool(m.get("reasoning")), variants=efforts,
                     input=list(m.get("input") or ["text"]), cost=dict(m["cost"]) if m.get("cost") else None)


def enrich(model: ModelInfo, facts: dict | None) -> ModelInfo:
    """Overwrite guessed metadata with models.dev facts (the name stays the one the endpoint gave)."""
    if not facts:
        return model
    if facts.get("context"):
        model.context = int(facts["context"])
    if facts.get("output"):
        model.output = int(facts["output"])
    model.reasoning = bool(facts.get("reasoning"))
    if facts.get("efforts") is not None:
        model.variants = [e for e in facts["efforts"] if e]
    if facts.get("input"):
        model.input = list(facts["input"])
    if facts.get("tools") is False:
        model.tools = False
    if facts.get("cost") and not model.cost:
        model.cost = dict(facts["cost"])
    return model
