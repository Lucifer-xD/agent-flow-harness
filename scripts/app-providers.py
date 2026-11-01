"""Write app/assets/providers.json: every provider the desktop offers, for the phone app.

    python scripts/app-providers.py

Run it when the provider catalog or the bundled models.dev snapshot changes, so the phone lists the
same providers (and sign-ins) as Settings → Models on the desktop.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AFH_HOME", tempfile.mkdtemp(prefix="afh-app-"))  # never read the user's own setup

from afh.engine import modelsdev  # noqa: E402
from afh.engine.providers import catalog  # noqa: E402

LOCAL = ("localhost", "127.0.0.1")
WIRES = {"openai", "anthropic", "gemini", "responses"}
out = []
for pid, e in catalog.entries().items():
    if e.get("kind") not in WIRES:
        continue
    static = catalog.STATIC_MODELS.get(pid) or []
    models = [m.id for m in static] or [m.id for m in modelsdev.provider_models(pid, pid) if not m.hidden][:12]
    url = e.get("base_url") or ""
    extra = e.get("extra") or {}
    item = {
        "id": pid,
        "name": e.get("name") or pid,
        "wire": e["kind"],
        "base": url,
        "docs": e.get("docs") or "",
        "featured": e.get("source") == "afh",
        "models": models,
    }
    if e.get("login"):
        item["login"] = e["login"]
    if e.get("login_only"):
        item["loginOnly"] = True
    if e.get("needs_key") is False:
        item["noKey"] = True
    if any(h in url for h in LOCAL) or e.get("custom_url"):
        item["local"] = True
    if e.get("fetch_models") is False:
        item["noFetch"] = True
    if e.get("params"):
        item["params"] = [{"name": p["name"], "label": p["label"], "default": p.get("default") or ""} for p in e["params"]]
    if e.get("hint"):
        item["hint"] = e["hint"]
    if e.get("headers"):
        item["headers"] = e["headers"]
    if "auth_header" in extra:
        item["authHeader"] = extra["auth_header"]
        item["authPrefix"] = extra.get("auth_prefix", "Bearer ")
    out.append(item)

dest = ROOT / "app" / "assets" / "providers.json"
dest.parent.mkdir(exist_ok=True)
dest.write_text(json.dumps({"providers": out}, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
print(f"{len(out)} providers ({sum(1 for p in out if p['featured'])} featured) -> {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")
