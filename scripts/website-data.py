"""Write website/data/providers.json: every provider AFH knows, for the website's Models page.

    python scripts/website-data.py

Run it when the provider catalog or the bundled models.dev snapshot changes.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AFH_HOME", tempfile.mkdtemp(prefix="afh-site-"))  # never read the user's own setup

from afh.engine import modelsdev  # noqa: E402
from afh.engine.providers import catalog  # noqa: E402

LOCAL = ("localhost", "127.0.0.1")
out = []
for pid, e in catalog.entries().items():
    models = modelsdev.provider_models(pid, pid)
    url = e.get("base_url") or ""
    out.append({
        "id": pid,
        "name": e.get("name") or pid,
        "kind": e.get("kind"),
        "models": len(models),
        "reasoning": sum(1 for m in models if m.variants),
        "vision": sum(1 for m in models if "image" in (m.input or [])),
        "login": bool(e.get("login")),
        "local": any(h in url for h in LOCAL),
        "docs": e.get("docs") or "",
        "featured": e.get("source") == "afh",
    })

dest = ROOT / "website" / "data" / "providers.json"
dest.parent.mkdir(exist_ok=True)
dest.write_text(json.dumps({"providers": out}, separators=(",", ":")), encoding="utf-8")
print(f"{len(out)} providers, {sum(p['models'] for p in out)} models -> {dest.relative_to(ROOT)}")
