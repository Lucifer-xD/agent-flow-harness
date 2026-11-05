"""AFH full screen in the terminal. `afh` opens this; `afh --plain` and pipes keep the line chat."""
from __future__ import annotations

import os
import sys
from pathlib import Path
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


def run(client: Any, a: Any) -> int:
    from ..cli import Events
    from .app import AFH

    app = AFH(client, Events(client), str(Path(getattr(a, "dir", None) or ".").resolve()), model=getattr(a, "model", None), agent=getattr(a, "agent", None),
              mode=getattr(a, "mode", None), thread=getattr(a, "thread", None), resume=bool(getattr(a, "resume", False)))
    app.run()
    return app.return_code or 0
