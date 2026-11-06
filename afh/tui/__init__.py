"""AFH full screen in the terminal. `afh` opens this; `afh --plain` and pipes keep the line chat."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def available() -> bool:
    """A real terminal, and a Textual that imports. Anything else falls back to the line chat."""
    if os.environ.get("TERM") == "dumb" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return True


def check() -> int:
    """`afh --tui-check`: the whole app starts and draws, without a terminal. CI runs this on Windows."""
    import asyncio
    import queue

    from pygments.lexers import get_lexer_by_name

    from . import picture
    from .app import AFH

    class Quiet:
        url, key, backend = "http://127.0.0.1:9", "", None

        def request(self, method: str, path: str, *rest: Any) -> Any:
            return {"models": [], "agents": [], "settings": {}} if path == "/api/bootstrap" else []

    async def go() -> None:
        app = AFH(Quiet(), SimpleNamespace(queue=queue.Queue()), str(Path.cwd()), home=Path(os.environ.get("AFH_HOME") or Path.home() / ".afh"))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(1)
            assert app.composer.box.has_focus
        assert get_lexer_by_name("python")  # a build without lexers would show code uncoloured and say nothing
        print("ok")

    picture.CELL = (10, 20)
    assert picture.film(12, 4, "#181616").frame(None)  # a build without Pillow would quietly lose the real mark
    picture.CELL = None

    asyncio.run(go())
    return 0


def run(opener: Any, a: Any) -> int:
    """Full screen at once: the app connects behind its own boot screen, not before it."""
    from . import picture
    from .app import AFH

    picture.probe()
    app = AFH(None, None, str(Path(getattr(a, "dir", None) or ".").resolve()), model=getattr(a, "model", None), agent=getattr(a, "agent", None),
              mode=getattr(a, "mode", None), thread=getattr(a, "thread", None), resume=bool(getattr(a, "resume", False)), opener=opener)
    try:
        app.run()
    finally:
        if app.client:
            app.client.close()
    return app.return_code or 0
