"""The UI is plain ES modules served as-is: a syntax error in one file blanks the whole app, so every
module is parsed with Node (as a module) before anything ships."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
MODULES = sorted((WEB / "js").glob("*.js"))


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_module_parses(module, tmp_path):
    copy = tmp_path / (module.stem + ".mjs")  # .mjs: parse as an ES module
    copy.write_text(module.read_text(encoding="utf-8"), encoding="utf-8")
    out = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_imports_point_at_real_exports():
    """`import { a, b } from "./x.js"` must name things x.js exports (a typo is a blank screen)."""
    exports: dict[str, set[str]] = {}
    for m in MODULES:
        text = m.read_text(encoding="utf-8")
        names = set(re.findall(r"^export (?:async )?(?:function|const|let|class) ([A-Za-z0-9_$]+)", text, re.M))
        exports[m.name] = names
    for m in MODULES:
        for names, target in re.findall(r"import \{([^}]*)\} from \"\./([a-z0-9-]+\.js)\"", m.read_text(encoding="utf-8")):
            for name in [n.strip().split(" as ")[0] for n in names.split(",") if n.strip()]:
                assert name in exports[target], f"{m.name} imports {name!r} from {target}, which does not export it"


def test_icons_used_exist():
    ui = (WEB / "js" / "ui.js").read_text(encoding="utf-8")
    known = set(re.findall(r"^\s+\"?([a-z-]+)\"?: P\(|^\s+\"?([a-z-]+)\"?: '<svg", ui, re.M))
    known = {a or b for a, b in known}
    used = set()
    for m in MODULES:
        used |= set(re.findall(r"\bico\(\"([a-z-]+)\"", m.read_text(encoding="utf-8")))
        used |= set(re.findall(r"\bicon\(\"([a-z-]+)\"", m.read_text(encoding="utf-8")))
    used |= set(re.findall(r'data-icon="([a-z-]+)"', (WEB / "index.html").read_text(encoding="utf-8")))
    assert not (used - known), f"unknown icons: {sorted(used - known)}"


def test_main_does_not_use_ctx_before_it_exists():
    """A top-level `ctx.x = …` above `export const ctx` throws at load time and leaves the app on its boot screen."""
    lines = (WEB / "js" / "main.js").read_text(encoding="utf-8").splitlines()
    defined = next(i for i, l in enumerate(lines) if l.startswith("export const ctx"))
    early = [i + 1 for i, l in enumerate(lines[:defined]) if re.match(r"^ctx\.\w+\s*=", l)]
    assert not early, f"main.js lines {early} use ctx before line {defined + 1} defines it"
