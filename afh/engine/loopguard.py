"""Notice when the model is going round in circles: the same words, or the same tool call with the same
input, step after step. The first time AFH tells the model to change course; if it keeps repeating
the same thing after that, the run stops so it doesn't burn the user's plan for nothing.

Waiting on a background job (only the jobs, todo or goal tools in a step) never counts: checking the
same job again is how waiting looks. A step that changes a file starts the count again, so the usual
"edit, run the tests, edit, run the tests" is never taken for a loop."""

from __future__ import annotations

import json
import re
from collections import deque

WINDOW = 8  # steps looked back on
NOTE_AT = 3  # the same thing this many times within the window: tell the model
STOP_AT = 3  # after the note, the same thing this many more times: stop the run
MIN_TEXT = 24  # shorter words ("Let me check.") are too common to mean anything
WAITING = {"jobs", "todo", "goal"}
CHANGES = {"write", "edit", "patch"}  # after a file changes, running the same check again is how fixing looks
# Driving a page or the screen: pressing the same key or scrolling again is normal, so those calls never count.
SCREEN = {"browser", "chrome", "computer"}
MOVES = {"press", "key", "scroll", "wait", "screenshot", "zoom", "hover", "back", "forward", "reload", "type_keys"}

NOTE = ("[AFH: you have now done the same thing {n} times in your last few steps: \"{what}\". Doing it again will not "
        "give a different result. Stop retrying it. Either try a clearly different approach, or stop and tell the "
        "user plainly what is blocking you and what you need from them.]")


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip(" .:!")


def _call(name: str, inp: object) -> str:
    try:
        return name + " " + json.dumps(inp, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return name + " " + str(inp)


class LoopGuard:
    def __init__(self) -> None:
        self.recent: deque[set[str]] = deque(maxlen=WINDOW)
        self.noted: str | None = None  # what the note was about
        self.after_note = 0  # repeats of it since the note

    def step(self, text: str, calls: list[tuple[str, object]]) -> tuple[str, str] | None:
        """Record one finished step. Returns ("note", text for the model), ("stop", what) or None."""
        if calls and all(name in WAITING for name, _ in calls):
            return None
        if any(name in CHANGES for name, _ in calls):
            self.recent.clear()
            self.noted, self.after_note = None, 0
            return None
        keys: dict[str, str] = {}  # key -> how to name it to the model
        words = _words(text)
        if len(words) >= MIN_TEXT:
            keys["t:" + words] = text.strip().splitlines()[0][:120]
        if calls and not all(n in SCREEN and isinstance(i, dict) and i.get("action") in MOVES for n, i in calls):
            sig = " | ".join(_call(n, i) for n, i in calls)
            keys["c:" + sig] = sig[:120]
        if not keys:
            return None
        if self.noted is not None:
            if self.noted in keys:
                self.after_note += 1
                if self.after_note >= STOP_AT:
                    return ("stop", keys[self.noted])
            self.recent.append(set(keys))
            return None
        for key, label in keys.items():
            n = 1 + sum(key in past for past in self.recent)
            if n >= NOTE_AT:
                self.noted, self.after_note = key, 0
                self.recent.append(set(keys))
                return ("note", NOTE.format(n=n, what=label))
        self.recent.append(set(keys))
        return None
